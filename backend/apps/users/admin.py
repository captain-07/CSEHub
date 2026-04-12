from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

# Register your models here.

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'username', 'is_staff', 'supabase_uid']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Supabase', {'fields': ('supabase_uid', 'avatar_url', 'display_name')}),
    )