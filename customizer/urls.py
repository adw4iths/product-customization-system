from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, DesignUploadView, CustomizationJobView, demo_page

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("", demo_page, name="demo"),
    path("api/", include(router.urls)),
    path("api/designs/", DesignUploadView.as_view(), name="design-upload"),
    path("api/customize/", CustomizationJobView.as_view(), name="customize"),
    path("api/customize/<uuid:job_id>/", CustomizationJobView.as_view(), name="customize-detail"),
]
