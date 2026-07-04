# High-Performance Product Customization System

A Django + DRF system that places a user's uploaded design onto product
photos (hoodie, cap, tee, ...) so it looks genuinely printed on the fabric:
correct perspective, correct fold/wrinkle bending, and correct lighting —
computed **automatically**, with no manual per-photo corner mapping.

## What's actually been tested, and how (read this first)

I don't have internet access in my own dev sandbox, so I could not run
`pip install django` there and launch a live server myself. To avoid
overstating what's verified, here's the honest breakdown:

**Execution-tested, with numeric proof (not just eyeballed):**
- The entire image-processing engine (`customizer/engine/`) — perspective
  detection, fold/wrinkle bump-mapping, lighting-aware blending — run
  directly, dozens of times, across 9 different product photos and 4
  different uploaded logos (including low-res, non-transparent, and
  asymmetric ones). Centering was measured to be within 0.5px of true
  center on every test. Sharpness improvements were measured with
  Laplacian variance, not just "looks sharper."

**Verified by other means, since Django itself can't run in my sandbox:**
- Every `.py` file passes `python -m py_compile` (catches syntax errors).
- Every model field is cross-checked by hand against every serializer,
  admin registration, view, signal, and task that touches it.
- The initial migration (`customizer/migrations/0001_initial.py`) is
  hand-written to match `models.py` field-for-field, so `migrate` works
  without needing you to run `makemigrations` first — but since I can't
  execute it myself, **you should run `makemigrations` anyway on first
  setup as a safety check** (see below); Django will simply say "no
  changes detected" if my migration already matches, or generate a small
  `0002` if I made a mistake somewhere.
- **A real bug was caught this way and fixed**: `seed_demo.py` creates a
  `ProductImage` row via `get_or_create()` *before* attaching the photo
  file, which would have fired the analysis signal against an empty file
  and crashed on first run. Fixed in `signals.py` with a guard that skips
  analysis until a file is actually attached.
- **A second real bug was caught and fixed**: the demo page's `fetch()`
  calls send no CSRF token. This is invisible if you test anonymously, but
  fails with 403 if the same browser also has an active `/admin/` login.
  Fixed by making the two API views explicitly public
  (`authentication_classes = []`), so CSRF enforcement never applies to them.

**Bottom line:** the hard, novel part (the rendering engine) has been
hammered on and measured. The Django scaffolding around it has been
reviewed line-by-line and had two real bugs caught and fixed by that
review, but the *only* way to be 100% certain a Django project boots
cleanly is to actually boot it — so run the smoke test below on your
machine before you submit. It should take under 5 minutes and every step
has an expected output so you know immediately if something's wrong.

## Smoke test checklist (run this before you submit)

```bash
pip install -r requirements.txt

# 1. Migrations — expect either "No changes detected" or a small 0002.
python manage.py makemigrations customizer
python manage.py migrate
# Expect: a list of "Applying customizer.0001_initial... OK" lines.

# 2. Seed the 9 sample products (auto-calibrated + manually-specified print areas)
python manage.py seed_demo
# Expect: 9 lines like "Created Hoodie / front  print_area={...}"

# 3. Admin sanity check
python manage.py createsuperuser
python manage.py runserver
# Visit http://localhost:8000/admin/ , log in, open Product Images —
# you should see 9 rows with print areas filled in, and a related
# "Product Image Analysis" row auto-created for each (proves the signal ran).

# 4. API sanity check (new terminal, server still running)
curl -F "file=@/path/to/any_logo.png" http://localhost:8000/api/designs/
# Expect: {"id": "<uuid>", "file": "...", "uploaded_at": "..."}

curl -X POST http://localhost:8000/api/customize/ \
  -H "Content-Type: application/json" \
  -d '{"design_id": "<uuid from above>", "product_image_id": 1}'
# Expect: {"id": "<job_id>", "status": "pending", ...}  (202 Accepted)

# 5. Render check
# With CELERY_TASK_ALWAYS_EAGER=True (see below) this resolves instantly;
# otherwise start `celery -A config worker --loglevel=info` in another
# terminal first, then:
curl http://localhost:8000/api/customize/<job_id>/
# Expect: "status": "done" and a "result_image" URL. Open it — the logo
# should be centered, warped to the product's shape, and shaded like it's
# printed on the fabric.

# 6. Browser demo
# Visit http://localhost:8000/ , pick a product, upload a logo, click
# Generate Mockup. Should show a live status line then the rendered image.
```

**No Redis on hand for step 5?** Add this one line to `config/settings.py`:
```python
CELERY_TASK_ALWAYS_EAGER = True
```
Jobs then run synchronously in-process — fine for the smoke test and for a
local demo, but take it back out before presenting the concurrency story,
since it defeats the purpose of the Celery queue.

## How this maps to the brief

### A. Product Data & Assets
- `customizer/models.py`: `Product`, `ProductImage` (per-angle base photo +
  admin-defined print area `x, y, w, h`, plus a tunable `max_tilt_deg`
  safety clamp per photo).
