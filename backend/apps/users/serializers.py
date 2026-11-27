from rest_framework import serializers

from django.utils import timezone

from .models import User, UserSession


class UserProfileSerializer(serializers.ModelSerializer):
    # This intentionally mirrors Django's server-controlled staff flag.  It is
    # read-only, so clients cannot grant themselves article-management access.
    is_admin = serializers.BooleanField(source='is_staff', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'display_name', 'avatar_url', 'is_admin']
        read_only_fields = ['email', 'is_admin']


class SessionKeySerializer(serializers.Serializer):
    """The fallback identifier for clients whose token carries no `session_id`.

    Normally the server reads the claim from the verified JWT and ignores this
    field entirely. It exists so a client (and the tests) can still identify a
    session when the provider omits the claim.
    """

    session_key = serializers.CharField(max_length=64, required=False, allow_blank=True)


class SessionPingResultSerializer(serializers.Serializer):
    session_key = serializers.CharField()
    created = serializers.BooleanField()
    logged_in_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    logged_out_at = serializers.DateTimeField(allow_null=True)


class SessionEndResultSerializer(serializers.Serializer):
    session_key = serializers.CharField()
    ended = serializers.BooleanField()
    logged_out_at = serializers.DateTimeField(allow_null=True)


class UserSessionSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    display_name = serializers.CharField(source='user.display_name', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            'id', 'user_id', 'email', 'username', 'display_name',
            'ip_address', 'user_agent',
            'logged_in_at', 'last_seen_at', 'logged_out_at',
            'is_active', 'duration_seconds',
        ]

    def get_duration_seconds(self, obj):
        if obj.logged_out_at is not None:
            end = obj.logged_out_at
        elif obj.is_active:
            end = timezone.now()
        else:
            # A tab that closed without signing out stops at its last heartbeat;
            # otherwise the row would keep claiming a longer visit every time the
            # admin refreshed the page.
            end = obj.last_seen_at
        return max(0, int((end - obj.logged_in_at).total_seconds()))


class UserSessionSummarySerializer(serializers.Serializer):
    active = serializers.IntegerField()
    logins_today = serializers.IntegerField()
    total = serializers.IntegerField()
    active_window_minutes = serializers.IntegerField()
