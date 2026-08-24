from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import get_object_or_404
from apps.articles.models import Article
from .models import Conversation, Message
from .serializers import ConversationSerializer, AskQuestionSerializer
from .rag_chat import answer_question


class AskArticleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        article = get_object_or_404(Article, slug=slug, is_published=True)

        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        conversation, _ = Conversation.objects.get_or_create(
            user=request.user,
            article=article,
        )

        Message.objects.create(
            conversation=conversation,
            role='user',
            content=question,
        )

        try:
            answer = answer_question(article, question)
        except Exception as e:
            answer = "Sorry, I couldn't process that question right now."
            print(f"[RAG] Chat error: {e}")

        Message.objects.create(
            conversation=conversation,
            role='assistant',
            content=answer,
        )

        return Response(ConversationSerializer(conversation).data)


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        article = get_object_or_404(Article, slug=slug, is_published=True)
        conversation = Conversation.objects.filter(
            user=request.user, article=article
        ).first()

        if not conversation:
            return Response({'messages': []})

        return Response(ConversationSerializer(conversation).data)