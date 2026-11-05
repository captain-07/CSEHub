from django.contrib import admin
from django.db.models import Q
from .models import (
    Category, Tag, Article, ArticleReaction, ArticleTag, CodeSnippet, QuizQuestion,
)


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
                    'like_count', 'dislike_count', 'view_count', 'created_at']
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
    #
    # `view_count` is read-only instead: nothing in the database records the
    # individual views, so a hand-edit here could never be derived again or
    # checked against anything. It is a tally, not a field.
    readonly_fields = ['created_at', 'updated_at', 'view_count']

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


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    """The review and authoring surface for the quiz.

    AI-generated rows arrive inactive, so `source` and `is_active` are the
    review workflow: filter to AI rows, activate the good ones in bulk. The
    article page only ever reads active rows. `clean()` on the model rejects a
    missing or duplicate option, because the admin form runs `full_clean()`.
    """

    list_display = ['prompt', 'article', 'source', 'correct_option', 'is_active', 'created_at']
    list_filter = ['source', 'is_active']
    list_editable = ['is_active']
    search_fields = ['prompt', 'article__title']
    autocomplete_fields = ['article']
    list_select_related = ['article']
    readonly_fields = ['ai_model']
    actions = ['activate_selected', 'deactivate_selected']
    fields = [
        'article', 'prompt',
        'option_a', 'option_b', 'option_c', 'option_d',
        'correct_option', 'explanation', 'source', 'ai_model', 'is_active',
    ]

    @admin.action(description='Activate selected quiz questions')
    def activate_selected(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'Activated {updated} question(s).')

    @admin.action(description='Deactivate selected quiz questions')
    def deactivate_selected(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {updated} question(s).')


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
