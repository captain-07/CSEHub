from rest_framework import serializers
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
    author_email = serializers.EmailField(source='author.email', read_only=True, default='None')

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'content', 'category',
            'tags', 'code_snippets', 'author_email',
            'is_published', 'created_at', 'updated_at'
        ]