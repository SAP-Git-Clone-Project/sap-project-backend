from rest_framework import serializers
from .models import VersionsModel, VersionStatus
from core.rbac import get_document_permissions, get_document_role

class VersionSerializer(serializers.ModelSerializer):
    # NOTE: UI helpers to display human-readable names and version relationships
    creator_name = serializers.ReadOnlyField(source="created_by.username")
    parent_version_number = serializers.ReadOnlyField(
        source="parent_version.version_number"
    )

    # NOTE: Provides owner ID to allow frontend to construct storage URLs
    document_owner_id = serializers.ReadOnlyField(source="document.created_by.id")
    document_title = serializers.ReadOnlyField(source="document.title")
    avatar_url = serializers.ReadOnlyField(source="created_by.avatar")
    
    # Method fields for dynamic data
    signed_file_path = serializers.SerializerMethodField()
    current_user_document_role = serializers.SerializerMethodField()
    current_user_effective_permissions = serializers.SerializerMethodField()

    class Meta:
        model = VersionsModel
        fields = [
            "id",
            "document",
            "created_by",
            "creator_name",
            "version_number",
            "content",
            "status",
            "parent_version",
            "parent_version_number",
            "created_at",
            "is_active",
            "signed_file_path",
            "file_path",
            "file_size",
            "checksum",
            "document_owner_id",
            "document_title",
            "avatar_url",
            "current_user_document_role",
            "current_user_effective_permissions",
        ]
        # SECURITY: System-critical fields are protected from direct user modification
        read_only_fields = [
            "id",
            "version_number",
            "created_by",
            "created_at",
            "file_path",
            "file_size",
            "checksum",
            "is_active",
        ]

    def validate(self, data):
        # NOTE: Validates that only approved content can be set as the active version
        status = data.get("status")
        # NOTE: Handles cases where is_active is checked during partial updates
        is_active = data.get("is_active", getattr(self.instance, "is_active", False))

        if is_active and status != VersionStatus.APPROVED:
            raise serializers.ValidationError(
                {"is_active": "Only approved versions can be set as active"}
            )

        return data

    def create(self, validated_data):
        # NOTE: Automatically branches from the current active version if no parent is specified
        request = self.context.get("request")
        document = validated_data.get("document")

        # NOTE: Automatically assigns the logged-in user as the version creator
        validated_data["created_by"] = request.user

        # NOTE: Logic to identify the most relevant parent version for the new branch
        if not validated_data.get("parent_version"):
            # NOTE: Prefers branching from the active version or defaults to latest
            parent = (
                VersionsModel.objects.filter(document=document, is_active=True).first()
                or VersionsModel.objects.filter(document=document)
                .order_by("-version_number")
                .first()
            )
            validated_data["parent_version"] = parent

        return super().create(validated_data)

    def update(self, instance, validated_data):
        # NOTE: Automatically activates a version when its status changes to approved
        new_status = validated_data.get("status", instance.status)

        if new_status == VersionStatus.APPROVED:
            validated_data["is_active"] = True

        return super().update(instance, validated_data)

    def get_signed_file_path(self, obj):
        """
        Uses the shared utility to get a Cloudinary signed URL.
        Imported inside to prevent circular import issues.
        """
        if not obj.file_path:
            return None
        try:
            from versions.views import get_signed_url
            return get_signed_url(obj.file_path)
        except Exception:
            return obj.file_path

    def get_current_user_document_role(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        return get_document_role(user, obj.document, version=obj)

    def get_current_user_effective_permissions(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return []
        return sorted(get_document_permissions(user, obj.document, version=obj))