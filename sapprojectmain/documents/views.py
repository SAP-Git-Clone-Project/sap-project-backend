from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .models import DocumentModel
from .serializers import DocumentSerializer

# CREATE
class CreateDocumentView(generics.CreateAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save()

        return Response(
            {
                "document": serializer.data,
                "uuid": document.id,
            },
            status=status.HTTP_201_CREATED
        )

# GET
class GetDocumentView(generics.RetrieveAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = DocumentSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        response.data = {
            "document": response.data
        }
        return response

# UPDATE
class UpdateDocumentView(generics.UpdateAPIView):
    queryset = DocumentModel.objects.get_queryset_without_deleted()
    serializer_class = DocumentSerializer
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
    serializer_class = DocumentSerializer
    lookup_field = "id"

    def destroy(self, request, *args, **kwargs):
        response = super().destroy(request, *args, **kwargs)
        return Response({"message": "Document deleted successfully"})

# GET ALL DOCUMENTS
class GetAllDocumentsView(APIView):
    def get(self, request):
        documents = DocumentModel.objects.get_queryset_without_deleted()
        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data, status=200)
