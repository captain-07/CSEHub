from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.articles.models import Article

from .access import can_read_article
from .models import Purchase


def make_purchase(user, article, status=Purchase.STATUS_PAID):
    return Purchase.objects.create(
        user=user,
        article=article,
        status=status,
        amount_paise=int(article.price * 100),
        receipt=f'test-{uuid4().hex}',
    )


class CanReadArticleTests(TestCase):
    """The gate every content-bearing route consults."""

    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            email='staff@example.com', username='staff', password='password', is_staff=True
        )
        self.reader = User.objects.create_user(
            email='reader@example.com', username='reader', password='password'
        )
        self.buyer = User.objects.create_user(
            email='buyer@example.com', username='buyer', password='password'
        )
        self.free = Article.objects.create(
            title='Free', slug='free', content={'blocks': []}, is_published=True,
        )
        self.paid = Article.objects.create(
            title='Paid', slug='paid', content={'blocks': []}, is_published=True,
            is_paid=True, price=Decimal('149.00'), author=self.staff,
        )

    def test_a_free_article_is_readable_by_anonymous_visitors(self):
        self.assertTrue(can_read_article(None, self.free))

    def test_a_paid_article_is_closed_to_anonymous_visitors(self):
        self.assertFalse(can_read_article(None, self.paid))

    def test_signing_in_without_a_purchase_does_not_unlock_it(self):
        self.assertFalse(can_read_article(self.reader, self.paid))

    def test_a_paid_purchase_unlocks_it(self):
        make_purchase(self.buyer, self.paid)
        self.assertTrue(can_read_article(self.buyer, self.paid))

    def test_failed_and_refunded_purchases_do_not_unlock_it(self):
        for status in (Purchase.STATUS_FAILED, Purchase.STATUS_REFUNDED):
            user = get_user_model().objects.create_user(
                email=f'{status}@example.com', username=status, password='password'
            )
            make_purchase(user, self.paid, status=status)
            self.assertFalse(can_read_article(user, self.paid), status)

    def test_a_staff_member_can_read_it(self):
        """Staff price the article and their editor reads the detail route."""
        self.assertTrue(can_read_article(self.staff, self.paid))

    def test_a_missing_article_is_never_readable(self):
        self.assertFalse(can_read_article(self.buyer, None))


class MyPurchasesViewTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        User = get_user_model()
        self.reader = User.objects.create_user(
            email='reader2@example.com', username='reader2', password='password'
        )
        self.buyer = User.objects.create_user(
            email='buyer2@example.com', username='buyer2', password='password'
        )
        self.paid = Article.objects.create(
            title='Paid Article', slug='paid-article', content={'blocks': []},
            is_published=True, is_paid=True, price=Decimal('199.00')
        )
        make_purchase(self.buyer, self.paid, status=Purchase.STATUS_PAID)
        self.client = APIClient()

    def test_anonymous_cannot_list_purchases(self):
        response = self.client.get('/api/payments/my-purchases/')
        self.assertEqual(response.status_code, 401)

    def test_reader_with_no_purchases_gets_empty_list(self):
        self.client.force_authenticate(user=self.reader)
        response = self.client.get('/api/payments/my-purchases/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_buyer_lists_paid_purchases(self):
        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/payments/my-purchases/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'paid-article')
        self.assertEqual(data[0]['title'], 'Paid Article')


