from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import NotificationModel
from .serializers import NotificationSerializer
from document_permissions.models import DocumentPermissionModel

# 1. Custom Pagination with unread counts
class NotificationPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            "unread_count": NotificationModel.objects.filter(
                recipient=self.request.user, 
                is_read=False
            ).count(),
            "notifications": data,
            "pagination": {
                "count": self.page.paginator.count,
                "totalPages": self.page.paginator.num_pages,
                "hasNext": self.get_next_link() is not None,
                "hasPrev": self.get_previous_link() is not None,
            },
        })

# 2. Optimized List View
class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        user = self.request.user
            
        # FIXED: Changed 'order_at' to 'order_by'
        # ADDED: 'select_related' to fetch document and user data in ONE query
        queryset = NotificationModel.objects.filter(recipient=user).select_related(
            'user', 'target_document'
        ).order_by("-created_at")

        # Handle Status Filtering
        status_filter = self.request.query_params.get("status")
        if status_filter == "unread":
            queryset = queryset.filter(is_read=False)
        elif status_filter == "read":
            queryset = queryset.filter(is_read=True)

            # Handle Search
        search_query = self.request.query_params.get("q")
        if search_query:
            # FIXED: Changed 'target_document_title' to 'target_document__title'
            # This follows the relationship to the actual Document model
            queryset = queryset.filter(
                Q(verb__icontains=search_query) |
                Q(target_document__title__icontains=search_query) |
                Q(user__username__icontains=search_query)
            )

        return queryset
        
# 3. Mark specific notification as read
class MarkNotificationReadView(generics.UpdateAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        return NotificationModel.objects.filter(recipient=self.request.user)

    def patch(self, request, *args, **kwargs):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({"status": "read"}, status=status.HTTP_200_OK)

# 4. Mark all as read
class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        NotificationModel.objects.filter(
            recipient=request.user, 
            is_read=False
        ).update(is_read=True)
        return Response({"status": "all marked as read"}, status=status.HTTP_200_OK)

# 5. Delete notification
class NotificationDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        return NotificationModel.objects.filter(recipient=self.request.user)

# 6. Handle Invitations
class HandleJoinRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(
            NotificationModel, pk=pk, recipient=request.user
        )

        action = request.data.get("action")
        req = notification.permission_request

        if not req:
            return Response({"error": "No request found"}, status=400)

        if req.user != request.user:
            raise PermissionDenied("Not your request")

        if req.status != "PENDING":
            return Response({"detail": "Already handled"}, status=400)

        if action == "accept":
            DocumentPermissionModel.objects.update_or_create(
                user=req.user,
                document=req.document,
                version=req.version,
                defaults={"permission_type": req.permission_type},
            )
            req.status = "ACCEPTED"
            notification.verb = "You accepted the invitation for"

        elif action == "reject":
            req.status = "REJECTED"
            notification.verb = "You declined the invitation for"

        else:
            return Response({"error": "Invalid action"}, status=400)

        req.save()
        notification.is_read = True
        notification.save()

        return Response({"status": req.status})