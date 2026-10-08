from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import get_object_or_404
from rest_framework import status
from drf_spectacular.utils import extend_schema
from apps.articles.models import Article
from .models import Conversation, Message
from .serializers import ConversationSerializer, AskQuestionSerializer
from .rag_chat import answer_question, ChatServiceError
import logging

logger = logging.getLogger(__name__)


def _conversation_payload(conversation, messages):
    """One response shape for both ask and history, so clients need one parser."""
    return {
        'id': conversation.id,
        'article': conversation.article_id,
        'article_title': conversation.article.title,
        'created_at': conversation.created_at,
        'messages': [
            {
                'id': message.id,
                'role': message.role,
                'content': message.content,
                'created_at': message.created_at,
            }
            for message in messages
        ],
    }


class AskArticleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AskQuestionSerializer,
        responses={200: ConversationSerializer},
        summary='Ask the learning assistant about an article',
    )
    def post(self, request, slug):
        article = Article.objects.filter(slug=slug, is_published=True).first()
        if not article and str(slug).isdigit():
            article = Article.objects.filter(pk=int(slug), is_published=True).first()
        if not article:
            raise Http404("No published article found matching the query")

        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        conversation, _ = Conversation.objects.get_or_create(
            user=request.user,
            article=article,
        )

        recent_messages = list(conversation.messages.order_by('-created_at')[:10])
        history = '\n'.join(
            f"{message.role}: {message.content}"
            for message in reversed(recent_messages)
        )
        Message.objects.create(
            conversation=conversation,
            role='user',
            content=question,
        )

        try:
            answer = answer_question(article, question, history=history)
        except ChatServiceError as exc:
            # Surface the real reason instead of a generic apology with a 200:
            # the client can then tell the user whether to retry.
            logger.warning('RAG chat unavailable for article %s: %s', article.slug, exc)
            return Response(
                {'detail': str(exc), 'code': 'chat_unavailable'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception('Unexpected RAG chat failure for article %s', article.slug)
            return Response(
                {'detail': 'The assistant is temporarily unavailable. Please try again.',
                 'code': 'chat_error'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        Message.objects.create(
            conversation=conversation,
            role='assistant',
            content=answer,
        )

        messages = list(conversation.messages.order_by('created_at'))
        return Response(_conversation_payload(conversation, messages))


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: ConversationSerializer},
        summary='Fetch the current user conversation for an article',
    )
    def get(self, request, slug):
        article = Article.objects.filter(slug=slug, is_published=True).first()
        if not article and str(slug).isdigit():
            article = Article.objects.filter(pk=int(slug), is_published=True).first()
        if not article:
            raise Http404("No published article found matching the query")

        conversation = Conversation.objects.filter(
            user=request.user, article=article
        ).first()

        if not conversation:
            return Response({
                'id': None,
                'article': article.id,
                'article_title': article.title,
                'created_at': None,
                'messages': [],
            })

        messages = list(conversation.messages.order_by('created_at'))
        return Response(_conversation_payload(conversation, messages))