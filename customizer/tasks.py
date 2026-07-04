import io
import time
import logging

import cv2
import numpy as np
from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import CustomizationJob
from .engine.pipeline import render_customization, ProductImageAnalysisResult, load_bgr, load_rgba

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, autoretry_for=(Exception,), retry_backoff=True)
def render_customization_job(self, job_id: str):
    """
    Runs PHASE 2 (fast path) of the pipeline for one job.

    Handling this as a Celery task -- rather than inline in the request/response
    cycle -- is what satisfies the "Concurrency Handling" requirement: many
    customization requests can be enqueued simultaneously and are processed
    across worker processes/machines without the web server blocking or
    degrading under load. Each worker holds no state between jobs, so this
    task scales horizontally by simply adding more Celery workers.
    """
    job = CustomizationJob.objects.select_related(
        "product_image", "product_image__analysis", "design"
    ).get(id=job_id)

    job.status = "processing"
    job.save(update_fields=["status"])

    t0 = time.monotonic()
    try:
        pi = job.product_image
        analysis_row = pi.analysis  # cached ProductImageAnalysis (Phase 1, precomputed)

        analysis = ProductImageAnalysisResult(
            quad=analysis_row.quad(),
            height_map=analysis_row.height_map(),
            meta={"tilt_deg": analysis_row.tilt_deg, "foreshorten": analysis_row.foreshorten},
        )

        base = load_bgr(pi.base_image.path)
        design = load_rgba(job.design.file.path)

        result_bgr = render_customization(base, design, pi.print_area, analysis)

        ok, buf = cv2.imencode(".png", result_bgr)
        if not ok:
            raise RuntimeError("Failed to encode result image")

        job.result_image.save(
            f"{job.id}.png", ContentFile(io.BytesIO(buf.tobytes()).read()), save=False
        )
        job.status = "done"
        job.finished_at = timezone.now()
        job.save()

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info("Rendered job %s in %.1fms", job.id, elapsed_ms)

    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save()
        raise
