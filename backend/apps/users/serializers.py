from rest_framework import serializers
from .models import User


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'display_name', 'avatar_url', 'is_staff']
        read_only_fields = ['email', 'is_staff']