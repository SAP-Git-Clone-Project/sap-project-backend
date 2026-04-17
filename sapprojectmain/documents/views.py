from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q, OuterRef, Subquery
import traceback
from django.db.models import Prefetch

from core.permissions import (
    HasDocumentReadPermission,
    HasDocumentWritePermission,
    HasDocumentDeletePermission,
    IsAuthenticatedUser,
)

from .models import (
    DocumentModel,
    DocumentDeletionDecisionModel,
    DocumentDeletionRequestModel,
)
from versions.models import VersionsModel
from .serializers import DocumentSerializer
from document_permissions.serializers import DocumentPermissionSerializer
from document_permissions.models import DocumentPermissionModel
from core.rbac import user_has_global_role
from user_roles.models import Role
from rest_framework.pagination import PageNumberPagination
from itertools import groupby


class DocumentPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 1000


# ---------------------------------------------------------------------------
# Helper — shared deletion-request logic (used by both delete endpoints)
# ---------------------------------------------------------------------------


def initiate_deletion_with_notifications(request, document):
    """
    Check reviewers, create a DeletionRequest, notify each reviewer via
    NotificationModel, and return a DRF Response.

    Returns None if the document was deleted immediately (no active version
    or no reviewers), in which case callers should handle their own response.
    Returns a Response(202) when approval flow is started.
    """
    from notifications.models import NotificationModel  # local import — avoids circular

    active_version = VersionsModel.objects.filter(
        document=document, is_active=True
    ).first()

    if not active_version:
        document.delete()
        return Response(
            {"detail": "Document deleted successfully"},
            status=status.HTTP_200_OK,
        )

    reviewers = DocumentPermissionModel.objects.filter(
        document=document,
        permission_type="APPROVE",
        version__isnull=True,
    ).select_related("user")

    if not reviewers.exists():
        document.delete()
        return Response(
            {"detail": "Document deleted (no reviewers found)"},
            status=status.HTTP_200_OK,
        )

    # Create or reuse a PENDING deletion request
    deletion_request, created = DocumentDeletionRequestModel.objects.get_or_create(
        document=document,
        requested_by=request.user,
        defaults={"status": "PENDING"},
    )

    # Reset any previous decisions so the vote starts fresh
    DocumentDeletionDecisionModel.objects.filter(document=document).delete()

    # Create a PENDING decision slot and a notification for each reviewer
    for rp in reviewers:
        reviewer = rp.user

        DocumentDeletionDecisionModel.objects.get_or_create(
            document=document,
            reviewer_id=reviewer,
            defaults={"decision": "PENDING"},
        )

        NotificationModel.objects.create(
            recipient=reviewer,
            user=request.user,  # who triggered the action
            target_document=document,
            verb=f"requested deletion of",
            deletion_request=deletion_request,
            is_read=False,
        )

    return Response(
        {
            "detail": "Deletion approval required from reviewers",
            "status": "PENDING",
            "request_id": str(deletion_request.id),
            "reviewers": [rp.user.username for rp in reviewers],
        },
        status=status.HTTP_202_ACCEPTED,
    )


# ---------------------------------------------------------------------------
# Consolidated Document Detail View
# ---------------------------------------------------------------------------


class DocumentDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [HasDocumentReadPermission()]
        if self.request.method in ["PUT", "PATCH"]:
            return [HasDocumentWritePermission()]
        if self.request.method == "DELETE":
            return [HasDocumentDeletePermission()]
        return [IsAuthenticatedUser()]

    def get_object(self, id):
        user = self.request.user
        try:
            # 1. Staff/Superusers skip checks
            if user.is_staff or user.is_superuser:
                return DocumentModel.objects.get(pk=id)

            # 2. Main query: User's visible docs OR any document with an active version
            # We use .distinct() because the join with versions might return multiple rows
            document = DocumentModel.objects.filter(
                Q(pk=id) & (
                    Q(id__in=DocumentModel.objects.visible_documents(user=user).values('id')) |
                    Q(versions__is_active=True)
                )
            ).distinct().first()

            # 3. Fallback: Creator checking their own deleted trash
            if not document:
                document = DocumentModel.objects.filter(
                    pk=id, 
                    created_by=user, 
                    is_deleted=True
                ).first()

            return document

        except (DocumentModel.DoesNotExist, ValueError):
            return None

    def get(self, request, id):
        document = self.get_object(id)
        if not document:
            return Response(
                {"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND
            )
        serializer = DocumentSerializer(document, context={"request": request})
        return Response(serializer.data)

    def put(self, request, id):
        document = self.get_object(id)
        if not document:
            return Response(
                {"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND
            )
        
        self.check_object_permissions(request, document)

        serializer = DocumentSerializer(
            document, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        document = self.get_object(id)
        if not document:
            return Response(
                {"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND
            )

        return initiate_deletion_with_notifications(request, document)


# ---------------------------------------------------------------------------
# Collection & Sharing Views
# ---------------------------------------------------------------------------


class DocumentListCreateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        user = request.user
        if user.is_superuser:
            documents = DocumentModel.objects.all().select_related('created_by')
        elif user.is_staff:
            documents = DocumentModel.objects.active_documents().select_related('created_by')
        else:
            visible_doc_ids = DocumentModel.objects.visible_documents(user=user).values_list(
                "id", flat=True
            )
            documents = (
                DocumentModel.objects.filter(
                    Q(id__in=visible_doc_ids) | Q(created_by=user, is_deleted=True)
                )
                .distinct()
                .select_related("created_by")
            )

        # PERF:
        # - Fetch only what the list view needs for "active_version" rendering.
        # - Prefetch current user's permission rows once to avoid N+1 in serializer.
        documents = (
            documents.select_related("created_by")
            .prefetch_related(
                Prefetch(
                    "versions",
                    queryset=VersionsModel.objects.filter(is_active=True).select_related(
                        "created_by",
                        "parent_version",
                        "document",
                    ),
                    to_attr="prefetched_active_versions",
                ),
                Prefetch(
                    "document_permissions",
                    queryset=DocumentPermissionModel.objects.filter(
                        user=user, version__isnull=True
                    ).only("document_id", "permission_type", "user_id", "version_id"),
                    to_attr="prefetched_current_user_permissions",
                ),
            )
            .order_by("-updated_at")
        )

        status = self.request.query_params.get("status")
        if status:
            filtered = documents.filter(versions__status=status, versions__is_active=True).distinct()
            if not filtered:
                latest_version_status = VersionsModel.objects.filter(document=OuterRef('pk')).order_by('-is_active', '-version_number').values('status')[:1]
                filtered = documents.annotate(current_version_status=Subquery(latest_version_status)).filter(current_version_status=status)
            documents = filtered

        search = self.request.query_params.get("search")
        if search:
            documents = documents.filter(title__icontains=search)

        # Apply pagination
        paginator = DocumentPagination()
        page = paginator.paginate_queryset(documents, request)

        # PERF: If a document has no active version, the serializer may need the latest version
        # (for owners/superusers/users with permissions). Fetch those latest versions in bulk.
        page_docs = list(page or [])
        if page_docs:
            doc_ids = [d.id for d in page_docs]
            latest_versions = (
                VersionsModel.objects.filter(document_id__in=doc_ids)
                .select_related("created_by", "parent_version", "document")
                .order_by("document_id", "-version_number")
            )
            latest_by_doc_id = {}
            for doc_id, versions in groupby(latest_versions, key=lambda v: v.document_id):
                latest_by_doc_id[doc_id] = next(versions, None)
            for d in page_docs:
                d._latest_version = latest_by_doc_id.get(d.id)

        serializer = DocumentSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if request.user.is_staff:
            return Response(
                {"detail": "Staff users cannot create documents."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not request.user.is_superuser and not user_has_global_role(
            request.user, Role.RoleName.AUTHOR
        ):
            return Response(
                {"detail": "Only users with author role can create documents."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = DocumentSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DocumentListGetAllView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        user = request.user
        if user.is_superuser:
            documents = DocumentModel.objects.all()
        elif user.is_staff:
            documents = DocumentModel.objects.active_documents()
        else:
            visible_doc_ids = DocumentModel.objects.visible_documents(user=user).values_list(
                "id", flat=True
            )
            documents = DocumentModel.objects.filter(
                Q(id__in=visible_doc_ids) | Q(created_by=user, is_deleted=True)
            ).distinct()

        # PERF: This endpoint is used by the frontend for dashboard stats.
        # Keep it lightweight: only prefetch active versions + current user perms,
        # and avoid expensive "latest version fallback" work in the serializer.
        documents = (
            documents.select_related("created_by")
            .prefetch_related(
                Prefetch(
                    "versions",
                    queryset=VersionsModel.objects.filter(is_active=True).select_related(
                        "created_by",
                        "parent_version",
                        "document",
                    ),
                    to_attr="prefetched_active_versions",
                ),
                Prefetch(
                    "document_permissions",
                    queryset=DocumentPermissionModel.objects.filter(
                        user=user, version__isnull=True
                    ).only("document_id", "permission_type", "user_id", "version_id"),
                    to_attr="prefetched_current_user_permissions",
                ),
            )
            .order_by("-updated_at")
        )

        # PERF: provide latest version in bulk for stats_mode fallback
        # (active version if present, else latest by version_number).
        doc_list = list(documents)
        if doc_list:
            doc_ids = [d.id for d in doc_list]
            latest_versions = (
                VersionsModel.objects.filter(document_id__in=doc_ids)
                .select_related("created_by", "parent_version", "document")
                .order_by("document_id", "-version_number")
            )
            latest_by_doc_id = {}
            for doc_id, versions in groupby(latest_versions, key=lambda v: v.document_id):
                latest_by_doc_id[doc_id] = next(versions, None)
            for d in doc_list:
                d._latest_version = latest_by_doc_id.get(d.id)

        serializer = DocumentSerializer(
            doc_list, many=True, context={"request": request, "stats_mode": True}
        )
        return Response(serializer.data)


class ShareDocumentView(APIView):
    permission_classes = [HasDocumentWritePermission]

    def post(self, request, id):
        serializer = DocumentPermissionSerializer(
            data=request.data, context={"document_id": id, "request": request}
        )
        if serializer.is_valid():
            try:
                document = DocumentModel.objects.active_documents().get(pk=id)
            except DocumentModel.DoesNotExist:
                return Response(
                    {"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND
                )
            serializer.save(document=document)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DocumentRestoreView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, id):
        try:
            document = DocumentModel.objects.all().get(pk=id)
        except (DocumentModel.DoesNotExist, ValueError):
            return Response(
                {"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND
            )

        is_owner = str(document.created_by_id) == str(request.user.id)
        if not (request.user.is_superuser or request.user.is_staff or is_owner):
            return Response(
                {"detail": "You do not have permission to restore this document."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not document.is_deleted:
            return Response(
                {"detail": "Document is already active."},
                status=status.HTTP_200_OK,
            )

        document.restore()
        serializer = DocumentSerializer(document, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Deletion Decision View  (reviewer casts APPROVED / REJECTED)
# ---------------------------------------------------------------------------


class DocumentDeletionDecisionView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, id):
        decision_value = request.data.get("decision")  # "APPROVED" or "REJECTED"

        if decision_value not in ("APPROVED", "REJECTED"):
            return Response(
                {"detail": "Invalid decision value."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            document = DocumentModel.objects.get(pk=id)
        except DocumentModel.DoesNotExist:
            return Response(
                {"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Record this reviewer's decision
        DocumentDeletionDecisionModel.objects.update_or_create(
            document=document,
            reviewer_id=request.user,
            defaults={"decision": decision_value},
        )

        # --- Check consensus ---
        reviewer_ids = set(
            DocumentPermissionModel.objects.filter(
                document=document, permission_type="APPROVE"
            ).values_list("user", flat=True)
        )

        decisions = DocumentDeletionDecisionModel.objects.filter(document=document)
        approved_ids = set(
            decisions.filter(decision="APPROVED").values_list("reviewer_id", flat=True)
        )
        rejected_exists = decisions.filter(decision="REJECTED").exists()

        # Update the DeletionRequest status so notifications stay in sync
        deletion_request = (
            DocumentDeletionRequestModel.objects.filter(document=document)
            .order_by("-created_at")
            .first()
        )

        if rejected_exists:
            if deletion_request:
                deletion_request.status = "REJECTED"
                deletion_request.save()

            # Ensure the document is NOT deleted.
            # If it was soft-deleted by an earlier action, restore it.
            if document.is_deleted:
                document.restore()
                
            # Notify the owner that deletion was rejected
            notify_owner_of_decision(document, deletion_request, accepted=False)
            return Response({"detail": "Deletion rejected."}, status=status.HTTP_200_OK)

        if reviewer_ids and reviewer_ids == approved_ids:
            if deletion_request:
                deletion_request.status = "APPROVED"
                deletion_request.save()
            document.delete()  # soft-delete via overridden delete()
            return Response(
                {"detail": "Document deleted after unanimous approval."},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"detail": "Decision recorded, waiting for other reviewers."},
            status=status.HTTP_200_OK,
        )


def notify_owner_of_decision(document, deletion_request, accepted: bool):
    """Send the document owner a notification about the final deletion decision."""
    from notifications.models import NotificationModel  # local import

    if not deletion_request:
        return

    owner = deletion_request.requested_by
    verb = "approved deletion of" if accepted else "rejected deletion of"

    NotificationModel.objects.create(
        recipient=owner,
        user=owner,
        target_document=document,
        verb=verb,
        deletion_request=deletion_request,
        is_read=False,
    )


# ---------------------------------------------------------------------------
# DocumentRequestDeleteView  (owner explicitly requests deletion via POST)
# ---------------------------------------------------------------------------


class DocumentRequestDeleteView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, id):
        document = self.get_object(id)
        if not document:
            return Response(
                {"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND
            )

        return initiate_deletion_with_notifications(request, document)
        
    def get_object(self, id):
        try:
            if self.request.user.is_superuser:
                return DocumentModel.objects.get(pk=id)
            return DocumentModel.objects.all().get(pk=id)
        except (DocumentModel.DoesNotExist, ValueError):
            return None
