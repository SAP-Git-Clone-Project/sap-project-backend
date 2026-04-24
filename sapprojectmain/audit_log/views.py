from rest_framework import viewsets, filters
from django.db.models import Q
from rest_framework.pagination import PageNumberPagination
from .models import AuditLogModel
from .serializers import AuditLogSerializer
from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser

# NOTE: Configures pagination for the audit log list endpoint
class AuditLogPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 1000

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLogModel.objects.all().select_related("user", "document")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]
    pagination_class = AuditLogPagination

    # Enable Server-Side Search (Standard DRF Search)
    filter_backends = [filters.SearchFilter]
    search_fields = ["user__username", "user__email", "action_type", "document__title", "description"]

    def get_queryset(self):
        queryset = self.queryset.all()

        actions = self.request.query_params.getlist("action")
        if actions:
            queryset = queryset.filter(action_type__in=actions)

        user_id = self.request.query_params.get("user_id")
        if user_id:
            try:
                import uuid
                uuid.UUID(user_id)  # validate format
                queryset = queryset.filter(user_id=user_id)
            except (ValueError, TypeError):
                return queryset.none()

        document_id = self.request.query_params.get("document_id")
        if document_id:
            queryset = queryset.filter(document_id=document_id)

        start_date = self.request.query_params.get("start_date")
        if start_date:
            queryset = queryset.filter(timestamp__gte=f"{start_date} 00:00:00")

        end_date = self.request.query_params.get("end_date")
        if end_date:
            queryset = queryset.filter(timestamp__lte=f"{end_date} 23:59:59")

        return queryset.order_by("-timestamp")