"""Tests for image optimisation, uploads and storage-provider portability."""

import io
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase

from apps.articles.models import Article
from apps.articles.image_processing import optimise_image
from apps.articles.storage import strip_extension
from apps.articles.media import provider_max_upload_bytes

from PIL import Image, ImageDraw


def make_image(size=(2400, 1800), mode='RGB', fmt='JPEG', colour=(30, 90, 160), **kwargs):
    """A real, decodable image — the endpoint relies on Pillow, not magic bytes."""
    buffer = io.BytesIO()
    Image.new(mode, size, colour).save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def make_animated_gif(frames=4, size=(600, 400)):
    buffer = io.BytesIO()
    pil_frames = [Image.new('RGB', size, (i * 60, 100, 200)) for i in range(frames)]
    pil_frames[0].save(
        buffer, format='GIF', save_all=True, append_images=pil_frames[1:],
        duration=100, loop=0,
    )
    return buffer.getvalue()


# Tests must never write to real object storage. Without this pin, a developer
# with USE_REMOTE_STORAGE=True in their .env would have the suite silently
# upload fixtures to their production bucket (and fail, or worse, pollute it).
LOCAL_STORAGE_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class ImageOptimisationTests(SimpleTestCase):
    """Optimisation is the bandwidth lever, so it is worth asserting precisely."""

    @override_settings(IMAGE_MAX_DIMENSION=800, IMAGE_WEBP_QUALITY=70, IMAGE_WEBP_METHOD=4)
    def test_large_photo_is_downscaled_and_reencoded(self):
        result = optimise_image(make_image((2400, 1800)), '.jpg')

        self.assertEqual(max(result.width, result.height), 800)
        self.assertEqual(result.extension, '.webp')
        self.assertEqual(result.content_type, 'image/webp')
        # 2400x1800 solid colour -> must be a large saving, not a rounding error.
        self.assertGreater(result.saved_ratio, 0.5)

    def test_small_images_are_never_upscaled(self):
        result = optimise_image(make_image((120, 90)), '.jpg')
        with Image.open(io.BytesIO(result.data)) as image:
            self.assertEqual(image.size, (120, 90))

    def test_transparent_png_keeps_its_alpha_channel(self):
        # Needs genuinely transparent pixels: a solid opaque RGBA image lets the
        # encoder drop an all-255 alpha channel, which is correct behaviour and
        # would not exercise the transparency path.
        image = Image.new('RGBA', (400, 300), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((80, 60, 320, 240), fill=(30, 90, 160, 255))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')

        result = optimise_image(buffer.getvalue(), '.png')
        with Image.open(io.BytesIO(result.data)) as decoded:
            self.assertIn(decoded.mode, ('RGBA', 'LA', 'PA'))
            self.assertLess(decoded.convert('RGBA').split()[-1].getextrema()[0], 255)

    def test_exif_is_stripped(self):
        """Screenshots routinely carry GPS and a camera serial; neither is wanted."""
        image = Image.new('RGB', (600, 400), (10, 20, 30))
        exif = image.getexif()
        exif[0x010F] = 'SecretCameraModel'
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', exif=exif)

        result = optimise_image(buffer.getvalue(), '.jpg')
        with Image.open(io.BytesIO(result.data)) as decoded:
            self.assertNotIn(0x010F, dict(decoded.getexif()))

    def test_animated_gif_keeps_all_frames(self):
        """The failure this guards against is silent: one frame looks 'fine'."""
        result = optimise_image(make_animated_gif(frames=6), '.gif')

        self.assertEqual(result.frames, 6)
        with Image.open(io.BytesIO(result.data)) as image:
            self.assertGreater(getattr(image, 'n_frames', 1), 1)
            self.assertTrue(getattr(image, 'is_animated', False))

    def test_corrupt_input_is_stored_unchanged_rather_than_raising(self):
        """A bad optimisation must never block publishing."""
        junk = b'this is definitely not an image'
        result = optimise_image(junk, '.png')

        self.assertEqual(result.data, junk)
        self.assertFalse(result.changed)

    def test_extension_matches_the_encoded_format(self):
        for extension, fmt, mode in (('.png', 'PNG', 'RGB'), ('.jpg', 'JPEG', 'RGB')):
            with self.subTest(extension=extension):
                result = optimise_image(make_image((300, 200), mode=mode, fmt=fmt), extension)
                with Image.open(io.BytesIO(result.data)) as image:
                    self.assertEqual(image.format, result.content_type.split('/')[1].upper())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), STORAGES=LOCAL_STORAGE_STORAGES)
