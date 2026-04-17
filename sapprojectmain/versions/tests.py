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
        # Requirement: email, username, password, first_name, last_name
        self.user = User.objects.create_user(
            username="editor_bob",
            email="bob@example.com",
            first_name="Bob",
            last_name="Editor",
            password="securepassword123"
        )
        
        self.document = DocumentModel.objects.create_document(
            created_by=self.user,
            title="Technical Specification"
        )
        
        # Initial version
        self.v1 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            version_number=1,
            content="Initial Content",
            status=VersionStatus.APPROVED,
            is_active=True
        )

        self.client.force_authenticate(user=self.user)
        self.list_url = reverse('document-versions', kwargs={'id': self.document.id})
        self.detail_url = reverse('version-detail', kwargs={'pk': self.v1.id})

class TestVersionHacker(VersionBaseTestCase):

    def test_immutable_approved_version(self):
        """Hacker Level: Ensure a version marked 'APPROVED' cannot be modified via PATCH."""
        payload = {"content": "Malicious Modification"}
        response = self.client.patch(self.detail_url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], "Finalized versions are immutable.")
        
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.content, "Initial Content")

    def test_unauthorized_status_escalation(self):
        """Security: Regular users cannot bypass review by PATCHing status to APPROVED."""
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            status=VersionStatus.DRAFT
        )
        url = reverse('version-detail', kwargs={'pk': v2.id})
        
        # User tries to approve their own work
        response = self.client.patch(url, {"status": VersionStatus.APPROVED})
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        v2.refresh_from_db()
        self.assertEqual(v2.status, VersionStatus.DRAFT)

    def test_cross_document_leak(self):
        """Security: Ensure User B cannot view version list of User A's private document."""
        hacker = User.objects.create_user(
            username="hacker", email="h@ex.com", 
            first_name="H", last_name="K", password="p"
        )
        self.client.force_authenticate(user=hacker)

        response = self.client.get(self.list_url)
        # Should return 404 (or 403) because get_object_or_404 filters by user access
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

class TestVersionLogic(VersionBaseTestCase):

    @patch('cloudinary.uploader.upload')
    def test_auto_increment_and_parent_chaining(self, mock_upload):
        """Base Level: New versions should auto-increment and link to the previous active version."""
        # 1. Setup Mock
        mock_upload.return_value = {'secure_url': 'http://cloud.com/v2.pdf'}
        
        # 2. Prepare File (ensure extension is in ALLOWED_EXTENSIONS)
        file_data = SimpleUploadedFile(
            "spec_v2.txt", 
            b"Updated content", 
            content_type="text/plain"
        )
        
        # 3. Payload must include 'document' because the Serializer 
        # is initialized with request.data in your View's POST method.
        payload = {
            "document": self.document.id,
            "file": file_data,
            "content": "V2 content"
        }

        # 4. Use 'multipart' format for file uploads
        response = self.client.post(self.list_url, payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        v2 = VersionsModel.objects.get(version_number=2)
        self.assertEqual(v2.parent_version, self.v1)
        self.assertEqual(v2.status, VersionStatus.PENDING)

    def test_active_singleton_enforcement(self):
        """Integrity: Marking V2 as active must deactivate V1."""
        # V2 is created and approved
        v2 = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            status=VersionStatus.APPROVED,
            is_active=True
        )
        
        self.v1.refresh_from_db()
        self.assertTrue(v2.is_active)
        self.assertFalse(self.v1.is_active)

class TestVersionFiles(VersionBaseTestCase):

    def test_file_type_whitelist(self):
        """Boundary: Reject dangerous or unsupported file extensions."""
        bad_file = SimpleUploadedFile("exploit.exe", b"binary_data")
        response = self.client.post(self.list_url, {"file": bad_file})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not allowed", response.data['error'])

    def test_version_diff_binary_block(self):
        """Logic: Ensure diff engine blocks comparison for non-text files."""
        # Create a version with a PDF path
        v_pdf = VersionsModel.objects.create(
            document=self.document,
            created_by=self.user,
            file_path="http://cloudinary.com/doc.pdf",
            content="" # No raw text
        )
        url = reverse('version-diff', kwargs={'pk': v_pdf.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['can_compare'])
        self.assertEqual(response.data['message'], "Direct text comparison not supported for this file type.")

class TestVersionExport(VersionBaseTestCase):

    def test_export_unauthenticated_fails(self):
        """Security: Logged out users get 401."""
        self.client.logout()
        url = reverse('version-export', kwargs={'pk': self.v1.id, 'file_format': 'pdf'})
        
        response = self.client.get(url)
        # IsAuthenticated triggers 401 for anonymous users
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_export_unauthorized_fails(self):
        """Security: Authenticated user with no document access gets 403."""
        # Create a second user who has no link to Bob's document
        stranger = User.objects.create_user(
            username="stranger", 
            email="stranger@ex.com", 
            first_name="No", last_name="Access", password="p"
        )
        self.client.force_authenticate(user=stranger)
        
        url = reverse('version-export', kwargs={'pk': self.v1.id, 'file_format': 'pdf'})
        response = self.client.get(url)
        
        # HasDocumentReadPermission or your internal has_access check triggers 403
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)