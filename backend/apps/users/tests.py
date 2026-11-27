from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase

from .authentication import SupabaseJWTAuthentication
from .models import UserSession



@override_settings(SUPABASE_URL='https://project.supabase.co')
class SupabaseAuthenticationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.uid = str(uuid4())

    def request(self, token='valid-token'):
        return self.factory.get('/api/me/', HTTP_AUTHORIZATION=f'Bearer {token}')

    @patch('apps.users.authentication.jwt.decode')
    @patch('apps.users.authentication._get_jwks_client')
    def test_valid_token_creates_and_updates_user(self, get_client, decode):
        get_client.return_value.get_signing_key_from_jwt.return_value = Mock(key='key')
        decode.return_value = {
            'sub': self.uid, 'email': 'first@example.com',
            'user_metadata': {'preferred_username': 'first', 'avatar_url': 'https://example.com/a.png'},
        }
        user, token = SupabaseJWTAuthentication().authenticate(self.request())
        self.assertEqual(token, 'valid-token')
        self.assertEqual(user.email, 'first@example.com')

        decode.return_value = {
            'sub': self.uid, 'email': 'changed@example.com',
            'user_metadata': {'preferred_username': 'changed'},
        }
        updated, _ = SupabaseJWTAuthentication().authenticate(self.request())
        self.assertEqual(updated.email, 'changed@example.com')
        self.assertEqual(updated.username, 'first')

    @patch('apps.users.authentication.jwt.decode')
    @patch('apps.users.authentication._get_jwks_client')
    def test_existing_email_without_uid_is_linked_not_duplicated(self, get_client, decode):
        """A createsuperuser/seed row must survive its first Google sign-in.

        Before the fix this raised a unique-constraint `IntegrityError` that the
        outer handler reported as an invalid token, locking the admin out.
        """
        existing = get_user_model().objects.create_user(
            # Mixed case on purpose: the token's email is lowercased, and the
            # lookup has to still find this row.
            email='Editor@Example.com', username='editor', is_staff=True, is_superuser=True,
        )
        get_client.return_value.get_signing_key_from_jwt.return_value = Mock(key='key')
        decode.return_value = {
            'sub': self.uid, 'email': 'editor@example.com',
            'user_metadata': {'full_name': 'Editor'},
        }

        user, _ = SupabaseJWTAuthentication().authenticate(self.request())

        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(str(user.supabase_uid), self.uid)
        self.assertEqual(
            get_user_model().objects.filter(email__iexact='editor@example.com').count(), 1
        )
        self.assertTrue(user.is_staff and user.is_superuser)
        # The hand-made profile is preserved rather than overwritten by defaults.
        self.assertEqual(user.username, 'editor')

    @patch('apps.users.authentication.jwt.decode')
    @patch('apps.users.authentication._get_jwks_client')
    def test_email_bound_to_another_identity_is_rejected(self, get_client, decode):
        get_user_model().objects.create_user(
            email='claimed@example.com', username='claimed',
            supabase_uid=uuid4(),
        )
        get_client.return_value.get_signing_key_from_jwt.return_value = Mock(key='key')
        decode.return_value = {'sub': self.uid, 'email': 'claimed@example.com'}

        with self.assertRaises(AuthenticationFailed) as caught:
            SupabaseJWTAuthentication().authenticate(self.request())

        self.assertIn('already linked', str(caught.exception))

    @patch('apps.users.authentication._get_jwks_client')
    def test_missing_or_invalid_tokens_are_rejected_safely(self, get_client):
        self.assertIsNone(SupabaseJWTAuthentication().authenticate(self.factory.get('/api/me/')))
        get_client.return_value.get_signing_key_from_jwt.side_effect = ValueError('provider detail')
        with self.assertRaises(AuthenticationFailed) as caught:
            SupabaseJWTAuthentication().authenticate(self.request('malformed'))
        self.assertNotIn('malformed', str(caught.exception))


