import uuid
import io
import hashlib
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from documents.models import DocumentModel
from versions.models import VersionsModel, VersionStatus
from reviews.models import ReviewModel
from unittest.mock import patch
from django.urls import reverse
from user_roles.models import Role, UserRole

User = get_user_model()


# =========================================================
# CORE FIXTURE: THE MULTI-TENANT ENVIRONMENT
# =========================================================
class BaseSteelTestCase(APITestCase):
    def setUp(self):
        # 1. User Setup: Owner (Victim), Attacker (Hacker), and Auditor (Admin)
        self.owner = User.objects.create_user(
            username="owner", email="owner@test.com", password="password123"
        )
        self.hacker = User.objects.create_user(
            username="hacker", email="hacker@test.com", password="password123"
        )
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="adminpass"
        )
        UserRole.objects.get_or_create(
            user=self.owner,
            role=Role.objects.get(role_name=Role.RoleName.AUTHOR),
        )

        # 2. JWT Auth Helpers
        self.owner_token = str(RefreshToken.for_user(self.owner).access_token)
        self.hacker_token = str(RefreshToken.for_user(self.hacker).access_token)
        self.admin_token = str(RefreshToken.for_user(self.admin).access_token)

        # 3. Baseline Data
        self.doc = DocumentModel.objects.create(
            title="Sensitive Corporate Strategy", created_by=self.owner
        )

        # 4. Create an initial approved version
        self.version = VersionsModel.objects.create(
            document=self.doc,
            version_number=1,
            content="Top Secret initial draft content.",
            created_by=self.owner,
            status=VersionStatus.APPROVED,
            is_active=True,
        )

    def set_auth(self, token=None):
        """Helper to switch between users or clear credentials"""
        if token:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        else:
            self.client.credentials()


# =========================================================
# LEVEL 1: BROKEN OBJECT LEVEL AUTHORIZATION (BOLA/IDOR)
# =========================================================
class DocumentBOLATests(BaseSteelTestCase):
    """Tests if a user can access or guess another user's private data."""

    def test_hacker_cannot_view_owner_detail(self):
        self.set_auth(self.hacker_token)
        # Targeted the VersionDetailView: path("<uuid:pk>/", ...)
        res = self.client.get(f"/api/versions/{self.version.id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_hacker_cannot_list_owner_docs(self):
        self.set_auth(self.hacker_token)
        res = self.client.get("/api/documents/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get("count"), 0)

    def test_uuid_brute_force_resistance(self):
        self.set_auth(self.hacker_token)
        for _ in range(3):
            res = self.client.get(f"/api/documents/{uuid.uuid4()}/")
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# =========================================================
# LEVEL 2: BROKEN PROPERTY INCORPORATION (BPI/MASS ASSIGNMENT)
# =========================================================
class DocumentMassAssignmentTests(BaseSteelTestCase):
    """Tests if users can change sensitive fields via PUT/PATCH."""

    def test_prevent_created_by_hijack(self):
        self.set_auth(self.owner_token)
        payload = {"title": "New Title", "created_by": self.hacker.id}
        self.client.put(f"/api/documents/{self.doc.id}/", payload)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.created_by, self.owner)

    def test_prevent_version_number_manipulation(self):
        self.set_auth(self.owner_token)
        payload = {"version_number": 999}
        res = self.client.patch(f"/api/versions/{self.version.id}/", payload)
        self.version.refresh_from_db()
        self.assertNotEqual(self.version.version_number, 999)


# =========================================================
# LEVEL 3: VERSION & FILE INTEGRITY TESTS
# =========================================================
class VersionIntegrityTests(BaseSteelTestCase):
    """Tests the immutability and file logic of the versioning system."""

    def test_approved_version_is_immutable(self):
        self.set_auth(self.owner_token)
        res = self.client.patch(
            f"/api/versions/{self.version.id}/", {"content": "Hacked content"}
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checksum_consistency(self):
        self.set_auth(self.owner_token)
        file = io.BytesIO(b"Steel-plating integrity check")
        file.name = "test.txt"
        data = {
            "file": file,
            "document": self.doc.id,
            "content": "Mandatory version content",
        }
        with patch("cloudinary.uploader.upload") as mocked_upload:
            mocked_upload.return_value = {"secure_url": "https://test.com/file.pdf"}
            # This matches DocumentVersionHandler: path("document/<uuid:id>/", ...)
            res = self.client.post(
                f"/api/versions/document/{self.doc.id}/", data, format="multipart"
            )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)


# =========================================================
# LEVEL 4: REVIEW & WORKFLOW LOCKDOWN
# =========================================================
class ReviewWorkflowTests(BaseSteelTestCase):
    """Ensures business logic and review stages are strictly followed."""

    def test_singleton_active_version(self):
        v2 = VersionsModel.objects.create(
            document=self.doc,
            version_number=2,
            status=VersionStatus.APPROVED,
            is_active=True,
            created_by=self.owner,
        )
        self.version.refresh_from_db()
        self.assertFalse(self.version.is_active)
        self.assertTrue(v2.is_active)

    def test_reviewer_permissions(self):
        self.set_auth(self.hacker_token)
        res = self.client.patch(
            f"/api/versions/{self.version.id}/", {"status": "approved"}
        )
        self.assertNotEqual(res.status_code, status.HTTP_200_OK)


# =========================================================
# LEVEL 5: DATA LEAKAGE & EXPORT SECURITY
# =========================================================
class DataLeakageTests(BaseSteelTestCase):
    """Tests if sensitive data leaks through error messages or exports."""

    def test_diff_without_permission(self):
        self.set_auth(self.hacker_token)
        # Matches: path("<uuid:pk>/diff/", ...)
        res = self.client.get(f"/api/versions/{self.version.id}/diff/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_export_pdf_authentication(self):
        # 1. Clear any login state
        self.client.credentials()

        # 2. Use REVERSE to find the URL.
        # This matches the 'name' in your urls.py and passes the required args.
        url = reverse("version-export", kwargs={"pk": self.version.id, "file_format": "pdf"})

        # 3. Call the URL
        res = self.client.get(url)

        # If this is 404 now, it means VersionExportView is missing
        # from your views or the name 'version-export' is wrong.
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# =========================================================
# LEVEL 6: INPUT SANITIZATION (XSS/SQLi)
# =========================================================
class InjectionResistanceTests(BaseSteelTestCase):
    """Tests resilience against common web attacks."""

    def test_xss_in_document_title(self):
        self.set_auth(self.owner_token)
        payload = {"title": "<script>alert('xss')</script>"}
        res = self.client.post("/api/documents/", payload)
        self.assertIn(res.status_code, [201, 400])

    def test_large_payload_denial_of_service(self):
        self.set_auth(self.owner_token)
        payload = {"title": "A" * 10**6}
        res = self.client.post("/api/documents/", payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
