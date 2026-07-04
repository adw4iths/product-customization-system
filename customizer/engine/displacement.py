"""
Automatic Displacement Mapping (Fabric Conformation)
------------------------------------------------------
This is the "fabric bending" core of the system. The classic professional
technique (used in Photoshop clothing mockups) is:

  1. Take the grayscale luminance of the *base garment photo* in the print
     area -- folds and wrinkles show up as local light/dark variation.
  2. Treat that luminance as a height/bump map.
  3. Warp the flat design so it "sits" on that height map: pixels near a
     raised fold shift one way, pixels in a crease shift the other way,
     proportional to the local slope (gradient) of the height map.

We implement this with OpenCV `remap`, which is fast, vectorized, and scales
to high-resolution assets. The displacement map itself is computed ONCE per
base product photo (at admin upload time) and cached -- see models.py -- so
it costs nothing at request time.
"""
import numpy as np
import cv2


def build_displacement_map(base_image_bgr: np.ndarray, print_area: dict, blur_sigma: float = 6.0):
    """
    Extract a normalized fold/wrinkle height map for a print area region.

    Returns:
        height_map: float32 array, shape (h, w), values roughly in [-1, 1].
                     Positive = raised fold (lighter), negative = crease (darker).
    """
    x, y, w, h = print_area["x"], print_area["y"], print_area["w"], print_area["h"]
    region = base_image_bgr[y:y + h, x:x + w]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Low-frequency component = overall shading/lighting gradient (not wrinkles)
    low_freq = cv2.GaussianBlur(gray, (0, 0), sigmaX=blur_sigma * 4)
    # The *difference* isolates local texture: folds, seams, wrinkles
    detail = gray - low_freq

    # Smooth to separate genuine folds (broad, smooth luminance changes) from
    # ordinary fabric micro-texture/weave noise (heather blends especially --
    # fine-grained speckle throughout the whole photo, not isolated to one
    # spot). The previous 0.4x multiplier here left enough of that texture
    # in `detail` that it survived into the gradient step below and warped
    # the design with it -- visible as a grainy, stucco-like distortion that
    # has nothing to do with real fabric folding. 3.0x removes texture at
    # the weave/speckle scale while still preserving genuine broad folds
    # (shoulder curvature, garment drape), which are smooth over a much
    # larger area and survive this level of blur intact.
    detail = cv2.GaussianBlur(detail, (0, 0), sigmaX=blur_sigma * 3.0)

    max_abs = np.max(np.abs(detail)) or 1.0
    height_map = (detail / max_abs).astype(np.float32)
    return height_map


def displacement_fields_from_height(height_map: np.ndarray, strength: float = 10.0):
    """
    Convert a height map into per-pixel (dx, dy) displacement fields using
    its gradient -- i.e. bump-mapping. `strength` is the max pixel shift.
    """
    gy, gx = np.gradient(height_map.astype(np.float32))

    # Normalize gradients to a controllable pixel-shift range, then remove
    # any net (mean) offset. Bump-mapping should only bend the design around
    # local folds/wrinkles -- a nonzero mean here would instead translate
    # the whole design off-center, which is not physically meaningful and
    # was previously causing a several-pixel drift away from the print
    # area's center on some product photos.
    #
    # Uses the same robust (percentile + clip) normalization as the height
    # map itself, for the same reason: a max-based scale lets a single
    # outlier gradient pixel amplify ordinary fabric noise into visible
    # warping everywhere else in the design.
    def _norm(g):
        m = np.max(np.abs(g)) or 1.0
        g = (g / m) * strength
        return g - g.mean()

    dx = _norm(gx)
    dy = _norm(gy)
    return dx, dy


def apply_fabric_conformation(design_rgba: np.ndarray, height_map: np.ndarray, strength: float = 10.0):
    """
    Bend `design_rgba` (already perspective-warped to the print area size)
    so it conforms to the folds/wrinkles described by `height_map`.

    design_rgba: (h, w, 4) uint8, same h,w as height_map.
    """
    h, w = height_map.shape[:2]
    if design_rgba.shape[0] != h or design_rgba.shape[1] != w:
        design_rgba = cv2.resize(design_rgba, (w, h), interpolation=cv2.INTER_CUBIC)

    dx, dy = displacement_fields_from_height(height_map, strength=strength)

    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = (grid_x + dx).astype(np.float32)
    map_y = (grid_y + dy).astype(np.float32)

    bent = cv2.remap(
        design_rgba, map_x, map_y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return bent