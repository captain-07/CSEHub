"""Checkout, verification and the webhook.

Nothing here talks to Razorpay: `apps.payments.gateway` is the single seam, and
every test patches it. The signature arithmetic in the webhook tests is real
(HMAC-SHA256 over the raw body), because that is the endpoint's only
authentication and a fake would not exercise it.
"""

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.articles.models import Article

from .access import can_read_article
from .gateway import PaymentGatewayError
from .models import PaymentEvent, Purchase

KEY_ID = 'rzp_test_key'
KEY_SECRET = 'api-secret'
WEBHOOK_SECRET = 'endpoint-secret'

BODY = {'blocks': [{'type': 'paragraph', 'data': {'text': 'The paid text.'}}]}

CONFIGURED = dict(
    RAZORPAY_KEY_ID=KEY_ID,
    RAZORPAY_KEY_SECRET=KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET,
)


@override_settings(**CONFIGURED)
class PaymentAPITestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user(
            email='author@example.com', username='author', password='password', is_staff=True
        )
        self.reader = User.objects.create_user(
            email='reader@example.com', username='reader', password='password'
        )
        self.paid = Article.objects.create(
            title='Paid article', slug='paid-article', content=BODY,
            is_published=True, author=self.author, is_paid=True,
            price=Decimal('149.00'),
        )

    def _purchase(self, status=Purchase.STATUS_CREATED, order_id='order_test_1', **kwargs):
        return Purchase.objects.create(
            user=kwargs.pop('user', self.reader),
            article=self.paid,
            status=status,
            amount_paise=14900,
            provider_order_id=order_id,
            **kwargs,
        )

    def _webhook(self, payload, event_id='evt_1', secret=WEBHOOK_SECRET, headers=True):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        extra = {}
        if headers:
            extra = {
                'HTTP_X_RAZORPAY_SIGNATURE': signature,
                'HTTP_X_RAZORPAY_EVENT_ID': event_id,
            }
        return self.client.post(
            '/api/payments/webhook/razorpay/',
            data=body,
            content_type='application/json',
            **extra,
        )


class CheckoutTests(PaymentAPITestCase):
    def test_checkout_requires_a_signed_in_reader(self):
        response = self.client.post(
            '/api/payments/checkout/', {'slug': 'paid-article'}, format='json'
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(Purchase.objects.exists())

    def test_checkout_states_the_amount_itself(self):
        """The request names the article; the server names the price."""
        self.client.force_authenticate(self.reader)
        with patch('apps.payments.gateway.create_order', return_value={'id': 'order_abc'}) as create:
            response = self.client.post(
                '/api/payments/checkout/', {'slug': 'paid-article'}, format='json'
            )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['amount'], 14900)
        self.assertEqual(response.data['currency'], 'INR')
        self.assertEqual(response.data['order_id'], 'order_abc')
        self.assertEqual(response.data['key_id'], KEY_ID)
        self.assertEqual(response.data['prefill']['email'], 'reader@example.com')
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount_paise'], 14900)

        purchase = Purchase.objects.get()
        self.assertEqual(purchase.user, self.reader)
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)
        self.assertEqual(purchase.provider_order_id, 'order_abc')
        self.assertTrue(purchase.receipt.startswith('csehub-'))
        self.assertLessEqual(len(purchase.receipt), 40)

    def test_a_client_supplied_amount_is_ignored(self):
        self.client.force_authenticate(self.reader)
        with patch('apps.payments.gateway.create_order', return_value={'id': 'order_abc'}) as create:
            self.client.post(
                '/api/payments/checkout/',
                {'slug': 'paid-article', 'amount': 1, 'price': 1},
                format='json',
            )
        self.assertEqual(create.call_args.kwargs['amount_paise'], 14900)

    def test_a_free_article_cannot_be_bought(self):
        Article.objects.create(
            title='Free', slug='free-article', content=BODY, is_published=True,
        )
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            '/api/payments/checkout/', {'slug': 'free-article'}, format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Purchase.objects.exists())

    def test_unowned_articles_cannot_be_bought(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            '/api/payments/checkout/', {'slug': 'no-such-article'}, format='json'
        )
        self.assertEqual(response.status_code, 404)

    def test_a_buyer_is_not_charged_twice(self):
        self._purchase(status=Purchase.STATUS_PAID)
        self.client.force_authenticate(self.reader)
        with patch('apps.payments.gateway.create_order') as create:
            response = self.client.post(
                '/api/payments/checkout/', {'slug': 'paid-article'}, format='json'
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['already_owned'])
        create.assert_not_called()
        self.assertEqual(Purchase.objects.count(), 1)

    def test_staff_are_never_charged(self):
        self.client.force_authenticate(self.author)
        with patch('apps.payments.gateway.create_order') as create:
            response = self.client.post(
                '/api/payments/checkout/', {'slug': 'paid-article'}, format='json'
            )
        self.assertTrue(response.data['already_owned'])
        create.assert_not_called()

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_checkout_says_so_when_payments_are_not_configured(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            '/api/payments/checkout/', {'slug': 'paid-article'}, format='json'
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn('not configured', response.data['detail'])
        self.assertFalse(Purchase.objects.exists())

    def test_a_provider_failure_closes_the_attempt_and_charges_nothing(self):
        self.client.force_authenticate(self.reader)
        with patch(
            'apps.payments.gateway.create_order',
            side_effect=PaymentGatewayError('The payment provider is temporarily unavailable.'),
        ):
            response = self.client.post(
                '/api/payments/checkout/', {'slug': 'paid-article'}, format='json'
            )

        self.assertEqual(response.status_code, 502)
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.status, Purchase.STATUS_FAILED)
        self.assertIsNone(purchase.provider_order_id)
        self.assertFalse(can_read_article(self.reader, self.paid))


