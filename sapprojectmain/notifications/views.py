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
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        # HACKER PROTECTION: A user can only "see" their own notifications.
        # If they try to access someone else's ID, they get a 404 (Not Found)
        # instead of a 403 (Forbidden), which is more secure.
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
