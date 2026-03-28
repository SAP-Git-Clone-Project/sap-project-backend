from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction

# Model/Serializer Imports
from .models import ReviewModel, ReviewStatus
from .serializers import ReviewSerializer
from core.permissions import IsReviewerForDocument


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


class ReviewListView(APIView):
    permission_classes = [IsReviewerForDocument]

    def get(self, request):
        user = request.user

        if user.is_staff or user.is_superuser:
            reviews = ReviewModel.objects.all()
        else:
            reviews = ReviewModel.objects.filter(
                version__document__document_permissions__user=user,
                version__document__document_permissions__permission_type="APPROVE",
            ).distinct()

        # NOTE: Default to pending only, pass ?all=true for full history/audit
        if request.query_params.get("all") != "true":
            reviews = reviews.filter(review_status=ReviewStatus.PENDING)

        serializer = ReviewSerializer(reviews, many=True)
        return Response(serializer.data)
