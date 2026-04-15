from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsAuthenticatedUser, IsStaffOrSuperUser
from .models import Role, UserRole
from .serializers import RoleSerializer, UserRoleSerializer, UserRoleAssignSerializer

User = get_user_model()

class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]
        else:
            permission_classes = [IsAuthenticatedUser]
        return [permission() for permission in permission_classes]


class UserRoleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserRoleSerializer
    permission_classes = [IsAuthenticatedUser]

    def get_queryset(self):
        queryset = UserRole.objects.select_related("user", "role", "assigned_by")
        if self.request.user.is_staff or self.request.user.is_superuser:
            return queryset
        return queryset.filter(user=self.request.user)


class UserRoleManageView(APIView):
    permission_classes = [IsAuthenticatedUser, IsStaffOrSuperUser]

    def post(self, request):
        serializer = UserRoleAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_user = get_object_or_404(User, id=serializer.validated_data["user"], is_active=True)
        role = get_object_or_404(Role, role_name=serializer.validated_data["role_name"])

        assignment, created = UserRole.objects.get_or_create(
            user=target_user,
            role=role,
            defaults={"assigned_by": request.user},
        )
        if not created and assignment.assigned_by_id != request.user.id:
            assignment.assigned_by = request.user
            assignment.save(update_fields=["assigned_by"])

        return Response(
            {
                "status": "created" if created else "exists",
                "user_role": UserRoleSerializer(assignment).data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        serializer = UserRoleAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_user = get_object_or_404(User, id=serializer.validated_data["user"], is_active=True)
        role = get_object_or_404(Role, role_name=serializer.validated_data["role_name"])
        assignment = UserRole.objects.filter(user=target_user, role=role).first()
        if not assignment:
            return Response({"detail": "Role assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        assignment.delete()
        return Response({"status": "deleted"}, status=status.HTTP_200_OK)
