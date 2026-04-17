from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from .models import NotificationModel
from documents.models import DocumentModel
from document_permissions.models import DocumentPermissionModel
from reviews.models import ReviewModel, ReviewStatus
from versions.models import VersionsModel, VersionStatus

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, email, first="Test", last="User", password="Secure@123!"):
    return User.objects.create_user(
        username=username,
        email=email,
        first_name=first,
        last_name=last,
        password=password,
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class NotificationBaseTestCase(TransactionTestCase):
    """
    TransactionTestCase is required so transaction.on_commit() callbacks
    actually fire inside each test.

    NOTE: DocumentModel.objects.create() triggers a post_save signal that
    auto-creates a DocumentPermissionModel for the owner, which in turn fires
    notify_access_granted (on_commit) → one notification for alice is created
    during setUp before any test body runs.  We wipe all notifications at the
    END of setUp so every test starts with a clean slate.
    """

    def setUp(self):
        self.client = APIClient()

        self.alice = make_user(
            username="alice_owner",
            email="alice@notify.com",
            first="Alice",
            last="Owner",
        )
        self.bob = make_user(
            username="bob_viewer",
            email="bob@notify.com",
            first="Bob",
            last="Viewer",
        )

        self.doc = DocumentModel.objects.create(
            title="Project Alpha",
            created_by=self.alice,
        )

        # Clear any notifications created by setUp-level signals so every
        # test starts with a known-zero state.
        NotificationModel.objects.all().delete()

        self.list_url = reverse("notification-list")
        self.mark_all_url = reverse("mark-all-read")

    # Convenience helpers
    def _notif(self, recipient, verb="pinged", is_read=False, document=None):
        return NotificationModel.objects.create(
            recipient=recipient,
            user=self.alice,
            verb=verb,
            is_read=is_read,
            target_document=document or self.doc,
        )

    def _mark_read_url(self, pk):
        return reverse("mark-read", kwargs={"pk": pk})

    def _delete_url(self, pk):
        return reverse("delete-notification", kwargs={"pk": pk})


# ---------------------------------------------------------------------------
# Authentication guard tests
# ---------------------------------------------------------------------------

class TestNotificationAuth(NotificationBaseTestCase):

    def test_list_requires_auth(self):
        """Security: Anonymous users cannot list notifications."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mark_all_read_requires_auth(self):
        """Security: Anonymous users cannot call mark-all-read."""
        response = self.client.post(self.mark_all_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mark_single_read_requires_auth(self):
        """Security: Anonymous users cannot mark a specific notification as read."""
        n = self._notif(self.alice)
        response = self.client.patch(self._mark_read_url(n.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_requires_auth(self):
        """Security: Anonymous users cannot delete notifications."""
        n = self._notif(self.alice)
        response = self.client.delete(self._delete_url(n.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# List + pagination + filtering
# ---------------------------------------------------------------------------

class TestNotificationList(NotificationBaseTestCase):

    def test_user_sees_only_own_notifications(self):
        """Isolation: Each user receives only their own notifications."""
        self._notif(self.alice, verb="for alice")
        self._notif(self.bob, verb="for bob")

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data.get("notifications", response.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["verb"], "for alice")

    def test_unread_count_in_paginated_response(self):
        """Payload: unread_count reflects only the current user's unread notifications."""
        self._notif(self.alice, is_read=False)
        self._notif(self.alice, is_read=False)
        self._notif(self.alice, is_read=True)
        self._notif(self.bob, is_read=False)   # must NOT affect alice's count

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unread_count"], 2)

    def test_filter_unread(self):
        """Filter: ?status=unread returns only unread notifications."""
        self._notif(self.alice, verb="unread one", is_read=False)
        self._notif(self.alice, verb="read one", is_read=True)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url, {"status": "unread"})

        data = response.data.get("notifications", response.data)
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["is_read"])

    def test_filter_read(self):
        """Filter: ?status=read returns only read notifications."""
        self._notif(self.alice, verb="unread one", is_read=False)
        self._notif(self.alice, verb="read one", is_read=True)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url, {"status": "read"})

        data = response.data.get("notifications", response.data)
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["is_read"])

    def test_search_by_verb(self):
        """Search: ?q= filters notifications by verb content."""
        self._notif(self.alice, verb="approved your document")
        self._notif(self.alice, verb="rejected your upload")

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url, {"q": "approved"})

        data = response.data.get("notifications", response.data)
        self.assertEqual(len(data), 1)
        self.assertIn("approved", data[0]["verb"])

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
        Security (IDOR): Bob cannot mark Alice's notification as read.
        Returns 404 — obscurity over 403.
        """
        n = self._notif(self.alice, is_read=False)

        self.client.force_authenticate(user=self.bob)
        response = self.client.patch(self._mark_read_url(n.id))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        n.refresh_from_db()
        self.assertFalse(n.is_read)

    def test_already_read_notification_stays_read(self):
        """Idempotency: Marking an already-read notification read again is a no-op."""
        n = self._notif(self.alice, is_read=True)

        self.client.force_authenticate(user=self.alice)
        response = self.client.patch(self._mark_read_url(n.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_malformed_uuid_returns_404(self):
        """Stability: Garbage UUIDs in the URL never trigger a 500."""
        self.client.force_authenticate(user=self.alice)
        response = self.client.patch("/api/notifications/not-a-valid-uuid/read/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Mark all as read
# ---------------------------------------------------------------------------

class TestMarkAllRead(NotificationBaseTestCase):

    def test_mark_all_read_affects_only_current_user(self):
        """
        Security: Mark-all-read is scoped strictly to the authenticated user.
        Bob's unread notification must remain unread after Alice's bulk update.
        """
        self._notif(self.alice, verb="alice unread 1", is_read=False)
        self._notif(self.alice, verb="alice unread 2", is_read=False)
        n_bob = self._notif(self.bob, verb="bob unread", is_read=False)

        self.client.force_authenticate(user=self.alice)
        response = self.client.post(self.mark_all_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "all marked as read")

        alice_unread = NotificationModel.objects.filter(
            recipient=self.alice, is_read=False
        ).count()
        self.assertEqual(alice_unread, 0)

        n_bob.refresh_from_db()
        self.assertFalse(n_bob.is_read)

    def test_mark_all_read_with_no_unread_is_safe(self):
        """Edge case: Calling mark-all-read when everything is already read returns 200."""
        self._notif(self.alice, is_read=True)

        self.client.force_authenticate(user=self.alice)
        response = self.client.post(self.mark_all_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_mark_all_read_no_notifications_is_safe(self):
        """Edge case: Calling mark-all-read with zero notifications returns 200."""
        self.client.force_authenticate(user=self.alice)
        response = self.client.post(self.mark_all_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Delete notification
# ---------------------------------------------------------------------------

class TestDeleteNotification(NotificationBaseTestCase):

    def test_owner_can_delete_own_notification(self):
        """Happy path: User successfully deletes their own notification."""
        n = self._notif(self.alice)
        n_id = n.id

        self.client.force_authenticate(user=self.alice)
        response = self.client.delete(self._delete_url(n_id))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(NotificationModel.objects.filter(id=n_id).exists())

    def test_idor_protection_delete(self):
        """Security (IDOR): Bob cannot delete Alice's notification."""
        n = self._notif(self.alice)

        self.client.force_authenticate(user=self.bob)
        response = self.client.delete(self._delete_url(n.id))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(NotificationModel.objects.filter(id=n.id).exists())

    def test_delete_nonexistent_returns_404(self):
        """Stability: Deleting a non-existent notification returns 404, not 500."""
        import uuid
        self.client.force_authenticate(user=self.alice)
        response = self.client.delete(self._delete_url(uuid.uuid4()))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Signal: access granted
