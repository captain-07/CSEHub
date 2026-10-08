from django.db import migrations, models

import re

HEADING_RE = re.compile(r'^(#{1,3})\s+(.*)$')


def _blocks_from_text(text):
    """Convert legacy plain-text/Markdown article bodies into Editor.js blocks.

    Parses line by line rather than splitting on blank lines so that a Markdown
    heading and the prose that follows it become *separate* blocks.  Splitting on
    blank lines instead would swallow the whole body into the heading block.
    """
    blocks = []
    buffer = []

    def flush():
        if not buffer:
            return
        body = '\n'.join(buffer).strip()
        buffer.clear()
        if body:
            blocks.append({'type': 'paragraph', 'data': {'text': body}})

    for raw_line in (text or '').splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue

        match = HEADING_RE.match(line)
        if match:
            flush()
            blocks.append({
                'type': 'header',
                'data': {'text': match.group(2).strip(), 'level': len(match.group(1))},
            })
            continue

        buffer.append(line)

    flush()
    return blocks


def text_to_editorjs(apps, schema_editor):
    Article = apps.get_model('articles', 'Article')
    for article in Article.objects.all().iterator():
        raw = article.content
        # Tolerate re-runs: already-converted rows are left untouched.
        if isinstance(raw, dict):
            continue
        blocks = _blocks_from_text(raw)
        if not blocks:
            blocks = [{'type': 'paragraph', 'data': {'text': ''}}]
        article.editor_content = {'time': 0, 'blocks': blocks, 'version': 'legacy'}
        article.save(update_fields=['editor_content'])


class Migration(migrations.Migration):
    dependencies = [('articles', '0002_article_articletag_article_tags_codesnippet')]

    operations = [
        migrations.AddField(
            model_name='article', name='editor_content',
            field=models.JSONField(default=dict),
        ),
        migrations.RunPython(text_to_editorjs, migrations.RunPython.noop),
        migrations.RemoveField(model_name='article', name='content'),
        migrations.RenameField(model_name='article', old_name='editor_content', new_name='content'),
        migrations.AddField(model_name='article', name='excerpt', field=models.TextField(blank=True)),
        migrations.AddField(model_name='article', name='featured_image', field=models.URLField(blank=True)),
    ]
