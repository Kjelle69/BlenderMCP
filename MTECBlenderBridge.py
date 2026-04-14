bl_info = {
    "name": "MTEC Blender Bridge",
    "author": "OpenAI + MTEC",
    "version": (0, 2, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MTEC MCP",
    "description": "Local HTTP bridge for Codex/VS Code control of Blender",
    "category": "Development",
}

import bpy
import json
import math
import os
import mathutils
import queue
import threading
import traceback
from datetime import datetime
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ============================================================
# Config
# ============================================================

class MTECBRIDGE_Config:
    REVISION = "v260414d"
    HOST = "127.0.0.1"
    PORT = 8765
    QUEUE_TIMEOUT = 60.0
    POLL_INTERVAL = 0.01


# ============================================================
# Thread-safe executor for bpy access on main thread
# ============================================================

class MainThreadExecutor:
    def __init__(self):
        self.execution_queue = queue.Queue()
        self.results = {}
        self.running = False

    def start(self):
        if not self.running:
            bpy.app.timers.register(self._process, first_interval=MTECBRIDGE_Config.POLL_INTERVAL)
            self.running = True

    def stop(self):
        self.running = False
        if bpy.app.timers.is_registered(self._process):
            bpy.app.timers.unregister(self._process)

    def _process(self):
        while not self.execution_queue.empty():
            req = self.execution_queue.get()
            req_id = req["id"]
            func = req["func"]
            args = req["args"]
            kwargs = req["kwargs"]
            try:
                result = func(*args, **kwargs)
                self.results[req_id] = {"ok": True, "result": result}
            except Exception as exc:
                self.results[req_id] = {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
        return MTECBRIDGE_Config.POLL_INTERVAL if self.running else None

    def execute(self, req_id, func, *args, **kwargs):
        self.execution_queue.put({
            "id": req_id,
            "func": func,
            "args": args,
            "kwargs": kwargs,
        })


executor = MainThreadExecutor()
viewport_animation_state = {"token": 0, "sweep_index": 0}

# ============================================================
# Helpers
# ============================================================

def now_iso():
    return datetime.now().isoformat()

def require_object(object_name: str):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        raise ValueError(f"Object '{object_name}' not found")
    return obj

def require_collection(collection_name: str):
    collection = bpy.data.collections.get(collection_name)
    if not collection:
        raise ValueError(f"Collection '{collection_name}' not found")
    return collection

def ensure_rigid_body_world():
    scene = bpy.context.scene
    if scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    world = scene.rigidbody_world
    if world is None:
        raise RuntimeError("Failed to create rigid body world")
    return world

def activate_object(obj, mode: str | None = None):
    active = bpy.context.view_layer.objects.active
    if active and getattr(active, "mode", "OBJECT") != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass
    for scene_obj in bpy.context.view_layer.objects:
        scene_obj.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if mode:
        bpy.ops.object.mode_set(mode=mode)
    maybe_focus_view_on_selection()
    return obj

def bridge_settings():
    return bpy.context.scene

def iter_view3d_overrides():
    window_manager = bpy.context.window_manager
    if not window_manager:
        return
    for window in window_manager.windows:
        screen = window.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            space = next((space for space in area.spaces if space.type == 'VIEW_3D'), None)
            if region is None or space is None:
                continue
            yield {
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
                "space_data": space,
            }

def capture_view_state(region_3d):
    return {
        "rotation": region_3d.view_rotation.copy(),
        "location": region_3d.view_location.copy(),
        "distance": float(region_3d.view_distance),
    }

def apply_view_state(region_3d, state):
    region_3d.view_rotation = state["rotation"]
    region_3d.view_location = state["location"]
    region_3d.view_distance = state["distance"]

def interpolate_view_state(start_state, end_state, factor: float):
    return {
        "rotation": start_state["rotation"].slerp(end_state["rotation"], factor),
        "location": start_state["location"].lerp(end_state["location"], factor),
        "distance": (1.0 - factor) * start_state["distance"] + factor * end_state["distance"],
    }

def effective_view_settings(scene):
    mode = getattr(scene, "mtecbridge_view_mode", "MANUAL")
    if mode == "CINEMATIC":
        sweep_index = viewport_animation_state["sweep_index"]
        sweep_step = getattr(scene, "mtecbridge_cinematic_sweep_step_deg", 32.0)
        yaw_offset = sweep_step * (sweep_index % 12)
        pitch_base = getattr(scene, "mtecbridge_cinematic_pitch_deg", 12.0)
        pitch_variation = getattr(scene, "mtecbridge_cinematic_pitch_variation_deg", 4.0)
        pitch_offset = pitch_base + pitch_variation * math.sin(math.radians(yaw_offset))
        dolly_wave = 1.0 + getattr(scene, "mtecbridge_cinematic_dolly_variation", 0.08) * math.cos(math.radians(yaw_offset))
        return {
            "mode": mode,
            "auto_focus": True,
            "auto_orbit": True,
            "smooth_view": True,
            "view_duration": getattr(scene, "mtecbridge_cinematic_duration", 1.0),
            "orbit_yaw_deg": yaw_offset,
            "orbit_pitch_deg": pitch_offset,
            "orbit_roll_deg": 0.0,
            "distance_scale": getattr(scene, "mtecbridge_cinematic_distance_scale", 1.35) * dolly_wave,
            "retain_distance_factor": getattr(scene, "mtecbridge_cinematic_retain_distance", 0.82),
        }
    return {
        "mode": mode,
        "auto_focus": getattr(scene, "mtecbridge_auto_focus", False),
        "auto_orbit": getattr(scene, "mtecbridge_auto_orbit", False),
        "smooth_view": getattr(scene, "mtecbridge_smooth_view", True),
        "view_duration": getattr(scene, "mtecbridge_view_duration", 0.45),
        "orbit_yaw_deg": getattr(scene, "mtecbridge_orbit_yaw_deg", 12.0),
        "orbit_pitch_deg": getattr(scene, "mtecbridge_orbit_pitch_deg", -5.0),
        "orbit_roll_deg": getattr(scene, "mtecbridge_orbit_roll_deg", 0.0),
        "distance_scale": 1.0,
        "retain_distance_factor": 0.0,
    }

def schedule_view_animation(start_state, end_state, duration: float):
    viewport_animation_state["token"] += 1
    token = viewport_animation_state["token"]
    duration = max(0.01, duration)
    frames = max(2, int(duration * 30.0))
    interval = duration / frames
    step = {"index": 0}

    def animate():
        if viewport_animation_state["token"] != token:
            return None
        overrides = list(iter_view3d_overrides() or [])
        if not overrides:
            return None

        override = overrides[0]
        region_3d = override["space_data"].region_3d
        factor = min(1.0, step["index"] / frames)
        apply_view_state(region_3d, interpolate_view_state(start_state, end_state, factor))
        override["area"].tag_redraw()

        if step["index"] >= frames:
            return None

        step["index"] += 1
        return interval

    bpy.app.timers.register(animate, first_interval=0.0)

def schedule_keyframed_view_animation(keyframes, duration: float, area, region_3d):
    if len(keyframes) < 2:
        return
    viewport_animation_state["token"] += 1
    token = viewport_animation_state["token"]
    duration = max(0.05, duration)
    segments = len(keyframes) - 1
    frames_per_segment = max(6, int((duration / segments) * 30.0))
    interval = duration / max(1, segments * frames_per_segment)
    state = {"segment": 0, "frame": 0}

    def ease(t):
        return 3.0 * t * t - 2.0 * t * t * t

    def animate():
        if viewport_animation_state["token"] != token:
            return None
        segment = state["segment"]
        if segment >= segments:
            return None
        factor = ease(min(1.0, state["frame"] / frames_per_segment))
        apply_view_state(
            region_3d,
            interpolate_view_state(keyframes[segment], keyframes[segment + 1], factor),
        )
        area.tag_redraw()
        state["frame"] += 1
        if state["frame"] > frames_per_segment:
            state["segment"] += 1
            state["frame"] = 0
        return interval if state["segment"] < segments else None

    bpy.app.timers.register(animate, first_interval=0.0)

def build_cinematic_keyframes(center, base_distance: float, settings: dict, steps: int):
    steps = max(2, steps)
    sweep_step = settings.get("orbit_yaw_deg", 32.0)
    keyframes = []
    start_index = viewport_animation_state["sweep_index"]
    for index in range(steps + 1):
        yaw_deg = sweep_step * (start_index + index)
        pitch_deg = settings.get("orbit_pitch_deg", 12.0)
        dolly_variation = settings.get("dolly_variation", 0.08)
        pitch_variation = settings.get("pitch_variation_deg", 4.0)
        yaw_rad = math.radians(yaw_deg)
        pitch_rad = math.radians(pitch_deg + pitch_variation * math.sin(yaw_rad))
        roll_rad = math.radians(settings.get("orbit_roll_deg", 0.0))
        distance = base_distance * (1.0 + dolly_variation * math.cos(yaw_rad))
        location = center.copy()
        location.z += 0.6 * math.sin(yaw_rad * 0.7)
        keyframes.append(
            {
                "rotation": mathutils.Euler((pitch_rad, roll_rad, yaw_rad), 'XYZ').to_quaternion(),
                "location": location,
                "distance": distance,
            }
        )
    viewport_animation_state["sweep_index"] += steps
    return keyframes

def maybe_focus_view_on_selection():
    scene = bridge_settings()
    settings = effective_view_settings(scene)
    auto_focus = settings["auto_focus"]
    auto_orbit = settings["auto_orbit"]
    smooth_view = settings["smooth_view"]
    if not auto_focus and not auto_orbit:
        return
    for override in iter_view3d_overrides() or []:
        region_3d = override["space_data"].region_3d
        start_state = capture_view_state(region_3d)
        try:
            with bpy.context.temp_override(**override):
                if auto_focus:
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                if auto_orbit:
                    apply_auto_orbit(region_3d, settings)
        except RuntimeError:
            continue
        end_state = capture_view_state(region_3d)
        end_state["distance"] = max(
            end_state["distance"] * settings["distance_scale"],
            start_state["distance"] * settings["retain_distance_factor"],
        )
        if smooth_view:
            apply_view_state(region_3d, start_state)
            schedule_view_animation(
                start_state,
                end_state,
                duration=settings["view_duration"],
            )
        else:
            apply_view_state(region_3d, end_state)
        if settings["mode"] == "CINEMATIC":
            viewport_animation_state["sweep_index"] += 1
        override["area"].tag_redraw()
        break

def apply_auto_orbit(region_3d, settings):
    if region_3d is None:
        return
    yaw = math.radians(settings["orbit_yaw_deg"])
    pitch = math.radians(settings["orbit_pitch_deg"])
    roll = math.radians(settings["orbit_roll_deg"])
    orbit = mathutils.Euler((pitch, roll, yaw), 'XYZ').to_quaternion()
    region_3d.view_rotation = orbit @ region_3d.view_rotation

def object_summary(obj):
    data = {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation_euler_rad": list(obj.rotation_euler),
        "rotation_euler_deg": [math.degrees(v) for v in obj.rotation_euler],
        "scale": list(obj.scale),
        "visible": obj.visible_get(),
        "selected": obj.select_get(),
    }
    if hasattr(obj.data, "vertices"):
        data["mesh_stats"] = {
            "vertices": len(obj.data.vertices),
            "edges": len(obj.data.edges),
            "faces": len(obj.data.polygons),
        }
    return data

def object_bounds(obj):
    if not hasattr(obj, "bound_box"):
        return None
    corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    mins = [min(v[i] for v in corners) for i in range(3)]
    maxs = [max(v[i] for v in corners) for i in range(3)]
    return {
        "min": mins,
        "max": maxs,
        "dimensions": [maxs[i] - mins[i] for i in range(3)],
    }

def serialize(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): serialize(v) for k, v in value.items()}
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        return [serialize(v) for v in value]
    return repr(value)

# ============================================================
# Core tool implementations
# ============================================================

def tool_get_scene_info():
    scene = bpy.context.scene
    settings = effective_view_settings(scene)
    return {
        "scene_name": scene.name,
        "file_path": bpy.data.filepath or "",
        "objects_total": len(bpy.data.objects),
        "materials_total": len(bpy.data.materials),
        "images_total": len(bpy.data.images),
        "collections_total": len(bpy.data.collections),
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "active_camera": scene.camera.name if scene.camera else None,
        "view_mode": getattr(scene, "mtecbridge_view_mode", "MANUAL"),
        "auto_focus": settings["auto_focus"],
        "auto_orbit": settings["auto_orbit"],
        "smooth_view": settings["smooth_view"],
        "view_duration": settings["view_duration"],
        "timestamp": now_iso(),
    }

def tool_set_bridge_options(
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
):
    scene = bridge_settings()
    if view_mode is not None:
        scene.mtecbridge_view_mode = view_mode
    if auto_focus is not None:
        scene.mtecbridge_auto_focus = auto_focus
    if auto_orbit is not None:
        scene.mtecbridge_auto_orbit = auto_orbit
    if smooth_view is not None:
        scene.mtecbridge_smooth_view = smooth_view
    if view_duration is not None:
        scene.mtecbridge_view_duration = view_duration
    if cinematic_duration is not None:
        scene.mtecbridge_cinematic_duration = cinematic_duration
    if cinematic_yaw_deg is not None:
        scene.mtecbridge_cinematic_yaw_deg = cinematic_yaw_deg
    if cinematic_pitch_deg is not None:
        scene.mtecbridge_cinematic_pitch_deg = cinematic_pitch_deg
    if cinematic_sweep_step_deg is not None:
        scene.mtecbridge_cinematic_sweep_step_deg = cinematic_sweep_step_deg
    if cinematic_pitch_variation_deg is not None:
        scene.mtecbridge_cinematic_pitch_variation_deg = cinematic_pitch_variation_deg
    if cinematic_distance_scale is not None:
        scene.mtecbridge_cinematic_distance_scale = cinematic_distance_scale
    if cinematic_retain_distance is not None:
        scene.mtecbridge_cinematic_retain_distance = cinematic_retain_distance
    if cinematic_dolly_variation is not None:
        scene.mtecbridge_cinematic_dolly_variation = cinematic_dolly_variation
    if orbit_yaw_deg is not None:
        scene.mtecbridge_orbit_yaw_deg = orbit_yaw_deg
    if orbit_pitch_deg is not None:
        scene.mtecbridge_orbit_pitch_deg = orbit_pitch_deg
    if orbit_roll_deg is not None:
        scene.mtecbridge_orbit_roll_deg = orbit_roll_deg
    settings = effective_view_settings(scene)
    return {
        "view_mode": scene.mtecbridge_view_mode,
        "auto_focus": settings["auto_focus"],
        "auto_orbit": settings["auto_orbit"],
        "smooth_view": settings["smooth_view"],
        "view_duration": settings["view_duration"],
        "orbit_yaw_deg": scene.mtecbridge_orbit_yaw_deg,
        "orbit_pitch_deg": scene.mtecbridge_orbit_pitch_deg,
        "orbit_roll_deg": scene.mtecbridge_orbit_roll_deg,
        "cinematic_duration": scene.mtecbridge_cinematic_duration,
        "cinematic_yaw_deg": scene.mtecbridge_cinematic_yaw_deg,
        "cinematic_pitch_deg": scene.mtecbridge_cinematic_pitch_deg,
        "cinematic_sweep_step_deg": scene.mtecbridge_cinematic_sweep_step_deg,
        "cinematic_pitch_variation_deg": scene.mtecbridge_cinematic_pitch_variation_deg,
        "cinematic_distance_scale": scene.mtecbridge_cinematic_distance_scale,
        "cinematic_retain_distance": scene.mtecbridge_cinematic_retain_distance,
        "cinematic_dolly_variation": scene.mtecbridge_cinematic_dolly_variation,
    }

def tool_cinematic_reveal_selection(
    object_names=None,
    duration: float | None = None,
    steps: int = 5,
):
    object_names = object_names or []
    scene = bridge_settings()
    settings = effective_view_settings(scene)
    override = next(iter_view3d_overrides() or [], None)
    if override is None:
        raise RuntimeError("No VIEW_3D area available for cinematic reveal")

    selected_objects = [require_object(name) for name in object_names] if object_names else [
        obj for obj in bpy.context.view_layer.objects if obj.select_get()
    ]
    if not selected_objects:
        raise RuntimeError("No selected objects available for cinematic reveal")

    for scene_obj in bpy.context.view_layer.objects:
        scene_obj.select_set(False)
    for obj in selected_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = selected_objects[-1]

    space = override["space_data"]
    region_3d = space.region_3d
    space.shading.type = 'RENDERED'
    space.shading.use_scene_lights = True
    space.shading.use_scene_world = True
    region_3d.view_perspective = 'PERSP'

    start_state = capture_view_state(region_3d)
    with bpy.context.temp_override(**override):
        bpy.ops.view3d.view_selected(use_all_regions=False)
    framed_state = capture_view_state(region_3d)

    bounds = [object_bounds(obj) for obj in selected_objects if object_bounds(obj)]
    if bounds:
        mins = [min(bound["min"][i] for bound in bounds) for i in range(3)]
        maxs = [max(bound["max"][i] for bound in bounds) for i in range(3)]
        center = mathutils.Vector([(mins[i] + maxs[i]) * 0.5 for i in range(3)])
    else:
        center = framed_state["location"].copy()

    base_distance = max(
        framed_state["distance"] * settings["distance_scale"],
        start_state["distance"] * settings["retain_distance_factor"],
        6.0,
    )
    settings = {
        **settings,
        "dolly_variation": getattr(scene, "mtecbridge_cinematic_dolly_variation", 0.08),
        "pitch_variation_deg": getattr(scene, "mtecbridge_cinematic_pitch_variation_deg", 4.0),
    }
    keyframes = [start_state]
    keyframes.extend(build_cinematic_keyframes(center, base_distance, settings, steps))
    apply_view_state(region_3d, start_state)
    schedule_keyframed_view_animation(
        keyframes,
        duration=duration if duration is not None else max(settings["view_duration"], 1.8),
        area=override["area"],
        region_3d=region_3d,
    )
    override["area"].tag_redraw()

    return {
        "objects": [obj.name for obj in selected_objects],
        "steps": steps,
        "duration": duration if duration is not None else max(settings["view_duration"], 1.8),
        "center": list(center),
        "base_distance": base_distance,
    }

def tool_list_objects(object_type: str = ""):
    names = []
    for obj in bpy.data.objects:
        if object_type and obj.type != object_type:
            continue
        names.append(object_summary(obj))
    return {"count": len(names), "objects": names}

def tool_get_object_info(object_name: str, include_modifiers: bool = True, include_materials: bool = True):
    obj = require_object(object_name)
    data = object_summary(obj)
    data["mode"] = obj.mode if hasattr(obj, "mode") else None
    data["parent"] = obj.parent.name if obj.parent else None
    data["collections"] = [collection.name for collection in obj.users_collection]
    data["bounds_world"] = object_bounds(obj)
    data["data_name"] = obj.data.name if getattr(obj, "data", None) else None

    if include_materials and hasattr(obj.data, "materials"):
        data["materials"] = [material.name if material else None for material in obj.data.materials]

    if include_modifiers:
        data["modifiers"] = []
        for modifier in obj.modifiers:
            data["modifiers"].append(
                {
                    "name": modifier.name,
                    "type": modifier.type,
                    "show_viewport": modifier.show_viewport,
                    "show_render": modifier.show_render,
                }
            )

    return data

def tool_create_mesh_object(
    primitive_type: str = "cube",
    name: str = "",
    size: float = 2.0,
    location = None,
    rotation_deg = None,
    scale = None,
):
    location = location or [0.0, 0.0, 0.0]
    rotation_deg = rotation_deg or [0.0, 0.0, 0.0]
    scale = scale or [1.0, 1.0, 1.0]

    primitive_type = primitive_type.lower()

    if primitive_type == "cube":
        bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    elif primitive_type in ("sphere", "uv_sphere"):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2.0, location=location)
    elif primitive_type == "ico_sphere":
        bpy.ops.mesh.primitive_ico_sphere_add(radius=size / 2.0, location=location)
    elif primitive_type == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=size / 2.0, depth=size, location=location)
    elif primitive_type == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=size / 2.0, depth=size, location=location)
    elif primitive_type == "plane":
        bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    elif primitive_type == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=size / 2.0, minor_radius=size / 4.0, location=location)
    elif primitive_type == "monkey":
        bpy.ops.mesh.primitive_monkey_add(size=size, location=location)
    else:
        raise ValueError(f"Unsupported primitive_type '{primitive_type}'")

    obj = bpy.context.active_object
    if name:
        obj.name = name
        if obj.data:
            obj.data.name = f"{name}_mesh"
    obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    obj.scale = scale
    maybe_focus_view_on_selection()
    return object_summary(obj)

