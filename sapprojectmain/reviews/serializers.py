from rest_framework import serializers
from .models import Reviews
from versions.serializers import VersionSerializer

class ReviewSerializer(serializers.ModelSerializer):
    # 'new_version' is the draft; 'old_version' is the current active file for diffing
    new_version = VersionSerializer(source='version', read_only=True)
    old_version = VersionSerializer(source='version.parent_version', read_only=True)

    class Meta:
        model = Reviews
        fields = [
            'id', 'version', 'reviewer', 'review_status', 
            'comments', 'reviewed_at', 'new_version', 'old_version'
        ]
        read_only_fields = ['id', 'reviewed_at', 'reviewer']