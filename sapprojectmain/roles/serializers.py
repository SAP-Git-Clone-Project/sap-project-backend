from rest_framework import serializers

from .models import RolesModel, UserRolesModel

from users.models import UserModel 

# Role serializer
class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolesModel
        fields = ["id", "role_name", "description"]

# UserRoles serializer
class UserRoleSerializer(serializers.ModelSerializer):
    # NOTE: Nested representation for user and role
    user = serializers.PrimaryKeyRelatedField(queryset=UserModel.objects.all())
    role = serializers.PrimaryKeyRelatedField(queryset=RolesModel.objects.all())

    assigned_by = serializers.PrimaryKeyRelatedField(
        read_only=True
    )

    class Meta:
        model = UserRolesModel
        fields = ["id", "user", "role", "assigned_at", "assigned_by"]
        read_only_fields = ["id", "assigned_at", "assigned_by"]

    def create(self, validated_data):
        # NOTE: Automatically set assigned_by to the requesting user
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            validated_data["assigned_by"] = request.user
        return super().create(validated_data)