class VerifyTests(PaymentAPITestCase):
    def _verify(self, order_id='order_test_1', payment_id='pay_1'):
        self.client.force_authenticate(self.reader)
        return self.client.post(
            '/api/payments/verify/',
            {
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': 'signed',
            },
            format='json',
        )

    def test_a_verified_payment_unlocks_the_article(self):
        purchase = self._purchase()
        with patch('apps.payments.gateway.verify_payment', return_value=True), \
                patch('apps.payments.gateway.fetch_payment', return_value={
                    'id': 'pay_1', 'order_id': 'order_test_1',
                    'amount': 14900, 'status': 'captured',
                }):
            response = self._verify()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'paid')
        self.assertTrue(response.data['has_access'])

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PAID)
        self.assertEqual(purchase.provider_payment_id, 'pay_1')
        self.assertIsNotNone(purchase.paid_at)

        detail = self.client.get('/api/articles/paid-article/')
        self.assertTrue(detail.data['has_access'])
        self.assertEqual(detail.data['content'], BODY)

    def test_a_bad_signature_unlocks_nothing(self):
        purchase = self._purchase()
        with patch('apps.payments.gateway.verify_payment', return_value=False):
            response = self._verify()

        self.assertEqual(response.status_code, 400)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)
        self.assertFalse(can_read_article(self.reader, self.paid))

    def test_verifying_twice_is_a_no_op(self):
        purchase = self._purchase()
        with patch('apps.payments.gateway.verify_payment', return_value=True), \
                patch('apps.payments.gateway.fetch_payment', return_value={
                    'order_id': 'order_test_1', 'amount': 14900, 'status': 'captured',
                }):
            self._verify()
            purchase.refresh_from_db()
            paid_at = purchase.paid_at
            second = self._verify()

        self.assertEqual(second.status_code, 200)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PAID)
        self.assertEqual(purchase.paid_at, paid_at)

    def test_another_readers_order_cannot_be_verified(self):
        other = get_user_model().objects.create_user(
            email='other@example.com', username='other', password='password'
        )
        self._purchase(user=other)
        with patch('apps.payments.gateway.verify_payment', return_value=True):
            response = self._verify()

        self.assertEqual(response.status_code, 404)

    def test_a_payment_for_the_wrong_amount_is_refused(self):
        purchase = self._purchase()
        with patch('apps.payments.gateway.verify_payment', return_value=True), \
                patch('apps.payments.gateway.fetch_payment', return_value={
                    'order_id': 'order_test_1', 'amount': 100, 'status': 'captured',
                }):
            response = self._verify()

        self.assertEqual(response.status_code, 400)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)

    def test_a_captured_payment_for_another_order_is_refused(self):
        purchase = self._purchase()
        with patch('apps.payments.gateway.verify_payment', return_value=True), \
                patch('apps.payments.gateway.fetch_payment', return_value={
                    'order_id': 'order_somebody_else', 'amount': 14900, 'status': 'captured',
                }):
            response = self._verify()

        self.assertEqual(response.status_code, 400)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)

    def test_an_uncaptured_payment_waits_for_the_webhook(self):
        purchase = self._purchase()
        with patch('apps.payments.gateway.verify_payment', return_value=True), \
                patch('apps.payments.gateway.fetch_payment', return_value={
                    'order_id': 'order_test_1', 'amount': 14900, 'status': 'authorized',
                }):
            response = self._verify()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'pending')
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)

    def test_a_refunded_purchase_stays_closed(self):
        purchase = self._purchase(status=Purchase.STATUS_REFUNDED)
        with patch('apps.payments.gateway.verify_payment', return_value=True):
            response = self._verify()

        self.assertEqual(response.status_code, 409)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_REFUNDED)


