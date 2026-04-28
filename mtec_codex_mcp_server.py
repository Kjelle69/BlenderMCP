"""
MTECCodexMCP
-------------
External MCP server for Codex/VS Code.
Talks MCP to Codex and HTTP to Blender via MTEC Blender Bridge.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BLENDER_BRIDGE_URL = os.environ.get("MTEC_BLENDER_BRIDGE_URL", "http://127.0.0.1:8765")
TIMEOUT = float(os.environ.get("MTEC_BLENDER_BRIDGE_TIMEOUT", "120"))

mcp = FastMCP("MTECCodexMCP")

def bridge_get(path: str) -> Any:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(f"{BLENDER_BRIDGE_URL}{path}")
        r.raise_for_status()
        return r.json()

def bridge_invoke(tool: str, **kwargs) -> Any:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            f"{BLENDER_BRIDGE_URL}/invoke",
            json={"tool": tool, "kwargs": kwargs},
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "Unknown bridge error"))
        return payload["result"]

@mcp.tool()
def blender_health() -> dict:
    """Check whether Blender bridge is reachable."""
    return bridge_get("/health")

@mcp.tool()
def blender_list_tools() -> dict:
    """List all tools currently exposed by the Blender bridge."""
    return bridge_get("/tools")

@mcp.tool()
def get_scene_info() -> dict:
    """Return basic scene information."""
    return bridge_invoke("get_scene_info")

@mcp.tool()
def set_bridge_options(
    view_mode: str | None = None,
    auto_focus: bool | None = None,
    auto_orbit: bool | None = None,
    smooth_view: bool | None = None,
    view_duration: float | None = None,
    cinematic_duration: float | None = None,
    cinematic_yaw_deg: float | None = None,
    cinematic_pitch_deg: float | None = None,
    cinematic_sweep_step_deg: float | None = None,
    cinematic_pitch_variation_deg: float | None = None,
    cinematic_distance_scale: float | None = None,
    cinematic_retain_distance: float | None = None,
    cinematic_dolly_variation: float | None = None,
    orbit_yaw_deg: float | None = None,
    orbit_pitch_deg: float | None = None,
    orbit_roll_deg: float | None = None,
) -> dict:
    """Configure bridge runtime options."""
    return bridge_invoke(
        "set_bridge_options",
        view_mode=view_mode,
        auto_focus=auto_focus,
        auto_orbit=auto_orbit,
        smooth_view=smooth_view,
        view_duration=view_duration,
        cinematic_duration=cinematic_duration,
        cinematic_yaw_deg=cinematic_yaw_deg,
        cinematic_pitch_deg=cinematic_pitch_deg,
        cinematic_sweep_step_deg=cinematic_sweep_step_deg,
        cinematic_pitch_variation_deg=cinematic_pitch_variation_deg,
        cinematic_distance_scale=cinematic_distance_scale,
        cinematic_retain_distance=cinematic_retain_distance,
        cinematic_dolly_variation=cinematic_dolly_variation,
        orbit_yaw_deg=orbit_yaw_deg,
        orbit_pitch_deg=orbit_pitch_deg,
        orbit_roll_deg=orbit_roll_deg,
    )

@mcp.tool()
def cinematic_reveal_selection(
    object_names: list[str] | None = None,
    duration: float | None = None,
    steps: int = 5,
) -> dict:
    """Run a cinematic viewport reveal for selected objects."""
    return bridge_invoke(
        "cinematic_reveal_selection",
        object_names=object_names,
        duration=duration,
        steps=steps,
    )

@mcp.tool()
def list_objects(object_type: str = "") -> dict:
    """List objects in the current Blender scene."""
    return bridge_invoke("list_objects", object_type=object_type)

@mcp.tool()
def get_object_info(
    object_name: str,
    include_modifiers: bool = True,
    include_materials: bool = True,
) -> dict:
    """Return detailed information for one Blender object."""
    return bridge_invoke(
        "get_object_info",
        object_name=object_name,
        include_modifiers=include_modifiers,
        include_materials=include_materials,
    )

@mcp.tool()
def create_mesh_object(
    primitive_type: str = "cube",
    name: str = "",
    size: float = 2.0,
    location: list[float] | None = None,
    rotation_deg: list[float] | None = None,
    scale: list[float] | None = None,
) -> dict:
    """Create a Blender primitive mesh object."""
    return bridge_invoke(
        "create_mesh_object",
        primitive_type=primitive_type,
        name=name,
        size=size,
        location=location,
        rotation_deg=rotation_deg,
        scale=scale,
    )

@mcp.tool()
def create_mesh_from_pydata(
    name: str,
    vertices: list[list[float]],
    edges: list[list[int]] | None = None,
    faces: list[list[int]] | None = None,
    location: list[float] | None = None,
    rotation_deg: list[float] | None = None,
    scale: list[float] | None = None,
) -> dict:
    """Create a Blender mesh from explicit vertices/edges/faces."""
    return bridge_invoke(
        "create_mesh_from_pydata",
        name=name,
        vertices=vertices,
        edges=edges,
        faces=faces,
        location=location,
        rotation_deg=rotation_deg,
        scale=scale,
    )

@mcp.tool()
def create_curve_object(
    curve_type: str = "bezier",
    name: str = "Curve",
    points: list[list[float]] | None = None,
    bevel_depth: float = 0.0,
    cyclic: bool = False,
) -> dict:
    """Create a Blender curve object."""
    return bridge_invoke(
        "create_curve_object",
        curve_type=curve_type,
        name=name,
        points=points,
        bevel_depth=bevel_depth,
        cyclic=cyclic,
    )

@mcp.tool()
def create_text_object(
    text: str = "Hello Blender",
    name: str = "Text",
    location: list[float] | None = None,
    rotation_deg: list[float] | None = None,
    size: float = 1.0,
    extrude: float = 0.0,
) -> dict:
    """Create a Blender text object."""
    return bridge_invoke(
        "create_text_object",
        text=text,
        name=name,
        location=location,
        rotation_deg=rotation_deg,
        size=size,
        extrude=extrude,
    )

@mcp.tool()
def transform_object(
    object_name: str,
    location: list[float] | None = None,
    rotation_deg: list[float] | None = None,
    scale: list[float] | None = None,
    delta: bool = False,
) -> dict:
    """Transform an object."""
    return bridge_invoke(
        "transform_object",
        object_name=object_name,
        location=location,
        rotation_deg=rotation_deg,
        scale=scale,
        delta=delta,
    )

@mcp.tool()
def duplicate_object(
    object_name: str,
    linked: bool = False,
    count: int = 1,
    offset: list[float] | None = None,
) -> dict:
    """Duplicate object(s)."""
    return bridge_invoke(
        "duplicate_object",
        object_name=object_name,
        linked=linked,
        count=count,
        offset=offset,
    )

@mcp.tool()
def select_objects(
    object_names: list[str],
    active_object: str = "",
    replace: bool = True,
) -> dict:
    """Select objects and optionally choose the active object."""
    return bridge_invoke(
        "select_objects",
        object_names=object_names,
        active_object=active_object,
        replace=replace,
    )

@mcp.tool()
def set_mode(mode: str = "OBJECT", object_name: str = "") -> dict:
    """Set Blender interaction mode for the active or provided object."""
    return bridge_invoke("set_mode", mode=mode, object_name=object_name)

@mcp.tool()
def apply_transforms(
    object_name: str,
    location: bool = False,
    rotation: bool = True,
    scale: bool = True,
) -> dict:
    """Apply object transforms."""
    return bridge_invoke(
        "apply_transforms",
        object_name=object_name,
        location=location,
        rotation=rotation,
        scale=scale,
    )

@mcp.tool()
def delete_objects(object_names: list[str]) -> dict:
    """Delete Blender objects by name."""
    return bridge_invoke("delete_objects", object_names=object_names)

@mcp.tool()
def create_collection(name: str, parent: str = "") -> dict:
    """Create a collection in the current scene."""
    return bridge_invoke("create_collection", name=name, parent=parent)

@mcp.tool()
def move_to_collection(object_name: str, collection_name: str, unlink_others: bool = False) -> dict:
    """Move or link an object into a collection."""
    return bridge_invoke(
        "move_to_collection",
        object_name=object_name,
        collection_name=collection_name,
        unlink_others=unlink_others,
    )

@mcp.tool()
def create_material(
    name: str,
    base_color: list[float] | None = None,
    metallic: float = 0.0,
    roughness: float = 0.5,
) -> dict:
    """Create a basic principled material."""
    return bridge_invoke(
        "create_material",
        name=name,
        base_color=base_color,
        metallic=metallic,
        roughness=roughness,
    )

@mcp.tool()
def assign_material(object_name: str, material_name: str) -> dict:
    """Assign a material to an object."""
    return bridge_invoke("assign_material", object_name=object_name, material_name=material_name)

@mcp.tool()
def create_blueprint_plane(
    image_path: str,
    view: str = "side",
    name: str = "",
    real_width: float | None = None,
    real_height: float | None = None,
    plane_offset: float = 0.0,
    location: list[float] | None = None,
    opacity: float = 0.55,
    collection: str = "Blueprints",
    lock: bool = True,
    show_in_front: bool = True,
) -> dict:
    """Create a calibrated side/top/front image plane for blueprint modelling."""
    return bridge_invoke(
        "create_blueprint_plane",
        image_path=image_path,
        view=view,
        name=name,
        real_width=real_width,
        real_height=real_height,
        plane_offset=plane_offset,
        location=location,
        opacity=opacity,
        collection=collection,
        lock=lock,
        show_in_front=show_in_front,
    )

@mcp.tool()
def setup_blueprint_scene(
    blueprints: list[dict],
    collection: str = "Blueprints",
    hide_existing: bool = False,
) -> dict:
    """Create multiple calibrated blueprint planes."""
    return bridge_invoke(
        "setup_blueprint_scene",
        blueprints=blueprints,
        collection=collection,
        hide_existing=hide_existing,
    )

@mcp.tool()
def create_trace_curve(
    name: str,
    view: str = "side",
    points: list[list[float]] | None = None,
    plane_offset: float = 0.0,
    curve_type: str = "bezier",
    cyclic: bool = False,
    bevel_depth: float = 0.01,
    collection: str = "Blueprint Traces",
) -> dict:
    """Create a trace curve on a side/top/front blueprint plane."""
    return bridge_invoke(
        "create_trace_curve",
        name=name,
        view=view,
        points=points,
        plane_offset=plane_offset,
        curve_type=curve_type,
        cyclic=cyclic,
        bevel_depth=bevel_depth,
        collection=collection,
    )

@mcp.tool()
def create_measurement(
    name: str,
    point_a: list[float],
    point_b: list[float],
    view: str = "side",
    plane_offset: float = 0.0,
    collection: str = "Blueprint Measurements",
) -> dict:
    """Create a visible measurement line and return its scene-unit length."""
    return bridge_invoke(
        "create_measurement",
        name=name,
        point_a=point_a,
        point_b=point_b,
        view=view,
        plane_offset=plane_offset,
        collection=collection,
    )

@mcp.tool()
def sample_curve_points(object_name: str, samples_per_spline: int = 64) -> dict:
    """Sample world-space points from a Blender curve."""
    return bridge_invoke(
        "sample_curve_points",
        object_name=object_name,
        samples_per_spline=samples_per_spline,
    )

@mcp.tool()
def set_origin(
    object_name: str,
    origin_type: str = "ORIGIN_GEOMETRY",
    center: str = "MEDIAN",
) -> dict:
    """Set an object's origin."""
    return bridge_invoke(
        "set_origin",
        object_name=object_name,
        origin_type=origin_type,
        center=center,
    )

