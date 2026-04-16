from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from documents.models import (
    DocumentModel,
    DocumentDeletionRequestModel,
    DocumentDeletionDecisionModel,
)
from document_permissions.models import DocumentPermissionModel
from versions.models import VersionsModel

User = get_user_model()


class BaseTestCase(APITestCase):
    def create_user(self, username, email, is_superuser=False):
        return User.objects.create_user(
            username=username,
            email=email,
            password="pass123",
            first_name="Test",
            last_name="User",
            is_superuser=is_superuser
        )

    def setUp(self):
        self.user = self.create_user("user1", "user1@test.com", is_superuser=True)
        self.user2 = self.create_user("user2", "user2@test.com")
        self.reviewer = self.create_user("reviewer", "reviewer@test.com")

        self.token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")


# ------------------------------------------------------------------
# Document CRUD Tests
# ------------------------------------------------------------------

class DocumentCRUDTests(BaseTestCase):

    def test_create_document(self):
        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Test Document"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(DocumentModel.objects.count(), 1)

    def test_unique_title_per_user(self):
        DocumentModel.objects.create_document(
            created_by=self.user, title="Unique Doc"
        )

        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Unique Doc"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_documents_list(self):
        DocumentModel.objects.create_document(
            created_by=self.user, title="Doc 1"
        )

        url = reverse("document-list-create")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_update_document(self):
        doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Old Title"
        )

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.put(url, {"title": "New Title"})

        doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(doc.title, "New Title")


# ------------------------------------------------------------------
# Soft Delete & Restore
# ------------------------------------------------------------------

class DocumentDeleteRestoreTests(BaseTestCase):

    def test_delete_without_active_version(self):
        doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Delete Me"
        )

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.delete(url)

        doc.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(doc.is_deleted)

    def test_delete_requires_approval(self):
        doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Needs Approval"
        )

        VersionsModel.objects.create(
            document=doc,
            version_number=1,
            is_active=True,
            created_by=self.user,
        )

        DocumentPermissionModel.objects.create(
            user=self.reviewer,
            document=doc,
            version=None,
            permission_type="APPROVE",
        )

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.delete(url)

        doc.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertFalse(doc.is_deleted)

    def test_restore_document(self):
        doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Restore Me"
        )
        doc.delete()

        url = reverse("document-restore", args=[doc.id])
        response = self.client.post(url)

        doc.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(doc.is_deleted)


# ------------------------------------------------------------------
# Visibility & Permissions
# ------------------------------------------------------------------

class DocumentVisibilityTests(BaseTestCase):

    def test_user_sees_own_document(self):
        DocumentModel.objects.create_document(
            created_by=self.user, title="My Doc"
        )

        url = reverse("document-list-create")
        response = self.client.get(url)

        self.assertEqual(len(response.data["results"]), 1)

    def test_user_sees_shared_document(self):
        doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Shared Doc"
        )

        DocumentPermissionModel.objects.create(
            user=self.user2,
            document=doc,
            permission_type="READ",
        )

        token2 = str(RefreshToken.for_user(self.user2).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token2}")

        url = reverse("document-list-create")
        response = self.client.get(url)

        self.assertEqual(len(response.data["results"]), 1)


# ------------------------------------------------------------------
# Deletion Workflow (Approval System)
# ------------------------------------------------------------------

class DocumentDeletionWorkflowTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Workflow Doc"
        )

        VersionsModel.objects.create(
            document=self.doc,
            version_number=1,
            is_active=True,
            created_by=self.user,
        )

        DocumentPermissionModel.objects.create(
            user=self.reviewer,
            document=self.doc,
            permission_type="APPROVE",
            version=None,
        )

    def test_deletion_request_created(self):
        url = reverse("document-request-delete", args=[self.doc.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(DocumentDeletionRequestModel.objects.count(), 1)
        self.assertEqual(DocumentDeletionDecisionModel.objects.count(), 1)

    def test_reviewer_approves_deletion(self):
        self.client.post(reverse("document-request-delete", args=[self.doc.id]))

        token = str(RefreshToken.for_user(self.reviewer).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("document-deletion-decision", args=[self.doc.id])
        response = self.client.post(url, {"decision": "APPROVED"})

        self.doc.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(self.doc.is_deleted)

    def test_reviewer_rejects_deletion(self):
        self.client.post(reverse("document-request-delete", args=[self.doc.id]))

        token = str(RefreshToken.for_user(self.reviewer).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("document-deletion-decision", args=[self.doc.id])
        response = self.client.post(url, {"decision": "REJECTED"})

        self.doc.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.doc.is_deleted)

        deletion_request = DocumentDeletionRequestModel.objects.first()
        self.assertEqual(deletion_request.status, "REJECTED")


# ------------------------------------------------------------------
# Edge Cases
# ------------------------------------------------------------------

class DocumentEdgeCaseTests(BaseTestCase):

    def test_non_owner_cannot_restore(self):
        doc = DocumentModel.objects.create_document(
            created_by=self.user, title="Protected Doc"
        )
        doc.delete()

        token = str(RefreshToken.for_user(self.user2).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("document-restore", args=[doc.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)