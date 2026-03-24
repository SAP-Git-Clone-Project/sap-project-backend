from rest_framework import serializers

from .models import DocumentModel

def validate_title(self, value):
    if not value.strip():
        raise serializers.ValidationError("Title cannot be empty")
    return value

# GET DOCUMENT
class GetDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentModel
        fields = [
            "id",
            "title",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

# CREATE DOCUMENT
class CreateDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentModel
        fields = ["title"]

    def validate(self, data):
        request = self.context["request"]
        user = request.user
        title = data.get("title")

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

# UPDATE DOCUMENT
class UpdateDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentModel
        fields = ["title"]

    def update(self, instance, validated_data):
        instance.title = validated_data.get("title", instance.title)
        instance.save(updated_fields=["title", "updated_at"])
        return instance
        
