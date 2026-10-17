"""Repoint article image URLs after changing storage provider.

Why this exists
---------------
Editor.js stores the URL an uploader hands back *inside* the article document:

    {"type": "image", "data": {"file": {"url": "https://old-host/articles/a.webp"}}}

That URL is absolute on purpose — the frontend is served from a different origin
than the API, so a relative path would break. The trade-off is that published
articles become coupled to whichever host served the image. Move the bucket to
Cloudinary, R2 or a new Supabase project and every existing image reference
points at a host that no longer serves them.

This command rewrites those references in place after the files have been copied
across. It only touches `image` blocks (and `featured_image`), never prose, so a
URL that merely looks like an old image link in a paragraph is left alone.

Usage
-----
    # Preview — prints what would change, writes nothing
    python manage.py rewrite_image_urls --from old.example.com

    # Apply
    python manage.py rewrite_image_urls --from old.example.com --apply

    # With an explicit host (needed when the bucket path also changed)
    python manage.py rewrite_image_urls \
        --from old.example.com/storage/v1/object/public/articles \
        --to   new.example.com/storage/v1/object/public/articles --apply
"""

import re

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from apps.articles.models import Article

# Block types whose `data` can carry an image URL.
_IMAGE_BLOCKS = {'image'}


class Command(BaseCommand):
    help = 'Rewrite stored article image URLs to point at the current storage provider'

    def add_arguments(self, parser):
        parser.add_argument(
            '--from',
            dest='old',
            required=True,
            help='Substring identifying URLs to replace (e.g. the old host or path prefix)',
        )
        parser.add_argument(
            '--to',
            dest='new',
            default='',
            help=(
                'Replacement substring. Defaults to the current public storage base, '
                'so a bare host is enough in the common case.'
            ),
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually write the changes. Without this flag the command only reports.',
        )
        parser.add_argument(
            '--dry-run-skip-featured',
            action='store_true',
            help='Only rewrite inline Editor.js image blocks, not Article.featured_image.',
        )
        parser.add_argument(
            '--strip-extension',
            action='store_true',
            help=(
                'Remove a trailing file extension from rewritten URLs. Cloudinary '
                'stores the format in the asset, not in the public id, so a name '
                'like "a.webp" becomes ".../a" — keeping the extension yields a '
                'doubled "a.webp.webp" URL that 404s.'
            ),
        )

    def handle(self, *args, **options):
        old = options['old']
        apply_changes = options['apply']
        replacement = options['new'] or _current_storage_base()
        strip_extension = options['strip_extension']

        if not old:
            raise CommandError('--from must not be empty.')

        self.stdout.write(f'Replacing  {old!r}')
        self.stdout.write(f'      with  {replacement!r}')
        self.stdout.write(f'   strip   {strip_extension}')
        self.stdout.write(f'    apply  {apply_changes}')
        self.stdout.write('')

        touched = 0
        rewritten = 0

        for article in Article.objects.all().iterator():
            changes = []

            content = article.content
            if isinstance(content, dict):
                new_content = self._rewrite_content(
                    content, old, replacement, strip_extension, changes
                )
                if new_content != content:
                    changes.append('content')

            if not options['dry_run_skip_featured'] and article.featured_image and old in article.featured_image:
                changes.append('featured_image')

            if not changes:
                continue

            touched += 1
            rewritten += len(changes)

            if apply_changes:
                fields = []
                if 'content' in changes:
                    article.content = self._rewrite_content(
                        content, old, replacement, strip_extension, []
                    )
                    fields.append('content')
                if 'featured_image' in changes:
                    article.featured_image = self._swap(
                        article.featured_image, old, replacement, strip_extension
                    )
                    fields.append('featured_image')
                article.save(update_fields=fields)

            self.stdout.write(
                f'  {article.slug}: {", ".join(sorted(set(changes)))}'
                + ('' if apply_changes else '  (not saved)')
            )

        verb = 'Rewrote' if apply_changes else 'Would rewrite'
        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'{verb} {rewritten} reference(s) across {touched} article(s).'
            )
        )
        if not apply_changes and touched:
            self.stdout.write('Re-run with --apply to save these changes.')

    def _swap(self, url, old, replacement, strip_extension):
        """Replace `old` with `replacement`, optionally dropping a file extension."""
        swapped = url.replace(old, replacement)
        if strip_extension:
            swapped = _strip_url_extension(swapped)
        return swapped

    def _rewrite_content(self, content, old, replacement, strip_extension, changes):
        """Return content with image-block URLs replaced. Mutates ``changes``."""
        blocks = content.get('blocks')
        if not isinstance(blocks, list):
            return content

        updated = dict(content)
        new_blocks = []

        for block in blocks:
            if not isinstance(block, dict) or block.get('type') not in _IMAGE_BLOCKS:
                new_blocks.append(block)
                continue

            new_block, changed = self._rewrite_block(block, old, replacement, strip_extension)
            if changed:
                changes.append('content')
            new_blocks.append(new_block)

        updated['blocks'] = new_blocks
        return updated

    def _rewrite_block(self, block, old, replacement, strip_extension):
        data = block.get('data')
        if not isinstance(data, dict):
            return block, False

        new_data = dict(data)
        changed = False

        # Editor.js image tool shape: data.file.url
        file_info = data.get('file')
        if isinstance(file_info, dict) and isinstance(file_info.get('url'), str):
            if old in file_info['url']:
                new_file = dict(file_info)
                new_file['url'] = self._swap(
                    file_info['url'], old, replacement, strip_extension
                )
                new_data['file'] = new_file
                changed = True

        # Tolerate documents written by hand or by an older plugin.
        for key in ('url', 'link'):
            value = data.get(key)
            if isinstance(value, str) and old in value:
                new_data[key] = self._swap(value, old, replacement, strip_extension)
                changed = True

        if not changed:
            return block, False

        return {**block, 'data': new_data}, True


_EXTENSION_RE = re.compile(r'\.[A-Za-z0-9]{1,8}(?=$|[?#])')


def _strip_url_extension(url: str) -> str:
    """Drop a trailing `.ext` from the path, leaving any query or fragment intact.

    Anchored to the end of the path so a Cloudinary public id such as
    `.../articles/a.b.webp` keeps every dot but the extension.
    """
    head, separator, tail = url.partition('?')
    if not separator:
        head, separator, tail = url.partition('#')
    return _EXTENSION_RE.sub('', head) + separator + tail


def _current_storage_base() -> str:
    """Public base for the configured storage, derived from a real URL."""
    try:
        url = default_storage.url('articles/probe')
    except Exception as exc:  # pragma: no cover - defensive
        raise CommandError(
            f'Could not determine the current storage URL ({exc}). '
            'Pass an explicit --to value.'
        )

    # .../articles/probe -> .../articles
    base = url.rsplit('/', 1)[0] if '/' in url else url
    return base