from django.db import models
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
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)

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
