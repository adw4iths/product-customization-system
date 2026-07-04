from django.shortcuts import render, get_object_or_404
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
    """
    GET /api/products/  and  /api/products/{slug}/ -- browse catalog + print areas.

    Looked up by slug, not the default numeric pk -- DRF's router defaults
    to pk-based lookup, so without this, /api/products/hoodie/ 404s and only
    /api/products/1/ works. Since product URLs everywhere else in this app
    (the detail page, the nav) use the human-readable slug, the API needs to
    match or the two halves of the app disagree about what a product's URL is.
    """
    queryset = Product.objects.prefetch_related("images").all()
    serializer_class = ProductSerializer
    lookup_field = "slug"


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
        render_customization_job.delay(str(job.id))

        return Response(CustomizationJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    def get(self, request, job_id=None):
        job = CustomizationJob.objects.get(id=job_id)
        return Response(CustomizationJobSerializer(job).data)


def product_list_page(request):
    """Landing page: grid of products, each linking to its detail page."""
    products = Product.objects.prefetch_related("images").all()
    return render(request, "customizer/product_list.html", {"products": products})


def product_detail_page(request, slug):
    """
    Product detail page: large product image, Upload Logo, Generate Mockup,
    and (once a mockup exists) a Download button. Matches the mentor's
    requested flow: Landing -> product card -> this page -> upload -> mockup
    -> download.
    """
    product = get_object_or_404(
        Product.objects.prefetch_related("images"), slug=slug
    )
    return render(request, "customizer/product_detail.html", {"product": product})


def demo_page(request):
    """Simple browser demo: pick a product view, upload a design, see the render."""
    products = Product.objects.prefetch_related("images").all()
    return render(request, "customizer/demo.html", {"products": products})