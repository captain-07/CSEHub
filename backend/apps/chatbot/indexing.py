"""Background (re)indexing of articles for the RAG assistant.

The signal handlers in `apps.articles.signals` only decide *whether* an article
changed in a way that matters to retrieval. The network work happens here, on a
single daemon worker thread, after the transaction that saved the article has
committed.

Nothing in this module may raise into the caller: a Pinecone or Gemini failure
must never roll back an article save. The worker logs the failure; the article
keeps whatever the provider still holds (which may be stale or, after a failed
mid-ingest, absent) until the next save or `manage.py ingest_articles` repairs
it.

This is deliberately not Celery + Redis. The project runs one low-volume web
process with a single job type, so a queue service would add more deployment
surface than work. `enqueue_reindex()` is the seam: replacing its body with a
task's `.delay(article_id)` is the whole migration if the site ever needs
durable, retrying tasks.
"""

import logging
import queue
import threading

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

_queue = queue.Queue()
_started = False
_start_lock = threading.Lock()


def rag_configured():
    """True when every provider setting the RAG path needs is present.

    Kept here rather than in `ingestion` so the signals can decide whether to
    enqueue without importing LangChain/Pinecone at module scope. `_sync`
    imports those lazily, after this check has passed.
    """
    return all((
        getattr(settings, 'PINECONE_API_KEY', ''),
        getattr(settings, 'PINECONE_INDEX_NAME', ''),
        getattr(settings, 'GEMINI_API_KEY', ''),
    ))


def _auto_index_enabled():
    return bool(getattr(settings, 'RAG_AUTO_INDEX', True)) and rag_configured()


def enqueue_reindex(article_id):
    """Queue one article id for indexing (or for vector removal).

    Called from `transaction.on_commit`, so it must never raise: an exception
    here would surface after the commit, turning a successful article save into
    a 500. Any failure is logged and swallowed instead.
    """
    try:
        if not _auto_index_enabled():
            return
        _ensure_worker()
        _queue.put(int(article_id))
    except Exception:
        logger.exception('Could not queue RAG indexing for article id=%s', article_id)


def _ensure_worker():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_worker, name='rag-index', daemon=True).start()


def _worker():
    while True:
        article_id = _queue.get()
        # The worker outlives requests, so it cannot borrow their connection.
        close_old_connections()
        try:
            _sync(article_id)
        except RuntimeError as exc:
            # Missing RAG settings are a configuration state, not a crash.
            logger.warning('RAG indexing skipped for article id=%s: %s', article_id, exc)
        except Exception:
            logger.exception('RAG index sync failed for article id=%s', article_id)
        finally:
            close_old_connections()
            _queue.task_done()


def _sync(article_id):
    """Bring the vector store in line with the article's current state.

    Re-reads the row instead of trusting the caller's snapshot: that is what
    makes an unpublish (or a delete) race with a reindex safe. Jobs run
    sequentially, so the last state queued always wins.
    """
    # Imported lazily: importing LangChain/Pinecone at Django startup is slow and
    # unnecessary for a deployment with the assistant switched off.
    from apps.articles.models import Article
    from .ingestion import ingest_article, remove_article_vectors

    article = Article.objects.filter(pk=article_id).first()
    if article is None or not article.is_published:
        # A deleted or unpublished article must not leave retrievable vectors
        # behind: they outlive the row and a filter can match them.
        remove_article_vectors(article_id)
        return

    chunks = ingest_article(article)
    logger.info('Indexed %s (%s chunks)', article.slug, chunks)
