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

    def handle(self, *args, **options):
        old = options['old']
        apply_changes = options['apply']
        replacement = options['new'] or _current_storage_base()

        if not old:
            raise CommandError('--from must not be empty.')

        self.stdout.write(f'Replacing  {old!r}')
        self.stdout.write(f'      with  {replacement!r}')
        self.stdout.write(f'    apply  {apply_changes}')
        self.stdout.write('')

        touched = 0
        rewritten = 0

        for article in Article.objects.all().iterator():
            changes = []

            content = article.content
            if isinstance(content, dict):
                new_content = self._rewrite_content(content, old, replacement, changes)
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
                    article.content = self._rewrite_content(content, old, replacement, [])
                    fields.append('content')
                if 'featured_image' in changes:
                    article.featured_image = article.featured_image.replace(old, replacement)
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

    def _rewrite_content(self, content, old, replacement, changes):
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

            new_block, changed = self._rewrite_block(block, old, replacement)
            if changed:
                changes.append('content')
            new_blocks.append(new_block)

        updated['blocks'] = new_blocks
        return updated

    def _rewrite_block(self, block, old, replacement):
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
                new_file['url'] = new_file['url'].replace(old, replacement)
                new_data['file'] = new_file
                changed = True

        # Tolerate documents written by hand or by an older plugin.
        for key in ('url', 'link'):
            value = data.get(key)
            if isinstance(value, str) and old in value:
                new_data[key] = value.replace(old, replacement)
                changed = True

        if not changed:
            return block, False

        return {**block, 'data': new_data}, True


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