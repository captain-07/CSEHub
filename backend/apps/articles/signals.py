"""Keep the vector index in step with the article table.

These handlers do no network work. They enqueue one id after the transaction
that saved the article commits; `apps.chatbot.indexing` owns the rest.

Comparing the indexed inputs before and after the save is what stops a
`is_featured` toggle, an author backfill or a view-count write from paying for a
re-embedding. `record_view()` and the reaction tallies use `QuerySet.update()`,
which bypasses `save()` and therefore these signals entirely.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.chatbot.indexing import enqueue_reindex
from .models import Article

# The fields `ingest_article` actually embeds. Anything else (is_featured,
# author, cover image, timestamps) cannot change the vectors, so it must not
# trigger a reindex.
INDEXED_FIELDS = ('title', 'excerpt', 'content', 'is_published')


@receiver(pre_save, sender=Article)
def _capture_index_inputs(sender, instance, **kwargs):
    """Remember the stored values so `post_save` can tell what really changed."""
    if instance.pk is None:
        instance._index_inputs_before = None
        return
    instance._index_inputs_before = (
        sender.objects.filter(pk=instance.pk).values(*INDEXED_FIELDS).first()
    )


@receiver(post_save, sender=Article)
def _reindex_on_publish_or_edit(sender, instance, created, **kwargs):
    before = getattr(instance, '_index_inputs_before', None)
    current = {field: getattr(instance, field) for field in INDEXED_FIELDS}
    was_published = bool(before and before['is_published'])

    # Drafts are not retrievable, so creating or editing one must not call a
    # provider. Unpublishing is handled below, because it has to remove vectors.
    if not instance.is_published and not was_published:
        return

    if not created and before == current:
        return

    article_id = instance.pk
    # The worker must not read the row before this transaction commits.
    transaction.on_commit(lambda: enqueue_reindex(article_id))


@receiver(post_delete, sender=Article)
def _remove_vectors_on_delete(sender, instance, **kwargs):
    article_id = instance.pk
    # The row is gone by the time this runs, so the worker takes the
    # "not published" branch and deletes the vectors for this id.
    transaction.on_commit(lambda: enqueue_reindex(article_id))