# ---------------------------------------------------------------------------

class TestAccessGrantedSignal(NotificationBaseTestCase):

    def test_notification_sent_when_permission_created(self):
        """Signal: Creating a DocumentPermission notifies the new collaborator."""
        DocumentPermissionModel.objects.create(
            document=self.doc,
            user=self.bob,
            permission_type="VIEWER",
        )

        # The actual verb format is: "permission granted by admin/owner: <TYPE>"
        notif = NotificationModel.objects.filter(recipient=self.bob).first()
        self.assertIsNotNone(notif)
        self.assertIn("permission granted", notif.verb)
        self.assertIn("VIEWER", notif.verb)

    def test_no_notification_on_permission_update(self):
        """Signal: Updating an existing permission must NOT fire a second notification."""
        perm = DocumentPermissionModel.objects.create(
            document=self.doc,
            user=self.bob,
            permission_type="VIEWER",
        )
        # Clear the grant notification that just fired
        NotificationModel.objects.filter(recipient=self.bob).delete()

        perm.permission_type = "WRITE"
        perm.save()

        count = NotificationModel.objects.filter(recipient=self.bob).count()
        self.assertEqual(count, 0)

    def test_notification_actor_is_document_owner(self):
        """Signal: The 'user' field on the notification is the document owner."""
        DocumentPermissionModel.objects.create(
            document=self.doc,
            user=self.bob,
            permission_type="APPROVE",
        )

        notif = NotificationModel.objects.filter(recipient=self.bob).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.user, self.alice)


# ---------------------------------------------------------------------------
# Signal: resignation (permission deleted)
# ---------------------------------------------------------------------------