- **Automated Image Analysis** — `customizer/engine/perspective.py` and
  `engine/displacement.py`:
  - *Perspective Detection*: estimates surface tilt from the dominant edge
    orientation (gradient/structure-tensor analysis, Sobel-based) along the
    silhouette on either side of the print area — no manual quad entry.
  - *Automatic Displacement Mapping*: extracts a fold/wrinkle "height map"
    from the base photo's luminance detail (unsharp-mask style: high-pass
    the grayscale image), the same principle professional mockup tools use
    for bump-mapped clothing renders.
  - This analysis runs **once** per product photo via a `post_save` signal
    (`customizer/signals.py`) and is cached in `ProductImageAnalysis`
    (quad as JSON, height map as a `.npy` file) — never recomputed per
    customer request.

### B. Image Rendering Logic — `customizer/engine/pipeline.py`
1. **Fit + Perspective Alignment**: the uploaded design is first scaled to
   fit the print area *preserving its aspect ratio* (centered, not
   stretched), then `cv2.getPerspectiveTransform` + `warpPerspective`
   (cubic interpolation) applies the cached tilt quad.
2. **Fabric Conformation**: `cv2.remap` (cubic interpolation) using
   per-pixel displacement fields derived from the height map's gradient
   (bump-mapping), zero-mean by construction so bending never drags the
   design off-center.
3. **Guaranteed centering**: after warping, the design's actual visual
   centroid is measured and any residual drift is corrected — the output
   is verified centered to sub-pixel precision regardless of tilt/fold
   parameters, rather than hoping the heuristics cancel out.
4. **Realistic Blending** — `engine/blending.py`: an unsharp-mask pass
   recovers crispness lost through the resample chain (important for
   low-resolution uploaded logos), then the design is multiplied by a
   normalized lighting map from the base photo (so shadows/highlights show
   through) and composited with a feathered alpha mask.

### C. Performance and Concurrency
- **Concurrency Handling**: `customizer/tasks.py` — rendering runs as a
  **Celery task**, not inline in the request/response cycle. `POST
  /api/customize/` returns a job id immediately; workers scale horizontally
  and hold no state between jobs, so throughput scales with worker count,
  not request count.
- **Efficiency**: the expensive analysis (perspective + displacement
  detection) is precomputed once and cached, so the per-request path is
  pure vectorized NumPy/OpenCV (`warpPerspective` + `remap` + array math) —
  no per-request image analysis, no Python pixel loops.

## Project layout
```
config/                  Django project settings, celery app, urls
customizer/
  engine/                 pure image-processing pipeline (no Django deps)
    perspective.py        auto perspective/tilt detection
    displacement.py        auto fold/wrinkle height map + bump-map warp
    blending.py             lighting-aware compositing + sharpening
    calibration.py          red-guide-box detector (demo assets only)
    pipeline.py             analyze_product_image() + render_customization()
  models.py               Product, ProductImage (+max_tilt_deg),
                          ProductImageAnalysis (cache), DesignUpload,
                          CustomizationJob
  migrations/0001_initial.py   hand-verified, matches models.py field-for-field
  signals.py              triggers Phase-1 analysis on save (guards against
                          firing before a file is attached)
  tasks.py                Celery task for Phase-2 render (concurrency)
  views.py / serializers.py / urls.py     DRF API (public, no CSRF trap)
  templates/customizer/demo.html          minimal browser demo
  management/commands/seed_demo.py        loads 9 sample products
media/products/...       9 sample base photos (4 auto-calibrated from the
                         brief PDF's guide boxes, 5 real-world photos with
                         manually-specified print areas)
media/designs/            sample test logos used during development
demo_output/              pre-rendered proof images
```

## Product catalog seeded by `seed_demo`
| Product | View | Print area source |
|---|---|---|
| Hoodie | front, back | auto-calibrated from PDF guide box |
| Cap | front, back | auto-calibrated from PDF guide box |
| Pink Tee | back | manually specified |
| Maroon Tee | front | manually specified |
| Two-Tone Cap | side | manually specified |
| Two-Tone Cap Alt | side | manually specified (exact decoration spec: left=1317, top=1063, w=552, h=441) |
| Khaki Cap | front | manually specified |

## Honest scope notes (worth saying out loud in your submission)
- Perspective/displacement detection is a fast, real, working **heuristic**
  (gradient/structure-tensor tilt + luminance-based bump mapping) — the
  same family of technique commercial mockup generators use. It is not a
  full 3D pose/depth neural model. On one product (a cap side profile with
  busy stitching) the tilt detector saturated at its safety clamp, which is
  a signal it was over-estimating tilt — handled by lowering `max_tilt_deg`
  for that specific photo (a real, admin-tunable field), not hidden.
- `fold_strength` (how strongly fabric folds bend the design) is a pipeline
  parameter but not yet exposed as a per-photo model field the way
  `max_tilt_deg` is — straightforward follow-up if you need it.
- If you upload a design PNG with a solid background instead of real
  transparency, it will paste as a rectangle. Worth a pre-upload check in
  a production version; not currently validated server-side.
