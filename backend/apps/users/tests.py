from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase

from .authentication import SupabaseJWTAuthentication



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
