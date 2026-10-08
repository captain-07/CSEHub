"""Server-side image optimisation.

Every image an editor uploads is normalised before it reaches storage. The point
is bandwidth, not tidiness: the article reading column is ~800px wide, so serving
a 4000px phone screenshot straight to a reader wastes most of the payload on
pixels nobody sees. Downscaling and re-encoding at upload time typically removes
70-90% of the bytes, once, for every future request.

Design notes:

* WebP is the default output because it is smaller than JPEG for photographs and
  than PNG for diagrams, and is supported by every browser CSEHub targets.
* PNG is kept when the source has an alpha channel *and* WebP does not come out
  smaller. Flat diagrams with hard edges can look worse under lossy WebP, so
  "smaller" alone is not enough of a reason to switch.
* Animated GIFs are preserved frame by frame. Algorithm visualisations are very
  often animated, and a naive ``open()``/``save()`` round trip would silently
  collapse them to a single frame.
* EXIF is dropped. It usually carries GPS coordinates and a camera serial number,
  and it is pure weight for a screenshot.

Pillow is a hard requirement for this module; the upload endpoint degrades to
storing the original bytes if it is somehow unavailable, so an admin is never
locked out of publishing because of an optional optimisation.
"""

import io
import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptimisationSettings:
    """Tunables, read from Django settings with sane defaults."""

    max_dimension: int = 1600
    webp_quality: int = 82
    webp_method: int = 6
    # Don't switch format unless it actually helps, by at least this margin.
    min_savings_ratio: float = 0.10


def get_optimisation_settings() -> OptimisationSettings:
    defaults = OptimisationSettings()
    return OptimisationSettings(
        max_dimension=getattr(settings, 'IMAGE_MAX_DIMENSION', defaults.max_dimension),
        webp_quality=getattr(settings, 'IMAGE_WEBP_QUALITY', defaults.webp_quality),
        webp_method=getattr(settings, 'IMAGE_WEBP_METHOD', defaults.webp_method),
        min_savings_ratio=getattr(settings, 'IMAGE_MIN_SAVINGS_RATIO', defaults.min_savings_ratio),
    )


@dataclass
class OptimisedImage:
    data: bytes
    content_type: str
    extension: str
    width: int
    height: int
    frames: int
    original_bytes: int
    changed: bool

    @property
    def saved_ratio(self) -> float:
        if not self.original_bytes:
            return 0.0
        return 1 - (len(self.data) / self.original_bytes)


def optimise_image(raw: bytes, source_extension: str) -> OptimisedImage:
    """Resize and re-encode ``raw``. Never raises on malformed input.

    A failure here returns the original bytes unchanged so a corrupt or exotic
    image still publishes — the alternative is refusing content because an
    optional optimisation tripped over it.
    """
    from PIL import Image, UnidentifiedImageError

    options = get_optimisation_settings()
    original_size = len(raw)

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            is_animated = getattr(probe, 'is_animated', False) and getattr(probe, 'n_frames', 1) > 1
            source_format = (probe.format or '').upper()
            frame_count = max(1, int(getattr(probe, 'n_frames', 1)))
            has_alpha = probe.mode in ('RGBA', 'LA', 'PA') or 'transparency' in probe.info
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning('Could not read uploaded image, storing it unmodified: %s', exc)
        return OptimisedImage(
            data=raw,
            content_type=_content_type_for(source_extension),
            extension=source_extension,
            width=0, height=0, frames=1,
            original_bytes=original_size, changed=False,
        )

    try:
        if is_animated:
            return _optimise_animated(raw, options, frame_count)

        with Image.open(io.BytesIO(raw)) as image:
            image = _strip_metadata(image)
            resized = _fit(image, options.max_dimension)

            # Alpha is preserved in both output formats — WebP supports it
            # natively — so there is nothing to flatten. `_choose` then picks
            # whichever encoding is genuinely smaller, which keeps transparent
            # diagrams sharp instead of pasting them onto a white rectangle.
            png_candidate = None
            if has_alpha or source_format == 'PNG':
                png_candidate = _encode(resized, 'PNG', options)

            webp_candidate = _encode(resized, 'WEBP', options)

            chosen = _choose(png_candidate, webp_candidate, has_alpha, options)
            width, height = resized.size
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning('Image optimisation failed, storing the original: %s', exc)
        return OptimisedImage(
            data=raw,
            content_type=_content_type_for(source_extension),
            extension=source_extension,
            width=0, height=0, frames=1,
            original_bytes=original_size, changed=False,
        )

    return OptimisedImage(
        data=chosen['data'],
        content_type=_content_type_for(chosen['extension']),
        extension=chosen['extension'],
        width=width,
        height=height,
        frames=1,
        original_bytes=original_size,
        changed=len(chosen['data']) != original_size or chosen['extension'] != source_extension,
    )


