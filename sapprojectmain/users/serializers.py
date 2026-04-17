from rest_framework import serializers
from django.core.validators import validate_email, RegexValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
import re

from .models import UserModel
from user_roles.models import Role, UserRole
from core.rbac import get_global_roles
from .models import UserModel
from user_roles.models import UserRole, Role

# VALIDATORS
# NOTE: Regex to ensure usernames are URL-safe and start with a letter
username_validator = RegexValidator(
    regex=r"^[A-Za-z][A-Za-z0-9_]*$",
    message="Username must start with a letter and contain only letters, numbers, or underscores",
)


def validate_password_strength(value):
    # NOTE: Enforces minimum length and standard Django complexity checks
    if len(value) < 8:
        raise serializers.ValidationError("Password must be at least 8 characters long")
    try:
        validate_password(value)
    except ValidationError as e:
        raise serializers.ValidationError(list(e.messages))

    # NOTE: Custom rules for uppercase and numeric requirements
    if not re.search(r"[A-Z]", value):
        raise serializers.ValidationError(
            "Password must include at least one uppercase letter"
        )
    if not re.search(r"[0-9]", value):
        raise serializers.ValidationError("Password must include at least one number")
    return value


# --- REGISTER SERIALIZER ---
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        validators=[validate_password_strength],
    )
    username = serializers.CharField(
        min_length=3,
        validators=[username_validator],
    )

    class Meta:
        model = UserModel
        fields = ["id", "username", "first_name", "last_name", "email", "password"]

    def validate_email(self, value):
        # NOTE: Ensures case-insensitive email uniqueness
        value = value.lower()
        if UserModel.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already in use")
        return value

    def validate_username(self, value):
        # NOTE: Ensures case-insensitive username uniqueness
        value = value.lower()
        if UserModel.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already in use")
        return value

    def create(self, validated_data):
        # NOTE: Delegates to custom manager to handle password hashing
        user = UserModel.objects.create_user(**validated_data)
        reader_role, _ = Role.objects.get_or_create(
            role_name=Role.RoleName.READER,
            defaults={"description": "Default role for newly registered users."},
        )
        UserRole.objects.get_or_create(user=user, role=reader_role)
        return user


# --- LOGIN SERIALIZER ---
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        # NOTE: Verifies credentials and account activity status
        user = authenticate(email=data.get("email"), password=data.get("password"))
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        if not user.is_active:
            raise serializers.ValidationError("Account is inactive")

        data["user"] = user
        return data


# --- USER PROFILE SERIALIZER ---
class UserSerializer(serializers.ModelSerializer):
    global_roles = serializers.SerializerMethodField()
    password = serializers.CharField(
        write_only=True,
        required=False,
        validators=[validate_password_strength],
    )

    class Meta:
        model = UserModel
        fields = [
            "id",
            "first_name",
            "last_name",
            "username",
            "email",
            "password",
            "avatar",
            "is_active",
            "is_staff",
            "is_superuser",
            "created_at",
            "global_roles",
        ]
        # SECURITY: Prevents self-escalation of privileges via profile updates
        read_only_fields = [
            "id",
            "is_staff",
            "is_superuser",
            "is_active",
            "created_at",
            "global_roles",
        ]

    def validate_email(self, value):
        # NOTE: Validates email uniqueness while ignoring current user instance
        value = value.lower()
        qs = UserModel.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Email already in use")
        return value

    def update(self, instance, validated_data):
        # NOTE: Updates profile attributes and handles password hashing if provided
        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance

    def get_global_roles(self, obj):
        return sorted(get_global_roles(obj))


# --- USER SEARCH SERIALIZER ---
class UserSearchSerializer(serializers.ModelSerializer):
    global_roles = serializers.SerializerMethodField()
    eligible_for_reviewer = serializers.SerializerMethodField()
    # NOTE: Returns minimal public info for user invitation search
    class Meta:
        model = UserModel
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "avatar",
            "global_roles",
            "eligible_for_reviewer",
        ]
        read_only_fields = ["id", "username", "email"]

    def get_global_roles(self, obj):
        return sorted(get_global_roles(obj))

    def get_eligible_for_reviewer(self, obj):
        return Role.RoleName.REVIEWER in get_global_roles(obj)
        fields = ["id", "username", "email", "first_name", "last_name", "avatar"]
        read_only_fields = ["id", "username", "email"]
