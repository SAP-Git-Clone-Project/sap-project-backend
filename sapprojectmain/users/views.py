from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from core.permissions import (
    IsStaffOrSuperUser, 
    IsAuthenticatedUser, 
    IsOwnerOrStaff, 
    IsSystemAdmin
)
from rest_framework.permissions import AllowAny

from .models import UserModel
from .serializers import RegisterSerializer, LoginSerializer, UserSerializer


# REGISTER
class RegisterView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "user": serializer.data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=201,
        )


# LOGIN
class LoginView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                },
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=200
        )


# GET all users - super user or the admin role ones
# NOTE: users/
class UserListView(APIView):

    # IMP: Can be done just by superusers or custom administrators
    permission_classes = [IsStaffOrSuperUser | IsSystemAdmin]

    def get(self, request):
        users = UserModel.objects.all()

        serializer = UserSerializer(users, many=True)

        return Response(serializer.data, status=200)


# GET, PUT, DELETE any user by id for admins
# NOTE: users/<uuid:id>/
class UserDetailView(APIView):

    # IMP: Override permissions
    def get_permissions(self):

        # NOTE: Any authenticated user can view any user
        if self.request.method == "GET":
            return [IsAuthenticatedUser()]

        # NOTE: PUT and DELETE will be managed by the superuser or custom administrator
        elif self.request.method in ["PUT", "DELETE"]:
            return [IsStaffOrSuperUser() | IsSystemAdmin()]

        # NOTE: Any other request will have default permission
        return super().get_permissions()

    # NOTE: Find user and get user data by id
    def get_object(self, id):
        try:
            return UserModel.objects.get(pk=id)
        except UserModel.DoesNotExist:
            return None

    # NOTE: GET by id
    def get(self, request, id):
        user = self.get_object(id)

        if not user:
            return Response({"detail": "User not found"}, status=404)

        # Helper to check if the current requester has the custom administrator role
        is_custom_admin = request.user.user_roles.filter(role__role_name='administrator').exists()

        # NOTE: Allow only self or admin (checking both Django staff and custom role)
        if request.user != user and not (request.user.is_staff or is_custom_admin):
            return Response({"detail": "Forbidden"}, status=403)

        serializer = UserSerializer(user)

        return Response(serializer.data, status=200)

    # NOTE: PUT by id
    def put(self, request, id):

        user = self.get_object(id)

        if not user:
            return Response({"detail": "User not found"}, status=404)

        serializer = UserSerializer(user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()

            return Response(serializer.data, status=200)

        return Response(serializer.errors, status=400)

    # NOTE: DELETE by id
    def delete(self, request, id):

        user = self.get_object(id)

        if not user:
            return Response({"detail": "User not found"}, status=404)

        user.delete()

        return Response({"detail": "User deleted"}, status=204)


# GET, PUT, DELETE the current user data
# NOTE: users/me/
class CurrentUserDetailView(APIView):
    permission_classes = [IsAuthenticatedUser]

    # NOTE: GET for the current logged user
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    # NOTE: PUT for the current logged user
    def put(self, request):
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if old_password and new_password:
            if not request.user.check_password(old_password):
                return Response({"detail": "Wrong password"}, status=400)

            if len(new_password) < 8:
                return Response({"detail": "Password too short"}, status=400)

            request.user.set_password(new_password)

            request.user.save()

            return Response({"detail": "Password updated"}, status=200)

        serializer = UserSerializer(request.user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)

        return Response(serializer.errors, status=400)

    # NOTE: DELETE for the current logged user
    def delete(self, request):
        request.user.delete()
        return Response(status=204)


# NOTE: users/<uuid:id>/toggle/
class ToggleUserView(APIView):
    # IMP: Allow custom administrators or Django staff to toggle users
    permission_classes = [IsStaffOrSuperUser | IsSystemAdmin]

    def patch(self, request, id):
        try:
            user = UserModel.objects.get(pk=id)
        except UserModel.DoesNotExist:
            return Response({"detail": "User not found"}, status=404)

        user.is_enabled = not user.is_enabled

        user.save()

        return Response({"is_enabled": user.is_enabled}, status=200)


# NOTE: users/logout/
class LogoutView(APIView):

    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]

            token = RefreshToken(refresh_token)

            token.blacklist()

            return Response({"detail": "Logged out"}, status=200)
        except Exception:
            return Response({"detail": "Invalid token"}, status=400)