class TestResignationSignal(NotificationBaseTestCase):

    def test_notification_sent_to_owner_on_resignation(self):
        """
        Signal: Deleting a permission notifies the document owner.

        Strategy: record alice's notification count BEFORE the delete, then
        assert it increased by exactly 1 with a verb containing 'resigned'.
        This avoids noise from bob's grant notification without a blanket delete.
        """
        perm = DocumentPermissionModel.objects.create(
            document=self.doc,
            user=self.bob,
            permission_type="VIEWER",
        )
        alice_before = NotificationModel.objects.filter(recipient=self.alice).count()

        perm.delete()

        notif = NotificationModel.objects.filter(
            recipient=self.alice,
            verb__icontains="resigned",
        ).first()
        self.assertIsNotNone(notif)
        alice_after = NotificationModel.objects.filter(recipient=self.alice).count()
        self.assertEqual(alice_after, alice_before + 1)

    def test_resignation_notification_actor_is_the_leaving_user(self):
        """Signal: The 'user' on the resignation notification is the departing collaborator."""
        perm = DocumentPermissionModel.objects.create(
            document=self.doc,
            user=self.bob,
            permission_type="WRITE",
        )
        perm.delete()

        notif = NotificationModel.objects.filter(
            recipient=self.alice,
            verb__icontains="resigned",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.user, self.bob)


# ---------------------------------------------------------------------------
# Signal: review decision
# ---------------------------------------------------------------------------

class TestReviewDecisionSignal(NotificationBaseTestCase):

    def _make_pending_review(self):
        version = VersionsModel.objects.create(
            document=self.doc,
            created_by=self.bob,
            status=VersionStatus.PENDING,
        )
        review = ReviewModel.objects.create(
            version=version,
            reviewer=self.alice,
            review_status=ReviewStatus.PENDING,
        )
        # Clear any notifications fired by version/review creation
        NotificationModel.objects.all().delete()
        return review

    def test_approval_notifies_version_creator(self):
        """Signal: Approving a review notifies the version's creator."""
        review = self._make_pending_review()

        review.review_status = ReviewStatus.APPROVED
        review.save()

        notif = NotificationModel.objects.filter(recipient=self.bob).first()
        self.assertIsNotNone(notif)
        self.assertIn("approved", notif.verb)

    def test_rejection_notifies_version_creator(self):
        """Signal: Rejecting a review notifies the version's creator."""
        review = self._make_pending_review()

        review.review_status = ReviewStatus.REJECTED
        review.save()

        notif = NotificationModel.objects.filter(recipient=self.bob).first()
        self.assertIsNotNone(notif)
        self.assertIn("rejected", notif.verb)

    def test_no_notification_when_status_unchanged(self):
        """Signal: Re-saving a review without changing status must not fire a notification."""
        review = self._make_pending_review()

        review.save()  # no status change

        count = NotificationModel.objects.filter(recipient=self.bob).count()
        self.assertEqual(count, 0)

    def test_no_decision_notification_on_review_creation(self):
        """Signal: Creating a brand-new review (created=True) must not fire the decision signal."""
        version = VersionsModel.objects.create(
            document=self.doc,
            created_by=self.bob,
            status=VersionStatus.PENDING,
        )
        NotificationModel.objects.all().delete()

        ReviewModel.objects.create(
            version=version,
            reviewer=self.alice,
            review_status=ReviewStatus.PENDING,
        )

        count = NotificationModel.objects.filter(
            recipient=self.bob,
            verb__icontains="approved",
        ).count()
        self.assertEqual(count, 0)

    def test_notification_actor_is_the_reviewer(self):
        """Signal: The 'user' on the decision notification is the reviewer (Alice)."""
        review = self._make_pending_review()

        review.review_status = ReviewStatus.APPROVED
        review.save()

        notif = NotificationModel.objects.filter(recipient=self.bob).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.user, self.alice)


# ---------------------------------------------------------------------------
# Serializer field tests
# ---------------------------------------------------------------------------

class TestNotificationSerializerFields(NotificationBaseTestCase):

    def test_response_contains_expected_fields(self):
        """Payload: Notification list items expose all required frontend fields."""
        self._notif(self.alice)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        data = response.data.get("notifications", response.data)
        self.assertGreater(len(data), 0)

        item = data[0]
        for field in [
            "id", "verb", "is_read", "created_at",
            "created_since", "target_document_title",
            "user_username", "user_avatar",
        ]:
            self.assertIn(field, item, msg=f"Missing field: {field}")

    def test_created_since_is_human_readable(self):
        """Serializer: created_since must be a non-empty string ending in 'ago' or a fallback."""
        self._notif(self.alice)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        data = response.data.get("notifications", response.data)
        since = data[0]["created_since"]
        self.assertIsInstance(since, str)
        self.assertTrue(since.endswith("ago") or since in ("Just now", "Recently"))

    def test_target_document_title_populated(self):
        """Serializer: target_document_title returns the linked document's title."""
        self._notif(self.alice, document=self.doc)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        data = response.data.get("notifications", response.data)
        self.assertEqual(data[0]["target_document_title"], self.doc.title)

    def test_permission_field_none_when_no_request(self):
        """Serializer: permission field is null when no permission_request is linked."""
        self._notif(self.alice)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        data = response.data.get("notifications", response.data)
        self.assertIsNone(data[0]["permission"])

    def test_deletion_field_none_when_no_request(self):
        """Serializer: deletion field is null when no deletion_request is linked."""
        self._notif(self.alice)

        self.client.force_authenticate(user=self.alice)
        response = self.client.get(self.list_url)

        data = response.data.get("notifications", response.data)
        self.assertIsNone(data[0]["deletion"])