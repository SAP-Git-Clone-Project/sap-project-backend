from rest_framework import serializers

from .models import DocumentPermissionModel
from users.models import UserModel
from documents.models import DocumentModel

# GET DOCUMENT PERMISSION
class GetDocumentPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentPermissionModel
        fields = [
            "id",
            "user_id",
            "document_id",
            "permission_type",
            "granted_at",
        ]

# CREATE DOCUMENT PERMISSION
class CreateDocumentPermissionSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=UserModel.objects.all()
    )
    document_id = serializers.PrimaryKeyRelatedField(
        queryset=DocumentModel.objects.all()
    )
    
    class Meta:
        model = DocumentPermissionModel
        fields = ["user_id", "document_id", "permission_type"]

    def validate(self, data):
        request         = self.context["request"]
        user_id         = data.get("user_id")
        document_id     = data.get("document_id")
        permission_type = data.get("permission_type")

        queryset = DocumentPermissionModel.objects.filter(
            user_id=user_id,
            document_id=document_id,
            permission_type=permission_type
        )

        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)

            if queryset.exists():
                raise serializers.ValidationError(
                    {"title": "This user already has the permission for the document"}
                )

        return data

    def create(self, validated_data):
        request = self.context["request"]
        
        return DocumentPermissionModel.objects.create_document_permission(**validated_data)
