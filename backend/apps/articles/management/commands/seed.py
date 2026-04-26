from django.core.management.base import BaseCommand
from apps.articles.models import Category, Tag, Article, ArticleTag, CodeSnippet


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
        tags = {}
        for name in ['array', 'linked-list', 'tree', 'dp', 'graph', 'recursion']:
            t, _ = Tag.objects.get_or_create(name=name, slug=name)
            tags[name] = t

        self.stdout.write('Seeding articles...')
        article, created = Article.objects.get_or_create(
            slug='two-sum-explained',
            defaults={
                'title': 'Two Sum — Explained',
                'content': (
                    '## Problem\n'
                    'Given an array of integers `nums` and an integer `target`, '
                    'return indices of the two numbers that add up to target.\n\n'
                    '## Approach\n'
                    'Use a hashmap to store complement values as you iterate.\n\n'
                    '## Complexity\n'
                    'Time: O(n) | Space: O(n)'
                ),
                'category': cats['dsa'],
                'is_published': True,
            }
        )
        if created:
            ArticleTag.objects.get_or_create(article=article, tag=tags['array'])
            ArticleTag.objects.get_or_create(article=article, tag=tags['dp'])
            CodeSnippet.objects.get_or_create(
                article=article,
                order=1,
                defaults={
                    'language': 'python',
                    'code': (
                        'def twoSum(nums, target):\n'
                        '    seen = {}\n'
                        '    for i, num in enumerate(nums):\n'
                        '        complement = target - num\n'
                        '        if complement in seen:\n'
                        '            return [seen[complement], i]\n'
                        '        seen[num] = i'
                    ),
                }
            )

        self.stdout.write(self.style.SUCCESS('Seed complete.'))