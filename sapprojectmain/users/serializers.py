from rest_framework import serializers
from django.core.validators import validate_email, RegexValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
import re

from .models import UserModel


# VALIDATORS
username_validator = RegexValidator(
    regex=r"^[A-Za-z][A-Za-z0-9_]*$",
    message="Username must start with a letter and contain only letters, numbers, or underscores",
)


# VALIDATE PASSWORD STRENGTH
def validate_password_strength(value):

    if len(value) < 8:
        raise serializers.ValidationError("Password must be at least 8 characters long")

    # Django built-in validators
    try:
        validate_password(value)
    except ValidationError as e:
        raise serializers.ValidationError(list(e.messages))

    # Custom rules
    if not re.search(r"[A-Z]", value):
        raise serializers.ValidationError("Password must include at least one uppercase letter")
    if not re.search(r"[a-z]", value):
        raise serializers.ValidationError("Password must include at least one lowercase letter")
    if not re.search(r"[0-9]", value):
        raise serializers.ValidationError("Password must include at least one number")
    if not re.search(r"[!+@#$%^&*(),.?\":{}|<>]", value):
        raise serializers.ValidationError(
            'Password must include at least one special character: ! + @ # $ % ^ & * ( ) , . ? " : { } | <>'
        )

    return value


# REGISTER
class RegisterSerializer(serializers.ModelSerializer):

    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password_strength],
    )

    username = serializers.CharField(
        min_length=3,
        max_length=50,
        validators=[username_validator],
    )

    class Meta:
        model = UserModel
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
        ]
        read_only_fields = ["id"]

    # EMAIL validation
    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError("Invalid email format")

        if UserModel.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("Email already in use")

        return value.lower()

    # USERNAME validation
    def validate_username(self, value):
        value = value.lower()

        if UserModel.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already in use")

        return value

    # CREATE USER
    def create(self, validated_data):
        password = validated_data.pop("password")

        user = UserModel.objects.create_user(password=password, **validated_data)

        return user


# LOGIN
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(email=data["email"], password=data["password"])

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        if not user.is_active:
            raise serializers.ValidationError("Account is inactive")

        if not user.is_enabled:
            raise serializers.ValidationError("Account has been disabled")

        data["user"] = user
        return data


# USER
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        required=False,
        validators=[validate_password_strength],
    )
    username = serializers.CharField(
        min_length=3,
        max_length=30,
        required=False,
        validators=[username_validator],
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
            "is_enabled",
            "is_staff",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_staff", "is_active", "created_at", "updated_at"]

    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError("Invalid email format")

        qs = UserModel.objects.filter(email=value.lower())

        # NOTE: Exclude current instance on update so user can keep their own email
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Email already in use")

        return value.lower()

    def validate_username(self, value):
        qs = UserModel.objects.filter(username=value)

        # NOTE: Exclude current instance on update so user can keep their own username
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Username already in use")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = UserModel.objects.create(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance
