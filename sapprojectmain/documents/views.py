from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DocumentModel
from .serializers import CreateDocumentSerializer, GetDocumentSerializer, UpdateDocumentSerializer

# CREATE
class CreateDocumentView(generics.CreateAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = CreateDocumentSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save()

        return Response(
            {
                "document": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

# GET
class GetDocumentView(generics.RetrieveAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = GetDocumentSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = self().retrieve(request, *args, **kwargs)
        response.data = {
            "document": response.data
        }
        return response

# UPDATE
class UpdateDocumentView(generics.UpdateAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = UpdateDocumentSerializer
    lookup_field = "id"

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        response.data = {
            "document": response.data
        }
        return response

# DELETE
class DeleteDocumentView(generics.DestroyAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = GetDocumentSerializer
    lookup_field = "id"

    def destroy(self, request, *args, **kwargs):
        response = super().destroy(request, *args, **kwargs)
        return Response({"message": "Document deleted successfully"})

# GET, POST, DELETE, PUT
