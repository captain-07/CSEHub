from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.payments.models import Purchase
from .models import Article


BODY = {
    'blocks': [
        {'type': 'paragraph', 'data': {'text': 'The part the reader pays for.'}},
    ]
}


def buy(user, article, status=Purchase.STATUS_PAID):
    return Purchase.objects.create(
        user=user,
        article=article,
        status=status,
        amount_paise=int(article.price * 100),
        receipt=f'test-{uuid4().hex}',
    )


class PaidArticleAPITests(APITestCase):
    """A paid article's body is withheld, not hidden with CSS.

    This is the security-critical half of the feature: the payment provider only
    decides who is *granted* access, so every route that can carry the writing
    has to be closed until a purchase exists.
    """

    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user(
            email='author@example.com', username='author', password='password', is_staff=True
        )
        self.reader = User.objects.create_user(
            email='reader@example.com', username='reader', password='password'
        )
        self.buyer = User.objects.create_user(
            email='buyer@example.com', username='buyer', password='password'
        )
        self.free = Article.objects.create(
            title='Free article',
            slug='free-article',
            content=BODY,
            excerpt='A free read.',
            is_published=True,
            author=self.author,
        )
        self.paid = Article.objects.create(
            title='Paid article',
            slug='paid-article',
            content=BODY,
            excerpt='A paid teaser.',
            video_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            is_published=True,
            author=self.author,
            is_paid=True,
            price=Decimal('149.00'),
        )

    # ---------------------------------------------------------- detail route

    def test_anonymous_reader_gets_the_teaser_without_the_body(self):
        response = self.client.get('/api/articles/paid-article/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_paid'])
        self.assertEqual(response.data['price'], '149.00')
        self.assertFalse(response.data['has_access'])
        self.assertIsNone(response.data['content'])
        self.assertEqual(response.data['code_snippets'], [])
        self.assertEqual(response.data['video_url'], '')
        self.assertEqual(response.data['quiz_question_count'], 0)
        # The sales pitch survives: a locked page still has to be worth opening.
        self.assertEqual(response.data['excerpt'], 'A paid teaser.')

    def test_a_free_article_still_serves_its_body_to_anonymous_readers(self):
        response = self.client.get('/api/articles/free-article/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_paid'])
        self.assertTrue(response.data['has_access'])
        self.assertEqual(response.data['content'], BODY)

    def test_signing_in_without_a_purchase_is_still_locked(self):
        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/articles/paid-article/')

        self.assertFalse(response.data['has_access'])
        self.assertIsNone(response.data['content'])

    def test_a_purchase_unlocks_the_body(self):
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)
        response = self.client.get('/api/articles/paid-article/')

        self.assertTrue(response.data['has_access'])
        self.assertEqual(response.data['content'], BODY)

    def test_a_refunded_purchase_relocks_the_body(self):
        buy(self.buyer, self.paid, status=Purchase.STATUS_REFUNDED)
        self.client.force_authenticate(self.buyer)

        response = self.client.get('/api/articles/paid-article/')

        self.assertFalse(response.data['has_access'])
        self.assertIsNone(response.data['content'])

    def test_staff_can_read_the_article_they_edit(self):
        self.client.force_authenticate(self.author)
        response = self.client.get('/api/articles/paid-article/')

        self.assertTrue(response.data['has_access'])
        self.assertEqual(response.data['content'], BODY)

    # ----------------------------------------------------------------- list

    def test_the_listing_shows_the_price_without_the_content(self):
        response = self.client.get('/api/articles/')
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data['results'] if item['slug'] == 'paid-article')

        self.assertTrue(row['is_paid'])
        self.assertEqual(row['price'], '149.00')
        self.assertNotIn('content', row)

    # ----------------------------------------------------------------- quiz

    def test_the_quiz_is_refused_without_access(self):
        response = self.client.get('/api/articles/paid-article/quiz/')

        self.assertEqual(response.status_code, 402)
        self.assertIn('paid', response.data['detail'])

    def test_the_quiz_opens_for_a_buyer(self):
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)
        response = self.client.get('/api/articles/paid-article/quiz/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['questions'], [])

    def test_a_quiz_submission_is_refused_without_access(self):
        response = self.client.post(
            '/api/articles/paid-article/quiz/submit/', {'answers': []}, format='json'
        )

        self.assertEqual(response.status_code, 402)

    # ----------------------------------------------------------------- views

    def test_a_locked_page_view_is_not_counted(self):
        self.client.get('/api/articles/paid-article/')
        response = self.client.post('/api/articles/paid-article/view/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['view_count'], 0)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.view_count, 0)

    def test_a_buyers_view_is_counted(self):
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)
        response = self.client.post('/api/articles/paid-article/view/')

        self.assertEqual(response.data['view_count'], 1)

    # ------------------------------------------------------------- assistant

    def test_the_assistant_refuses_a_paid_article_without_access(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            '/api/articles/paid-article/ask/', {'question': 'Explain this.'}, format='json'
        )

        self.assertEqual(response.status_code, 402)

    def test_the_conversation_history_is_refused_without_access(self):
        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/articles/paid-article/conversation/')

        self.assertEqual(response.status_code, 402)

    @patch('apps.chatbot.views.answer_question', return_value='A grounded answer')
    def test_the_assistant_answers_a_buyer(self, answer):
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)
        response = self.client.post(
            '/api/articles/paid-article/ask/', {'question': 'Explain this.'}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages'][-1]['content'], 'A grounded answer')

    # --------------------------------------------------------------- writing

    def test_a_paid_article_needs_a_price(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(
            '/api/articles/',
            {
                'title': 'Unpriced',
                'slug': 'unpriced',
                'content': BODY,
                'is_paid': True,
                'price': 0,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('price', response.data)

    def test_ticking_paid_on_an_unpriced_article_is_refused(self):
        self.client.force_authenticate(self.author)
        response = self.client.patch(
            '/api/articles/free-article/', {'is_paid': True}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('price', response.data)

    def test_a_price_cannot_be_negative(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(
            '/api/articles/',
            {
                'title': 'Negative',
                'slug': 'negative',
                'content': BODY,
                'is_paid': True,
                'price': -5,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_a_paid_article_can_be_created_with_a_price(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(
            '/api/articles/',
            {
                'title': 'Priced',
                'slug': 'priced',
                'content': BODY,
                'is_paid': True,
                'price': '99.00',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        article = Article.objects.get(slug='priced')
        self.assertTrue(article.is_paid)
        self.assertEqual(article.price, Decimal('99.00'))

    def test_making_a_paid_article_free_opens_it_to_everyone(self):
        self.client.force_authenticate(self.author)
        self.client.patch('/api/articles/paid-article/', {'is_paid': False}, format='json')
        self.client.force_authenticate(None)

        response = self.client.get('/api/articles/paid-article/')

        self.assertTrue(response.data['has_access'])
        self.assertEqual(response.data['content'], BODY)

    def test_the_database_refuses_a_paid_article_without_a_price(self):
        """The serializer is the readable error; the constraint is the guarantee."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Article.objects.create(
                    title='Bad', slug='bad-price', content=BODY,
                    is_paid=True, price=Decimal('0'),
                )
