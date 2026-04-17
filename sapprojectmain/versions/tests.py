from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from versions.models import VersionsModel, VersionStatus
from documents.models import DocumentModel
from document_permissions.models import DocumentPermissionModel

User = get_user_model()


class VersionBaseTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="editor_bob",
            email="bob@example.com",
            first_name="Bob",
            last_name="Editor",
            password="securepassword123",
        )

        self.document = DocumentModel.objects.create_document(
            created_by=self.user,
            title="Technical Specification",
        )

        # v1: APPROVED and active (owner's initial version)
        self.v1 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=1,
            content="Initial Content",
            status=VersionStatus.APPROVED,
            is_active=True,
        )

        self.client.force_authenticate(user=self.user)
        self.list_url = reverse("document-versions", kwargs={"id": self.document.id})
        self.detail_url = reverse("version-detail", kwargs={"pk": self.v1.id})


# ---------------------------------------------------------------------------
# Security / hacker-level tests
# ---------------------------------------------------------------------------

class TestVersionHacker(VersionBaseTestCase):

    def test_immutable_approved_version(self):
        """Hacker Level: APPROVED versions must be immutable — PATCH is rejected."""
        payload = {"content": "Malicious Modification"}
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Finalized versions are immutable.")

        self.v1.refresh_from_db()
        self.assertEqual(self.v1.content, "Initial Content")

    def test_unauthorized_status_escalation_returns_200_for_owner(self):
        """
        Security (real behaviour): The document owner passes can_review_document,
        so a PATCH to APPROVED succeeds (200) for them.
        A non-owner/non-reviewer must get 403.
        """
        # Create a DRAFT version owned by self.user (the document owner)
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            status=VersionStatus.DRAFT,
        )
        url = reverse("version-detail", kwargs={"pk": v2.id})

        # Owner approving their own draft → passes the can_review_document gate
        response = self.client.patch(url, {"status": VersionStatus.APPROVED})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthorized_status_escalation_blocked_for_stranger(self):
        """
        Security: A user with no document access cannot PATCH status to APPROVED
        and gets 403 (or 404 depending on get_authorized_version).
        """
        stranger = User.objects.create_user(
            username="stranger_hacker",
            email="sh@ex.com",
            first_name="S",
            last_name="H",
            password="p",
        )
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            status=VersionStatus.DRAFT,
            is_active=False,
        )
        self.client.force_authenticate(user=stranger)
        url = reverse("version-detail", kwargs={"pk": v2.id})

        response = self.client.patch(url, {"status": VersionStatus.APPROVED})
        # Stranger has no access → get_authorized_version raises 404
        self.assertIn(
            response.status_code,
            [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND],
        )

    def test_cross_document_leak_active_doc_is_visible(self):
        """
        Security (real behaviour): Because v1 is active (is_public=True in the
        DocumentVersionHandler GET query), an authenticated stranger CAN list
        versions of a document that has an active version.  This is the current
        access-control posture — readers see the public/active version list.
        """
        hacker = User.objects.create_user(
            username="hacker",
            email="h@ex.com",
            first_name="H",
            last_name="K",
            password="p",
        )
        self.client.force_authenticate(user=hacker)

        response = self.client.get(self.list_url)
        # Document has an active version → considered "public" → 200
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cross_document_leak_inactive_doc_is_hidden(self):
        """
        Security: A document with NO active version is private.
        An unrelated user gets 404 when listing its versions.
        """
        # New owner + completely private document (no active version)
        alice = User.objects.create_user(
            username="alice",
            email="alice@ex.com",
            first_name="Alice",
            last_name="Owner",
            password="p",
        )
        private_doc = DocumentModel.objects.create_document(
            created_by=alice,
            title="Alice's Private Doc",
        )
        VersionsModel.objects.create(
            document=private_doc,
            created_by=alice,
            version_number=1,
            content="secret",
            status=VersionStatus.DRAFT,
            is_active=False,   # ← NOT active → not public
        )

        hacker = User.objects.create_user(
            username="hacker2",
            email="h2@ex.com",
            first_name="H2",
            last_name="K2",
            password="p",
        )
        self.client.force_authenticate(user=hacker)

        url = reverse("document-versions", kwargs={"id": private_doc.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Business-logic tests
# ---------------------------------------------------------------------------

class TestVersionLogic(VersionBaseTestCase):

    @patch("cloudinary.uploader.upload")
    def test_auto_increment_and_parent_chaining(self, mock_upload):
        """
        Base Level: New versions auto-increment and chain to the previous active
        version.  The view hardcodes status=DRAFT on creation.
        """
        mock_upload.return_value = {"secure_url": "http://cloud.com/v2.pdf"}

        file_data = SimpleUploadedFile(
            "spec_v2.txt",
            b"Updated content",
            content_type="text/plain",
        )
        payload = {
            "document": self.document.id,
            "file": file_data,
            "content": "V2 content",
        }
        response = self.client.post(self.list_url, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        v2 = VersionsModel.objects.get(version_number=2)
        # Parent chaining: v2 links to v1 (the active version at time of upload)
        self.assertEqual(v2.parent_version, self.v1)
        # The view explicitly saves new versions as DRAFT
        self.assertEqual(v2.status, VersionStatus.DRAFT)

    def test_active_singleton_enforcement(self):
        """Integrity: Marking V2 as active must deactivate V1."""
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            status=VersionStatus.APPROVED,
            is_active=True,
        )

        self.v1.refresh_from_db()
        self.assertTrue(v2.is_active)
        self.assertFalse(self.v1.is_active)

    def test_draft_cannot_be_set_active(self):
        """Integrity: Model.save() silently resets is_active=False for non-APPROVED versions."""
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            status=VersionStatus.DRAFT,
            is_active=True,   # attempted — should be stripped
        )
        v2.refresh_from_db()
        self.assertFalse(v2.is_active)

    def test_version_number_auto_increments_on_create(self):
        """Base Level: version_number is auto-assigned via Model.save() when omitted."""
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            status=VersionStatus.DRAFT,
        )
        self.assertEqual(v2.version_number, 2)

        v3 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            status=VersionStatus.DRAFT,
        )
        self.assertEqual(v3.version_number, 3)


