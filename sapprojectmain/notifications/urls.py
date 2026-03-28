from django.urls import path
from .views import NotificationListView, MarkNotificationReadView, MarkAllReadView

urlpatterns = [
    # NOTE: GET to list notifications and retrieve unread count
    path("", NotificationListView.as_view(), name="notification-list"),
    # NOTE: POST to perform bulk update of all notifications to read status
    path("mark-all-read/", MarkAllReadView.as_view(), name="mark-all-read"),
    # NOTE: PATCH to update a specific notification as read by ID
    path(
        "<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="notification-read"
    ),
]
