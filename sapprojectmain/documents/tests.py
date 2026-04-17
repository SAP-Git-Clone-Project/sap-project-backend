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
from user_roles.models import Role, UserRole
from versions.models import VersionsModel, VersionStatus

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, email, *, superuser=False, staff=False):
    """
    Creates a user with all required fields.

    IMPORTANT: DocumentListCreateView.post blocks is_staff users with 403 before
    the superuser bypass fires.  create_superuser() sets is_staff=True via
    setdefault(), so the owner is built with create_user(..., is_superuser=True,
    is_staff=False) instead to avoid that guard.
    """
    return User.objects.create_user(
        username=username,
        email=email,
        password="pass123",
        first_name="Test",
        last_name="User",
        is_superuser=superuser,
        is_staff=staff,
    )


def assign_role(user, role_name):
    role, _ = Role.objects.get_or_create(role_name=role_name)
    UserRole.objects.get_or_create(user=user, role=role)


def make_document(created_by, title="Test Doc"):
    """
    Creates a document via the manager (which also auto-grants DELETE to the
    owner). Use this everywhere instead of DocumentModel.objects.create() to
    avoid bypassing that logic.
    """
    return DocumentModel.objects.create_document(created_by=created_by, title=title)


def make_active_version(document, created_by):
    """
    Creates a version that is genuinely active.

    VersionsModel.save() enforces: is_active=True is only kept when
    status == APPROVED.  Passing any other status causes save() to silently
    flip is_active back to False, which breaks every test that depends on an
    active version existing (deletion workflow, visibility, etc.).
    """
    return VersionsModel.objects.create(
        document=document,
        version_number=1,
        status=VersionStatus.APPROVED,
        is_active=True,
        created_by=created_by,
    )


def auth(client, user):
    """Authenticate the test client as the given user via JWT."""
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class BaseTestCase(APITestCase):
    """
    Provides three pre-authenticated users:

    - self.owner     superuser, authenticated by default. Bypasses role and
                     permission guards so CRUD tests stay focused on behaviour,
                     not setup.
    - self.other     plain user with AUTHOR global role (can create documents).
    - self.reviewer  plain user, used for approval-workflow tests.
    """

    def setUp(self):
        self.owner = make_user("owner", "owner@test.com", superuser=True)
        self.other = make_user("other", "other@test.com")
        self.reviewer = make_user("reviewer", "reviewer@test.com")

        # Give other and reviewer the AUTHOR role so they can create documents
        # when needed and pass global-role checks in the views.
        assign_role(self.other, Role.RoleName.AUTHOR)
        assign_role(self.reviewer, Role.RoleName.AUTHOR)

        # Default client is authenticated as the owner (superuser).
        auth(self.client, self.owner)


# =============================================================================
# Document CRUD
# =============================================================================

