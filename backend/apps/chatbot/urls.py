from django.urls import path
from .views import AskArticleView, AskArticleStreamView, ConversationDetailView

urlpatterns = [
    path('articles/<slug:slug>/ask/', AskArticleView.as_view(), name='ask-article'),
    # The same answer, written out as it is produced. Kept as a separate route
    # rather than a flag on `ask/` so the existing whole-reply contract — and
    # every client already reading it — is untouched.
    path('articles/<slug:slug>/ask/stream/', AskArticleStreamView.as_view(), name='ask-article-stream'),
    path('articles/<slug:slug>/conversation/', ConversationDetailView.as_view(), name='conversation-detail'),
]
