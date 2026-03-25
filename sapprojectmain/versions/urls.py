from django.urls import path
from .views import DocumentVersionHandler, VersionDetailView

urlpatterns = [
    # api/versions/document/<uuid:id>/
    path('document/<uuid:id>/', DocumentVersionHandler.as_view(), name='document-versions'),
    # api/versions/<uuid:pk>/
    path('<uuid:pk>/', VersionDetailView.as_view(), name='version-detail'),
]