@mcp.tool()
def convert_object(object_name: str, target: str = "MESH") -> dict:
    """Convert an object to another Blender data type."""
    return bridge_invoke("convert_object", object_name=object_name, target=target)

@mcp.tool()
def create_light(
    light_type: str = "POINT",
    name: str = "Light",
    location: list[float] | None = None,
    rotation_deg: list[float] | None = None,
    energy: float = 1000.0,
) -> dict:
    """Create a light."""
    return bridge_invoke(
        "create_light",
        light_type=light_type,
        name=name,
        location=location,
        rotation_deg=rotation_deg,
        energy=energy,
    )

@mcp.tool()
def create_camera(
    name: str = "Camera",
    location: list[float] | None = None,
    rotation_deg: list[float] | None = None,
    focal_length: float = 50.0,
    set_active: bool = True,
) -> dict:
    """Create a camera."""
    return bridge_invoke(
        "create_camera",
        name=name,
        location=location,
        rotation_deg=rotation_deg,
        focal_length=focal_length,
        set_active=set_active,
    )

@mcp.tool()
def add_modifier(
    object_name: str,
    modifier_type: str,
    name: str = "",
    settings: dict | None = None,
) -> dict:
    """Add a modifier to an object."""
    return bridge_invoke(
        "add_modifier",
        object_name=object_name,
        modifier_type=modifier_type,
        name=name,
        settings=settings,
    )

