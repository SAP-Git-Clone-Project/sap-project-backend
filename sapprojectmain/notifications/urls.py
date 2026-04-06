from django.urls import path
from .views import (
    NotificationListView,
    MarkNotificationReadView,
    MarkAllReadView,
    HandleJoinRequestView,
)

urlpatterns = [
    # NOTE: Fetch all notifications and unread count
    path("", NotificationListView.as_view(), name="notification-list"),
    # NOTE: Mark a specific notification as read (manual or on click)
    path("<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="mark-read"),
    # NOTE: Bulk update to clear all unread alerts
    path("mark-all-read/", MarkAllReadView.as_view(), name="mark-all-read"),
    # NOTE: Endpoint for 'Accept'/'Reject' buttons on join requests
    path(
        "<uuid:pk>/handle-request/",
        HandleJoinRequestView.as_view(),
        name="handle-request",
    ),
]
