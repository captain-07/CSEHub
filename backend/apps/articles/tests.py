from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Article, Category, CodeSnippet, Tag


class ArticleAPITests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name='DSA', slug='dsa')
        self.tag = Tag.objects.create(name='Array', slug='array')
        self.staff = get_user_model().objects.create_user(
            email='staff@example.com', username='staff', password='password', is_staff=True
        )
        self.user = get_user_model().objects.create_user(
            email='user@example.com', username='user', password='password'
        )
        self.published = Article.objects.create(
            title='Public', slug='public', content='content', category=self.category, is_published=True
        )
        self.draft = Article.objects.create(
            title='Draft', slug='draft', content='content', category=self.category
        )

    def test_public_users_only_see_published_articles(self):
        response = self.client.get('/api/articles/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['slug'] for item in response.data['results']], ['public'])
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 404)

    def test_staff_can_manage_drafts_and_write_relationships(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 200)
        payload = {
            'title': 'Created', 'slug': 'created', 'content': 'body',
            'category': self.category.pk, 'tags': [self.tag.pk], 'is_published': False,
            'code_snippets': [{'language': 'python', 'code': 'print(1)', 'order': 1}],
        }
        response = self.client.post('/api/articles/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        article = Article.objects.get(slug='created')
        self.assertEqual(article.author, self.staff)
        self.assertEqual(list(article.tags.all()), [self.tag])
        self.assertEqual(article.code_snippets.count(), 1)
        self.assertEqual(self.client.patch(f'/api/articles/{article.pk}/', {'is_published': True}, format='json').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/articles/{article.pk}/').status_code, 204)

    def test_normal_user_cannot_write(self):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/', {'title': 'No', 'slug': 'no', 'content': 'no'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_pagination_has_drfs_urls(self):
        for number in range(25):
            Article.objects.create(title=f'Article {number}', slug=f'article-{number}', content='x', is_published=True)
        response = self.client.get('/api/articles/?page=2')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/api/articles/', response.data['previous'])
