from rest_framework import viewsets, filters  # Added filters
from django.core.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from .models import AuditLogModel
from .serializers import AuditLogSerializer
from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser


class AuditLogPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 1000


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLogModel.objects.all().select_related("user", "document")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]
    pagination_class = AuditLogPagination

    # Enable Server-Side Search
    filter_backends = [filters.SearchFilter]
    # This allows searching across these specific fields in the DB
    search_fields = ["user__username", "action_type", "document__title", "description"]

    def get_queryset(self):
        queryset = self.queryset.all()

        # Specific field filters (e.g., from dropdowns)
        action = self.request.query_params.get("action")
        user_id = self.request.query_params.get("user_id")
        document_id = self.request.query_params.get("document_id")

        try:
            if action:
                queryset = queryset.filter(action_type=action)
            if user_id:
                queryset = queryset.filter(user_id=user_id)
            if document_id:
                queryset = queryset.filter(document_id=document_id)

            return queryset.order_by("-timestamp")

        except (ValidationError, ValueError, Exception) as e:
            print(f"Audit Log Filter Exception: {e}")
            return AuditLogModel.objects.none()
