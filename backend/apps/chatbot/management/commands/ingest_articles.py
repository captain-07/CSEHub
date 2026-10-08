from django.core.management.base import BaseCommand, CommandError
from apps.articles.models import Article
from apps.chatbot.ingestion import ingest_article, purge_namespace


class Command(BaseCommand):
    help = 'Ingest published articles into the Pinecone vector index'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug',
            help='Only ingest the article with this slug (idempotent — safe to re-run).',
        )
        parser.add_argument(
            '--purge',
            action='store_true',
            help=(
                'Empty the vector namespace before ingesting. Use this when articles '
                'have been deleted or replaced, because per-article re-ingestion leaves '
                'orphan vectors behind and reused ids can then return the wrong content.'
            ),
        )

    def handle(self, *args, **options):
        slug = options.get('slug')
        purge = options.get('purge')

        if purge and slug:
            raise CommandError('--purge cannot be combined with --slug; it clears the whole namespace.')

        if slug:
            articles = Article.objects.filter(slug=slug, is_published=True)
            if not articles.exists():
                raise CommandError(
                    f'No published article found with slug "{slug}". '
                    'Drafts are not indexed — publish the article first.'
                )
        else:
            articles = Article.objects.filter(is_published=True)

        if purge:
            try:
                purge_namespace()
            except Exception as e:
                raise CommandError(f'Could not purge the vector namespace: {e}')
            self.stdout.write(self.style.WARNING('Purged the vector namespace.'))

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