from django.urls import path
from .views import ReviewDetailView, ReviewListView

urlpatterns = [
    # NOTE: GET for the reviewer inbox to list pending document reviews
    path("inbox/", ReviewListView.as_view(), name="review-inbox"),
    # NOTE: GET, PUT, and PATCH for viewing diffs or performing approvals
    path("<uuid:pk>/", ReviewDetailView.as_view(), name="review-detail"),
]