@mcp.tool()
def apply_modifier(object_name: str, modifier_name: str) -> dict:
    """Apply a modifier."""
    return bridge_invoke("apply_modifier", object_name=object_name, modifier_name=modifier_name)

@mcp.tool()
def boolean_operation(
    object_a: str,
    object_b: str,
    operation: str = "DIFFERENCE",
    solver: str = "FAST",
    apply: bool = True,
) -> dict:
    """Boolean operation between two objects."""
    return bridge_invoke(
        "boolean_operation",
        object_a=object_a,
        object_b=object_b,
        operation=operation,
        solver=solver,
        apply=apply,
    )

@mcp.tool()
def configure_render_settings(
    engine: str = "CYCLES",
    samples: int = 128,
    resolution_x: int = 1920,
    resolution_y: int = 1080,
) -> dict:
    """Configure render settings."""
    return bridge_invoke(
        "configure_render_settings",
        engine=engine,
        samples=samples,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
    )

@mcp.tool()
def render_image(output_path: str, use_viewport: bool = False) -> dict:
    """Render a still image to disk."""
    return bridge_invoke("render_image", output_path=output_path, use_viewport=use_viewport)

@mcp.tool()
def import_file(file_path: str) -> dict:
    """Import a supported 3D file into Blender."""
    return bridge_invoke("import_file", file_path=file_path)

