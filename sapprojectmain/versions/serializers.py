from rest_framework import serializers
from .models import Versions


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Versions
        fields = "__all__"
        read_only_fields = [
            "id",
            "version_number",
            "file_path",
            "file_size",
            "checksum",
            "is_active",
        ]

    def create(self, validated_data):
        doc = validated_data["document"]
        last_v = (
            Versions.objects.filter(document=doc).order_by("-version_number").first()
        )
        validated_data["version_number"] = (last_v.version_number + 1) if last_v else 1
        return super().create(validated_data)
