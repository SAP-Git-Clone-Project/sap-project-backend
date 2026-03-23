from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate
import re

from .models import UserModel

# REGISTER
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = UserModel
        fields = ["id", "username", "email", "password"]

    # EMAIL
    def validate_email(self, value):
        try:
            validate_email(value)
        except ValidationError:
            raise serializers.ValidationError("Invalid email format")

        if UserModel.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already exists")

        return value.lower()

    # USERNAME
    def validate_username(self, value):
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", value):
            raise serializers.ValidationError(
                "Username must start with a letter and contain only letters, numbers, underscore"
            )

        if UserModel.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists")

        return value

    # PASSWORD
    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password too short")

        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError("Must include uppercase")

        if not re.search(r"[0-9]", value):
            raise serializers.ValidationError("Must include number")

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise serializers.ValidationError("Must include special character")

        return value

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

        if not user.is_enabled:
            raise serializers.ValidationError("User disabled")

        data["user"] = user
        return data

# USER