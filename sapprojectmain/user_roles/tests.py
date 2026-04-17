import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Role, UserRole
from .serializers import RoleSerializer, UserRoleSerializer, UserRoleAssignSerializer

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, *, staff=False, superuser=False, active=True):
    user = User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}_{uuid.uuid4()}@test.com",
        first_name="Jorkata",
        last_name="Draganov",
        is_staff=staff,
        is_superuser=superuser,
        is_active=active,
    )
    return user


def make_role(name=Role.RoleName.READER, description=""):
    role, _ = Role.objects.get_or_create(
        role_name=name,
        defaults={"description": description},
    )
    return role


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class RoleModelTest(TestCase):

    def test_str_returns_display_name(self):
        role = make_role(Role.RoleName.AUTHOR)
        self.assertEqual(str(role), "Author")

    def test_role_name_unique(self):
        make_role(Role.RoleName.READER)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Role.objects.create(role_name=Role.RoleName.READER)

    def test_id_is_uuid(self):
        role = make_role()
        self.assertIsInstance(role.id, uuid.UUID)

    def test_description_optional(self):
        role = Role.objects.create(role_name=Role.RoleName.REVIEWER)
        self.assertIsNone(role.description)


class UserRoleModelTest(TestCase):

    def setUp(self):
        self.user = make_user("alice")
        self.staff = make_user("bob", staff=True)
        self.role = make_role(Role.RoleName.WRITER)

    def test_str(self):
        ur = UserRole.objects.create(user=self.user, role=self.role)
        self.assertIn("alice", str(ur))
        self.assertIn("writer", str(ur))

    def test_id_is_uuid(self):
        ur = UserRole.objects.create(user=self.user, role=self.role)
        self.assertIsInstance(ur.id, uuid.UUID)

    def test_unique_user_role_constraint(self):
        UserRole.objects.create(user=self.user, role=self.role)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            UserRole.objects.create(user=self.user, role=self.role)

    def test_assigned_by_nullable(self):
        ur = UserRole.objects.create(user=self.user, role=self.role)
        self.assertIsNone(ur.assigned_by)

    def test_assigned_by_set_null_on_user_delete(self):
        assigner = make_user("assigner")
        ur = UserRole.objects.create(user=self.user, role=self.role, assigned_by=assigner)
        assigner.delete()
        ur.refresh_from_db()
        self.assertIsNone(ur.assigned_by)

    def test_cascades_on_user_delete(self):
        UserRole.objects.create(user=self.user, role=self.role)
        self.user.delete()
        self.assertFalse(UserRole.objects.filter(role=self.role).exists())

    def test_cascades_on_role_delete(self):
        UserRole.objects.create(user=self.user, role=self.role)

        role_id = self.role.id
        self.role.delete()

        self.assertFalse(
            UserRole.objects.filter(user=self.user, role=role_id).exists()
        )


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------

class RoleSerializerTest(TestCase):

    def test_serializes_fields(self):
        role = make_role(Role.RoleName.READER, description="Can read content")
        data = RoleSerializer(role).data
        self.assertEqual(data["role_name"], Role.RoleName.READER)
        self.assertEqual(data["description"], "Can read content")
        self.assertIn("id", data)

    def test_id_read_only(self):
        s = RoleSerializer(data={"id": str(uuid.uuid4()), "role_name": "reader"})
        s.is_valid()
        self.assertNotIn("id", s.validated_data)

    def test_invalid_role_name_rejected(self):
        s = RoleSerializer(data={"role_name": "god_mode"})
        self.assertFalse(s.is_valid())
        self.assertIn("role_name", s.errors)


