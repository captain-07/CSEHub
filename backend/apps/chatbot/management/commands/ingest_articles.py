from django.core.management.base import BaseCommand
from apps.articles.models import Article
from apps.chatbot.ingestion import ingest_article


class Command(BaseCommand):
    help = 'Ingest all published articles into Pinecone'

    def handle(self, *args, **kwargs):
        articles = Article.objects.filter(is_published=True)
        if not articles.exists():
            self.stdout.write(self.style.WARNING('No published articles found.'))
            return

        for article in articles:
            try:
                count = ingest_article(article)
                self.stdout.write(f'  {article.slug} — {count} chunks')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  FAILED {article.slug}: {e}'))

        self.stdout.write(self.style.SUCCESS('Ingestion complete.'))