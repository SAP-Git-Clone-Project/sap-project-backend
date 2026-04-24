from rest_framework import serializers
from .models import AuditLogModel


# NOTE: Serializer for the AuditLogModel converts and validates the recieved and sent data from the API endpoints, ensuring the data is in correct format and validated before stored or sent to the client
class AuditLogSerializer(serializers.ModelSerializer):
    # NOTE: Readonly fields gets the related info from the user and doc models
    username = serializers.ReadOnlyField(source="user.username")
    first_name = serializers.ReadOnlyField(source="user.first_name")
    last_name = serializers.ReadOnlyField(source="user.last_name")
    email = serializers.ReadOnlyField(source="user.email")
    document_title = serializers.ReadOnlyField(source="document.title")

    created_by_avatar_url = serializers.SerializerMethodField()

    # NOTE: The class defines which fields are included in the serializer output
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

    # NOTE: Because of the foreign key the serializer can access the related user and doc info using obj.
    def get_created_by_avatar_url(self, obj):
        if obj.user:
            return obj.user.avatar
        return "https://res.cloudinary.com/dbgpxmjln/image/upload/v1766143170/deafult-avatar_tyvazc.png"
