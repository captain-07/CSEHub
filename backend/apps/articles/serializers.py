from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from .models import Category, Tag, Article, CodeSnippet, SUPPORTED_BLOCK_TYPES


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug']


class CodeSnippetSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeSnippet
        fields = ['language', 'code', 'order']


def article_author_name(article):
    """Public byline for an article, or None when it has no author.

    The name is always derived server-side: `display_name` when the author set
    one, otherwise the username, and only as a last resort the email. The FK is
    nullable, so every consumer must tolerate a null byline.
    """
    author = article.author
    if not author:
        return None
    return author.display_name or author.username or author.email


# Both read serializers expose the byline. Cards are built from the *list*
# endpoint, so restricting it to the detail serializer silently guarantees that
# article grids can never show an author regardless of what the database holds.
# The fields are repeated rather than mixed in because DRF's metaclass only
# collects declared fields from classes it built, so a plain mixin contributes
# nothing and `author_name` would be treated as a model field.
class ArticleListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    author_email = serializers.EmailField(source='author.email', read_only=True, default=None)
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['id', 'title', 'slug', 'excerpt', 'featured_image', 'category', 'tags',
                  'author_name', 'author_email',
                  'is_published', 'is_featured', 'created_at', 'updated_at']

    def get_author_name(self, article):
        return article_author_name(article)


class ArticleDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    code_snippets = CodeSnippetSerializer(many=True, read_only=True)
    author_email = serializers.EmailField(source='author.email', read_only=True, default=None)
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'excerpt', 'featured_image', 'content', 'category',
            'tags', 'code_snippets', 'author_name', 'author_email',
            'is_published', 'is_featured', 'created_at', 'updated_at'
        ]

    def get_author_name(self, article):
        return article_author_name(article)


class ArticleWriteSerializer(serializers.ModelSerializer):
    """Staff-facing representation with explicit writable relationships."""

    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False, allow_null=True
    )
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    code_snippets = CodeSnippetSerializer(many=True, required=False)
    slug = serializers.CharField(required=False, allow_blank=True, max_length=255)
    # Write-only from the public side: `perform_create` already sets the author
    # to the requesting staff user, so this exists to let an admin reassign a
    # byline on content that predates that behaviour (or was seeded).
    author = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'excerpt', 'featured_image', 'content', 'category', 'tags',
            'code_snippets', 'author', 'is_published', 'is_featured', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code_snippets(self, snippets):
        orders = [snippet.get('order', 0) for snippet in snippets]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError('Each code snippet must have a unique order.')
        return snippets

    def validate(self, attrs):
        """Derive a unique slug when the client leaves it blank.

        On a partial update neither title nor slug may be present, so the
        existing slug is retained rather than demanding one from the client.
        """
        slug = (attrs.get('slug') or '').strip()
        title = (attrs.get('title') or '').strip()

        if self.instance is not None and not slug and not title:
            return attrs

        if not slug and title:
            slug = slugify(title)[:255]
        if not slug:
            raise serializers.ValidationError({'slug': 'A slug or a title is required.'})

        queryset = Article.objects.filter(slug=slug)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            base, suffix = slug, 2
            while Article.objects.filter(slug=f'{base}-{suffix}').exists():
                suffix += 1
            slug = f'{base}-{suffix}'
        attrs['slug'] = slug
        return attrs

    def validate_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Content must be an Editor.js document object.')
        blocks = value.get('blocks')
        if not isinstance(blocks, list):
            raise serializers.ValidationError('Content must include a blocks array.')
        if len(blocks) > 500:
            raise serializers.ValidationError('Content has too many blocks.')
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') not in SUPPORTED_BLOCK_TYPES or not isinstance(block.get('data'), dict):
                raise serializers.ValidationError('Content contains an unsupported or malformed Editor.js block.')
        return value

    @transaction.atomic
    def create(self, validated_data):
        tags = validated_data.pop('tags', [])
        snippets = validated_data.pop('code_snippets', [])
        article = Article.objects.create(**validated_data)
        article.tags.set(tags)
        CodeSnippet.objects.bulk_create(
            [CodeSnippet(article=article, **snippet) for snippet in snippets]
        )
        return article

    @transaction.atomic
    def update(self, instance, validated_data):
        tags = validated_data.pop('tags', None)
        snippets = validated_data.pop('code_snippets', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        if snippets is not None:
            instance.code_snippets.all().delete()
            CodeSnippet.objects.bulk_create(
                [CodeSnippet(article=instance, **snippet) for snippet in snippets]
            )
        return instance
