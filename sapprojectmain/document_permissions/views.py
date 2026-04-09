from rest_framework import generics, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q
import traceback

from core.permissions import (
    HasDocumentWritePermission,
    HasDocumentDeletePermission,
    IsStaffOrSuperUser,
    IsAuthenticatedUser,
)
from .models import DocumentPermissionModel
from .serializers import DocumentPermissionSerializer

# --- MANAGEMENT ACTIONS ---


class CreateDocumentPermissionView(generics.CreateAPIView):
    # Grant or update document access
    # Frontend sends User UUID from UserSearchView
    queryset = DocumentPermissionModel.objects.all()
    serializer_class = DocumentPermissionSerializer
    # Only users with WRITE/DELETE roles can share access
    permission_classes = [IsAuthenticatedUser, HasDocumentDeletePermission]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        document_permission = serializer.save()

        return Response(
            {
                "document_permission": serializer.data,
                "uuid": document_permission.id,
                "status": "created" if document_permission._was_created else "updated",
            },
            status=status.HTTP_201_CREATED,
        )


class DeleteDocumentPermissionView(generics.DestroyAPIView):
    # Revoke access for a specific user
    # Target row using its specific permission UUID
    queryset = DocumentPermissionModel.objects.all()
    serializer_class = DocumentPermissionSerializer
    lookup_field = "id"
    # Requires DELETE level permission or Staff status
    permission_classes = [
        IsAuthenticatedUser,
        HasDocumentDeletePermission | IsStaffOrSuperUser,
    ]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        # Primary creator cannot be revoked unless by Superuser
        if instance.permission_type == "DELETE":
            if (
                instance.document.created_by == instance.user
                and not request.user.is_superuser
            ):
                return Response(
                    {"detail": "Cannot revoke the primary owner's permissions"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        instance.delete()
        return Response(
            {"detail": "Permission revoked successfully"}, status=status.HTTP_200_OK
        )


# --- VIEWING ACTIONS ---


class GetDocumentMembersView(generics.ListAPIView):
    # List all users invited to one specific document
    # URL uses doc_id to filter the document_id column
    serializer_class = DocumentPermissionSerializer
    permission_classes = [IsAuthenticatedUser]

    def get_queryset(self):
        try:
            # Map URL variable doc_id to model field document_id
            doc_id = self.kwargs.get("doc_id")
            user = self.request.user

            base_query = DocumentPermissionModel.objects.filter(
                Q(document_id=doc_id) | Q(version_id=doc_id)
            ).select_related("user", "document")

            if not user.is_staff and not user.is_superuser:
                is_member = base_query.filter(user=user).exists()
                if not is_member:
                    raise PermissionDenied()

            try:
                # Converting to a list forces the database query and 
                # helps reveal errors before the renderer starts
                list(base_query) 
            except Exception as e:
                print("--- DATABASE ERROR ---")
                traceback.print_exc()
                raise ValueError({"error": "Database query failed"})

            # return DocumentPermissionModel.objects.filter(document_id=doc_id) # .select_related("user")
            return base_query
        except Exception as e:
            traceback.print_exc()
            raise PermissionDenied()


class GetAllDocumentPermissionsView(APIView):
    # Global permission list for dashboards
    # Staff see everything while users see docs they can manage
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        user = request.user
        if user.is_staff or user.is_superuser:
            permissions = DocumentPermissionModel.objects.all()
        else:
            # Filter for docs where user has management rights
            permissions = DocumentPermissionModel.objects.filter(
                document__document_permissions__user=user,
                document__document_permissions__permission_type__in=["WRITE", "DELETE"],
            ).distinct()

        serializer = DocumentPermissionSerializer(permissions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GetDocumentPermissionView(generics.RetrieveAPIView):
    # Fetch details for a single member record
    # Target row using its specific permission UUID
    queryset = DocumentPermissionModel.objects.all()
    serializer_class = DocumentPermissionSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticatedUser]

    def get_queryset(self):
        user = self.request.user
        # Users see records for documents they are part of
        if user.is_staff or user.is_superuser:
            return DocumentPermissionModel.objects.all()
        return DocumentPermissionModel.objects.filter(
            document__document_permissions__user=user
        ).distinct()


class RejectDocumentPermissionView(APIView):
    # User voluntarily leaves a document
    # Uses doc_id from URL to find the specific link
    permission_classes = [IsAuthenticatedUser]

    def delete(self, request, doc_id):
        # Locate the link for the current logged in user
        permission = DocumentPermissionModel.objects.filter(
            user=request.user, document_id=doc_id
        ).first()

        if not permission:
            return Response(
                {"detail": "You do not have permissions for this document"}, status=status.HTTP_404_NOT_FOUND
            )
        
        if (
            permission.permission_type == "DELETE"
            and permission.document.created_by == request.user
            and not request.user.is_superuser
        ):
            return Response(
                {"detail": "The primary owner cannot resign from the document"},
                status=status.HTTP_403_FORBIDDEN,
            )

        permission.delete()
        return Response(
            {"detail": "You have successfully resigned from this document"}, status=status.HTTP_200_OK
        )
