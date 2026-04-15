from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Role, UserRole

User = get_user_model()


class UserRoleTests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="super",
            email="super@example.com",
            password="pass12345A",
        )
        self.staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="pass12345A",
            is_staff=True,
        )
        self.target = User.objects.create_user(
            username="target",
            email="target@example.com",
            password="pass12345A",
        )
        self.reader_role = Role.objects.get(role_name=Role.RoleName.READER)
        self.reviewer_role = Role.objects.get(role_name=Role.RoleName.REVIEWER)

    def test_new_user_gets_default_reader_role(self):
        self.assertTrue(
            UserRole.objects.filter(user=self.target, role=self.reader_role).exists()
        )

    def test_staff_can_assign_role(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            reverse("user-role-manage"),
            {"user": str(self.target.id), "role_name": Role.RoleName.REVIEWER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            UserRole.objects.filter(user=self.target, role=self.reviewer_role).exists()
        )

    def test_regular_user_cannot_assign_role(self):
        regular = User.objects.create_user(
            username="regular",
            email="regular@example.com",
            password="pass12345A",
        )
        self.client.force_authenticate(regular)
        response = self.client.post(
            reverse("user-role-manage"),
            {"user": str(self.target.id), "role_name": Role.RoleName.REVIEWER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
