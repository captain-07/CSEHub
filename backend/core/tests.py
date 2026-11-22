"""The project-level endpoints: today, the health check."""

from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase


class HealthCheckTests(TestCase):
    def test_a_healthy_process_says_ok(self):
        response = self.client.get('/healthz/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_the_check_is_the_connection_not_the_schema(self):
        with patch('core.views.connection') as connection:
            cursor = connection.cursor.return_value.__enter__.return_value

            self.client.get('/healthz/')

        cursor.execute.assert_called_once_with('SELECT 1')

    def test_an_unreachable_database_is_a_degraded_answer(self):
        with patch('core.views.connection') as connection:
            connection.cursor.side_effect = DatabaseError('down')

            response = self.client.get('/healthz/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'degraded'})

    def test_the_answer_is_never_cached(self):
        """A cached 200 would hide an outage from the monitor that asked."""
        response = self.client.get('/healthz/')

        cache_control = response.headers.get('Cache-Control', '')
        self.assertIn('no-store', cache_control)

    def test_it_is_read_only(self):
        response = self.client.post('/healthz/')

        self.assertEqual(response.status_code, 405)
