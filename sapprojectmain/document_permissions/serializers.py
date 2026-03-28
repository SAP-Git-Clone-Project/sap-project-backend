from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import DocumentPermissionModel

User = get_user_model()


# SERIALIZER FOR DOCUMENT ACCESS PERMISSIONS
class DocumentPermissionSerializer(serializers.ModelSerializer):
    # NOTE: Using explicit querysets for robust relation handling
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    # IMP: Dynamic model retrieval to prevent circular import issues with the Document app
    document = serializers.PrimaryKeyRelatedField(
        queryset=DocumentPermissionModel._meta.get_field(
            "document"
        ).remote_field.model.objects.all()
    )

    # NOTE: Read-only fields to provide context in the API response
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
        # SECURITY: System-generated fields are locked from external modification
        read_only_fields = ["id", "granted_at"]

    def create(self, validated_data):
        # NOTE: Extraction of core relation data from the validated payload
        user = validated_data.pop("user")
        document = validated_data.pop("document")
        permission_type = validated_data.get("permission_type")

        # IMP: Logic performs an upsert to prevent duplicates and allow role upgrades
        instance, created = DocumentPermissionModel.objects.update_or_create(
            user=user, document=document, defaults={"permission_type": permission_type}
        )

        return instance


# NOTE: Ensure the unique constraint in Meta matches this update_or_create logic