class MeViewTests(APITestCase):
    """`GET /api/me/` is the only thing the frontend trusts for `is_admin`."""

    def setUp(self):
        self.reader = get_user_model().objects.create_user(
            email='reader@example.com', username='reader'
        )
        self.editor = get_user_model().objects.create_user(
            email='editor@example.com', username='editor', is_staff=True
        )

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get('/api/me/').status_code, 401)

    def test_me_reports_is_admin_from_the_server_side_flag(self):
        self.client.force_authenticate(self.reader)
        self.assertFalse(self.client.get('/api/me/').data['is_admin'])
        self.client.force_authenticate(self.editor)
        self.assertTrue(self.client.get('/api/me/').data['is_admin'])

    def test_a_client_cannot_grant_itself_admin(self):
        self.client.force_authenticate(self.reader)
        response = self.client.patch(
            '/api/me/',
            {'is_admin': True, 'is_staff': True, 'email': 'attacker@example.com'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.is_staff, 'is_staff must not be client-writable')
        self.assertEqual(self.reader.email, 'reader@example.com', 'email must not be client-writable')
        self.assertFalse(response.data['is_admin'])

    def test_display_fields_are_editable(self):
        self.client.force_authenticate(self.reader)
        response = self.client.patch(
            '/api/me/',
            {'display_name': 'Reader One', 'avatar_url': 'https://example.com/a.png'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.display_name, 'Reader One')
        self.assertEqual(self.reader.avatar_url, 'https://example.com/a.png')


@override_settings(SESSION_ACTIVE_WINDOW_MINUTES=30)
class LoginSessionTests(APITestCase):
    """The login log: one row per Supabase session, not per request."""

    def setUp(self):
        self.reader = get_user_model().objects.create_user(
            email='reader@example.com', username='reader'
        )
        self.admin = get_user_model().objects.create_user(
            email='admin@example.com', username='admin', is_staff=True
        )

    def ping(self, key='session-one'):
        return self.client.post(
            '/api/auth/session/', {'session_key': key}, format='json'
        )

    def test_a_session_is_recorded_once_and_later_pings_refresh_it(self):
        self.client.force_authenticate(self.reader)

        first = self.ping()
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data['created'])
        session = UserSession.objects.get()
        self.assertEqual(session.user, self.reader)

        # Age the row so the refresh is visible rather than a same-instant tie.
        session.last_seen_at = timezone.now() - timedelta(minutes=5)
        session.save(update_fields=['last_seen_at'])

        second = self.ping()
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data['created'])
        self.assertEqual(UserSession.objects.count(), 1)
        session.refresh_from_db()
        self.assertGreater(session.last_seen_at, timezone.now() - timedelta(minutes=1))

    def test_logout_closes_the_session_and_a_late_ping_cannot_reopen_it(self):
        self.client.force_authenticate(self.reader)
        self.ping()

        ended = self.client.post(
            '/api/auth/session/logout/', {'session_key': 'session-one'}, format='json'
        )
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertTrue(ended.data['ended'])

        session = UserSession.objects.get()
        self.assertIsNotNone(session.logged_out_at)
        self.assertFalse(session.is_active)

        # A heartbeat that raced the sign-out must leave the row closed.
        self.ping()
        session.refresh_from_db()
        self.assertIsNotNone(session.logged_out_at)
        self.assertFalse(session.is_active)

    def test_a_session_key_cannot_be_claimed_by_another_account(self):
        self.client.force_authenticate(self.reader)
        self.ping('shared-key')

        other = get_user_model().objects.create_user(
            email='other@example.com', username='other'
        )
        self.client.force_authenticate(other)
        response = self.ping('shared-key')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserSession.objects.get().user, self.reader)

    def test_a_request_without_a_session_identifier_is_rejected(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post('/api/auth/session/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_silent_sessions_age_out_of_the_active_window(self):
        UserSession.objects.create(
            user=self.reader,
            session_key='stale',
            last_seen_at=timezone.now() - timedelta(minutes=31),
        )
        self.assertFalse(UserSession.objects.get(session_key='stale').is_active)

        self.client.force_authenticate(self.admin)
        summary = self.client.get('/api/auth/sessions/summary/')
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data['active'], 0)
        self.assertEqual(summary.data['total'], 1)

    def test_the_login_log_is_admin_only(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/auth/sessions/').status_code, 403)
        self.assertEqual(self.client.get('/api/auth/sessions/summary/').status_code, 403)

    def test_session_endpoints_require_authentication(self):
        self.assertEqual(
            self.client.post('/api/auth/session/', {}, format='json').status_code, 401
        )
        self.assertEqual(
            self.client.post('/api/auth/session/logout/', {}, format='json').status_code, 401
        )
        self.assertEqual(self.client.get('/api/auth/sessions/').status_code, 401)

    def test_admin_can_filter_active_and_ended_sessions(self):
        UserSession.objects.create(user=self.reader, session_key='live')
        UserSession.objects.create(
            user=self.reader,
            session_key='closed',
            logged_out_at=timezone.now(),
        )

        self.client.force_authenticate(self.admin)

        active = self.client.get('/api/auth/sessions/', {'status': 'active'})
        self.assertEqual(active.status_code, 200, active.data)
        self.assertEqual(active.data['count'], 1)
        self.assertTrue(active.data['results'][0]['is_active'])
        self.assertEqual(active.data['results'][0]['email'], 'reader@example.com')

        ended = self.client.get('/api/auth/sessions/', {'status': 'ended'})
        self.assertEqual(ended.status_code, 200, ended.data)
        self.assertEqual(ended.data['count'], 1)
        self.assertFalse(ended.data['results'][0]['is_active'])

    def test_search_matches_the_user(self):
        UserSession.objects.create(user=self.reader, session_key='one')
        self.client.force_authenticate(self.admin)

        response = self.client.get('/api/auth/sessions/', {'search': 'reader@'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)

        miss = self.client.get('/api/auth/sessions/', {'search': 'nobody@'})
        self.assertEqual(miss.data['count'], 0)

    def test_today_and_total_counts_are_reported(self):
        UserSession.objects.create(user=self.reader, session_key='today')
        old = UserSession.objects.create(user=self.reader, session_key='old')
        # `logged_in_at` has a default, so set it explicitly for the historical row.
        UserSession.objects.filter(pk=old.pk).update(
            logged_in_at=timezone.now() - timedelta(days=2)
        )

        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/auth/sessions/summary/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['logins_today'], 1)
        self.assertEqual(response.data['active_window_minutes'], 30)


@override_settings(SUPABASE_URL='https://project.supabase.co')
class UserBanTests(APITestCase):
    """Banning is a local decision, enforced by the authentication class."""

    def setUp(self):
        self.reader = get_user_model().objects.create_user(
            email='reader@example.com', username='reader'
        )
        self.admin = get_user_model().objects.create_user(
            email='admin@example.com', username='admin', is_staff=True
        )

    def ban(self, user_id=None, reason=''):
        return self.client.post(
            f'/api/auth/users/{user_id or self.reader.pk}/ban/',
            {'reason': reason},
            format='json',
        )

    def test_an_admin_can_ban_a_reader_and_open_sessions_close(self):
        session = UserSession.objects.create(user=self.reader, session_key='live')
        self.client.force_authenticate(self.admin)

        response = self.ban(reason='spam comments')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['is_banned'])
        self.assertEqual(response.data['ban_reason'], 'spam comments')
        self.assertEqual(response.data['ended_sessions'], 1)

        self.reader.refresh_from_db()
        self.assertTrue(self.reader.is_banned)
        self.assertIsNotNone(self.reader.banned_at)
        session.refresh_from_db()
        self.assertIsNotNone(session.logged_out_at)
        self.assertFalse(session.is_active)

    @patch('apps.users.authentication.jwt.decode')
    @patch('apps.users.authentication._get_jwks_client')
    def test_a_banned_user_is_refused_even_with_a_valid_token(self, get_client, decode):
        self.reader.supabase_uid = uuid4()
        self.reader.is_banned = True
        self.reader.save(update_fields=['supabase_uid', 'is_banned'])
        get_client.return_value.get_signing_key_from_jwt.return_value = Mock(key='key')
        decode.return_value = {'sub': str(self.reader.supabase_uid), 'email': self.reader.email}

        request = RequestFactory().get('/api/me/', HTTP_AUTHORIZATION='Bearer token')
        with self.assertRaises(AuthenticationFailed) as caught:
            SupabaseJWTAuthentication().authenticate(request)

        self.assertIn('banned', str(caught.exception))

    def test_an_admin_can_unban_a_reader(self):
        self.reader.ban('first offence')
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            f'/api/auth/users/{self.reader.pk}/unban/', {}, format='json'
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_banned'])
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.is_banned)
        self.assertIsNone(self.reader.banned_at)
        self.assertEqual(self.reader.ban_reason, '')

    def test_an_admin_cannot_ban_their_own_account(self):
        self.client.force_authenticate(self.admin)
        response = self.ban(self.admin.pk)
        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_banned)

    def test_staff_accounts_cannot_be_banned_from_the_panel(self):
        other_staff = get_user_model().objects.create_user(
            email='other-admin@example.com', username='other-admin', is_staff=True
        )
        self.client.force_authenticate(self.admin)

        response = self.ban(other_staff.pk)

        self.assertEqual(response.status_code, 400)
        other_staff.refresh_from_db()
        self.assertFalse(other_staff.is_banned)

    def test_a_reader_cannot_ban_anyone(self):
        self.client.force_authenticate(self.reader)
        response = self.ban(self.admin.pk)
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_banned)

    def test_banning_twice_is_a_no_op(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.ban().status_code, 200)
        second = self.ban()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['ended_sessions'], 0)

    def test_the_account_list_is_admin_only_and_filterable(self):
        self.reader.ban('spam')
        self.client.force_authenticate(self.admin)

        banned = self.client.get('/api/auth/users/', {'status': 'banned'})
        self.assertEqual(banned.status_code, 200, banned.data)
        self.assertEqual(banned.data['count'], 1)
        self.assertEqual(banned.data['results'][0]['email'], 'reader@example.com')
        self.assertTrue(banned.data['results'][0]['is_banned'])

        active = self.client.get('/api/auth/users/', {'status': 'active'})
        self.assertEqual(active.data['count'], 1)
        self.assertEqual(active.data['results'][0]['email'], 'admin@example.com')

        searched = self.client.get('/api/auth/users/', {'search': 'reader@'})
        self.assertEqual(searched.data['count'], 1)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/auth/users/').status_code, 403)

    def test_the_account_summary_counts_banned_and_staff(self):
        self.reader.ban('spam')
        self.client.force_authenticate(self.admin)

        response = self.client.get('/api/auth/users/summary/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['banned'], 1)
        self.assertEqual(response.data['admins'], 1)