def tool_create_curve_object(
    curve_type: str = "bezier",
    name: str = "Curve",
    points = None,
    bevel_depth: float = 0.0,
    cyclic: bool = False,
):
    points = points or [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
    curve_data = bpy.data.curves.new(name=name, type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.bevel_depth = bevel_depth

    curve_type = curve_type.lower()
    if curve_type == "bezier":
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(len(points) - 1)
        for i, point in enumerate(points):
            bp = spline.bezier_points[i]
            bp.co = point
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'
    elif curve_type == "poly":
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(points) - 1)
        for i, point in enumerate(points):
            spline.points[i].co = [point[0], point[1], point[2], 1.0]
    else:
        raise ValueError(f"Unsupported curve_type '{curve_type}'")
    spline.use_cyclic_u = cyclic

    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    maybe_focus_view_on_selection()
    return object_summary(obj)

def tool_create_text_object(
    text: str = "Hello Blender",
    name: str = "Text",
    location = None,
    rotation_deg = None,
    size: float = 1.0,
    extrude: float = 0.0,
):
    location = location or [0.0, 0.0, 0.0]
    rotation_deg = rotation_deg or [0.0, 0.0, 0.0]

    font_curve = bpy.data.curves.new(type="FONT", name=name)
    font_curve.body = text
    font_curve.size = size
    font_curve.extrude = extrude

    obj = bpy.data.objects.new(name, font_curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    maybe_focus_view_on_selection()
    return object_summary(obj)

def tool_transform_object(object_name: str, location=None, rotation_deg=None, scale=None, delta: bool = False):
    obj = require_object(object_name)
    activate_object(obj)
    if location is not None:
        if delta:
            obj.location = [obj.location[i] + location[i] for i in range(3)]
        else:
            obj.location = location
    if rotation_deg is not None:
        rot_rad = [math.radians(v) for v in rotation_deg]
        if delta:
            obj.rotation_euler = [obj.rotation_euler[i] + rot_rad[i] for i in range(3)]
        else:
            obj.rotation_euler = rot_rad
    if scale is not None:
        if delta:
            obj.scale = [obj.scale[i] * scale[i] for i in range(3)]
        else:
            obj.scale = scale
    maybe_focus_view_on_selection()
    return object_summary(obj)

def tool_duplicate_object(object_name: str, linked: bool = False, count: int = 1, offset=None):
    offset = offset or [0.0, 0.0, 0.0]
    obj = require_object(object_name)
    created = []
    for i in range(count):
        dup = obj.copy()
        if obj.data and not linked:
            dup.data = obj.data.copy()
        dup.name = f"{obj.name}_copy_{i+1}"
        dup.location = [obj.location[j] + offset[j] * (i + 1) for j in range(3)]
        bpy.context.collection.objects.link(dup)
        created.append(object_summary(dup))
    return {"count": len(created), "objects": created}

def tool_select_objects(object_names, active_object: str = "", replace: bool = True):
    if replace:
        active = bpy.context.view_layer.objects.active
        if active and getattr(active, "mode", "OBJECT") != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except RuntimeError:
                pass
        for scene_obj in bpy.context.view_layer.objects:
            scene_obj.select_set(False)
    selected = []
    for name in object_names:
        obj = require_object(name)
        obj.select_set(True)
        selected.append(obj.name)
    if active_object:
        bpy.context.view_layer.objects.active = require_object(active_object)
    elif selected:
        bpy.context.view_layer.objects.active = require_object(selected[-1])
    active = bpy.context.view_layer.objects.active
    maybe_focus_view_on_selection()
    return {"selected": selected, "active": active.name if active else None}

def tool_set_mode(mode: str = "OBJECT", object_name: str = ""):
    mode = mode.upper()
    obj = require_object(object_name) if object_name else bpy.context.view_layer.objects.active
    if not obj:
        raise ValueError("No active object available")
    activate_object(obj)
    bpy.ops.object.mode_set(mode=mode)
    maybe_focus_view_on_selection()
    return {"object": obj.name, "mode": obj.mode}

def tool_apply_transforms(object_name: str, location: bool = False, rotation: bool = True, scale: bool = True):
    obj = require_object(object_name)
    activate_object(obj, mode="OBJECT")
    bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale)
    return object_summary(obj)

def tool_delete_objects(object_names):
    deleted = []
    for name in object_names:
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted.append(name)
    return {"deleted": deleted, "count": len(deleted)}

def tool_create_collection(name: str, parent: str = ""):
    existing = bpy.data.collections.get(name)
    if existing:
        collection = existing
    else:
        collection = bpy.data.collections.new(name)
        if parent:
            require_collection(parent).children.link(collection)
        else:
            bpy.context.scene.collection.children.link(collection)
    return {
        "name": collection.name,
        "parent": parent or bpy.context.scene.collection.name,
        "objects": len(collection.objects),
        "children": len(collection.children),
    }

def tool_move_to_collection(object_name: str, collection_name: str, unlink_others: bool = False):
    obj = require_object(object_name)
    collection = require_collection(collection_name)
    if obj not in collection.objects[:]:
        collection.objects.link(obj)

    if unlink_others:
        for existing in list(obj.users_collection):
            if existing != collection:
                existing.objects.unlink(obj)

    return {
        "object": obj.name,
        "collections": [c.name for c in obj.users_collection],
    }

def tool_create_material(
    name: str,
    base_color=None,
    metallic: float = 0.0,
    roughness: float = 0.5,
):
    base_color = base_color or [0.8, 0.8, 0.8, 1.0]
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (300, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Base Color'].default_value = base_color
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return {
        "name": mat.name,
        "base_color": base_color,
        "metallic": metallic,
        "roughness": roughness,
    }

def tool_assign_material(object_name: str, material_name: str):
    obj = require_object(object_name)
    mat = bpy.data.materials.get(material_name)
    if not mat:
        raise ValueError(f"Material '{material_name}' not found")
    if not hasattr(obj.data, "materials"):
        raise ValueError(f"Object '{object_name}' cannot receive materials")
    if len(obj.data.materials) == 0:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat
    return {"object": object_name, "material": material_name}

def tool_set_origin(object_name: str, origin_type: str = "ORIGIN_GEOMETRY", center: str = "MEDIAN"):
    obj = require_object(object_name)
    activate_object(obj, mode="OBJECT")
    bpy.ops.object.origin_set(type=origin_type, center=center)
    return object_summary(obj)

def tool_convert_object(object_name: str, target: str = "MESH"):
    obj = require_object(object_name)
    activate_object(obj, mode="OBJECT")
    bpy.ops.object.convert(target=target)
    converted = bpy.context.view_layer.objects.active
    return object_summary(converted)

def tool_create_light(
    light_type: str = "POINT",
    name: str = "Light",
    location = None,
    rotation_deg = None,
    energy: float = 1000.0,
):
    location = location or [0.0, 0.0, 5.0]
    rotation_deg = rotation_deg or [0.0, 0.0, 0.0]
    data = bpy.data.lights.new(name=name, type=light_type)
    data.energy = energy
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    maybe_focus_view_on_selection()
    return object_summary(obj)

def tool_create_camera(
    name: str = "Camera",
    location = None,
    rotation_deg = None,
    focal_length: float = 50.0,
    set_active: bool = True,
):
    location = location or [7.0, -7.0, 5.0]
    rotation_deg = rotation_deg or [60.0, 0.0, 45.0]
    data = bpy.data.cameras.new(name=name)
    data.lens = focal_length
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    if set_active:
        bpy.context.scene.camera = obj
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    maybe_focus_view_on_selection()
    return object_summary(obj)

def tool_add_modifier(object_name: str, modifier_type: str, name: str = "", settings=None):
    obj = require_object(object_name)
    settings = settings or {}
    mod = obj.modifiers.new(name=name or modifier_type, type=modifier_type)
    for key, value in settings.items():
        if hasattr(mod, key):
            setattr(mod, key, value)
    return {"object": object_name, "modifier": mod.name, "type": modifier_type, "settings": settings}

def tool_apply_modifier(object_name: str, modifier_name: str):
    obj = require_object(object_name)
    if modifier_name not in obj.modifiers:
        raise ValueError(f"Modifier '{modifier_name}' not found on '{object_name}'")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier_name)
    return {"object": object_name, "modifier_applied": modifier_name}

def tool_boolean_operation(object_a: str, object_b: str, operation: str = "DIFFERENCE", solver: str = "FAST", apply: bool = True):
    obj_a = require_object(object_a)
    obj_b = require_object(object_b)
    mod = obj_a.modifiers.new(name=f"Boolean_{operation}", type='BOOLEAN')
    mod.object = obj_b
    mod.operation = operation
    mod.solver = solver
    if apply:
        bpy.context.view_layer.objects.active = obj_a
        obj_a.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return {"object_a": object_a, "object_b": object_b, "operation": operation, "applied": apply}

def tool_configure_render_settings(engine: str = "CYCLES", samples: int = 128, resolution_x: int = 1920, resolution_y: int = 1080):
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    if engine == "CYCLES":
        scene.cycles.samples = samples
    elif engine == "BLENDER_EEVEE":
        scene.eevee.taa_render_samples = samples
    return {
        "engine": scene.render.engine,
        "resolution_x": resolution_x,
        "resolution_y": resolution_y,
        "samples": samples,
    }

def tool_render_image(output_path: str, use_viewport: bool = False):
    if not output_path:
        raise ValueError("output_path is required")
    scene = bpy.context.scene
    scene.render.filepath = output_path
    if use_viewport:
        bpy.ops.render.opengl(write_still=True, view_context=True)
    else:
        bpy.ops.render.render(write_still=True)
    return {"output_path": output_path, "engine": scene.render.engine}

def tool_import_file(file_path: str):
    file_path = str(file_path)
    lower = file_path.lower()
    if lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=file_path)
    elif lower.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=file_path)
    elif lower.endswith(".glb") or lower.endswith(".gltf"):
        bpy.ops.import_scene.gltf(filepath=file_path)
    elif lower.endswith(".stl"):
        bpy.ops.wm.stl_import(filepath=file_path)
    else:
        raise ValueError("Unsupported file format")
    return {"file_path": file_path, "status": "imported"}

