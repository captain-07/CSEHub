from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.articles.models import Article
from .models import Conversation
from .rag_chat import ChatServiceError, _response_text


class ChatTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='user@example.com', username='user')
        self.other = get_user_model().objects.create_user(email='other@example.com', username='other')
        self.article = Article.objects.create(title='Article', slug='article', content='x', is_published=True)

    def test_chat_requires_authentication(self):
        self.assertEqual(self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json').status_code, 401)

    @patch('apps.chatbot.views.answer_question', return_value='A grounded answer')
    def test_chat_stores_messages_and_isolated(self, answer):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json')
        self.assertEqual(response.status_code, 200)
        conversation = Conversation.objects.get(user=self.user, article=self.article)
        self.assertEqual(conversation.messages.count(), 2)
        self.client.force_authenticate(self.other)
        response = self.client.get('/api/articles/article/conversation/')
        self.assertEqual(response.data, {'messages': []})

    @patch('apps.chatbot.views.answer_question', side_effect=ChatServiceError('down'))
    def test_provider_failure_is_safe_and_persisted(self, answer):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/articles/article/ask/', {'question': 'Why?'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn("couldn't process", response.data['messages'][-1]['content'])

    def test_llm_response_normalization(self):
        self.assertEqual(_response_text('plain'), 'plain')
        self.assertEqual(_response_text(type('R', (), {'content': [{'text': 'one'}, {'text': ' two'}]})()), 'one two')
        with self.assertRaises(ChatServiceError):
            _response_text({'unexpected': 'shape'})
