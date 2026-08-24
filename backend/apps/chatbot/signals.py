from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.articles.models import Article
from .ingestion import ingest_article


@receiver(post_save, sender=Article)
def article_post_save(sender, instance, created, **kwargs):
    if instance.is_published:
        try:
            count = ingest_article(instance)
            print(f"[RAG] Ingested '{instance.slug}' — {count} chunks")
        except Exception as e:
            # never let a RAG failure break the article save
            print(f"[RAG] Ingestion failed for '{instance.slug}': {e}")