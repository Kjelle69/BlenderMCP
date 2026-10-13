# Modelling shortcuts extracted from build scripts

The first three tools below are implemented in version 0.3.0: `validate_meshes`,
`replace_mesh_geometry` and `create_profile_member`. The remaining tools are proposals.
They come from the local RV-4 and
BSA scripts archived in `_local_builds/`. Model dimensions, aircraft station
tables, part names and reference drawings must stay outside the bridge.

## Existing tools

`create_mesh_from_pydata`, `create_curve_object`, `add_modifier`,
`boolean_operation`, `create_collection`, `assign_material`, `create_measurement`,
`render_image` and `save_blend_file` already cover individual steps. The scripts
repeat preparation, placement, cleanup and checks around them. Wrap these
workflows instead of duplicating primitive tools.

## Prioritized additions

| Priority | Proposed tool | Repeated workflow | Evidence in archived scripts |
| --- | --- | --- | --- |
| 1 | `validate_meshes` | Evaluated meshes, non-manifold edges, finite coordinates and dimensions | `rv4_front_details_check.py`, `rv4_all_bulkheads_check.py` |
| 1 | `replace_mesh_geometry` | Update parts without losing identity, collections, placement or material policy | `rv4_front_details_live.py`, `rv4_bulkhead_21_live.py` |
| 1 | `create_profile_member` | L/U/rectangular sections extruded along a line or stations | `rv4_front_details.py:angle`, `rv4_tail_structure.py:channel` |
| 1 | `create_formed_sheet` | Outline, thickness, flanges, straight bends and reliefs | `rv4_front_details.py:sheet/flange`, `rv4_f401_fold.py` |
| 2 | `cut_openings` | Circles, rounded rectangles, edge notches and temporary cutter cleanup | `rv4_f419_aft_extension.py`, `rv4_f410_single.py` |
| 2 | `preview_objects` | Isolate parts, aim an orthographic camera, render and restore state | `rv4_front_details_check.py`, `*_preview.py` |
| 2 | `measure_geometry` | Station distances, projected widths, datum angles and clearance | `rv4_bulkhead_dimensions.py`, `rv4_deck_clearance.py` |
| 3 | `loft_sections` | Skins from matched cross sections, end caps and thickness | `rv4_skin_fit.py`, `rv4_blockout.py:loft`, `bsa_500_build.py:panel` |
| 3 | `sample_outline` | Shape-preserving interpolation of ordinate tables and symmetry | `rv4_all_bulkheads.py:pchip/sample/closed` |
| 3 | `place_along_segment` | Cylinder/cone/beam alignment between two points | `bsa_500_build.py:cyl` |

## Common contract

- Explicit `units=m|mm|in`; normalize lengths once to Blender meters. Angles in degrees.
- Planar reference frame (`origin`, `axis_u`, `axis_v`), named material and collection.
  Reject degenerate/non-orthogonal frames.
- Explicit creation/update policy. Duplicate names fail by default; require
  replacement to avoid accidental `.001` copies.
- Return names, bounds, actual dimensions and validation results rather than
  every Python local variable or the entire scene.
- Prepare and validate temporary geometry before replacing an existing mesh.
- Restore selection and active scene where possible. Preview tools must restore
  camera, visibility and render settings even when rendering fails.

## First implementation slice

Start with validation, mesh replacement and straight profile members. These
have small, testable contracts and remove repeated boilerplate from most builds.
Follow with formed sheets and openings using the same mesh lifecycle.

### Mesh validation

Inputs: named objects, evaluated/raw mesh, units, optional expected dimensions
and tolerance. Read-only by default; repair must be explicit.
Return boundary/non-manifold counts, degenerate faces, non-finite coordinates,
mesh counts and bounds. Open sheet surfaces are intentional in some workflows,
so use `require_closed` instead of treating all boundaries as errors.

### Geometry replacement

Inputs: target, vertices/faces or a source object, explicit material/modifier/
transform policies. Default to preserving object identity and placement.
Replace only the named object's mesh; require opt-in to update shared mesh users.

A later library-loading extension can centralize `.blend` append/update. Copy
requested names before assigning `destination.objects` (Blender mutates that
list); resolve existing targets before appending and remove unused appended objects.

### Profile members

Inputs: `profile=L|U|RECT|CUSTOM`, section dimensions, thickness, start/end or
stations, reference normal and common placement options. Define section
orientation; reject zero-length paths. Cap solids and retain hollow interiors.
Start with straight members; curved paths need explicit twist/corner policies.

### Formed sheets

Inputs: outline, thickness, frame, optional flanges and bends. Flanges specify
edge, width, side, angle and end relief. Bends specify line, moving side, angle
and radius. Mirror operations must correct face winding and normal direction.

Start with planar polygons and straight, non-intersecting bends, not a universal
sheet-metal solver. Split faces along bend lines before rotating. Radius,
chamfer and relief must be explicit: an invented rounded edge changed the
intended part during the RV-4 work. Keep drawing-specific profiles as input data.

### Openings

Inputs: targets, circle/rounded-rectangle/polygon descriptors, orientation,
clearance, depth and apply/cutter-retention policies. Derive through-depth from
evaluated bounds when requested. Edge notches are polygons crossing an edge.
Rollback geometry if a boolean fails validation; delete only cutters from this call.

## Later workflow improvements

- `execute_operations`: structured sequences of existing tools, per-step results,
  one viewport update and stop-on-error. Do not call it transactional until rollback exists.
- `snapshot_objects`: back up selected parts/collections without changing the
  active file or scene.
- `measure_geometry`: distinguish signed plane distances and axis projections
  from true surface clearance. Bounds cannot prove that parts do not intersect.
- `preview_objects`: front/back/side presets and several views in one call.
- `run_python_snippet`: explicit JSON `result` and recursive-namespace handling.
  Returning all locals caused serialization failures with modules and cyclic
  execution dictionaries in the live-update scripts.

## Implementation and verification

Separate pure section/outline calculations from Blender scene changes.
Register tools both in the add-on's `TOOLS` dictionary and as wrappers in
`mtec_codex_mcp_server.py`; exposure in `/tools` alone does not add an MCP tool.
Add any helper module explicitly to the ZIP allowlist.

Test in disposable background Blender scenes: inch-sized angle, U-channel,
folded sheet with relief, through-hole under a rotated transform and replacement
with shared mesh users. Check dimensions, required closedness, material/collection
preservation and cleanup on failure. Preview tests must verify state restoration.
Public tests use generic shapes; private aircraft drawings stay in the local archive.
