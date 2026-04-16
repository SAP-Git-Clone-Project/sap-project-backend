import uuid
import hashlib
import difflib
import cloudinary.uploader
import io
from urllib.parse import urlparse
import httpx
import requests
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
import traceback

import cloudinary.utils
import time
import re

from core.permissions import (
    HasDocumentReadPermission,
    HasDocumentWritePermission,
    IsAuthenticatedUser,
)
from core.rbac import can_review_document
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth import get_user_model

User = get_user_model()


def get_signed_url(file_path: str) -> str:
    if not file_path:
        return ""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    resource_type = "image" if ext in {"jpg", "jpeg", "png", "gif", "webp"} else "raw"

    parsed = urlparse(file_path)
    parts = parsed.path.split("/upload/", 1)
    if len(parts) < 2:
        return file_path

    after_upload = re.sub(r"^v\d+/", "", parts[1])

    signed_url, _ = cloudinary.utils.cloudinary_url(
        after_upload,
        resource_type=resource_type,
        type="upload",
        sign_url=True,
        expires_at=int(time.time()) + 300,
    )
    return signed_url


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
            # Documents
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            # Images (Existing + New)
            "image/jpeg",  # Covers .jpg and .jpeg
            "image/png",  # .png
            "image/gif",  # .gif
            "image/webp",  # .webp
            "image/svg+xml",  # .svg (Note the +xml suffix)
        ]

        if not (
            mime_type.startswith("text/")
            or mime_type in allowed_mimes
            or file.name.endswith(".doc")
            or file.name.endswith(".docx")
            or file.name.endswith(".pdf")
            or file.name.endswith(".txt")
        ):
            raise ValidationError(
                f"Asset Security Breach: File type '{mime_type}' is not authorized."
            )

    def get(self, request, id):
        from django.db.models import Exists, OuterRef

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

        versions = (
            VersionsModel.objects.filter(document=doc)
            .select_related(
                "created_by",
                "document",
                "document__created_by",
                "parent_version",
            )
            .order_by("-version_number")
        )

        is_owner = (
            request.user.is_superuser or 
            doc.created_by == request.user or 
            doc.document_permissions.filter(user=request.user, permission_type="DELETE").exists()
        )

        if not is_owner:
            versions = versions.exclude(status=VersionStatus.REJECTED)

        serializer = VersionSerializer(versions, many=True, context={"request": request})
        return Response(serializer.data)

    def get_cloudinary_resource_type(self, file_obj):
        """
        Cloudinary has three resource types:
        - 'image': actual images (jpg, png, gif, webp...)
        - 'video': video/audio files
        - 'raw':   everything else (pdf, docx, txt, csv...)
        """
        image_mimes = {"image/jpeg", "image/png", "image/gif", "image/webp"}

        chunk = file_obj.read(8192)
        file_obj.seek(0)

        try:
            matches = magic.magic_string(chunk)
            mime_type = matches[0].mime_type if matches else "application/octet-stream"
        except Exception:
            mime_type = "application/octet-stream"

        return "image" if mime_type in image_mimes else "raw"

    def post(self, request, id):
        try:
            if request.user.is_superuser:
                docs = DocumentModel.objects.all()
            else:
                docs = DocumentModel.objects.filter(
                    Q(created_by=request.user)
                    | Q(document_permissions__user=request.user)
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

            serializer = VersionSerializer(
                data=request.data, context={"request": request}
            )
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            checksum = generate_checksum(file_obj)

            last_v = (
                VersionsModel.objects.filter(document=doc)
                .order_by("version_number")
                .last()
            )

            new_version_number = (last_v.version_number + 1) if last_v else 1

            folder_path = (
                f"documents/{doc.created_by.id}/{doc.id}/v{new_version_number}"
            )

            try:
                resource_type = self.get_cloudinary_resource_type(file_obj)
                upload_result = cloudinary.uploader.upload(
                    file_obj,
                    folder=folder_path,
                    resource_type=resource_type,
                    use_filename=True,
                    unique_filename=True,
                    overwrite=False,
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
        serializer = VersionSerializer(version, context={"request": request})
        return Response(serializer.data)

    def patch(self, request, pk):
        version = get_authorized_version(request.user, pk)

        if version.status == VersionStatus.APPROVED:
            return Response(
                {"error": "Finalized versions are immutable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if "status" in request.data and not (request.user.is_staff or request.user.is_superuser):
            if request.data["status"] == VersionStatus.APPROVED and not can_review_document(
                request.user, version.document, version=version
            ):
                return Response(
                    {"error": "Only eligible reviewers or staff can approve versions."},
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

    def fetch_file_text(self, url):
        """
        Fetches text content from Cloudinary.
        Added follow_redirects=True because Cloudinary URLs often redirect to CDN nodes.
        """
        if not url:
            return None
        try:
            with httpx.Client(follow_redirects=True) as client:
                headers = {"User-Agent": "Mozilla/5.0"}
                r = client.get(url, timeout=10.0, headers=headers)
                if r.status_code == 200:
                    # Use r.text to get decoded string content
                    return r.text
                return None
        except Exception as e:
            print(f"Cloudinary Fetch Error: {str(e)}")
            return None

    def get(self, request, pk):
        # 1. Authorization
        version = get_authorized_version(request.user, pk)
        is_owner = version.document.created_by_id == request.user.id
        
        can_compare = (
            request.user.is_superuser
            or is_owner
            or can_review_document(request.user, version.document, version=version)
        )
        
        if not can_compare:
            return Response(
                {"detail": "Only superusers, document owner, or reviewers can compare versions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 2. Setup Base Version
        compare_to = request.query_params.get("compare_to")
        base_version = version.parent_version
        
        if compare_to:
            if str(compare_to) == str(version.id):
                return Response(
                    {"detail": "Current version cannot be compared with itself."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            base_version = get_object_or_404(
                VersionsModel.objects.filter(document_id=version.document_id),
                pk=compare_to,
            )
            if not request.user.is_superuser:
                get_authorized_version(request.user, base_version.id)

        # 3. Fetch New Content from Cloudinary
        current_signed_url = get_signed_url(version.file_path)
        current_file_text = self.fetch_file_text(current_signed_url)
        
        if current_file_text is None:
            return Response(
                {"can_compare": False, "message": f"Cloudinary error: Could not retrieve V{version.version_number}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        current_filename = version.file_path.split('/')[-1] if version.file_path else "current.txt"
        
        if not base_version:
            return Response({
                "can_compare": True,
                "has_parent": False, 
                "new_v": version.version_number,
                "new_filename": current_filename,
                "new_content": current_file_text, 
                "diff": []
            })

        # 4. Fetch Old Content from Cloudinary
        base_signed_url = get_signed_url(base_version.file_path)
        parent_file_text = self.fetch_file_text(base_signed_url)
        
        if parent_file_text is None:
            return Response(
                {"can_compare": False, "message": f"Cloudinary error: Could not retrieve V{base_version.version_number}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        base_filename = base_version.file_path.split('/')[-1] if base_version.file_path else "previous.txt"

        # 5. Diffing Logic
        # Clean lines to ensure \r\n doesn't mess up the comparison
        old_lines = parent_file_text.splitlines()
        new_lines = current_file_text.splitlines()

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
                "has_parent": True,
                "old_v": base_version.version_number,
                "new_v": version.version_number,
                "old_version_id": str(base_version.id),
                "new_version_id": str(version.id),
                "old_filename": base_filename,
                "new_filename": current_filename,
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


class VersionInheritedReviewersView(APIView):
    def get(self, request, pk):
        version = get_object_or_404(VersionsModel.objects.select_related('document'), pk=pk)
            
        # Fetch all versions for this document once
        all_versions = VersionsModel.objects.filter(
            document_id=version.document_id,
            version_number__lt=version.version_number
        ).values_list('id', flat=True)

        # Fetch all reviews for those versions in one query
        reviewer_ids = ReviewModel.objects.filter(
            version_id__in=all_versions
        ).values_list("reviewer", flat=True).distinct()

        users = User.objects.filter(id__in=reviewer_ids).only('id', 'username')

        return Response([
            {"id": u.id, "username": u.username} for u in users
        ])

    def get_inherited_reviewers(self, version):
        visited = set()
        reviewers = set()

        current = version.parent_version

        while current:
            if current.id in visited:
                break
            visited.add(current.id)

            # get reviewers from this version
            version_reviewers = ReviewModel.objects.filter(version=current).values_list(
                "reviewer", flat=True
            )

            reviewers.update(version_reviewers)

            current = current.parent_version

        return reviewers
