from django.core.management.base import BaseCommand, CommandError

from apps.articles.models import Article
from apps.articles.quiz_ai import (
    DEFAULT_QUESTION_COUNT,
    MAX_QUESTIONS_PER_REQUEST,
    QuizGenerationError,
    generate_quiz_questions,
)


class Command(BaseCommand):
    help = 'Generate reviewable AI quiz questions for one article'

    def add_arguments(self, parser):
        parser.add_argument('slug', help='Slug of the article to generate questions for.')
        parser.add_argument(
            '--count',
            type=int,
            default=DEFAULT_QUESTION_COUNT,
            help=f'How many questions to request (1-{MAX_QUESTIONS_PER_REQUEST}).',
        )
        parser.add_argument(
            '--replace-ai',
            action='store_true',
            help='Remove earlier AI-generated questions first. Hand-written questions are kept.',
        )
        parser.add_argument(
            '--activate',
            action='store_true',
            help='Make the generated questions reader-visible immediately. Review first.',
        )

    def handle(self, *args, **options):
        count = options['count']
        if not 1 <= count <= MAX_QUESTIONS_PER_REQUEST:
            raise CommandError(
                f'--count must be between 1 and {MAX_QUESTIONS_PER_REQUEST}.'
            )

        article = Article.objects.filter(slug=options['slug']).first()
        if article is None:
            raise CommandError(f'No article found with slug "{options["slug"]}".')

        try:
            created, rejected = generate_quiz_questions(
                article,
                count,
                replace_ai=options['replace_ai'],
                activate=options['activate'],
            )
        except QuizGenerationError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Generated {len(created)} question(s) for {article.slug}; '
                f'{rejected} rejected by validation.'
            )
        )
        if not options['activate']:
            self.stdout.write(
                'The new questions are inactive — review and activate them in the Django admin.'
            )
