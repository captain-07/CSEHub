from rest_framework import serializers
from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'role', 'content', 'created_at']


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    article_title = serializers.CharField(source='article.title', read_only=True)

    class Meta:
        model = Conversation
        fields = ['id', 'article', 'article_title', 'messages', 'created_at']


class AskQuestionSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)