class WebhookTests(PaymentAPITestCase):
    def _capture_payload(self, order_id='order_test_1', payment_id='pay_1'):
        return {
            'event': 'payment.captured',
            'payload': {'payment': {'entity': {
                'id': payment_id, 'order_id': order_id,
                'amount': 14900, 'currency': 'INR', 'status': 'captured',
            }}},
        }

    def _refund_payload(self, payment_id='pay_1'):
        return {
            'event': 'refund.processed',
            'payload': {'refund': {'entity': {
                'id': 'rfnd_1', 'payment_id': payment_id, 'amount': 14900,
            }}},
        }

    def test_a_signed_capture_settles_the_purchase(self):
        purchase = self._purchase()
        response = self._webhook(self._capture_payload())

        self.assertEqual(response.status_code, 200, response.data)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PAID)
        self.assertEqual(purchase.provider_payment_id, 'pay_1')
        self.assertTrue(can_read_article(self.reader, self.paid))

    def test_a_bad_signature_is_refused_and_recorded_nowhere(self):
        purchase = self._purchase()
        response = self._webhook(self._capture_payload(), secret='not-the-secret')

        self.assertEqual(response.status_code, 400)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)
        self.assertFalse(PaymentEvent.objects.exists())

    def test_a_duplicate_delivery_grants_nothing_new(self):
        purchase = self._purchase()
        self._webhook(self._capture_payload(), event_id='evt_same')
        purchase.refresh_from_db()
        paid_at = purchase.paid_at
        purchase.status = Purchase.STATUS_CREATED
        purchase.paid_at = None
        purchase.save(update_fields=['status', 'paid_at'])

        second = self._webhook(self._capture_payload(), event_id='evt_same')

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['status'], 'duplicate')
        purchase.refresh_from_db()
        # The replay was ignored: the row is exactly where the test left it.
        self.assertEqual(purchase.status, Purchase.STATUS_CREATED)
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.assertNotEqual(paid_at, None)

    def test_a_failed_payment_does_not_unlock_anything(self):
        purchase = self._purchase()
        payload = {
            'event': 'payment.failed',
            'payload': {'payment': {'entity': {
                'id': 'pay_1', 'order_id': 'order_test_1',
            }}},
        }
        response = self._webhook(payload)

        self.assertEqual(response.status_code, 200)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_FAILED)
        self.assertFalse(can_read_article(self.reader, self.paid))

    def test_a_processed_refund_revokes_access(self):
        purchase = self._purchase()
        self._webhook(self._capture_payload())
        self._webhook(self._refund_payload(), event_id='evt_refund')

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_REFUNDED)
        self.assertFalse(can_read_article(self.reader, self.paid))

        detail = self.client.get('/api/articles/paid-article/')
        self.assertFalse(detail.data['has_access'])
        self.assertIsNone(detail.data['content'])

    def test_a_pending_refund_changes_nothing(self):
        """`refund.created` means initiated; it can still fail."""
        purchase = self._purchase(status=Purchase.STATUS_PAID, provider_payment_id='pay_1')
        response = self._webhook(
            {
                'event': 'refund.created',
                'payload': {'refund': {'entity': {'id': 'rfnd_1', 'payment_id': 'pay_1'}}},
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'ignored')
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PAID)

    def test_an_unsubscribed_event_is_acknowledged(self):
        response = self._webhook({'event': 'order.paid', 'payload': {}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'ignored')

    def test_a_capture_for_an_unknown_order_is_ignored(self):
        response = self._webhook(self._capture_payload(order_id='order_unknown'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'ignored')

    def test_a_delivery_without_headers_is_refused(self):
        response = self._webhook(self._capture_payload(), headers=False)
        self.assertEqual(response.status_code, 400)

    @override_settings(RAZORPAY_WEBHOOK_SECRET='')
    def test_the_webhook_says_so_when_it_is_not_configured(self):
        response = self._webhook(self._capture_payload())
        self.assertEqual(response.status_code, 503)

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_the_webhook_does_not_depend_on_the_api_keys(self):
        """The endpoint secret signs deliveries; the key pair is for checkout."""
        purchase = self._purchase()
        response = self._webhook(self._capture_payload())

        self.assertEqual(response.status_code, 200, response.data)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PAID)
