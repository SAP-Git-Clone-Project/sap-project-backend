from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from core.permissions import IsStaffOrSuperUser, IsAuthenticatedUser, IsOwnerOrStaff

from .models import UserModel
from .serializers import RegisterSerializer, LoginSerializer, UserSerializer


# REGISTER
class RegisterView(APIView):
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
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )


# GET all users
# NOTE: users/
class UserListView(APIView):

    # IMP: Can be done just by superusers
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        users = UserModel.objects.all()

        serializer = UserSerializer(users, many=True)

        return Response(serializer.data, status=200)


# GET, PUT, DELETE any user by id for admins
# NOTE: users/<uuid:id>/
class UserDetailView(APIView):

    # Override permissions
    permission_classes = [IsStaffOrSuperUser]

    # NOTE: GET
    def get(self, request, id):
        try:
            user = UserModel.objects.get(pk=id)
        except UserModel.DoesNotExist:
            return Response({"detail": "User not found"}, status=404)

        serializer = UserSerializer(user)
        return Response(serializer.data, status=200)

    # NOTE: PUT
    def put(self, request, id):
        try:
            user = UserModel.objects.get(pk=id)
        except UserModel.DoesNotExist:
            return Response({"detail": "User not found"}, status=404)

        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # NOTE: DELETE
    def delete(self, request, id):
        try:
            user = UserModel.objects.get(pk=id)
        except UserModel.DoesNotExist:
            return Response({"detail": "User not found"}, status=404)

        user.delete()
        return Response(status=204)


# GET, PUT, DELETE the current user data
# NOTE: users/me/
class CurrentUserDetailView(APIView):
    permission_classes = [IsAuthenticatedUser]

    # NOTE: GET
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    # NOTE: PUT
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
            return Response({"detail": "Password updated"})

        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # NOTE: DELETE
    def delete(self, request):
        request.user.delete()
        return Response(status=204)


# NOTE: users/<uuid:id>/toggle/
class ToggleUserView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def patch(self, request, id):
        try:
            user = UserModel.objects.get(pk=id)
        except UserModel.DoesNotExist:
            return Response({"detail": "User not found"}, status=404)

        user.is_enabled = not user.is_enabled
        user.save()
        return Response({"is_enabled": user.is_enabled})


# NOTE: users/logout/
class LogoutView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Logged out"})
        except Exception:
            return Response({"detail": "Invalid token"}, status=400)
