"""The PDF edition of a paid article.

The download is a second copy of the body, so it has to pass the same gate as
the detail route. These tests pin the gate and the file itself; the layout is
`apps/articles/pdf.py`'s business.
"""

from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.payments.models import Purchase
from .models import Article, CodeSnippet
from .pdf import _inline, _wrap_code, article_to_story, render_article_pdf

BODY = {
    'blocks': [
        {'type': 'header', 'data': {'level': 2, 'text': 'A heading'}},
        {'type': 'paragraph', 'data': {'text': 'The part the reader pays for.'}},
        {
            'type': 'code',
            'data': {'code': 'def f(x):\n\treturn x < 3 and y > 2\n', 'language': 'python'},
        },
        {'type': 'list', 'data': {'style': 'ordered', 'items': ['First', 'Second']}},
        {'type': 'quote', 'data': {'text': 'Quoted', 'caption': 'Someone'}},
        {'type': 'image', 'data': {'caption': 'Diagram', 'file': {'url': 'https://example.com/a.png'}}},
        {'type': 'linkTool', 'data': {'url': 'https://example.com', 'text': 'Example'}},
        {'type': 'delimiter', 'data': {}},
    ]
}


def buy(user, article, status=Purchase.STATUS_PAID):
    return Purchase.objects.create(
        user=user,
        article=article,
        status=status,
        amount_paise=int(article.price * 100),
        receipt=f'pdf-test-{uuid4().hex}',
    )


