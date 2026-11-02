from django.apps import AppConfig


class ArticlesConfig(AppConfig):
    name = 'apps.articles'

    def ready(self):
        # Imported here rather than at module scope so the app registry is
        # populated before the signal receivers are registered.
        from . import signals  # noqa: F401
