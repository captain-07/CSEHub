from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.

class User(AbstractUser):
    email = models.EmailField(unique=True, blank=True)
    supabase_uid = models.UUIDField(unique=True, null=True, blank=True)
    avatar_url = models.URLField(blank=True)
    display_name = models.CharField(max_length=100, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email
    