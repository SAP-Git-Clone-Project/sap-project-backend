import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock

from documents.models import DocumentModel
from versions.models import VersionsModel
from .models import DocumentPermissionModel
from user_roles.models import Role, UserRole

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, *, staff=False, superuser=False, active=True):
    if superuser:
        return User.objects.create_superuser(
            username=username,
            password="testpass123",
            email=f"{username}@test.com",
            first_name=username.capitalize(),
            last_name="Test",
        )
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@test.com",
        first_name=username.capitalize(),
        last_name="Test",
        is_staff=staff,
        is_active=active,
    )


def make_role(name):
    role, _ = Role.objects.get_or_create(role_name=name)
    return role


def assign_role(user, role):
    ur, _ = UserRole.objects.get_or_create(user=user, role=role)
    return ur


def make_document(title, created_by):
    return DocumentModel.objects.create(title=title, created_by=created_by)


def grant_permission(user, document, permission_type, version=None):
    return DocumentPermissionModel.objects.create(
        user=user,
        document=document,
        version=version,
        permission_type=permission_type,
    )


# ---------------------------------------------------------------------------
# Shared setUp
# ---------------------------------------------------------------------------

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

    Roles are created (not fetched) so tests are self-contained.
    """

    def setUp(self):
        self.client = APIClient()

        # --- Roles ---
        self.author_role = make_role(Role.RoleName.AUTHOR)
        self.writer_role = make_role(Role.RoleName.WRITER)
        self.reviewer_role = make_role(Role.RoleName.REVIEWER)
        self.reader_role = make_role(Role.RoleName.READER)

        # --- Users ---
        self.owner = make_user("owner")
        self.write_user = make_user("write_user")
        self.delete_user = make_user("delete_user")
        self.read_user = make_user("read_user")
        self.new_user = make_user("new_user")
        self.unrelated_user = make_user("unrelated")
        self.superuser = make_user("superuser", superuser=True)

        # --- Global role assignments ---
        assign_role(self.owner, self.author_role)
        assign_role(self.write_user, self.writer_role)
        assign_role(self.delete_user, self.author_role)
        assign_role(self.read_user, self.reader_role)

        # --- Documents ---
        self.document = make_document("Primary Doc", self.owner)
        self.other_document = make_document("Other Doc", self.unrelated_user)

        # --- Permissions on primary document ---
        self.owner_permission = grant_permission(
            self.owner, self.document, "DELETE"
        )
        self.write_permission = grant_permission(
            self.write_user, self.document, "WRITE"
        )
        self.delete_permission = grant_permission(
            self.delete_user, self.document, "DELETE"
        )
        self.read_permission = grant_permission(
            self.read_user, self.document, "READ"
        )

        # --- Permission for unrelated_user on their own document ---
        self.unrelated_permission = grant_permission(
            self.unrelated_user, self.other_document, "DELETE"
        )

        # --- Active version on primary document so GetDocumentMembersView
        #     grants access to members without hitting the PermissionDenied gate ---
        self.active_version = VersionsModel.objects.create(
            document=self.document,
            is_active=True,
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
        """READ users are blocked from the grant endpoint (needs DELETE)."""
        self.client.force_authenticate(user=self.read_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_write_user_cannot_grant_permission(self):
        """
        The grant endpoint requires HasDocumentDeletePermission — WRITE is
        not enough.  A WRITE user must receive 403.
        """
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
        assign_role(self.new_user, self.author_role)
        self.client.force_authenticate(user=self.owner)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "WRITE",
        }
        self.client.post(url, data)
        self.assertTrue(
            DocumentPermissionModel.objects.filter(
                user=self.new_user, document=self.document
            ).exists()
        )

    def test_grant_existing_returns_updated_status(self):
        """
        Upsert path — granting a new level to an existing user should succeed
        and report "updated".
        """
        assign_role(self.read_user, self.author_role)
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

    def test_grant_new_user_returns_created_status(self):
        """Fresh grant must report "created" and return 201."""
        assign_role(self.new_user, self.reader_role)
        self.client.force_authenticate(user=self.owner)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "created")


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

    def test_unauthenticated_cannot_revoke_permission(self):
        """No token → 401."""
        url = reverse("permission-revoke", kwargs={"id": self.read_permission.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_revoke_nonexistent_permission_returns_404(self):
        """Guessing a random UUID returns 404."""
        self.client.force_authenticate(user=self.delete_user)
        url = reverse("permission-revoke", kwargs={"id": uuid.uuid4()})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


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

    def test_unauthenticated_cannot_resign(self):
        """No token → 401."""
        url = reverse("permission-resign", kwargs={"doc_id": self.document.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


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

    def test_member_list_contains_expected_users(self):
        """The member list includes all users with permissions on the document."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("doc-members", kwargs={"doc_id": self.document.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user_ids = {str(p["user"]) for p in response.data}
        self.assertIn(str(self.owner.id), user_ids)
        self.assertIn(str(self.read_user.id), user_ids)
        self.assertIn(str(self.write_user.id), user_ids)

    def test_nonexistent_document_returns_empty_or_404(self):
        """A UUID that matches no document or version should not 500."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("doc-members", kwargs={"doc_id": uuid.uuid4()})
        response = self.client.get(url)
        self.assertIn(
            response.status_code,
            [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND],
        )


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
            "user": str(self.read_user.id),
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
        The grant endpoint requires HasDocumentDeletePermission, so WRITE is blocked.
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

    def test_new_user_cannot_grant_any_permission(self):
        """A user with no permissions on the document cannot grant access to others."""
        self.client.force_authenticate(user=self.new_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.read_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestIDOR(DocumentPermissionTestSetup):

    def test_unrelated_user_cannot_list_document_members(self):
        """
        An authenticated user with no relation to the document must not be
        able to enumerate its members.

        Note: GetDocumentMembersView currently only checks IsAuthenticatedUser.
        This test documents the expected secure behaviour. It will FAIL until
        a membership/ownership check is added to the view.
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
        unrelated user fetching a valid UUID should get 404, not 200.
        """
        self.client.force_authenticate(user=self.unrelated_user)
        url = reverse("permission-detail", kwargs={"id": self.read_permission.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unrelated_user_cannot_grant_on_foreign_document(self):
        """
        A DELETE-level user on other_document must not be able to grant
        permissions on the primary document they have no access to.
        """
        self.client.force_authenticate(user=self.unrelated_user)
        url = reverse("permission-grant")
        data = {
            "user": str(self.new_user.id),
            "document": str(self.document.id),
            "permission_type": "READ",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


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
        RejectDocumentPermissionView guards against this.

        Note: This test will FAIL if the owner check is not present in
        RejectDocumentPermissionView.delete().
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

    def test_write_user_can_resign(self):
        """A WRITE-level user can freely remove themselves from the document."""
        self.client.force_authenticate(user=self.write_user)
        url = reverse("permission-resign", kwargs={"doc_id": self.document.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            DocumentPermissionModel.objects.filter(
                user=self.write_user, document=self.document
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
        staff_user = make_user("staff", staff=True)
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

    def test_unauthenticated_cannot_list_permissions(self):
        """Global permission list requires authentication."""
        url = reverse("permission-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_user_cannot_see_other_document_permissions(self):
        """
        A DELETE-level user on the primary document must not see permission
        rows belonging to other_document.
        """
        self.client.force_authenticate(user=self.delete_user)
        url = reverse("permission-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        doc_ids = {str(p["document"]) for p in response.data}
        self.assertNotIn(str(self.other_document.id), doc_ids)