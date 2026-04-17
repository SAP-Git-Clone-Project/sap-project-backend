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
from versions.models import VersionsModel
from documents.models import DocumentModel

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
    serializer_class = DocumentPermissionSerializer
    permission_classes = [IsAuthenticatedUser] 

    def get_queryset(self):
        raw_doc_id = self.kwargs.get("doc_id")
        try:
            obj_id = uuid.UUID(str(raw_doc_id))
        except (ValueError, TypeError):
            return DocumentPermissionModel.objects.none()

        user = self.request.user
        
        version = VersionsModel.objects.filter(pk=obj_id).first()

        if version:
            is_version_path = True
            document_id = version.document_id
            version_id = version.id
            has_active_version = version.is_active
        else:
            is_version_path = False
            document_id = obj_id
            has_active_version = VersionsModel.objects.filter(
                document_id=document_id,
                is_active=True
            ).exists()

        # 1. Staff Bypass
        if user.is_staff or user.is_superuser:
            return self._apply_filters(obj_id, is_version_path)

        # 2. Logic to determine access
        document_id = None
        version_id = None
        has_active_version = False

        if is_version_path:
            # We are looking at members of a SPECIFIC version
            document_id = version.document_id
            version_id = version.id
            has_active_version = version.is_active
        else:
            # We are looking at members of a DOCUMENT
            document_id = obj_id
            # Check if ANY version of this document is active
            has_active_version = VersionsModel.objects.filter(
                document_id=document_id,
                is_active=True
            ).exists()

        # 3. Check for ownership or explicit invitation
        is_owner_or_invited = DocumentModel.objects.filter(pk=document_id).filter(
            Q(created_by=user) | Q(document_permissions__user=user)
        ).exists()

        # 4. The Final Gate
        # If the version/doc is active, we don't care about is_owner_or_invited
        if not (has_active_version or is_owner_or_invited):
            raise PermissionDenied("You do not have clearance to view this document's members.")

        return self._apply_filters(document_id, is_version_path, version_id)

    def _apply_filters(self, document_id, is_version_path, version_id=None):
        # If it's a version path, we strictly show version permissions
        if is_version_path and version_id:
            queryset = DocumentPermissionModel.objects.filter(version_id=version_id)
            # queryset = queryset.filter(permission_type="APPROVE")
        else:
            # Otherwise, show all permissions for the document
            queryset = DocumentPermissionModel.objects.filter(document_id=document_id)

        # Apply role filters from query params
        role_filter = self.request.query_params.get("role")
        if role_filter:
            queryset = queryset.filter(user__user_roles__role__role_name=role_filter)

        return queryset.select_related("user", "document").distinct()


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
