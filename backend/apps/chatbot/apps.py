from django.apps import AppConfig


class ChatbotConfig(AppConfig):
    name = 'apps.chatbot'

    def ready(self):
        import apps.chatbot.signals  # noqa