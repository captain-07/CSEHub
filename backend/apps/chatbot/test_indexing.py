from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.articles.models import Article
from apps.chatbot.indexing import _sync, enqueue_reindex, rag_configured
from apps.chatbot.ingestion import NAMESPACE, remove_article_vectors

RAG_SETTINGS = {
    'PINECONE_API_KEY': 'test-key',
    'PINECONE_INDEX_NAME': 'test-index',
    'GEMINI_API_KEY': 'test-key',
}


def make_article(**overrides):
    values = {
        'title': 'Binary Search',
        'slug': 'binary-search',
        'excerpt': 'A short summary.',
        'content': {'blocks': [{'type': 'paragraph', 'data': {'text': 'body'}}]},
    }
    values.update(overrides)
    return Article.objects.create(**values)


class ReindexSignalTests(TestCase):
    """A save must queue work only when the indexed inputs actually changed."""

    def setUp(self):
        self.article = make_article()

    def _save(self, **changes):
        for field, value in changes.items():
            setattr(self.article, field, value)
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save()

    @patch('apps.articles.signals.enqueue_reindex')
    def test_creating_a_published_article_enqueues_it(self, enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            article = make_article(slug='new', is_published=True)
        enqueue.assert_called_once_with(article.pk)

    @patch('apps.articles.signals.enqueue_reindex')
    def test_creating_a_draft_enqueues_nothing(self, enqueue):
        with self.captureOnCommitCallbacks(execute=True):
            make_article(slug='draft')
        enqueue.assert_not_called()

    @patch('apps.articles.signals.enqueue_reindex')
    def test_publishing_a_draft_enqueues_it(self, enqueue):
        self._save(is_published=True)
        enqueue.assert_called_once_with(self.article.pk)

    @patch('apps.articles.signals.enqueue_reindex')
    def test_editing_a_draft_enqueues_nothing(self, enqueue):
        self._save(title='Changed title')
        enqueue.assert_not_called()

    @patch('apps.articles.signals.enqueue_reindex')
    def test_editing_a_published_article_enqueues_it(self, enqueue):
        self._save(is_published=True)
        enqueue.reset_mock()

        self._save(content={'blocks': [{'type': 'paragraph', 'data': {'text': 'new body'}}]})
        enqueue.assert_called_once_with(self.article.pk)

    @patch('apps.articles.signals.enqueue_reindex')
    def test_editing_the_excerpt_enqueues_it(self, enqueue):
        """The excerpt is now part of the indexed text, so it counts as content."""
        self._save(is_published=True)
        enqueue.reset_mock()

        self._save(excerpt='A better summary.')
        enqueue.assert_called_once_with(self.article.pk)

    @patch('apps.articles.signals.enqueue_reindex')
    def test_metadata_only_save_enqueues_nothing(self, enqueue):
        self._save(is_published=True)
        enqueue.reset_mock()

        self._save(is_featured=True)
        enqueue.assert_not_called()

    @patch('apps.articles.signals.enqueue_reindex')
    def test_unpublishing_enqueues_removal(self, enqueue):
        self._save(is_published=True)
        enqueue.reset_mock()

        self._save(is_published=False)
        enqueue.assert_called_once_with(self.article.pk)

    @patch('apps.articles.signals.enqueue_reindex')
    def test_deleting_enqueues_removal(self, enqueue):
        pk = self.article.pk
        with self.captureOnCommitCallbacks(execute=True):
            self.article.delete()
        enqueue.assert_called_once_with(pk)

    @patch('apps.articles.signals.enqueue_reindex')
    def test_counting_a_view_enqueues_nothing(self, enqueue):
        """`record_view` updates with `QuerySet.update`, which bypasses signals."""
        self._save(is_published=True)
        enqueue.reset_mock()

        self.article.record_view()
        enqueue.assert_not_called()


class IndexSyncTests(TestCase):
    """The worker re-reads the row, so the last state queued always wins."""

    def test_published_article_is_ingested(self):
        article = make_article(is_published=True)
        with patch('apps.chatbot.ingestion.ingest_article', return_value=3) as ingest:
            _sync(article.pk)
        ingest.assert_called_once_with(article)

    def test_unpublished_article_has_its_vectors_removed(self):
        article = make_article(is_published=True)
        article.is_published = False
        article.save()
        with patch('apps.chatbot.ingestion.remove_article_vectors') as remove:
            _sync(article.pk)
        remove.assert_called_once_with(article.pk)

    def test_missing_article_has_its_vectors_removed(self):
        with patch('apps.chatbot.ingestion.remove_article_vectors') as remove:
            _sync(999999)
        remove.assert_called_once_with(999999)


class EnqueueGuardTests(TestCase):
    """Auto-indexing is opt-out and inert when the provider is unconfigured."""

    @override_settings(
        PINECONE_API_KEY='',
        PINECONE_INDEX_NAME='',
        GEMINI_API_KEY='',
    )
    def test_rag_is_not_configured_without_keys(self):
        self.assertFalse(rag_configured())

    @override_settings(RAG_AUTO_INDEX=False, **RAG_SETTINGS)
    @patch('apps.chatbot.indexing._ensure_worker')
    def test_disabled_setting_never_starts_the_worker(self, ensure_worker):
        enqueue_reindex(1)
        ensure_worker.assert_not_called()

    @override_settings(RAG_AUTO_INDEX=True, **RAG_SETTINGS)
    @patch('apps.chatbot.indexing._queue')
    @patch('apps.chatbot.indexing._ensure_worker')
    def test_enabled_setting_queues_the_article(self, ensure_worker, task_queue):
        enqueue_reindex(7)
        ensure_worker.assert_called_once_with()
        task_queue.put.assert_called_once_with(7)

    @override_settings(
        RAG_AUTO_INDEX=True,
        PINECONE_API_KEY='',
        PINECONE_INDEX_NAME='',
        GEMINI_API_KEY='',
    )
    @patch('apps.chatbot.indexing._ensure_worker')
    def test_missing_credentials_never_start_the_worker(self, ensure_worker):
        enqueue_reindex(1)
        ensure_worker.assert_not_called()

    @override_settings(RAG_AUTO_INDEX=True, **RAG_SETTINGS)
    @patch('apps.chatbot.indexing._ensure_worker', side_effect=RuntimeError('no threads'))
    def test_queueing_failure_never_raises(self, ensure_worker):
        # A save must succeed even if the worker cannot be started; the exception
        # would otherwise surface after commit as a 500.
        enqueue_reindex(1)


@override_settings(**RAG_SETTINGS)
class RemoveArticleVectorsTests(TestCase):
    """Unpublish/delete must remove exactly one article's vectors."""

    @patch('apps.chatbot.ingestion.Pinecone')
    def test_delete_is_filtered_by_article_id(self, pinecone):
        index = pinecone.return_value.Index.return_value
        remove_article_vectors(42)
        index.delete.assert_called_once_with(
            filter={'article_id': '42'},
            namespace=NAMESPACE,
        )

    @patch('apps.chatbot.ingestion.Pinecone')
    def test_a_missing_namespace_is_not_an_error(self, pinecone):
        pinecone.return_value.Index.return_value.delete.side_effect = Exception(
            'Namespace not found'
        )
        # Nothing was ever indexed, which is the normal state on a fresh deploy.
        remove_article_vectors(42)

    @patch('apps.chatbot.ingestion.Pinecone')
    def test_other_provider_failures_propagate(self, pinecone):
        pinecone.return_value.Index.return_value.delete.side_effect = Exception('boom')
        with self.assertRaises(Exception):
            remove_article_vectors(42)
