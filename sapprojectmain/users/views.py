from rest_framework import status, generics, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out

from .models import UserModel
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    UserSearchSerializer,
)

# NOTE: Custom permission classes for access control
from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser

User = get_user_model()

# --- 1. AUTHENTICATION & IDENTITY ---


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # NOTE: POST to create a new user account and return JWT tokens
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # NOTE: Signals login event for audit tracking upon registration
        user_logged_in.send(sender=user.__class__, request=request, user=user)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": serializer.data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # NOTE: POST to verify credentials and issue new JWT tokens
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        # IMP: Trigger login signal for security and audit logging
        user_logged_in.send(sender=user.__class__, request=request, user=user)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "is_staff": user.is_staff,
                },
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        # NOTE: POST to blacklist the refresh token and terminate the session
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)

            user = request.user
            token.blacklist()

            # NOTE: Signal logout event for audit trails
            user_logged_out.send(sender=user.__class__, request=request, user=user)

            return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"detail": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST
            )


# --- 2. USER DISCOVERY ---


class UserSearchView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedUser]
    serializer_class = UserSearchSerializer
    filter_backends = [filters.SearchFilter]
    # NOTE: Configures searchable fields for finding other users to invite
    search_fields = ["username", "email"]

    def get_queryset(self):
        # NOTE: Excludes the requesting user from search results
        return UserModel.objects.exclude(id=self.request.user.id).filter(is_active=True)


# --- 3. ADMIN & STAFF ACTIONS ---


class UserListView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        # NOTE: GET list of all users for staff members
        users = UserModel.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)


class ToggleUserView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def patch(self, request, id):
        # NOTE: PATCH to enable or disable a user account
        user = get_object_or_404(UserModel, pk=id)

        # SECURITY: Prevents non-superusers from deactivating superuser accounts
        if user.is_superuser and not request.user.is_superuser:
            return Response(
                {"detail": "Staff cannot modify Superusers."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user.is_active = not user.is_active
        user.save()
        return Response({"is_active": user.is_active})


# --- 4. TARGETED MEMBER ACTIONS ---


class UserDetailView(APIView):
    def get_permissions(self):
        # NOTE: Dynamics permissions where GET is authenticated but modifications are staff-only
        if self.request.method == "GET":
            return [IsAuthenticatedUser()]
        return [IsStaffOrSuperUser()]

    def get(self, request, id):
        # NOTE: GET specific user details by UUID
        user = get_object_or_404(UserModel, pk=id)
        serializer = UserSerializer(user)
        return Response(serializer.data)

    def put(self, request, id):
        # NOTE: PUT to update a specific user account partially
        user = get_object_or_404(UserModel, pk=id)

        # SECURITY: Restricts modification of superusers to other superusers
        if user.is_superuser and not request.user.is_superuser:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = UserSerializer(
            user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, id):
        # NOTE: DELETE to remove a user account from the system
        user = get_object_or_404(UserModel, pk=id)

        if user.is_superuser and not request.user.is_superuser:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- 5. THE 'ME' ENDPOINT ---


class CurrentUserDetailView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        # NOTE: GET the profile of the currently logged-in user
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        # NOTE: PUT to update own profile or change password
        new_password = request.data.get("new_password")

        if new_password:
            # SECURITY: Requires old password verification for password changes
            if not request.user.check_password(request.data.get("old_password")):
                return Response(
                    {"detail": "Incorrect old password."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            request.user.set_password(new_password)
            request.user.save()

        serializer = UserSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request):
        # NOTE: DELETE to allow a user to deactivate/delete their own account
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
