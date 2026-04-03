from rest_framework import serializers
from django.utils import timezone
from .models import ReviewModel, ReviewStatus
from versions.serializers import VersionSerializer
from versions.models import VersionStatus


class ReviewSerializer(serializers.ModelSerializer):
    # NOTE: Provides current and parent version data for frontend diffing
    # new_version = VersionSerializer(source="version", read_only=True)
    new_version = serializers.SerializerMethodField()
    old_version = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()

    # old_version = VersionSerializer(source="version.parent_version", read_only=True)

    # NOTE: Read-only field for reviewer identification in the UI
    # reviewer_name = serializers.ReadOnlyField(source="reviewer.username")

    class Meta:
        model = ReviewModel
        fields = [
            "id",
            "version",
            "reviewer",
            "reviewer_name",
            "review_status",
            "comments",
            "reviewed_at",
            "new_version",
            "old_version",
        ]
        # NOTE: System-managed fields excluded from direct user input
        read_only_fields = ["id", "reviewed_at", "reviewer", "version"]

    def get_new_version(self, obj):
        version = obj.version
        if version:
            try:
                return VersionSerializer(version).data
            except Exception:
                return None
        return None

    def get_old_version(self, obj):
        parent = obj.version.parent_version
        if parent:
            return VersionSerializer(parent).data
        return None

    def get_reviewer_name(self, obj):
        return obj.reviewer.username if obj.reviewer else None

    def validate(self, data):
        # NOTE: Ensures rejection includes a mandatory explanatory comment
        status = data.get("review_status")
        comments = data.get("comments")

        if status == ReviewStatus.REJECTED and not comments:
            raise serializers.ValidationError(
                {"comments": "Please provide a reason for rejecting this version"}
            )
        return data

    def update(self, instance, validated_data):
        # NOTE: Syncs review decisions with document version states
        request = self.context.get("request")
        new_status = validated_data.get("review_status", instance.review_status)

        # SECURITY: Automatically captures the current reviewer and timestamp
        instance.reviewer = request.user
        instance.reviewed_at = timezone.now()

        # NOTE: Version status synchronization logic
        version = instance.version

        if new_status == ReviewStatus.APPROVED:
            # IMP: Approval activates the version and deactivates old ones via model logic
            version.status = VersionStatus.APPROVED
            version.is_active = True
        elif new_status == ReviewStatus.REJECTED:
            # NOTE: Rejection marks the version as rejected and inactive
            version.status = VersionStatus.REJECTED
            version.is_active = False

        # NOTE: Persists version changes before updating the review record
        version.save()

        # NOTE: Finalizes the review update using standard serializer logic
        return super().update(instance, validated_data)
