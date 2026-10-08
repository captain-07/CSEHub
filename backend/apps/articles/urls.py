from rest_framework.routers import DefaultRouter
from django.urls import path

from .media import ImageUploadView
from .views import CategoryViewSet, TagViewSet, ArticleViewSet

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('tags', TagViewSet)
router.register('articles', ArticleViewSet)

urlpatterns = [
    path('uploads/images/', ImageUploadView.as_view(), name='image-upload'),
    *router.urls,
]
