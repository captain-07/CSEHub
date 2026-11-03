import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.articles.models import (
    Article,
    ArticleReaction,
    REACTION_DISLIKE,
    REACTION_LIKE,
)

# Fake readers are named so they are obvious in the Django admin and easy to
# remove. `.invalid` is a reserved TLD, so no address can ever receive mail.
DEMO_PREFIX = 'demo_reader_'


class Command(BaseCommand):
    help = (
        'Add synthetic likes, dislikes and views to published articles for demos '
        'and UI testing. Reactions go through set_reaction() and views through '
        'record_view(), so the denormalized counters stay consistent.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--articles', type=int, default=0,
            help='How many published articles to touch (default: all).',
        )
        parser.add_argument(
            '--min', dest='minimum', type=int, default=10,
            help='Minimum reactions per article (default: 10).',
        )
        parser.add_argument(
            '--max', dest='maximum', type=int, default=15,
            help='Maximum reactions per article (default: 15).',
        )
        parser.add_argument(
            '--views-min', type=int, default=40,
            help='Minimum views added per article (default: 40).',
        )
        parser.add_argument(
            '--views-max', type=int, default=80,
            help='Maximum views added per article (default: 80).',
        )
        parser.add_argument(
            '--seed', type=int, default=None,
            help='Seed the RNG so a run can be reproduced.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be added without writing anything.',
        )
        parser.add_argument(
            '--no-views', action='store_true',
            help='Skip view counts (views cannot be undone: there is no row per view).',
        )
        parser.add_argument(
            '--no-reactions', action='store_true',
            help='Skip likes/dislikes.',
        )
        parser.add_argument(
            '--reset-reactions', action='store_true',
            help='Remove demo readers\' reactions from the selected articles first.',
        )
        parser.add_argument(
            '--likes-only', action='store_true',
            help='Only add likes (no dislikes).',
        )

    def handle(self, *args, **options):
        minimum = options['minimum']
        maximum = options['maximum']
        views_minimum = options['views_min']
        views_maximum = options['views_max']
        if minimum < 0 or maximum < minimum:
            raise CommandError('--min must be >= 0 and --max must be >= --min.')
        if maximum > 100:
            raise CommandError('--max is capped at 100 so the command cannot create users by accident.')
        if views_minimum < 0 or views_maximum < views_minimum:
            raise CommandError('--views-min must be >= 0 and --views-max must be >= --views-min.')
        if views_maximum > 10000:
            raise CommandError('--views-max is capped at 10000.')

        rng = random.Random(options['seed'])

        articles = list(Article.objects.filter(is_published=True).order_by('pk'))
        limit = options['articles']
        if limit:
            if limit < 1:
                raise CommandError('--articles must be at least 1, or 0 for all.')
            rng.shuffle(articles)
            articles = articles[:limit]
        if not articles:
            raise CommandError('No published articles found.')

        database = connection.settings_dict
        self.stdout.write(
            f'Database: {database.get("HOST") or "local"} / {database.get("NAME")} '
            f'({len(articles)} published article(s))'
        )

        reset_users = (
            list(get_user_model().objects.filter(username__startswith=DEMO_PREFIX))
            if options['reset_reactions']
            else []
        )
        # A real run resets before planning, so the headroom calculation sees
        # the reactions that will actually remain. A dry run must not write, so
        # `_plan` discounts the demo reactions instead.
        if reset_users and not options['dry_run']:
            for article in articles:
                self._reset(article, reset_users)
            for article in articles:
                article.refresh_from_db()

        plans = [
            self._plan(
                article,
                rng,
                minimum=minimum,
                maximum=maximum,
                views_minimum=views_minimum,
                views_maximum=views_maximum,
                no_reactions=options['no_reactions'],
                no_views=options['no_views'],
                resetting=bool(reset_users and options['dry_run']),
            )
            for article in articles
        ]

        if options['dry_run']:
            for plan in plans:
                capped = ' (capped by views)' if plan['capped'] else ''
                self.stdout.write(
                    f'  would add {plan["reactions"]} reaction(s){capped} and '
                    f'{plan["views"]} view(s) -> {plan["article"].slug}'
                )
            if reset_users:
                self.stdout.write('  would remove existing demo reactions first.')
            self.stdout.write(self.style.WARNING('Dry run: nothing was written.'))
            return

        demo_users = (
            self._demo_users(maximum)
            if not options['no_reactions'] and maximum
            else []
        )

        total_reactions = total_views = capped_articles = 0
        for plan in plans:
            article = plan['article']
            # Views first: reactions are capped against views that exist, so
            # adding them in the other order could momentarily exceed the total.
            for _ in range(plan['views']):
                article.record_view()
            total_views += plan['views']

            if plan['reactions']:
                total_reactions += self._add_reactions(
                    article, demo_users, plan['reactions'], rng,
                    likes_only=options['likes_only'],
                )
            if plan['capped']:
                capped_articles += 1

        self.stdout.write(self.style.SUCCESS(
            f'Added {total_reactions} reaction(s) and {total_views} view(s) '
            f'across {len(plans)} article(s).'
        ))
        if capped_articles:
            self.stdout.write(self.style.WARNING(
                f'{capped_articles} article(s) had reactions capped so they cannot exceed views.'
            ))
        if demo_users:
            self.stdout.write(f'Demo readers available: {len(demo_users)} ({DEMO_PREFIX}*)')

    def _plan(self, article, rng, *, minimum, maximum, views_minimum,
              views_maximum, no_reactions, no_views, resetting=False):
        views = 0 if no_views else rng.randint(views_minimum, views_maximum)
        reactions = 0 if no_reactions else rng.randint(minimum, maximum)

        existing_reactions = article.like_count + article.dislike_count
        if resetting:
            # A dry run cannot delete rows, so discount the demo reactions a
            # real run would remove before measuring the available headroom.
            existing_reactions -= ArticleReaction.objects.filter(
                article=article, user__username__startswith=DEMO_PREFIX
            ).count()
            existing_reactions = max(0, existing_reactions)

        headroom = max(0, (article.view_count + views) - existing_reactions)
        return {
            'article': article,
            'reactions': min(reactions, headroom),
            'views': views,
            'capped': reactions > headroom,
        }

    def _demo_users(self, count):
        """Return `count` clearly-labelled fake readers, creating them if needed."""
        User = get_user_model()
        users = []
        for index in range(1, count + 1):
            username = f'{DEMO_PREFIX}{index:02d}'
            email = f'demo.reader.{index:02d}@example.invalid'
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(
                    username=username,
                    email=email,
                    display_name=f'Demo Reader {index:02d}',
                    is_active=False,
                )
                user.set_unusable_password()
                user.save()
            elif user.email != email:
                raise CommandError(
                    f'{username} already exists with a different email; refusing to '
                    'reuse what may be a real account.'
                )
            users.append(user)
        return users

    def _reset(self, article, users):
        for reaction in ArticleReaction.objects.filter(
            article=article, user__in=users
        ).select_related('user'):
            # `set_reaction(..., None)` deletes the row *and* decrements the
            # article's tally; deleting the row directly would leave it drifting.
            ArticleReaction.objects.set_reaction(article, reaction.user, None)

    def _add_reactions(self, article, users, target, rng, likes_only=False):
        existing = set(
            ArticleReaction.objects.filter(article=article, user__in=users)
            .values_list('user_id', flat=True)
        )
        available = [user for user in users if user.pk not in existing]
        rng.shuffle(available)

        added = 0
        for user in available[:target]:
            value = REACTION_LIKE if likes_only else rng.choice([REACTION_LIKE, REACTION_DISLIKE])
            ArticleReaction.objects.set_reaction(article, user, value)
            added += 1
        return added
