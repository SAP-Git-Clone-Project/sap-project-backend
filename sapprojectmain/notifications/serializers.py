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
    permission = serializers.SerializerMethodField()
    deletion = serializers.SerializerMethodField()

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
            "permission",
            "deletion",
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
        
    def get_permission(self, obj):
        if not obj.permission_request:
            return None

        return {
            "id": obj.permission_request.id,
            "status": obj.permission_request.status,
        }

    def get_deletion(self, obj):
        if not obj.deletion_request:
            return None

        return {
            "id": obj.deletion_request.id,
            "status": obj.deletion_request.status,
            "document_title": obj.deletion_request.document.title if obj.deletion_request.document else None,
            "requested_by": obj.deletion_request.requested_by.username if obj.deletion_request.requested_by else None,
        }