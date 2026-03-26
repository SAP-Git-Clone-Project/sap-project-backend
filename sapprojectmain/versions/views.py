import uuid
import hashlib
import cloudinary.uploader
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction  # ADDED

from .models import Versions, VersionStatus
from .serializers import VersionSerializer
from core.permissions import HasDocumentPermission

# CRITICAL: Import the Review model from your other app
from reviews.models import Reviews


def generate_checksum(file):
    sha256_hash = hashlib.sha256()
    file.seek(0)
    for byte_block in file.chunks():
        sha256_hash.update(byte_block)
    file.seek(0)
    return sha256_hash.hexdigest()


class DocumentVersionHandler(APIView):
    permission_classes = [HasDocumentPermission]

    def get(self, request, id):
        versions = Versions.objects.filter(document_id=id).order_by("-version_number")
        serializer = VersionSerializer(versions, many=True)
        return Response(serializer.data)

    def post(self, request, id):
        from documents.models import Documents

        doc = get_object_or_404(Documents, id=id)
        self.check_object_permissions(request, doc)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=400)

        # Generate Metadata
        file_size = file_obj.size
        checksum = generate_checksum(file_obj)
        temp_version_id = uuid.uuid4()

        try:
            # Upload to Cloudinary with Folder: documents/doc_id/version_id/
            upload_result = cloudinary.uploader.upload(
                file_obj,
                folder=f"documents/{doc.id}/{temp_version_id}",
                resource_type="auto",
            )
            file_url = upload_result.get("secure_url")
        except Exception as e:
            return Response({"error": f"Cloudinary error: {str(e)}"}, status=500)

        # Identify current active version to set as 'parent'
        parent = Versions.objects.filter(document=doc, is_active=True).first()
        serializer = VersionSerializer(data=request.data)

        if serializer.is_valid():
            # USE TRANSACTION: Save Version and Create Review as one unit
            with transaction.atomic():
                new_version = serializer.save(
                    id=temp_version_id,
                    document=doc,
                    parent_version=parent,
                    file_path=file_url,
                    file_size=file_size,
                    checksum=checksum,
                    status=VersionStatus.PENDING,  # Links to your pending logic
                )

                # TRIGGER: Create the review record so it shows in the reviewer's inbox
                Reviews.objects.create(version=new_version, review_status="pending")

            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)


class VersionDetailView(APIView):
    permission_classes = [HasDocumentPermission]

    def get(self, request, pk):
        version = get_object_or_404(Versions, pk=pk)
        return Response(VersionSerializer(version).data)

    def patch(self, request, pk):
        version = get_object_or_404(Versions, pk=pk)
        if version.status == VersionStatus.APPROVED:
            return Response({"error": "Approved versions are immutable."}, status=400)

        serializer = VersionSerializer(version, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        version = get_object_or_404(Versions, pk=pk)
        if version.is_active:
            return Response({"error": "Cannot delete active version."}, status=400)
        version.delete()
        return Response(status=204)

class VersionDiffView(APIView):
    permission_classes = [HasDocumentPermission]

    def get(self, request, pk):
        version = get_object_or_404(Versions, pk=pk)
        self.check_object_permissions(request, version.document)

        parent = version.parent_version
        return Response({
            "new_version": VersionSerializer(version).data,
            "old_version": VersionSerializer(parent).data if parent else None,
        })