@mcp.tool()
def export_file(file_path: str, selected_only: bool = False) -> dict:
    """Export supported 3D file from Blender."""
    return bridge_invoke("export_file", file_path=file_path, selected_only=selected_only)

@mcp.tool()
def save_blend_file(file_path: str) -> dict:
    """Save current .blend file."""
    return bridge_invoke("save_blend_file", file_path=file_path)

@mcp.tool()
def clear_scene(keep_cameras: bool = True, keep_lights: bool = True) -> dict:
    """Clear current scene."""
    return bridge_invoke("clear_scene", keep_cameras=keep_cameras, keep_lights=keep_lights)

@mcp.tool()
def set_timeline_frame(frame: int) -> dict:
    """Set the current Blender timeline frame."""
    return bridge_invoke("set_timeline_frame", frame=frame)

@mcp.tool()
def set_viewport_shading(
    shading_type: str = "RENDERED",
    use_scene_lights: bool = True,
    use_scene_world: bool = True,
) -> dict:
    """Set shading mode for visible 3D viewports."""
    return bridge_invoke(
        "set_viewport_shading",
        shading_type=shading_type,
        use_scene_lights=use_scene_lights,
        use_scene_world=use_scene_world,
    )

@mcp.tool()
def set_rigid_body_world(
    frame_start: int | None = None,
    frame_end: int | None = None,
    substeps_per_frame: int | None = None,
    solver_iterations: int | None = None,
    gravity: list[float] | None = None,
    enabled: bool | None = None,
) -> dict:
    """Configure the scene rigid body world."""
    return bridge_invoke(
        "set_rigid_body_world",
        frame_start=frame_start,
        frame_end=frame_end,
        substeps_per_frame=substeps_per_frame,
        solver_iterations=solver_iterations,
        gravity=gravity,
        enabled=enabled,
    )

