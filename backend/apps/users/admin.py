from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserSession


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'username', 'is_staff', 'supabase_uid']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Supabase', {'fields': ('supabase_uid', 'avatar_url', 'display_name')}),
    )


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    """Fallback view of the login log.

    The admin panel's "Login log" page is the supported path for editors who
    have no Django admin password; this registration is the repair hatch for a
    session whose logout never arrived.
    """

    list_display = [
        'user', 'logged_in_at', 'last_seen_at', 'logged_out_at', 'ip_address',
    ]
    list_select_related = ['user']
    list_filter = ['logged_out_at']
    search_fields = ['user__email', 'user__username', 'ip_address']
    readonly_fields = [
        'user', 'session_key', 'ip_address', 'user_agent',
        'logged_in_at', 'last_seen_at',
    ]
    date_hierarchy = 'logged_in_at'
