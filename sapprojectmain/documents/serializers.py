from rest_framework import serializers
from .models import DocumentModel
from versions.serializers import VersionSerializer


class DocumentSerializer(serializers.ModelSerializer):
    created_by_username = serializers.ReadOnlyField(source="created_by.username")
    created_by_avatar_url = serializers.ReadOnlyField(source="created_by.avatar")
    active_version = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentModel
        fields = [
            "id",
            "title",
            "created_by",
            "created_by_username",
            "created_by_avatar_url",
            "created_at",
            "updated_at",
            "active_version",
            "is_deleted",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_active_version(self, obj):
        # First, try to get the active version
        versions_list = getattr(obj, 'prefetched_versions', list(obj.versions.all()))
        active_v = next((v for v in versions_list if v.is_active), None)
        if active_v:
            return VersionSerializer(active_v).data
        
        request = self.context.get("request", None)
        user = getattr(request, "user", None)

        # If no active version, check for permissions
        if user:
            is_owner = obj.created_by_id == user.id
            is_superuser = user.is_superuser
            has_perm = getattr(obj, 'user_has_permission_annotated', False)

            if is_owner or is_superuser or has_perm:
                if versions_list:
                    latest_v = sorted(versions_list, key=lambda v: v.version_number, reverse=True)[0]
                    return VersionSerializer(latest_v).data
                
        return None

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