from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductViewSet, DesignUploadView, CustomizationJobView, demo_page,
    product_list_page, product_detail_page,
)

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("", product_list_page, name="product-list-page"),
    path("products/<slug:slug>/", product_detail_page, name="product-detail-page"),
    path("demo/", demo_page, name="demo"),
    path("api/", include(router.urls)),
    path("api/designs/", DesignUploadView.as_view(), name="design-upload"),
    path("api/customize/", CustomizationJobView.as_view(), name="customize"),
    path("api/customize/<uuid:job_id>/", CustomizationJobView.as_view(), name="customize-detail"),
]