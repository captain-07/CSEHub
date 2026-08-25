from django.urls import path
from .views import AskArticleView, ConversationDetailView

urlpatterns = [
    path('articles/<slug:slug>/ask/', AskArticleView.as_view(), name='ask-article'),
    path('articles/<slug:slug>/conversation/', ConversationDetailView.as_view(), name='conversation-detail'),
]