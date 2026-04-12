from django.urls import path
from .views import (
    NotificationListView,
    MarkNotificationReadView,
    MarkAllReadView,
    NotificationDeleteView,
    HandleJoinRequestView,
    HandleDeletionRequestView,
)

urlpatterns = [
    # GET: Fetch paginated notifications (supports ?page=, ?status=, and ?q=)
    path("", NotificationListView.as_view(), name="notification-list"),
    # PATCH: Mark a specific notification as read
    path("<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="mark-read"),
    # DELETE: Purge a specific notification from the database
    path(
        "<uuid:pk>/delete/",
        NotificationDeleteView.as_view(),
        name="delete-notification",
    ),
    # POST: Bulk update to clear all unread alerts
    path("mark-all-read/", MarkAllReadView.as_view(), name="mark-all-read"),
    # POST: Endpoint for 'Accept'/'Reject' buttons on join requests
    path(
        "<uuid:pk>/handle-request/",
        HandleJoinRequestView.as_view(),
        name="handle-request",
    ),
    path("<uuid:pk>/handle-deletion/", HandleDeletionRequestView.as_view(), name="notification-handle-deletion"),
]
