from rest_framework import serializers
from django.utils.timesince import timesince
from .models import NotificationModel


class NotificationSerializer(serializers.ModelSerializer):
    # NOTE: Pulls the username from the related UserModel (formerly 'actor')
    user_username = serializers.ReadOnlyField(source="user.username")

    # NOTE: Pulls the avatar URL directly from the related UserModel
    user_avatar = serializers.ReadOnlyField(source="user.avatar")

    # NOTE: Pulls the title from the related DocumentModel
    target_document_title = serializers.ReadOnlyField(source="target_document.title")

    # NOTE: Calculated field for relative time display like "2 mins ago"
    created_since = serializers.SerializerMethodField()

    class Meta:
        model = NotificationModel
        fields = [
            "id",
            "user_username",
            "user_avatar",
            "verb",
            "target_document_title",
            "target_document",
            "is_read",
            "created_at",
            "created_since",
        ]
        # NOTE: System-managed fields excluded from user input
        read_only_fields = ["id", "created_at", "created_since"]

    def get_created_since(self, obj):
        """
        Formats the creation timestamp into a simple relative string.
        Takes the first part of timesince (e.g., '1 minute' from '1 minute, 2 seconds')
        """
        if not obj.created_at:
            return "Just now"

        try:
            # Get the first component of the time difference (e.g., "2 minutes")
            time_str = timesince(obj.created_at).split(",")[0]
            # Replace non-breaking spaces if they appear to keep the string clean
            time_str = time_str.replace("\xa0", " ")
            return f"{time_str} ago"
        except Exception:
            return "Recently"
