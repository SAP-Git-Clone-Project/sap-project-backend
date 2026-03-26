from rest_framework import serializers

from .models import DocumentModel

def validate_title(self, value):
    if not value.strip():
        raise serializers.ValidationError("Title cannot be empty")
    return value

# DOCUMENT SERIALIEZR
class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentModel
        fields = [
            "id",
            "title",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate(self, data):
        request = self.context["request"]
        user = request.user
        title = data.get("title")

        if not title:
            raise serializers.ValidationError({"title": "Title cannot be empty"})

        queryset = DocumentModel.objects.filter(
            created_by=user,
            title=title,
            is_deleted=False
        )
        
        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)
            
        if queryset.exists():
            raise serializers.ValidationError(
                {"title": "You already have a document with this title"}
            )

        return data

    def create(self, validated_data):
        request = self.context["request"]
        
        return DocumentModel.objects.create_document(
            created_by=request.user,
            **validated_data)

    def update(self, instance, validated_data):
        instance.title = validated_data.get("title", instance.title)
        instance.save(update_fields=["title", "updated_at"])
        return instance
