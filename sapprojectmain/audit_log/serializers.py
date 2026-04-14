from rest_framework import serializers  # <--- Add this line!
from .models import AuditLogModel


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.username")
    first_name = serializers.ReadOnlyField(source="user.first_name")
    last_name = serializers.ReadOnlyField(source="user.last_name")
    email = serializers.ReadOnlyField(source="user.email")
    document_title = serializers.ReadOnlyField(source="document.title")
    created_by_avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = AuditLogModel
        fields = [
            "id",
            "user",
            "email",
            "username",
            "action_type",
            "document",
            "first_name",
            "last_name",
            "document_title",
            "ip_address",
            "timestamp",
            "description",
            "created_by_avatar_url",
        ]

    def get_created_by_avatar_url(self, obj):
        if obj.user:
            return obj.user.avatar
        return "https://res.cloudinary.com/dbgpxmjln/image/upload/v1766143170/deafult-avatar_tyvazc.png"
