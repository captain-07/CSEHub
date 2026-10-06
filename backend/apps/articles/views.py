
# Create your views here.
from rest_framework import viewsets, filters
from rest_framework.permissions import IsAdminUser, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from .models import Category, Tag, Article
from .serializers import (
    CategorySerializer, TagSerializer,
    ArticleListSerializer, ArticleDetailSerializer, ArticleWriteSerializer
)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [AllowAny]


class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category__slug', 'tags__slug']
    search_fields = ['title', 'content']
    ordering_fields = ['created_at']
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
        # Staff need drafts to manage content; everyone else can only see published work.
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_published=True)
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [AllowAny()]
