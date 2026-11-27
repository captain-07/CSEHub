import ipaddress

from django.db import IntegrityError
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User, UserSession, active_session_cutoff, session_active_window_minutes
from .serializers import (
    AdminUserSerializer,
    AdminUserSummarySerializer,
    BanUserSerializer,
    SessionEndResultSerializer,
    SessionKeySerializer,
    SessionPingResultSerializer,
    UserBanResultSerializer,
    UserProfileSerializer,
    UserSessionSerializer,
    UserSessionSummarySerializer,
)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserProfileSerializer},
        summary='Fetch the authenticated user profile',
        description='`is_admin` mirrors the server-side staff flag and is read-only.',
    )
    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)

    @extend_schema(
        request=UserProfileSerializer,
        responses={200: UserProfileSerializer},
        summary='Update the authenticated user profile',
        description='Only `username`, `display_name` and `avatar_url` are writable.',
    )
    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# --- Login sessions ---------------------------------------------------------
#
# Supabase owns the actual session; this app keeps a record of it so an editor
# can see who signed in, when they last did anything, and who is online now.
# Nothing here grants access — a valid bearer token is still the only way in.

_SESSION_KEY_CHARS = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'
)


def _session_key_from_request(request):
    """Identify the sign-in session this request belongs to.

    The verified `session_id` claim is authoritative. The request body is only a
    fallback for a token that omits it (and for tests), and it is scoped to the
    caller by `_record_session` so one account cannot write to another's row.
    """
    claims = getattr(request, 'supabase_claims', None) or {}
    key = str(claims.get('session_id') or '').strip()

    if not key:
        body = request.data if isinstance(request.data, dict) else {}
        key = str(body.get('session_key') or '').strip()

    if not key:
        raise ValidationError(
            {'session_key': 'This sign-in session could not be identified.'}
        )
    if len(key) > 64 or any(char not in _SESSION_KEY_CHARS for char in key):
        raise ValidationError({'session_key': 'Invalid session identifier.'})
    return key


def _client_ip(request):
    """The visitor's address, tolerating the proxy header Render sets."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    raw = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _record_session(request, key):
    """Create the row on first contact, refresh it on every later ping."""
    now = timezone.now()
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:512]
    defaults = {
        'user': request.user,
        'logged_in_at': now,
        'last_seen_at': now,
        'ip_address': _client_ip(request),
        'user_agent': user_agent,
    }

    try:
        session, created = UserSession.objects.get_or_create(
            session_key=key, defaults=defaults,
        )
    except IntegrityError:
        # Two tabs pinging at once: the other request inserted the row first.
        session, created = UserSession.objects.get(session_key=key), False

    if not created:
        if session.user_id != request.user.pk:
            raise PermissionDenied('This session belongs to another account.')
        # An explicitly ended session stays ended. A heartbeat that raced the
        # logout must not silently reopen it.
        if session.logged_out_at is None:
            session.last_seen_at = now
            update_fields = ['last_seen_at']
            if not session.ip_address and defaults['ip_address']:
                session.ip_address = defaults['ip_address']
                update_fields.append('ip_address')
            if not session.user_agent and user_agent:
                session.user_agent = user_agent
                update_fields.append('user_agent')
            session.save(update_fields=update_fields)

    return session, created


class SessionPingView(APIView):
    """Record that a browser holding a session is still here.

    Called on page load, after sign-in and on a heartbeat. It is deliberately
    idempotent: the first call creates the row, the rest only move
    `last_seen_at`, so a refresh or a second tab never looks like a new login.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SessionKeySerializer,
        responses={200: SessionPingResultSerializer},
        summary='Record or refresh the current login session',
        description=(
            'The session is identified by the token\'s `session_id` claim. '
            'Repeating the call updates `last_seen_at` rather than creating a '
            'second login.'
        ),
    )
    def post(self, request):
        key = _session_key_from_request(request)
        session, created = _record_session(request, key)
        return Response(
            SessionPingResultSerializer({
                'session_key': session.session_key,
                'created': created,
                'logged_in_at': session.logged_in_at,
                'last_seen_at': session.last_seen_at,
                'logged_out_at': session.logged_out_at,
            }).data
        )