@mcp.tool()
def add_rigid_body(
    object_name: str,
    body_type: str = "ACTIVE",
    collision_shape: str = "BOX",
    mass: float = 1.0,
    friction: float = 0.5,
    restitution: float = 0.0,
    collision_margin: float = 0.04,
    linear_damping: float = 0.04,
    angular_damping: float = 0.1,
    use_margin: bool = True,
    enabled: bool = True,
) -> dict:
    """Add a rigid body to an object."""
    return bridge_invoke(
        "add_rigid_body",
        object_name=object_name,
        body_type=body_type,
        collision_shape=collision_shape,
        mass=mass,
        friction=friction,
        restitution=restitution,
        collision_margin=collision_margin,
        linear_damping=linear_damping,
        angular_damping=angular_damping,
        use_margin=use_margin,
        enabled=enabled,
    )

@mcp.tool()
def configure_rigid_body(
    object_name: str,
    body_type: str | None = None,
    collision_shape: str | None = None,
    mass: float | None = None,
    friction: float | None = None,
    restitution: float | None = None,
    collision_margin: float | None = None,
    linear_damping: float | None = None,
    angular_damping: float | None = None,
    use_margin: bool | None = None,
    enabled: bool | None = None,
) -> dict:
    """Configure an existing rigid body."""
    return bridge_invoke(
        "configure_rigid_body",
        object_name=object_name,
        body_type=body_type,
        collision_shape=collision_shape,
        mass=mass,
        friction=friction,
        restitution=restitution,
        collision_margin=collision_margin,
        linear_damping=linear_damping,
        angular_damping=angular_damping,
        use_margin=use_margin,
        enabled=enabled,
    )

@mcp.tool()
def free_bake() -> dict:
    """Free all physics cache bakes."""
    return bridge_invoke("free_bake")

@mcp.tool()
def reset_physics_simulation(frame: int | None = None) -> dict:
    """Clear physics caches and reset the timeline."""
    return bridge_invoke("reset_physics_simulation", frame=frame)

@mcp.tool()
def bake_to_frame(frame_end: int, frame_start: int | None = None) -> dict:
    """Bake physics caches up to a frame."""
    return bridge_invoke("bake_to_frame", frame_end=frame_end, frame_start=frame_start)

@mcp.tool()
def add_impactor(
    name: str = "Impactor",
    location: list[float] | None = None,
    radius: float = 1.0,
    mass: float = 25.0,
    collision_shape: str = "SPHERE",
    friction: float = 0.4,
    restitution: float = 0.05,
    subdivisions: int = 3,
) -> dict:
    """Create a heavy rigid body impactor sphere."""
    return bridge_invoke(
        "add_impactor",
        name=name,
        location=location,
        radius=radius,
        mass=mass,
        collision_shape=collision_shape,
        friction=friction,
        restitution=restitution,
        subdivisions=subdivisions,
    )

@mcp.tool()
def build_and_smash_demo(
    base_size: int = 5,
    cube_size: float = 1.0,
    impactor_mass: float = 60.0,
    impactor_height: float = 12.0,
) -> dict:
    """Build a lit rigid-body cube demo scene with cinematic reveal."""
    return bridge_invoke(
        "build_and_smash_demo",
        base_size=base_size,
        cube_size=cube_size,
        impactor_mass=impactor_mass,
        impactor_height=impactor_height,
    )

@mcp.tool()
def call_operator(operator_id: str, kwargs: dict | None = None) -> dict:
    """Generic bpy.ops bridge for advanced operations."""
    return bridge_invoke("call_operator", operator_id=operator_id, kwargs=kwargs)

@mcp.tool()
def run_python_snippet(code: str) -> dict:
    """Run a Python snippet inside Blender. Powerful but risky."""
    return bridge_invoke("run_python_snippet", code=code)

if __name__ == "__main__":
    mcp.run()
