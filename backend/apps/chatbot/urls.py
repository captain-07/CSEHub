from django.urls import path
from .views import AskArticleView, ConversationDetailView

urlpatterns = [
    path('articles//ask/', AskArticleView.as_view(), name='ask-article'),
    path('articles//conversation/', ConversationDetailView.as_view(), name='conversation-detail'),
]