def tool_export_file(file_path: str, selected_only: bool = False):
    file_path = str(file_path)
    lower = file_path.lower()
    if lower.endswith(".fbx"):
        bpy.ops.export_scene.fbx(filepath=file_path, use_selection=selected_only)
    elif lower.endswith(".obj"):
        bpy.ops.wm.obj_export(filepath=file_path, export_selected_objects=selected_only)
    elif lower.endswith(".glb"):
        bpy.ops.export_scene.gltf(filepath=file_path, export_format='GLB', use_selection=selected_only)
    elif lower.endswith(".gltf"):
        bpy.ops.export_scene.gltf(filepath=file_path, export_format='GLTF_SEPARATE', use_selection=selected_only)
    elif lower.endswith(".stl"):
        bpy.ops.wm.stl_export(filepath=file_path, export_selected_objects=selected_only)
    else:
        raise ValueError("Unsupported file format")
    return {"file_path": file_path, "status": "exported"}

def tool_save_blend_file(file_path: str):
    bpy.ops.wm.save_as_mainfile(filepath=file_path)
    return {"file_path": file_path, "status": "saved"}

def tool_clear_scene(keep_cameras: bool = True, keep_lights: bool = True):
    removed = []
    for obj in list(bpy.data.objects):
        if keep_cameras and obj.type == "CAMERA":
            continue
        if keep_lights and obj.type == "LIGHT":
            continue
        removed.append(obj.name)
        bpy.data.objects.remove(obj, do_unlink=True)
    return {"removed": removed, "count": len(removed)}

