import uuid
import numpy as np
from django.db import models


class Product(models.Model):
    """A sellable product (Hoodie, Cap, T-Shirt, ...)."""
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    """
    One base photo of a product from a specific angle (front/back/side),
    with the admin-defined print area for that angle.
    """
    VIEW_CHOICES = [("front", "Front"), ("back", "Back"), ("side", "Side")]

    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    view = models.CharField(max_length=10, choices=VIEW_CHOICES)
    base_image = models.ImageField(upload_to="products/%Y/%m/")

    # Admin-defined print area (max width/height + coordinates), per spec section A.
    print_area_x = models.PositiveIntegerField()
    print_area_y = models.PositiveIntegerField()
    print_area_w = models.PositiveIntegerField()
    print_area_h = models.PositiveIntegerField()

    # Safety clamp for automatic perspective-tilt detection (see
    # engine/perspective.py). Flat, large panels (t-shirt front/back) are
    # reliable at the default. Small curved panels with busy stitching
    # (cap sides, sleeves) can fool the detector into over-estimating tilt;
    # if a photo's analysis saturates at this clamp, lower it here.
    max_tilt_deg = models.FloatField(default=18.0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("product", "view")

    def __str__(self):
        return f"{self.product.name} - {self.view}"

    @property
    def print_area(self) -> dict:
        return {
            "x": self.print_area_x, "y": self.print_area_y,
            "w": self.print_area_w, "h": self.print_area_h,
        }


class ProductImageAnalysis(models.Model):
    """
    Cached PHASE 1 analysis result for a ProductImage: the automatically
    detected perspective quad + fold/wrinkle displacement (height) map.

    This is (re)computed once whenever a ProductImage or its print area is
    saved (see signals.py), NOT on every customization request -- this is
    what makes runtime rendering fast under concurrent load.
    """
    product_image = models.OneToOneField(
        ProductImage, related_name="analysis", on_delete=models.CASCADE
    )
    quad_json = models.JSONField()          # 4x2 destination corners
    height_map_file = models.FileField(upload_to="analysis/")  # .npy, float32 HxW
    tilt_deg = models.FloatField(default=0.0)
    foreshorten = models.FloatField(default=0.0)
    computed_at = models.DateTimeField(auto_now=True)

    def quad(self) -> np.ndarray:
        return np.array(self.quad_json, dtype=np.float32)

    def height_map(self) -> np.ndarray:
        self.height_map_file.open("rb")
        try:
            return np.load(self.height_map_file)
        finally:
            self.height_map_file.close()


def design_upload_path(instance, filename):
    return f"designs/{instance.id}/{filename}"


class DesignUpload(models.Model):
    """A user-uploaded design (logo/art) to be placed on products."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ImageField(upload_to=design_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class CustomizationJob(models.Model):
    """
    One customization render request. Tracked as a job so requests can be
    processed asynchronously (Celery) for high-concurrency throughput -- the
    client gets a job id immediately and polls/receives a callback, instead
    of holding an HTTP connection open during rendering.
    """
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    design = models.ForeignKey(DesignUpload, on_delete=models.CASCADE)
    product_image = models.ForeignKey(ProductImage, on_delete=models.CASCADE)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    result_image = models.ImageField(upload_to="output/%Y/%m/", blank=True, null=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Job {self.id} ({self.status})"
