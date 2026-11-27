from django.urls import path

from .views import (
    AdminUserListView,
    AdminUserSummaryView,
    MeView,
    SessionEndView,
    SessionPingView,
    UserBanView,
    UserSessionListView,
    UserSessionSummaryView,
    UserUnbanView,
)

urlpatterns = [
    path('me/', MeView.as_view(), name='me'),

    # Login session tracking. The two write routes are called by the browser;
    # the two read routes are the admin login log.
    path('auth/session/', SessionPingView.as_view(), name='session-ping'),
    path('auth/session/logout/', SessionEndView.as_view(), name='session-logout'),
    path('auth/sessions/', UserSessionListView.as_view(), name='session-list'),
    path('auth/sessions/summary/', UserSessionSummaryView.as_view(), name='session-summary'),

    # Account administration (admin only).
    path('auth/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('auth/users/summary/', AdminUserSummaryView.as_view(), name='admin-user-summary'),
    path('auth/users/<int:pk>/ban/', UserBanView.as_view(), name='admin-user-ban'),
    path('auth/users/<int:pk>/unban/', UserUnbanView.as_view(), name='admin-user-unban'),
]
