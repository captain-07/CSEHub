from django.contrib import admin
from django.db.models import Q
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
    list_display = ['title', 'category', 'author', 'is_published', 'is_featured', 'created_at']
    list_filter = ['category', 'is_published', 'is_featured']
    # `content` is a JSONField, which has no text lookup — searching it raises
    # FieldError, so the admin searches the human-readable text fields instead.
    search_fields = ['title', 'excerpt']
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ['is_published', 'is_featured']
    list_select_related = ['category', 'author']
    inlines = [ArticleTagInline, CodeSnippetInline]
    readonly_fields = ['created_at', 'updated_at']

    def get_queryset(self, request):
        """Mirror the API: a non-superuser admin manages only their own articles.

        The API scopes staff to `Q(author=user) | Q(author__isnull=True)`, and
        this site has to agree or it becomes a back door around that rule.
        """
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(Q(author=request.user) | Q(author__isnull=True))

    def has_change_permission(self, request, obj=None):
        # `get_queryset` hides other authors' articles from the list, but a
        # staff user can still reach one by typing its id into the URL.
        if obj is None or request.user.is_superuser:
            return super().has_change_permission(request, obj)
        return obj.author_id in (None, request.user.pk)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)