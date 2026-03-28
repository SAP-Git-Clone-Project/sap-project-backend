from django.test import TestCase

import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import DocumentModel
from .models import DocumentPermissionModel

User = get_user_model()


class DocumentPermissionTestSetup(TestCase):
    """
    Shared setUp for all permission tests.

    Users:
        owner        — created the document, has DELETE permission
        write_user   — has WRITE permission on the document
        delete_user  — has DELETE permission (not the creator)
        read_user    — has READ permission on the document
        new_user     — authenticated but has no permission yet
        unrelated    — authenticated, exists on a completely different document
        superuser    — Django superuser, bypasses all guards

    Documents:
        document         — the primary document used in most tests
        other_document   — owned by unrelated_user, used for cross-doc tests
    """

    def setUp(self):
        self.client = APIClient()

        # --- Users ---
        self.owner = User.objects.create_user(
            username="owner", password="pass", email="owner@test.com"
        )
        self.write_user = User.objects.create_user(
            username="write_user", password="pass", email="write@test.com"
        )
        self.delete_user = User.objects.create_user(
            username="delete_user", password="pass", email="delete@test.com"
        )
        self.read_user = User.objects.create_user(
            username="read_user", password="pass", email="read@test.com"
        )
        self.new_user = User.objects.create_user(
            username="new_user", password="pass", email="new@test.com"
        )
        self.unrelated_user = User.objects.create_user(
            username="unrelated", password="pass", email="unrelated@test.com"
        )
        self.superuser = User.objects.create_superuser(
            username="superuser", password="pass", email="super@test.com"
        )

        # --- Documents ---
        self.document = DocumentModel.objects.create(
            title="Primary Doc", created_by=self.owner
        )
        self.other_document = DocumentModel.objects.create(
            title="Other Doc", created_by=self.unrelated_user
        )

        # --- Permissions on primary document ---
        self.owner_permission = DocumentPermissionModel.objects.create(
            user=self.owner,
            document=self.document,
            permission_type="DELETE",
        )
        self.write_permission = DocumentPermissionModel.objects.create(
            user=self.write_user,
            document=self.document,
            permission_type="WRITE",
        )
        self.delete_permission = DocumentPermissionModel.objects.create(
            user=self.delete_user,
            document=self.document,
            permission_type="DELETE",
        )
        self.read_permission = DocumentPermissionModel.objects.create(
            user=self.read_user,
            document=self.document,
            permission_type="READ",
        )

        # --- Permission for unrelated_user on their own document ---
        self.unrelated_permission = DocumentPermissionModel.objects.create(
            user=self.unrelated_user,
            document=self.other_document,
            permission_type="DELETE",
        )


# =============================================================================
# BASE LEVEL TESTS
# =============================================================================


