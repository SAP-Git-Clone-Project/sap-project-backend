from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import DocumentPermissionModel
from versions.models import VersionsModel
from documents.models import DocumentModel

User = get_user_model()


# SERIALIZER FOR DOCUMENT ACCESS PERMISSIONS
class DocumentPermissionSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    document = serializers.PrimaryKeyRelatedField(
        # queryset=DocumentPermissionModel._meta.get_field(
        #    "document"
        # ).remote_field.model.objects.all()
        queryset=DocumentModel.objects.all(),
        required=False,
        allow_null=True
    )
    version = serializers.PrimaryKeyRelatedField(
        queryset=VersionsModel.objects.all(), 
        required=False, 
        allow_null=True
    )
    username = serializers.ReadOnlyField(source="user.username")
    document_title = serializers.ReadOnlyField(source="document.title")
    # user_avatar = serializers.ReadOnlyField(source="user.avatar")
    full_name = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()

    class Meta:
        model = DocumentPermissionModel
        fields = [
            "id",
            "user",
            "username",
            "document",
            "version",
            "document_title",
            "permission_type",
            "granted_at",
            "full_name",
            "user_avatar",
        ]
        read_only_fields = ["id", "granted_at"]
        # Disable the auto-generated unique_together validator so that
        # update_or_create in create() can handle upserts cleanly
        validators = []

    def create(self, validated_data):
        user = validated_data.pop("user")
        document = validated_data.pop("document")
        version = validated_data.pop("version", None)
        permission_type = validated_data.get("permission_type")

        instance, created = DocumentPermissionModel.objects.update_or_create(
            user=user, document=document, version=version, defaults={"permission_type": permission_type}
        )
        instance._was_created = created
        return instance
    
    def get_full_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
        return "Unknown User"

    def get_user_avatar(self, obj):
        if obj.user:
            return obj.user.avatar
        return ""
