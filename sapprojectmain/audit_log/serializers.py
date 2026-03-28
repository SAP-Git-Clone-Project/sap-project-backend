from rest_framework import serializers
from .models import AuditLogModel

# SERIALIZER FOR SYSTEM AUDIT RECORDS
class AuditLogSerializer(serializers.ModelSerializer):
    # NOTE: Mapping the username string for frontend display clarity
    username = serializers.ReadOnlyField(source="user.username")
    # NOTE: Fetching the related document title for easier log identification
    document_title = serializers.ReadOnlyField(source="document.title")

    class Meta:
        model = AuditLogModel
        # IMP: Exporting all fields to provide a full audit trail via the API
        fields = '__all__'
        
# SECURITY: Ensure the viewset using this serializer enforces strict read-only access
# NOTE: Consider prefetching 'user' and 'document' to optimize performance