from pathlib import Path

import cv2

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from customizer.engine.calibration import detect_guide_box
from customizer.models import Product, ProductImage


# Samples whose print area is auto-calibrated from a red guide box baked
# into the sample photo (the assets extracted from the original brief PDF).
AUTO_CALIBRATED_SAMPLES = [
    ("Hoodie", "hoodie", "front", "products/hoodie/front/base.png"),
    ("Hoodie", "hoodie", "back", "products/hoodie/back/base.png"),
    ("Cap", "cap", "front", "products/cap/front/base.png"),
    ("Cap", "cap", "back", "products/cap/back/base.png"),
]

# Samples with no guide box (real-world photos as an admin would actually
# upload them) -- print area is specified explicitly, exactly as an admin
# would enter it in the admin panel for a brand new product photo.
MANUAL_SAMPLES = [

    ("Pink Tee", "pink-tee", "back",
     "products/pink_tee/back/base.jpg",
     599, 810, 799, 900, 18.0),

    ("Maroon Tee", "maroon-tee", "front",
     "products/maroon_tee/front/base.jpg",
     600, 436, 800, 634, 18.0),

    ("Two-Tone Cap", "twotone-cap", "side",
     "products/twotone_cap/side/base.jpg",
     432, 768, 720, 528, 8.0),

    ("Two-Tone Cap Alt", "twotone-cap-alt", "side",
     "products/twotone_cap_alt/side/base.jpg",
     1317, 1063, 552, 441, 8.0),

    ("Khaki Cap", "khaki-cap", "front",
     "products/khaki_cap/front/base.jpg",
     158, 87, 241, 144, 18.0),

    # ---------------- NEW PRODUCT ----------------

   (
    "OTTO Sun Visor",
    "otto-sun-visor",
    "front",
    "products/sunwisor/front/otto_front.jpg",
    70,     # X
    55,     # Y
    420,    # W
    115,    # H
    18.0,
),
(
    "OTTO Sun Visor",
    "otto-sun-visor",
    "side",
    "products/sunwisor/side/otto_side.jpg",
    201,
    619,
    1083,
    1240,
    18.0,
),
]


class Command(BaseCommand):
    help = (
        "Seed demo products/images. Samples extracted from the brief PDF "
        "have their print area auto-calibrated from a red guide rectangle "
        "baked into the photo (see engine/calibration.py). Newly uploaded "
        "real-world photos have no such marker, so their print area is "
        "specified explicitly here -- exactly as an admin would enter it "
        "for a brand new product in a real deployment."
    )

    def handle(self, *args, **options):
        for name, slug, view, rel_path in AUTO_CALIBRATED_SAMPLES:
            product, _ = Product.objects.get_or_create(name=name, slug=slug)
            src = Path(settings.MEDIA_ROOT) / rel_path
            if not src.exists():
                self.stdout.write(self.style.WARNING(f"Missing sample asset {src}, skipping."))
                continue
            image_bgr = cv2.imread(str(src))
            area = detect_guide_box(image_bgr)
            self._create(product, view, src, area)

        for name, slug, view, rel_path, x, y, w, h, max_tilt in MANUAL_SAMPLES:
            product, _ = Product.objects.get_or_create(name=name, slug=slug)
            src = Path(settings.MEDIA_ROOT) / rel_path
            if not src.exists():
                self.stdout.write(self.style.WARNING(f"Missing sample asset {src}, skipping."))
                continue
            self._create(product, view, src, dict(x=x, y=y, w=w, h=h), max_tilt_deg=max_tilt)

    def _create(self, product, view, src, area, max_tilt_deg=18.0):
        pi, created = ProductImage.objects.get_or_create(
        product=product,
        view=view,
        defaults=dict(
            print_area_x=area["x"],
            print_area_y=area["y"],
            print_area_w=area["w"],
            print_area_h=area["h"],
            max_tilt_deg=max_tilt_deg,
        ),
    )

        if created:
            with open(src, "rb") as f:
             pi.base_image.save(src.name, File(f), save=True)

            self.stdout.write(
             self.style.SUCCESS(
                f"Created {product.name} / {view}  print_area={area}"
            )
        )
        else:
            self.stdout.write(
                f"Already exists: {product.name} / {view}"
        )