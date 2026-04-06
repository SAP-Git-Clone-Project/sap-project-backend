from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import NotificationModel
from .serializers import NotificationSerializer

# Import your permission model to update the role status
# from document_permissions.models import DocumentPermissionModel


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # NOTE: Returns notifications for the logged-in user sorted by date
        return NotificationModel.objects.filter(recipient=self.request.user).order_by(
            "-created_at"
        )

    def get(self, request, *args, **kwargs):
        # NOTE: GET to retrieve notifications and total unread count
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        unread_count = queryset.filter(is_read=False).count()
        return Response(
            {"unread_count": unread_count, "notifications": serializer.data}
        )


class MarkNotificationReadView(generics.UpdateAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        # HACKER PROTECTION: Users only see their own notifications.
        return NotificationModel.objects.filter(recipient=self.request.user)

    def patch(self, request, *args, **kwargs):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({"status": "read"}, status=status.HTTP_200_OK)


class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # NOTE: POST to update all unread notifications for the user at once
        NotificationModel.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True
        )
        return Response({"status": "all marked as read"}, status=status.HTTP_200_OK)


class HandleJoinRequestView(APIView):
    """
    NEW: Handles the logic when a user clicks 'Accept' or 'Reject'
    on a document role invitation notification.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(
            NotificationModel, pk=pk, recipient=request.user
        )
        action = request.data.get("action")  # 'accept' or 'reject'

        # This assumes your signal added the permission ID to the data field
        # e.g., data={"permission_id": "uuid", "type": "ROLE_REQUEST"}
        permission_id = (
            notification.data.get("permission_id") if notification.data else None
        )

        if not permission_id:
            return Response(
                {"error": "No permission ID found"}, status=status.HTTP_400_BAD_REQUEST
            )

        if action == "accept":
            # Logic: Update the permission record to 'ACTIVE'
            # DocumentPermissionModel.objects.filter(id=permission_id).update(is_active=True)
            notification.verb = "You accepted the invitation for"
            msg = "Invitation accepted"

        elif action == "reject":
            # Logic: Delete the pending permission record
            # DocumentPermissionModel.objects.filter(id=permission_id).delete()
            notification.verb = "You declined the invitation for"
            msg = "Invitation declined"

        else:
            return Response(
                {"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Mark as read so buttons disappear in the UI
        notification.is_read = True
        notification.save()

        return Response({"status": msg}, status=status.HTTP_200_OK)
