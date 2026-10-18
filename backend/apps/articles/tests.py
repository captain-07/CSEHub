from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase

from rest_framework.test import APITestCase

from .models import (
    Article, ArticleReaction, Category, Tag, SUPPORTED_BLOCK_TYPES,
    REACTION_LIKE, REACTION_DISLIKE,
)


class ArticleAPITests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name='DSA', slug='dsa')
        self.tag = Tag.objects.create(name='Array', slug='array', category=self.category)
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

    def test_public_listing_hides_drafts_from_everyone_including_staff(self):
        """The home page, the article index and the "keep learning" rail all read
        this endpoint. An editor browsing them should see exactly what a reader
        sees, so their own drafts must not appear."""
        self.draft.author = self.staff
        self.draft.save()

        self.client.force_authenticate(self.staff)
        slugs = [item['slug'] for item in self.client.get('/api/articles/').data['results']]
        self.assertIn('public', slugs)
        self.assertNotIn('draft', slugs)

    def test_admin_listing_still_returns_the_callers_own_draft(self):
        """The scope is what the panel opts into; the public listing losing drafts
        must not cost the editor access to their own work."""
        self.draft.author = self.staff
        self.draft.save()

        self.client.force_authenticate(self.staff)
        slugs = [
            item['slug']
            for item in self.client.get('/api/articles/?mine=true').data['results']
        ]
        self.assertIn('draft', slugs)

    def test_superuser_public_listing_is_published_only(self):
        """Superuser bypasses the ownership rule, not the published-only rule."""
        root = get_user_model().objects.create_superuser(
            email='root@example.com', username='root', password='password'
        )
        self.draft.author = root
        self.draft.save()

        self.client.force_authenticate(root)
        slugs = [item['slug'] for item in self.client.get('/api/articles/').data['results']]
        self.assertNotIn('draft', slugs)

    def test_admin_can_still_open_their_own_draft_by_slug(self):
        """Direct retrieval is not the public listing, so the editor keeps the
        ability to open a draft and keep writing it."""
        self.draft.author = self.staff
        self.draft.save()

        self.client.force_authenticate(self.staff)
        response = self.client.get(f'/api/articles/{self.draft.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['slug'], 'draft')

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

        `mine=true` is required for the falsy forms: drafts only exist inside
        the admin panel's own-articles scope. Without a staff user the draft is
        hidden by `get_queryset` regardless of the filter, which would make a
        broken `false` value look correct.
        """
        self.client.force_authenticate(self.staff)
        for value, expected in (
            ('true', {'public'}),
            ('1', {'public'}),
            ('false', {'draft'}),
            ('0', {'draft'}),
        ):
            with self.subTest(is_published=value):
                response = self.client.get(f'/api/articles/?mine=true&is_published={value}')
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

    def test_seeded_tags_belong_to_a_category(self):
        """Every tag is filed under one category, which the FK now requires."""
        self.call_seed()
        tags = Tag.objects.all()
        self.assertTrue(tags.exists())
        for tag in tags:
            self.assertIsNotNone(
                tag.category, f'seeded tag {tag.slug} has no category'
            )


class TagCategoryTests(APITestCase):
    """A tag belongs to exactly one category; a category groups many tags."""

    def setUp(self):
        self.dsa = Category.objects.create(name='DSA', slug='dsa')
        self.system_design = Category.objects.create(name='System Design', slug='system-design')
        self.tag = Tag.objects.create(name='Array', slug='array', category=self.dsa)
        Tag.objects.create(name='Graph', slug='graph', category=self.system_design)
        self.staff = get_user_model().objects.create_user(
            email='staff@example.com', username='staff', password='password', is_staff=True
        )

    def test_tag_payload_includes_its_category(self):
        response = self.client.get(f'/api/tags/{self.tag.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['category']['slug'], 'dsa')

    def test_tags_can_be_filtered_by_category(self):
        response = self.client.get('/api/tags/?category__slug=dsa')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['slug'] for item in response.data['results']], ['array'])

    def test_creating_a_tag_requires_a_category(self):
        self.client.force_authenticate(self.staff)
        missing = self.client.post('/api/tags/', {'name': 'Tree', 'slug': 'tree'}, format='json')
        self.assertEqual(missing.status_code, 400)
        self.assertIn('category_id', missing.data)

        created = self.client.post(
            '/api/tags/',
            {'name': 'Tree', 'slug': 'tree', 'category_id': self.dsa.pk},
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(Tag.objects.get(slug='tree').category, self.dsa)

    def test_deleting_a_category_with_tags_is_refused(self):
        self.client.force_authenticate(self.staff)
        response = self.client.delete(f'/api/categories/{self.dsa.pk}/')
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Category.objects.filter(pk=self.dsa.pk).exists())

    def test_deleting_an_empty_category_is_allowed(self):
        self.client.force_authenticate(self.staff)
        empty = Category.objects.create(name='Web Dev', slug='web-dev')
        self.assertEqual(self.client.delete(f'/api/categories/{empty.pk}/').status_code, 204)


class ArticleReactionTests(APITestCase):
    """Reader likes and dislikes.

    Two things are being defended here. First, the counts shown to readers must
    match the stored reactions exactly, because they are denormalized onto the
    article and a wrong number is silently public. Second, a reader may hold at
    most one verdict per article, which the database enforces rather than the
    view layer.
    """

    def setUp(self):
        self.article = Article.objects.create(
            title='Public', slug='public', content={'blocks': []}, is_published=True
        )
        self.draft = Article.objects.create(
            title='Draft', slug='draft', content={'blocks': []}, is_published=False
        )
        self.reader = get_user_model().objects.create_user(
            email='reader@example.com', username='reader', password='password'
        )
        self.other = get_user_model().objects.create_user(
            email='other@example.com', username='other', password='password'
        )

    def react(self, value, slug=None, user=None):
        self.client.force_authenticate(user or self.reader)
        return self.client.post(
            f'/api/articles/{slug or self.article.slug}/react/',
            {'value': value},
            format='json',
        )

    def counts(self, article=None):
        article = article or self.article
        article.refresh_from_db()
        return article.like_count, article.dislike_count

    # --- authorization ---

    def test_anonymous_readers_cannot_react(self):
        response = self.client.post(
            f'/api/articles/{self.article.slug}/react/',
            {'value': REACTION_LIKE},
            format='json',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.counts(), (0, 0))

    def test_a_regular_reader_can_react(self):
        """Reacting is not an admin capability: any signed-in reader may."""
        response = self.react(REACTION_LIKE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['value'], REACTION_LIKE)

    def test_readers_cannot_react_to_an_unpublished_article(self):
        response = self.react(REACTION_LIKE, slug=self.draft.slug)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ArticleReaction.objects.count(), 0)

    def test_an_unknown_value_is_rejected(self):
        response = self.react('love')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ArticleReaction.objects.count(), 0)

    def test_a_missing_value_is_rejected(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            f'/api/articles/{self.article.slug}/react/', {}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    # --- one verdict per reader ---

    def test_switching_from_like_to_dislike_moves_rather_than_adds(self):
        self.react(REACTION_LIKE)
        response = self.react(REACTION_DISLIKE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['value'], REACTION_DISLIKE)
        self.assertEqual(ArticleReaction.objects.filter(user=self.reader).count(), 1)
        self.assertEqual(self.counts(), (0, 1))

    def test_repeating_the_same_value_does_not_double_count(self):
        """The endpoint is explicit rather than a toggle, so a duplicated request
        from a flaky connection must converge instead of flipping the verdict."""
        self.react(REACTION_LIKE)
        response = self.react(REACTION_LIKE)

        self.assertEqual(response.data['like_count'], 1)
        self.assertEqual(self.counts(), (1, 0))

    def test_clearing_removes_the_reaction(self):
        self.react(REACTION_LIKE)
        response = self.react('none')

        self.assertEqual(response.data['value'], None)
        self.assertEqual(ArticleReaction.objects.count(), 0)
        self.assertEqual(self.counts(), (0, 0))

    def test_clearing_without_a_reaction_is_a_no_op(self):
        response = self.react('none')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['value'], None)
        self.assertEqual(self.counts(), (0, 0))

    def test_the_database_forbids_two_reactions_from_one_reader(self):
        """Backs the invariant at the layer that actually guarantees it, so a
        future code path cannot reintroduce the double-vote."""
        ArticleReaction.objects.create(
            article=self.article, user=self.reader, value=REACTION_LIKE
        )
        with self.assertRaises(IntegrityError):
            ArticleReaction.objects.create(
                article=self.article, user=self.reader, value=REACTION_DISLIKE
            )

    def test_readers_react_independently(self):
        self.react(REACTION_LIKE, user=self.reader)
        self.react(REACTION_DISLIKE, user=self.other)
        self.assertEqual(self.counts(), (1, 1))

    # --- counts and exposure ---

    def test_the_response_reports_the_fresh_counts(self):
        """The UI settles its buttons from this payload and must not have to
        re-fetch the article."""
        self.react(REACTION_LIKE, user=self.reader)
        response = self.react(REACTION_DISLIKE, user=self.other)
        self.assertEqual(response.data['like_count'], 1)
        self.assertEqual(response.data['dislike_count'], 1)

    def test_the_list_endpoint_exposes_counts(self):
        self.react(REACTION_LIKE)
        self.client.force_authenticate(None)
        response = self.client.get('/api/articles/')
        row = response.data['results'][0]
        self.assertEqual(row['like_count'], 1)
        self.assertEqual(row['dislike_count'], 0)

    def test_detail_reports_the_readers_own_reaction(self):
        self.react(REACTION_LIKE)
        response = self.client.get(f'/api/articles/{self.article.slug}/')
        self.assertEqual(response.data['my_reaction'], REACTION_LIKE)

    def test_detail_reports_no_reaction_for_another_reader(self):
        self.react(REACTION_LIKE, user=self.reader)
        self.client.force_authenticate(self.other)
        response = self.client.get(f'/api/articles/{self.article.slug}/')
        self.assertEqual(response.data['my_reaction'], None)

    def test_detail_reports_no_reaction_for_anonymous_readers(self):
        self.react(REACTION_LIKE)
        self.client.force_authenticate(None)
        response = self.client.get(f'/api/articles/{self.article.slug}/')
        self.assertEqual(response.data['my_reaction'], None)

    def test_the_list_endpoint_omits_the_readers_own_reaction(self):
        """It would need a query per row; the detail endpoint carries it instead."""
        self.react(REACTION_LIKE)
        response = self.client.get('/api/articles/')
        self.assertNotIn('my_reaction', response.data['results'][0])

    def test_the_write_serializer_cannot_set_the_counts(self):
        """Counts are derived. A staff PATCH that tried to set them would
        otherwise overwrite the tallies with an arbitrary number."""
        staff = get_user_model().objects.create_user(
            email='staff@example.com', username='staff2', password='password', is_staff=True
        )
        Article.objects.filter(pk=self.article.pk).update(author=staff)
        self.client.force_authenticate(staff)
        response = self.client.patch(
            f'/api/articles/{self.article.slug}/',
            {'like_count': 9999, 'title': 'Renamed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.counts(), (0, 0))

    # --- lifecycle ---

    def test_deleting_an_article_removes_its_reactions(self):
        self.react(REACTION_LIKE)
        self.article.delete()
        self.assertEqual(ArticleReaction.objects.count(), 0)

    def test_deleting_a_reader_removes_their_reactions(self):
        self.react(REACTION_LIKE)
        self.reader.delete()
        self.assertEqual(ArticleReaction.objects.count(), 0)

    def test_recompute_repairs_counts_that_drifted(self):
        """The repair hatch for rows edited outside the manager, e.g. the admin."""
        ArticleReaction.objects.create(
            article=self.article, user=self.reader, value=REACTION_LIKE
        )
        Article.objects.filter(pk=self.article.pk).update(like_count=99, dislike_count=42)

        call_command('recompute_reaction_counts', stdout=StringIO(), stderr=StringIO())

        self.assertEqual(self.counts(), (1, 0))

    def test_recompute_zeroes_articles_whose_reactions_are_gone(self):
        self.react(REACTION_LIKE)
        ArticleReaction.objects.all().delete()
        Article.objects.filter(pk=self.article.pk).update(like_count=5)

        call_command('recompute_reaction_counts', stdout=StringIO(), stderr=StringIO())

        self.assertEqual(self.counts(), (0, 0))


class ArticleViewCountTests(APITestCase):
    """Reads, counted one per reader session by the client.

    The number is denormalized for the same reason as the reaction tallies, so
    what matters is that exactly one place writes it and that a client can never
    set it. Deduplication is *not* tested here: the server keeps no row per view,
    so there is nothing for it to deduplicate against, and that behaviour lives
    in the client's `recordViewOnce`. What is pinned instead is the contract it
    relies on — every request counts, so it has to send exactly one.
    """

    def setUp(self):
        self.article = Article.objects.create(
            title='Public', slug='public', content={'blocks': []}, is_published=True
        )
        self.draft = Article.objects.create(
            title='Draft', slug='draft', content={'blocks': []}, is_published=False
        )
        self.staff = get_user_model().objects.create_user(
            email='staff@example.com', username='staff', password='password', is_staff=True
        )
        self.reader = get_user_model().objects.create_user(
            email='reader@example.com', username='reader', password='password'
        )

    def count_view(self, slug=None):
        return self.client.post(f'/api/articles/{slug or self.article.slug}/view/')

    def view_count(self, article=None):
        article = article or self.article
        article.refresh_from_db()
        return article.view_count

    # --- counting ---

    def test_an_anonymous_read_is_counted(self):
        """Readers are not signed in, so this endpoint must be public."""
        response = self.count_view()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['view_count'], 1)
        self.assertEqual(self.view_count(), 1)

    def test_the_article_can_be_addressed_by_id(self):
        response = self.client.post(f'/api/articles/{self.article.pk}/view/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.view_count(), 1)

    def test_every_request_counts(self):
        """The endpoint does not deduplicate — that is the client's job. Pinned
        so the guarantee `recordViewOnce` depends on cannot drift silently."""
        self.count_view()
        response = self.count_view()
        self.assertEqual(response.data['view_count'], 2)
        self.assertEqual(self.view_count(), 2)

    def test_a_get_does_not_count(self):
        """The action is POST-only, so a crawler or a prefetch cannot tally."""
        response = self.client.get(f'/api/articles/{self.article.slug}/view/')
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.view_count(), 0)

    def test_an_unpublished_article_cannot_be_counted(self):
        response = self.count_view(slug=self.draft.slug)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.view_count(self.draft), 0)

    def test_an_unknown_slug_is_not_counted(self):
        self.assertEqual(self.count_view(slug='does-not-exist').status_code, 404)

    # --- who counts ---

    def test_a_signed_in_reader_still_counts(self):
        """Only staff are exempt: an ordinary signed-in reader is who the number
        is for."""
        self.client.force_authenticate(self.reader)
        response = self.count_view()
        self.assertEqual(response.data['view_count'], 1)
        self.assertEqual(self.view_count(), 1)

    def test_a_staff_read_is_acknowledged_but_not_counted(self):
        """Otherwise every time an editor opened their own work to check it, the
        article would report another reader who never existed."""
        self.client.force_authenticate(self.staff)
        response = self.count_view()
        self.assertEqual(response.status_code, 200)
        # Still answered, so the client settles on the true total rather than
        # treating the request as a failure.
        self.assertEqual(response.data['view_count'], 0)
        self.assertEqual(self.view_count(), 0)

    def test_a_staff_read_reports_the_current_total(self):
        self.count_view()
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.count_view().data['view_count'], 1)

    # --- exposure ---

    def test_the_list_endpoint_exposes_the_count(self):
        self.count_view()
        row = self.client.get('/api/articles/').data['results'][0]
        self.assertEqual(row['view_count'], 1)

    def test_the_detail_endpoint_exposes_the_count(self):
        self.count_view()
        response = self.client.get(f'/api/articles/{self.article.slug}/')
        self.assertEqual(response.data['view_count'], 1)

    def test_articles_can_be_ordered_by_views(self):
        other = Article.objects.create(
            title='Other', slug='other', content={'blocks': []}, is_published=True
        )
        Article.objects.filter(pk=other.pk).update(view_count=5)

        page = self.client.get('/api/articles/?ordering=-view_count')

        self.assertEqual([row['slug'] for row in page.data['results']], ['other', 'public'])

    def test_the_write_serializer_cannot_set_the_count(self):
        """It is a tally, not a field. A staff PATCH that carried one would
        otherwise overwrite the number with whatever the client sent."""
        Article.objects.filter(pk=self.article.pk).update(author=self.staff)
        self.client.force_authenticate(self.staff)
        response = self.client.patch(
            f'/api/articles/{self.article.slug}/',
            {'view_count': 9999, 'title': 'Renamed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.view_count(), 0)

    # --- the single writer ---

    def test_record_view_returns_the_new_total(self):
        article = Article.objects.get(pk=self.article.pk)
        self.assertEqual(article.record_view(), 1)
        # The instance was refreshed, so the caller does not have to re-fetch it
        # the way `react` has to.
        self.assertEqual(article.view_count, 1)
        self.assertEqual(article.record_view(), 2)

    def test_record_view_does_not_count_as_an_edit(self):
        """`updated_at` is `auto_now`, but the increment goes through
        `QuerySet.update()`, which bypasses it. If a read bumped the timestamp,
        every article would look freshly modified the moment anyone opened it."""
        before = Article.objects.get(pk=self.article.pk).updated_at

        self.article.record_view()

        self.assertEqual(Article.objects.get(pk=self.article.pk).updated_at, before)


class ArticleVideoTests(APITestCase):
    """The optional per-article video link.

    It is an ordinary `URLField` on the article — one video, chosen by the
    editor, and usually absent. Two things are worth pinning: that it survives
    the write path at all, and that a non-URL is refused up front. The reader
    always builds the player from a *derived* embed URL (see `videoEmbed` in
    renderer.js), so a stored value can never become a frame source on its own,
    but junk would still surface as a broken link card.
    """

    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email='staff@example.com', username='staff', password='password', is_staff=True
        )
        self.article = Article.objects.create(
            title='With video', slug='with-video', content={'blocks': []}, is_published=True
        )

    def patch(self, **body):
        return self.client.patch(
            f'/api/articles/{self.article.slug}/', body, format='json'
        )

    def test_the_field_is_optional(self):
        """Most articles have no video, so the default has to be a blank string
        rather than null — the reader renders on presence, not on `None`."""
        response = self.client.get(f'/api/articles/{self.article.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['video_url'], '')

    def test_a_video_url_round_trips_through_a_write(self):
        self.client.force_authenticate(self.staff)
        response = self.patch(video_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ')

        self.assertEqual(response.status_code, 200)
        self.article.refresh_from_db()
        self.assertEqual(
            self.article.video_url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        )

    def test_a_non_url_is_rejected(self):
        self.client.force_authenticate(self.staff)
        response = self.patch(video_url='javascript:alert(1)')

        self.assertEqual(response.status_code, 400)
        self.assertIn('video_url', response.data)

    def test_the_list_endpoint_exposes_the_video_url(self):
        Article.objects.filter(pk=self.article.pk).update(
            video_url='https://vimeo.com/123456789'
        )
        row = self.client.get('/api/articles/').data['results'][0]
        self.assertEqual(row['video_url'], 'https://vimeo.com/123456789')