class ArticlePdfTests(APITestCase):
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
            is_published=True,
            author=self.author,
        )
        self.paid = Article.objects.create(
            title='Paid article',
            slug='paid-article',
            content=BODY,
            excerpt='A paid teaser.',
            is_published=True,
            author=self.author,
            is_paid=True,
            price=Decimal('149.00'),
        )

    # ------------------------------------------------------------------ gate

    def test_anonymous_reader_is_refused_with_402(self):
        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 402)
        self.assertIn('paid', response.data['detail'])
        self.assertNotIn('application/pdf', response['Content-Type'])

    def test_signing_in_without_a_purchase_is_refused(self):
        self.client.force_authenticate(self.reader)
        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 402)

    def test_a_refunded_purchase_does_not_download(self):
        buy(self.buyer, self.paid, status=Purchase.STATUS_REFUNDED)
        self.client.force_authenticate(self.buyer)

        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 402)

    def test_a_free_article_has_no_pdf(self):
        response = self.client.get('/api/articles/free-article/pdf/')

        self.assertEqual(response.status_code, 404)

    def test_a_draft_paid_article_is_not_reachable(self):
        draft = Article.objects.create(
            title='Draft', slug='draft-paid', content=BODY,
            is_published=False, author=self.author, is_paid=True,
            price=Decimal('99.00'),
        )
        buy(self.buyer, draft)
        self.client.force_authenticate(self.buyer)

        response = self.client.get('/api/articles/draft-paid/pdf/')

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------- file

    def test_a_buyer_gets_a_pdf_named_after_the_slug(self):
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)

        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            response['Content-Disposition'], 'attachment; filename="paid-article.pdf"'
        )
        self.assertIn('no-store', response['Cache-Control'])
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertGreater(len(response.content), 1000)

    def test_staff_can_download_what_they_edit(self):
        self.client.force_authenticate(self.author)

        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_an_article_that_renders_nothing_still_produces_a_file(self):
        """A blank body must not turn a download into a 500."""
        self.paid.content = {'blocks': []}
        self.paid.save(update_fields=['content'])
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)

        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_the_pdf_carries_the_attached_code_snippets(self):
        CodeSnippet.objects.create(
            article=self.paid, language='python', code='print("a snippet")'
        )

        story = article_to_story(self.paid)
        prose = '\n'.join(f.text for f in story if hasattr(f, 'text'))
        code = '\n'.join(line for f in story if hasattr(f, 'lines') for line in f.lines)

        self.assertIn('python', prose)
        self.assertIn('print("a snippet")', code)

    def test_characters_outside_latin_1_do_not_break_the_render(self):
        """The base-14 fonts are single-byte; sanitising is cheaper than a font."""
        self.paid.title = 'Em dash \u2014 and emoji \U0001F600 in the title'
        self.paid.excerpt = 'Curly \u201cquotes\u201d and an apostrophe\u2019s tail.'
        self.paid.content = {
            'blocks': [
                {'type': 'paragraph', 'data': {'text': 'CJK \u4f60\u597d and emoji \U0001F600.'}},
                {'type': 'code', 'data': {'code': '# \u4f60\u597d\nprint("ok")\n'}},
                {'type': 'image', 'data': {'caption': '\u56fe\u7247', 'file': {'url': 'https://example.com/a.png'}}},
            ]
        }
        self.paid.save()
        buy(self.buyer, self.paid)
        self.client.force_authenticate(self.buyer)

        response = self.client.get('/api/articles/paid-article/pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))


class ArticlePdfRenderingTests(APITestCase):
    """The document says what the article says, block for block."""

    def setUp(self):
        self.article = Article(
            title='Rendered', slug='rendered', excerpt='Teaser.', content=BODY,
            is_paid=True, price=Decimal('10.00'),
        )

    def story_text(self, article=None):
        def texts(flowables):
            for flowable in flowables:
                if hasattr(flowable, 'text'):
                    yield flowable.text
                # `KeepTogether` wraps a quotation and its attribution, so the
                # paragraphs inside it are one level down.
                inner = getattr(flowable, '_content', None)
                if isinstance(inner, list):
                    yield from texts(inner)

        return '\n'.join(texts(article_to_story(article or self.article)))

    def test_the_title_excerpt_and_body_reach_the_document(self):
        text = self.story_text()

        self.assertIn('Rendered', text)
        self.assertIn('Teaser.', text)
        self.assertIn('A heading', text)
        self.assertIn('The part the reader pays for.', text)
        self.assertIn('Quoted', text)
        self.assertIn('Example', text)

    def test_inline_markup_is_translated_rather_than_shown(self):
        self.article.content = {
            'blocks': [{
                'type': 'paragraph',
                'data': {'text': '<b>Bold</b> and <i>italic</i> in <code>code</code>'},
            }]
        }

        text = self.story_text()

        self.assertIn('<b>Bold</b>', text)
        self.assertIn('<i>italic</i>', text)
        self.assertNotIn('&lt;b&gt;', text)

    def test_an_unknown_block_degrades_to_its_text(self):
        self.article.content = {
            'blocks': [{'type': 'experimental', 'data': {'text': 'Still readable'}}]
        }

        self.assertIn('Still readable', self.story_text())

    def test_a_legacy_markdown_body_is_still_readable(self):
        self.article.content = '# Heading\n\nFirst paragraph.\n\nSecond paragraph.'

        text = self.story_text()

        self.assertIn('Heading', text)
        self.assertIn('First paragraph.', text)

    def test_long_code_is_wrapped_before_it_reaches_the_page(self):
        wrapped = _wrap_code('x' * 500)

        self.assertGreater(wrapped.count('\n'), 1)
        self.assertEqual(len(wrapped.replace('\n', '').replace('    ', '')), 500)

    def test_unbalanced_inline_markup_does_not_break_the_document(self):
        """ReportLab raises on an unclosed tag; stored content is free text."""
        self.article.content = {
            'blocks': [
                {'type': 'paragraph', 'data': {'text': '<b>never closed'}},
                {'type': 'paragraph', 'data': {'text': '</b>stray close'}},
                {'type': 'paragraph', 'data': {'text': '<i><b>crossed</i></b>'}},
                {'type': 'paragraph', 'data': {'text': '<code>never closed either'}},
            ]
        }

        data = render_article_pdf(self.article)

        self.assertTrue(data.startswith(b'%PDF'))

    def test_an_unfinished_tag_is_closed_and_a_crossed_pair_is_ordered(self):
        self.assertEqual(_inline('<b>bold'), '<b>bold</b>')
        self.assertEqual(_inline('</b>plain'), 'plain')
        self.assertEqual(_inline('<i><b>crossed</i></b>'), '<i><b>crossed</b></i>')

    def test_an_unsafe_link_is_dropped_rather_than_opened(self):
        self.assertEqual(_inline('<a href="javascript:alert(1)">bad</a>'), 'bad')
        self.assertEqual(
            _inline('<a href="https://example.com?a=1&b=2">good</a>'),
            '<link href="https://example.com?a=1&amp;b=2">good</link>',
        )