class UserRoleAssignSerializerTest(TestCase):

    def test_valid_data(self):
        s = UserRoleAssignSerializer(data={
            "user": str(uuid.uuid4()),
            "role_name": Role.RoleName.WRITER,
        })
        self.assertTrue(s.is_valid(), s.errors)

    def test_invalid_role_name(self):
        s = UserRoleAssignSerializer(data={
            "user": str(uuid.uuid4()),
            "role_name": "not_a_role",
        })
        self.assertFalse(s.is_valid())
        self.assertIn("role_name", s.errors)

    def test_invalid_user_uuid(self):
        s = UserRoleAssignSerializer(data={"user": "not-a-uuid", "role_name": "reader"})
        self.assertFalse(s.is_valid())
        self.assertIn("user", s.errors)


# ---------------------------------------------------------------------------
# RoleViewSet tests
# ---------------------------------------------------------------------------

class RoleViewSetTest(APITestCase):

    def setUp(self):
        self.regular = make_user("regular")
        self.staff = make_user("staff", staff=True)
        self.role = make_role(Role.RoleName.READER)
        self.list_url = reverse("role-list")
        self.detail_url = reverse("role-detail", args=[self.role.id])

    # -- list / retrieve (any authenticated user) --

    def test_list_authenticated(self):
        self.client.force_authenticate(self.regular)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_retrieve_authenticated(self):
        self.client.force_authenticate(self.regular)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(str(r.data["id"]), str(self.role.id))

    def test_list_unauthenticated(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- create --

    def test_create_as_staff(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.list_url, {"role_name": "reviewer"})
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_create_as_regular_user_forbidden(self):
        self.client.force_authenticate(self.regular)
        r = self.client.post(self.list_url, {"role_name": "reviewer"})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_duplicate_role_fails(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.list_url, {"role_name": Role.RoleName.READER})
        self.assertIn(r.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

    # -- update --

    def test_update_as_staff(self):
        self.client.force_authenticate(self.staff)
        r = self.client.patch(self.detail_url, {"description": "Updated"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["description"], "Updated")

    def test_update_as_regular_user_forbidden(self):
        self.client.force_authenticate(self.regular)
        r = self.client.patch(self.detail_url, {"description": "Hack"})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    # -- delete --

    def test_delete_as_staff(self):
        self.client.force_authenticate(self.staff)
        r = self.client.delete(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_as_regular_user_forbidden(self):
        self.client.force_authenticate(self.regular)
        r = self.client.delete(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_write_forbidden(self):
        r = self.client.post(self.list_url, {"role_name": "reviewer"})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# UserRoleViewSet tests
# ---------------------------------------------------------------------------

class UserRoleViewSetTest(APITestCase):

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.staff = make_user("staff", staff=True)
        self.role_reader = make_role(Role.RoleName.READER)
        self.role_writer = make_role(Role.RoleName.WRITER)
        self.alice_ur, _ = UserRole.objects.get_or_create(
            user=self.alice,
            role=self.role_reader
        )

        self.bob_ur, _ = UserRole.objects.get_or_create(
            user=self.bob,
            role=self.role_writer
        )
        self.list_url = reverse("user-role-list")

    def test_unauthenticated_forbidden(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_user_sees_only_own_roles(self):
        self.client.force_authenticate(self.alice)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in r.data]
        self.assertIn(str(self.alice_ur.id), ids)
        self.assertNotIn(str(self.bob_ur.id), ids)

    def test_staff_sees_all_roles(self):
        self.client.force_authenticate(self.staff)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in r.data]
        self.assertIn(str(self.alice_ur.id), ids)
        self.assertIn(str(self.bob_ur.id), ids)

    def test_retrieve_own_role(self):
        self.client.force_authenticate(self.alice)
        url = reverse("user-role-detail", args=[self.alice_ur.id])
        r = self.client.get(url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_response_includes_username_and_role_name(self):
        self.client.force_authenticate(self.alice)
        url = reverse("user-role-detail", args=[self.alice_ur.id])
        r = self.client.get(url)
        self.assertEqual(r.data["username"], "alice")
        self.assertEqual(r.data["role_name"], Role.RoleName.READER)


# ---------------------------------------------------------------------------
# UserRoleManageView tests
# ---------------------------------------------------------------------------

class UserRoleManageViewTest(APITestCase):

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.staff = make_user("staff", staff=True)
        self.superuser = make_user("super", superuser=True)
        self.role = make_role(Role.RoleName.WRITER)
        self.url = reverse("user-role-manage")

    def _payload(self, user=None, role_name=None):
        return {
            "user": str((user or self.alice).id),
            "role_name": role_name or Role.RoleName.WRITER,
        }

    # -- POST: assign role --

    def test_assign_role_as_staff(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["status"], "created")
        self.assertTrue(UserRole.objects.filter(user=self.alice, role=self.role).exists())

    def test_assign_role_as_superuser(self):
        self.client.force_authenticate(self.superuser)
        r = self.client.post(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_assign_sets_assigned_by(self):
        self.client.force_authenticate(self.staff)
        self.client.post(self.url, self._payload())
        ur = UserRole.objects.get(user=self.alice, role=self.role)
        self.assertEqual(ur.assigned_by, self.staff)

    def test_assign_existing_role_returns_200(self):
        UserRole.objects.create(user=self.alice, role=self.role, assigned_by=self.staff)
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["status"], "exists")

    def test_assign_updates_assigned_by_when_different_staff(self):
        other_staff = make_user("other_staff", staff=True)
        UserRole.objects.create(user=self.alice, role=self.role, assigned_by=other_staff)
        self.client.force_authenticate(self.staff)
        self.client.post(self.url, self._payload())
        ur = UserRole.objects.get(user=self.alice, role=self.role)
        self.assertEqual(ur.assigned_by, self.staff)

    def test_assign_role_as_regular_user_forbidden(self):
        self.client.force_authenticate(self.alice)
        r = self.client.post(self.url, self._payload(user=self.bob))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_unauthenticated_forbidden(self):
        r = self.client.post(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_assign_nonexistent_user_returns_404(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, {"user": str(uuid.uuid4()), "role_name": "writer"})
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_inactive_user_returns_404(self):
        inactive = make_user("inactive", active=False)
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, self._payload(user=inactive))
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_nonexistent_role_returns_404(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, {"user": str(self.alice.id), "role_name": "author"})
        # role_name is valid enum but Role row doesn't exist yet
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_invalid_payload_returns_400(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, {"user": "bad-uuid", "role_name": "writer"})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_invalid_role_name_returns_400(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, {"user": str(self.alice.id), "role_name": "god"})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_response_contains_user_role_data(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post(self.url, self._payload())
        self.assertIn("user_role", r.data)
        self.assertEqual(r.data["user_role"]["username"], "alice")
        self.assertEqual(r.data["user_role"]["role_name"], Role.RoleName.WRITER)

    # -- DELETE: remove role --

    def test_delete_role_as_staff(self):
        UserRole.objects.create(user=self.alice, role=self.role)
        self.client.force_authenticate(self.staff)
        r = self.client.delete(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["status"], "deleted")
        self.assertFalse(UserRole.objects.filter(user=self.alice, role=self.role).exists())

    def test_delete_nonexistent_assignment_returns_404(self):
        self.client.force_authenticate(self.staff)
        r = self.client.delete(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_as_regular_user_forbidden(self):
        UserRole.objects.create(user=self.alice, role=self.role)
        self.client.force_authenticate(self.alice)
        r = self.client.delete(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_unauthenticated_forbidden(self):
        r = self.client.delete(self.url, self._payload())
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_nonexistent_user_returns_404(self):
        self.client.force_authenticate(self.staff)
        r = self.client.delete(self.url, {"user": str(uuid.uuid4()), "role_name": "writer"})
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_inactive_user_returns_404(self):
        inactive = make_user("inactive2", active=False)
        UserRole.objects.create(user=inactive, role=self.role)
        self.client.force_authenticate(self.staff)
        r = self.client.delete(self.url, self._payload(user=inactive))
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_invalid_payload_returns_400(self):
        self.client.force_authenticate(self.staff)
        r = self.client.delete(self.url, {"user": "not-a-uuid", "role_name": "writer"})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)