def tool_set_timeline_frame(frame: int):
    scene = bpy.context.scene
    scene.frame_set(int(frame))
    return {
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
    }

def tool_set_viewport_shading(
    shading_type: str = "RENDERED",
    use_scene_lights: bool = True,
    use_scene_world: bool = True,
):
    updated = 0
    for override in iter_view3d_overrides() or []:
        space = override["space_data"]
        space.shading.type = shading_type
        if hasattr(space.shading, "use_scene_lights"):
            space.shading.use_scene_lights = use_scene_lights
        if hasattr(space.shading, "use_scene_world"):
            space.shading.use_scene_world = use_scene_world
        override["area"].tag_redraw()
        updated += 1
    return {
        "shading_type": shading_type,
        "use_scene_lights": use_scene_lights,
        "use_scene_world": use_scene_world,
        "viewports_updated": updated,
    }

def tool_set_rigid_body_world(
    frame_start: int | None = None,
    frame_end: int | None = None,
    substeps_per_frame: int | None = None,
    solver_iterations: int | None = None,
    gravity: list[float] | None = None,
    enabled: bool | None = None,
):
    scene = bpy.context.scene
    world = ensure_rigid_body_world()
    if frame_start is not None:
        scene.frame_start = int(frame_start)
    if frame_end is not None:
        scene.frame_end = int(frame_end)
    if substeps_per_frame is not None and hasattr(world, "substeps_per_frame"):
        world.substeps_per_frame = int(substeps_per_frame)
    if solver_iterations is not None and hasattr(world, "solver_iterations"):
        world.solver_iterations = int(solver_iterations)
    if enabled is not None and hasattr(world, "enabled"):
        world.enabled = bool(enabled)
    if gravity is not None:
        if len(gravity) != 3:
            raise ValueError("gravity must have exactly 3 values")
        scene.gravity = gravity
    point_cache = getattr(world, "point_cache", None)
    return {
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "substeps_per_frame": getattr(world, "substeps_per_frame", None),
        "solver_iterations": getattr(world, "solver_iterations", None),
        "enabled": getattr(world, "enabled", True),
        "gravity": list(scene.gravity),
        "cache_frame_start": point_cache.frame_start if point_cache else None,
        "cache_frame_end": point_cache.frame_end if point_cache else None,
    }

def tool_add_rigid_body(
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
):
    ensure_rigid_body_world()
    obj = require_object(object_name)
    activate_object(obj)
    if obj.rigid_body is None:
        bpy.ops.rigidbody.object_add()
    rb = obj.rigid_body
    rb.type = body_type
    rb.collision_shape = collision_shape
    rb.mass = mass
    rb.friction = friction
    rb.restitution = restitution
    rb.use_margin = use_margin
    if hasattr(rb, "collision_margin"):
        rb.collision_margin = collision_margin
    if hasattr(rb, "linear_damping"):
        rb.linear_damping = linear_damping
    if hasattr(rb, "angular_damping"):
        rb.angular_damping = angular_damping
    rb.enabled = enabled
    return {
        "object": obj.name,
        "type": rb.type,
        "collision_shape": rb.collision_shape,
        "mass": rb.mass,
        "friction": rb.friction,
        "restitution": rb.restitution,
        "collision_margin": getattr(rb, "collision_margin", None),
        "linear_damping": getattr(rb, "linear_damping", None),
        "angular_damping": getattr(rb, "angular_damping", None),
        "enabled": rb.enabled,
    }

def tool_configure_rigid_body(
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
):
    obj = require_object(object_name)
    if obj.rigid_body is None:
        raise ValueError(f"Object '{object_name}' has no rigid body")
    rb = obj.rigid_body
    if body_type is not None:
        rb.type = body_type
    if collision_shape is not None:
        rb.collision_shape = collision_shape
    if mass is not None:
        rb.mass = mass
    if friction is not None:
        rb.friction = friction
    if restitution is not None:
        rb.restitution = restitution
    if use_margin is not None:
        rb.use_margin = use_margin
    if collision_margin is not None and hasattr(rb, "collision_margin"):
        rb.collision_margin = collision_margin
    if linear_damping is not None and hasattr(rb, "linear_damping"):
        rb.linear_damping = linear_damping
    if angular_damping is not None and hasattr(rb, "angular_damping"):
        rb.angular_damping = angular_damping
    if enabled is not None:
        rb.enabled = enabled
    return {
        "object": obj.name,
        "type": rb.type,
        "collision_shape": rb.collision_shape,
        "mass": rb.mass,
        "friction": rb.friction,
        "restitution": rb.restitution,
        "collision_margin": getattr(rb, "collision_margin", None),
        "linear_damping": getattr(rb, "linear_damping", None),
        "angular_damping": getattr(rb, "angular_damping", None),
        "enabled": rb.enabled,
    }

def tool_free_bake():
    ensure_rigid_body_world()
    bpy.ops.ptcache.free_bake_all()
    return {"status": "freed"}

def tool_reset_physics_simulation(frame: int | None = None):
    ensure_rigid_body_world()
    scene = bpy.context.scene
    bpy.ops.ptcache.free_bake_all()
    scene.frame_set(int(frame) if frame is not None else scene.frame_start)
    return {
        "status": "reset",
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
    }

def tool_bake_to_frame(frame_end: int, frame_start: int | None = None):
    scene = bpy.context.scene
    world = ensure_rigid_body_world()
    point_cache = getattr(world, "point_cache", None)
    if frame_start is not None:
        scene.frame_start = int(frame_start)
    scene.frame_end = int(frame_end)
    if point_cache:
        point_cache.frame_start = scene.frame_start
        point_cache.frame_end = scene.frame_end
    bpy.ops.ptcache.free_bake_all()
    bpy.ops.ptcache.bake_all(bake=True)
    return {
        "status": "baked",
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "cache_frame_start": point_cache.frame_start if point_cache else None,
        "cache_frame_end": point_cache.frame_end if point_cache else None,
    }

