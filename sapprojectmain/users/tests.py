from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from django.urls import reverse
from user_roles.models import Role, UserRole

User = get_user_model()


# NOTE: SETUP
class BaseTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Regular user
        self.user = User.objects.create_user(
            email="user@test.com", username="user", password="StrongPass1"
        )

        # Staff user
        self.staff = User.objects.create_user(
            email="staff@test.com",
            username="staff",
            password="StrongPass1",
            is_staff=True,
        )

        # Superuser
        self.superuser = User.objects.create_superuser(
            email="admin@test.com", username="admin", password="StrongPass1"
        )

    def auth(self, user):
        res = self.client.post(
            reverse("login"), {"email": user.email, "password": "StrongPass1"}
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")


# NOTE: TEST BASIC FUNCTIONALITY
class TestAuthFlow(BaseTestCase):
    def test_register(self):
        res = self.client.post(
            reverse("register"),
            {
                "email": "new@test.com",
                "username": "newuser",
                "first_name": "A",
                "last_name": "B",
                "password": "StrongPass1",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_register_assigns_default_reader_role(self):
        res = self.client.post(
            reverse("register"),
            {
                "email": "reader@test.com",
                "username": "readeruser",
                "first_name": "A",
                "last_name": "B",
                "password": "StrongPass1",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="reader@test.com")
        reader = Role.objects.get(role_name=Role.RoleName.READER)
        self.assertTrue(UserRole.objects.filter(user=user, role=reader).exists())

    def test_login(self):
        res = self.client.post(
            reverse("login"), {"email": "user@test.com", "password": "StrongPass1"}
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)

    def test_logout_requires_auth(self):
        res = self.client.post(reverse("logout"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# NOTE: TEST VALIDATION & EDGE CASES
class TestRegisterValidation(BaseTestCase):
    def test_duplicate_email_case_insensitive(self):
        res = self.client.post(
            reverse("register"),
            {
                "email": "USER@test.com",
                "username": "newuser",
                "first_name": "A",
                "last_name": "B",
                "password": "StrongPass1",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weak_password_rejected(self):
        res = self.client.post(
            reverse("register"),
            {
                "email": "weak@test.com",
                "username": "weakuser",
                "first_name": "A",
                "last_name": "B",
                "password": "123",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# NOTE: TEST SEARCH & ENUMERATION
class TestUserSearch(BaseTestCase):
    def test_search_requires_auth(self):
        res = self.client.get(reverse("user-search"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_can_search_others(self):
        self.auth(self.user)

        res = self.client.get(reverse("user-search"), {"search": "staff"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_user_cannot_see_self(self):
        self.auth(self.user)

        res = self.client.get(reverse("user-search"), {"search": "user"})
        ids = [u["id"] for u in res.data]
        self.assertNotIn(str(self.user.id), ids)


# NOTE: TEST PERMISSIONS (CRITICAL)
class TestPermissions(BaseTestCase):
    def test_non_staff_cannot_list_users(self):
        self.auth(self.user)
        res = self.client.get(reverse("all-users"))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_list_users(self):
        self.auth(self.staff)
        res = self.client.get(reverse("all-users"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)


# NOTE: TEST TOGGLE ABUSE TESTS
class TestToggleUser(BaseTestCase):
    def test_staff_can_toggle_user(self):
        self.auth(self.staff)

        res = self.client.patch(reverse("user-toggle", args=[self.user.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_staff_cannot_toggle_superuser(self):
        self.auth(self.staff)

        res = self.client.patch(reverse("user-toggle", args=[self.superuser.id]))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


# NOTE: TEST TOKEN ABUSE TESTS
class TestJWTAbuse(BaseTestCase):

    def test_invalid_token(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalidtoken")
        res = self.client.get(reverse("user-me"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_token(self):
        res = self.client.get(reverse("user-me"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# NOTE: TEST "ME" ENDPOINT ATTACKS
class TestCurrentUser(BaseTestCase):
    def test_get_me(self):
        self.auth(self.user)
        res = self.client.get(reverse("user-me"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_change_password_wrong_old(self):
        self.auth(self.user)
        res = self.client.put(
            reverse("user-me"),
            {"old_password": "wrong", "new_password": "NewStrongPass1"},
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_success(self):
        self.auth(self.user)
        res = self.client.put(
            reverse("user-me"),
            {"old_password": "StrongPass1", "new_password": "NewStrongPass1"},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_user_delete_self(self):
        self.auth(self.user)
        # FIX: password confirmation is now required
        res = self.client.delete(reverse("user-me"), {"password": "StrongPass1"})
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)


# NOTE: TEST IDOR & PRIVILEGE TESTS
class TestUserDetailSecurity(BaseTestCase):
    def test_user_cannot_access_unrelated_user_data(self):
        """
        Users with no shared document should be blocked — IDOR fixed.
        """
        self.auth(self.user)
        res = self.client.get(reverse("user-detail", args=[self.staff.id]))
        # FIX: 403 is now correct — no shared document between user and staff
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_cannot_delete_other_user(self):
        self.auth(self.user)
        res = self.client.delete(reverse("user-detail", args=[self.staff.id]))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_modify_superuser(self):
        self.auth(self.staff)
        res = self.client.put(
            reverse("user-detail", args=[self.superuser.id]), {"username": "hacked"}
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
