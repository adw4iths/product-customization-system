import io
import numpy as np

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from customizer.models import ProductImage, ProductImageAnalysis
from customizer.engine.pipeline import analyze_product_image, load_bgr


class Command(BaseCommand):
    help = "Rebuild cached ProductImageAnalysis for all ProductImages."

    def handle(self, *args, **options):

        images = ProductImage.objects.all()

        if not images.exists():
            self.stdout.write(self.style.WARNING("No ProductImages found."))
            return

        self.stdout.write(
            self.style.NOTICE(f"Found {images.count()} product images.\n")
        )

        for pi in images:
            try:
                self.stdout.write(f"Processing {pi.product.name} ({pi.view})...")

                base = load_bgr(pi.base_image.path)

                result = analyze_product_image(
                    base,
                    pi.print_area,
                    max_tilt_deg=pi.max_tilt_deg,
                )

                analysis, created = ProductImageAnalysis.objects.get_or_create(
                    product_image=pi
                )

                analysis.quad_json = result.quad.tolist()
                analysis.tilt_deg = result.meta["tilt_deg"]
                analysis.foreshorten = result.meta["foreshorten"]

                buffer = io.BytesIO()
                np.save(buffer, result.height_map)
                buffer.seek(0)

                analysis.height_map_file.save(
                    f"{pi.id}_height.npy",
                    ContentFile(buffer.read()),
                    save=False,
                )

                analysis.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Finished {pi.product.name} ({pi.view})"
                    )
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Failed {pi.product.name} ({pi.view})"
                    )
                )
                self.stdout.write(str(e))

        self.stdout.write(
            self.style.SUCCESS("\nAnalysis rebuild completed.")
        )