def tool_add_impactor(
    name: str = "Impactor",
    location = None,
    radius: float = 1.0,
    mass: float = 25.0,
    collision_shape: str = "SPHERE",
    friction: float = 0.4,
    restitution: float = 0.05,
    subdivisions: int = 3,
):
    location = location or [0.0, 0.0, 5.0]
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=max(1, int(subdivisions)),
        radius=radius,
        location=location,
    )
    obj = bpy.context.active_object
    obj.name = name
    result = tool_add_rigid_body(
        object_name=obj.name,
        body_type="ACTIVE",
        collision_shape=collision_shape,
        mass=mass,
        friction=friction,
        restitution=restitution,
    )
    return {
        "object": obj.name,
        "location": list(obj.location),
        "radius": radius,
        "rigid_body": result,
    }

def tool_build_and_smash_demo(
    base_size: int = 5,
    cube_size: float = 1.0,
    impactor_mass: float = 60.0,
    impactor_height: float = 12.0,
):
    if base_size < 1:
        raise ValueError("base_size must be at least 1")

    tool_clear_scene(keep_cameras=False, keep_lights=False)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 180
    scene.frame_set(1)

    tool_set_viewport_shading("RENDERED", use_scene_lights=True, use_scene_world=True)
    tool_set_bridge_options(
        view_mode="CINEMATIC",
        cinematic_duration=1.1,
        cinematic_pitch_deg=14.0,
        cinematic_sweep_step_deg=34.0,
        cinematic_distance_scale=1.45,
        cinematic_retain_distance=0.85,
        cinematic_dolly_variation=0.12,
        cinematic_pitch_variation_deg=5.0,
    )

    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs[0].default_value = (0.03, 0.025, 0.02, 1.0)
        background.inputs[1].default_value = 0.65

    plane_mesh = bpy.data.meshes.new("DemoGroundMesh")
    plane_obj = bpy.data.objects.new("DemoGround", plane_mesh)
    bpy.context.scene.collection.objects.link(plane_obj)
    half_extent = max(12.0, base_size * cube_size * 1.8)
    plane_mesh.from_pydata(
        [
            (-half_extent, -half_extent, 0.0),
            (half_extent, -half_extent, 0.0),
            (half_extent, half_extent, 0.0),
            (-half_extent, half_extent, 0.0),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    plane_mesh.update()

    ground_material = bpy.data.materials.new("DemoGroundMat")
    ground_material.use_nodes = True
    principled = ground_material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = (0.78, 0.68, 0.48, 1.0)
        principled.inputs["Roughness"].default_value = 0.95
    plane_obj.data.materials.append(ground_material)

    bpy.ops.object.light_add(type='SUN', location=(8.0, -10.0, 14.0))
    sun = bpy.context.active_object
    sun.name = "DemoSun"
    sun.rotation_euler = (math.radians(40.0), 0.0, math.radians(35.0))
    sun.data.energy = 3.2

    bpy.ops.object.light_add(type='AREA', location=(-6.0, 4.0, 8.0))
    fill = bpy.context.active_object
    fill.name = "DemoFill"
    fill.rotation_euler = (math.radians(62.0), 0.0, math.radians(-58.0))
    fill.data.energy = 2500.0
    fill.data.size = 10.0

    bpy.ops.object.camera_add(location=(10.0, -13.0, 8.5), rotation=(math.radians(66.0), 0.0, math.radians(36.0)))
    camera = bpy.context.active_object
    camera.name = "DemoCamera"
    camera.data.lens = 42.0
    scene.camera = camera

    layer_materials = []
    for layer in range(base_size):
        factor = layer / max(1, base_size - 1)
        color = (
            0.16 + 0.72 * factor,
            0.60 + 0.18 * (1.0 - abs(factor - 0.5) * 2.0),
            0.12,
            1.0,
        )
        material = bpy.data.materials.new(f"DemoLayer_{layer:02d}")
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled:
            principled.inputs["Base Color"].default_value = color
            principled.inputs["Roughness"].default_value = 0.55
        layer_materials.append(material)

    cube_names = []
    spacing = cube_size * 1.05
    for layer_index, width in enumerate(range(base_size, 0, -1)):
        z = cube_size * 0.5 + layer_index * cube_size
        offset = (width - 1) * spacing * 0.5
        for x_index in range(width):
            for y_index in range(width):
                x = x_index * spacing - offset
                y = y_index * spacing - offset
                bpy.ops.mesh.primitive_cube_add(size=cube_size, location=(x, y, z))
                cube = bpy.context.active_object
                cube.name = f"DemoCube_L{layer_index:02d}_{x_index:02d}_{y_index:02d}"
                cube.data.materials.append(layer_materials[layer_index])
                cube_names.append(cube.name)

    tool_set_rigid_body_world(
        frame_start=1,
        frame_end=scene.frame_end,
        substeps_per_frame=20,
        solver_iterations=30,
    )
    tool_add_rigid_body("DemoGround", body_type="PASSIVE", collision_shape="BOX", friction=0.9, restitution=0.05)
    for cube_name in cube_names:
        tool_add_rigid_body(
            cube_name,
            body_type="ACTIVE",
            collision_shape="BOX",
            mass=1.0,
            friction=0.75,
            restitution=0.02,
            linear_damping=0.05,
            angular_damping=0.12,
        )

    impactor = tool_add_impactor(
        name="DemoImpactor",
        location=[spacing * 0.7, -spacing * 0.6, impactor_height],
        radius=max(0.7, cube_size * 0.75),
        mass=impactor_mass,
        friction=0.35,
        restitution=0.08,
    )

    tool_reset_physics_simulation(frame=1)
    reveal_targets = ["DemoGround", "DemoImpactor", *cube_names]
    tool_cinematic_reveal_selection(
        object_names=reveal_targets[: min(len(reveal_targets), 32)],
        duration=2.4,
        steps=6,
    )

    return {
        "status": "ready",
        "cube_count": len(cube_names),
        "base_size": base_size,
        "cube_size": cube_size,
        "ground": "DemoGround",
        "camera": camera.name,
        "lights": [sun.name, fill.name],
        "impactor": impactor["object"],
        "frame_range": [scene.frame_start, scene.frame_end],
    }

def tool_call_operator(operator_id: str, kwargs=None):
    kwargs = kwargs or {}
    module_name, op_name = operator_id.split(".", 1)
    op_module = getattr(bpy.ops, module_name)
    op = getattr(op_module, op_name)
    result = op(**kwargs)
    return {"operator": operator_id, "kwargs": kwargs, "result": repr(result)}

def tool_run_python_snippet(code: str):
    execution_ns = {
        "__builtins__": __builtins__,
        "bpy": bpy,
        "math": math,
    }
    # Use one shared namespace so comprehensions/generator expressions
    # can resolve variables created earlier in the same snippet.
    exec(code, execution_ns, execution_ns)
    return {
        "status": "executed",
        "locals": serialize({k: v for k, v in execution_ns.items() if not k.startswith("__")})
    }

def tool_create_armature_humanoid(name: str = "HumanoidRig", scale: float = 1.0):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm = bpy.context.active_object
    arm.name = name
    eb = arm.data.edit_bones
    eb.remove(eb[0])

    def add(name, head, tail, parent=None):
        bone = eb.new(name)
        bone.head = mathutils.Vector(head) * scale
        bone.tail = mathutils.Vector(tail) * scale
        if parent:
            bone.parent = parent
        return bone

    hips = add("hips", (0, 0, 1), (0, 0, 1.15))
    spine = add("spine", (0, 0, 1.15), (0, 0, 1.35), hips)
    chest = add("chest", (0, 0, 1.35), (0, 0, 1.55), spine)
    neck = add("neck", (0, 0, 1.55), (0, 0, 1.7), chest)
    head = add("head", (0, 0, 1.7), (0, 0, 1.9), neck)

    l_sh = add("shoulder.L", (0, 0, 1.5), (0.12, 0, 1.5), chest)
    l_ua = add("upper_arm.L", (0.12, 0, 1.5), (0.42, 0, 1.48), l_sh)
    l_la = add("lower_arm.L", (0.42, 0, 1.48), (0.72, 0, 1.25), l_ua)
    l_hand = add("hand.L", (0.72, 0, 1.25), (0.82, 0, 1.15), l_la)

    r_sh = add("shoulder.R", (0, 0, 1.5), (-0.12, 0, 1.5), chest)
    r_ua = add("upper_arm.R", (-0.12, 0, 1.5), (-0.42, 0, 1.48), r_sh)
    r_la = add("lower_arm.R", (-0.42, 0, 1.48), (-0.72, 0, 1.25), r_ua)
    r_hand = add("hand.R", (-0.72, 0, 1.25), (-0.82, 0, 1.15), r_la)

    l_thigh = add("thigh.L", (0.08, 0, 1.0), (0.08, 0, 0.55), hips)
    l_shin = add("shin.L", (0.08, 0, 0.55), (0.08, 0, 0.1), l_thigh)
    l_foot = add("foot.L", (0.08, 0, 0.1), (0.18, 0.1, 0.0), l_shin)

    r_thigh = add("thigh.R", (-0.08, 0, 1.0), (-0.08, 0, 0.55), hips)
    r_shin = add("shin.R", (-0.08, 0, 0.55), (-0.08, 0, 0.1), r_thigh)
    r_foot = add("foot.R", (-0.08, 0, 0.1), (-0.18, 0.1, 0.0), r_shin)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"armature": arm.name, "bone_count": len(arm.data.bones)}

def _select_active(obj):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

def tool_auto_weight_bind(object_name: str, armature_name: str, method: str = "automatic", clean_threshold: float = 0.0):
    mesh = bpy.data.objects.get(object_name)
    arm = bpy.data.objects.get(armature_name)
    if not mesh or not arm:
        return {"ok": False, "error": "Mesh or armature not found"}
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bind_type = "ARMATURE_AUTO" if method == "automatic" else "ARMATURE_NAME"
    bpy.ops.object.parent_set(type=bind_type, keep_transform=True)
    if clean_threshold > 0:
        _select_active(mesh)
        bpy.ops.object.vertex_group_clean(group_select_mode="ALL", limit=clean_threshold)
    return {"ok": True, "bound": mesh.name, "armature": arm.name, "method": method}

def tool_mirror_weights(object_name: str, axis: str = "X", use_topology: bool = False):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"ok": False, "error": f"Object '{object_name}' not found"}
    _select_active(obj)
    bpy.ops.object.vertex_group_mirror(use_topology=use_topology, mirror_axis={"X":0,"Y":1,"Z":2}.get(axis.upper(),0), all_groups=True)
    return {"ok": True, "mirrored": True, "axis": axis}