class PurchaseLogViewTests(TestCase):
    """The admin transaction log: every attempt, with its payment details."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            email='pay-admin@example.com', username='pay-admin',
            password='password', is_staff=True,
        )
        self.reader = User.objects.create_user(
            email='pay-reader@example.com', username='pay-reader', password='password',
        )
        self.article = Article.objects.create(
            title='Sold Article', slug='sold-article', content={'blocks': []},
            is_published=True, is_paid=True, price=Decimal('149.00'),
        )
        self.paid = Purchase.objects.create(
            user=self.reader, article=self.article, status=Purchase.STATUS_PAID,
            amount_paise=14900, provider_order_id='order_paid',
            provider_payment_id='pay_paid', receipt='receipt-paid',
            contact='9999999999', paid_at=timezone.now(),
        )
        self.refunded = Purchase.objects.create(
            user=self.reader, article=self.article, status=Purchase.STATUS_REFUNDED,
            amount_paise=19900, provider_order_id='order_refunded',
            provider_payment_id='pay_refunded', receipt='receipt-refunded',
        )
        self.failed = Purchase.objects.create(
            user=self.reader, article=self.article, status=Purchase.STATUS_FAILED,
            amount_paise=14900, provider_order_id='order_failed',
            receipt='receipt-failed',
        )
        self.open = Purchase.objects.create(
            user=self.reader, article=self.article, status=Purchase.STATUS_CREATED,
            amount_paise=9900, provider_order_id='order_open',
            receipt='receipt-open',
        )
        self.client = APIClient()

    def test_the_log_and_summary_are_admin_only(self):
        self.assertEqual(self.client.get('/api/payments/purchases/').status_code, 401)
        self.assertEqual(
            self.client.get('/api/payments/purchases/summary/').status_code, 401
        )

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/payments/purchases/').status_code, 403)
        self.assertEqual(
            self.client.get('/api/payments/purchases/summary/').status_code, 403
        )

    def test_the_log_lists_every_attempt_with_its_details(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/payments/purchases/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 4)
        row = next(r for r in response.data['results'] if r['id'] == self.paid.pk)
        self.assertEqual(row['user_email'], 'pay-reader@example.com')
        self.assertEqual(row['user_username'], 'pay-reader')
        self.assertEqual(row['article_title'], 'Sold Article')
        self.assertEqual(row['article_slug'], 'sold-article')
        self.assertEqual(row['amount'], '149.00')
        self.assertEqual(row['amount_paise'], 14900)
        self.assertEqual(row['currency'], 'INR')
        self.assertEqual(row['status'], 'paid')
        self.assertEqual(row['provider'], 'razorpay')
        self.assertEqual(row['provider_order_id'], 'order_paid')
        self.assertEqual(row['provider_payment_id'], 'pay_paid')
        self.assertEqual(row['receipt'], 'receipt-paid')
        self.assertEqual(row['contact'], '9999999999')
        self.assertIsNotNone(row['paid_at'])

    def test_the_log_is_newest_first(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/payments/purchases/')
        self.assertEqual(response.data['results'][0]['id'], self.open.pk)

    def test_status_filter_and_search(self):
        self.client.force_authenticate(self.admin)

        paid = self.client.get('/api/payments/purchases/', {'status': 'paid'})
        self.assertEqual(paid.data['count'], 1)
        self.assertEqual(paid.data['results'][0]['id'], self.paid.pk)

        # An unrecognised status is ignored rather than returning nothing.
        ignored = self.client.get('/api/payments/purchases/', {'status': 'nonsense'})
        self.assertEqual(ignored.data['count'], 4)

        by_order = self.client.get(
            '/api/payments/purchases/', {'search': 'order_refunded'}
        )
        self.assertEqual(by_order.data['count'], 1)
        self.assertEqual(by_order.data['results'][0]['id'], self.refunded.pk)

        by_article = self.client.get(
            '/api/payments/purchases/', {'search': 'sold-article'}
        )
        self.assertEqual(by_article.data['count'], 4)

        by_buyer = self.client.get(
            '/api/payments/purchases/', {'search': 'pay-reader@'}
        )
        self.assertEqual(by_buyer.data['count'], 4)

        by_receipt = self.client.get(
            '/api/payments/purchases/', {'search': 'receipt-failed'}
        )
        self.assertEqual(by_receipt.data['count'], 1)

        miss = self.client.get('/api/payments/purchases/', {'search': 'nobody'})
        self.assertEqual(miss.data['count'], 0)

    def test_the_summary_counts_and_sums_each_status(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/payments/purchases/summary/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total'], 4)
        self.assertEqual(response.data['paid'], 1)
        self.assertEqual(response.data['paid_amount_paise'], 14900)
        self.assertEqual(response.data['refunded'], 1)
        self.assertEqual(response.data['refunded_amount_paise'], 19900)
        self.assertEqual(response.data['failed'], 1)
        self.assertEqual(response.data['open'], 1)

    def test_an_empty_log_summarises_to_zero(self):
        Purchase.objects.all().delete()
        self.client.force_authenticate(self.admin)

        response = self.client.get('/api/payments/purchases/summary/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total'], 0)
        self.assertEqual(response.data['paid_amount_paise'], 0)
        self.assertEqual(response.data['refunded_amount_paise'], 0)

