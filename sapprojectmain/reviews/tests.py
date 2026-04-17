from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from .models import ReviewModel, ReviewStatus
from versions.models import VersionsModel, VersionStatus
from documents.models import DocumentModel
from document_permissions.models import DocumentPermissionModel

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

class ReviewBaseTestCase(APITestCase):
    def setUp(self):
        # Document owner + reviewer = same person (Jane owns the doc and has APPROVE)
        self.jane = make_user(
            username="reviewer_jane",
            email="jane@example.com",
            first="Jane",
            last="Reviewer",
        )

        self.document = DocumentModel.objects.create_document(
            created_by=self.jane,
            title="Quarterly Report",
        )

        DocumentPermissionModel.objects.update_or_create(
            user=self.jane,
            document=self.document,
            defaults={"permission_type": "APPROVE"},
        )

        self.version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.PENDING,
        )

        self.review = ReviewModel.objects.create(
            version=self.version,
            reviewer=self.jane,
            review_status=ReviewStatus.PENDING,
        )

        self.client.force_authenticate(user=self.jane)
        self.detail_url = reverse("review-detail", kwargs={"pk": self.review.id})
        self.inbox_url = reverse("review-inbox")
        self.create_url = reverse("review-create")


# ---------------------------------------------------------------------------
# Security / hacker tests
# ---------------------------------------------------------------------------

class TestReviewHacker(ReviewBaseTestCase):

    def test_idempotency_finalized_state(self):
        """Hacker Level: A finalized review cannot be re-approved or re-rejected."""
        self.review.review_status = ReviewStatus.APPROVED
        self.review.save()

        payload = {"review_status": ReviewStatus.REJECTED, "comments": "Changing my mind"}
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "This review has already been finalized.")

    def test_cross_user_permission_leak_get(self):
        """Security: Unrelated user cannot GET another user's review."""
        intruder = make_user(
            username="intruder_user",
            email="intruder@example.com",
            first="Int",
            last="Ruder",
        )
        self.client.force_authenticate(user=intruder)

        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_user_permission_leak_patch(self):
        """Security: Unrelated user cannot PATCH another user's review."""
        intruder = make_user(
            username="patch_intruder",
            email="patch_intruder@example.com",
            first="Pat",
            last="Cher",
        )
        self.client.force_authenticate(user=intruder)

        payload = {"review_status": ReviewStatus.APPROVED}
        response = self.client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_access_review(self):
        """Security: Anonymous users are denied access to review detail."""
        self.client.logout()
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejection_without_comment_is_blocked(self):
        """Validation: Rejecting without a comment must be blocked by the serializer."""
        payload = {"review_status": ReviewStatus.REJECTED}
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("comments", response.data)

    def test_version_singleton_active_enforced_on_approval(self):
        """Integrity: Approving a review deactivates any previously active version."""
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.APPROVED,
            is_active=True,
        )

        payload = {"review_status": ReviewStatus.APPROVED}
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.version.refresh_from_db()
        v2.refresh_from_db()

        self.assertTrue(self.version.is_active)
        self.assertFalse(v2.is_active)

    def test_soft_delete_access_block(self):
        """Boundary: Reviews linked to deleted documents are inaccessible."""
        self.document.delete()

        response = self.client.get(self.detail_url)
        self.assertIn(
            response.status_code,
            [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND],
        )


# ---------------------------------------------------------------------------
# State-sync tests
# ---------------------------------------------------------------------------

class TestReviewStateSync(ReviewBaseTestCase):

    def test_version_status_syncs_on_approval(self):
        """Base Level: Approving a review sets version to APPROVED and is_active=True."""
        payload = {"review_status": ReviewStatus.APPROVED}
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.version.refresh_from_db()
        self.review.refresh_from_db()

        self.assertEqual(self.version.status, VersionStatus.APPROVED)
        self.assertTrue(self.version.is_active)
        self.assertEqual(self.review.review_status, ReviewStatus.APPROVED)

    def test_version_status_syncs_on_rejection(self):
        """Base Level: Rejecting a review sets version to REJECTED and is_active=False."""
        payload = {
            "review_status": ReviewStatus.REJECTED,
            "comments": "Formatting issues throughout.",
        }
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.version.refresh_from_db()
        self.review.refresh_from_db()

        self.assertEqual(self.version.status, VersionStatus.REJECTED)
        self.assertFalse(self.version.is_active)
        self.assertEqual(self.review.review_status, ReviewStatus.REJECTED)

    def test_reviewed_at_timestamp_set_on_patch(self):
        """Integrity: reviewed_at must be populated after a PATCH decision."""
        self.assertIsNone(self.review.reviewed_at)

        payload = {"review_status": ReviewStatus.APPROVED}
        self.client.patch(self.detail_url, payload)

        self.review.refresh_from_db()
        self.assertIsNotNone(self.review.reviewed_at)

    def test_reviewer_field_set_to_current_user_on_patch(self):
        """Integrity: The reviewer field is stamped with the authenticated user on PATCH."""
        payload = {"review_status": ReviewStatus.APPROVED}
        self.client.patch(self.detail_url, payload)

        self.review.refresh_from_db()
        self.assertEqual(self.review.reviewer, self.jane)