def tool_normalize_weights(object_name: str):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"ok": False, "error": f"Object '{object_name}' not found"}
    _select_active(obj)
    bpy.ops.object.vertex_group_normalize_all(lock_active=False)
    return {"ok": True, "normalized": True}

def tool_prune_small_weights(object_name: str, threshold: float = 0.001):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"ok": False, "error": f"Object '{object_name}' not found"}
    _select_active(obj)
    bpy.ops.object.vertex_group_clean(group_select_mode="ALL", limit=threshold)
    return {"ok": True, "pruned": True, "threshold": threshold}

def tool_retarget_bone_map(armature_name: str):
    arm = bpy.data.objects.get(armature_name)
    if not arm or arm.type != "ARMATURE":
        return {"ok": False, "error": f"Armature '{armature_name}' not found"}
    bones = arm.data.bones
    human_map = {
        "hips": "hips",
        "spine": "spine",
        "chest": "chest",
        "neck": "neck",
        "head": "head",
        "shoulder.L": "shoulder_l",
        "upper_arm.L": "upper_arm_l",
        "lower_arm.L": "lower_arm_l",
        "hand.L": "hand_l",
        "shoulder.R": "shoulder_r",
        "upper_arm.R": "upper_arm_r",
        "lower_arm.R": "lower_arm_r",
        "hand.R": "hand_r",
        "thigh.L": "thigh_l",
        "shin.L": "shin_l",
        "foot.L": "foot_l",
        "thigh.R": "thigh_r",
        "shin.R": "shin_r",
        "foot.R": "foot_r",
    }
    present = {k: v for k, v in human_map.items() if k in bones}
    return {"ok": True, "bone_map": present, "missing": [k for k in human_map if k not in bones]}

def tool_quick_render_preview(output_path: str = "", resolution_x: int = 1280, resolution_y: int = 720, samples: int = 32):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.eevee.taa_render_samples = max(4, samples)
    base_path = output_path or bpy.path.abspath("//render_preview.png")
    if base_path.startswith("//"):
        base_path = bpy.path.abspath(base_path)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    scene.render.filepath = base_path
    bpy.ops.render.render(write_still=True)
    return {"engine": scene.render.engine, "filepath": base_path, "samples": samples}

def tool_quick_render_final(output_path: str = "", resolution_x: int = 1920, resolution_y: int = 1080, samples: int = 256, use_denoise: bool = True):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = use_denoise
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    base_path = output_path or bpy.path.abspath("//render_final.png")
    if base_path.startswith("//"):
        base_path = bpy.path.abspath(base_path)
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    scene.render.filepath = base_path
    bpy.ops.render.render(write_still=True)
    return {"engine": scene.render.engine, "filepath": base_path, "samples": samples, "denoise": use_denoise}

def tool_frame_selection(margin: float = 1.3):
    scene = bpy.context.scene
    cam = scene.camera
    if cam is None:
        bpy.ops.object.camera_add(location=(0, -5, 3))
        cam = bpy.context.active_object
        scene.camera = cam
    objs = [o for o in bpy.context.selected_objects if o.type != "CAMERA"]
    if not objs:
        objs = [o for o in scene.objects if o.type != "CAMERA"]
    if not objs:
        return {"ok": False, "error": "No objects to frame"}
    mins = mathutils.Vector((1e9, 1e9, 1e9))
    maxs = mathutils.Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for v in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(v)
            mins = mathutils.Vector((min(mins.x, w.x), min(mins.y, w.y), min(mins.z, w.z)))
            maxs = mathutils.Vector((max(maxs.x, w.x), max(maxs.y, w.y), max(maxs.z, w.z)))
    center = (mins + maxs) * 0.5
    size = max((maxs - mins).length, 0.001) * 0.5 * margin
    fov = cam.data.angle if cam.data.type == "PERSP" else math.radians(50)
    dist = size / math.tan(fov * 0.5)
    cam.location = center + mathutils.Vector((0, -dist * 1.1, dist * 0.6))
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return {"camera": cam.name, "center": list(center), "distance": dist, "count": len(objs)}

def tool_lighting_preset(preset: str = "three_point", strength: float = 1000.0):
    scene = bpy.context.scene
    created = []
    if preset == "three_point":
        positions = {
            "Key": (4, -4, 4),
            "Fill": (-3, -2, 3),
            "Rim": (-4, 4, 4),
        }
        factors = {"Key": 1.0, "Fill": 0.5, "Rim": 0.8}
        for name, loc in positions.items():
            bpy.ops.object.light_add(type="AREA", location=loc, radius=1.5)
            light = bpy.context.active_object
            light.name = f"LP_{name}"
            light.data.energy = strength * factors[name]
            created.append(light.name)
    return {"preset": preset, "lights": created, "strength": strength}

def tool_apply_mod_stack(object_name: str):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"ok": False, "error": f"Object '{object_name}' not found"}
    applied = []
    for mod in list(obj.modifiers):
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        applied.append(mod.name)
    return {"ok": True, "applied": applied}

def tool_duplicate_array_radial(object_name: str, count: int = 8, radius: float = 2.0):
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"ok": False, "error": f"Object '{object_name}' not found"}
    created = []
    for i in range(count):
        dup = obj.copy()
        dup.data = obj.data.copy()
        angle = (i / count) * 2 * math.pi
        dup.location = mathutils.Vector((math.cos(angle) * radius, math.sin(angle) * radius, obj.location.z))
        bpy.context.collection.objects.link(dup)
        created.append(dup.name)
    return {"ok": True, "created": created}

def tool_set_world_color_or_hdri(color=None, hdri_path: str = "", strength: float = 1.0):
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    background = nodes.get("Background") or nodes.new("ShaderNodeBackground")
    output = nodes.get("World Output") or nodes.new("ShaderNodeOutputWorld")
    links.new(background.outputs["Background"], output.inputs["Surface"])
    if hdri_path:
        env = nodes.get("Environment Texture") or nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri_path)
        env.image.colorspace_settings.name = "sRGB"
        links.new(env.outputs["Color"], background.inputs["Color"])
    elif color:
        background.inputs["Color"].default_value = (color[0], color[1], color[2], 1)
    background.inputs["Strength"].default_value = strength
    return {
        "world": world.name,
        "hdri": bool(hdri_path),
        "strength": strength,
        "color": list(color) if color else None,
    }
