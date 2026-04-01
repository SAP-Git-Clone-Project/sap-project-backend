from rest_framework import serializers
from .models import DocumentModel
from versions.serializers import VersionSerializer


class DocumentSerializer(serializers.ModelSerializer):
    created_by_username = serializers.ReadOnlyField(source="created_by.username")
    active_version = serializers.SerializerMethodField()
    versions = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentModel
        fields = [
            "id",
            "title",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "active_version",
            "versions",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_active_version(self, obj):
        version = obj.versions.filter(is_active=True).first()
        if version:
            return VersionSerializer(version).data
        return None

    def get_versions(self, obj):
        """
        Return all versions if the request user is the creator,
        otherwise return only the active version.
        """
        request = self.context.get("request", None)
        if request and request.user == obj.created_by:
            return VersionSerializer(obj.versions.all(), many=True).data
        else:
            active_version = obj.versions.filter(is_active=True).first()
            if active_version:
                return [VersionSerializer(active_version).data]
            return []

    # Optional: title validation and creation/update logic
    def validate_title(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Title cannot be empty")
        return value

    def validate(self, data):
        request = self.context.get("request")
        if not request or not request.user:
            return data

        user = request.user
        title = data.get("title")
        queryset = DocumentModel.objects.filter(created_by=user, title=title, is_deleted=False)
        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError(
                {"title": "You already have an active document with this title"}
            )
        return data

    def create(self, validated_data):
        request = self.context.get("request")
        return DocumentModel.objects.create_document(created_by=request.user, **validated_data)

    def update(self, instance, validated_data):
        instance.title = validated_data.get("title", instance.title)
        instance.save()
        return instance