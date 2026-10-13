# Better 2D drawing import

Proposal following the RV-4 modelling sessions. Drawing processing is not yet
implemented; the three geometry shortcuts in version 0.3.0 are available now.

## Observed problem

The existing bridge can create an image plane from an image's total width/height
and trace points already expressed in model coordinates. It cannot open a PDF,
calibrate a selected drawing view, rectify a photographed sheet or convert image
pixel coordinates into a measured part contour.

A local inspection of RV-4 sheets 20, 21, 22, 23 and 26 found zero native text and
zero vector paths in each. Each page consists of 18-20 embedded raster images.
Extracting PDF vectors alone therefore cannot solve this user's drawings.
The original files and inspection report remain in the private model archive.

## Recommended workflow

1. **Inspect once:** page count, page bounds, text/vector/raster counts and a
   thumbnail. Report mixed pages rather than forcing a single classification.
2. **Select a view:** crop the relevant detail at high resolution. Pages mix full,
   half and quarter scale drawings; calibrate each detail independently.
3. **Calibrate:** use two picked points and a known distance for uniform scale.
   Three non-collinear point correspondences support an affine transform;
   four well-distributed point correspondences support perspective correction.
   Reserve an extra known dimension for a check that did not participate in fitting.
4. **Trace with constraints:** represent lines as lines and specified radii as
   arcs. Snap symmetry/centreline constraints and use drawing dimensions as
   authoritative input. Image-based curves remain approximate until checked.
5. **Review an overlay:** show the proposed contour over the source crop, with
   dimension residuals and uncertain segments. Corrections become reusable data.
6. **Create geometry:** pass approved outlines, thicknesses and bend definitions
   to reusable bridge tools; avoid generating another project-specific Python file.

The first useful feature is calibrated crops plus pixel-to-model mapping. OCR
and contour detection can follow; full automatic drawing-to-3D would conceal too
many assumptions in these old drawings.

## Proposed tools and data

| Tool | Inputs | Result |
| --- | --- | --- |
| `inspect_drawing` | PDF/image path, page | Content inventory, source fingerprint, preview |
| `prepare_drawing_view` | Page, crop, output resolution, optional rotation | PNG and exact source-to-pixel coordinate transform |
| `calibrate_drawing_view` | Picked points, known dimensions or correspondences, units | Model transform, assumptions, check residuals |
| `trace_drawing_view` | Pixel points, line/arc segments, constraints | Model-space polyline/curve and overlay |
| `read_dimension_candidates` | Crop, language, optional OCR | Text, bounding boxes, parsed values, ambiguity markers |

Store a small JSON record per detail: source fingerprint, page, crop coordinates,
pixel size, calibration points, transform, units, datum, revision, contour and
confidence/provenance per measurement. Preserve raw text such as `21 1/2` beside
its parsed value. Do not silently replace an inconsistent printed ordinate.

Coordinate conventions must be explicit: PDF coordinates and image pixels start
at the top left, model view coordinates generally increase upwards. Crop offsets,
page rotation and later resampling must be composed into the stored transform.
Do not calibrate against a screenshot that has been resized without its metadata.

## Vector PDFs versus scans

For genuine vector PDFs, PyMuPDF exposes drawing paths through `get_drawings()`;
it also exposes native text and clipped page rasterization. Prefer original line
and curve data to pixel tracing when present. Still separate contour, centreline,
dimension and hatch candidates: a vector path is not automatically a part edge.
See [PyMuPDF drawing extraction](https://pymupdf.readthedocs.io/en/latest/recipes-drawing-and-graphics.html)
and [page APIs](https://pymupdf.readthedocs.io/en/latest/page.html).

For scans, render the composed PDF page/crop instead of importing the first
embedded image: a page can be tiled, rotated or contain multiple image objects.
For skewed flat drawings, OpenCV offers affine and perspective transforms from
point correspondences. Perspective correction cannot recover a folded sheet's
surface or erase lens distortion by itself. See
[OpenCV geometric transforms](https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html).

OCR can provide text candidates for raster drawings; PyMuPDF's OCR interface
uses Tesseract. Fractions, diameter symbols and handwritten dimensions need
validation against the image. Confidence must not turn an inferred or uncertain
dimension into an exact model constraint.

## Architecture and implementation order

Process PDFs/images in the external MCP runtime, not Blender's main thread.
Keep PDF/OCR/OpenCV dependencies optional and separate from the base bridge.
Exchange JSON contours/transforms and preview files with the add-on, keeping
the same input usable for manual tracing, OCR and vector extraction.

1. Add inspection and reproducible high-resolution crop preparation.
2. Add uniform calibration, then affine calibration and independent check dimensions.
3. Add transformed traces and a visual overlay without changing model geometry.
4. Add native-vector extraction and constrained line/arc fitting.
5. Add perspective correction and OCR candidates when needed.

Test with small public synthetic vector and raster fixtures: mixed page scales,
rotated pages, tiled images, known distances, crop/resample chains and badly
conditioned calibration points. Reject degenerate calibration rather than
producing a plausible-looking scale. Private aircraft sheets stay local.
