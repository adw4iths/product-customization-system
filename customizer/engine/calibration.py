"""
Demo-asset calibration helper.
--------------------------------
The sample product photos bundled with this project (extracted from the
challenge brief PDF) have a red guide rectangle already burned into the
image pixels, marking where the print area is meant to be. This module
detects that rectangle's exact pixel bounds so the demo's print-area
coordinates are guaranteed to match what's actually drawn in the photo.

This is a ONE-TIME calibration utility for the bundled samples only. In
real usage there is no red box in the photo -- the admin defines the print
area directly (see ProductImage.print_area_x/y/w/h in models.py). Nothing
in the request-time rendering pipeline depends on this module.
"""
import cv2
import numpy as np


def detect_guide_box(image_bgr: np.ndarray, min_component_area: int = 300) -> dict:
    """
    Find a red rectangle outline in `image_bgr` and return its bounding box
    as {x, y, w, h}. Picks the connected component with the largest
    bounding-box area (robust against small red flecks elsewhere in the
    photo, e.g. skin tone or fabric color).

    Raises ValueError if no plausible red rectangle is found.
    """
    b = image_bgr[:, :, 0].astype(int)
    g = image_bgr[:, :, 1].astype(int)
    r = image_bgr[:, :, 2].astype(int)

    red_mask = (
        (r > 150) & (g < 110) & (b < 110) & (r - g > 60) & (r - b > 60)
    ).astype(np.uint8) * 255

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(red_mask, connectivity=8)

    best_i, best_score = None, -1
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_component_area:
            continue
        bbox_area = int(w) * int(h)
        if bbox_area > best_score:
            best_score, best_i = bbox_area, i

    if best_i is None:
        raise ValueError("No red guide rectangle found in image")

    x, y, w, h, _area = stats[best_i]
    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
