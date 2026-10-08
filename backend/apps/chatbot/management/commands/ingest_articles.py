from django.core.management.base import BaseCommand, CommandError
from apps.articles.models import Article
from apps.chatbot.ingestion import ingest_article


class Command(BaseCommand):
    help = 'Ingest published articles into the Pinecone vector index'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug',
            help='Only ingest the article with this slug (idempotent — safe to re-run).',
        )

    def handle(self, *args, **options):
        slug = options.get('slug')

        if slug:
            articles = Article.objects.filter(slug=slug, is_published=True)
            if not articles.exists():
                raise CommandError(
                    f'No published article found with slug "{slug}". '
                    'Drafts are not indexed — publish the article first.'
                )
        else:
            articles = Article.objects.filter(is_published=True)

        if not articles.exists():
            self.stdout.write(self.style.WARNING('No published articles found.'))
            return

        failures = []
        for article in articles:
            try:
                count = ingest_article(article)
                self.stdout.write(f'  {article.slug} — {count} chunks')
            except Exception as e:
                failures.append(article.slug)
                self.stdout.write(self.style.ERROR(f'  FAILED {article.slug}: {e}'))

        if failures:
            raise CommandError(f'Ingestion failed for: {", ".join(failures)}')
        self.stdout.write(self.style.SUCCESS('Ingestion complete.'))