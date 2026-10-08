from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from django_filters.rest_framework.filterset import BooleanFilter, FilterSet
from apps.chatbot.ingestion import ingest_article
from .models import Category, Tag, Article
from .permissions import IsAuthorOrReadOnly
from .serializers import (
    CategorySerializer, TagSerializer,
    ArticleListSerializer, ArticleDetailSerializer, ArticleWriteSerializer
)
import logging

logger = logging.getLogger(__name__)


class AdminWriteOrReadAnyMixin:
    """Public read, admin-only writes.

    The frontend hides admin controls, but this is the layer that actually
    enforces authorization: a client that skips the UI still gets a 403.

    `get_permissions` is the single source of truth, so any admin-only action
    must be listed in ADMIN_ACTIONS — a per-action `permission_classes` would be
    silently ignored because this method overrides DRF's default resolution.

    "Admin" here means a staff user; it is not itself a grant to edit any
    particular article. A viewset that scopes writes per author sets
    `author_scoped_writes = True`, which adds the object-level check.
    """

    ADMIN_ACTIONS = ('create', 'update', 'partial_update', 'destroy')

    def get_permissions(self):
        if self.action in self.ADMIN_ACTIONS:
            # The object-level check only applies to viewsets whose model has an
            # `author`; ArticleViewSet appends it, and shared mixins such as
            # CategoryViewSet have no such field to compare against.
            perms = [IsAdminUser()]
            if getattr(self, 'author_scoped_writes', False):
                perms.append(IsAuthorOrReadOnly())
            return perms
        return [AllowAny()]


class CategoryViewSet(AdminWriteOrReadAnyMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = 'pk'


class TagViewSet(AdminWriteOrReadAnyMixin, viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    lookup_field = 'pk'


class ArticleFilterSet(FilterSet):
    """`mine=true` narrows the listing to the requesting staff member's articles.

    This is opt-in rather than a change to `get_queryset`, because the admin
    panel and the public site share this endpoint. Narrowing the default
    queryset would hide other people's published articles from a logged-in
    editor browsing the public listing — that content is public, so hiding it
    would be wrong.

    Only ever narrows: `get_queryset` already decides what a user may see, so
    this cannot widen the result set for anyone.
    """

    mine = BooleanFilter(method='filter_mine')

    class Meta:
        model = Article
        fields = ['category__slug', 'tags__slug', 'is_featured', 'is_published']

    def filter_mine(self, queryset, name, value):
        if not value:
            return queryset
        user = self.request.user
        if not (user.is_authenticated and user.is_staff):
            # A non-staff caller has no drafts of their own, so this reduces to
            # the published set `get_queryset` already returned.
            return queryset
        if user.is_superuser:
            return queryset
        return queryset.filter(Q(author=user) | Q(author__isnull=True))


class ArticleViewSet(AdminWriteOrReadAnyMixin, viewsets.ModelViewSet):
    ADMIN_ACTIONS = AdminWriteOrReadAnyMixin.ADMIN_ACTIONS + ('reindex',)
    # Opt in to the author check, since the mixin is also used by Category and
    # Tag, which have no `author` to compare against.
    author_scoped_writes = True
    queryset = Article.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # `is_published` is exposed so the admin list can filter by status. It is safe
    # to expose publicly because `get_queryset` already hides drafts from anyone
    # who is not staff, so the filter can only ever narrow an already-filtered set.
    filterset_class = ArticleFilterSet
    search_fields = ['title', 'excerpt']
    ordering_fields = ['created_at', 'title']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ArticleWriteSerializer
        if self.action == 'list':
            return ArticleListSerializer
        return ArticleDetailSerializer

    def get_queryset(self):
        queryset = Article.objects.select_related('category', 'author').prefetch_related(
            'tags', 'code_snippets'
        )
        user = self.request.user
        if not (user.is_authenticated and user.is_staff):
            # Everyone else sees published work only, whoever wrote it.
            return queryset.filter(is_published=True).distinct()

        # Staff see everything already published — that content is public, and
        # hiding colleagues' published work would just look broken — plus their
        # own drafts. `author=None` is included so content imported or seeded
        # without an author is not stranded, invisible to everyone.
        if user.is_superuser:
            return queryset.distinct()
        return queryset.filter(
            Q(author=user) | Q(author__isnull=True) | Q(is_published=True)
        ).distinct()

    lookup_field = 'slug'
    lookup_value_regex = '[^/]+'

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_val = self.kwargs.get(lookup_url_kwarg)

        # Primary lookup: slug
        obj = queryset.filter(slug=lookup_val).first()
        if obj is not None:
            self.check_object_permissions(self.request, obj)
            return obj

        # Backward-compatibility fallback: if lookup_val is numeric, try integer id/pk
        if lookup_val and str(lookup_val).isdigit():
            obj = queryset.filter(pk=int(lookup_val)).first()
            if obj is not None:
                self.check_object_permissions(self.request, obj)
                return obj

        raise Http404("No article found matching the query")

    def perform_create(self, serializer):
        # The author is the creator, so a new article is always one they can
        # edit. A superuser may pass `author` to publish something on someone
        # else's behalf; anyone else passing it was refused by the serializer.
        if serializer.validated_data.get('author') is None:
            serializer.save(author=self.request.user)
        else:
            serializer.save()

    @action(detail=True, methods=['post'])
    def reindex(self, request, slug=None, **kwargs):
        """Send this article's content to the vector store.

        Embedding is deliberately *not* performed inside `perform_create` /
        `update`: it costs a network round-trip to Pinecone plus a Gemini
        embedding call, which must not block a normal save. Admins trigger it
        explicitly, or via `manage.py ingest_articles`.
        """
        article = self.get_object()
        if not article.is_published:
            return Response(
                {'detail': 'Publish this article before indexing it.'},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            chunks = ingest_article(article)
        except RuntimeError as exc:
            # RAG is optional infrastructure; a missing key must not look like
            # a server fault or silently corrupt the article save.
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception('Reindexing failed for article %s', article.pk)
            return Response(
                {'detail': f'Reindexing failed: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'status': 'indexed', 'slug': article.slug, 'chunks': chunks})