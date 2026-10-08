from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APITestCase

from .models import Article, Category, Tag, SUPPORTED_BLOCK_TYPES


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
            title='Public', slug='public', content={'blocks': []}, category=self.category, is_published=True
        )
        self.draft = Article.objects.create(
            title='Draft', slug='draft', content={'blocks': []}, category=self.category
        )

    def test_public_users_only_see_published_articles(self):
        response = self.client.get('/api/articles/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['slug'] for item in response.data['results']], ['public'])
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 404)

    def test_article_detail_lookup_by_slug_and_id_fallback(self):
        by_slug = self.client.get(f'/api/articles/{self.published.slug}/')
        self.assertEqual(by_slug.status_code, 200)
        self.assertEqual(by_slug.data['slug'], self.published.slug)

        by_id = self.client.get(f'/api/articles/{self.published.pk}/')
        self.assertEqual(by_id.status_code, 200)
        self.assertEqual(by_id.data['slug'], self.published.slug)
        self.assertEqual(by_slug.data['id'], by_id.data['id'])

    def test_staff_can_manage_drafts_and_write_relationships(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 200)
        payload = {
            'title': 'Created', 'slug': 'created', 'content': {'blocks': [{'type': 'paragraph', 'data': {'text': 'body'}}]},
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

    def test_mine_filter_narrows_the_admin_list_to_their_own_articles(self):
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.published.author = other
        self.published.save()
        self.draft.author = self.staff
        self.draft.save()

        self.client.force_authenticate(self.staff)
        slugs = [
            item['slug']
            for item in self.client.get('/api/articles/?mine=true').data['results']
        ]
        self.assertIn('draft', slugs)
        self.assertNotIn('public', slugs)

    def test_mine_filter_does_not_hide_published_articles_from_the_public_site(self):
        """The admin panel and the public listing share this endpoint."""
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.published.author = other
        self.published.save()

        self.client.force_authenticate(self.staff)
        slugs = [item['slug'] for item in self.client.get('/api/articles/').data['results']]
        self.assertIn('public', slugs)

    def test_mine_filter_is_ignored_for_a_non_staff_caller(self):
        """It must never widen what `get_queryset` already permits."""
        self.published.author = self.staff
        self.published.save()
        self.draft.author = None
        self.draft.save()

        slugs = [item['slug'] for item in self.client.get('/api/articles/?mine=true').data['results']]
        self.assertEqual(slugs, ['public'])

    def test_mine_filter_is_ignored_for_a_superuser(self):
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.published.author = other
        self.published.save()
        root = get_user_model().objects.create_superuser(
            email='root@example.com', username='root', password='password'
        )
        self.client.force_authenticate(root)
        slugs = [
            item['slug'] for item in self.client.get('/api/articles/?mine=true').data['results']
        ]
        self.assertIn('public', slugs)

    def test_mine_filter_still_hides_other_authors_drafts(self):
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.draft.author = other
        self.draft.save()
        self.client.force_authenticate(self.staff)
        slugs = [item['slug'] for item in self.client.get('/api/articles/?mine=true').data['results']]
        self.assertNotIn('draft', slugs)

    def test_staff_cannot_see_or_edit_another_authors_article(self):
        """Write access is per-author, not merely 'is staff'."""
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.published.author = other
        self.published.save()

        self.client.force_authenticate(self.staff)
        # Published content stays visible (it is public anyway), but writes and
        # deletes are refused — being able to read is not being able to edit.
        self.assertEqual(self.client.get(f'/api/articles/{self.published.pk}/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/articles/{self.published.pk}/', {'title': 'Hijacked'}, format='json').status_code,
            403,
        )
        self.assertEqual(self.client.delete(f'/api/articles/{self.published.pk}/').status_code, 403)
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, 'Public')

    def test_staff_cannot_touch_another_authors_draft_by_direct_url(self):
        """A draft is not public, so it must not even be readable — and a direct
        lookup must not be a way around the list filter."""
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.draft.author = other
        self.draft.save()

        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 404)
        self.assertEqual(
            self.client.patch(f'/api/articles/{self.draft.pk}/', {'title': 'Hijacked'}, format='json').status_code,
            404,
        )
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.title, 'Draft')

    def test_staff_sees_their_own_drafts_but_not_another_authors_draft(self):
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.draft.author = other
        self.draft.save()
        self.client.force_authenticate(self.staff)
        slugs = [item['slug'] for item in self.client.get('/api/articles/').data['results']]
        self.assertIn('public', slugs)
        self.assertNotIn('draft', slugs)

    def test_staff_sees_another_authors_published_article_read_only(self):
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.published.author = other
        self.published.save()
        self.client.force_authenticate(self.staff)
        # Published work is public, so it stays readable — only writes are scoped.
        self.assertEqual(self.client.get(f'/api/articles/{self.published.pk}/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/articles/{self.published.pk}/', {'title': 'Nope'}, format='json').status_code,
            403,
        )
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, 'Public')

    def test_unattributed_article_stays_reachable(self):
        """`author` is nullable, so such content must not become unreachable."""
        self.assertIsNone(self.draft.author)
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/articles/{self.draft.pk}/', {'title': 'Adopted'}, format='json').status_code,
            200,
        )

    def test_superuser_can_edit_any_article(self):
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        root = get_user_model().objects.create_superuser(
            email='root@example.com', username='root', password='password'
        )
        self.published.author = other
        self.published.save()

        self.client.force_authenticate(root)
        listing = self.client.get('/api/articles/')
        self.assertIn('public', [item['slug'] for item in listing.data['results']])
        self.assertEqual(self.client.get(f'/api/articles/{self.draft.pk}/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/articles/{self.published.pk}/', {'title': 'Edited'}, format='json').status_code,
            200,
        )

    def test_normal_user_cannot_write(self):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/', {'title': 'No', 'slug': 'no', 'content': {'blocks': []}}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_write(self):
        response = self.client.post('/api/articles/', {'title': 'No', 'slug': 'no2', 'content': {'blocks': []}}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_normal_user_cannot_mutate_or_delete_existing_article(self):
        """The frontend hides these controls; the API must still refuse them."""
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.patch(f'/api/articles/{self.published.pk}/', {'is_published': False}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/articles/{self.published.pk}/').status_code, 403)
        self.published.refresh_from_db()
        self.assertTrue(self.published.is_published, 'article must not have been modified')

    def test_pagination_has_drfs_urls(self):
        for number in range(25):
            Article.objects.create(title=f'Article {number}', slug=f'article-{number}', content={'blocks': []}, is_published=True)
        response = self.client.get('/api/articles/?page=2')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/api/articles/', response.data['previous'])

    def test_category_and_tag_writes_are_admin_only(self):
        """Reads stay public; writes are refused for anonymous and normal users."""
        self.assertEqual(self.client.get('/api/categories/').status_code, 200)
        self.assertEqual(self.client.get('/api/tags/').status_code, 200)

        self.assertEqual(
            self.client.post('/api/categories/', {'name': 'X', 'slug': 'x'}, format='json').status_code,
            401,
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.post('/api/categories/', {'name': 'X', 'slug': 'x'}, format='json').status_code,
            403,
        )
        self.assertEqual(
            self.client.post('/api/tags/', {'name': 'Y', 'slug': 'y'}, format='json').status_code,
            403,
        )

        self.client.force_authenticate(self.staff)
        created = self.client.post('/api/categories/', {'name': 'Algorithms', 'slug': 'algorithms'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(self.client.delete(f'/api/categories/{created.data["id"]}/').status_code, 204)

    def test_malformed_editorjs_content_is_rejected(self):
        self.client.force_authenticate(self.staff)
        for payload in (
            {'title': 'Bad', 'slug': 'bad-1', 'content': 'plain string'},
            {'title': 'Bad', 'slug': 'bad-2', 'content': {'no_blocks': True}},
            {'title': 'Bad', 'slug': 'bad-3', 'content': {'blocks': [{'type': 'evil', 'data': {}}]}},
            {'title': 'Bad', 'slug': 'bad-4', 'content': {'blocks': [{'type': 'header', 'data': 'not-a-dict'}]}},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post('/api/articles/', payload, format='json').status_code,
                    400,
                )

    def test_slug_is_derived_and_deduplicated(self):
        self.client.force_authenticate(self.staff)
        first = self.client.post(
            '/api/articles/', {'title': 'Binary Search', 'slug': '', 'content': {'blocks': []}}, format='json'
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data['slug'], 'binary-search')

        second = self.client.post(
            '/api/articles/', {'title': 'Binary Search', 'slug': '', 'content': {'blocks': []}}, format='json'
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data['slug'], 'binary-search-2')

    def test_is_featured_can_be_filtered(self):
        Article.objects.create(title='Star', slug='star', content={'blocks': []}, is_published=True, is_featured=True)
        response = self.client.get('/api/articles/?is_featured=true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['slug'] for item in response.data['results']], ['star'])

    def test_is_published_can_be_filtered_for_staff(self):
        """The admin list filters by status, so both truthy and falsy forms work.

        Without a staff user the draft is hidden by `get_queryset` regardless of
        the filter, which would make a broken `false` value look correct.
        """
        self.client.force_authenticate(self.staff)
        for value, expected in (
            ('true', {'public'}),
            ('1', {'public'}),
            ('false', {'draft'}),
            ('0', {'draft'}),
        ):
            with self.subTest(is_published=value):
                response = self.client.get(f'/api/articles/?is_published={value}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {item['slug'] for item in response.data['results']},
                    expected,
                )

    def test_reindex_requires_admin_and_published_article(self):
        self.assertEqual(
            self.client.post(f'/api/articles/{self.published.pk}/reindex/').status_code, 401
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.post(f'/api/articles/{self.published.pk}/reindex/').status_code, 403
        )
        self.client.force_authenticate(self.staff)
        # Unpublished articles cannot be indexed.
        self.assertEqual(
            self.client.post(f'/api/articles/{self.draft.pk}/reindex/').status_code, 409
        )

    def test_list_endpoint_exposes_author_name(self):
        """Cards are built from the list endpoint, so a byline missing here means
        no article grid can ever show an author."""
        self.staff.display_name = 'Debjyoti Saha'
        self.staff.save()
        self.published.author = self.staff
        self.published.save()

        response = self.client.get('/api/articles/')
        self.assertEqual(response.status_code, 200)
        item = next(r for r in response.data['results'] if r['slug'] == 'public')
        self.assertEqual(item['author_name'], 'Debjyoti Saha')
        self.assertEqual(item['author_email'], 'staff@example.com')

    def test_list_endpoint_tolerates_an_unattributed_article(self):
        """Article.author is nullable, so seeded and imported rows may have none."""
        response = self.client.get('/api/articles/')
        self.assertEqual(response.status_code, 200)
        item = next(r for r in response.data['results'] if r['slug'] == 'public')
        self.assertIsNone(item['author_name'])
        self.assertIsNone(item['author_email'])

    def test_staff_cannot_reassign_the_author(self):
        """Ownership is what grants write access, so it must not be client-writable."""
        self.client.force_authenticate(self.staff)
        response = self.client.patch(
            f'/api/articles/{self.published.pk}/', {'author': self.user.pk}, format='json'
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.published.refresh_from_db()
        self.assertIsNone(self.published.author)

    def test_staff_cannot_claim_an_article_by_reassigning_it_to_themselves(self):
        """The escalation path: seize an article, then edit it under the new owner."""
        other = get_user_model().objects.create_user(
            email='other-staff@example.com', username='other-staff', is_staff=True
        )
        self.published.author = other
        self.published.save()

        self.client.force_authenticate(self.staff)
        response = self.client.patch(
            f'/api/articles/{self.published.pk}/', {'author': self.staff.pk}, format='json'
        )
        # The queryset scopes writes, so the article is out of reach entirely.
        self.assertIn(response.status_code, (400, 403, 404), response.data)
        self.published.refresh_from_db()
        self.assertEqual(self.published.author, other)

    def test_superuser_may_reassign_the_author(self):
        root = get_user_model().objects.create_superuser(
            email='root@example.com', username='root', password='password'
        )
        self.client.force_authenticate(root)
        response = self.client.patch(
            f'/api/articles/{self.published.pk}/', {'author': self.staff.pk}, format='json'
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.published.refresh_from_db()
        self.assertEqual(self.published.author, self.staff)

    def test_detail_exposes_author_name_without_requiring_the_client_to_derive_it(self):
        self.staff.display_name = 'Debjyoti Saha'
        self.staff.save()
        self.published.author = self.staff
        self.published.save()

        response = self.client.get(f'/api/articles/{self.published.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['author_name'], 'Debjyoti Saha')
        # Falls back to the username, then the email, when no display name is set.
        self.staff.display_name = ''
        self.staff.save()
        self.published.refresh_from_db()
        response = self.client.get(f'/api/articles/{self.published.pk}/')
        self.assertEqual(response.data['author_name'], self.staff.username)

    def test_every_supported_block_type_round_trips(self):
        """The serializer allow-list is the contract the editor toolbar is built on."""
        self.client.force_authenticate(self.staff)
        blocks = [
            {'type': 'paragraph', 'data': {'text': 'Body <b>bold</b>'}},
            {'type': 'header', 'data': {'text': 'Section', 'level': 2}},
            {'type': 'list', 'data': {'style': 'unordered', 'items': [{'content': 'One'}]}},
            {'type': 'quote', 'data': {'text': 'Quoted', 'caption': 'Someone'}},
            {'type': 'code', 'data': {'code': 'print(1)', 'language': 'python'}},
            {'type': 'image', 'data': {'file': {'url': 'https://example.com/a.png'}, 'caption': 'Fig'}},
            {'type': 'delimiter', 'data': {}},
            {'type': 'linkTool', 'data': {'url': 'https://example.com', 'text': 'Link'}},
        ]
        self.assertEqual(
            {block['type'] for block in blocks},
            set(SUPPORTED_BLOCK_TYPES),
            'the test fixture must cover every supported block type',
        )
        response = self.client.post(
            '/api/articles/',
            {'title': 'All blocks', 'slug': 'all-blocks', 'content': {'blocks': blocks}},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        stored = Article.objects.get(slug='all-blocks')
        self.assertEqual(len(stored.content['blocks']), len(blocks))


class SeedAuthorTests(TestCase):
    """`build.sh` runs `manage.py seed` on every deploy, so unattributed seed
    content ships a site where no article shows an author."""

    def call_seed(self):
        call_command('seed', stdout=StringIO(), stderr=StringIO())

    def test_seeded_articles_carry_a_byline(self):
        self.call_seed()
        articles = Article.objects.all()
        self.assertTrue(articles.exists())
        for article in articles:
            self.assertIsNotNone(
                article.author, f'seeded article {article.slug} has no author'
            )

    def test_reseeding_backfills_seeded_articles_that_predate_the_author_column(self):
        """An older deploy seeded content with a null author, so the first run
        after this change must repair those rows, not just brand-new ones."""
        Article.objects.create(
            title='Two Sum — Explained', slug='two-sum-explained',
            content={'blocks': []}, is_published=True,
        )

        self.call_seed()

        self.assertIsNotNone(Article.objects.get(slug='two-sum-explained').author)

    def test_reseeding_does_not_overwrite_an_author_assigned_later(self):
        self.call_seed()
        article = Article.objects.get(slug='two-sum-explained')
        editor = get_user_model().objects.create_user(
            email='editor@example.com', username='editor', is_staff=True
        )
        article.author = editor
        article.save(update_fields=['author'])

        self.call_seed()

        article.refresh_from_db()
        self.assertEqual(article.author, editor)
