from django.contrib import admin
from django.db.models import Q
from .models import Category, Tag, Article, ArticleReaction, ArticleTag, CodeSnippet


class TagInline(admin.TabularInline):
    """Tags belong to a category, so they can be filed from the category page."""

    model = Tag
    extra = 0
    fields = ['name', 'slug']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [TagInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'category']
    list_filter = ['category']
    list_select_related = ['category']
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
    list_display = ['title', 'category', 'author', 'is_published', 'is_featured',
                    'like_count', 'dislike_count', 'created_at']
    list_filter = ['category', 'is_published', 'is_featured']
    # `content` is a JSONField, which has no text lookup — searching it raises
    # FieldError, so the admin searches the human-readable text fields instead.
    search_fields = ['title', 'excerpt']
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ['is_published', 'is_featured']
    list_select_related = ['category', 'author']
    inlines = [ArticleTagInline, CodeSnippetInline]
    # The tallies are maintained by ArticleReactionManager. Editable here only
    # because an admin may legitimately want to correct a drifted counter; the
    # repair hatch is `manage.py recompute_reaction_counts`.
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


@admin.register(ArticleReaction)
class ArticleReactionAdmin(admin.ModelAdmin):
    list_display = ['article', 'user', 'value', 'created_at']
    list_filter = ['value']
    search_fields = ['article__title', 'user__email']
    list_select_related = ['article', 'user']
    # Hand-editing a row here desynchronises the article's tallies, which only
    # `ArticleReactionManager.set_reaction` maintains. That is deliberate: the
    # counts are the reader-facing number and must not be silently recomputed by
    # an unrelated save. Run `manage.py recompute_reaction_counts` afterwards.