def _optimise_animated(raw: bytes, options: OptimisationSettings, frame_count: int) -> OptimisedImage:
    """Re-encode every frame, preserving animation.

    Animated GIF is genuinely good at flat-colour content, and animated WebP has
    per-frame overhead — for a simple looping diagram the "optimised" WebP can
    come out *larger* than the original. So the result is only used when it is
    actually smaller; otherwise the GIF is kept byte-for-byte. Making a file
    bigger while claiming to optimise it would be worse than doing nothing.
    """
    from PIL import Image, ImageSequence

    try:
        with Image.open(io.BytesIO(raw)) as image:
            frames = []
            for frame in ImageSequence.Iterator(image):
                frame = _fit(frame.convert('RGBA'), options.max_dimension)
                frames.append(frame)

            if not frames:
                raise ValueError('animated image contained no frames')

            buffer = io.BytesIO()
            frames[0].save(
                buffer, format='WEBP', save_all=True, append_images=frames[1:],
                loop=0, duration=image.info.get('duration', 100),
                quality=options.webp_quality, method=options.webp_method,
            )
            data = buffer.getvalue()

        if len(data) >= len(raw):
            return OptimisedImage(
                data=raw,
                content_type='image/gif',
                extension='.gif',
                width=frames[0].size[0], height=frames[0].size[1],
                frames=frame_count,
                original_bytes=len(raw), changed=False,
            )

        return OptimisedImage(
            data=data,
            content_type='image/webp',
            extension='.webp',
            width=frames[0].size[0],
            height=frames[0].size[1],
            frames=frame_count,
            original_bytes=len(raw),
            changed=True,
        )
    except Exception as exc:
        # Fall back to the original rather than failing the upload; whatever went
        # wrong, the author's GIF is still the best available artefact.
        logger.info('Animated re-encode failed, keeping the original: %s', exc)
        return OptimisedImage(
            data=raw,
            content_type='image/gif',
            extension='.gif',
            width=0, height=0,
            frames=frame_count,
            original_bytes=len(raw), changed=False,
        )


def _strip_metadata(image):
    """Drop EXIF and other ancillary chunks without re-encoding pixels."""
    # `Image.open` lazily loads; create a clean copy so the returned image does
    # not keep the original's info dict (which is what carries EXIF).
    clean = image.copy()
    for key in ('exif', 'xmp', 'icc_profile', 'photoshop', 'comment'):
        clean.info.pop(key, None)
    return clean


def _fit(image, max_dimension: int):
    """Downscale so the longest edge is at most ``max_dimension``.

    Never upscales: a 400px diagram stays 400px rather than being blown up to
    1600px, which would add bytes and change nothing for the reader.
    """
    width, height = image.size
    longest = max(width, height)
    if longest <= max_dimension:
        return image

    scale = max_dimension / float(longest)
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        resample=_resample_filter(),
    )


def _resample_filter():
    from PIL import Image
    # LANCZOS for downscaling quality; fall back on older Pillow builds.
    resampling = getattr(Image, 'Resampling', Image)
    return getattr(resampling, 'LANCZOS', getattr(resampling, 'ANTIALIAS', 1))


def _encode(image, fmt: str, options: OptimisationSettings):
    buffer = io.BytesIO()

    if fmt == 'WEBP':
        image.save(
            buffer, format='WEBP',
            quality=options.webp_quality, method=options.webp_method,
        )
        extension = '.webp'
    elif fmt == 'PNG':
        # optimise=True picks the best PNG filter per scanline; meaningful on
        # flat diagrams, negligible cost on photographs.
        image.save(buffer, format='PNG', optimize=True)
        extension = '.png'
    else:  # pragma: no cover - defensive
        raise ValueError(f'unsupported output format {fmt}')

    return {
        'data': buffer.getvalue(),
        'extension': extension,
        'format': fmt,
    }


def _choose(png_candidate, webp_candidate, has_alpha: bool, options: OptimisationSettings):
    """Pick between PNG and WebP.

    A transparent source is a strong hint that the image is a diagram with hard
    edges, where lossy WebP can smear fine text. So PNG wins ties unless WebP is
    meaningfully smaller.
    """
    if png_candidate is None:
        return webp_candidate

    png_size = len(png_candidate['data'])
    webp_size = len(webp_candidate['data'])

    if has_alpha and webp_size > png_size * (1 - options.min_savings_ratio):
        return png_candidate
    return webp_candidate if webp_size < png_size else png_candidate


def _content_type_for(extension: str) -> str:
    return {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.avif': 'image/avif',
    }.get((extension or '').lower(), 'application/octet-stream')