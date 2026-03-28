from django.core.exceptions import ValidationError
from rest_framework import viewsets
from .models import AuditLogModel
from .serializers import AuditLogSerializer
from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLogModel.objects.all().select_related("user", "document", "version")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]

    def get_queryset(self):
        # Start with the optimized queryset
        queryset = self.queryset

        action = self.request.query_params.get("action")
        user_id = self.request.query_params.get("user_id")
        document_id = self.request.query_params.get("document_id")

        try:
            if action:
                queryset = queryset.filter(action_type=action)
            if user_id:
                # Use the field name 'user', Django handles the UUID lookup
                queryset = queryset.filter(user=user_id)
            if document_id:
                # Use the field name 'document'
                queryset = queryset.filter(document=document_id)
        except (ValidationError, ValueError):
            # If a hacker sends a fake UUID, return nothing instead of crashing
            return queryset.none()

        return queryset
