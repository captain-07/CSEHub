from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.articles.models import Article
from .models import Conversation
from .rag_chat import ChatServiceError, _response_text


class ChatTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='user@example.com', username='user')
        self.other = get_user_model().objects.create_user(email='other@example.com', username='other')
        self.article = Article.objects.create(title='Article', slug='article', content={'blocks': []}, is_published=True)

    def test_chat_requires_authentication(self):
        self.assertEqual(self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json').status_code, 401)

    @patch('apps.chatbot.views.answer_question', return_value='A grounded answer')
    def test_chat_stores_messages_and_isolated(self, answer):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json')
        self.assertEqual(response.status_code, 200)
        conversation = Conversation.objects.get(user=self.user, article=self.article)
        self.assertEqual(conversation.messages.count(), 2)
        # The ask response and the history endpoint must agree on shape so a
        # client only ever needs one parser.
        self.assertEqual(
            sorted(response.data.keys()),
            ['article', 'article_title', 'created_at', 'id', 'messages'],
        )
        self.assertEqual(response.data['messages'][-1]['content'], 'A grounded answer')
        self.client.force_authenticate(self.user)
        history = self.client.get('/api/articles/article/conversation/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(sorted(history.data.keys()), sorted(response.data.keys()))
        self.assertEqual(len(history.data['messages']), 2)

    def test_conversation_history_is_empty_but_well_formed_for_new_user(self):
        self.client.force_authenticate(self.other)
        response = self.client.get('/api/articles/article/conversation/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data.keys()),
            ['article', 'article_title', 'created_at', 'id', 'messages'],
        )
        self.assertEqual(response.data['messages'], [])

    @patch('apps.chatbot.views.answer_question', side_effect=ChatServiceError('down'))
    def test_provider_failure_returns_service_unavailable(self, answer):
        """A broken provider must be a 503, not a fake answer with a 200."""
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'chat_unavailable')
        # The question is still recorded; no fabricated assistant reply is stored.
        conversation = Conversation.objects.get(user=self.user, article=self.article)
        self.assertEqual(conversation.messages.count(), 1)
        self.assertEqual(conversation.messages.first().role, 'user')

    @patch('apps.chatbot.views.answer_question', side_effect=RuntimeError('boom'))
    def test_unexpected_failure_returns_bad_gateway(self, answer):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['code'], 'chat_error')

    def test_chat_on_draft_article_is_not_found(self):
        Article.objects.create(title='Draft', slug='draft-article', content={'blocks': []})
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/draft-article/ask/', {'question': 'Why?'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_llm_response_normalization(self):
        self.assertEqual(_response_text('plain'), 'plain')
        self.assertEqual(_response_text(type('R', (), {'content': [{'text': 'one'}, {'text': ' two'}]})()), 'one two')
        with self.assertRaises(ChatServiceError):
            _response_text({'unexpected': 'shape'})


class ContentToTextTests(TestCase):
    """Editor.js JSON must reach the vector store as readable prose, not syntax.

    The whole RAG path depends on this: `ingest_article` embeds whatever
    `article_content_to_text` returns, and raw JSON would both waste tokens and
    make retrieval far worse.
    """

    def test_editorjs_blocks_become_structured_readable_text(self):
        from apps.chatbot.ingestion import article_content_to_text

        text = article_content_to_text({
            'blocks': [
                {'type': 'header', 'data': {'text': 'Binary Search', 'level': 2}},
                {'type': 'paragraph', 'data': {'text': 'It works on <b>sorted</b> input.'}},
                {'type': 'list', 'data': {'style': 'unordered', 'items': [
                    {'content': 'Find the <i>middle</i> element'},
                    'Compare and discard a half',
                ]}},
                {'type': 'code', 'data': {'code': 'def search(a, t):\n    ...', 'language': 'python'}},
                {'type': 'quote', 'data': {'text': 'Measure twice.'}},
                {'type': 'delimiter', 'data': {}},
                {'type': 'image', 'data': {'caption': 'The halving pattern'}},
            ],
        })

        self.assertIn('Heading: Binary Search', text)
        self.assertIn('sorted', text)
        # Inline markup must be stripped, not embedded in the embedding text.
        self.assertNotIn('<b>', text)
        self.assertNotIn('<i>', text)
        self.assertIn('- Find the middle element', text)
        self.assertIn('Code (python):', text)
        self.assertIn('def search(a, t):', text)
        self.assertIn('Measure twice.', text)
        self.assertIn('The halving pattern', text)
        # JSON syntax must never reach the vector store.
        self.assertNotIn('"type"', text)
        self.assertNotIn('"blocks"', text)

    def test_legacy_plain_text_content_is_still_supported(self):
        from apps.chatbot.ingestion import article_content_to_text

        self.assertEqual(article_content_to_text('A plain body'), 'A plain body')
        self.assertEqual(article_content_to_text(None), '')
        self.assertEqual(article_content_to_text({'blocks': []}), '')


class PurgeNamespaceTests(TestCase):
    """`ingest_article` only deletes its own article's vectors.

    That leaves vectors belonging to deleted articles in place, and because ids
    get reused a filtered search can then match an orphan's text and the
    assistant answers from the wrong article. `--purge` exists to clear them, so
    it needs coverage: it is the one command here that destroys data.
    """

    def setUp(self):
        from apps.chatbot import ingestion

        self.ingestion = ingestion
        self.published = Article.objects.create(
            title='Published', slug='published', content={'blocks': []}, is_published=True
        )

    def _ingest(self, **kwargs):
        from apps.chatbot.management.commands.ingest_articles import Command

        return Command().handle(**kwargs)

    def test_purge_clears_the_namespace_before_ingesting(self):
        with patch.object(self.ingestion, 'purge_namespace') as purge, \
                patch('apps.chatbot.management.commands.ingest_articles.ingest_article',
                      return_value=3) as ingest, \
                patch('apps.chatbot.management.commands.ingest_articles.purge_namespace', purge):
            self._ingest(slug=None, purge=True)

        purge.assert_called_once_with()
        ingest.assert_called_once_with(self.published)

    def test_ingestion_without_purge_leaves_the_namespace_alone(self):
        with patch('apps.chatbot.management.commands.ingest_articles.purge_namespace') as purge, \
                patch('apps.chatbot.management.commands.ingest_articles.ingest_article',
                      return_value=2) as ingest:
            self._ingest(slug=None, purge=False)

        purge.assert_not_called()
        ingest.assert_called_once_with(self.published)

    def test_purge_with_slug_is_refused(self):
        """`--purge` clears everything, so pairing it with `--slug` is a mistake."""
        from django.core.management.base import CommandError

        with patch('apps.chatbot.management.commands.ingest_articles.purge_namespace') as purge:
            with self.assertRaises(CommandError):
                self._ingest(slug='published', purge=True)

        purge.assert_not_called()

    def test_purge_uses_delete_all_for_the_configured_namespace(self):
        with patch('apps.chatbot.ingestion.Pinecone') as pinecone:
            index = Mock()
            pinecone.return_value.Index.return_value = index
            with patch.object(self.ingestion, '_require_rag_settings'):
                self.ingestion.purge_namespace()

        index.delete.assert_called_once_with(delete_all=True, namespace=self.ingestion.NAMESPACE)
        pinecone.return_value.Index.assert_called_once_with(settings.PINECONE_INDEX_NAME)
