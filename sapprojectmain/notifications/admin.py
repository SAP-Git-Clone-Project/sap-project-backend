from django.contrib import admin
from .models import NotificationModel


@admin.register(NotificationModel)
class NotificationAdmin(admin.ModelAdmin):
    # NOTE: Columns shown in the admin list overview
    list_display = (
        "recipient",
        "user",  # Tracks the user who triggered the event
        "verb",
        "target_document",
        "is_read",
        "created_at",
    )

    # NOTE: Sidebar filters for status, date, and action type
    list_filter = ("is_read", "created_at", "verb")

    # NOTE: Search bar targets specific user and action details
    search_fields = (
        "recipient__username", 
        "user__username", 
        "verb", 
        "target_document__title"
    )

    # SECURITY: Locked fields to prevent manual tampering with audit data
    readonly_fields = ("id", "created_at")

    # NOTE: Default ordering to match model behavior (Newest first)
    ordering = ("-created_at",)