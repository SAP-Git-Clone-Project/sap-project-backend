from rest_framework import viewsets, permissions
from .models import AuditLogModel
from .serializers import AuditLogSerializer

from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser

# VIEWSET FOR SYSTEM AUDIT RECORDS
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    # NOTE: ReadOnlyModelViewSet prevents POST, PUT, and DELETE methods by design
    # PERFORMANCE: select_related fetches linked objects in a single SQL JOIN to avoid N+1 issues
    queryset = AuditLogModel.objects.all().select_related("user", "document", "version")
    serializer_class = AuditLogSerializer
    
    # SECURITY: Access is strictly restricted to staff/admin users only
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]

    def get_queryset(self):
        queryset = super().get_queryset()

        # NOTE: Extraction of query parameters for targeted log analysis
        action = self.request.query_params.get("action")
        user_id = self.request.query_params.get("user_id")
        document_id = self.request.query_params.get("document_id")

        # IMP: Dynamic filtering logic to refine audit search results
        if action:
            queryset = queryset.filter(action_type=action)
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if document_id:
            queryset = queryset.filter(document_id=document_id)

        return queryset

# NOTE: Staff can now filter logs via ?action=LOGIN or ?user_id=<uuid>
# IMP: Ensure the frontend passes the correct UUID format for filtering