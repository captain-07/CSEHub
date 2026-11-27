from django.urls import path

from .views import (
    MeView,
    SessionEndView,
    SessionPingView,
    UserSessionListView,
    UserSessionSummaryView,
)

urlpatterns = [
    path('me/', MeView.as_view(), name='me'),

    # Login session tracking. The two write routes are called by the browser;
    # the two read routes are the admin login log.
    path('auth/session/', SessionPingView.as_view(), name='session-ping'),
    path('auth/session/logout/', SessionEndView.as_view(), name='session-logout'),
    path('auth/sessions/', UserSessionListView.as_view(), name='session-list'),
    path('auth/sessions/summary/', UserSessionSummaryView.as_view(), name='session-summary'),
]
