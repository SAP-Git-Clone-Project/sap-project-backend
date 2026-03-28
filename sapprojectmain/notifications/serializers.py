from rest_framework import serializers
from django.utils.timesince import timesince
from .models import NotificationModel


class NotificationSerializer(serializers.ModelSerializer):
    # NOTE: Read-only fields to provide human-readable actor and document names
    actor_username = serializers.ReadOnlyField(source="actor.username")
    target_document_title = serializers.ReadOnlyField(source="target_document.title")

    # NOTE: Calculated field for relative time display like 2 mins ago
    created_since = serializers.SerializerMethodField()

    class Meta:
        model = NotificationModel
        fields = [
            "id",
            "actor_username",
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
        # NOTE: Formats the creation timestamp into a simple relative string
        return f"{timesince(obj.created_at).split(',')[0]} ago"