TOOLS = {
    "get_scene_info": {"func": tool_get_scene_info, "description": "Basic scene information", "schema": {}},
    "set_bridge_options": {"func": tool_set_bridge_options, "description": "Configure bridge UI/runtime options", "schema": {}},
    "cinematic_reveal_selection": {"func": tool_cinematic_reveal_selection, "description": "Cinematic viewport reveal for selected objects", "schema": {}},
    "list_objects": {"func": tool_list_objects, "description": "List scene objects", "schema": {"object_type": "Optional Blender type filter"}},
    "get_object_info": {"func": tool_get_object_info, "description": "Detailed object information", "schema": {"object_name": "str"}},
    "create_mesh_object": {"func": tool_create_mesh_object, "description": "Create a primitive mesh object", "schema": {}},
    "create_curve_object": {"func": tool_create_curve_object, "description": "Create a curve object", "schema": {}},
    "create_text_object": {"func": tool_create_text_object, "description": "Create a text object", "schema": {}},
    "transform_object": {"func": tool_transform_object, "description": "Move/rotate/scale an object", "schema": {}},
    "duplicate_object": {"func": tool_duplicate_object, "description": "Duplicate object(s)", "schema": {}},
    "select_objects": {"func": tool_select_objects, "description": "Select one or more objects", "schema": {"object_names": "List[str]"}},
    "set_mode": {"func": tool_set_mode, "description": "Set object interaction mode", "schema": {"mode": "OBJECT|EDIT|SCULPT|..." }},
    "apply_transforms": {"func": tool_apply_transforms, "description": "Apply object transforms", "schema": {"object_name": "str"}},
    "delete_objects": {"func": tool_delete_objects, "description": "Delete objects", "schema": {"object_names": "List[str]"}},
    "create_collection": {"func": tool_create_collection, "description": "Create a collection", "schema": {"name": "str"}},
    "move_to_collection": {"func": tool_move_to_collection, "description": "Link object into collection", "schema": {"object_name": "str", "collection_name": "str"}},
    "create_material": {"func": tool_create_material, "description": "Create a basic principled material", "schema": {}},
    "assign_material": {"func": tool_assign_material, "description": "Assign first material slot", "schema": {}},
    "set_origin": {"func": tool_set_origin, "description": "Set object origin", "schema": {"object_name": "str"}},
    "convert_object": {"func": tool_convert_object, "description": "Convert object type", "schema": {"object_name": "str", "target": "MESH|CURVE|..." }},
    "create_light": {"func": tool_create_light, "description": "Create a light", "schema": {}},
    "create_camera": {"func": tool_create_camera, "description": "Create a camera", "schema": {}},
    "add_modifier": {"func": tool_add_modifier, "description": "Add modifier to object", "schema": {}},
    "apply_modifier": {"func": tool_apply_modifier, "description": "Apply modifier", "schema": {}},
    "boolean_operation": {"func": tool_boolean_operation, "description": "Boolean between two objects", "schema": {}},
    "configure_render_settings": {"func": tool_configure_render_settings, "description": "Configure render settings", "schema": {}},
    "render_image": {"func": tool_render_image, "description": "Render still image", "schema": {}},
    "quick_render_preview": {"func": tool_quick_render_preview, "description": "Fast Eevee preview render", "schema": {"output_path": "str?", "resolution_x": "int", "resolution_y": "int", "samples": "int"}},
    "quick_render_final": {"func": tool_quick_render_final, "description": "Cycles final render", "schema": {"output_path": "str?", "resolution_x": "int", "resolution_y": "int", "samples": "int", "use_denoise": "bool"}},
    "frame_selection": {"func": tool_frame_selection, "description": "Frame selected objects with active camera", "schema": {"margin": "float"}},
    "lighting_preset": {"func": tool_lighting_preset, "description": "Create basic lighting preset", "schema": {"preset": "three_point", "strength": "float"}},
    "create_armature_humanoid": {"func": tool_create_armature_humanoid, "description": "Create a basic humanoid armature in T-pose", "schema": {"name": "str", "scale": "float"}},
    "auto_weight_bind": {"func": tool_auto_weight_bind, "description": "Bind mesh to armature with automatic weights", "schema": {"object_name": "str", "armature_name": "str", "method": "automatic|name", "clean_threshold": "float"}},
    "mirror_weights": {"func": tool_mirror_weights, "description": "Mirror vertex weights across an axis", "schema": {"object_name": "str", "axis": "X|Y|Z", "use_topology": "bool"}},
    "normalize_weights": {"func": tool_normalize_weights, "description": "Normalize all vertex groups", "schema": {"object_name": "str"}},
    "prune_small_weights": {"func": tool_prune_small_weights, "description": "Remove small vertex weights", "schema": {"object_name": "str", "threshold": "float"}},
    "retarget_bone_map": {"func": tool_retarget_bone_map, "description": "Export a simple humanoid bone map", "schema": {"armature_name": "str"}},
    "import_file": {"func": tool_import_file, "description": "Import supported 3D file", "schema": {}},
    "export_file": {"func": tool_export_file, "description": "Export supported 3D file", "schema": {}},
    "save_blend_file": {"func": tool_save_blend_file, "description": "Save .blend file", "schema": {}},
    "clear_scene": {"func": tool_clear_scene, "description": "Clear current scene", "schema": {}},
    "set_timeline_frame": {"func": tool_set_timeline_frame, "description": "Set the current timeline frame", "schema": {"frame": "int"}},
    "set_viewport_shading": {"func": tool_set_viewport_shading, "description": "Set viewport shading mode for visible 3D views", "schema": {}},
    "set_rigid_body_world": {"func": tool_set_rigid_body_world, "description": "Configure rigid body world settings", "schema": {}},
    "add_rigid_body": {"func": tool_add_rigid_body, "description": "Add a rigid body to an object", "schema": {"object_name": "str"}},
    "configure_rigid_body": {"func": tool_configure_rigid_body, "description": "Configure an existing rigid body", "schema": {"object_name": "str"}},
    "free_bake": {"func": tool_free_bake, "description": "Free all physics cache bakes", "schema": {}},
    "reset_physics_simulation": {"func": tool_reset_physics_simulation, "description": "Clear physics caches and reset the timeline", "schema": {}},
    "bake_to_frame": {"func": tool_bake_to_frame, "description": "Bake physics caches through a frame range", "schema": {"frame_end": "int"}},
    "add_impactor": {"func": tool_add_impactor, "description": "Create a heavy rigid body impactor sphere", "schema": {}},
    "build_and_smash_demo": {"func": tool_build_and_smash_demo, "description": "Build a lit rigid-body cube demo scene with cinematic reveal", "schema": {}},
    "apply_mod_stack": {"func": tool_apply_mod_stack, "description": "Apply all modifiers on an object", "schema": {"object_name": "str"}},
    "duplicate_array_radial": {"func": tool_duplicate_array_radial, "description": "Duplicate object radially", "schema": {"object_name": "str", "count": "int", "radius": "float"}},
    "set_world_color_or_hdri": {"func": tool_set_world_color_or_hdri, "description": "Set world background color or HDRI", "schema": {"color": "[r,g,b]", "hdri_path": "str", "strength": "float"}},
    "call_operator": {"func": tool_call_operator, "description": "Generic bpy.ops bridge", "schema": {}},
    "run_python_snippet": {"func": tool_run_python_snippet, "description": "Execute Python in Blender context", "schema": {"code": "Python source string"}},
}

# ============================================================
# HTTP API
# ============================================================

