import io
import numpy as np

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from customizer.models import ProductImage, ProductImageAnalysis
from customizer.engine.pipeline import (
    analyze_product_image,
    load_bgr,
)


class Command(BaseCommand):
    help = "Rebuild cached analysis (.npy height maps) for all product images."

    def handle(self, *args, **options):

        self.stdout.write(self.style.NOTICE("Rebuilding product analysis...\n"))

        images = ProductImage.objects.all()

        if not images.exists():
            self.stdout.write(self.style.WARNING("No ProductImage records found."))
            return

        for pi in images:

            if not pi.base_image:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {pi.product.name} ({pi.view}) - no image."
                    )
                )
                continue

            try:
                base = load_bgr(pi.base_image.path)

                result = analyze_product_image(
                    base,
                    pi.print_area,
                    max_tilt_deg=pi.max_tilt_deg,
                )

                buffer = io.BytesIO()
                np.save(buffer, result.height_map)
                buffer.seek(0)

                analysis, created = ProductImageAnalysis.objects.update_or_create(
                    product_image=pi,
                    defaults={
                        "quad_json": result.quad.tolist(),
                        "tilt_deg": result.meta["tilt_deg"],
                        "foreshorten": result.meta["foreshorten"],
                    },
                )

                analysis.height_map_file.save(
                    f"{pi.id}_height.npy",
                    ContentFile(buffer.read()),
                    save=True,
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ {pi.product.name} ({pi.view})"
                    )
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {pi.product.name} ({pi.view}) -> {e}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS("\nFinished rebuilding analysis.")
        )