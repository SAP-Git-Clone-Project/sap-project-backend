import uuid
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import NotificationModel
from documents.models import DocumentModel
from document_permissions.models import DocumentPermissionModel

User = get_user_model()


class NotificationHardenedTests(TransactionTestCase):
    """
    Hacker-level test suite for Notifications.
    Uses TransactionTestCase to support transaction.on_commit signals.
    """

    def setUp(self):
        self.client = APIClient()
        self.user_a = User.objects.create_user(
            username="usera", password="pass123", email="a@test.com"
        )
        self.user_b = User.objects.create_user(
            username="userb", password="pass123", email="b@test.com"
        )

        # Create a document for signal testing
        self.doc = DocumentModel.objects.create(
            title="Secure Document", created_by=self.user_a
        )

        # URL lookups (Ensure these names match your urls.py)
        self.list_url = reverse("notification-list")
        self.mark_all_read_url = reverse("mark-all-read")

    # --- BASIC FUNCTIONALITY ---

    def test_list_and_unread_count(self):
        """Verify notifications are filtered by user and unread count logic."""
        NotificationModel.objects.create(
            recipient=self.user_a, verb="notified", is_read=False
        )
        NotificationModel.objects.create(
            recipient=self.user_a, verb="notified", is_read=True
        )

        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check that we handle both paginated and non-paginated responses
        data = response.data.get("notifications", response.data)
        unread = response.data.get("unread_count")

        self.assertEqual(unread, 1)
        self.assertEqual(len(data), 2)

    def test_signal_on_permission_granted(self):
        """Verify that granting permission triggers a real notification via on_commit."""
        DocumentPermissionModel.objects.create(
            document=self.doc, user=self.user_b, permission_type="VIEWER"
        )

        # Check if User B got the notification
        notif = NotificationModel.objects.filter(recipient=self.user_b).first()
        self.assertIsNotNone(notif)
        self.assertIn("granted you", notif.verb)

    # --- HACKER & SECURITY TESTS ---

    def test_idor_protection_mark_read(self):
        """
        HACKER CHECK: IDOR Protection.
        User B should NOT be able to see or mark User A's notification as read.
        Expected: 404 Not Found (Obscurity is better than 403).
        """
        notif_a = NotificationModel.objects.create(recipient=self.user_a, verb="secret")
        mark_read_url = reverse("mark-read", kwargs={"pk": notif_a.id})

        self.client.force_authenticate(user=self.user_b)
        response = self.client.patch(mark_read_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Verify it stayed unread
        notif_a.refresh_from_db()
        self.assertFalse(notif_a.is_read)

    def test_malformed_uuid_lookup(self):
        """STABILITY CHECK: Garbage UUIDs should never trigger a 500 crash."""
        self.client.force_authenticate(user=self.user_a)

        # Hardcoded bypass because reverse() regex prevents invalid UUIDs
        bad_url = "/api/notifications/not-a-uuid-12345/read/"
        response = self.client.patch(bad_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_all_read_isolation(self):
        """SECURITY CHECK: Mark All Read must only affect the authenticated user."""
        NotificationModel.objects.create(recipient=self.user_a, is_read=False, verb="A")
        NotificationModel.objects.create(recipient=self.user_b, is_read=False, verb="B")

        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(self.mark_all_read_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check DB
        self.assertTrue(NotificationModel.objects.get(verb="A").is_read)
        self.assertFalse(NotificationModel.objects.get(verb="B").is_read)

    def test_signal_reliability_on_review(self):
        """
        INTEGRITY CHECK: Ensure pre_save and post_save logic works for review status changes.
        """
        from reviews.models import ReviewModel
        from versions.models import VersionsModel

        version = VersionsModel.objects.create(
            document=self.doc, created_by=self.user_b
        )
        review = ReviewModel.objects.create(
            version=version, reviewer=self.user_a, review_status="PENDING"
        )

        # Update to trigger 'post_save' + 'on_commit'
        review.review_status = "APPROVED"
        review.save()

        count = NotificationModel.objects.filter(
            recipient=self.user_b, verb__contains="approved"
        ).count()

        self.assertEqual(count, 1)
