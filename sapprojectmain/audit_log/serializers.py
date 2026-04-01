from rest_framework import serializers  # <--- Add this line!
from .models import AuditLogModel

class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.username")
    document_title = serializers.ReadOnlyField(source="document.title")
    created_by_avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = AuditLogModel
        fields = [
            'id', 'user', 'username', 'action_type', 'document', 
            'document_title', 'ip_address', 'timestamp', 
            'description', 'created_by_avatar_url'
        ]

    def get_created_by_avatar_url(self, obj):
        if obj.user:
            return obj.user.avatar
        return "https://res.cloudinary.com/dbgpxmjln/image/upload/v1766143170/deafult-avatar_tyvazc.png"