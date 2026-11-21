from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase

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
