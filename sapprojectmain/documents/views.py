from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import (
    HasDocumentReadPermission,
    HasDocumentWritePermission,
    HasDocumentDeletePermission,
    IsAuthenticatedUser,
)

from .models import DocumentModel
from .serializers import DocumentSerializer
from document_permissions.serializers import DocumentPermissionSerializer

# --- CONSOLIDATED DOCUMENT DETAIL VIEW ---


class DocumentDetailView(APIView):
    def get_permissions(self):
        # NOTE: Dynamically assign permissions based on request method
        if self.request.method == "GET":
            # NOTE: READ permission check
            return [HasDocumentReadPermission()]
        if self.request.method in ["PUT", "PATCH"]:
            # NOTE: WRITE permission check
            return [HasDocumentWritePermission()]
        if self.request.method == "DELETE":
            # NOTE: DELETE permission check for owners
            return [HasDocumentDeletePermission()]
        return [IsAuthenticatedUser()]

    def get_object(self, id):
        # NOTE: Uses active_documents manager to exclude soft-deleted records
        try:
            return DocumentModel.objects.active_documents().get(pk=id)
        except (DocumentModel.DoesNotExist, ValueError):
            return None

    def get(self, request, id):
        # NOTE: GET details of a specific active document
        document = self.get_object(id)
        if not document:
            return Response({"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = DocumentSerializer(document)
        return Response(serializer.data)

    def put(self, request, id):
        # NOTE: Updates document title or content
        document = self.get_object(id)
        if not document:
            return Response(
                {"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # NOTE: Partial update allows changing specific fields like title
        serializer = DocumentSerializer(
            document, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        # NOTE: Triggers model level soft-delete logic
        document = self.get_object(id)
        if not document:
            return Response(
                {"detail": "Document not found"}, status=status.HTTP_404_NOT_FOUND
            )

        document.delete()
        return Response(
            {"detail": "Document deleted successfully"}, status=status.HTTP_200_OK
        )


# --- COLLECTION & SHARING VIEWS ---


class DocumentListCreateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        # NOTE: Lists documents accessible to the user
        user = request.user
        if user.is_superuser:
            documents = DocumentModel.objects.get_queryset()
        elif user.is_staff:
            # NOTE: Superusers can see all active documents
            documents = DocumentModel.objects.active_documents()
        else:
            # SECURITY: Checks permission table across app boundaries
            documents = (
                DocumentModel.objects.visible_documents(user)
                .filter(document_permissions__user=user)
                .distinct()
            )

        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data)

    def post(self, request):
        # NOTE: Triggers manager to create doc and auto-grant delete rights
        serializer = DocumentSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            document = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ShareDocumentView(APIView):
    # NOTE: Handles document sharing via access invite
    # SECURITY: Only users with WRITE rights can share or invite
    permission_classes = [HasDocumentWritePermission]

    def post(self, request, id):
        # NOTE: Pass doc ID to context for update_or_create logic
        serializer = DocumentPermissionSerializer(
            data=request.data, context={"document_id": id, "request": request}
        )

        if serializer.is_valid():
            # IMP: Ensure sharing is performed on an active document
            try:
                document = DocumentModel.objects.active_documents().get(pk=id)
            except DocumentModel.DoesNotExist:
                return Response({"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)
            serializer.save(document=document)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
