"""
Rendering Pipeline
--------------------
Two distinct phases, which is the key to the performance requirement:

  PHASE 1 - ANALYSIS (slow, ~100-300ms, runs ONCE per product photo):
      Perspective quad detection + displacement/height map extraction.
      Triggered when an admin uploads/edits a product photo, not per request.
      Results are cached (see models.ProductImageAnalysis).

  PHASE 2 - RENDER (fast, ~10-40ms even at high res, runs per customization
      request): perspective-warp the design into the cached quad, bend it
      using the cached height map, blend it using the cached lighting map.
      This is pure vectorized numpy/OpenCV -- no analysis, no ML inference --
      which is what makes concurrent high-volume rendering practical.
"""
from dataclasses import dataclass
import numpy as np
import cv2

from .perspective import detect_surface_quad
from .displacement import build_displacement_map, apply_fabric_conformation
from .blending import composite_design


@dataclass
class ProductImageAnalysisResult:
    quad: np.ndarray            # (4,2) destination corners for perspective warp
    height_map: np.ndarray      # (h,w) fold/wrinkle map, cached per print area
    meta: dict                  # tilt_deg, foreshorten, etc. (useful for admin QA)


def analyze_product_image(base_image_bgr: np.ndarray, print_area: dict, max_tilt_deg: float = 18.0) -> ProductImageAnalysisResult:
    """PHASE 1. Run once per product photo and cache the result.

    `max_tilt_deg` bounds how much automatic tilt detection is allowed to
    shear the design. Flat, large-panel garments (t-shirt front/back) are
    well-behaved with the default. Small curved panels (cap sides, sleeves)
    have busier stitching/seam edges that can fool the gradient-based
    detector into reporting more tilt than is really there -- when that
    happens, detect_surface_quad saturates at this clamp, which is a signal
    to use a lower, more conservative value for that product type rather
    than trusting the raw estimate.
    """
    quad, meta = detect_surface_quad(base_image_bgr, print_area, max_tilt_deg=max_tilt_deg)
    height_map = build_displacement_map(base_image_bgr, print_area)
    return ProductImageAnalysisResult(quad=quad, height_map=height_map, meta=meta)


def render_customization(
    base_image_bgr: np.ndarray,
    design_rgba: np.ndarray,
    print_area: dict,
    analysis: ProductImageAnalysisResult,
    fold_strength: float = 10.0,
) -> np.ndarray:
    """
    PHASE 2. Fast per-request render using a cached analysis result.

    Steps map directly to the spec:
      1. Perspective Alignment  -> warpPerspective into analysis.quad
      2. Fabric Conformation    -> remap using analysis.height_map
      3. Realistic Blending     -> composite_design()
    """
    x, y, w, h = print_area["x"], print_area["y"], print_area["w"], print_area["h"]

    img_h, img_w = base_image_bgr.shape[:2]
    if x + w > img_w or y + h > img_h:
        raise ValueError(
            f"Print area (x={x}, y={y}, w={w}, h={h}) needs a photo at least "
            f"{x + w}x{y + h}px, but the base image is only {img_w}x{img_h}px. "
            f"This usually means the print-area coordinates were authored "
            f"against a different photo/crop than the one actually saved as "
            f"this product's base_image -- re-check which source file the "
            f"coordinates came from."
        )

    # --- 0. Fit the uploaded design into the print area, preserving its
    # aspect ratio, before doing anything else. Without this step the design
    # is stretched to whatever shape the print area happens to be (e.g. a
    # square logo squashed into a wide, short cap panel) and the perspective
    # transform below samples the wrong region of the source image, since it
    # assumes the source frame is already (w, h). Both bugs together are
    # what caused designs to render squished into a corner of the print area.
    design_h, design_w = design_rgba.shape[:2]
    scale = min(w / design_w, h / design_h)
    fit_w, fit_h = max(1, int(round(design_w * scale))), max(1, int(round(design_h * scale)))

    fitted = cv2.resize(
        design_rgba, (fit_w, fit_h),
        interpolation=cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA,
    )
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    off_x, off_y = (w - fit_w) // 2, (h - fit_h) // 2
    canvas[off_y:off_y + fit_h, off_x:off_x + fit_w] = fitted
    design_rgba = canvas  # now exactly (h, w, 4), design centered & undistorted

    # --- 1. Perspective Alignment ---
    src_pts = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    # quad is in full-image coordinates; make it relative to the print area
    # origin since we warp the design into a w x h canvas first.
    quad_local = analysis.quad.copy()
    quad_local[:, 0] -= x
    quad_local[:, 1] -= y

    M = cv2.getPerspectiveTransform(src_pts, quad_local)
    warped = cv2.warpPerspective(
        design_rgba, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )

    # --- 2. Fabric Conformation ---
    # `fold_strength` is a max pixel displacement. On a small print area
    # (e.g. a ~150-250px cap panel) a fixed 10px shift is a much larger
    # fraction of the design than on a large tee print, so it visibly
    # warps/distorts small logos far more than large ones -- part of the
    # same "quality loss on small print areas" issue as blending.py's
    # feather/sharpen/texture strengths. Scale it down the same way
    # (reference: 400px, a mid-sized garment print).
    REFERENCE_DIM = 400.0
    local_strength = fold_strength * max(0.0, min(1.0, min(w, h) / REFERENCE_DIM))
    bent = apply_fabric_conformation(warped, analysis.height_map, strength=local_strength)

    # --- 2b. Guaranteed centering ---
    # Perspective tilt and fold-bending are now built to be centroid-neutral
    # (see perspective.py / displacement.py), but photo-specific edge cases
    # can still leave a small residual drift. Rather than trust that the
    # heuristics cancel out perfectly on every product photo, we measure the
    # actual result and correct it: this guarantees the design's visual
    # center always lands exactly on the print area's center, which is what
    # makes the output look deliberately placed rather than "close enough".
    bent = _recenter_to_box(bent)

    # --- 3. Realistic Blending ---
    result = composite_design(base_image_bgr, bent, print_area)
    return result


def _recenter_to_box(rgba: np.ndarray, alpha_threshold: int = 15) -> np.ndarray:
    """
    Shift `rgba` (design already warped into a canvas the size of the print
    area) so the centroid of its visible (alpha > threshold) pixels sits
    exactly at the canvas center. No-op if the design is fully transparent.
    """
    h, w = rgba.shape[:2]
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha > alpha_threshold)
    if xs.size == 0:
        return rgba

    cx, cy = xs.mean(), ys.mean()
    dx, dy = (w / 2.0) - cx, (h / 2.0) - cy

    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return rgba  # already centered within half a pixel

    M = np.array([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
    return cv2.warpAffine(
        rgba, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def load_rgba(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.shape[2] == 3:
        alpha = np.full(img.shape[:2], 255, dtype=np.uint8)
        img = np.dstack([img, alpha])
    return img


def load_bgr(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img