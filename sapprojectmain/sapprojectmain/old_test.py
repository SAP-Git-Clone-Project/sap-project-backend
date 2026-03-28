import difflib

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.test import APIRequestFactory
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from roles.models import RolesModel, UserRolesModel
from documents.models import DocumentModel
from reviews.models import Reviews, ReviewStatus
from versions.models import Versions
import uuid
import hashlib
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from users.serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
)

from roles.serializers import UserRoleSerializer;
from documents.serializers import DocumentSerializer;

User = get_user_model()

'''

# ROLE TESTS

class RolesModelTest(TestCase):
    def test_create_role(self):
        role = RolesModel.objects.create(role_name="author")
        self.assertEqual(role.role_name, "author")

    def test_role_unique(self):
        RolesModel.objects.create(role_name="author")
        with self.assertRaises(Exception):
            RolesModel.objects.create(role_name="author")


class UserRolesModelTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create admin user
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="StrongPass1!",
            first_name="Admin",
            last_name="User",
        )

        # Create administrator role
        self.admin_role = RolesModel.objects.create(role_name="administrator")

        # Assign role to admin user
        UserRolesModel.objects.create(
            user=self.admin,
            role=self.admin_role,
            assigned_by=self.admin,
        )

        # Normal user
        self.user = User.objects.create_user(
            username="user",
            email="user@test.com",
            password="StrongPass1!",
            first_name="Normal",
            last_name="User",
        )

        self.role = RolesModel.objects.create(role_name="author")

        self.client.force_authenticate(user=self.admin)
            
    def test_assign_role(self):
        assignment = UserRolesModel.objects.create(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
        )

        self.assertEqual(assignment.user, self.user)
        self.assertEqual(assignment.role, self.role)

    def test_unique_user_role_constraint(self):
        UserRolesModel.objects.create(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
        )

        with self.assertRaises(Exception):
            UserRolesModel.objects.create(
                user=self.user,
                role=self.role,
                assigned_by=self.admin,
            )

class UserRoleSerializerTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.admin = User.objects.create_user(
            email="admin@test.com", username="admin", first_name="Test", last_name="Admin", password="StrongPass1!"
        )
        self.user = User.objects.create_user(
            email="user@test.com", username="user", password="StrongPass1!"
        )
        self.role = RolesModel.objects.create(role_name="author")

    def test_assigned_by_is_set_automatically(self):
        request = self.factory.post("/")
        request.user = self.admin

        data = {
            "user": str(self.user.id),
            "role": str(self.role.id),
        }

        serializer = UserRoleSerializer(
            data=data,
            context={"request": request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()

        self.assertEqual(instance.assigned_by, self.admin)

    def test_serializer_invalid_user(self):
        request = self.factory.post("/")
        request.user = self.admin

        data = {
            "user": "invalid-uuid",
            "role": str(self.role.id),
        }

        serializer = UserRoleSerializer(
            data=data,
            context={"request": request},
        )

        self.assertFalse(serializer.is_valid())

class UserRoleAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Admin user
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="StrongPass1!"
        )

        # Normal user
        self.user = User.objects.create_user(
            username="user",
            email="user@test.com",
            password="StrongPass1!"
        )

        # Roles
        self.admin_role = RolesModel.objects.create(role_name="administrator")
        self.author_role = RolesModel.objects.create(role_name="author")

        # Assign admin role to admin
        UserRolesModel.objects.create(
            user=self.admin,
            role=self.admin_role,
            assigned_by=self.admin
        )

        self.client.force_authenticate(user=self.admin)

    def test_list_assignments(self):
        # Assign author role to normal user
        UserRolesModel.objects.create(
            user=self.user,
            role=self.author_role,
            assigned_by=self.admin
        )
        response = self.client.get("/api/roles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)  # admin + user

    def test_assign_role_success(self):
        data = {"user": str(self.user.id), "role": str(self.author_role.id)}
        response = self.client.post("/api/roles/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            UserRolesModel.objects.filter(user=self.user, role=self.author_role).exists()
        )

    def test_assign_role_duplicate(self):
        UserRolesModel.objects.create(user=self.user, role=self.author_role, assigned_by=self.admin)
        data = {"user": str(self.user.id), "role": str(self.author_role.id)}
        response = self.client.post("/api/roles/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(
            "error" in response.data or "non_field_errors" in response.data
        )

    def test_get_single_assignment(self):
        assignment = UserRolesModel.objects.create(user=self.user, role=self.author_role, assigned_by=self.admin)
        response = self.client.get(f"/api/roles/{assignment.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(assignment.id))

    def test_delete_assignment(self):
        assignment = UserRolesModel.objects.create(user=self.user, role=self.author_role, assigned_by=self.admin)
        response = self.client.delete(f"/api/roles/{assignment.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserRolesModel.objects.filter(id=assignment.id).exists())

    # ---------- Logic-specific tests ----------

    def test_non_admin_cannot_assign_role(self):
        self.client.force_authenticate(user=self.user)
        data = {"user": str(self.user.id), "role": str(self.author_role.id)}
        response = self.client.post("/api/roles/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_admin_cannot_list_roles(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/roles/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_nonexistent_assignment(self):
        fake_id = uuid.uuid4()
        response = self.client.delete(f"/api/roles/{fake_id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_only_admin_can_assign_admin_role(self):
        self.client.force_authenticate(user=self.user)
        data = {"user": str(self.user.id), "role": str(self.admin_role.id)}
        response = self.client.post("/api/roles/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_role_to_self(self):
        # Even admin assigning to self (should succeed in your logic)
        data = {"user": str(self.admin.id), "role": str(self.author_role.id)}
        response = self.client.post("/api/roles/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(UserRolesModel.objects.filter(user=self.admin, role=self.author_role).exists())

# USER TESTS

class RegisterSerializerTest(TestCase):
    def test_register_success(self):
        data = {
            "username": "testuser",
            "first_name": "John",
            "last_name": "Doe",
            "email": "test@example.com",
            "password": "StrongPass1!",
        }

        serializer = RegisterSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        user = serializer.save()
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("StrongPass1!"))

    def test_register_duplicate_email(self):
        User.objects.create_user(
            username="existing",
            email="test@example.com",
            first_name="Test",
            last_name="User",
            password="StrongPass1!"
        )

        data = {
            "username": "newuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "StrongPass1!",
        }

        serializer = RegisterSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_register_invalid_username(self):
        data = {
            "username": "123invalid",
            "email": "test2@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "StrongPass1!",
        }

        serializer = RegisterSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("username", serializer.errors)

    def test_register_weak_password(self):
        data = {
            "username": "validuser",
            "email": "test3@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "weak",
        }

        serializer = RegisterSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)


class LoginSerializerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="login@example.com",
            username="loginexampleusername",
            first_name="Pesho",
            last_name="Ivanov",
            password="StrongPass1!",
            # is_active=True,
            # is_enabled=True,
        )

    def test_login_success(self):
        data = {
            "email": "login@example.com",
            "password": "StrongPass1!",
        }

        serializer = LoginSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["user"], self.user)

    def test_login_invalid_credentials(self):
        data = {
            "email": "login@example.com",
            "password": "WrongPass1!",
        }

        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()

        data = {
            "email": "login@example.com",
            "password": "StrongPass1!",
        }

        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

    def test_login_disabled_user(self):
        self.user.is_enabled = False
        self.user.save()

        data = {
            "email": "login@example.com",
            "password": "StrongPass1!",
        }

        serializer = LoginSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)


class UserSerializerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="existinguser",
            email="existing@example.com",
            password="StrongPass1!",
        )

    def test_update_user_success(self):
        serializer = UserSerializer(
            instance=self.user,
            data={"first_name": "Updated"},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.first_name, "Updated")

    def test_update_email_duplicate(self):
        User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="StrongPass1!",
        )

        serializer = UserSerializer(
            instance=self.user,
            data={"email": "other@example.com"},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_update_username_duplicate(self):
        User.objects.create_user(
            username="takenusername",
            email="unique@example.com",
            password="StrongPass1!",
        )

        serializer = UserSerializer(
            instance=self.user,
            data={"username": "takenusername"},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("username", serializer.errors)

    def test_update_password(self):
        serializer = UserSerializer(
            instance=self.user,
            data={"password": "NewStrongPass1!"},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertTrue(user.check_password("NewStrongPass1!"))

    def test_create_user(self):
        data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": "StrongPass1!",
            "first_name": "Todor",
            "last_name": "Petrov",
        }

        serializer = UserSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        user = serializer.save()
        self.assertTrue(user.check_password("StrongPass1!"))

# DOCUMENTS TESTS

class DocumentAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create admin user
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="StrongPass1!",
            first_name="Admin",
            last_name="User",
        )

        # Create/get administrator role
        self.admin_role, _ = RolesModel.objects.get_or_create(
            role_name="administrator"
        )

        # Assign role to admin user
        UserRolesModel.objects.create(
            user=self.admin,
            role=self.admin_role,
            assigned_by=self.admin,
        )

        # Normal user
        self.user = User.objects.create_user(
            username="user",
            email="user@test.com",
            password="StrongPass1!",
            first_name="Test",
            last_name="User",
        )

        self.role, _ = RolesModel.objects.get_or_create(role_name="author")

        self.client.force_authenticate(user=self.admin)

        self.document = DocumentModel.objects.create_document(
            created_by=self.admin,
            title="Admin Doc"
        )

    # ---------------------
    # CREATE DOCUMENT
    # ---------------------
    def test_create_document_success(self):
        data = {"title": "New Document"}
        response = self.client.post("/api/documents/create/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["document"]["title"], "New Document")
        self.assertTrue(DocumentModel.objects.filter(title="New Document").exists())

    def test_create_document_empty_title(self):
        data = {"title": "   "}
        response = self.client.post("/api/documents/create/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response.data)

    def test_create_document_duplicate_title(self):
        data = {"title": "Admin Doc"}
        response = self.client.post("/api/documents/create/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response.data)

    # ---------------------
    # RETRIEVE DOCUMENT
    # ---------------------
    def test_get_document_success(self):
        response = self.client.get(f"/api/documents/{self.document.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["document"]["title"], self.document.title)

    def test_get_document_not_found(self):
        import uuid
        response = self.client.get(f"/api/documents/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ---------------------
    # UPDATE DOCUMENT
    # ---------------------
    def test_update_document_success(self):
        data = {"title": "Updated Title"}
        response = self.client.put(
            f"/api/documents/{self.document.id}/update/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["document"]["title"], "Updated Title")
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "Updated Title")

    def test_update_document_duplicate_title(self):
        # Create another document
        DocumentModel.objects.create_document(created_by=self.admin, title="Other Doc")

        data = {"title": "Other Doc"}
        response = self.client.put(
            f"/api/documents/{self.document.id}/update/", data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response.data)

    # ---------------------
    # DELETE DOCUMENT
    # ---------------------
    def test_delete_document_success(self):
        response = self.client.delete(f"/api/documents/{self.document.id}/delete/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Document deleted successfully")

        # Document should be soft deleted
        self.document.refresh_from_db()
        self.assertTrue(self.document.is_deleted)

    # ---------------------
    # GET ALL DOCUMENTS
    # ---------------------
    def test_get_all_documents(self):
        # Create another document
        DocumentModel.objects.create_document(created_by=self.admin, title="Second Doc")

        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only non-deleted documents should be returned
        self.assertEqual(len(response.data), 2)
        titles = [doc["title"] for doc in response.data]
        self.assertIn("Admin Doc", titles)
        self.assertIn("Second Doc", titles)

    def test_get_all_documents_excludes_deleted(self):
        # Soft delete original document
        self.document.delete()

        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)  # no active documents remain

    # ---------------------
    # PERMISSION CHECKS
    # ---------------------
    def test_non_authenticated_user_cannot_create(self):
        self.client.force_authenticate(user=None)
        data = {"title": "Anonymous Doc"}
        response = self.client.post("/api/documents/create/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_cannot_delete_if_permission_restricted(self):
        # Assuming your HasDocumentDeletePermission blocks normal users
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/documents/{self.document.id}/delete/")
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED])

# REVIEW TESTS

class ReviewsAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create admin user
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="StrongPass1!",
            first_name="Admin",
            last_name="User",
        )

        # Create/get administrator role
        self.admin_role, _ = RolesModel.objects.get_or_create(
            role_name="administrator"
        )

        # Assign role to admin user
        UserRolesModel.objects.create(
            user=self.admin,
            role=self.admin_role,
            assigned_by=self.admin,
        )

        # Normal user
        self.user = User.objects.create_user(
            username="user",
            email="user@test.com",
            password="StrongPass1!",
            first_name="Test",
            last_name="User",
        )

        self.role, _ = RolesModel.objects.get_or_create(role_name="author")

        self.client.force_authenticate(user=self.admin)

        self.document = DocumentModel.objects.create_document(
            created_by=self.admin,
            title="Admin Doc"
        )

        self.document2 = DocumentModel.objects.create_document(
            created_by=self.admin,
            title="New Doc"
        )

        # Create users
        self.reviewer = User.objects.create_user(
            username="reviewer", email="rev@test.com", password="StrongPass1!"
        )
        self.author = User.objects.create_user(
            username="author", email="author@test.com", password="StrongPass1!"
        )

        # Create a document version (mock)
        # Previous approved versions
        self.version1 = Versions.objects.create(
            document=self.document,
            version_number=1,
            content="Version 1 content",
            status="approved",
            is_active=False
        )
        self.version2 = Versions.objects.create(
            document=self.document,
            version_number=2,
            content="Version 2 content",
            status="approved",
            is_active=False
        )

        # Pending version to review
        self.version3 = Versions.objects.create(
            document=self.document,
            version_number=3,  # will be reassigned if logic counts only approved
            content="Version 3 content",
            status="pending_approval",
            is_active=False
        )

        # Create a pending review
        self.review = Reviews.objects.create(
            reviewer=self.reviewer,
            version=self.version3,
        )

        # Authenticate as reviewer
        self.client.force_authenticate(user=self.reviewer)

    def test_get_review_detail(self):
        url = f"/api/reviews/{self.review.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.review.id))

    def test_approve_review(self):
        url = f"/api/reviews/{self.review.id}/"
        data = {"review_status": ReviewStatus.APPROVED, "comments": "Looks good"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Reload from DB
        self.review.refresh_from_db()
        self.version3.refresh_from_db()
        self.version1.refresh_from_db()
        self.version2.refresh_from_db()

        # Review updated
        self.assertEqual(self.review.review_status, ReviewStatus.APPROVED)
        self.assertEqual(self.review.reviewer, self.reviewer)
        self.assertTrue(self.version3.is_active)
        self.assertEqual(self.version3.status, "approved")

        # Auto-incremented version number (should now be 3)
        last_approved = Versions.objects.filter(
            document=self.document, status="approved"
        ).order_by("-version_number").first()
        self.assertEqual(last_approved.version_number, 3)

        # Previous versions should be inactive
        self.assertFalse(self.version1.is_active)
        self.assertFalse(self.version2.is_active)

    def test_reject_review(self):
        url = f"/api/reviews/{self.review.id}/"
        data = {"review_status": ReviewStatus.REJECTED, "comments": "Needs changes"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Reload
        self.review.refresh_from_db()
        self.version3.refresh_from_db()

        self.assertEqual(self.review.review_status, ReviewStatus.REJECTED)
        self.assertEqual(self.version3.status, "rejected")
        self.assertFalse(self.version3.is_active)

    def test_cannot_reapprove_finalized_review(self):
        # First, approve
        self.review.review_status = ReviewStatus.APPROVED
        self.review.save()

        url = f"/api/reviews/{self.review.id}/"
        data = {"review_status": ReviewStatus.REJECTED, "comments": "Trying to override"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "Review already finalized.")

    def test_only_reviewer_can_patch(self):
        # Force authenticate as someone else
        other_user = User.objects.create_user(username="other", email="other@test.com", first_name="Other", last_name="User", password="StrongPass1!")
        self.client.force_authenticate(user=other_user)

        url = f"/api/reviews/{self.review.id}/"
        data = {"review_status": ReviewStatus.APPROVED, "comments": "Trying to approve"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

'''

class VersionsChecksumTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create admin user
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="StrongPass1!",
            first_name="Admin",
            last_name="User",
        )

        # Create/get administrator role
        self.admin_role, _ = RolesModel.objects.get_or_create(
            role_name="administrator"
        )

        # Assign role to admin user
        UserRolesModel.objects.create(
            user=self.admin,
            role=self.admin_role,
            assigned_by=self.admin,
        )

        # Normal user
        self.user = User.objects.create_user(
            username="user",
            email="user@test.com",
            password="StrongPass1!",
            first_name="Test",
            last_name="User",
        )

        self.role, _ = RolesModel.objects.get_or_create(role_name="author")

        self.client.force_authenticate(user=self.admin)

        self.document = DocumentModel.objects.create_document(created_by=self.admin, title="Doc 1")

        # Create users
        self.reviewer = User.objects.create_user(
            username="reviewer", email="rev@test.com", password="StrongPass1!"
        )
        self.author = User.objects.create_user(
            username="author", email="author@test.com", password="StrongPass1!"
        )

    '''
    @patch("versions.views.HasDocumentPermission.has_object_permission", return_value=True)
    def test_version_checksum_matches_file_content(self):
        file_content = b"Hello, this is a test file!"
        file = SimpleUploadedFile("test.txt", file_content, content_type="text/plain")

        url = f"/api/versions/document/{self.document.id}/"
        data = {"content": "Checksum test", "file": file}

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        version_id = response.data["id"]
        version = Versions.objects.get(id=version_id)

        # Compute expected SHA256 checksum
        sha256_hash = hashlib.sha256()
        sha256_hash.update(file_content)
        expected_checksum = sha256_hash.hexdigest()

        self.assertEqual(version.checksum, expected_checksum)

    def test_diff(self):
        old_file_content = b"Hello, this is a test file!\nIt has multiple lines.\nEnd."
        old_file = SimpleUploadedFile("old.txt", old_file_content, content_type="text/plain")

        new_file_content = b"Hello, this is a revised test file!\nIt has multiple lines.\nEnd."
        new_file = SimpleUploadedFile("new.txt", new_file_content, content_type="text/plain")

        old_lines = old_file.read().decode("utf-8").splitlines()
        new_lines = new_file.read().decode("utf-8").splitlines()

        old_file.seek(0)
        new_file.seek(0)

        diff = difflib.unified_diff(old_lines, new_lines, fromfile="old.txt", tofile="new.txt", lineterm="")
        for line in diff:
            print(line)
    '''

