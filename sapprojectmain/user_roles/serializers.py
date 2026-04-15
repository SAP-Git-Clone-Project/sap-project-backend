from rest_framework import serializers
from .models import Role, UserRole

class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "role_name", "description"]
        read_only_fields = ["id"]


class UserRoleSerializer(serializers.ModelSerializer):
    role_name = serializers.ReadOnlyField(source="role.role_name")
    username = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = UserRole
        fields = [
            "id",
            "user",
            "username",
            "role",
            "role_name",
            "assigned_by",
            "assigned_at",
        ]
        read_only_fields = ["id", "assigned_at", "assigned_by"]


class UserRoleAssignSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    role_name = serializers.ChoiceField(choices=Role.RoleName.choices)