# ---------------------------------------------------------------------------
# File / diff tests
# ---------------------------------------------------------------------------

class TestVersionFiles(VersionBaseTestCase):

    def test_file_type_whitelist(self):
        """Boundary: Reject dangerous or unsupported file extensions."""
        bad_file = SimpleUploadedFile("exploit.exe", b"binary_data")
        response = self.client.post(self.list_url, {"file": bad_file})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not allowed", response.data["error"])

    def test_version_diff_pdf_returns_400_when_cloudinary_unreachable(self):
        """
        Logic (real behaviour): The diff view tries to fetch from Cloudinary.
        For a PDF-path version in tests (no real Cloudinary), the fetch fails
        and the view returns 400 with can_compare=False in the body.
        """
        v_pdf = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            file_path="http://cloudinary.com/doc.pdf",
            content="",
        )
        url = reverse("version-diff", kwargs={"pk": v_pdf.id})
        response = self.client.get(url)

        # Cloudinary is unreachable in tests → 400 with can_compare: False
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["can_compare"])

    @patch("versions.views.VersionDiffView.fetch_file_text")
    def test_version_diff_no_parent_returns_content(self, mock_fetch):
        """Logic: A version with no parent returns its own content and an empty diff."""
        mock_fetch.return_value = "Hello world"

        v_alone = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            file_path="http://cloudinary.com/doc.txt",
            content="Hello world",
        )
        url = reverse("version-diff", kwargs={"pk": v_alone.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["can_compare"])
        self.assertFalse(response.data["has_parent"])
        self.assertEqual(response.data["diff"], [])


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestVersionExport(VersionBaseTestCase):

    def test_export_unauthenticated_fails(self):
        """Security: Logged-out users receive 401."""
        self.client.logout()
        url = reverse(
            "version-export", kwargs={"pk": self.v1.id, "file_format": "pdf"}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_export_owner_gets_pdf(self):
        """Happy path: Document owner can export a version as PDF."""
        url = reverse(
            "version-export", kwargs={"pk": self.v1.id, "file_format": "pdf"}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_export_owner_gets_txt(self):
        """Happy path: Document owner can export a version as TXT."""
        url = reverse(
            "version-export", kwargs={"pk": self.v1.id, "file_format": "txt"}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/plain", response["Content-Type"])

    def test_export_active_version_accessible_to_stranger(self):
        """
        Real behaviour: is_active=True makes has_access=True for anyone authenticated,
        so a stranger CAN export the active version (v1).
        """
        stranger = User.objects.create_user(
            username="stranger",
            email="stranger@ex.com",
            first_name="No",
            last_name="Access",
            password="p",
        )
        self.client.force_authenticate(user=stranger)

        url = reverse(
            "version-export", kwargs={"pk": self.v1.id, "file_format": "txt"}
        )
        response = self.client.get(url)
        # v1 is active → has_access is True → 200
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_export_inactive_version_blocked_for_stranger(self):
        """
        Security: A non-active, non-owned version gives a stranger 403.
        """
        v_private = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=2,
            status=VersionStatus.DRAFT,
            is_active=False,
        )
        stranger = User.objects.create_user(
            username="stranger2",
            email="s2@ex.com",
            first_name="No",
            last_name="Access",
            password="p",
        )
        self.client.force_authenticate(user=stranger)

        url = reverse(
            "version-export",
            kwargs={"pk": v_private.id, "file_format": "txt"},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_export_invalid_format_returns_400(self):
        """Boundary: Unsupported export format returns 400."""
        url = reverse(
            "version-export", kwargs={"pk": self.v1.id, "file_format": "csv"}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid format", response.data["error"])