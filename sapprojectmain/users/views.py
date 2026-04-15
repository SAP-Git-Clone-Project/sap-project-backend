# Django
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models import Q
from django.shortcuts import get_object_or_404

# DRF
from rest_framework import filters, generics, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# SimpleJWT
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

# Internal
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

# NOTE: Custom permission classes for access control
from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser, IsSuperUser

import json

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
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()

            user = request.user
            ip = get_current_ip(request)

            AuditLogModel.objects.create(
                user=user,
                action_type="logout",
                ip_address=ip,
                description=f"User {user.email} logged out.",
            )

            return Response({"detail": "Logged out."}, status=200)

        except Exception as e:
            print("ERROR:", str(e))
            return Response({"detail": "Invalid token."}, status=400)


# --- 2. USER DISCOVERY ---


class UserSearchView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedUser]
    serializer_class = UserSearchSerializer
    filter_backends = [filters.SearchFilter]
    # NOTE: Configures searchable fields for finding other users to invite
    search_fields = ["username", "email"]

    def get_queryset(self):
        queryset = UserModel.objects.exclude(id=self.request.user.id).filter(is_active=True)

        role_name = self.request.query_params.get("role")
        if role_name:
            queryset = queryset.filter(user_roles__role__role_name=role_name)

        document_id = self.request.query_params.get("document")
        if document_id:
            queryset = queryset.filter(
                document_permissions__document_id=document_id
            ).distinct()

        return queryset.distinct()


# --- 3. ADMIN & STAFF ACTIONS ---


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class UserListDestroyView(generics.ListCreateAPIView):
    queryset = UserModel.objects.all().order_by("-created_at")
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search) | Q(email__icontains=search)
            )

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            val = is_active.lower() == "true"
            queryset = queryset.filter(is_active=val)

        is_staff = self.request.query_params.get("is_staff")
        if is_staff is not None:
            val = is_staff.lower() == "true"
            queryset = queryset.filter(Q(is_staff=val) | Q(is_superuser=val))
            
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        return queryset

    def get_serializer_context(self):
        return {"request": self.request}


class UserAdminToggleView(generics.GenericAPIView):
    queryset = UserModel.objects.all()
    permission_classes = [IsAuthenticatedUser, IsSuperUser]
    lookup_field = "id"

    def post(self, request, *args, **kwargs):
        user_to_toggle = self.get_object()
        requester = request.user
        password = request.data.get("password")

        # 1. Password Verification (Using check_password like your delete view)
        if not password:
            return Response(
                {"detail": "Password is required to change admin status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not requester.check_password(password):
            return Response(
                {"error": "Invalid credentials. Action denied."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 2. Safety Check
        if user_to_toggle == requester:
            return Response(
                {"detail": "You cannot change your own admin status through this endpoint."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Toggle Logic
        requested_status = request.data.get("is_staff")
        if requested_status is not None:
            user_to_toggle.is_staff = str(requested_status).lower() == "true"
        else:
            user_to_toggle.is_staff = not user_to_toggle.is_staff

        user_to_toggle.save()

        return Response(
            {
                "username": user_to_toggle.username,
                "is_staff": user_to_toggle.is_staff,
                "message": f"Successfully updated admin status for {user_to_toggle.username}.",
            },
            status=status.HTTP_200_OK,
        )

class AdminDeleteUserView(APIView):
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]

    def delete(self, request, id):
        password = request.data.get("password")
        if not password:
            try:
                password = json.loads(request.body).get("password")
            except (json.JSONDecodeError, AttributeError):
                pass

        if not password:
            return Response(
                {"error": "Admin password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.check_password(password):
            return Response(
                {"error": "Invalid credentials. Termination aborted."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        current_user = request.user
        user_to_delete = get_object_or_404(UserModel, pk=id)

        if current_user == user_to_delete:
            return Response(
                {"error": "You cannot delete your own account from this panel."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if current_user.is_superuser:
            if user_to_delete.is_superuser:
                return Response(
                    {"error": "Superusers cannot delete other superusers."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        elif current_user.is_staff:
            if user_to_delete.is_superuser or user_to_delete.is_staff:
                return Response(
                    {"error": "Admins cannot delete other management accounts."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        tokens = OutstandingToken.objects.filter(user=user_to_delete)
        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=token) for token in tokens],
            ignore_conflicts=True
        )
        AuditLogModel.objects.filter(user=user_to_delete).update(user=None)
        user_to_delete.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

class ToggleUserView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def patch(self, request, id):
        # NOTE: PATCH to enable or disable a user account
        user = get_object_or_404(UserModel, pk=id)
        current_user = request.user

        # SECURITY: Prevents users from deactivating their own accounts
        if user == current_user:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # HIERARCHY LOGIC:
        # 1. Superuser logic: Can toggle anyone EXCEPT other Superusers
        if current_user.is_superuser:
            if user.is_superuser:
                return Response(
                    {"detail": "Superusers cannot modify other Superusers."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 2. Staff (Admin) logic: Cannot toggle Superusers OR other Staff members
        elif current_user.is_staff:
            if user.is_superuser or user.is_staff:
                return Response(
                    {"detail": "Admins cannot modify other Admins or Superusers."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Perform the toggle
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
        AuditLogModel.objects.filter(user=user).update(user=None)

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
        AuditLogModel.objects.filter(user=user).update(user=None)

        # 2. PERMANENT DELETE
        user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
