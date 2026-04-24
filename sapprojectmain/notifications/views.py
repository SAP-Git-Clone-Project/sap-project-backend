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
import traceback


# Custom Pagination with unread counts
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


# Optimized List View with filtering and search
class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        user = self.request.user

        queryset = NotificationModel.objects.filter(recipient=user).select_related(
            'user', 'target_document'
        ).order_by("-created_at")

        status_filter = self.request.query_params.get("status")
        if status_filter == "unread":
            queryset = queryset.filter(is_read=False)
        elif status_filter == "read":
            queryset = queryset.filter(is_read=True)

        search_query = self.request.query_params.get("q")
        if search_query:
            queryset = queryset.filter(
                Q(verb__icontains=search_query) |
                Q(target_document__title__icontains=search_query) |
                Q(user__username__icontains=search_query)
            )

        return queryset


# Mark specific notification as read
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


# Mark all as read
class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        NotificationModel.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(is_read=True)
        return Response({"status": "all marked as read"}, status=status.HTTP_200_OK)


# Delete notification
class NotificationDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        return NotificationModel.objects.filter(recipient=self.request.user)


# Handle permission/invitation requests  (unchanged)
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


# Handle document deletion approval requests  (NEW — mirrors HandleJoinRequestView)
class HandleDeletionRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(
            NotificationModel, pk=pk, recipient=request.user
        )

        action = request.data.get("action")   # "accept" | "reject"
        deletion_req = notification.deletion_request

        if not deletion_req:
            return Response({"error": "No deletion request found"}, status=400)

        if deletion_req.status != "PENDING":
            return Response({"detail": "Already handled"}, status=400)

        if action not in ("accept", "reject"):
            return Response({"error": "Invalid action"}, status=400)

        from documents.models import DocumentDeletionDecisionModel
        from documents.views import notify_owner_of_decision

        document = deletion_req.document
        decision_value = "APPROVED" if action == "accept" else "REJECTED"

        # Record this reviewer's vote
        DocumentDeletionDecisionModel.objects.update_or_create(
            document=document,
            reviewer_id=request.user,
            defaults={"decision": decision_value},
        )

        # Update the notification's verb so it reflects what the reviewer did
        notification.verb = (
            "You approved the deletion of"
            if action == "accept"
            else "You rejected the deletion of"
        )
        notification.is_read = True
        notification.save()

        # --- Check consensus ---
        reviewer_ids = set(
            DocumentPermissionModel.objects.filter(
                document=document, permission_type="APPROVE"
            ).values_list("user", flat=True)
        )

        decisions = DocumentDeletionDecisionModel.objects.filter(document=document)
        approved_ids = set(decisions.filter(decision="APPROVED").values_list("reviewer_id", flat=True))
        rejected_exists = decisions.filter(decision="REJECTED").exists()

        if rejected_exists:
            deletion_req.status = "REJECTED"
            deletion_req.save()
            notify_owner_of_decision(document, deletion_req, accepted=False)
            return Response({"status": "REJECTED", "detail": "Deletion rejected."})

        if reviewer_ids and reviewer_ids == approved_ids:
            deletion_req.status = "APPROVED"
            deletion_req.save()
            notify_owner_of_decision(document, deletion_req, accepted=True)
            document.delete()
            return Response({"status": "APPROVED", "detail": "Document deleted after unanimous approval."})

        return Response({"status": "PENDING", "detail": "Vote recorded, waiting for other reviewers."})
    