from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase

from .authentication import SupabaseJWTAuthentication
from .models import UserSession
