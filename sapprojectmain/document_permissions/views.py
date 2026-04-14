from urllib import request

from rest_framework import generics, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q
import traceback
import uuid

from core.permissions import (
    HasDocumentWritePermission,
    HasDocumentDeletePermission,
    IsStaffOrSuperUser,
    IsAuthenticatedUser,
)
from .models import DocumentPermissionModel, DocumentPermissionRequestModel
from .serializers import DocumentPermissionSerializer
from notifications.models import NotificationModel

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
    # Revoke access for a specific user on either a document or a version.
    # Target row using its specific permission UUID (lookup_field = "id").
    # The queryset spans both document-level and version-level permission rows
    # so a single UUID resolves correctly regardless of which context it belongs to.
    serializer_class = DocumentPermissionSerializer
    lookup_field = "id"
    # Requires DELETE level permission or Staff status
    permission_classes = [
        IsAuthenticatedUser,
        HasDocumentDeletePermission | IsStaffOrSuperUser,
    ]

    def get_queryset(self):
        # Include both document-scoped and version-scoped permission rows.
        # Filtering by both non-null paths keeps the queryset explicit and
        # avoids accidentally exposing unrelated permission records.
        return DocumentPermissionModel.objects.filter(
            Q(document__isnull=False) | Q(version__isnull=False)
        ).select_related("user", "document", "version")

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        # The primary-owner guard only applies to document-level DELETE permissions.
        # Version-level rows never carry a DELETE permission_type and have no
        # meaningful "created_by" concept, so we skip the check for them entirely.
        is_document_permission = instance.document is not None
        if (
            is_document_permission
            and instance.permission_type == "DELETE"
            and instance.document.created_by == instance.user
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
        raw_doc_id = self.kwargs.get("doc_id")
            
        try:
            doc_id = uuid.UUID(str(raw_doc_id))
        except (ValueError, TypeError):
            # If not a valid UUID, return empty rather than crashing
            return DocumentPermissionModel.objects.none()

        user = self.request.user

        queryset = DocumentPermissionModel.objects.filter(
            Q(document_id=doc_id) | Q(version_id=doc_id)
        ).select_related("user", "document", "version").distinct()

        if not user.is_staff and not user.is_superuser:
            # Check if the requesting user has any link to this doc/version
            if not queryset.filter(user=user).exists():
                raise PermissionDenied("You do not have access to this document's member list.")

        return queryset


class GetAllDocumentPermissionsView(APIView):
    # Global permission list for dashboards
    # Staff see everything while users see docs they can manage
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        user = request.user

        base_queryset = DocumentPermissionModel.objects.select_related("user", "document")

        if user.is_staff or user.is_superuser:
            permissions = base_queryset.all()
        else:
            # Filter for docs where user has management rights
            manageable_docs = DocumentPermissionModel.objects.filter(
                user=user, 
                permission_type__in=["WRITE", "DELETE"]
            ).values('document_id')
            
            permissions = base_queryset.filter(document_id__in=manageable_docs)

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
    
class CreatePermissionRequestView(APIView):
    permission_classes = [IsAuthenticatedUser, HasDocumentDeletePermission]

    def post(self, request):
        print("CreatePermissionRequestView HIT")
        print(request.data)

        user_id = request.data.get("user")
        document_id = request.data.get("document")
        version_id = request.data.get("version")
        permission_type = request.data.get("permission_type")

        req, created = DocumentPermissionRequestModel.objects.get_or_create(
            user_id=user_id,
            document_id=document_id,
            version_id=version_id,
            permission_type=permission_type,
            defaults={"requested_by": request.user},
        )

        if not created:
            return Response(
                {"detail": "Request already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        NotificationModel.objects.create(
            recipient_id=user_id,
            user=request.user,
            verb=f"invited you as {permission_type}",
            target_document_id=document_id,
            permission_request=req,
        )

        return Response({"status": "request_sent"}, status=201)
