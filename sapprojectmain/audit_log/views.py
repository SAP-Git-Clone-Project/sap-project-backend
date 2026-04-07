from rest_framework import viewsets, filters
from django.db.models import Q
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

    # Enable Server-Side Search (Standard DRF Search)
    filter_backends = [filters.SearchFilter]
    search_fields = ["user__username", "action_type", "document__title", "description"]

    def get_queryset(self):
        # Start with the base queryset
        queryset = self.queryset.all()

        # 1. Multiple Action Filter (Handled as a list)
        # Frontend will send: ?action=CREATE&action=DELETE
        actions = self.request.query_params.getlist("action")
        if actions:
            queryset = queryset.filter(action_type__in=actions)

        # 2. Specific User Filter
        user_id = self.request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # 3. Smart Date Range Filtering
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            # Filters from 00:00:00 of the chosen day
            queryset = queryset.filter(timestamp__gte=f"{start_date} 00:00:00")
        
        if end_date:
            # Filters until 23:59:59 of the chosen day
            queryset = queryset.filter(timestamp__lte=f"{end_date} 23:59:59")

        # Return ordered by newest first
        return queryset.order_by("-timestamp")