from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import DocumentPermissionModel

User = get_user_model()


# SERIALIZER FOR DOCUMENT ACCESS PERMISSIONS
class DocumentPermissionSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    document = serializers.PrimaryKeyRelatedField(
        queryset=DocumentPermissionModel._meta.get_field(
            "document"
        ).remote_field.model.objects.all()
    )
    username = serializers.ReadOnlyField(source="user.username")
    document_title = serializers.ReadOnlyField(source="document.title")

    class Meta:
        model = DocumentPermissionModel
        fields = [
            "id",
            "user",
            "username",
            "document",
            "document_title",
            "permission_type",
            "granted_at",
        ]
        read_only_fields = ["id", "granted_at"]
        # Disable the auto-generated unique_together validator so that
        # update_or_create in create() can handle upserts cleanly
        validators = []

    def create(self, validated_data):
        user = validated_data.pop("user")
        document = validated_data.pop("document")
        permission_type = validated_data.get("permission_type")

        instance, created = DocumentPermissionModel.objects.update_or_create(
            user=user, document=document, defaults={"permission_type": permission_type}
        )
        instance._was_created = created
        return instance
