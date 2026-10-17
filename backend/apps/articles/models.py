from django.db import models, transaction
from django.db.models import Count, F
from django.db.models.functions import Greatest
from django.conf import settings

# Create your models here.

# Editor.js block types the API accepts. This is the single authority: the
# serializer rejects anything outside it, and the frontend configures its editor
# toolbar from the same list (see frontend/js/admin.js).
SUPPORTED_BLOCK_TYPES = (
    'paragraph', 'header', 'list', 'quote', 'code', 'image', 'delimiter', 'linkTool',
)


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Tag(models.Model):
    # A tag belongs to exactly one category; a category groups many tags. Names
    # and slugs stay globally unique, so a tag slug is an unambiguous lookup key
    # anywhere it appears (URLs, `?tags__slug=` filters, the tag detail route).
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)
    # PROTECT rather than CASCADE: deleting a category must not silently strip
    # its tags from the articles that carry them. The API turns the resulting
    # ProtectedError into a readable 409 (see CategoryViewSet.destroy).
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='tags',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Article(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=255)
    # Editor.js documents are kept as structured JSON.  The data migration that
    # introduced this field wraps older text articles in safe paragraph blocks.
    content = models.JSONField(default=dict)
    excerpt = models.TextField(blank=True)
    featured_image = models.URLField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articles'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articles'
    )
    tags = models.ManyToManyField(
        Tag,
        through='ArticleTag',
        blank=True,
        related_name='articles'
    )
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    # Denormalized tallies, kept in step by `ArticleReactionManager.set_reaction`.
    # Stored rather than aggregated so the article list — which every page of the
    # site reads, and which already ends in `.distinct()` — never pays for a
    # GROUP BY. The trade is that the numbers can drift if a reaction row is ever
    # mutated outside that manager, which is why the manager is the only writer
    # and `recompute_reaction_counts` exists as a repair hatch.
    like_count = models.PositiveIntegerField(default=0)
    dislike_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-is_published', '-created_at']),
            models.Index(fields=['is_featured']),
        ]

    def __str__(self):
        return self.title


class ArticleTag(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('article', 'tag')


class CodeSnippet(models.Model):
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='code_snippets'
    )
    language = models.CharField(max_length=50)
    code = models.TextField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']


# Stored verdicts. Module-level rather than nested on ArticleReaction so the
# manager below can map them at class-definition time.
REACTION_LIKE = 'like'
REACTION_DISLIKE = 'dislike'
# Accepted on the wire only. It is not a stored value: clearing a reaction
# deletes the row, so `None` means "this reader has no verdict".
REACTION_NONE = 'none'


class ArticleReactionManager(models.Manager):
    """The only writer of `Article.like_count` / `Article.dislike_count`.

    Every reaction change funnels through `set_reaction` so the denormalized
    tallies can never drift from the underlying rows. The API is deliberately
    explicit rather than a blind toggle: the caller states the verdict it wants,
    so sending the same request twice lands in the same place instead of
    flipping back and forth.
    """

    # Maps a stored value to the Article column that tallies it.
    COUNT_FIELD = {REACTION_LIKE: 'like_count', REACTION_DISLIKE: 'dislike_count'}

    @transaction.atomic
    def set_reaction(self, article, user, value):
        """Record `user`'s verdict on `article` and return the value now stored.

        `value` is one of the stored choices, or None to clear the verdict.
        Returns None, 'like' or 'dislike'.
        """
        if value is not None and value not in self.COUNT_FIELD:
            raise ValueError(f'Unsupported reaction value: {value!r}')

        existing = self.select_for_update().filter(article=article, user=user).first()

        if value is None:
            if existing is not None:
                existing.delete()
                self._adjust(article, existing.value, -1)
            return None

        if existing is None:
            self.create(article=article, user=user, value=value)
            self._adjust(article, value, 1)
            return value

        if existing.value != value:
            self._adjust(article, existing.value, -1)
            existing.value = value
            existing.save(update_fields=['value', 'updated_at'])
            self._adjust(article, value, 1)
        return existing.value

    def _adjust(self, article, value, delta):
        """Apply `delta` to the tally for `value`, clamped at zero.

        The clamp is belt-and-braces: `_adjust` is only ever called in the same
        transaction as the row change that justifies it, so a negative count
        would mean that invariant had already been broken. Clamping means such a
        break shows up as a zero rather than as an impossible number rendered to
        readers.
        """
        field = self.COUNT_FIELD[value]
        Article.objects.filter(pk=article.pk).update(
            **{field: Greatest(F(field) + delta, 0)}
        )

    def recompute_reaction_counts(self):
        """Rebuild every article's tallies from its rows.

        A repair hatch, not a hot path. Useful if a reaction row is ever created,
        edited or deleted by hand — in the admin, say — which would otherwise
        leave the counters quietly wrong.
        """
        counts = {}
        for row in self.values('article_id', 'value').annotate(total=Count('id')):
            counts.setdefault(row['article_id'], {})[row['value']] = row['total']

        articles = []
        for article in Article.objects.all().only('pk', 'like_count', 'dislike_count'):
            tally = counts.get(article.pk, {})
            article.like_count = tally.get(REACTION_LIKE, 0)
            article.dislike_count = tally.get(REACTION_DISLIKE, 0)
            articles.append(article)
        Article.objects.bulk_update(articles, ['like_count', 'dislike_count'])
        return len(articles)


class ArticleReaction(models.Model):
    """One reader's verdict on one article: liked or disliked.

    `unique_together` is what makes "a reader may not both like and dislike the
    same article" a database guarantee rather than something the view layer has
    to be careful about. A like-to-dislike switch updates this one row instead of
    inserting a second, so the tallies can never disagree with the rows.
    """

    LIKE = REACTION_LIKE
    DISLIKE = REACTION_DISLIKE
    NONE = REACTION_NONE
    VALUE_CHOICES = [(LIKE, 'Like'), (DISLIKE, 'Dislike')]

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='reactions'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='article_reactions'
    )
    value = models.CharField(max_length=10, choices=VALUE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ArticleReactionManager()

    class Meta:
        unique_together = ('article', 'user')

    def __str__(self):
        return f'{self.user_id}:{self.article_id}={self.value}'

