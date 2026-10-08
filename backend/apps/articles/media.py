"""Image uploads for Editor.js image blocks.

The admin editor needs somewhere to put an inline image. Uploads therefore go to
a backend endpoint rather than being embedded as base64 in the article JSON —
an Editor.js document is stored verbatim in a JSONField, and a handful of
screenshots would multiply the row size and pollute the RAG payload.

Design constraints:

* ``IsAdminUser`` — anyone who can call this can already publish an article.
* The browser never receives a storage credential. It uploads to this API and
  gets back a plain URL.
* Filenames are generated server-side; the client-supplied name is only used to
  derive an extension from a small allow-list, which removes the path-traversal
  and script-extension vectors of ``FileField.upload_to``.
* Storage is whatever ``default_storage`` is configured as — a local filesystem
  in development, Supabase Storage in production. Nothing here knows the
  difference, so moving to a different backend (Cloudinary, S3, R2) is a
  settings change. See ``apps.articles.image_processing`` for the
  optimise-before-storing step.
"""

import mimetypes
import posixpath
import secrets
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer

from .image_processing import optimise_image


# Only raster formats an <img> tag can display. SVG is deliberately excluded:
# it can carry script, and serving it from the API origin would be an XSS vector.
ALLOWED_CONTENT_TYPES = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/avif': '.avif',
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB source

# Animated GIFs are common for algorithm visualisations and run far larger than
# a screenshot, so they get their own ceiling. Output is usually far smaller.
MAX_ANIMATED_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# Content types that carry no information about the payload, so the filename may
# be consulted instead. See `_extension_from_name`.
GENERIC_CONTENT_TYPES = {'', 'application/octet-stream', 'binary/octet-stream'}

_UPLOAD_SERIALIZER = inline_serializer(
    name='ImageUploadRequest',
    fields={'file': serializers.ImageField()},
)


def _public_url(name: str, request) -> str:
    """Absolute URL for a stored file, so the editor stores an absolute reference.

    Editor.js persists whatever URL it is given into the article document, and
    the article page is rendered on the Vercel origin while the file lives on the
    API origin. A relative URL would therefore break as soon as the article is
    read from a different host.

    Two shapes have to be handled:

    * local filesystem — ``default_storage.url()`` returns a root-relative path
      (``/media/articles/x.webp``), which is turned into an absolute URL against
      the request (or ``API_PUBLIC_BASE_URL`` when behind a proxy).
    * remote object storage — ``default_storage.url()`` already returns a fully
      qualified CDN URL and must be used verbatim. Prefixing it with a host would
      produce ``https://api.example.com/https://bucket...``.
    """
    url = str(default_storage.url(name))

    if urlparse(url).scheme in ('http', 'https'):
        return url

    path = url.lstrip('/')
    host = getattr(settings, 'API_PUBLIC_BASE_URL', '') or ''
    if host:
        return f"{host.rstrip('/')}/{path}"
    return request.build_absolute_uri(path)


class ImageUploadView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request=_UPLOAD_SERIALIZER,
        responses={201: {'type': 'object'}},
        summary='Upload an image for use in an article',
        description=(
            'Admin-only. Accepts a multipart `file` field and returns an absolute '
            'URL suitable for an Editor.js image block. PNG, JPEG, GIF, WebP and '
            'AVIF. Images are downscaled and re-encoded to WebP server-side before '
            'storage; animated GIFs keep their frames.'
        ),
    )
    def post(self, request):
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return Response(
                {'file': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = (uploaded.content_type or '').lower()
        # The declared content type is authoritative. The filename fallback is
        # only consulted when the browser sends nothing usable, otherwise an
        # attacker could label any payload `image/png` via the extension.
        extension = ALLOWED_CONTENT_TYPES.get(content_type) or _extension_from_name(
            uploaded.name, content_type
        )
        if not extension:
            return Response(
                {'file': ['Only PNG, JPEG, GIF, WebP or AVIF images are supported.']},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        raw = uploaded.read()

        # Optimise before the size check: a 15 MB phone screenshot is a perfectly
        # reasonable thing to want to embed, and it becomes ~200 KB on disk. What
        # matters is the stored result, not the source.
        try:
            optimised = optimise_image(raw, extension)
        except ImportError:
            return Response(
                {'file': ['Image optimisation is unavailable (Pillow is not installed).']},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        limit = (
            MAX_ANIMATED_UPLOAD_BYTES if optimised.frames > 1 else MAX_UPLOAD_BYTES
        )
        if len(optimised.data) > limit:
            return Response(
                {'file': [f'Processed images must be {limit // (1024 * 1024)} MB or smaller.']},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        if not optimised.changed and len(raw) > limit:
            return Response(
                {'file': [f'Images must be {limit // (1024 * 1024)} MB or smaller.']},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Never reuse the client filename: `default_storage.save` sanitises it,
        # but a random name also removes collisions and awkward characters. The
        # extension follows the optimised output, not the upload.
        name = posixpath.join('articles', f'{secrets.token_hex(12)}{optimised.extension}')

        try:
            saved_name = default_storage.save(name, ContentFile(optimised.data))
        except ValidationError as exc:
            return Response({'file': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'url': _public_url(saved_name, request),
                'name': posixpath.basename(saved_name),
                'size': len(optimised.data),
                'original_size': optimised.original_bytes,
                'width': optimised.width,
                'height': optimised.height,
                'animated': optimised.frames > 1,
            },
            status=status.HTTP_201_CREATED,
        )


def _extension_from_name(filename: str, content_type: str) -> str:
    """Fallback for clients that send no (or a generic) content type.

    Only engaged when the browser says nothing useful — an empty string, or one
    of the generic types some upload libraries substitute. An explicit type such
    as `application/pdf` is never overridden, so mislabelling a non-image cannot
    slip through on the strength of its filename.
    """
    if content_type and content_type not in GENERIC_CONTENT_TYPES:
        return ''

    suffix = Path(filename or '').suffix.lower()
    if suffix in set(ALLOWED_CONTENT_TYPES.values()):
        return suffix
    guessed, _ = mimetypes.guess_type(f'file{suffix}')
    return ALLOWED_CONTENT_TYPES.get(guessed or '', '')