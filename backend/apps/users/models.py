from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

# Create your models here.

class User(AbstractUser):
    email = models.EmailField(unique=True)
    supabase_uid = models.UUIDField(unique=True, null=True, blank=True)
    avatar_url = models.URLField(blank=True)
    display_name = models.CharField(max_length=100, blank=True)

    # A ban is deliberately separate from Django's `is_active`. `is_active` is a
    # general account switch (and the Django admin's own), while `is_banned`
    # records an editorial decision with a time and a reason, and is what the
    # admin panel can undo without guessing whether the account was disabled for
    # some other purpose.
    is_banned = models.BooleanField(default=False)
    banned_at = models.DateTimeField(null=True, blank=True)
    ban_reason = models.CharField(max_length=255, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email

    def ban(self, reason=''):
        """Lock the account out and close every session it still has open.

        Authentication is checked on every request, so the next API call from a
        banned reader is refused even though Supabase will keep honouring their
        token until it expires. Closing the local session rows keeps the login
        log from claiming a banned reader is still online.
        """
        self.is_banned = True
        self.banned_at = timezone.now()
        self.ban_reason = (reason or '')[:255]
        self.save(update_fields=['is_banned', 'banned_at', 'ban_reason'])
        return self.login_sessions.filter(logged_out_at__isnull=True).update(
            logged_out_at=self.banned_at,
        )

    def unban(self):
        """Restore access. Sessions closed by the ban stay closed."""
        self.is_banned = False
        self.banned_at = None
        self.ban_reason = ''
        self.save(update_fields=['is_banned', 'banned_at', 'ban_reason'])
        return self


def session_active_window_minutes():
    """How long a silent session is still considered active.

    The browser checks in periodically (see `auth-state.js`), so a row whose
    `last_seen_at` has fallen behind that heartbeat by this much is treated as
    gone even when no `SIGNED_OUT` event ever arrived. A closed tab cannot send
    a logout request, so freshness — not a flag — is what makes "currently
    online" honest.
    """
    return getattr(settings, 'SESSION_ACTIVE_WINDOW_MINUTES', 30)


def active_session_cutoff(now=None):
    now = now or timezone.now()
    return now - timedelta(minutes=session_active_window_minutes())


class UserSession(models.Model):
    """One Supabase sign-in session, from login to logout.

    A row is created the first time a browser announces a session and is keyed
    by Supabase's `session_id` claim, so token refreshes, page reloads and extra
    tabs all update the same row rather than inventing a new login. `logged_out_at`
    is written when the reader signs out; otherwise `last_seen_at` decides
    whether the session is still alive.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_sessions',
    )
    session_key = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    logged_in_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    logged_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_seen_at']
        indexes = [
            models.Index(fields=['logged_out_at', 'last_seen_at']),
            models.Index(fields=['user', '-last_seen_at']),
        ]

    def __str__(self):
        return f'{self.user} · {self.logged_in_at:%Y-%m-%d %H:%M}'

    @property
    def is_active(self):
        if self.logged_out_at is not None:
            return False
        return self.last_seen_at >= active_session_cutoff()
    