class DocumentCRUDTests(BaseTestCase):

    def test_create_document(self):
        """Owner (superuser) can create a document."""
        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Test Document"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(DocumentModel.objects.filter(title="Test Document").exists())

    def test_create_document_auto_grants_delete_permission_to_owner(self):
        """The manager must give the creator a DELETE permission automatically."""
        url = reverse("document-list-create")
        self.client.post(url, {"title": "Auto Permission Doc"})

        doc = DocumentModel.objects.get(title="Auto Permission Doc")
        self.assertTrue(
            DocumentPermissionModel.objects.filter(
                user=self.owner, document=doc, permission_type="DELETE"
            ).exists()
        )

    def test_duplicate_title_for_same_user_is_rejected(self):
        """A user cannot create two active documents with the same title."""
        make_document(self.owner, "Unique Doc")

        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Unique Doc"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_title_allowed_for_different_users(self):
        """Two different users may each have a document with the same title."""
        make_document(self.other, "Shared Title")

        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Shared Title"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_empty_title_is_rejected(self):
        """Blank titles must be rejected by the serializer."""
        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "   "})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_documents_list(self):
        """Authenticated users can list their documents."""
        make_document(self.owner, "Doc 1")
        make_document(self.owner, "Doc 2")

        url = reverse("document-list-create")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(response.data["results"][0]["title"] in ("Doc 1", "Doc 2"), True)

    def test_get_document_detail(self):
        """Owner can retrieve a single document by ID."""
        doc = make_document(self.owner, "Detail Doc")

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Detail Doc")

    def test_update_document_title(self):
        """Owner can update the document title via PUT."""
        doc = make_document(self.owner, "Old Title")

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.put(url, {"title": "New Title"})

        doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(doc.title, "New Title")

    def test_update_to_existing_title_rejected(self):
        """Renaming a document to a title the user already owns must fail."""
        make_document(self.owner, "Taken Title")
        doc = make_document(self.owner, "Original Title")

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.put(url, {"title": "Taken Title"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_cannot_list_documents(self):
        """No credentials → 401."""
        self.client.credentials()  # clear auth
        url = reverse("document-list-create")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_staff_cannot_create_documents(self):
        """Staff users are explicitly blocked from creating documents."""
        staff = make_user("staff", "staff@test.com", staff=True)
        auth(self.client, staff)

        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Staff Doc"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_without_author_role_cannot_create_document(self):
        """A regular user without the AUTHOR role must be blocked."""
        plain = make_user("plain", "plain@test.com")
        auth(self.client, plain)

        url = reverse("document-list-create")
        response = self.client.post(url, {"title": "Unauthorised Doc"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_nonexistent_document_returns_404(self):
        """Fetching a random UUID must return 404."""
        import uuid
        url = reverse("document-detail-manage", args=[uuid.uuid4()])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# =============================================================================
# Soft Delete & Restore
# =============================================================================

class DocumentDeleteRestoreTests(BaseTestCase):

    def test_delete_without_active_version_soft_deletes_immediately(self):
        """
        When a document has no active version (and no reviewers), DELETE
        must soft-delete it immediately and return 200.
        """
        doc = make_document(self.owner, "Delete Me")

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.delete(url)

        doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(doc.is_deleted)

    def test_delete_without_reviewers_soft_deletes_immediately(self):
        """
        An active version exists but no APPROVE-level permission rows exist,
        so the document is deleted immediately.
        """
        doc = make_document(self.owner, "No Reviewers")
        make_active_version(doc, self.owner)

        url = reverse("document-detail-manage", args=[doc.id])
        response = self.client.delete(url)

        doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(doc.is_deleted)

    def test_delete_with_active_version_and_reviewer_requires_approval(self):
        """
        When a document has an active version AND at least one reviewer,
        DELETE must start the approval flow and return 202.
        """
        doc = make_document(self.owner, "Needs Approval")
        make_active_version(doc, self.owner)
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
        self.assertIn("request_id", response.data)

    def test_restore_soft_deleted_document(self):
        """Owner can restore a soft-deleted document."""
        doc = make_document(self.owner, "Restore Me")
        doc.delete()

        url = reverse("document-restore", args=[doc.id])
        response = self.client.post(url)

        doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(doc.is_deleted)

    def test_restore_already_active_document_returns_200(self):
        """Restoring a document that is not deleted must return 200 without error."""
        doc = make_document(self.owner, "Already Active")

        url = reverse("document-restore", args=[doc.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_owner_cannot_restore_document(self):
        """A user who does not own the document must receive 403 on restore."""
        doc = make_document(self.owner, "Protected Doc")
        doc.delete()

        auth(self.client, self.other)
        url = reverse("document-restore", args=[doc.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_soft_delete_sets_flag_not_removes_row(self):
        """After soft-delete the row must still exist in the database."""
        doc = make_document(self.owner, "Ghost Doc")
        doc_id = doc.id
        doc.delete()

        self.assertTrue(DocumentModel.objects.filter(pk=doc_id).exists())

    def test_deleted_document_excluded_from_active_queryset(self):
        """active_documents() must not return soft-deleted rows."""
        doc = make_document(self.owner, "Excluded Doc")
        doc.delete()

        active_ids = DocumentModel.objects.active_documents().values_list("id", flat=True)
        self.assertNotIn(doc.id, active_ids)


# =============================================================================
# Visibility & Permissions
# =============================================================================

class DocumentVisibilityTests(BaseTestCase):

    def test_owner_sees_own_document_in_list(self):
        """The document creator must see their document in the list response."""
        make_document(self.owner, "My Doc")

        url = reverse("document-list-create")
        response = self.client.get(url)

        titles = [d["title"] for d in response.data["results"]]
        self.assertIn("My Doc", titles)

    def test_user_sees_document_shared_with_them(self):
        """A document explicitly shared with a user must appear in their list."""
        doc = make_document(self.owner, "Shared Doc")
        DocumentPermissionModel.objects.create(
            user=self.other, document=doc, permission_type="READ"
        )

        auth(self.client, self.other)
        url = reverse("document-list-create")
        response = self.client.get(url)

        titles = [d["title"] for d in response.data["results"]]
        self.assertIn("Shared Doc", titles)

    def test_user_sees_document_with_active_version(self):
        """
        Any authenticated user can see a document that has an active version,
        even without an explicit permission row, because visible_documents()
        annotates has_active_version=True for such documents.
        """
        doc = make_document(self.owner, "Public Active Doc")
        make_active_version(doc, self.owner)

        plain = make_user("viewer", "viewer@test.com")
        auth(self.client, plain)
        url = reverse("document-list-create")
        response = self.client.get(url)

        titles = [d["title"] for d in response.data["results"]]
        self.assertIn("Public Active Doc", titles)

    def test_unshared_document_hidden_from_other_user(self):
        """A document with no active version and no shared permission must not
        appear in another user's list."""
        make_document(self.owner, "Private Doc")

        auth(self.client, self.other)
        url = reverse("document-list-create")
        response = self.client.get(url)

        titles = [d["title"] for d in response.data["results"]]
        self.assertNotIn("Private Doc", titles)

    def test_superuser_sees_all_documents(self):
        """Superusers must see all documents including those they did not create."""
        make_document(self.other, "Other User Doc")

        url = reverse("document-list-create")
        response = self.client.get(url)  # authenticated as owner (superuser)

        titles = [d["title"] for d in response.data["results"]]
        self.assertIn("Other User Doc", titles)

    def test_owner_can_still_see_their_soft_deleted_document(self):
        """
        The list view includes soft-deleted docs for their creator.
        """
        doc = make_document(self.owner, "Deleted But Mine")
        doc.delete()

        url = reverse("document-list-create")
        response = self.client.get(url)

        titles = [d["title"] for d in response.data["results"]]
        self.assertIn("Deleted But Mine", titles)


# =============================================================================
# Deletion Approval Workflow
# =============================================================================

class DocumentDeletionWorkflowTests(BaseTestCase):
    """
    Full approval workflow: owner requests deletion → reviewer approves/rejects.
    """

    def setUp(self):
        super().setUp()
        self.doc = make_document(self.owner, "Workflow Doc")
        make_active_version(self.doc, self.owner)

        # reviewer gets APPROVE permission so they appear in the reviewer list
        DocumentPermissionModel.objects.create(
            user=self.reviewer,
            document=self.doc,
            permission_type="APPROVE",
            version=None,
        )

    def test_request_delete_creates_deletion_request_and_decisions(self):
        """POST to request-delete must create one DeletionRequest and one
        Decision row (one per reviewer)."""
        url = reverse("document-request-delete", args=[self.doc.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(
            DocumentDeletionRequestModel.objects.filter(document=self.doc).count(), 1
        )
        self.assertEqual(
            DocumentDeletionDecisionModel.objects.filter(document=self.doc).count(), 1
        )

    def test_request_delete_response_lists_reviewers(self):
        """The 202 response body must include the reviewer's username."""
        url = reverse("document-request-delete", args=[self.doc.id])
        response = self.client.post(url)

        self.assertIn("reviewers", response.data)
        self.assertIn(self.reviewer.username, response.data["reviewers"])

    def test_second_deletion_request_resets_previous_decisions(self):
        """Re-requesting deletion must wipe old decision rows and start fresh."""
        url = reverse("document-request-delete", args=[self.doc.id])
        self.client.post(url)

        # Simulate a partial vote
        DocumentDeletionDecisionModel.objects.filter(document=self.doc).update(
            decision="REJECTED"
        )

        self.client.post(url)  # second request
        decisions = DocumentDeletionDecisionModel.objects.filter(document=self.doc)
        self.assertTrue(all(d.decision == "PENDING" for d in decisions))

    def test_reviewer_approval_soft_deletes_document(self):
        """Unanimous approval must soft-delete the document."""
        self.client.post(reverse("document-request-delete", args=[self.doc.id]))

        auth(self.client, self.reviewer)
        url = reverse("document-deletion-decision", args=[self.doc.id])
        response = self.client.post(url, {"decision": "APPROVED"})

        self.doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(self.doc.is_deleted)

    def test_reviewer_rejection_leaves_document_intact(self):
        """Any rejection must keep the document alive and mark request REJECTED."""
        self.client.post(reverse("document-request-delete", args=[self.doc.id]))

        auth(self.client, self.reviewer)
        url = reverse("document-deletion-decision", args=[self.doc.id])
        response = self.client.post(url, {"decision": "REJECTED"})

        self.doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.doc.is_deleted)

        deletion_request = DocumentDeletionRequestModel.objects.filter(
            document=self.doc
        ).first()
        self.assertIsNotNone(deletion_request, "DeletionRequest was not created")
        self.assertEqual(deletion_request.status, "REJECTED")

    def test_partial_approval_does_not_delete(self):
        """With two reviewers, one approval must not trigger deletion."""
        second_reviewer = make_user("reviewer2", "reviewer2@test.com")
        # second_reviewer needs an APPROVE permission on the document.
        # version=None so initiate_deletion_with_notifications picks them up
        # (it filters version__isnull=True).
        perm, created = DocumentPermissionModel.objects.get_or_create(
            user=second_reviewer,
            document=self.doc,
            version=None,
            defaults={"permission_type": "APPROVE"},
        )
        if not created:
            perm.permission_type = "APPROVE"
            perm.save(update_fields=["permission_type"])

        # Sanity check: both reviewers must be visible before the request
        approve_count = DocumentPermissionModel.objects.filter(
            document=self.doc, permission_type="APPROVE", version__isnull=True
        ).count()
        self.assertEqual(approve_count, 2, "Expected 2 APPROVE permissions before request-delete")

        self.client.post(reverse("document-request-delete", args=[self.doc.id]))

        # Sanity check: both decision rows must have been created
        decision_count = DocumentDeletionDecisionModel.objects.filter(
            document=self.doc
        ).count()
        self.assertEqual(decision_count, 2, "Expected 2 decision rows after request-delete")

        auth(self.client, self.reviewer)
        url = reverse("document-deletion-decision", args=[self.doc.id])
        response = self.client.post(url, {"decision": "APPROVED"})

        self.doc.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.doc.is_deleted)
        self.assertIn("waiting", response.data["detail"].lower())

    def test_invalid_decision_value_returns_400(self):
        """Sending a decision other than APPROVED/REJECTED must return 400."""
        self.client.post(reverse("document-request-delete", args=[self.doc.id]))

        auth(self.client, self.reviewer)
        url = reverse("document-deletion-decision", args=[self.doc.id])
        response = self.client.post(url, {"decision": "MAYBE"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deletion_decision_on_nonexistent_document_returns_404(self):
        """Decision endpoint must return 404 for unknown document IDs."""
        import uuid
        auth(self.client, self.reviewer)
        url = reverse("document-deletion-decision", args=[uuid.uuid4()])
        response = self.client.post(url, {"decision": "APPROVED"})

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)