class SessionEndView(APIView):
    """Close the current login session.

    The browser calls this *before* clearing its Supabase session, because the
    bearer token is the only proof that the caller owns the row. A closed tab
    cannot call it at all; `last_seen_at` ages those sessions out.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SessionKeySerializer,
        responses={200: SessionEndResultSerializer},
        summary='End the current login session',
        description='Marks `logged_out_at`. A session that was never recorded is a no-op.',
    )
    def post(self, request):
        key = _session_key_from_request(request)
        session = UserSession.objects.filter(session_key=key).first()

        if session is None:
            # Tracking may have started after this sign-in. Nothing is wrong
            # with the logout itself, so do not turn it into an error.
            return Response({'session_key': key, 'ended': False, 'logged_out_at': None})

        if session.user_id != request.user.pk:
            raise PermissionDenied('This session belongs to another account.')

        if session.logged_out_at is None:
            session.logged_out_at = timezone.now()
            session.save(update_fields=['logged_out_at'])

        return Response(
            SessionEndResultSerializer({
                'session_key': session.session_key,
                'ended': True,
                'logged_out_at': session.logged_out_at,
            }).data
        )


class UserSessionListView(generics.ListAPIView):
    """The admin's login log: one row per sign-in session."""

    permission_classes = [IsAdminUser]
    serializer_class = UserSessionSerializer

    @extend_schema(
        summary='List login sessions',
        description=(
            'Admin only. `?status=active` keeps sessions that have not been '
            'signed out and whose heartbeat is inside the active window; '
            '`?status=ended` is the complement. `?search=` matches the email, '
            'username or display name.'
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = UserSession.objects.select_related('user')
        cutoff = active_session_cutoff()
        status_filter = self.request.query_params.get('status', '').strip()

        if status_filter == 'active':
            queryset = queryset.filter(
                logged_out_at__isnull=True,
                last_seen_at__gte=cutoff,
            )
        elif status_filter == 'ended':
            queryset = queryset.filter(
                Q(logged_out_at__isnull=False) | Q(last_seen_at__lt=cutoff)
            )

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(user__email__icontains=search)
                | Q(user__username__icontains=search)
                | Q(user__display_name__icontains=search)
            )

        return queryset.order_by('-last_seen_at')


class UserSessionSummaryView(APIView):
    """Counts for the top of the login log, kept out of the paginated list."""

    permission_classes = [IsAdminUser]

    @extend_schema(
        responses={200: UserSessionSummarySerializer},
        summary='Summarise login activity',
        description='Admin only. Counts of active, today\'s and total sessions.',
    )
    def get(self, request):
        now = timezone.now()
        cutoff = active_session_cutoff(now)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        payload = {
            'active': UserSession.objects.filter(
                logged_out_at__isnull=True, last_seen_at__gte=cutoff,
            ).count(),
            'logins_today': UserSession.objects.filter(
                logged_in_at__gte=start_of_today,
            ).count(),
            'total': UserSession.objects.count(),
            'active_window_minutes': session_active_window_minutes(),
        }
        return Response(UserSessionSummarySerializer(payload).data)


# --- Account administration -------------------------------------------------
#
# A ban is a local decision enforced by `SupabaseJWTAuthentication` on every
# request. The project deliberately has no Supabase service-role key, so it
# cannot revoke the provider session itself; refusing the token here is what
# makes the ban effective for this API, and closing the login-session rows keeps
# the admin's "active now" list honest.


def _ban_result(user, ended_sessions=0):
    return {
        'id': user.pk,
        'is_banned': user.is_banned,
        'banned_at': user.banned_at,
        'ban_reason': user.ban_reason,
        'ended_sessions': ended_sessions,
    }


class AdminUserListView(generics.ListAPIView):
    """Every account, for the admin panel's ban/unban controls."""

    permission_classes = [IsAdminUser]
    serializer_class = AdminUserSerializer

    @extend_schema(
        summary='List user accounts',
        description=(
            'Admin only. `?status=banned` keeps banned accounts and '
            '`?status=active` the rest; `?search=` matches email, username or '
            'display name. `last_seen_at` is the newest login heartbeat.'
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = User.objects.annotate(
            last_seen_at=Max('login_sessions__last_seen_at'),
        )
        status_filter = self.request.query_params.get('status', '').strip()

        if status_filter == 'banned':
            queryset = queryset.filter(is_banned=True)
        elif status_filter == 'active':
            queryset = queryset.filter(is_banned=False)

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(username__icontains=search)
                | Q(display_name__icontains=search)
            )

        return queryset.order_by('-date_joined', '-id')


class UserBanView(APIView):
    """Ban an account and close any session it still has open.

    Staff accounts and the caller's own account are refused: the panel is for
    readers, and an editor who locks themselves out has no way back in through
    it. Re-banning an already banned account is a no-op rather than an error.
    """

    permission_classes = [IsAdminUser]

    @extend_schema(
        request=BanUserSerializer,
        responses={200: UserBanResultSerializer},
        summary='Ban a user account',
        description=(
            'Admin only. The optional `reason` is shown in the account list. '
            'Every open login session is closed at the same time.'
        ),
    )
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)

        if user.pk == request.user.pk:
            raise ValidationError(
                {'detail': 'You cannot ban your own account.'}
            )
        if user.is_staff or user.is_superuser:
            raise ValidationError(
                {'detail': 'Staff accounts cannot be banned here.'}
            )

        serializer = BanUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if user.is_banned:
            return Response(UserBanResultSerializer(_ban_result(user)).data)

        ended = user.ban(serializer.validated_data.get('reason', ''))
        return Response(UserBanResultSerializer(_ban_result(user, ended)).data)


class UserUnbanView(APIView):
    """Restore an account's access. Sessions closed by the ban stay closed."""

    permission_classes = [IsAdminUser]

    @extend_schema(
        request=None,
        responses={200: UserBanResultSerializer},
        summary='Unban a user account',
        description='Admin only. Unbanning an account that is not banned is a no-op.',
    )
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)

        if not user.is_banned:
            return Response(UserBanResultSerializer(_ban_result(user)).data)

        user.unban()
        return Response(UserBanResultSerializer(_ban_result(user)).data)


class AdminUserSummaryView(APIView):
    """Counts for the top of the account list."""

    permission_classes = [IsAdminUser]

    @extend_schema(
        responses={200: AdminUserSummarySerializer},
        summary='Summarise user accounts',
        description='Admin only. Total accounts, banned accounts and staff accounts.',
    )
    def get(self, request):
        payload = {
            'total': User.objects.count(),
            'banned': User.objects.filter(is_banned=True).count(),
            'admins': User.objects.filter(is_staff=True).count(),
        }
        return Response(AdminUserSummarySerializer(payload).data)
