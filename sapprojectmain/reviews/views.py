import traceback

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction

# Model/Serializer Imports
from .models import ReviewModel, ReviewStatus
from .serializers import ReviewSerializer
from versions.models import VersionsModel, VersionStatus
from document_permissions.models import DocumentPermissionModel
from django.contrib.auth import get_user_model
from core.permissions import IsAuthenticatedUser, IsReviewerForDocument

from django.contrib.auth import get_user_model

User = get_user_model()

class ReviewDetailView(APIView):
    permission_classes = [IsReviewerForDocument]

    def get(self, request, pk):
        # NOTE: GET review data including old and new versions for diffing
        review = get_object_or_404(ReviewModel, pk=pk)

        # SECURITY: Verifies user has specific approval rights for this document
        self.check_object_permissions(request, review)

        serializer = ReviewSerializer(review)
        return Response(serializer.data)

    def patch(self, request, pk):
        # NOTE: PATCH to finalize the review decision as approved or rejected

        # IMP: Atomic transaction with row locking to prevent concurrent updates
        with transaction.atomic():
            review = get_object_or_404(ReviewModel.objects.select_for_update(), pk=pk)

            self.check_object_permissions(request, review)

            # NOTE: Prevents modification of reviews that are no longer pending
            if review.review_status != ReviewStatus.PENDING:
                return Response(
                    {"error": "This review has already been finalized."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # NOTE: Serializer handles the status sync and version activation logic
            serializer = ReviewSerializer(
                review, data=request.data, partial=True, context={"request": request}
            )

            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ReviewCreateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        try:
            version_id = request.data.get("version")
            reviewer_id = request.data.get("reviewer")

            if not version_id:
                return Response({"error": "'version' is required."}, status=status.HTTP_400_BAD_REQUEST)
            if not reviewer_id:
                return Response({"error": "'reviewer' is required."}, status=status.HTTP_400_BAD_REQUEST)

            reviewer = get_object_or_404(User, pk=reviewer_id)

            with transaction.atomic():
                version = get_object_or_404(VersionsModel, pk=version_id)

                # SECURITY: Only users with APPROVE permission on this document can be reviewers
                has_approve_permission = DocumentPermissionModel.objects.filter(
                    user=reviewer,
                    document=version.document,
                    permission_type="APPROVE"
                ).exists()

                if not has_approve_permission and not request.user.is_superuser:
                    return Response(
                        {"error": "This user is not an authorized reviewer for this document."},
                        status=status.HTTP_403_FORBIDDEN
                    )

                if ReviewModel.objects.filter(
                    version=version,
                    review_status=ReviewStatus.PENDING,
                    reviewer=reviewer,
                ).exists():
                    return Response(
                        {"error": "This reviewer already has a pending review for this version."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                review = ReviewModel.objects.create(
                    version=version,
                    review_status=ReviewStatus.PENDING,
                    reviewer=reviewer,
                )

                version.status = VersionStatus.PENDING
                version.save()

            return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ReviewListView(APIView):
    permission_classes = [IsReviewerForDocument]

    def get(self, request):
        user = request.user

        if user.is_staff or user.is_superuser:
            reviews = ReviewModel.objects.all()
        else:
            reviews = ReviewModel.objects.filter(reviewer_id=user).select_related("version").distinct()

        # NOTE: Default to pending only, pass ?all=true for full history/audit
        if request.query_params.get("all") != "true":
            reviews = reviews.filter(review_status=ReviewStatus.PENDING)

        serializer = ReviewSerializer(reviews, many=True)
        return Response(serializer.data)
