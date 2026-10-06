from rest_framework import serializers
from django.db import transaction

from .models import Category, Tag, Article, CodeSnippet


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


class ArticleListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Article
        fields = ['id', 'title', 'slug', 'category', 'tags', 'created_at']


class ArticleDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    code_snippets = CodeSnippetSerializer(many=True, read_only=True)
    author_email = serializers.EmailField(source='author.email', read_only=True, default=None)

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'content', 'category',
            'tags', 'code_snippets', 'author_email',
            'is_published', 'created_at', 'updated_at'
        ]


class ArticleWriteSerializer(serializers.ModelSerializer):
    """Staff-facing representation with explicit writable relationships."""

    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False, allow_null=True
    )
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    code_snippets = CodeSnippetSerializer(many=True, required=False)

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'content', 'category', 'tags',
            'code_snippets', 'is_published', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code_snippets(self, snippets):
        orders = [snippet.get('order', 0) for snippet in snippets]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError('Each code snippet must have a unique order.')
        return snippets

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
