from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DocumentPermissionModel

from .serializers import DocumentPermissionSerializer

# CREATE
class CreateDocumentPermissionView(generics.CreateAPIView):
    queryset = DocumentPermissionModel.objects.all()
    serializer_class = DocumentPermissionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document_permission = serializer.save()

        return Response(
            {
                "document_permission": serializer.data,
                "uuid": document_permission.id
            },
            status = status.HTTP_201_CREATED
        )

# GET
class GetDocumentPermissionView(generics.RetrieveAPIView):
    queryset = DocumentPermissionModel.objects.all()
    serializer_class = DocumentPermissionSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        response.data = {
            "document_permission": response.data
        }
        return response

# DELETE
class DeleteDocumentPermissionView(generics.DestroyAPIView):
    queryset = DocumentPermissionModel.objects.get_queryset()
    serializer_class = DocumentPermissionSerializer
    lookup_field = "id"

    def destroy(self, request, *args, **kwargs):
        response = super().destroy(request, *args, **kwargs)
        return Response({"message": "Document permission deleted successfully"})

# GET ALL DOCUMENT PERMISSIONS
class GetAllDocumentPermissionsView(APIView):
    def get(self, request):
        document_permissions = DocumentPermissionModel.objects.all()
        serializer = DocumentPermissionSerializer(document_permissions, many=True)
        return Response(serializer.data, status=200)
