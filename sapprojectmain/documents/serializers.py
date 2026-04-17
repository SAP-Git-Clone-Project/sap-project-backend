from rest_framework import serializers
from .models import DocumentModel
from versions.serializers import VersionSummarySerializer
from core.rbac import get_document_permissions, get_document_role


class DocumentSerializer(serializers.ModelSerializer):
    created_by_username = serializers.ReadOnlyField(source="created_by.username")
    created_by_avatar_url = serializers.ReadOnlyField(source="created_by.avatar")
    active_version = serializers.SerializerMethodField()
    current_user_document_role = serializers.SerializerMethodField()
    current_user_effective_permissions = serializers.SerializerMethodField()
    
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
            "current_user_document_role",
            "current_user_effective_permissions",
            "is_deleted",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def _get_prefetched_permission_types(self, obj):
        """
        PERF: Views may attach the current user's permission rows via
        `prefetched_current_user_permissions` to avoid N+1 queries.
        """
        perms = getattr(obj, "prefetched_current_user_permissions", None)
        if perms is None:
            return None
        return {p.permission_type for p in perms}

    def get_active_version(self, obj):
        # Stats endpoints still need accurate status counts:
        # use active version when present, otherwise latest version.
        if self.context.get("stats_mode") is True:
            active_versions = getattr(obj, "prefetched_active_versions", None)
            if active_versions:
                return VersionSummarySerializer(
                    active_versions[0], context=self.context
                ).data
            latest_v = getattr(obj, "_latest_version", None)
            if latest_v is None:
                latest_v = (
                    obj.versions.select_related(
                        "created_by", "parent_version", "document"
                    )
                    .order_by("-version_number")
                    .first()
                )
            return (
                VersionSummarySerializer(latest_v, context=self.context).data
                if latest_v
                else None
            )

        # First, try the prefetched active version (fast path for list views)
        active_versions = getattr(obj, "prefetched_active_versions", None)
        if active_versions:
            # there should be max 1 active version per document
            return VersionSummarySerializer(
                active_versions[0], context=self.context
            ).data

        # Fallback: instance/detail views may not prefetch
        active_v = obj.versions.filter(is_active=True).select_related(
            "created_by", "parent_version", "document"
        ).first()
        if active_v:
            return VersionSummarySerializer(active_v, context=self.context).data
        
        request = self.context.get("request", None)
        user = getattr(request, "user", None)

        # If no active version, check for permissions
        if user:
            is_owner = obj.created_by_id == user.id
            is_superuser = user.is_superuser
            prefetched_perm_types = self._get_prefetched_permission_types(obj)
            has_perm = (
                bool(prefetched_perm_types)
                if prefetched_perm_types is not None
                else getattr(obj, "user_has_permission_annotated", False)
            )

            if is_owner or is_superuser or has_perm:
                latest_v = getattr(obj, "_latest_version", None)
                if latest_v is None:
                    latest_v = (
                        obj.versions.select_related(
                            "created_by", "parent_version", "document"
                        )
                        .order_by("-version_number")
                        .first()
                    )
                if latest_v:
                    return VersionSummarySerializer(latest_v, context=self.context).data
                
        return None

    def get_current_user_document_role(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        prefetched_perm_types = self._get_prefetched_permission_types(obj)
        if prefetched_perm_types is None:
            return get_document_role(user, obj)

        # Mirror priority logic in core.rbac.get_document_role without hitting DB
        priority = ["DELETE", "WRITE", "APPROVE", "READ"]
        from core.rbac import PERMISSION_TO_ROLE

        for permission in priority:
            if permission in prefetched_perm_types:
                return PERMISSION_TO_ROLE.get(permission)
        return None

    def get_current_user_effective_permissions(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return []
        prefetched_perm_types = self._get_prefetched_permission_types(obj)
        if prefetched_perm_types is not None:
            return sorted(prefetched_perm_types)
        return sorted(get_document_permissions(user, obj))

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