class ImageUploadTests(APITestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email='staff@example.com', username='staff', password='password', is_staff=True
        )
        self.user = get_user_model().objects.create_user(
            email='user@example.com', username='user', password='password'
        )

    def upload(self, name='diagram.png', content_type='image/png', body=None):
        body = make_image((300, 200), fmt='PNG') if body is None else body
        return self.client.post(
            '/api/uploads/images/',
            {'file': SimpleUploadedFile(name, body, content_type=content_type)},
            format='multipart',
        )

    def test_anonymous_and_normal_users_cannot_upload(self):
        self.assertEqual(self.upload().status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.upload().status_code, 403)

    def test_staff_upload_returns_an_absolute_url(self):
        self.client.force_authenticate(self.staff)
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        # Editor.js stores this URL verbatim and the article page is served from
        # a different origin, so it must be absolute.
        self.assertTrue(response.data['url'].startswith('http'), response.data['url'])
        self.assertIn('/media/articles/', response.data['url'])

    def test_stored_file_is_the_optimised_version_not_the_upload(self):
        self.client.force_authenticate(self.staff)
        body = make_image((1600, 1200), fmt='JPEG')
        response = self.client.post(
            '/api/uploads/images/',
            {'file': SimpleUploadedFile('photo.jpg', body, content_type='image/jpeg')},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['url'].endswith('.webp'), response.data['url'])
        self.assertLess(response.data['size'], response.data['original_size'])

        from django.core.files.storage import default_storage
        name = response.data['url'].split('/media/')[-1]
        with default_storage.open(name) as stored:
            self.assertLess(stored.size, len(body))

    def test_client_filename_is_not_reused(self):
        """A traversal-style name must not influence where the file lands."""
        self.client.force_authenticate(self.staff)
        response = self.upload(name='../../etc/passwd.png')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('..', response.data['name'])

    def test_disallowed_content_types_are_refused(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.upload(name='payload.svg', content_type='image/svg+xml', body=b'<svg/>').status_code,
            415,
        )
        self.assertEqual(self.upload(content_type='application/pdf').status_code, 415)

    def test_missing_file_is_a_bad_request(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post('/api/uploads/images/', {}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('file', response.data)

    def test_oversized_undecodable_upload_is_refused(self):
        """Junk is stored unchanged, so the size check must still catch it."""
        self.client.force_authenticate(self.staff)
        response = self.upload(body=b'\x00' * (10 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_oversized_photo_is_accepted_because_it_optimises_under_the_limit(self):
        """A big screenshot is a reasonable upload; the stored result is what counts."""
        self.client.force_authenticate(self.staff)
        body = make_image((4000, 3000), fmt='PNG')
        response = self.client.post(
            '/api/uploads/images/',
            {'file': SimpleUploadedFile('huge.png', body, content_type='image/png')},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertLessEqual(response.data['size'], 10 * 1024 * 1024)
        self.assertLess(response.data['size'], len(body))

    def test_upload_reports_dimensions_for_the_editor(self):
        self.client.force_authenticate(self.staff)
        response = self.upload(body=make_image((900, 500), fmt='PNG'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data['width'], response.data['height']), (900, 500))
        self.assertFalse(response.data['animated'])

    @override_settings(STORAGE_MAX_UPLOAD_BYTES=512)
    def test_provider_ceiling_overrides_the_local_limit(self):
        """Cloudinary's Free plan caps uploads at 10 MB. An image that passes
        every local check must not go on to fail at the provider."""
        self.client.force_authenticate(self.staff)
        response = self.upload(body=make_animated_gif(frames=4, size=(600, 400)))

        # 4 MB of local headroom, but the provider allows 512 bytes.
        self.assertEqual(response.status_code, 413, response.data)
        self.assertIn('512', str(response.data))


class PublicUrlTests(SimpleTestCase):
    """`_public_url` must handle both storage shapes without mangling either."""

    class FakeRequest:
        @staticmethod
        def build_absolute_uri(path):
            return f'https://api.example.com/{path.lstrip("/")}'

    def _url_for(self, stored_url):
        """Resolve `_public_url` against a stub storage returning `stored_url`.

        Patching the module attribute avoids LazyObject's __setattr__ behaviour,
        which `patch.object(storage, 'url')` would run into.
        """
        from apps.articles import media

        class StubStorage:
            @staticmethod
            def url(_name):
                return stored_url

        with patch.object(media, 'default_storage', StubStorage()):
            return media._public_url('articles/x.webp', self.FakeRequest())

    @override_settings(API_PUBLIC_BASE_URL='')
    def test_local_filesystem_relative_path_becomes_absolute(self):
        self.assertEqual(
            self._url_for('/media/articles/x.webp'),
            'https://api.example.com/media/articles/x.webp',
        )

    @override_settings(API_PUBLIC_BASE_URL='https://proxy.example.com')
    def test_api_public_base_url_overrides_the_request_host(self):
        self.assertEqual(
            self._url_for('/media/articles/x.webp'),
            'https://proxy.example.com/media/articles/x.webp',
        )

    @override_settings(API_PUBLIC_BASE_URL='')
    def test_remote_object_storage_url_is_used_verbatim(self):
        """Regression guard: prefixing a CDN URL yields a double-scheme URL."""
        remote = 'https://abc.supabase.co/storage/v1/object/public/articles/x.webp'
        self.assertEqual(self._url_for(remote), remote)

    @override_settings(API_PUBLIC_BASE_URL='https://proxy.example.com')
    def test_remote_url_is_not_prefixed_even_when_a_base_url_is_set(self):
        remote = 'https://abc.supabase.co/storage/v1/object/public/articles/x.webp'
        self.assertEqual(self._url_for(remote), remote)


@override_settings(STORAGES=LOCAL_STORAGE_STORAGES)
class RewriteImageUrlsTests(TestCase):
    """Repointing URLs after a provider change must not touch prose."""

    def setUp(self):
        self.article = Article.objects.create(
            title='With image',
            slug='with-image',
            content={
                'blocks': [
                    {'type': 'paragraph', 'data': {'text': 'See https://old.example.com/docs for details.'}},
                    {'type': 'image', 'data': {
                        'file': {'url': 'https://old.example.com/storage/v1/object/public/articles/a.webp'},
                        'caption': 'Diagram',
                    }},
                    {'type': 'code', 'data': {'code': 'x = "https://old.example.com"'}},
                ],
            },
            featured_image='https://old.example.com/storage/v1/object/public/articles/hero.webp',
        )

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('rewrite_image_urls', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self._run('--from', 'old.example.com')
        self.article.refresh_from_db()
        self.assertIn('Would rewrite', output)
        self.assertIn('not saved', output)
        self.assertIn('old.example.com', self.article.content['blocks'][1]['data']['file']['url'])

    def test_apply_rewrites_image_blocks_only(self):
        self._run(
            '--from', 'old.example.com',
            '--to', 'new.example.com',
            '--apply',
        )
        self.article.refresh_from_db()
        blocks = self.article.content['blocks']

        # The image block is repointed.
        self.assertEqual(
            blocks[1]['data']['file']['url'],
            'https://new.example.com/storage/v1/object/public/articles/a.webp',
        )
        # Prose and code that merely mention the old host are left alone.
        self.assertIn('old.example.com', blocks[0]['data']['text'])
        self.assertIn('old.example.com', blocks[2]['data']['code'])
        # featured_image is a field of its own.
        self.assertEqual(
            self.article.featured_image,
            'https://new.example.com/storage/v1/object/public/articles/hero.webp',
        )

    def test_command_is_idempotent(self):
        args = ('--from', 'old.example.com', '--to', 'new.example.com', '--apply')
        self._run(*args)
        first = Article.objects.get(slug='with-image').content
        self._run(*args)
        self.assertEqual(Article.objects.get(slug='with-image').content, first)

    def test_strip_extension_removes_the_file_extension(self):
        """Cloudinary public ids carry no extension; keeping one doubles it."""
        self._run(
            # The full bucket base, not just the host: `--from` replaces a
            # substring, so a host-only value would leave the bucket path behind.
            '--from', 'https://old.example.com/storage/v1/object/public/articles',
            '--to', 'https://res.cloudinary.com/demo/image/upload/articles',
            '--strip-extension', '--apply',
        )
        self.article.refresh_from_db()
        self.assertEqual(
            self.article.content['blocks'][1]['data']['file']['url'],
            'https://res.cloudinary.com/demo/image/upload/articles/a',
        )
        self.assertEqual(
            self.article.featured_image,
            'https://res.cloudinary.com/demo/image/upload/articles/hero',
        )

    def test_extension_is_kept_by_default(self):
        self._run('--from', 'old.example.com', '--to', 'new.example.com', '--apply')
        self.article.refresh_from_db()
        self.assertTrue(
            self.article.content['blocks'][1]['data']['file']['url'].endswith('.webp')
        )

    def test_strip_extension_keeps_dots_inside_the_public_id(self):
        from apps.articles.management.commands.rewrite_image_urls import _strip_url_extension

        self.assertEqual(
            _strip_url_extension('https://h/articles/v1.2/a.webp'),
            'https://h/articles/v1.2/a',
        )
        # A query string is not an extension and must survive.
        self.assertEqual(
            _strip_url_extension('https://h/articles/a.webp?v=2'),
            'https://h/articles/a?v=2',
        )


CLOUDINARY_DEMO_STORAGE = {
    'CLOUD_NAME': 'demo', 'API_KEY': 'key', 'API_SECRET': 'secret',
    'SECURE': True, 'PREFIX': '',
}


@override_settings(STORAGES=LOCAL_STORAGE_STORAGES, CLOUDINARY_STORAGE=CLOUDINARY_DEMO_STORAGE)
class MigrateImagesToCloudinaryTests(TestCase):
    """The copy step. `_collect_targets` and the public id it derives are the
    parts that can silently do the wrong thing."""

    OLD = 'https://abc.supabase.co/storage/v1/object/public/articles'

    def setUp(self):
        self.article = Article.objects.create(
            title='Migration',
            slug='migration',
            content={
                'blocks': [
                    {'type': 'paragraph', 'data': {'text': f'prose mentioning {self.OLD}'}},
                    {'type': 'image', 'data': {
                        'file': {'url': f'{self.OLD}/a.webp'}, 'caption': 'A',
                    }},
                    {'type': 'image', 'data': {
                        'file': {'url': f'{self.OLD}/a.webp'}, 'caption': 'Same file again',
                    }},
                    {'type': 'image', 'data': {
                        'file': {'url': f'{self.OLD}/b.png'},
                    }},
                    {'type': 'image', 'data': {
                        'file': {'url': 'https://example.com/external.jpg'},
                    }},
                ],
            },
            featured_image=f'{self.OLD}/hero.webp',
        )
        Article.objects.create(
            title='Already migrated', slug='already',
            content={'blocks': [{'type': 'image', 'data': {
                'file': {'url': 'https://res.cloudinary.com/demo/image/upload/articles/c'},
            }}]},
        )

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('migrate_images_to_cloudinary', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_uploads_nothing_and_lists_each_file_once(self):
        with patch('cloudinary.uploader.upload') as upload:
            output = self._run('--from', self.OLD)

        upload.assert_not_called()
        self.assertIn('targets    3', output)
        self.assertIn(f'{self.OLD}/a.webp', output)
        self.assertIn('Dry run', output)

    def test_external_urls_are_left_alone(self):
        """A hand-written link to someone else's image is not ours to migrate."""
        with patch('cloudinary.uploader.upload'):
            output = self._run('--from', self.OLD, '--apply')
        self.assertNotIn('external.jpg', output)

    def test_apply_uploads_with_an_extension_free_public_id(self):
        with patch('cloudinary.uploader.upload') as upload:
            self._run('--from', self.OLD, '--apply')

        ids = sorted(call.kwargs['public_id'] for call in upload.call_args_list)
        self.assertEqual(ids, ['articles/a', 'articles/b', 'articles/hero'])

    def test_apply_prints_the_follow_up_rewrite_command(self):
        with patch('cloudinary.uploader.upload'):
            output = self._run('--from', self.OLD, '--apply')
        self.assertIn('--strip-extension', output)
        self.assertIn(self.OLD, output)

    def test_a_failed_copy_aborts_before_any_url_is_rewritten(self):
        with patch('cloudinary.uploader.upload', side_effect=Exception('boom')):
            from django.core.management.base import CommandError
            with self.assertRaises(CommandError):
                self._run('--from', self.OLD, '--apply')

        # The command never touches articles, so the stored URLs must be intact.
        self.article.refresh_from_db()
        self.assertEqual(
            self.article.content['blocks'][1]['data']['file']['url'],
            f'{self.OLD}/a.webp',
        )

    @override_settings(CLOUDINARY_STORAGE={'CLOUD_NAME': '', 'API_KEY': '', 'API_SECRET': ''})
    def test_missing_credentials_fail_clearly_instead_of_at_the_api(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError) as caught:
            self._run('--from', self.OLD, '--apply')
        self.assertIn('CLOUDINARY_CLOUD_NAME', str(caught.exception))

    @override_settings(CLOUDINARY_STORAGE={'CLOUD_NAME': '', 'API_KEY': '', 'API_SECRET': ''})
    def test_dry_run_still_works_without_credentials(self):
        """Previewing must not require secrets the operator may not have yet."""
        output = self._run('--from', self.OLD)
        self.assertIn('Dry run', output)


class ProviderCeilingTests(SimpleTestCase):
    """Cloudinary's Free plan caps uploads at 10 MB; ours must respect it."""

    @override_settings(STORAGE_MAX_UPLOAD_BYTES=0)
    def test_local_filesystem_has_no_provider_ceiling(self):
        self.assertEqual(provider_max_upload_bytes(), 0)

    @override_settings(STORAGE_MAX_UPLOAD_BYTES=10 * 1024 * 1024)
    def test_cloudinary_ceiling_is_reported(self):
        self.assertEqual(provider_max_upload_bytes(), 10 * 1024 * 1024)


class CloudinaryPublicIdTests(SimpleTestCase):
    """Public ids and delivery URLs, with no network access."""

    def setUp(self):
        import cloudinary
        self.cloudinary = cloudinary
        current = cloudinary.config()
        # `cloudinary.config()` returns a live object that refuses `**` unpacking,
        # so snapshot the individual keys that matter rather than the whole thing.
        self._original = {
            key: getattr(current, key)
            for key in ('cloud_name', 'api_key', 'api_secret', 'secure', 'force_version')
        }
        cloudinary.config(cloud_name='demo', api_key='key', api_secret='secret', secure=True)

    def tearDown(self):
        self.cloudinary.config(**self._original)

    def _storage(self):
        from apps.articles.storage import CloudinaryArticleStorage
        return CloudinaryArticleStorage()

    def test_public_id_drops_only_the_extension(self):
        self.assertEqual(strip_extension('articles/abc.webp'), 'articles/abc')
        self.assertEqual(strip_extension('articles/abc'), 'articles/abc')
        # A dotted folder name must survive; splitext works on the basename only.
        self.assertEqual(strip_extension('v1.2/articles/abc.webp'), 'v1.2/articles/abc')

    def test_url_is_unsigned(self):
        """A signature is derived from the API secret, so rotating it would
        invalidate every URL already stored in published article JSON."""
        url = self._storage().url('articles/abc')
        self.assertEqual(url, 'https://res.cloudinary.com/demo/image/upload/articles/abc')
        self.assertNotIn('/s--', url)

    def test_url_does_not_double_the_extension(self):
        self.assertNotIn('.webp.webp', self._storage().url('articles/abc.webp'))

    def test_url_is_the_same_with_or_without_the_extension(self):
        storage = self._storage()
        self.assertEqual(
            storage.url('articles/abc.webp'), storage.url('articles/abc')
        )

    def test_folder_prefix_is_not_applied(self):
        """`PREFIX` defaults to MEDIA_URL; settings pins it to '' so public ids
        match the object keys used by the previous S3 bucket."""
        self.assertNotIn('/media/', self._storage().url('articles/abc'))


class CloudinarySaveErrorTests(SimpleTestCase):
    """A provider rejection must become a 400, not an AttributeError.

    Regression guard: the handler used to name `cloudinary.api.Error`, which the
    SDK does not expose, so any failed upload raised `AttributeError` and the
    original Cloudinary error was lost. The SDK signals status through exception
    *types* (BadRequest/NotFound/AlreadyExists/GeneralError) rather than an
    `http_code` attribute.
    """

    def setUp(self):
        import cloudinary
        self.cloudinary = cloudinary
        current = cloudinary.config()
        self._original = {
            key: getattr(current, key)
            for key in ('cloud_name', 'api_key', 'api_secret', 'secure')
        }
        cloudinary.config(cloud_name='demo', api_key='key', api_secret='secret', secure=True)

    def tearDown(self):
        self.cloudinary.config(**self._original)

    def _save(self):
        from django.core.files.base import ContentFile
        from apps.articles.storage import CloudinaryArticleStorage
        return CloudinaryArticleStorage()._save('articles/x.webp', ContentFile(b'data'))

    def test_client_rejection_becomes_a_validation_error(self):
        from django.core.exceptions import ValidationError
        with patch(
            'cloudinary.uploader.upload',
            side_effect=self.cloudinary.exceptions.BadRequest('bad image'),
        ):
            with self.assertRaises(ValidationError):
                self._save()

    def test_an_existing_asset_is_treated_as_a_client_error(self):
        from django.core.exceptions import ValidationError
        with patch(
            'cloudinary.uploader.upload',
            side_effect=self.cloudinary.exceptions.AlreadyExists('exists'),
        ):
            with self.assertRaises(ValidationError):
                self._save()

    def test_provider_outage_is_reraised_as_a_server_error(self):
        with patch(
            'cloudinary.uploader.upload',
            side_effect=self.cloudinary.exceptions.GeneralError('provider down'),
        ):
            with self.assertRaises(self.cloudinary.exceptions.GeneralError):
                self._save()

