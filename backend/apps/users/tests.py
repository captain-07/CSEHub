from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import RequestFactory, TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed

from .authentication import SupabaseJWTAuthentication
from .models import User


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
        self.assertEqual(updated.username, 'changed')

    @patch('apps.users.authentication._get_jwks_client')
    def test_missing_or_invalid_tokens_are_rejected_safely(self, get_client):
        self.assertIsNone(SupabaseJWTAuthentication().authenticate(self.factory.get('/api/me/')))
        get_client.return_value.get_signing_key_from_jwt.side_effect = ValueError('provider detail')
        with self.assertRaises(AuthenticationFailed) as caught:
            SupabaseJWTAuthentication().authenticate(self.request('malformed'))
        self.assertNotIn('malformed', str(caught.exception))
