"""Per-user ceilings on the assistant.

The ask routes are the only endpoints that spend money per request — a Gemini
call plus a Pinecone query — and the drawer is open to any signed-in account.
Without a ceiling, one scripted reader can exhaust the provider quota the whole
site shares.

Two windows are applied together: a burst limit that stops a loop, and a daily
limit that bounds what a single account can cost. Both routes use both classes,
and the cache key is scoped, so `/ask/` and `/ask/stream/` draw on one budget
rather than getting a fresh allowance each.

The rates live in settings and are read per request, which is what lets a
deployment tune them to its provider plan and a test lower them with
`override_settings`.
"""

from django.conf import settings
from rest_framework.throttling import UserRateThrottle


class ChatBurstThrottle(UserRateThrottle):
    """Short window: a reader typing questions, not a script in a loop."""

    scope = 'chat-burst'

    def get_rate(self):
        return settings.CHAT_THROTTLE_RATE


class ChatDailyThrottle(UserRateThrottle):
    """Long window: the most one account may spend in a day."""

    scope = 'chat-daily'

    def get_rate(self):
        return settings.CHAT_THROTTLE_DAILY_RATE
