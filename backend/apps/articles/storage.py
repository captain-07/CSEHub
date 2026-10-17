"""Cloudinary storage backend for article images.

`django-cloudinary-storage` is installed and registered, but three of its defaults
are wrong for this project and all three fail *quietly* — uploads succeed and the
images break later, on pages nobody tests until a reader hits one.

1. **URLs are signed.**  ``cloudinary_url()`` defaults to ``sign_url=True`` and
   inserts an ``/s--<sha1>--/`` segment into every delivery URL. The signature is
   derived from ``api_secret``, so rotating the secret invalidates every image URL
   already baked into published article JSON. Article images are public and the
   URLs are permanent, so they are generated unsigned.

2. **Public ids must not carry a file extension.**  Cloudinary appends the
   delivery format to the URL, so a public id of ``a/b.webp`` yields
   ``.../a/b.webp.webp`` and 404s. The upstream library works around this for
   *static* files only (``StaticCloudinaryStorage._remove_extension_for_non_raw_file``)
   and leaves media uploads at the mercy of ``use_filename``.

3. **``PREFIX`` defaults to ``MEDIA_URL``**, so every asset lands under a
   ``media/`` folder in the Cloudinary console. Harmless, but it makes public ids
   diverge from the object keys used by the previous S3 bucket, which in turn
   makes ``rewrite_image_urls`` harder to reason about. Set ``PREFIX: ''`` in
   settings so public ids match the ``articles/<token>`` keys already stored.

Nothing else needs to know about Cloudinary: ``apps.articles.media`` talks only
to ``default_storage``.
"""

import posixpath

import cloudinary
import cloudinary.exceptions
import cloudinary.uploader
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile


# Cloudinary raises a typed exception per HTTP status (see
# cloudinary.api_client.execute_request.EXCEPTION_CODES) and does NOT carry a
# numeric `http_code` on the exception object. A 4xx means the upload itself was
# unacceptable, so it is surfaced as a 400; anything else (auth/permission/rate
# limit on our account, or a provider outage) stays a 500.
_CLIENT_UPLOAD_ERRORS = (
    cloudinary.exceptions.BadRequest,
    cloudinary.exceptions.NotFound,
    cloudinary.exceptions.AlreadyExists,
)


def strip_extension(name: str) -> str:
    """Drop a trailing ``.ext`` from a stored name to form a Cloudinary public id.

    ``posixpath.splitext`` only considers the basename, so a dotted folder name
    such as ``v1.2/articles/abc.webp`` keeps its folder intact.
    """
    root, extension = posixpath.splitext(name)
    return root if extension else name


class CloudinaryArticleStorage(MediaCloudinaryStorage):
    """Public, unsigned, extension-free public ids."""

    def public_id_for(self, name: str) -> str:
        """The public id a file uploaded as `name` is stored under.

        Public so the migration command derives ids exactly the way new uploads
        do — otherwise migrated images land in a different folder from uploads
        made after the switch, and the two never agree on a delivery URL.
        """
        return strip_extension(self._prepend_prefix(self._normalise_name(name)))

    def _save(self, name, content):
        # `public_id` is set explicitly rather than relying on `use_filename`,
        # so the id a file is stored under is exactly the id we can derive a URL
        # from later. `_save` must return that id: `media.ImageUploadView` hands
        # the return value straight to `default_storage.url()`.
        try:
            response = cloudinary.uploader.upload(
                UploadedFile(content, name),
                public_id=self.public_id_for(name),
                resource_type=self._get_resource_type(name),
                tags=self.TAG,
                overwrite=False,
            )
        except cloudinary.exceptions.Error as exc:
            # Reuse Django's ValidationError so `ImageUploadView` answers 400
            # with a readable message instead of a 500 and a Cloudinary stack
            # trace. Only client-side rejections are translated — a Cloudinary
            # outage is our problem, not the uploader's, and must stay a 500.
            # NOTE: the SDK exposes this base class as `cloudinary.exceptions.Error`
            # (and `cloudinary.uploader.Error`); `cloudinary.api` does NOT export
            # an `Error` name, so catching `cloudinary.api.Error` used to raise
            # AttributeError instead of translating the failure.
            if isinstance(exc, _CLIENT_UPLOAD_ERRORS):
                raise ValidationError(f'Cloudinary rejected the upload: {exc}') from exc
            raise
        return response['public_id']

    def _get_url(self, name):
        # Stripping here too keeps `url()` tolerant of both forms: `_save` hands
        # back an extension-free public id, but `rewrite_image_urls` and ad-hoc
        # callers may still pass the name the file was uploaded under. Both must
        # resolve to the same asset.
        resource = cloudinary.CloudinaryResource(
            self.public_id_for(name),
            default_resource_type=self._get_resource_type(name),
            url_options={
                # See module docstring, item 1.
                'sign_url': False,
                # Without this Cloudinary inserts a literal `v1/` segment for any
                # public id containing a slash. Harmless but noisy, and it makes
                # the base URL that `rewrite_image_urls` derives harder to read.
                # Safe because ids are unique and uploads never overwrite.
                'force_version': False,
            },
        )
        return resource.url
