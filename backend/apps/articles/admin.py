from django.contrib import admin
from .models import Category, Tag, Article, ArticleTag, CodeSnippet


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


class CodeSnippetInline(admin.TabularInline):
    model = CodeSnippet
    extra = 1
    fields = ['language', 'code', 'order']


class ArticleTagInline(admin.TabularInline):
    model = ArticleTag
    extra = 1


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'author', 'is_published', 'created_at']
    list_filter = ['category', 'is_published']
    search_fields = ['title', 'content']
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ['is_published']
    raw_id_fields = ['author']
    inlines = [ArticleTagInline, CodeSnippetInline]
    readonly_fields = ['created_at', 'updated_at']