# ---------------------------------------------------------------------------
# Inbox / list tests
# ---------------------------------------------------------------------------

class TestReviewPermissions(ReviewBaseTestCase):

    def test_reviewer_sees_own_pending_reviews_in_inbox(self):
        """Base Level: Reviewer sees their pending reviews in the inbox."""
        response = self.client.get(self.inbox_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(str(response.data[0]["id"]), str(self.review.id))

    def test_inbox_hides_finalized_reviews_by_default(self):
        """Default filter: Inbox only shows PENDING unless ?all=true."""
        self.review.review_status = ReviewStatus.APPROVED
        self.review.save()

        response = self.client.get(self.inbox_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_inbox_all_flag_returns_all_statuses(self):
        """Performance: ?all=true bypasses the pending filter and returns full history."""
        self.review.review_status = ReviewStatus.APPROVED
        self.review.save()

        response = self.client.get(self.inbox_url, {"all": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_inbox_filter_by_version_id(self):
        """Performance: ?version= narrows inbox to a single version's reviews."""
        other_version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.PENDING,
        )
        ReviewModel.objects.create(
            version=other_version,
            reviewer=self.jane,
            review_status=ReviewStatus.PENDING,
        )

        response = self.client.get(self.inbox_url, {"version": str(self.version.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(str(response.data[0]["version"]), str(self.version.id))

    def test_staff_sees_all_reviews_across_documents(self):
        """Privilege: Staff users bypass document-level filters and see every review."""
        other_owner = make_user(
            username="other_doc_owner",
            email="other_doc_owner@example.com",
            first="Other",
            last="Owner",
        )
        other_doc = DocumentModel.objects.create_document(
            created_by=other_owner, title="Top Secret"
        )
        other_v = VersionsModel.objects.create(
            document=other_doc,
            created_by=other_owner,
            version_number=1,
        )
        ReviewModel.objects.create(
            version=other_v,
            reviewer=other_owner,
            review_status=ReviewStatus.PENDING,
        )

        self.jane.is_staff = True
        self.jane.save()

        response = self.client.get(self.inbox_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_non_staff_sees_only_own_reviews(self):
        """Isolation: Non-staff users only see reviews assigned to them."""
        bob = make_user(
            username="bob_reviewer",
            email="bob_reviewer@example.com",
            first="Bob",
            last="Rev",
        )
        DocumentPermissionModel.objects.create(
            user=bob,
            document=self.document,
            permission_type="APPROVE",
        )
        bob_version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.PENDING,
        )
        ReviewModel.objects.create(
            version=bob_version,
            reviewer=bob,
            review_status=ReviewStatus.PENDING,
        )

        self.client.force_authenticate(user=bob)
        response = self.client.get(self.inbox_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for entry in response.data:
            self.assertEqual(entry["reviewer"], bob.id)


# ---------------------------------------------------------------------------
# Create review tests
# ---------------------------------------------------------------------------

class TestReviewCreate(ReviewBaseTestCase):
    """
    Jane is the document creator but the base setUp only gives her APPROVE.
    can_write_document() checks for a WRITE entry in document_permissions, so
    we add that here — otherwise the view's first guard fires 403 on every call.
    """

    def setUp(self):
        super().setUp()
        DocumentPermissionModel.objects.update_or_create(
            user=self.jane,
            document=self.document,
            defaults={"permission_type": "WRITE"},
        )

    def test_owner_can_assign_eligible_reviewer(self):
        """Base Level: A document owner can create a review for an eligible reviewer."""
        eligible = make_user(
            username="eligible_rev",
            email="eligible_rev@example.com",
            first="Eli",
            last="Gible",
        )
        DocumentPermissionModel.objects.create(
            user=eligible,
            document=self.document,
            permission_type="APPROVE",
        )
        new_version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.DRAFT,
        )

        payload = {
            "version": str(new_version.id),
            "reviewer": eligible.id,
        }
        response = self.client.post(self.create_url, payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            ReviewModel.objects.filter(version=new_version, reviewer=eligible).exists()
        )
        new_version.refresh_from_db()
        self.assertEqual(new_version.status, VersionStatus.PENDING)

    def test_duplicate_pending_review_is_blocked(self):
        """Idempotency: Assigning the same reviewer twice to the same version is rejected."""
        # Need a reviewer with APPROVE (eligibility guard) on a fresh version.
        # Jane only has WRITE after setUp, so we use a dedicated eligible user.
        eligible = make_user(
            username="dup_check_rev",
            email="dup_check_rev@example.com",
            first="Dup",
            last="Check",
        )
        DocumentPermissionModel.objects.create(
            user=eligible,
            document=self.document,
            permission_type="APPROVE",
        )
        new_version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.DRAFT,
        )
        # Seed the first review so the duplicate guard has something to find
        ReviewModel.objects.create(
            version=new_version,
            reviewer=eligible,
            review_status=ReviewStatus.PENDING,
        )

        # Second assignment of the same reviewer → must be blocked
        payload = {
            "version": str(new_version.id),
            "reviewer": eligible.id,
        }
        response = self.client.post(self.create_url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already has a pending review", response.data["error"])

    def test_ineligible_reviewer_is_blocked(self):
        """Security: Users without APPROVE permission cannot be assigned as reviewers."""
        rando = make_user(
            username="rando_user_01",
            email="rando_01@example.com",
            first="Ran",
            last="Do",
        )
        new_version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.DRAFT,
        )

        payload = {
            "version": str(new_version.id),
            "reviewer": rando.id,
        }
        response = self.client.post(self.create_url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Actual message: "This user is not an eligible reviewer for this document."
        self.assertIn("not an eligible reviewer for this document", response.data["error"])

    def test_missing_version_field_returns_400(self):
        """Validation: Missing version in payload returns 400."""
        response = self.client.post(self.create_url, {"reviewer": self.jane.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("version", response.data["error"])

    def test_missing_reviewer_field_returns_400(self):
        """Validation: Missing reviewer in payload returns 400."""
        response = self.client.post(
            self.create_url, {"version": str(self.version.id)}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reviewer", response.data["error"])

    def test_unauthenticated_cannot_create_review(self):
        """Security: Anonymous users cannot create reviews."""
        self.client.logout()
        payload = {"version": str(self.version.id), "reviewer": self.jane.id}
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Data-retention tests
# ---------------------------------------------------------------------------

class TestReviewDataRetention(ReviewBaseTestCase):

    def test_review_persists_after_reviewer_deleted(self):
        """Audit: Deleting a reviewer account preserves the review record (SET_NULL)."""
        guest = make_user(
            username="guest_reviewer_01",
            email="guest01@example.com",
            first="Guest",
            last="One",
        )
        DocumentPermissionModel.objects.create(
            user=guest,
            document=self.document,
            permission_type="APPROVE",
        )

        self.client.force_authenticate(user=guest)
        payload = {"review_status": ReviewStatus.APPROVED}
        self.client.patch(self.detail_url, payload)

        guest.delete()

        self.review.refresh_from_db()
        self.assertIsNone(self.review.reviewer)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, VersionStatus.APPROVED)

    def test_review_cascade_deleted_with_version(self):
        """Integrity: Deleting a version also removes its associated reviews."""
        review_id = self.review.id
        self.version.delete()
        self.assertFalse(ReviewModel.objects.filter(id=review_id).exists())


# ---------------------------------------------------------------------------
# Payload / serializer tests
# ---------------------------------------------------------------------------

class TestReviewPayload(ReviewBaseTestCase):

    def test_get_review_returns_new_and_old_version(self):
        """Base Level: GET review detail includes new_version and old_version for diffing."""
        parent_v = VersionsModel.objects.create(
            document=self.document,
            created_by=self.jane,
            status=VersionStatus.APPROVED,
        )
        self.version.parent_version = parent_v
        self.version.save()

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["new_version"])
        self.assertIsNotNone(response.data["old_version"])
        self.assertEqual(str(response.data["old_version"]["id"]), str(parent_v.id))

    def test_get_review_old_version_is_none_without_parent(self):
        """Edge case: old_version is None when the version has no parent."""
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["old_version"])

    def test_get_review_includes_reviewer_name(self):
        """Payload: reviewer_name is present and matches the assigned reviewer."""
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["reviewer_name"], self.jane.username)

    def test_read_only_fields_ignored_on_patch(self):
        """Security: version and reviewer fields in PATCH payload are silently ignored."""
        other = make_user(
            username="readonly_tester",
            email="readonly_tester@example.com",
            first="Read",
            last="Only",
        )
        payload = {
            "review_status": ReviewStatus.APPROVED,
            "reviewer": other.id,
            "version": str(self.version.id),
        }
        self.client.patch(self.detail_url, payload)

        self.review.refresh_from_db()
        self.assertEqual(self.review.reviewer, self.jane)
        self.assertEqual(self.review.version, self.version)