"""
Automatic Perspective Detection
--------------------------------
Given a base product photo and an admin-defined print area (an axis-aligned
rectangle: x, y, w, h), this module automatically estimates how that surface
is tilted/turned in the photo and returns a destination quadrilateral
(4 corner points) that the flat design should be warped into.

No manual per-image corner mapping is required. The estimate is derived from:
  1. The dominant edge orientation along the garment/product silhouette next
     to the print area (via Sobel gradients + a structure-tensor style
     weighted angle), which tells us the *shear/rotation* of the surface.
  2. A foreshortening estimate from the relative brightness/contrast falloff
     across the region, which approximates *how much the far edge appears
     to recede* (simple, fast proxy for full 3D perspective).

This is a deliberately lightweight, real-time-friendly heuristic rather than
a full monocular-depth/pose model -- it is accurate enough for garment
mockups and is cheap enough to run per upload, but in this system it is
actually pre-computed ONCE per product image and cached (see models.py),
so runtime cost for a customization request is ~0.
"""
import numpy as np
import cv2


def _dominant_edge_angle(gray_strip: np.ndarray) -> float:
    """
    Estimate the dominant edge orientation (in radians, relative to vertical)
    within a thin strip of the image using gradient-weighted orientation
    averaging (a simplified structure tensor).

    Returns an angle in radians where 0 = perfectly vertical edge (no tilt).
    """
    gray_strip = cv2.GaussianBlur(gray_strip, (5, 5), 0)
    gx = cv2.Sobel(gray_strip, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_strip, cv2.CV_32F, 0, 1, ksize=3)

    mag = np.sqrt(gx ** 2 + gy ** 2)
    # Only trust strong edges (garment seams / silhouette), ignore flat fabric noise
    threshold = np.percentile(mag, 90) if mag.size else 0
    mask = mag >= max(threshold, 1e-6)

    if not np.any(mask):
        return 0.0

    # Structure tensor components, weighted by gradient magnitude
    gxx = float(np.sum((gx[mask] ** 2)))
    gyy = float(np.sum((gy[mask] ** 2)))
    gxy = float(np.sum((gx[mask] * gy[mask])))

    # Dominant orientation of the edge *tangent* (perpendicular to gradient)
    theta = 0.5 * np.arctan2(2 * gxy, gxx - gyy)
    # theta here is gradient orientation; the edge tangent is perpendicular
    edge_angle = theta + np.pi / 2

    # Normalize into [-pi/2, pi/2] and express as deviation from vertical
    edge_angle = np.arctan(np.tan(edge_angle))
    return float(edge_angle)


def detect_surface_quad(base_image_bgr: np.ndarray, print_area: dict, max_tilt_deg: float = 18.0):
    """
    Estimate the tilted destination quad for a print area.

    Args:
        base_image_bgr: full base product photo, BGR (OpenCV) array.
        print_area: dict with keys x, y, w, h (top-left corner + size, in
            pixels, as defined by the admin for this product photo).
        max_tilt_deg: safety clamp so noisy photos can't produce extreme warps.

    Returns:
        np.ndarray shape (4, 2) float32: [top-left, top-right, bottom-right,
        bottom-left] destination points in image pixel coordinates.
    """
    x, y, w, h = print_area["x"], print_area["y"], print_area["w"], print_area["h"]
    H, W = base_image_bgr.shape[:2]
    gray = cv2.cvtColor(base_image_bgr, cv2.COLOR_BGR2GRAY)

    pad = max(4, int(0.15 * w))
    left_x0, left_x1 = max(0, x - pad), min(W, x + pad)
    right_x0, right_x1 = max(0, x + w - pad), min(W, x + w + pad)
    y0, y1 = max(0, y), min(H, y + h)

    left_strip = gray[y0:y1, left_x0:left_x1]
    right_strip = gray[y0:y1, right_x0:right_x1]

    left_angle = _dominant_edge_angle(left_strip) if left_strip.size else 0.0
    right_angle = _dominant_edge_angle(right_strip) if right_strip.size else 0.0

    # Average the two edges -> overall panel tilt (rotation/shear of the surface)
    tilt = (left_angle + right_angle) / 2.0
    max_tilt = np.radians(max_tilt_deg)
    tilt = float(np.clip(tilt, -max_tilt, max_tilt))

    # Foreshortening proxy: compare local contrast/brightness gradient across
    # the vertical span of the print area. A surface curving away from camera
    # (sleeve, cap bill, hood side) tends to darken and lose contrast toward
    # one edge -- we use that falloff to narrow that side slightly.
    region = gray[y0:y1, x:x + w].astype(np.float32)
    if region.size:
        col_means = region.mean(axis=0)
        left_lvl = float(col_means[: max(1, len(col_means) // 4)].mean())
        right_lvl = float(col_means[-max(1, len(col_means) // 4):].mean())
        total = max(left_lvl + right_lvl, 1e-6)
        # -0.15 .. +0.15 fraction of height, narrowing the darker side
        foreshorten = np.clip((left_lvl - right_lvl) / total, -0.4, 0.4) * 0.15
    else:
        foreshorten = 0.0

    # Build the destination quad: start from the axis-aligned rectangle,
    # then apply shear (tilt) and a slight taper (foreshorten).
    #
    # IMPORTANT: the shear is split evenly between the top and bottom edges
    # (top shifts one way, bottom shifts the opposite way, by half each).
    # This models the surface rotating about its own center, which is both
    # the physically correct behavior and -- critically -- keeps the quad's
    # centroid exactly on the print area's center regardless of tilt angle.
    # (An earlier version shifted only the bottom edge, which tilted the
    # quad correctly but also dragged its centroid sideways, causing the
    # design to render off-center from the visible print-area rectangle.)
    shear_px = np.tan(tilt) * h
    half_shear = shear_px / 2.0
    taper_top = foreshorten * h
    taper_bottom = -foreshorten * h

    top_left = (x + taper_top + half_shear, y)
    top_right = (x + w - taper_top + half_shear, y)
    bottom_left = (x + taper_bottom - half_shear, y + h)
    bottom_right = (x + w - taper_bottom - half_shear, y + h)

    quad = np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)
    return quad, {"tilt_deg": float(np.degrees(tilt)), "foreshorten": float(foreshorten)}
