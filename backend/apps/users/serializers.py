from rest_framework import serializers
from .models import User


class UserProfileSerializer(serializers.ModelSerializer):
    # This intentionally mirrors Django's server-controlled staff flag.  It is
    # read-only, so clients cannot grant themselves article-management access.
    is_admin = serializers.BooleanField(source='is_staff', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'display_name', 'avatar_url', 'is_admin']
        read_only_fields = ['email', 'is_admin']
