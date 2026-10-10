# MTEC Blender Bridge Development Plan

This plan captures gaps found during real modelling sessions and turns them into bridge/tooling work items.

## Priorities

### 1. Stability for long Blender operations

- Add request-level timeout reporting that returns partial progress instead of closing the HTTP connection.
- Add a job API for heavy operations: `start_job`, `get_job_status`, `cancel_job`, `get_job_result`.
- Keep Blender responsive by running long mesh/modifier tasks in small chunks through timers.
- Add clear error payloads with traceback text for `run_python_snippet` failures.

### 2. Safer geometry workflows

- Add dedicated tools for common modelling operations instead of relying on large raw Python snippets:
  - `create_solid_sole`
  - `create_strap_surface`
  - `create_heel_cup`
  - `create_perforation_pattern`
  - `emboss_text_on_surface`
- Add mesh validation tools:
  - outward normal checks
  - non-manifold edge counts
  - open boundary detection
  - dimensions and wall-thickness checks
  - optional repair: recalc normals, merge duplicate vertices, fill small holes
- Add a boolean preview/apply workflow that can hide cutters, apply one modifier at a time, and roll back on failure.

### 3. Print-focused product modelling

- Add print-safe presets for flexible footwear:
  - minimum wall thickness
  - minimum post diameter
  - drainage hole spacing
  - tread depth
  - bevel/radius defaults
- Add material-zone support so one object can keep different visual zones, such as black sole and blue upper.
- Add export checks before STL/3MF export: scale, units, modifiers, hidden cutters, and manifold status.

### 4. Surface-aware text and decals

- Add an `emboss_text_on_surface` tool that places text on a curved surface using sampled normals.
- Support readable orientation controls: from toe, from heel, mirrored left/right, centered on object.
- Add options for raised emboss, recessed deboss, and separate-color inlay.

### 5. Viewport and session feedback

- Add lightweight viewport screenshot/render helpers for visual QA after each modelling step.
- Add `frame_objects` and `set_camera_to_objects` tools that work reliably after generated geometry.
- Add a compact scene summary showing visible object count, hidden cutters, active modifiers, and selected objects.

### 6. Bridge observability

- Log every tool call with duration, object counts before/after, and exception details.
- Add `/status` with current job state, last error, and Blender busy/idle state.
- Add `/diagnostics` with addon version, Blender version, Python version, active scene name, and memory hints.

## Lessons From The Bath-Slipper Session

- Heavy boolean patterns can crash or timeout the bridge if done in one raw snippet.
- Live boolean cutters should default to hidden and be grouped in a cutter collection.
- Perforation tools need rollback because a failed boolean can visually destroy one side of a pair.
- Separate product parts are easier to repair than one giant mesh while iterating.
- Text placement needs surface normals; flat text looks wrong on curved straps.
- Heel retention geometry needs explicit attachment points, not only floating curve arcs.

## Suggested Implementation Order

1. Add structured error payloads and traceback forwarding for `run_python_snippet`.
2. Add job/status endpoints for long-running operations.
3. Add mesh validation and normal repair tools.
4. Add safe boolean/perforation workflow with hidden cutter collections and rollback.
5. Add surface-aware emboss/deboss text tool.
6. Add print-readiness checks and STL/3MF export helpers.

