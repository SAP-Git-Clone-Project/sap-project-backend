from rest_framework import status, generics, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from audit_log.middleware import get_current_ip
from audit_log.models import AuditLogModel

from .models import UserModel
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    UserSearchSerializer,
)
from document_permissions.models import DocumentPermissionModel
from django.db.models import Q

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
        # user_logged_in.send(sender=user.__class__, request=request, user=user)

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
                    "avatar": user.avatar
                },
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()

            user = request.user

            # 🔥 DIRECT AUDIT LOG (no signals)
            AuditLogModel.objects.create(
                user=user,
                action_type="logout",
                ip_address=get_current_ip() or "0.0.0.0",
                description=f"User {user.email} logged out.",
            )

            return Response({"detail": "Logged out."}, status=200)

        except Exception:
            return Response({"detail": "Invalid token."}, status=400)


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
        if user == request.user:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        if self.request.method == "GET":
            return [IsAuthenticatedUser()]
        return [IsStaffOrSuperUser()]

    def get(self, request, id):
        # Staff and superusers see anyone
        if request.user.is_staff or request.user.is_superuser:
            user = get_object_or_404(UserModel, pk=id)
            return Response(UserSerializer(user).data)

        # Always can see yourself
        if str(request.user.id) == str(id):
            return Response(UserSerializer(request.user).data)

        target_user = get_object_or_404(UserModel, pk=id)

        # Get all doc IDs the requesting user has access to
        my_doc_ids = DocumentPermissionModel.objects.filter(
            user=request.user
        ).values_list("document_id", flat=True)

        # Check if target user is also on any of those same docs
        shares_document = DocumentPermissionModel.objects.filter(
            user=target_user, document_id__in=my_doc_ids
        ).exists()

        if not shares_document:
            return Response(
                {"detail": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(UserSerializer(target_user).data)

    def put(self, request, id):
        user = get_object_or_404(UserModel, pk=id)
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
        user = get_object_or_404(UserModel, pk=id)

        # Permission Check
        if user.is_superuser and not request.user.is_superuser:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )

        # DELETE RELATED TOKENS FIRST
        OutstandingToken.objects.filter(user=user).delete()

        # 2. DELETE THE USER
        user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# --- 5. THE 'ME' ENDPOINT ---


class CurrentUserDetailView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        new_password = request.data.get("new_password")

        if new_password:
            if not request.user.check_password(request.data.get("old_password")):
                return Response(
                    {"detail": "Incorrect old password."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            request.user.set_password(new_password)
            request.user.save()

            # FIX: Blacklist the refresh token so old sessions die immediately
            try:
                refresh_token = request.data.get("refresh")
                if refresh_token:
                    RefreshToken(refresh_token).blacklist()
            except Exception:
                pass  # Don't block the response if blacklist fails

        serializer = UserSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request):
        password = request.data.get("password")
        if not password or not request.user.check_password(password):
            return Response(
                {"detail": "Password confirmation required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user

        # 1. CLEAR TOKENS
        OutstandingToken.objects.filter(user=user).delete()

        # 2. PERMANENT DELETE
        user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
