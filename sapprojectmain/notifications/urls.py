from django.urls import path
from .views import NotificationListView, MarkNotificationReadView, MarkAllReadView

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="mark-read"),
    path("mark-all-read/", MarkAllReadView.as_view(), name="mark-all-read"),
]
