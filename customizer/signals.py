import io
import numpy as np
from django.core.files.base import ContentFile
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ProductImage, ProductImageAnalysis
from .engine.pipeline import analyze_product_image, load_bgr


@receiver(post_save, sender=ProductImage)
def run_analysis_on_save(sender, instance: ProductImage, **kwargs):
    """
    Automated Image Analysis (spec section A): whenever the admin
    uploads/edits a product photo or its print area, automatically compute
    the perspective quad and the fold/wrinkle displacement map -- ONCE --
    and cache it. No manual per-photo corner mapping is ever required.
    """
    if not instance.base_image:
        # ProductImage can be saved once before a file is attached (e.g.
        # get_or_create() creates the row from `defaults` first, then a
        # separate call assigns the file). Nothing to analyze yet -- this
        # signal will fire again once the file is actually attached.
        return

    base = load_bgr(instance.base_image.path)
    result = analyze_product_image(base, instance.print_area, max_tilt_deg=instance.max_tilt_deg)

    buf = io.BytesIO()
    np.save(buf, result.height_map)
    buf.seek(0)

    defaults = {
        "quad_json": result.quad.tolist(),
        "tilt_deg": result.meta["tilt_deg"],
        "foreshorten": result.meta["foreshorten"],
    }

    analysis, _ = ProductImageAnalysis.objects.update_or_create(
        product_image=instance, defaults=defaults
    )
    analysis.height_map_file.save(
        f"{instance.id}_height.npy", ContentFile(buf.read()), save=True
    )
