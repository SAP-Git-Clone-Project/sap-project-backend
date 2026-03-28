from rest_framework import serializers
from .models import DocumentModel

# NOTE: Dynamic approach used for related models to avoid circular imports


class DocumentSerializer(serializers.ModelSerializer):
    # NOTE: Read-only field to provide owner context to the frontend
    created_by_username = serializers.ReadOnlyField(source="created_by.username")

    class Meta:
        model = DocumentModel
        fields = [
            "id",
            "title",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        # NOTE: System-managed fields restricted from user input
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_title(self, value):
        # NOTE: Basic check to ensure title contains actual text
        if not value or not value.strip():
            raise serializers.ValidationError("Title cannot be empty")
        return value

    def validate(self, data):
        # NOTE: Validates title uniqueness for active documents only
        request = self.context.get("request")
        if not request or not request.user:
            return data

        user = request.user
        title = data.get("title")

        # SECURITY: Prevents name collisions while allowing reuse of deleted titles
        queryset = DocumentModel.objects.filter(
            created_by=user, title=title, is_deleted=False
        )

        # NOTE: Exclude current instance during updates to avoid self-collision
        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)

        if queryset.exists():
            raise serializers.ValidationError(
                {"title": "You already have an active document with this title"}
            )

        return data

    def create(self, validated_data):
        # IMP: Uses manager method to handle atomic doc creation and permission setup
        request = self.context.get("request")

        # NOTE: Passes authenticated user as the permanent owner
        return DocumentModel.objects.create_document(
            created_by=request.user, **validated_data
        )

    def update(self, instance, validated_data):
        # NOTE: Standard update logic for modifying document title
        instance.title = validated_data.get("title", instance.title)
        instance.save()
        return instance
