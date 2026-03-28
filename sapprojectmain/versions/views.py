import uuid
import hashlib
import difflib
import cloudinary.uploader
import io
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.http import FileResponse, HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# Model/Serializer Imports
from .models import VersionsModel, VersionStatus
from .serializers import VersionSerializer

# Permission Imports
from core.permissions import HasDocumentReadPermission, HasDocumentWritePermission


def generate_checksum(file):
    # NOTE: Generates a SHA-256 hash to ensure file integrity and detect changes
    sha256_hash = hashlib.sha256()
    file.seek(0)
    for byte_block in file.chunks():
        sha256_hash.update(byte_block)
    file.seek(0)
    return sha256_hash.hexdigest()


# --- COLLECTION HANDLER (LIST & UPLOAD) ---


class DocumentVersionHandler(APIView):
    def get_permissions(self):
        # NOTE: GET requires read access while POST requires write permissions
        if self.request.method == "GET":
            return [HasDocumentReadPermission()]
        return [HasDocumentWritePermission()]

    def get(self, request, id):
        from documents.models import DocumentModel

        doc = get_object_or_404(DocumentModel, id=id)

        versions = VersionsModel.objects.filter(document=doc).order_by(
            "-version_number"
        )

        # NOTE: Restricts visibility of rejected versions to owners or admins
        is_owner = (
            doc.created_by == request.user
            or doc.document_permissions.filter(
                user=request.user, permission_type="DELETE"
            ).exists()
        )

        if not is_owner:
            versions = versions.exclude(status=VersionStatus.REJECTED)

        serializer = VersionSerializer(versions, many=True)
        return Response(serializer.data)

    def post(self, request, id):
        from documents.models import DocumentModel
        from reviews.models import ReviewModel

        doc = get_object_or_404(DocumentModel, id=id)
        file_obj = request.FILES.get("file")

        if not file_obj:
            return Response(
                {"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST
            )

        # NOTE: Calculates checksum and determines next version number increment
        checksum = generate_checksum(file_obj)
        last_v = (
            VersionsModel.objects.filter(document=doc).order_by("version_number").last()
        )
        new_version_number = (last_v.version_number + 1) if last_v else 1

        # NOTE: Structured storage path including owner and document IDs
        folder_path = f"documents/{doc.created_by.id}/{doc.id}/v{new_version_number}"

        try:
            # NOTE: Uploads the file to Cloudinary and retrieves the secure URL
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

        serializer = VersionSerializer(data=request.data, context={"request": request})

        if serializer.is_valid():
            with transaction.atomic():
                # NOTE: Persists version record and initializes a pending review
                new_version = serializer.save(
                    document=doc,
                    version_number=new_version_number,
                    file_path=file_url,
                    file_size=file_obj.size,
                    checksum=checksum,
                    status=VersionStatus.PENDING,
                    created_by=request.user,
                    parent_version=last_v,
                )
                ReviewModel.objects.create(version=new_version, status="pending")

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- DETAIL & GITHUB-STYLE DIFF ---


class VersionDetailView(APIView):
    permission_classes = [HasDocumentReadPermission]

    def get(self, request, pk):
        # NOTE: GET metadata for a specific version by primary key
        version = get_object_or_404(VersionsModel, pk=pk)
        return Response(VersionSerializer(version).data)

    def patch(self, request, pk):
        # NOTE: PATCH to update version details if it has not been approved
        version = get_object_or_404(VersionsModel, pk=pk)

        # SECURITY: Approved versions are frozen to maintain historical integrity
        if version.status == VersionStatus.APPROVED:
            return Response(
                {"error": "Finalized versions are immutable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = VersionSerializer(
            version, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VersionDiffView(APIView):
    permission_classes = [HasDocumentReadPermission]

    def get(self, request, pk):
        # NOTE: Performs a line-by-line text comparison against the parent version
        version = get_object_or_404(VersionsModel, pk=pk)

        binary_exts = ["pdf", "zip", "docx", "jpg", "png"]
        ext = version.file_path.split(".")[-1].lower() if version.file_path else ""

        # NOTE: Returns error if the file type is not suitable for text diffing
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

        # NOTE: Standard difflib sequence matching to identify inserts, deletes, or equals
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


# --- EXPORT VIEW ---


class VersionExportView(APIView):
    permission_classes = [HasDocumentReadPermission]

    def get(self, request, pk, format):
        # NOTE: GET to generate a downloadable TXT or PDF of the version content
        version = get_object_or_404(VersionsModel, pk=pk)
        filename = f"{version.document.title}_v{version.version_number}"

        if format == "txt":
            # NOTE: Generates a plain text response with metadata header
            header = f"DOC: {version.document.title}\nVER: {version.version_number}\n"
            header += f"BY: {version.created_by.username}\n" + ("-" * 20) + "\n\n"
            content = header + (
                version.content or "Binary file content cannot be displayed."
            )
            response = HttpResponse(content, content_type="text/plain")
            response["Content-Disposition"] = f'attachment; filename="{filename}.txt"'
            return response

        elif format == "pdf":
            # NOTE: Uses reportlab to draw document content into a downloadable PDF
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
            to = p.beginText(50, 700)
            lines = (version.content or "Binary file content.").splitlines()
            for line in lines[:60]:
                to.textLine(line)
            p.drawText(to)
            p.showPage()
            p.save()
            buffer.seek(0)
            return FileResponse(buffer, as_attachment=True, filename=f"{filename}.pdf")

        return Response(
            {"error": "Invalid format Choose 'pdf' or 'txt'"},
            status=status.HTTP_400_BAD_REQUEST,
        )
