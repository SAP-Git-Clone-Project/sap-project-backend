from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
import traceback

from core.permissions import (
    HasDocumentReadPermission,
    HasDocumentWritePermission,
    HasDocumentDeletePermission,
    IsAuthenticatedUser,
)

from .models import DocumentModel, DocumentDeletionDecisionModel, DocumentDeletionRequestModel
from versions.models import VersionsModel
from .serializers import DocumentSerializer
from document_permissions.serializers import DocumentPermissionSerializer
from document_permissions.models import DocumentPermissionModel


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
    from notifications.models import NotificationModel   # local import — avoids circular

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
            user=request.user,                    # who triggered the action
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
        try:
            if self.request.user.is_superuser:
                return DocumentModel.objects.all().get(pk=id)
            return DocumentModel.objects.active_documents().get(pk=id)
        except (DocumentModel.DoesNotExist, ValueError):
            return None

    def get(self, request, id):
        document = self.get_object(id)
        if not document:
            return Response({"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = DocumentSerializer(document, context={"request": request})
        return Response(serializer.data)

    def put(self, request, id):
        document = self.get_object(id)
        if not document:
            return Response({"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND)
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
            return Response({"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND)

        return initiate_deletion_with_notifications(request, document)


# ---------------------------------------------------------------------------
# Collection & Sharing Views
# ---------------------------------------------------------------------------

class DocumentListCreateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        user = request.user
        if user.is_superuser:
            documents = DocumentModel.objects.all()
        elif user.is_staff:
            documents = DocumentModel.objects.active_documents()
        else:
            documents = DocumentModel.objects.visible_documents(user=user)

        documents = documents.order_by("-updated_at")
        serializer = DocumentSerializer(documents, many=True, context={"request": request})
        return Response(serializer.data)

    def post(self, request):
        if request.user.is_staff:
            return Response(
                {"detail": "Staff users cannot create documents."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = DocumentSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
                return Response({"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)
            serializer.save(document=document)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Deletion Decision View  (reviewer casts APPROVED / REJECTED)
# ---------------------------------------------------------------------------

class DocumentDeletionDecisionView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, id):
        decision_value = request.data.get("decision")  # "APPROVED" or "REJECTED"

        if decision_value not in ("APPROVED", "REJECTED"):
            return Response({"detail": "Invalid decision value."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            document = DocumentModel.objects.get(pk=id)
        except DocumentModel.DoesNotExist:
            return Response({"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

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
        approved_ids = set(decisions.filter(decision="APPROVED").values_list("reviewer_id", flat=True))
        rejected_exists = decisions.filter(decision="REJECTED").exists()

        # Update the DeletionRequest status so notifications stay in sync
        deletion_request = DocumentDeletionRequestModel.objects.filter(
            document=document
        ).order_by("-created_at").first()

        if rejected_exists:
            if deletion_request:
                deletion_request.status = "REJECTED"
                deletion_request.save()
            # Notify the owner that deletion was rejected
            notify_owner_of_decision(document, deletion_request, accepted=False)
            return Response({"detail": "Deletion rejected."}, status=status.HTTP_200_OK)

        if reviewer_ids and reviewer_ids == approved_ids:
            if deletion_request:
                deletion_request.status = "APPROVED"
                deletion_request.save()
            document.delete()  # soft-delete via overridden delete()
            return Response({"detail": "Document deleted after unanimous approval."}, status=status.HTTP_200_OK)

        return Response({"detail": "Decision recorded, waiting for other reviewers."}, status=status.HTTP_200_OK)


def notify_owner_of_decision(document, deletion_request, accepted: bool):
    """Send the document owner a notification about the final deletion decision."""
    from notifications.models import NotificationModel   # local import

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
        try:
            document = self.get_object(id)
            if not document:
                return Response({"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND)

            return initiate_deletion_with_notifications(request, document)

        except Exception as e:
            traceback.print_exc()
            return Response({"detail": "Internal server error"}, status=500)

    def get_object(self, id):
        try:
            if self.request.user.is_superuser:
                return DocumentModel.objects.get(pk=id)
            return DocumentModel.objects.active_documents().get(pk=id)
        except (DocumentModel.DoesNotExist, ValueError):
            return None