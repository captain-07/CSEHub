import django.db.models.deletion
from django.db import migrations, models


# The sample taxonomy the seed command ships. Encoded here as well so an
# existing database — which the migration's backfill has to file — ends up with
# the same categories a fresh `migrate` + `seed` produces. Frozen on purpose: a
# migration must not change when the seed does.
KNOWN_TAG_CATEGORIES = {
    'array': 'dsa',
    'linked-list': 'dsa',
    'tree': 'core-cs',
    'dp': 'dsa',
    'graph': 'system-design',
    'recursion': 'dsa',
}


def backfill_tag_categories(apps, schema_editor):
    """Give every existing tag a category before the FK becomes required.

    A tag is filed by, in order of preference:

    1. the known seed mapping above;
    2. the category its articles agree on, when they all share one;
    3. a 'General' category, created on demand.

    Step 3 only triggers for tags that are unused, or used across categories —
    neither of which can be derived. Editors can re-file those from the admin.
    """
    Tag = apps.get_model('articles', 'Tag')
    Category = apps.get_model('articles', 'Category')

    by_slug = {category.slug: category for category in Category.objects.all()}
    fallback = None

    for tag in Tag.objects.filter(category__isnull=True):
        category = by_slug.get(KNOWN_TAG_CATEGORIES.get(tag.slug, ''))

        if category is None:
            # A plain set, not `.distinct()`: `values_list(...).distinct()`
            # still carries Article.Meta.ordering, so DISTINCT is computed over
            # (category_id, created_at) and returns one row per article.
            category_ids = set(
                tag.articles.exclude(category__isnull=True)
                .values_list('category_id', flat=True)
            )
            if len(category_ids) == 1:
                category = Category.objects.get(pk=category_ids.pop())

        if category is None:
            if fallback is None:
                fallback, _ = Category.objects.get_or_create(
                    slug='general', defaults={'name': 'General'}
                )
            category = fallback

        tag.category = category
        tag.save(update_fields=['category'])


def clear_tag_categories(apps, schema_editor):
    Tag = apps.get_model('articles', 'Tag')
    Tag.objects.update(category=None)


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0005_article_dislike_count_article_like_count_and_more'),
    ]

    operations = [
        # Nullable first so the column can be added to a table that already has
        # rows, then backfilled, then tightened to NOT NULL.
        migrations.AddField(
            model_name='tag',
            name='category',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tags',
                to='articles.category',
            ),
        ),
        migrations.RunPython(backfill_tag_categories, clear_tag_categories),
        migrations.AlterField(
            model_name='tag',
            name='category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tags',
                to='articles.category',
            ),
        ),
    ]
