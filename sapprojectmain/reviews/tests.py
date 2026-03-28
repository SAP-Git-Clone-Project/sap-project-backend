from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from .models import ReviewModel, ReviewStatus
from versions.models import VersionsModel, VersionStatus
from documents.models import DocumentModel
from document_permissions.models import DocumentPermissionModel

User = get_user_model()

class ReviewBaseTestCase(APITestCase):
    def setUp(self):
        self.reviewer = User.objects.create_user(
            username="reviewer_jane",
            email="jane@example.com",
            first_name="Jane",
            last_name="Reviewer",
            password="securepassword123"
        )
        
        # This call ALREADY creates a DocumentPermission for self.reviewer
        self.document = DocumentModel.objects.create_document(
            created_by=self.reviewer,
            title="Quarterly Report"
        )
        
        # Use update_or_create to avoid UNIQUE constraint failure
        # This ensures the reviewer has the 'APPROVE' right needed for the view
        DocumentPermissionModel.objects.update_or_create(
            user=self.reviewer,
            document=self.document,
            defaults={"permission_type": "APPROVE"}
        )
        
        self.version = VersionsModel.objects.create(
            document=self.document,
            created_by=self.reviewer,
            status=VersionStatus.PENDING
        )
        
        self.review = ReviewModel.objects.create(
            version=self.version,
            review_status=ReviewStatus.PENDING
        )

        self.client.force_authenticate(user=self.reviewer)
        self.detail_url = reverse('review-detail', kwargs={'pk': self.review.id})

class TestReviewHacker(ReviewBaseTestCase):

    def test_idempotency_finalized_state(self):
        """Hacker Level: Ensure a finalized review cannot be 're-rejected' or 're-approved'."""
        # 1. Finalize it first
        self.review.review_status = ReviewStatus.APPROVED
        self.review.save()

        # 2. Try to change it via API
        payload = {"review_status": ReviewStatus.REJECTED, "comments": "Changing my mind"}
        response = self.client.patch(self.detail_url, payload)

        # Should trigger your check: if review.review_status != ReviewStatus.PENDING
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], "This review has already been finalized.")

    def test_cross_user_permission_leak(self):
        """Security: Ensure User B cannot see or PATCH User A's review."""
        malicious_user = User.objects.create_user(
            username="malicious", email="m@ex.com", 
            first_name="M", last_name="A", password="p"
        )
        # We do NOT create a DocumentPermission for this user
        self.client.force_authenticate(user=malicious_user)

        response = self.client.get(self.detail_url)
        # This confirms why your previous test failed with 403:
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_version_number_integrity_during_approval(self):
        """Integrity: Ensure that approving a review respects the version's singleton active status."""
        # Create a newer version that is currently approved/active
        v2 = VersionsModel.objects.create(
            document=self.document, 
            created_by=self.reviewer, 
            status=VersionStatus.APPROVED,
            is_active=True
        )
        
        # Approve the original version (self.version) via the review
        payload = {"review_status": ReviewStatus.APPROVED}
        self.client.patch(self.detail_url, payload)
        
        v2.refresh_from_db()
        self.version.refresh_from_db()

        # Because of your VersionsModel.save() logic, v2 should now be inactive
        self.assertTrue(self.version.is_active)
        self.assertFalse(v2.is_active)

    def test_soft_delete_access_block(self):
        """Boundary: Ensure reviews for deleted documents are inaccessible."""
        self.document.delete() # Sets is_deleted=True
        
        response = self.client.get(self.detail_url)
        # If your QuerySet filters out is_deleted, this might return 404. 
        # If permissions check it, 403.
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])