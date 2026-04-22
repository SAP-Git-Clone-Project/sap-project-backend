import logging
import uuid
import hashlib
import difflib
import cloudinary.uploader
import io
import zipfile
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
from django.utils import timezone
from django.utils.text import slugify

import cloudinary.utils
import time
import re
from datetime import datetime
from zoneinfo import ZoneInfo

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
from core.rbac import can_review_document
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)

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
            # We use an OR (|) to allow access if ANY of these are true
            Q(document__created_by=user) |              # Owner of the doc
            Q(document__document_permissions__user=user) | # Invited to the doc
            Q(created_by=user) |                        # Creator of this version
            Q(is_active=True),                          # <--- PUBLIC ACCESS DOOR
            document__is_deleted=False,
        ).distinct(),
        pk=pk,
    )


# Uploads: extension must match detected content (magic bytes), not just one OR the other.
ALLOWED_EXTENSIONS = frozenset({"pdf", "doc", "docx", "txt"})

# Declared extension -> MIME types that are acceptable for that extension (normalized, no params).
EXTENSION_EXPECTED_MIMES = {
    "pdf": frozenset({"application/pdf"}),
    "doc": frozenset({"application/msword"}),
    "docx": frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
    "txt": frozenset({"text/plain", "text/markdown"}),
}

# Never treat as documents/images regardless of filename.
BLOCKLISTED_MIMES = frozenset(
    {
        "text/html",
        "application/javascript",
        "text/javascript",
        "application/x-javascript",
        "application/x-msdownload",
        "application/x-dosexec",
        "application/x-executable",
    }
)


def _normalize_mime(mime: str) -> str:
    if not mime:
        return ""
    return mime.split(";", 1)[0].strip().lower()


def _sniff_mime_from_bytes(chunk: bytes) -> str | None:
    """Fallback when magic returns octet-stream; signatures for allowed types only."""
    if not chunk:
        return None
    if chunk.startswith(b"%PDF"):
        return "application/pdf"
    if chunk.startswith(b"PK\x03\x04"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(chunk), "r")
            names = set(zf.namelist())
            zf.close()
            if "[Content_Types].xml" in names and any(
                n.startswith("word/") for n in names
            ):
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except Exception:
            return None
        return None
    if chunk.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/msword"
    return None


def _looks_like_plain_text(chunk: bytes) -> bool:
    if not chunk:
        return True
    if b"\x00" in chunk[:8192]:
        return False
    sample = chunk[:8192]
    try:
        s = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            s = sample.decode("latin-1")
        except Exception:
            return False
    if not s.strip():
        return True
    printable = sum(1 for c in s if c.isprintable() or c in "\n\r\t")
    return printable / max(len(s), 1) > 0.95