class CloudinaryFileFetchTest(TestCase):
    def setUp(self):
        # Create a user and document
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@test.com",
            password="StrongPass1!"
        )
        self.document1 = DocumentModel.objects.create_document(
            created_by=self.user,
            title="Test Doc"
        )
        self.document2 = DocumentModel.objects.create_document(
            created_by=self.user,
            title="Test Doc 2"
        )

        # Suppose you have a version already uploaded to Cloudinary
        # For test purposes, use a public test URL
        self.cloudinary_url1 = "https://res.cloudinary.com/dbgpxmjln/raw/upload/v1774485946/world_xnaov9.java"
        self.cloudinary_url2 = "https://res.cloudinary.com/dbgpxmjln/raw/upload/v1774485946/hello_cmexmn.c"

        self.version1 = Versions.objects.create(
            document=self.document1,
            version_number=1,
            file_path=self.cloudinary_url1,
            status="approved",
            content="Test file content1"
        )

        self.version2 = Versions.objects.create(
            document=self.document2,
            version_number=1,
            file_path=self.cloudinary_url2,
            status="approved",
            content="Test file content2"
        )

    def test_fetch_file_from_cloudinary(self):
        # Fetch the file via requests
        response1 = requests.get(self.version1.file_path)
        self.assertEqual(response1.status_code, 200, "Could not fetch file from Cloudinary")

        response2 = requests.get(self.version2.file_path)
        self.assertEqual(response2.status_code, 200, "Could not fetch file from Cloudinary")

        # The file content in bytes
        file_content1 = response1.content
        self.assertTrue(len(file_content1) > 0, "Fetched file is empty")

        file_content2 = response2.content
        self.assertTrue(len(file_content2) > 0, "Fetched file is empty")

        # Optional: decode and check content
        decoded_content1 = file_content1.decode("utf-8").splitlines()
        #print("File content from Cloudinary:\n", decoded_content1)

        decoded_content2 = file_content2.decode("utf-8").splitlines()
        #print("File content from Cloudinary:\n", decoded_content2)

        diff = difflib.unified_diff(decoded_content1, decoded_content2, fromfile=self.version1.file_path, tofile=self.version2.file_path, lineterm="")
        for line in diff:
            print(line)