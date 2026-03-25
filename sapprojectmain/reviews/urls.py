from django.urls import path
from .views import ReviewDetailView

urlpatterns = [
    # Full path: api/reviews/<uuid:pk>/
    path('<uuid:pk>/', ReviewDetailView.as_view(), name='review-detail'),
]