import uuid
import hashlib
import difflib
import cloudinary.uploader
import io
from urllib.parse import urlparse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

import puremagic as magic
from django.core.exceptions import ValidationError

from .models import VersionsModel, VersionStatus
from reviews.models import ReviewModel, ReviewStatus
from documents.models import DocumentModel
from .serializers import VersionSerializer

from core.permissions import (
    HasDocumentReadPermission,
    HasDocumentWritePermission,
    IsAuthenticatedUser,
)
from rest_framework.permissions import IsAuthenticated


def generate_checksum(file):
    sha256_hash = hashlib.sha256()
    file.seek(0)
    for byte_block in file.chunks():
        sha256_hash.update(byte_block)
    file.seek(0)
    return sha256_hash.hexdigest()


def get_authorized_version(user, pk):
    if user.is_superuser:
        return get_object_or_404(VersionsModel, pk=pk)
    
    base_qs = VersionsModel.objects.select_related("document")

    return get_object_or_404(
        base_qs.filter(
            Q(document__created_by=user)
            | Q(document__document_permissions__user=user)
            | Q(created_by=user),
            document__is_deleted=False,
        ).distinct(),
        pk=pk,
    )


ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg"}


class DocumentVersionHandler(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [HasDocumentReadPermission()]
        return [HasDocumentWritePermission()]
    
    def validate_is_text_or_asset(self, file):
        chunk = file.read(8192)

        try:
            matches = magic.magic_string(chunk)
            mime_type = matches[0].mime_type if matches else None
            if not mime_type:
                # fall back to checking the file extension via puremagic
                mime_type = magic.from_file(file.name)
        except Exception:
            mime_type = "application/octet-stream"

        file.seek(0)

        allowed_mimes = [
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'image/jpeg',
            'image/png'
        ]

        if not (
            mime_type.startswith('text/')
            or mime_type in allowed_mimes
            or file.name.endswith('.doc')
            or file.name.endswith('.docx')
        ):
            raise ValidationError(
                f"Asset Security Breach: File type '{mime_type}' is not authorized."
            )

    def get(self, request, id):
        if request.user.is_superuser:
            docs = DocumentModel.objects.all()
        else:
            docs = DocumentModel.objects.filter(
                Q(created_by=request.user) | Q(document_permissions__user=request.user)
            ).distinct()

        doc = get_object_or_404(
            docs,
            id=id,
        )

        if not request.user.is_superuser:
            if doc.is_deleted:
                return Response({"detail": "You can't access a version associated with a deleted document"}, status=status.HTTP_404_NOT_FOUND)

        versions = VersionsModel.objects.filter(document=doc).order_by(
            "-version_number"
        )

        is_owner = (
            doc.created_by == request.user
            or doc.document_permissions.filter(
                user=request.user, permission_type="DELETE"
            ).exists()
        )

        if not is_owner and not request.user.is_superuser:
            versions = versions.exclude(status=VersionStatus.REJECTED)

        serializer = VersionSerializer(versions, many=True)
        return Response(serializer.data)

    def post(self, request, id):
        try:
            if request.user.is_superuser:
                docs = DocumentModel.objects.all()
            else:
                docs = DocumentModel.objects.filter(
                    Q(created_by=request.user) | Q(document_permissions__user=request.user)
                ).distinct()

            doc = get_object_or_404(
                docs,
                id=id,
            )

            file_obj = request.FILES.get("file")

            if not file_obj:
                return Response(
                    {"error": "No file uploaded"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            self.validate_is_text_or_asset(file_obj)
                
            serializer = VersionSerializer(data=request.data, context={"request": request})
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            checksum = generate_checksum(file_obj)

            last_v = (
                VersionsModel.objects.filter(document=doc).order_by("version_number").last()
            )

            new_version_number = (last_v.version_number + 1) if last_v else 1

            folder_path = f"documents/{doc.created_by.id}/{doc.id}/v{new_version_number}"

            try:
                upload_result = cloudinary.uploader.upload(
                    file_obj,
                    folder=folder_path,
                    resource_type="auto",
                )
                file_url = upload_result.get("secure_url")
            except Exception as e:
                return Response(
                    {"error": f"Cloudinary error: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            with transaction.atomic():
                new_version = serializer.save(
                    document=doc,
                    version_number=new_version_number,
                    file_path=file_url,
                    file_size=file_obj.size,
                    checksum=checksum,
                    status=VersionStatus.DRAFT,
                    created_by=request.user,
                    parent_version=last_v,
                )
                
            return Response(serializer.data, status=status.HTTP_201_CREATED)
    
        except Exception as ve:
            print(ve)


class VersionDetailView(APIView):
    def get_permissions(self):
        if self.request.method in ["GET", "HEAD", "OPTIONS"]:
            return [HasDocumentReadPermission()]
        return [HasDocumentWritePermission()]

    def get(self, request, pk):
        version = get_authorized_version(request.user, pk)
        serializer = VersionSerializer(version)
        return Response(serializer.data)

    def patch(self, request, pk):
        version = get_authorized_version(request.user, pk)

        if version.status == VersionStatus.APPROVED:
            return Response(
                {"error": "Finalized versions are immutable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if "status" in request.data and not request.user.is_staff:
            if request.data["status"] == VersionStatus.APPROVED:
                return Response(
                    {"error": "Only reviewers or staff can approve versions."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = VersionSerializer(
            version,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VersionDiffView(APIView):
    permission_classes = [HasDocumentReadPermission]

    def get(self, request, pk):

        version = get_authorized_version(request.user, pk)

        # FIX 4: Cloudinary URLs have query params — parse properly
        binary_exts = ["pdf", "zip", "docx", "jpg", "png"]
        raw_path = urlparse(version.file_path).path if version.file_path else ""
        ext = raw_path.rsplit(".", 1)[-1].lower() if "." in raw_path else ""

        if ext in binary_exts or not version.content:
            return Response(
                {
                    "can_compare": False,
                    "message": "Direct text comparison not supported for this file type.",
                    "file_url": version.file_path,
                }
            )

        parent = version.parent_version

        if not parent:
            return Response(
                {"has_parent": False, "new_content": version.content, "diff": []}
            )

        old_lines = (parent.content or "").splitlines()
        new_lines = (version.content or "").splitlines()

        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        diff_output = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for line in old_lines[i1:i2]:
                    diff_output.append({"type": "equal", "value": line})
            elif tag in ("delete", "replace"):
                for line in old_lines[i1:i2]:
                    diff_output.append({"type": "delete", "value": line})
            if tag in ("insert", "replace"):
                for line in new_lines[j1:j2]:
                    diff_output.append({"type": "insert", "value": line})

        return Response(
            {
                "can_compare": True,
                "old_v": parent.version_number,
                "new_v": version.version_number,
                "diff": diff_output,
            }
        )


class VersionExportView(APIView):
    permission_classes = [IsAuthenticated, HasDocumentReadPermission]

    def get(self, request, pk, file_format):

        version = get_object_or_404(VersionsModel, pk=pk)

        user = request.user

        has_access = (
            user.is_superuser
            or version.created_by == user
            or version.document.created_by == user
            or version.document.document_permissions.filter(user=user).exists()
        )

        if not has_access:
            return Response(
                {"detail": "You do not have permission to access this resource."},
                status=status.HTTP_403_FORBIDDEN,
            )

        filename = f"{version.document.title}_v{version.version_number}"

        if file_format == "txt":
            header = (
                f"DOC: {version.document.title}\n"
                f"VER: {version.version_number}\n"
                f"BY: {version.created_by.username}\n" + ("-" * 20) + "\n\n"
            )

            content = header + (
                version.content or "Binary file content cannot be displayed."
            )

            response = HttpResponse(content, content_type="text/plain")
            response["Content-Disposition"] = f'attachment; filename="{filename}.txt"'
            return response

        if file_format == "pdf":
            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)

            p.setFont("Helvetica-Bold", 14)
            p.drawString(50, 750, f"Document: {version.document.title}")

            p.setFont("Helvetica", 10)
            p.drawString(
                50,
                735,
                f"Version: {version.version_number} | Author: {version.created_by.username}",
            )

            p.line(50, 725, 550, 725)

            p.setFont("Courier", 9)
            text = p.beginText(50, 700)

            for line in (version.content or "Binary file content.").splitlines()[:60]:
                text.textLine(line)

            p.drawText(text)
            p.showPage()
            p.save()

            buffer.seek(0)
            return FileResponse(buffer, as_attachment=True, filename=f"{filename}.pdf")

        return Response(
            {"error": "Invalid format. Use 'pdf' or 'txt'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
