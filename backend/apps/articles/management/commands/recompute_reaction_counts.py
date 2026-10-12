from django.core.management.base import BaseCommand

from apps.articles.models import ArticleReaction


class Command(BaseCommand):
    help = (
        'Rebuild Article.like_count and Article.dislike_count from the stored '
        'reactions, repairing any drift caused by hand-edited rows.'
    )

    def handle(self, *args, **options):
        updated = ArticleReaction.objects.recompute_reaction_counts()
        self.stdout.write(
            self.style.SUCCESS(f'Recomputed reaction counts for {updated} article(s).')
        )
