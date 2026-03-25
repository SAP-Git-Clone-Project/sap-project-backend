from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import RolesModel, UserRolesModel
from .serializers import RoleSerializer, UserRoleSerializer
from core.permissions import IsSystemAdmin, IsAuthenticatedUser


class UserRoleAssignmentView(APIView):
    """
    Analogous to an Express route handler:
    router.get('/', (req, res) => ...)
    router.post('/', (req, res) => ...)
    """

    permission_classes = [IsSystemAdmin]  # Only admins can touch this

    def get(self, request):
        # List all role assignments (who has what)
        assignments = UserRolesModel.objects.all()
        serializer = UserRoleSerializer(assignments, many=True)
        return Response(serializer.data)

    def post(self, request):
        # Assign a role to a user
        serializer = UserRoleSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            # Check if assignment already exists (prevent duplicates)
            user = serializer.validated_data["user"]
            role = serializer.validated_data["role"]
            if UserRolesModel.objects.filter(user=user, role=role).exists():
                return Response(
                    {"error": "Role already assigned"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserRoleDetailView(APIView):
    permission_classes = [IsSystemAdmin]

    def delete(self, request, id):
        # Remove a specific role assignment (Revoke permission)
        assignment = get_object_or_404(UserRolesModel, pk=id)
        assignment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
