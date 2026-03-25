from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone

from .models import Reviews, ReviewStatus
from .serializers import ReviewSerializer
from versions.models import Versions
from core.permissions import IsReviewerForDocument


class ReviewDetailView(APIView):
    permission_classes = [IsReviewerForDocument]

    def get(self, request, pk):
        """Fetch side-by-side data for the GitHub-style diff view."""
        review = get_object_or_404(Reviews, pk=pk)
        self.check_object_permissions(request, review)
        return Response(ReviewSerializer(review).data)

    def patch(self, request, pk):
        """Processes approval/rejection with pre-engineered safety logic."""

        # Use select_for_update to lock the row during the transaction
        review = get_object_or_404(Reviews.objects.select_for_update(), pk=pk)
        self.check_object_permissions(request, review)

        new_status = request.data.get("review_status")
        comments = request.data.get("comments")

        if review.review_status != ReviewStatus.PENDING:
            return Response({"error": "Review already finalized."}, status=400)

        with transaction.atomic():
            # 1. Update Review Metadata
            review.review_status = new_status
            review.comments = comments
            review.reviewed_at = timezone.now()
            review.reviewer = request.user
            review.save()

            version = review.version

            if new_status == ReviewStatus.APPROVED:
                # 2. Pre-engineered: Auto-increment version number
                last_v = (
                    Versions.objects.filter(
                        document=version.document, status="approved"
                    )
                    .order_by("-version_number")
                    .first()
                )
                version.version_number = (last_v.version_number + 1) if last_v else 1

                # 3. Pre-engineered: Force only ONE active version
                Versions.objects.filter(document=version.document).update(
                    is_active=False
                )

                # 4. Finalize new version
                version.status = "approved"
                version.is_active = True
                version.save()

            elif new_status == ReviewStatus.REJECTED:
                version.status = "rejected"
                version.is_active = False
                version.save()

        return Response(ReviewSerializer(review).data)
