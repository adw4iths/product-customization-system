from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser

from .models import Product, ProductImage, DesignUpload, CustomizationJob
from .serializers import (
    ProductSerializer, ProductImageSerializer, DesignUploadSerializer,
    CustomizationJobSerializer, CreateCustomizationJobSerializer,
)
from .tasks import render_customization_job


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/products/  and  /api/products/{id}/ -- browse catalog + print areas."""
    queryset = Product.objects.prefetch_related("images").all()
    serializer_class = ProductSerializer


class DesignUploadView(APIView):
    """
    POST /api/designs/  (multipart form, field name 'file')
    Uploads the user's design (logo/art). Returns a design id to reference
    in a customization job.
    """
    parser_classes = [MultiPartParser]
    authentication_classes = []  # public endpoint; avoids CSRF enforcement
    permission_classes = []      # tripping up the demo page's plain fetch()
                                  # calls if the same browser also has an
                                  # active Django admin session.

    def post(self, request):
        serializer = DesignUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        design = serializer.save()
        return Response(DesignUploadSerializer(design).data, status=status.HTTP_201_CREATED)


class CustomizationJobView(APIView):
    """
    POST /api/customize/  {design_id, product_image_id}
    Enqueues a render job (Celery) and returns immediately with a job id --
    this is what lets the system absorb many simultaneous requests without
    the web process blocking on image processing.

    GET /api/customize/{job_id}/  -- poll for status/result.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = CreateCustomizationJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        design = DesignUpload.objects.get(id=data["design_id"])
        product_image = ProductImage.objects.get(id=data["product_image_id"])

        job = CustomizationJob.objects.create(design=design, product_image=product_image)
        render_customization_job(str(job.id)) 
        return Response(CustomizationJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    def get(self, request, job_id=None):
        job = CustomizationJob.objects.get(id=job_id)
        return Response(CustomizationJobSerializer(job).data)


def demo_page(request):
    """Simple browser demo: pick a product view, upload a design, see the render."""
    products = Product.objects.prefetch_related("images").all()
    return render(request, "customizer/demo.html", {"products": products})
