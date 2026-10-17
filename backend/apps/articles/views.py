from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q, ProtectedError
from django.http import Http404
from drf_spectacular.utils import extend_schema
from django_filters.rest_framework import DjangoFilterBackend
from django_filters.rest_framework.filterset import BooleanFilter, FilterSet
from apps.chatbot.ingestion import ingest_article
from .models import Category, Tag, Article, ArticleReaction, REACTION_NONE
from .permissions import IsAuthorOrReadOnly
from .serializers import (
    CategorySerializer, TagSerializer,
    ArticleListSerializer, ArticleDetailSerializer, ArticleWriteSerializer,
    ReactionRequestSerializer, ReactionResultSerializer,
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

    def destroy(self, request, *args, **kwargs):
        """Delete the category, unless its tags still point at it.

        `Tag.category` is PROTECT, so deleting a category that still has tags
        raises ProtectedError. Django's admin renders that as a friendly page,
        but here it would surface as a 500; a 409 with the count is something
        the client can act on.
        """
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            count = len(exc.protected_objects)
            return Response(
                {
                    'detail': (
                        f'This category still has {count} tag'
                        f'{"s" if count != 1 else ""}. Move or delete them first.'
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )


class TagViewSet(AdminWriteOrReadAnyMixin, viewsets.ModelViewSet):
    # `tag.category` is part of the serializer's read shape, so it is joined
    # rather than fetched once per tag.
    queryset = Tag.objects.select_related('category')
    serializer_class = TagSerializer
    lookup_field = 'pk'
    filter_backends = [DjangoFilterBackend]
    # `?category__slug=` narrows the collection to one category's tags, which is
    # what the grouped tag cloud and the admin tag picker build their views from.
    filterset_fields = ['category__slug', 'category']


class ArticleFilterSet(FilterSet):
    """Query filters for the article collection.

    The admin panel's `mine=true` scope is *not* handled here. It has to widen
    the default published-only listing back out to include the caller's own
    drafts, and a `django-filter` filter can only ever narrow a queryset. It
    is read by `ArticleViewSet._is_admin_listing` instead; it is declared here
    only so it is documented and validated rather than silently ignored.
    """

    mine = BooleanFilter(method='ignore_mine')

    class Meta:
        model = Article
        fields = ['category__slug', 'tags__slug', 'is_featured', 'is_published']

    def ignore_mine(self, queryset, name, value):
        return queryset


class ArticleViewSet(AdminWriteOrReadAnyMixin, viewsets.ModelViewSet):
    ADMIN_ACTIONS = AdminWriteOrReadAnyMixin.ADMIN_ACTIONS + ('reindex',)
    # Opt in to the author check, since the mixin is also used by Category and
    # Tag, which have no `author` to compare against.
    author_scoped_writes = True
    # Actions that need their own permission class. The mixin's `get_permissions`
    # is the single source of truth for reads and admin writes, but it has no way
    # to express "signed in, but not necessarily staff", which is what a
    # reaction is. Naming the action here is therefore the only way to get past
    # it; a `permission_classes` on the `@action` would be silently ignored.
    AUTHENTICATED_ACTIONS = ('react',)
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

    def get_permissions(self):
        # See AUTHENTICATED_ACTIONS. Everything else defers to the mixin.
        if self.action in self.AUTHENTICATED_ACTIONS:
            return [IsAuthenticated()]
        return super().get_permissions()

    def _is_admin_listing(self):
        """True when the caller is a staff member asking for their own workspace.

        `mine=true` is the admin panel's marker. It is handled here rather than
        as a `django-filter` filter because it has to *widen* the default
        published-only listing back to include drafts — a filter only ever
        narrows, so it could not express this.
        """
        if self.action != 'list':
            return False
        user = self.request.user
        if not (user and user.is_authenticated and user.is_staff):
            return False
        return self.request.query_params.get('mine', '').lower() in ('1', 'true', 'yes')

    def get_queryset(self):
        # `tags__category` rather than plain `tags`: the nested TagSerializer
        # reads `tag.category`, so without the chained prefetch every tag on
        # every listed article would be its own query.
        queryset = Article.objects.select_related('category', 'author').prefetch_related(
            'tags__category', 'code_snippets'
        )
        user = self.request.user

        # Listings are published-only for everyone, including staff and
        # superusers. Drafts belong to the admin panel only: the home page,
        # the article index and the "keep learning" rail all read from this
        # endpoint, and an editor browsing them should see what a reader sees.
        # The scope is decided here rather than at each call site so a new
        # public listing cannot forget the filter and leak drafts.
        if self._is_admin_listing():
            if user.is_superuser:
                return queryset.distinct()
            # `author=None` is included so content imported or seeded without an
            # author is not stranded, invisible to everyone.
            return queryset.filter(Q(author=user) | Q(author__isnull=True)).distinct()

        if self.action == 'list':
            return queryset.filter(is_published=True).distinct()

        # Direct retrieval and writes still resolve a staff member's own draft:
        # the admin editor has to open one to keep working on it. This is scoped
        # to their own content by `IsAuthorOrReadOnly` on writes.
        if user.is_authenticated and user.is_staff:
            if user.is_superuser:
                return queryset.distinct()
            return queryset.filter(
                Q(author=user) | Q(author__isnull=True) | Q(is_published=True)
            ).distinct()

        return queryset.filter(is_published=True).distinct()

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

    @extend_schema(
        request=ReactionRequestSerializer,
        responses={200: ReactionResultSerializer},
        summary='Like, dislike, or clear a reaction to this article',
        description=(
            'Sets the signed-in reader\'s verdict to the value supplied. A reader '
            'holds at most one reaction per article, so sending `dislike` after '
            '`like` moves the reaction rather than adding a second one. Send '
            '`none` to withdraw it. Idempotent: repeating a request is a no-op.'
        ),
    )
    @action(detail=True, methods=['post'])
    def react(self, request, slug=None, **kwargs):
        """Like, dislike, or clear the signed-in reader's reaction.

        Requires an authenticated reader, which is why it is listed in
        AUTHENTICATED_ACTIONS rather than ADMIN_ACTIONS: the mixin has no way to
        express "signed in, but not staff".
        """
        article = self.get_object()

        serializer = ReactionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = serializer.validated_data['value']

        # `none` is a wire-only value; clearing means deleting the row.
        value = ArticleReaction.objects.set_reaction(
            article, request.user, None if requested == REACTION_NONE else requested
        )

        # The counters were bumped with `F()` expressions, so the in-memory
        # article still holds the values from before this request.
        article.refresh_from_db(fields=['like_count', 'dislike_count'])

        return Response({
            'value': value,
            'like_count': article.like_count,
            'dislike_count': article.dislike_count,
        })

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