class DocumentVersionHandler(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [HasDocumentReadPermission()]
        return [HasDocumentWritePermission()]

    def validate_is_text_or_asset(self, file):
        """
        Extension and content must agree: magic bytes (and sniff fallback) must match
        the declared filename extension. Prevents e.g. malware.txt with real PE binary,
        or report.pdf with text/html payload.
        """
        filename = getattr(file, "name", "") or ""
        if "." not in filename:
            raise ValidationError(
                "File type not allowed: missing extension; declare a real file name."
            )

        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"File type not allowed: extension '.{ext}' is not permitted."
            )

        chunk = file.read(8192)
        file.seek(0)

        if not chunk:
            raise ValidationError(
                "File type not allowed: empty file cannot be validated."
            )

        try:
            matches = magic.magic_string(chunk)
            mime_raw = matches[0].mime_type if matches else None
        except Exception:
            mime_raw = None

        mime_norm = _normalize_mime(mime_raw or "")

        if mime_norm in BLOCKLISTED_MIMES:
            raise ValidationError(
                f"File type not allowed: content looks like '{mime_norm}' "
                f"which is not permitted for uploads."
            )

        if not mime_norm or mime_norm == "application/octet-stream":
            sniffed = _sniff_mime_from_bytes(chunk)
            if sniffed:
                mime_norm = sniffed
            elif ext == "txt" and _looks_like_plain_text(chunk):
                mime_norm = "text/plain"
            else:
                mime_norm = mime_norm or "application/octet-stream"

        expected = EXTENSION_EXPECTED_MIMES.get(ext)
        if not expected:
            raise ValidationError(f"File type not allowed: extension '.{ext}' is not permitted.")

        if mime_norm not in expected:
            raise ValidationError(
                f"File type not allowed: extension '.{ext}' does not match content "
                f"(detected '{mime_norm}'). Possible spoofing."
            )

    def get(self, request, id):
        from django.db.models import Exists, OuterRef, Q

        if request.user.is_superuser:
            docs = DocumentModel.objects.all()
        else:
            # Check if the document has any active versions
            has_active_version = VersionsModel.objects.filter(
                document=OuterRef('pk'), 
                is_active=True
            )

            docs = DocumentModel.objects.annotate(
                is_public=Exists(has_active_version)
            ).filter(
                Q(created_by=request.user) | 
                Q(document_permissions__user=request.user) |
                Q(is_public=True)  # <-- This allows Readers to find the doc
            ).distinct()

        # Now get_object_or_404 will succeed for Readers
        doc = get_object_or_404(docs, id=id)

        # 1. Fetch versions for this document
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

        # 2. Determine if user has "Management" rights
        is_owner = (
            request.user.is_superuser or 
            doc.created_by == request.user or 
            doc.document_permissions.filter(
                user=request.user, 
                permission_type__in=["DELETE", "WRITE"]
            ).exists()
        )

        # 3. Filter version visibility based on role
        if not is_owner:
            # Readers should only see active or approved versions, 
            # usually excluding rejected or draft versions.
            versions = versions.exclude(status=VersionStatus.REJECTED)
            # Optional: You might also want to filter for only active/approved:
            # versions = versions.filter(Q(is_active=True) | Q(status=VersionStatus.APPROVED))

        serializer = VersionSerializer(versions, many=True, context={"request": request})
        return Response(serializer.data)

    def get_cloudinary_resource_type(self, file_obj):
        """
        Only .doc / .docx / .pdf / .txt are allowed after validation — upload as raw.
        """
        return "raw"

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

        except ValidationError as e:
            messages = getattr(e, "messages", None)
            msg = messages[0] if messages else str(e)
            return Response({"error": msg}, status=status.HTTP_400_BAD_REQUEST)


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
            logger.exception(f"Cloudinary Fetch Error: %s", str(e))
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
        new_size = len(current_file_text.encode("utf-8"))

        if not base_version:
            return Response({
                "can_compare": True,
                "has_parent": False, 
                "new_v": version.version_number,
                "new_filename": current_filename,
                "new_content": current_file_text, 
                "old_size": 0,
                "new_size": new_size,
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

        old_size = len(parent_file_text.encode("utf-8"))
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
                "old_size": old_size,
                "new_size": new_size,
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
            or version.is_active
        )

        if not has_access:
            return Response(
                {"detail": "You do not have permission to access this resource."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            tz_sofia = ZoneInfo("Europe/Sofia")
        except Exception:
            tz_sofia = timezone.get_fixed_timezone(120)

        def format_uk_datetime(dt_value):
            if not dt_value:
                return "N/A"
            if dt_value.tzinfo is None:
                dt_value = dt_value.replace(tzinfo=tz_sofia)
            return dt_value.astimezone(tz_sofia).strftime("%d/%m/%Y %H:%M:%S")

        def format_file_size_bytes(size):
            if size is None:
                return "N/A"
            return f"{size} B"

        created_by = version.created_by

        def get_user_full_name(user_obj):
            if not user_obj:
                return "N/A"
            if hasattr(user_obj, "get_full_name") and callable(user_obj.get_full_name):
                full = (user_obj.get_full_name() or "").strip()
                if full:
                    return full
            first = (getattr(user_obj, "first_name", "") or "").strip()
            last = (getattr(user_obj, "last_name", "") or "").strip()
            combined = f"{first} {last}".strip()
            return combined or "N/A"

        created_by_details = (
            f"Username: {created_by.username} | User full name: {get_user_full_name(created_by)} | "
            f"User email: {created_by.email or 'N/A'} | User ID: {created_by.id}"
            if created_by
            else "N/A"
        )

        export_generated_at = datetime.now(tz_sofia).strftime("%d/%m/%Y %H:%M:%S")
        created_at_display = format_uk_datetime(version.created_at)
        file_size_display = format_file_size_bytes(version.file_size)

        safe_title = re.sub(r'[\\/:*?"<>|]+', " ", version.document.title).strip()
        safe_title = re.sub(r"\s+", " ", safe_title)
        ascii_title = slugify(safe_title)
        if not ascii_title:
            ascii_title = "document"
        filename = f"{ascii_title} v{version.version_number}"

        file_url = version.file_path or "N/A"

        if file_format == "txt":
            content = (
                f"DOCUMENT EXPORT\n"
                f"- {export_generated_at}\n"
                f"{'-'*40}\n"
                f"Document Title: {version.document.title}\n"
                f"Version: {version.version_number}\n"
                f"Status: {version.status}\n"
                f"Created By: {created_by_details}\n"
                f"Version Created At: {created_at_display} (BG Time)\n"
                f"Is Active: {version.is_active}\n"
                f"File URL: {file_url}\n"
                f"File Size: {file_size_display}\n"
                f"Checksum: {version.checksum or 'N/A'}\n"
                f"Parent Version: {version.parent_version_id or 'None'}\n"
                f"{'-'*40}\n"
            )

            response = HttpResponse(content, content_type="text/plain")
            response["Content-Disposition"] = f'attachment; filename="{filename}.txt"'
            return response

        if file_format == "pdf":
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=letter)
            page_width, page_height = letter

            left_margin = 50
            right_margin = 50
            max_text_width = page_width - left_margin - right_margin
            y = page_height - 40

            def line(text, font="Helvetica", size=10, gap=15):
                nonlocal y
                c.setFont(font, size)
                words = str(text).split(" ")
                wrapped_lines = []
                current_line = ""

                for word in words:
                    # Break single long tokens (e.g. URLs) so they never overflow margins.
                    if c.stringWidth(word, font, size) > max_text_width:
                        if current_line:
                            wrapped_lines.append(current_line)
                            current_line = ""
                        chunk = ""
                        for ch in word:
                            if c.stringWidth(f"{chunk}{ch}", font, size) <= max_text_width:
                                chunk = f"{chunk}{ch}"
                            else:
                                wrapped_lines.append(chunk)
                                chunk = ch
                        if chunk:
                            wrapped_lines.append(chunk)
                    else:
                        candidate = word if not current_line else f"{current_line} {word}"
                        if c.stringWidth(candidate, font, size) <= max_text_width:
                            current_line = candidate
                        else:
                            if current_line:
                                wrapped_lines.append(current_line)
                            current_line = word
                if current_line:
                    wrapped_lines.append(current_line)

                if not wrapped_lines:
                    wrapped_lines = [""]

                for wrapped in wrapped_lines:
                    if y <= 45:
                        c.showPage()
                        y = page_height - 40
                        c.setFont(font, size)
                    c.drawString(left_margin, y, wrapped)
                    y -= gap

            line(f"DOCUMENT EXPORT", "Helvetica-Bold", 14, 20)
            line(f"- {export_generated_at}")
            line(f"Document: {version.document.title}")
            line(f"Version: {version.version_number}")
            line(f"Status: {version.status}")
            line(f"Created By: {created_by_details}")
            line(f"Version Created At: {created_at_display} (BG Time)")
            line(f"Is Active: {version.is_active}")
            line(f"File URL: {file_url}")
            line(f"File Size: {file_size_display}")
            line(f"Checksum: {version.checksum or 'N/A'}")
            line(f"Parent Version: {version.parent_version_id or 'None'}")

            c.showPage()
            c.save()

            buffer.seek(0)

            return FileResponse(
                buffer,
                as_attachment=True,
                filename=f"{filename}.pdf"
            )

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
