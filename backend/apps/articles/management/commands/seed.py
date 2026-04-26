from django.core.management.base import BaseCommand
from apps.articles.models import Category, Tag, Article
# from apps.problems.models import Problem, TestCase


class Command(BaseCommand):
    help = 'Seed database with sample data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding categories...')
        cats = {}
        for name, slug in [
            ('DSA', 'dsa'),
            ('System Design', 'system-design'),
            ('Web Dev', 'web-dev'),
            ('Core CS', 'core-cs'),
        ]:
            c, _ = Category.objects.get_or_create(name=name, slug=slug)
            cats[slug] = c

        self.stdout.write('Seeding tags...')
        for name in ['array', 'linked-list', 'tree', 'dp', 'graph', 'recursion']:
            Tag.objects.get_or_create(name=name, slug=name)

        self.stdout.write('Seeding articles...')
        Article.objects.get_or_create(
            slug='two-sum-explained',
            defaults={
                'title': 'Two Sum — Explained',
                'content': '## Problem Given an array of integers nums and an integer target...',
                'category': cats['dsa'],
                'is_published': True,
            }
        )

        # self.stdout.write('Seeding problems...')
        # p, _ = Problem.objects.get_or_create(
        #     slug='two-sum',
        #     defaults={
        #         'title': 'Two Sum',
        #         'description': 'Given an array of integers, return indices of the two numbers that add up to target.',
        #         'difficulty': 'easy',
        #         'category': cats['dsa'],
        #         'is_published': True,
        #     }
        # )
        # TestCase.objects.get_or_create(
        #     problem=p,
        #     input='[2,7,11,15]9',
        #     defaults={'expected_output': '[0,1]', 'is_hidden': False}
        # )
        # TestCase.objects.get_or_create(
        #     problem=p,
        #     input='[3,2,4]6',
        #     defaults={'expected_output': '[1,2]', 'is_hidden': True}
        # )

        # self.stdout.write(self.style.SUCCESS('Done. Seed complete.'))
