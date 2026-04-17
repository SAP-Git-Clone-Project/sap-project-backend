import uuid
from django.db import models
from django.conf import settings


class ReviewStatus(models.TextChoices):
    # NOTE: Standardized status options for document approval workflows
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ReviewModel(models.Model):
    # NOTE: Secure UUID used for review identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # NOTE: Link to specific document version using app-label to avoid circularity
    version = models.ForeignKey(
        "versions.VersionsModel", on_delete=models.CASCADE, related_name="reviews"
    )

    # NOTE: The reviewer assigned to or performing the evaluation
    # SECURITY: SET_NULL preserves audit history if a user account is deleted
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews_given",
    )

    # NOTE: Tracks the current state of the review process
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )

    # NOTE: Feedback or justification provided by the reviewer
    comments = models.TextField(blank=True, null=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reviews"
        # NOTE: Sorts reviews by most recent completion date
        ordering = ["-reviewed_at"]
        indexes = [
            # PERF: Common query for "my pending reviews"
            models.Index(fields=["reviewer", "review_status"]),
        ]

    def __str__(self):
        # NOTE: Formats the review for admin display and logging
        return f"Review for {self.version.document.title} - {self.review_status}"