class BridgeHTTPHandler(BaseHTTPRequestHandler):
    server_version = "MTECBlenderBridge/0.1"

    def _write_json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._write_json(200, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ["/", "/info"]:
            tools = [
                (name, meta["description"], meta["schema"])
                for name, meta in TOOLS.items()
            ]
            html_parts = [
                "<!doctype html>",
                "<html><head><meta charset='utf-8'>",
                "<title>MTEC Blender Bridge</title>",
                "<style>",
                "body{font-family:Inter,Arial,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px;line-height:1.5;}",
                ".card{max-width:960px;margin:0 auto;background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;box-shadow:0 10px 40px rgba(0,0,0,0.4);}",
                "h1{margin:0 0 12px;font-size:26px;}",
                ".muted{color:#8b949e;font-size:14px;}",
                ".pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#238636;color:#e6edf3;font-size:12px;margin-left:8px;}",
                "table{width:100%;border-collapse:collapse;margin-top:16px;}",
                "th,td{border-bottom:1px solid #30363d;padding:8px 6px;text-align:left;vertical-align:top;font-size:14px;}",
                "th{color:#8b949e;font-weight:600;}",
                "code{background:#0b0f14;border:1px solid #30363d;padding:2px 4px;border-radius:6px;font-size:13px;}",
                ".schema{color:#8b949e;font-size:13px;}",
                "</style></head><body>",
                "<div class='card'>",
                f"<h1>MTEC Blender Bridge <span class='pill'>OK</span></h1>",
                f"<div class='muted'>Revision {MTECBRIDGE_Config.REVISION} &mdash; Host {MTECBRIDGE_Config.HOST}:{MTECBRIDGE_Config.PORT}</div>",
                f"<div class='muted'>Tools: {len(tools)}</div>",
                "<table>",
                "<tr><th>Tool</th><th>Beskrivning</th><th>Schema</th></tr>",
            ]
            for name, desc, schema in tools:
                html_parts.append("<tr>")
                html_parts.append(f"<td><code>{name}</code></td>")
                html_parts.append(f"<td>{desc}</td>")
                html_parts.append(f"<td class='schema'><pre style='margin:0;white-space:pre-wrap;'>"
                                  f"{json.dumps(schema, ensure_ascii=False, indent=2)}</pre></td>")
                html_parts.append("</tr>")
            html_parts.extend([
                "</table>",
                "<p class='muted'>Health: <code>/health</code> &middot; Tools JSON: <code>/tools</code> &middot; Invoke: <code>/invoke</code> (POST)</p>",
                "</div></body></html>"
            ])
            html = "".join(html_parts)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/health":
            self._write_json(200, {
                "ok": True,
                "service": "MTEC Blender Bridge",
                "revision": MTECBRIDGE_Config.REVISION,
                "host": MTECBRIDGE_Config.HOST,
                "port": MTECBRIDGE_Config.PORT,
                "timestamp": now_iso(),
            })
            return

        if parsed.path == "/tools":
            self._write_json(200, {
                "ok": True,
                "tools": [
                    {
                        "name": name,
                        "description": meta["description"],
                        "schema": meta["schema"],
                    }
                    for name, meta in TOOLS.items()
                ]
            })
            return

        self._write_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._write_json(400, {"ok": False, "error": "Invalid JSON"})
            return

        if parsed.path != "/invoke":
            self._write_json(404, {"ok": False, "error": "Not found"})
            return

        tool_name = payload.get("tool")
        kwargs = payload.get("kwargs", {}) or {}

        if tool_name not in TOOLS:
            self._write_json(404, {"ok": False, "error": f"Unknown tool '{tool_name}'"})
            return

        req_id = payload.get("id") or f"req_{datetime.now().timestamp()}"
        executor.execute(req_id, TOOLS[tool_name]["func"], **kwargs)

        import time
        started = time.time()
        while time.time() - started < MTECBRIDGE_Config.QUEUE_TIMEOUT:
            if req_id in executor.results:
                result = executor.results.pop(req_id)
                if result["ok"]:
                    self._write_json(200, {"ok": True, "tool": tool_name, "result": serialize(result["result"])})
                else:
                    self._write_json(500, {"ok": False, "tool": tool_name, "error": result["error"], "traceback": result.get("traceback", "")})
                return
            time.sleep(0.01)

        self._write_json(504, {"ok": False, "error": "Bridge timeout"})

    def log_message(self, format, *args):
        print("[MTECBridge]", format % args)


server_instance = None
server_thread = None

def start_http_server():
    global server_instance, server_thread
    if server_thread and server_thread.is_alive():
        return

    executor.start()
    server_instance = ThreadingHTTPServer((MTECBRIDGE_Config.HOST, MTECBRIDGE_Config.PORT), BridgeHTTPHandler)
    server_thread = threading.Thread(target=server_instance.serve_forever, daemon=True)
    server_thread.start()

def stop_http_server():
    global server_instance, server_thread
    if server_instance:
        server_instance.shutdown()
        server_instance.server_close()
        server_instance = None
    server_thread = None
    executor.stop()

def server_running():
    return server_thread is not None and server_thread.is_alive()

# ============================================================
# UI
# ============================================================

class MTECBRIDGE_OT_start_server(bpy.types.Operator):
    bl_idname = "mtecbridge.start_server"
    bl_label = "Start MTEC Bridge"

    def execute(self, context):
        try:
            start_http_server()
            self.report({'INFO'}, f"MTEC Blender Bridge running on http://{MTECBRIDGE_Config.HOST}:{MTECBRIDGE_Config.PORT}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

class MTECBRIDGE_OT_stop_server(bpy.types.Operator):
    bl_idname = "mtecbridge.stop_server"
    bl_label = "Stop MTEC Bridge"

    def execute(self, context):
        stop_http_server()
        self.report({'INFO'}, "MTEC Blender Bridge stopped")
        return {'FINISHED'}

class MTECBRIDGE_PT_panel(bpy.types.Panel):
    bl_label = "MTEC MCP"
    bl_idname = "MTECBRIDGE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MTEC MCP"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        box.label(text="MTEC Blender Bridge")
        box.label(text=f"Revision: {MTECBRIDGE_Config.REVISION}")
        box.label(text=f"Endpoint: http://{MTECBRIDGE_Config.HOST}:{MTECBRIDGE_Config.PORT}")
        box.label(text=f"Objects: {len(bpy.data.objects)}")
        if server_running():
            box.operator("mtecbridge.stop_server", icon='PAUSE')
        else:
            box.operator("mtecbridge.start_server", icon='PLAY')
        viewport_box = layout.box()
        viewport_box.prop(
            scene,
            "mtecbridge_show_viewport_settings",
            text="Viewport",
            icon='TRIA_DOWN' if scene.mtecbridge_show_viewport_settings else 'TRIA_RIGHT',
            emboss=False,
        )
        if scene.mtecbridge_show_viewport_settings:
            viewport_box.prop(scene, "mtecbridge_view_mode", text="Mode")
            if scene.mtecbridge_view_mode == 'CINEMATIC':
                viewport_box.prop(scene, "mtecbridge_cinematic_duration", text="Motion duration")
                viewport_box.prop(scene, "mtecbridge_cinematic_pitch_deg", text="Orbit pitch")
                viewport_box.prop(scene, "mtecbridge_cinematic_sweep_step_deg", text="Sweep step")
                viewport_box.prop(scene, "mtecbridge_cinematic_pitch_variation_deg", text="Pitch variation")
                viewport_box.prop(scene, "mtecbridge_cinematic_distance_scale", text="Distance scale")
                viewport_box.prop(scene, "mtecbridge_cinematic_retain_distance", text="Keep overview")
                viewport_box.prop(scene, "mtecbridge_cinematic_dolly_variation", text="Dolly variation")
            else:
                viewport_box.prop(scene, "mtecbridge_auto_focus", text="Auto-focus edited objects")
                viewport_box.prop(scene, "mtecbridge_auto_orbit", text="Auto-orbit edited objects")
                viewport_box.prop(scene, "mtecbridge_smooth_view", text="Smooth camera motion")
                smooth_col = viewport_box.column()
                smooth_col.enabled = scene.mtecbridge_smooth_view
                smooth_col.prop(scene, "mtecbridge_view_duration", text="Motion duration")
                orbit_col = viewport_box.column()
                orbit_col.enabled = scene.mtecbridge_auto_orbit
                orbit_col.prop(scene, "mtecbridge_orbit_yaw_deg", text="Orbit yaw")
                orbit_col.prop(scene, "mtecbridge_orbit_pitch_deg", text="Orbit pitch")
                orbit_col.prop(scene, "mtecbridge_orbit_roll_deg", text="Orbit roll")
        box = layout.box()
        box.label(text="HTTP paths")
        box.label(text="/health")
        box.label(text="/tools")
        box.label(text="/invoke")

classes = [
    MTECBRIDGE_OT_start_server,
    MTECBRIDGE_OT_stop_server,
    MTECBRIDGE_PT_panel,
]

def register():
    bpy.types.Scene.mtecbridge_auto_focus = bpy.props.BoolProperty(
        name="Auto-focus edited objects",
        description="Frame selected/edited objects in the first 3D viewport after bridge operations",
        default=False,
    )
    bpy.types.Scene.mtecbridge_show_viewport_settings = bpy.props.BoolProperty(
        name="Show viewport settings",
        description="Expand viewport automation settings",
        default=False,
    )
    bpy.types.Scene.mtecbridge_view_mode = bpy.props.EnumProperty(
        name="Viewport mode",
        description="Choose how the bridge should move the viewport",
        items=[
            ('MANUAL', "Manual", "Use the manual focus/orbit controls"),
            ('CINEMATIC', "Cinematic", "Use smoother, presentation-friendly camera motion"),
        ],
        default='MANUAL',
    )
    bpy.types.Scene.mtecbridge_auto_orbit = bpy.props.BoolProperty(
        name="Auto-orbit edited objects",
        description="Apply a small view rotation after framing to make demos more readable",
        default=False,
    )
    bpy.types.Scene.mtecbridge_smooth_view = bpy.props.BoolProperty(
        name="Smooth camera motion",
        description="Animate viewport motion instead of jumping instantly",
        default=True,
    )
    bpy.types.Scene.mtecbridge_view_duration = bpy.props.FloatProperty(
        name="Motion duration",
        description="Viewport animation duration in seconds",
        default=0.45,
        min=0.05,
        max=3.0,
    )
    bpy.types.Scene.mtecbridge_orbit_yaw_deg = bpy.props.FloatProperty(
        name="Orbit yaw",
        description="Horizontal orbit step in degrees",
        default=12.0,
        min=-180.0,
        max=180.0,
    )
    bpy.types.Scene.mtecbridge_orbit_pitch_deg = bpy.props.FloatProperty(
        name="Orbit pitch",
        description="Vertical orbit step in degrees",
        default=-5.0,
        min=-180.0,
        max=180.0,
    )
    bpy.types.Scene.mtecbridge_orbit_roll_deg = bpy.props.FloatProperty(
        name="Orbit roll",
        description="Roll orbit step in degrees",
        default=0.0,
        min=-180.0,
        max=180.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_duration = bpy.props.FloatProperty(
        name="Cinematic motion duration",
        description="Viewport animation duration in cinematic mode",
        default=0.9,
        min=0.05,
        max=5.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_yaw_deg = bpy.props.FloatProperty(
        name="Cinematic orbit yaw",
        description="Legacy cinematic yaw control",
        default=18.0,
        min=-180.0,
        max=180.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_pitch_deg = bpy.props.FloatProperty(
        name="Cinematic orbit pitch",
        description="Vertical orbit step in cinematic mode",
        default=12.0,
        min=-180.0,
        max=180.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_sweep_step_deg = bpy.props.FloatProperty(
        name="Cinematic sweep step",
        description="How much the camera moves around the object between operations",
        default=32.0,
        min=1.0,
        max=180.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_pitch_variation_deg = bpy.props.FloatProperty(
        name="Cinematic pitch variation",
        description="Extra vertical variation applied during cinematic sweeps",
        default=4.0,
        min=0.0,
        max=45.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_distance_scale = bpy.props.FloatProperty(
        name="Cinematic distance scale",
        description="How much extra distance to add after framing in cinematic mode",
        default=1.35,
        min=0.5,
        max=3.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_retain_distance = bpy.props.FloatProperty(
        name="Cinematic keep overview",
        description="Minimum fraction of the current view distance to preserve in cinematic mode",
        default=0.82,
        min=0.0,
        max=2.0,
    )
    bpy.types.Scene.mtecbridge_cinematic_dolly_variation = bpy.props.FloatProperty(
        name="Cinematic dolly variation",
        description="How much the camera distance should breathe during round-robin sweeps",
        default=0.08,
        min=0.0,
        max=0.5,
    )
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    stop_http_server()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.mtecbridge_cinematic_dolly_variation
    del bpy.types.Scene.mtecbridge_cinematic_retain_distance
    del bpy.types.Scene.mtecbridge_cinematic_pitch_variation_deg
    del bpy.types.Scene.mtecbridge_cinematic_sweep_step_deg
    del bpy.types.Scene.mtecbridge_cinematic_distance_scale
    del bpy.types.Scene.mtecbridge_cinematic_pitch_deg
    del bpy.types.Scene.mtecbridge_cinematic_yaw_deg
    del bpy.types.Scene.mtecbridge_cinematic_duration
    del bpy.types.Scene.mtecbridge_view_mode
    del bpy.types.Scene.mtecbridge_show_viewport_settings
    del bpy.types.Scene.mtecbridge_view_duration
    del bpy.types.Scene.mtecbridge_smooth_view
    del bpy.types.Scene.mtecbridge_orbit_roll_deg
    del bpy.types.Scene.mtecbridge_orbit_pitch_deg
    del bpy.types.Scene.mtecbridge_orbit_yaw_deg
    del bpy.types.Scene.mtecbridge_auto_orbit
    del bpy.types.Scene.mtecbridge_auto_focus

if __name__ == "__main__":
    register()
