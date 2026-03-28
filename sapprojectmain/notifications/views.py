from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import NotificationModel
from .serializers import NotificationSerializer


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
    queryset = NotificationModel.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def patch(self, request, *args, **kwargs):
        # NOTE: PATCH to mark a single notification as read by UUID
        notification = self.get_object()

        # SECURITY: Prevents users from marking others' notifications as read
        if notification.recipient != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        notification.is_read = True
        notification.save()
        return Response({"status": "read"})


class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # NOTE: POST to update all unread notifications for the user at once
        NotificationModel.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True
        )
        return Response({"status": "all marked as read"}, status=status.HTTP_200_OK)
