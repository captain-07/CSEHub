from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import Article, ArticleReaction, REACTION_LIKE
from .management.commands.seed_engagement import DEMO_PREFIX


def make_article(**overrides):
    values = {
        'title': 'Article',
        'slug': 'article',
        'content': {'blocks': []},
        'is_published': True,
    }
    values.update(overrides)
    return Article.objects.create(**values)


class SeedEngagementCommandTests(TestCase):
    def setUp(self):
        self.article = make_article()
        self.draft = make_article(slug='draft', is_published=False)

    def test_adds_reactions_and_views_to_published_articles_only(self):
        call_command(
            'seed_engagement',
            articles=0, minimum=3, maximum=3,
            views_min=3, views_max=3, seed=1, verbosity=0,
        )

        self.article.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.article.like_count + self.article.dislike_count, 3)
        self.assertEqual(self.article.view_count, 3)
        self.assertEqual(self.draft.view_count, 0)
        self.assertEqual(
            ArticleReaction.objects.filter(article=self.article).count(), 3
        )

    def test_dry_run_writes_nothing(self):
        call_command(
            'seed_engagement',
            minimum=3, maximum=3, views_min=3, views_max=3,
            seed=1, dry_run=True, verbosity=0,
        )

        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 0)
        self.assertEqual(ArticleReaction.objects.count(), 0)
        self.assertFalse(
            get_user_model().objects.filter(username__startswith=DEMO_PREFIX).exists()
        )

    def test_reset_removes_only_demo_reader_reactions(self):
        real = get_user_model().objects.create_user(
            email='real@example.com', username='real', password='password'
        )
        ArticleReaction.objects.set_reaction(self.article, real, REACTION_LIKE)

        call_command(
            'seed_engagement',
            minimum=3, maximum=3, views_min=3, views_max=3,
            seed=1, verbosity=0,
        )
        call_command(
            'seed_engagement',
            minimum=0, maximum=0, seed=1, reset_reactions=True,
            no_views=True, verbosity=0,
        )

        self.article.refresh_from_db()
        self.assertEqual(
            ArticleReaction.objects.filter(article=self.article).count(), 1
        )
        self.assertEqual(ArticleReaction.objects.get(article=self.article).user, real)
        self.assertEqual(self.article.like_count, 1)

    def test_likes_only_adds_no_dislikes(self):
        call_command(
            'seed_engagement',
            minimum=3, maximum=3, views_min=3, views_max=3,
            seed=1, likes_only=True, verbosity=0,
        )

        self.article.refresh_from_db()
        self.assertEqual(self.article.like_count, 3)
        self.assertEqual(self.article.dislike_count, 0)

    def test_reactions_are_capped_by_views(self):
        # Asking for 10 reactions with only 5 views must produce 5, not 10.
        call_command(
            'seed_engagement',
            minimum=10, maximum=10, views_min=5, views_max=5,
            seed=1, verbosity=0,
        )

        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 5)
        self.assertEqual(self.article.like_count + self.article.dislike_count, 5)
        self.assertLessEqual(
            self.article.like_count + self.article.dislike_count,
            self.article.view_count,
        )

    def test_reactions_cannot_exceed_the_number_of_demo_readers(self):
        call_command(
            'seed_engagement',
            minimum=5, maximum=5, views_min=5, views_max=5,
            seed=1, articles=1, verbosity=0,
        )
        call_command(
            'seed_engagement',
            minimum=5, maximum=5, views_min=5, views_max=5,
            seed=1, articles=1, verbosity=0,
        )

        # A second run does not add a reader twice, and it does not exceed the
        # 5 fake readers the command created.
        self.assertEqual(ArticleReaction.objects.filter(article=self.article).count(), 5)