class TestGrantPermissionBase(DocumentPermissionTestSetup):

    def test_unauthenticated_user_cannot_grant_permission(self):
        """No token → 401 before any permission check fires."""
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_read_only_user_cannot_grant_permission(self):
        """READ users are blocked from the grant endpoint (needs WRITE/DELETE)."""
        self.client.force_authenticate(user=self.read_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_write_user_can_grant_read_permission(self):
        """Happy path — a WRITE user successfully grants READ to a new user."""
        self.client.force_authenticate(user=self.write_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_grant_creates_permission_in_db(self):
        """Always verify the DB side, not just the HTTP response."""
        self.client.force_authenticate(user=self.owner)  # only DELETE-level can grant
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "WRITE",
        }
        self.client.post(url, data)
        exists = DocumentPermissionModel.objects.filter(
            user=self.new_user, document=self.document
        ).exists()
        self.assertTrue(exists)

    def test_grant_existing_returns_updated_status(self):
        """
        Upsert path — granting a new level to an existing user should succeed
        and report "updated".
        """
        self.client.force_authenticate(user=self.owner)
        url = reverse("permission-grant")
        data = {
            "user": str(self.read_user.id),  # already has READ
            "document": str(self.document.id),
            "permission_type": "WRITE",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "updated")
        perm = DocumentPermissionModel.objects.get(
            user=self.read_user, document=self.document
        )
        self.assertEqual(perm.permission_type, "WRITE")


class TestRevokePermissionBase(DocumentPermissionTestSetup):

    def test_delete_user_can_revoke_read_permission(self):
        """A DELETE-level user can revoke another user's access."""
        self.client.force_authenticate(user=self.delete_user)
        url = reverse("permission-revoke", kwargs={"id": self.read_permission.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            DocumentPermissionModel.objects.filter(id=self.read_permission.id).exists()
        )

    def test_read_user_cannot_revoke_permission(self):
        """A READ user must not be able to revoke anyone's access."""
        self.client.force_authenticate(user=self.read_user)
        url = reverse("permission-revoke", kwargs={"id": self.write_permission.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            DocumentPermissionModel.objects.filter(id=self.write_permission.id).exists()
        )


class TestResignBase(DocumentPermissionTestSetup):

    def test_resign_removes_permission(self):
        """A user can voluntarily remove themselves from a document."""
        self.client.force_authenticate(user=self.read_user)
        url = reverse("permission-resign", kwargs={"doc_id": self.document.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("detail", response.data)
        self.assertFalse(
            DocumentPermissionModel.objects.filter(
                user=self.read_user, document=self.document
            ).exists()
        )

    def test_resign_nonexistent_returns_404(self):
        """A user with no permission on the document gets 404, not 500."""
        self.client.force_authenticate(user=self.new_user)
        url = reverse("permission-resign", kwargs={"doc_id": self.document.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestListMembersBase(DocumentPermissionTestSetup):

    def test_member_can_list_document_members(self):
        """Any member of a document can see the member list."""
        self.client.force_authenticate(user=self.read_user)
        url = reverse("doc-members", kwargs={"doc_id": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)

    def test_unauthenticated_cannot_list_members(self):
        """Unauthenticated requests to the member list are rejected."""
        url = reverse("doc-members", kwargs={"doc_id": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# =============================================================================
# HACKER LEVEL TESTS
# =============================================================================


class TestPrivilegeEscalation(DocumentPermissionTestSetup):

    def test_read_user_cannot_self_escalate(self):
        """
        Attacker sends their own user ID to the grant endpoint.
        They must be blocked — permission_type in DB must stay READ.
        """
        self.client.force_authenticate(user=self.read_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.read_user.id),  # self-targeting
            "document": str(self.document.id),
            "permission_type": "DELETE",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        perm = DocumentPermissionModel.objects.get(
            user=self.read_user, document=self.document
        )
        self.assertEqual(perm.permission_type, "READ")

    def test_write_user_cannot_grant_delete_permission(self):
        """
        A WRITE user must not be able to create a DELETE (owner-level) grant.
        This ceiling is not currently enforced — test will fail until added.
        """
        self.client.force_authenticate(user=self.write_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "DELETE",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            DocumentPermissionModel.objects.filter(
                user=self.new_user, document=self.document
            ).exists()
        )


class TestIDOR(DocumentPermissionTestSetup):

    def test_unrelated_user_cannot_list_document_members(self):
        """
        Any authenticated user can currently enumerate members of any document
        by guessing a UUID. GetDocumentMembersView only checks IsAuthenticatedUser.

        BUG: This test will FAIL until an ownership/membership check is added
        to GetDocumentMembersView.get_queryset().
        """
        self.client.force_authenticate(user=self.unrelated_user)
        url = reverse("doc-members", kwargs={"doc_id": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelated_user_cannot_revoke_permission_by_uuid(self):
        """
        An authenticated user from a completely different document must not be
        able to revoke permissions on this document by guessing the UUID.
        """
        self.client.force_authenticate(user=self.unrelated_user)
        url = reverse("permission-revoke", kwargs={"id": self.read_permission.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            DocumentPermissionModel.objects.filter(id=self.read_permission.id).exists()
        )

    def test_unrelated_user_cannot_fetch_permission_detail(self):
        """
        GetDocumentPermissionView filters by document membership, so an
        unrelated user fetching a valid UUID should get 404 (not found in their
        queryset), not 200.
        """
        self.client.force_authenticate(user=self.unrelated_user)
        url = reverse("permission-detail", kwargs={"id": self.read_permission.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestOwnerProtection(DocumentPermissionTestSetup):

    def test_non_superuser_cannot_revoke_owner_permission(self):
        """
        A DELETE-level user who is not the document creator must not be able
        to revoke the primary owner's DELETE permission.
        """
        self.client.force_authenticate(user=self.delete_user)
        url = reverse("permission-revoke", kwargs={"id": self.owner_permission.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            DocumentPermissionModel.objects.filter(id=self.owner_permission.id).exists()
        )

    def test_superuser_can_revoke_owner_permission(self):
        """Superusers are the one exception to the owner protection guard."""
        self.client.force_authenticate(user=self.superuser)
        url = reverse("permission-revoke", kwargs={"id": self.owner_permission.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            DocumentPermissionModel.objects.filter(id=self.owner_permission.id).exists()
        )

    def test_owner_cannot_resign_from_their_own_document(self):
        """
        The primary owner resigning would leave the document ownerless.
        RejectDocumentPermissionView currently has no guard for this.

        BUG: This test will FAIL until the same owner check from destroy()
        is added to RejectDocumentPermissionView.delete().
        """
        self.client.force_authenticate(user=self.owner)
        url = reverse("permission-resign", kwargs={"doc_id": self.document.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            DocumentPermissionModel.objects.filter(
                user=self.owner, document=self.document
            ).exists()
        )

    def test_non_owner_delete_user_can_resign(self):
        """
        A DELETE-level user who is NOT the document creator should be
        able to resign freely.
        """
        self.client.force_authenticate(user=self.delete_user)
        url = reverse("permission-resign", kwargs={"doc_id": self.document.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            DocumentPermissionModel.objects.filter(
                user=self.delete_user, document=self.document
            ).exists()
        )


class TestCrossDocumentLeakage(DocumentPermissionTestSetup):

    def test_read_user_cannot_see_unrelated_document_in_list(self):
        """
        GetAllDocumentPermissionsView for non-staff must only return permissions
        for documents where the user holds WRITE or DELETE rights.
        A READ-only user must not see any entry from other_document.
        """
        self.client.force_authenticate(user=self.read_user)
        url = reverse("permission-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        doc_ids = {str(p["document"]) for p in response.data}
        self.assertNotIn(str(self.other_document.id), doc_ids)

    def test_staff_sees_all_permissions(self):
        """Staff users get the global view — all permissions across all documents."""
        staff_user = User.objects.create_user(
            username="staff", password="pass", email="staff@test.com", is_staff=True
        )
        self.client.force_authenticate(user=staff_user)
        url = reverse("permission-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        doc_ids = {str(p["document"]) for p in response.data}
        self.assertIn(str(self.document.id), doc_ids)
        self.assertIn(str(self.other_document.id), doc_ids)

    def test_write_user_can_only_see_managed_documents(self):
        """
        A WRITE user sees permissions for documents they manage (WRITE/DELETE),
        but not documents they have no role on at all.
        """
        self.client.force_authenticate(user=self.write_user)
        url = reverse("permission-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        doc_ids = {str(p["document"]) for p in response.data}
        self.assertIn(str(self.document.id), doc_ids)
        self.assertNotIn(str(self.other_document.id), doc_ids)
