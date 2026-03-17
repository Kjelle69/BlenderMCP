bl_info = {
    "name": "MTECBlenderMCP",
    "author": "OpenAI + MTEC Productions",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MTEC MCP",
    "description": "Run a local MCP server from Blender so Codex in VS Code can control Blender.",
    "category": "Development",
}

import bpy
import sys
import os
import math
import json
import time
import queue
import shlex
import base64
import random
import logging
import tempfile
import traceback
import threading
import subprocess
import importlib
import contextlib
from pathlib import Path
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] [MTECBlenderMCP] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


class MTECMCPConfig:
    HOST = "127.0.0.1"
    PORT = 8765
    STARTUP_TIMEOUT = 20.0
    EXECUTION_TIMEOUT = 120.0
    QUEUE_POLL_SECONDS = 0.01
    MAX_QUEUE_SIZE = 1000
    AUTO_INSTALL = True


uvicorn = None
FastAPI = None
FastMCP = None


def _ensure_package(import_name: str, pip_name: str) -> None:
    try:
        importlib.import_module(import_name)
        return
    except ImportError:
        if not MTECMCPConfig.AUTO_INSTALL:
            raise

    logger.info("Installing missing package %s", pip_name)
    try:
        subprocess.check_call([sys.executable, "-m", "ensurepip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
    importlib.invalidate_caches()
    importlib.import_module(import_name)


def bootstrap_runtime() -> None:
    global uvicorn, FastAPI, FastMCP
    if uvicorn is not None and FastAPI is not None and FastMCP is not None:
        return

    _ensure_package("fastapi", "fastapi")
    _ensure_package("uvicorn", "uvicorn[standard]")
    _ensure_package("mcp", 'mcp[cli]')

    import uvicorn as _uvicorn
    from fastapi import FastAPI as _FastAPI
    from mcp.server.fastmcp import FastMCP as _FastMCP

    uvicorn = _uvicorn
    FastAPI = _FastAPI
    FastMCP = _FastMCP
    logger.info("MCP runtime ready")


class MainThreadExecutor:
    def __init__(self) -> None:
        self.requests: "queue.Queue[dict]" = queue.Queue(maxsize=MTECMCPConfig.MAX_QUEUE_SIZE)
        self.results: Dict[str, dict] = {}
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        if not bpy.app.timers.is_registered(self._process):
            bpy.app.timers.register(self._process)
        self.running = True
        logger.info("MainThreadExecutor started")

    def stop(self) -> None:
        if bpy.app.timers.is_registered(self._process):
            bpy.app.timers.unregister(self._process)
        self.running = False
        logger.info("MainThreadExecutor stopped")

    def _process(self):
        try:
            while True:
                req = self.requests.get_nowait()
                req_id = req["id"]
                try:
                    result = req["func"](*req["args"], **req["kwargs"])
                    self.results[req_id] = {"ok": True, "result": result}
                except Exception as e:
                    self.results[req_id] = {
                        "ok": False,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    }
        except queue.Empty:
            pass
        return MTECMCPConfig.QUEUE_POLL_SECONDS

    def call(self, func, *args, **kwargs):
        req_id = f"req-{time.time_ns()}-{random.randint(1000,9999)}"
        self.requests.put({"id": req_id, "func": func, "args": args, "kwargs": kwargs}, timeout=1.0)
        start = time.time()
        while time.time() - start < MTECMCPConfig.EXECUTION_TIMEOUT:
            if req_id in self.results:
                payload = self.results.pop(req_id)
                if payload["ok"]:
                    return payload["result"]
                raise RuntimeError(payload["error"] + "\n" + payload.get("traceback", ""))
            time.sleep(0.002)
        raise TimeoutError(f"Execution timed out after {MTECMCPConfig.EXECUTION_TIMEOUT}s")


EXECUTOR = MainThreadExecutor()


def on_main_thread(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return EXECUTOR.call(fn, *args, **kwargs)
    return wrapper


def _obj_or_raise(name: str):
    obj = bpy.data.objects.get(name)
    if not obj:
        raise ValueError(f"Object '{name}' not found")
    return obj


def _material_or_raise(name: str):
    mat = bpy.data.materials.get(name)
    if not mat:
        raise ValueError(f"Material '{name}' not found")
    return mat


def _ensure_collection(name: Optional[str]):
    if not name:
        return bpy.context.collection
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


@on_main_thread
def ping() -> Dict[str, Any]:
    return {
        "name": "MTECBlenderMCP",
        "ok": True,
        "blender_version": list(bpy.app.version),
        "scene": bpy.context.scene.name,
        "time": datetime.now().isoformat(),
    }


@on_main_thread
def get_scene_info() -> Dict[str, Any]:
    scene = bpy.context.scene
    obj_types: Dict[str, int] = {}
    for obj in scene.objects:
        obj_types[obj.type] = obj_types.get(obj.type, 0) + 1
    return {
        "scene_name": scene.name,
        "objects": len(scene.objects),
        "selected": len([o for o in scene.objects if o.select_get()]),
        "active_object": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        "object_types": obj_types,
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "current_frame": scene.frame_current,
        "frame_range": [scene.frame_start, scene.frame_end],
        "render_engine": scene.render.engine,
    }


@on_main_thread
def list_objects(object_type: Optional[str] = None, collection: Optional[str] = None) -> List[Dict[str, Any]]:
    objs = list(bpy.data.objects)
    if object_type:
        objs = [o for o in objs if o.type == object_type]
    if collection:
        coll = bpy.data.collections.get(collection)
        objs = [o for o in objs if coll and o.name in coll.objects]
    return [
        {
            "name": o.name,
            "type": o.type,
            "location": list(o.location),
            "visible": o.visible_get(),
            "selected": o.select_get(),
        }
        for o in objs
    ]


@on_main_thread
def get_object_info(object_name: str) -> Dict[str, Any]:
    obj = _obj_or_raise(object_name)
    bbox = [obj.matrix_world @ bpy.mathutils.Vector(corner) for corner in obj.bound_box] if hasattr(obj, "bound_box") else []
    dims = list(obj.dimensions)
    return {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation_euler_deg": [math.degrees(v) for v in obj.rotation_euler],
        "scale": list(obj.scale),
        "dimensions": dims,
        "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
        "modifiers": [m.name for m in obj.modifiers],
        "parent": obj.parent.name if obj.parent else None,
    }


@on_main_thread
def create_primitive(
    primitive_type: str = "cube",
    name: Optional[str] = None,
    location: Optional[List[float]] = None,
    rotation_deg: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    size: float = 2.0,
    collection: Optional[str] = None,
    segments: int = 32,
    rings: int = 16,
    vertices: int = 32,
    major_segments: int = 48,
    minor_segments: int = 12,
) -> Dict[str, Any]:
    location = location or [0.0, 0.0, 0.0]
    rotation_deg = rotation_deg or [0.0, 0.0, 0.0]
    scale = scale or [1.0, 1.0, 1.0]

    primitive_type = primitive_type.lower()
    if primitive_type == "cube":
        bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    elif primitive_type in {"sphere", "uv_sphere"}:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2.0, segments=segments, ring_count=rings, location=location)
    elif primitive_type == "ico_sphere":
        bpy.ops.mesh.primitive_ico_sphere_add(radius=size / 2.0, location=location)
    elif primitive_type == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=size / 2.0, depth=size, vertices=vertices, location=location)
    elif primitive_type == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=size / 2.0, radius2=0.0, depth=size, vertices=vertices, location=location)
    elif primitive_type == "plane":
        bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    elif primitive_type == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=size / 2.0, minor_radius=size / 5.0, major_segments=major_segments, minor_segments=minor_segments, location=location)
    elif primitive_type == "monkey":
        bpy.ops.mesh.primitive_monkey_add(size=size, location=location)
    else:
        raise ValueError(f"Unsupported primitive_type: {primitive_type}")

    obj = bpy.context.active_object
    if name:
        obj.name = name
        if obj.data:
            obj.data.name = f"{name}_data"
    obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    obj.scale = scale

    target_collection = _ensure_collection(collection)
    if target_collection not in obj.users_collection:
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        target_collection.objects.link(obj)

    return get_object_info(obj.name)


@on_main_thread
def transform_object(
    object_name: str,
    location: Optional[List[float]] = None,
    rotation_deg: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    delta: bool = False,
) -> Dict[str, Any]:
    obj = _obj_or_raise(object_name)
    if location is not None:
        if delta:
            obj.location.x += location[0]
            obj.location.y += location[1]
            obj.location.z += location[2]
        else:
            obj.location = location
    if rotation_deg is not None:
        rot = [math.radians(v) for v in rotation_deg]
        if delta:
            obj.rotation_euler.x += rot[0]
            obj.rotation_euler.y += rot[1]
            obj.rotation_euler.z += rot[2]
        else:
            obj.rotation_euler = rot
    if scale is not None:
        if delta:
            obj.scale.x *= scale[0]
            obj.scale.y *= scale[1]
            obj.scale.z *= scale[2]
        else:
            obj.scale = scale
    return get_object_info(object_name)


@on_main_thread
def duplicate_object(object_name: str, linked: bool = False, count: int = 1, offset: Optional[List[float]] = None) -> Dict[str, Any]:
    src = _obj_or_raise(object_name)
    offset = offset or [2.0, 0.0, 0.0]
    created = []
    for i in range(count):
        dup = src.copy()
        if src.data and not linked:
            dup.data = src.data.copy()
        dup.name = f"{src.name}_copy_{i+1}"
        dup.location = src.location.copy()
        dup.location.x += offset[0] * (i + 1)
        dup.location.y += offset[1] * (i + 1)
        dup.location.z += offset[2] * (i + 1)
        bpy.context.collection.objects.link(dup)
        created.append(dup.name)
    return {"source": object_name, "created": created, "linked": linked}


@on_main_thread
def delete_objects(object_names: List[str], delete_data: bool = True) -> Dict[str, Any]:
    deleted = []
    missing = []
    for name in object_names:
        obj = bpy.data.objects.get(name)
        if not obj:
            missing.append(name)
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if delete_data and data is not None and getattr(data, "users", 1) == 0:
            # Try to remove orphaned data blocks cleanly.
            for bag_name in ("meshes", "curves", "cameras", "lights", "grease_pencils", "fonts"):
                bag = getattr(bpy.data, bag_name, None)
                if bag is None:
                    continue
                try:
                    if data.name in bag:
                        bag.remove(data)
                        break
                except Exception:
                    pass
        deleted.append(name)
    return {"deleted": deleted, "missing": missing}


@on_main_thread
def set_parent(child_name: str, parent_name: Optional[str]) -> Dict[str, Any]:
    child = _obj_or_raise(child_name)
    parent = _obj_or_raise(parent_name) if parent_name else None
    child.parent = parent
    if parent:
        child.matrix_parent_inverse = parent.matrix_world.inverted()
    return {"child": child_name, "parent": parent_name}


@on_main_thread
def add_modifier(object_name: str, modifier_type: str, modifier_name: Optional[str] = None, settings_json: Optional[str] = None) -> Dict[str, Any]:
    obj = _obj_or_raise(object_name)
    mod = obj.modifiers.new(name=modifier_name or modifier_type, type=modifier_type)
    settings = json.loads(settings_json) if settings_json else {}
    for key, value in settings.items():
        if hasattr(mod, key):
            setattr(mod, key, value)
    return {"object": object_name, "modifier": mod.name, "type": modifier_type, "settings": settings}


@on_main_thread
def apply_modifier(object_name: str, modifier_name: str) -> Dict[str, Any]:
    obj = _obj_or_raise(object_name)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier_name)
    return {"object": object_name, "modifier_applied": modifier_name}


@on_main_thread
def create_material(
    material_name: str,
    base_color: Optional[List[float]] = None,
    metallic: float = 0.0,
    roughness: float = 0.5,
    alpha: float = 1.0,
) -> Dict[str, Any]:
    base_color = base_color or [0.8, 0.8, 0.8, 1.0]
    mat = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = None
    out = None
    for n in nodes:
        if n.type == 'BSDF_PRINCIPLED':
            bsdf = n
        elif n.type == 'OUTPUT_MATERIAL':
            out = n
    if bsdf is None:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    if out is None:
        out = nodes.new('ShaderNodeOutputMaterial')
    if not out.inputs['Surface'].is_linked:
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Base Color'].default_value = base_color
    if 'Metallic' in bsdf.inputs:
        bsdf.inputs['Metallic'].default_value = metallic
    if 'Roughness' in bsdf.inputs:
        bsdf.inputs['Roughness'].default_value = roughness
    if 'Alpha' in bsdf.inputs:
        bsdf.inputs['Alpha'].default_value = alpha
    if alpha < 1.0:
        mat.blend_method = 'BLEND'
    return {"material": mat.name, "base_color": base_color, "metallic": metallic, "roughness": roughness, "alpha": alpha}


@on_main_thread
def assign_material(object_name: str, material_name: str, slot_index: int = -1) -> Dict[str, Any]:
    obj = _obj_or_raise(object_name)
    mat = _material_or_raise(material_name)
    if not hasattr(obj.data, 'materials'):
        raise ValueError(f"Object '{object_name}' cannot hold materials")
    if slot_index < 0:
        obj.data.materials.append(mat)
        slot_index = len(obj.material_slots) - 1
    else:
        while len(obj.data.materials) <= slot_index:
            obj.data.materials.append(None)
        obj.data.materials[slot_index] = mat
    return {"object": object_name, "material": material_name, "slot_index": slot_index}


@on_main_thread
def create_light(
    light_type: str = "POINT",
    name: Optional[str] = None,
    location: Optional[List[float]] = None,
    rotation_deg: Optional[List[float]] = None,
    energy: float = 1000.0,
    color: Optional[List[float]] = None,
    size: float = 1.0,
) -> Dict[str, Any]:
    location = location or [0, 0, 5]
    rotation_deg = rotation_deg or [0, 0, 0]
    color = color or [1, 1, 1]
    data = bpy.data.lights.new(name or f"{light_type}_Light", type=light_type)
    data.energy = energy
    data.color = color
    if light_type == 'AREA':
        data.size = size
    elif light_type == 'POINT':
        data.shadow_soft_size = size
    obj = bpy.data.objects.new(name or f"{light_type}_Light", data)
    obj.location = location
    obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    bpy.context.collection.objects.link(obj)
    return {"name": obj.name, "type": light_type, "location": list(obj.location), "energy": energy}


@on_main_thread
def create_camera(
    name: str = "Camera_MCP",
    location: Optional[List[float]] = None,
    rotation_deg: Optional[List[float]] = None,
    focal_length: float = 50.0,
    set_active: bool = True,
) -> Dict[str, Any]:
    location = location or [7, -7, 5]
    rotation_deg = rotation_deg or [60, 0, 45]
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = focal_length
    cam_obj = bpy.data.objects.new(name, cam_data)
    cam_obj.location = location
    cam_obj.rotation_euler = [math.radians(v) for v in rotation_deg]
    bpy.context.collection.objects.link(cam_obj)
    if set_active:
        bpy.context.scene.camera = cam_obj
    return {"name": cam_obj.name, "location": list(cam_obj.location), "focal_length": focal_length, "active": set_active}


@on_main_thread
def save_blend_file(filepath: str, compress: bool = False, copy: bool = False) -> Dict[str, Any]:
    filepath = str(Path(filepath))
    if not filepath.lower().endswith('.blend'):
        filepath += '.blend'
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=compress, copy=copy)
    return {"saved": filepath, "compress": compress, "copy": copy}


@on_main_thread
def import_file(filepath: str) -> Dict[str, Any]:
    filepath = str(Path(filepath))
    ext = Path(filepath).suffix.lower()
    before = set(bpy.data.objects.keys())
    if ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=filepath)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=filepath)
    elif ext in {'.glb', '.gltf'}:
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == '.stl':
        bpy.ops.wm.stl_import(filepath=filepath)
    elif ext == '.ply':
        bpy.ops.wm.ply_import(filepath=filepath)
    elif ext == '.blend':
        raise ValueError('Importing .blend via this tool is not supported; use Append/Link or Python operator bridge.')
    else:
        raise ValueError(f'Unsupported file extension: {ext}')
    after = set(bpy.data.objects.keys())
    return {"filepath": filepath, "imported_objects": sorted(list(after - before))}


@on_main_thread
def export_file(filepath: str, file_format: str, selected_only: bool = False) -> Dict[str, Any]:
    filepath = str(Path(filepath))
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    ff = file_format.lower()
    if ff == 'fbx':
        bpy.ops.export_scene.fbx(filepath=filepath, use_selection=selected_only)
    elif ff == 'obj':
        bpy.ops.wm.obj_export(filepath=filepath, export_selected_objects=selected_only)
    elif ff == 'glb':
        bpy.ops.export_scene.gltf(filepath=filepath, export_format='GLB', use_selection=selected_only)
    elif ff == 'gltf':
        bpy.ops.export_scene.gltf(filepath=filepath, export_format='GLTF_SEPARATE', use_selection=selected_only)
    elif ff == 'stl':
        bpy.ops.wm.stl_export(filepath=filepath, export_selected_objects=selected_only)
    elif ff == 'ply':
        bpy.ops.wm.ply_export(filepath=filepath, export_selected_objects=selected_only)
    else:
        raise ValueError(f'Unsupported export format: {file_format}')
    return {"filepath": filepath, "format": file_format, "selected_only": selected_only}


@on_main_thread
def render_image(filepath: str, use_viewport: bool = False, animation: bool = False) -> Dict[str, Any]:
    filepath = str(Path(filepath))
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = filepath
    if use_viewport:
        bpy.ops.render.opengl(animation=animation, write_still=not animation)
    else:
        bpy.ops.render.render(animation=animation, write_still=not animation)
    return {"filepath": filepath, "animation": animation, "use_viewport": use_viewport}


@on_main_thread
def select_objects(object_names: List[str], active_object: Optional[str] = None) -> Dict[str, Any]:
    bpy.ops.object.select_all(action='DESELECT')
    selected = []
    for name in object_names:
        obj = bpy.data.objects.get(name)
        if obj:
            obj.select_set(True)
            selected.append(name)
    if active_object and bpy.data.objects.get(active_object):
        bpy.context.view_layer.objects.active = bpy.data.objects[active_object]
    elif selected:
        bpy.context.view_layer.objects.active = bpy.data.objects[selected[0]]
    return {"selected": selected, "active": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None}


@on_main_thread
def call_operator(operator_id: str, kwargs_json: Optional[str] = None) -> Dict[str, Any]:
    """Generic escape hatch: call any Blender operator, e.g. 'mesh.primitive_cube_add'."""
    kwargs = json.loads(kwargs_json) if kwargs_json else {}
    module_name, op_name = operator_id.split('.', 1)
    op_module = getattr(bpy.ops, module_name)
    op = getattr(op_module, op_name)
    result = op(**kwargs)
    return {"operator": operator_id, "kwargs": kwargs, "result": list(result) if result else []}


@on_main_thread
def run_python_snippet(code: str) -> Dict[str, Any]:
    """Last-resort escape hatch. Executes Python inside Blender. Use carefully."""
    scope = {
        'bpy': bpy,
        'math': math,
        'json': json,
        'Path': Path,
        'datetime': datetime,
        '__builtins__': __builtins__,
    }
    local_vars: Dict[str, Any] = {}
    exec(code, scope, local_vars)
    safe_locals = {k: repr(v)[:500] for k, v in local_vars.items() if not k.startswith('_')}
    return {"ok": True, "locals": safe_locals}


@on_main_thread
def capture_viewport_png(max_size: int = 768) -> Dict[str, Any]:
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp.close()
    scene = bpy.context.scene
    rx = scene.render.resolution_x
    ry = scene.render.resolution_y
    pct = scene.render.resolution_percentage
    longest = max(rx, ry)
    if longest > max_size:
        scene.render.resolution_percentage = max(1, int((max_size / longest) * 100))
    bpy.ops.render.opengl(write_still=True, view_context=True)
    rendered = bpy.data.images.get('Render Result')
    if rendered is None:
        raise RuntimeError('Render Result not found')
    rendered.save_render(filepath=tmp.name)
    with open(tmp.name, 'rb') as f:
        data = base64.b64encode(f.read()).decode('ascii')
    scene.render.resolution_x = rx
    scene.render.resolution_y = ry
    scene.render.resolution_percentage = pct
    os.unlink(tmp.name)
    return {"image_base64": data, "mime_type": "image/png"}


class MCPServerState:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.server = None
        self.app = None
        self.fastapi = None
        self.last_error = ""
        self.started_url = ""

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


STATE = MCPServerState()


def _build_fastmcp_server():
    bootstrap_runtime()
    mcp = FastMCP("MTECBlenderMCP", stateless_http=True)
    for tool in [
        ping,
        get_scene_info,
        list_objects,
        get_object_info,
        create_primitive,
        transform_object,
        duplicate_object,
        delete_objects,
        set_parent,
        add_modifier,
        apply_modifier,
        create_material,
        assign_material,
        create_light,
        create_camera,
        save_blend_file,
        import_file,
        export_file,
        render_image,
        select_objects,
        call_operator,
        run_python_snippet,
        capture_viewport_png,
    ]:
        mcp.tool()(tool)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())
            yield

    app = FastAPI(title="MTECBlenderMCP", lifespan=lifespan)
    app.mount("/mcp", mcp.streamable_http_app())
    return mcp, app


def start_server() -> str:
    if STATE.is_running():
        return STATE.started_url
    EXECUTOR.start()
    mcp, app = _build_fastmcp_server()
    config = uvicorn.Config(app, host=MTECMCPConfig.HOST, port=MTECMCPConfig.PORT, log_level="info")
    server = uvicorn.Server(config)
    STATE.server = server
    STATE.app = app
    STATE.fastapi = mcp
    STATE.last_error = ""
    STATE.started_url = f"http://{MTECMCPConfig.HOST}:{MTECMCPConfig.PORT}/mcp"

    def _runner():
        try:
            server.run()
        except Exception as e:
            STATE.last_error = f"{e}\n{traceback.format_exc()}"
            logger.exception("MTECBlenderMCP server crashed")

    thread = threading.Thread(target=_runner, daemon=True, name="MTECBlenderMCPServer")
    STATE.thread = thread
    thread.start()

    start = time.time()
    while time.time() - start < MTECMCPConfig.STARTUP_TIMEOUT:
        if STATE.last_error:
            raise RuntimeError(STATE.last_error)
        if thread.is_alive():
            # give uvicorn a moment to bind
            time.sleep(0.3)
            return STATE.started_url
        time.sleep(0.05)

    raise TimeoutError("Server did not start in time")


def stop_server() -> None:
    if STATE.server is not None:
        try:
            STATE.server.should_exit = True
        except Exception:
            pass
    if STATE.thread is not None:
        STATE.thread.join(timeout=3.0)
    STATE.thread = None
    STATE.server = None
    STATE.app = None
    STATE.fastapi = None
    EXECUTOR.stop()


class MTECMCPPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    host: bpy.props.StringProperty(name="Host", default=MTECMCPConfig.HOST)
    port: bpy.props.IntProperty(name="Port", default=MTECMCPConfig.PORT, min=1, max=65535)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.label(text="Restart the server after changing host/port.")


class MTECMCP_OT_start(bpy.types.Operator):
    bl_idname = "mtecmcp.start_server"
    bl_label = "Start MTEC Blender MCP"

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences if __name__ in context.preferences.addons else None
        if prefs:
            MTECMCPConfig.HOST = prefs.host
            MTECMCPConfig.PORT = prefs.port
        try:
            url = start_server()
            self.report({'INFO'}, f"MTECBlenderMCP started at {url}")
            return {'FINISHED'}
        except Exception as e:
            STATE.last_error = str(e)
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class MTECMCP_OT_stop(bpy.types.Operator):
    bl_idname = "mtecmcp.stop_server"
    bl_label = "Stop MTEC Blender MCP"

    def execute(self, context):
        stop_server()
        self.report({'INFO'}, "MTECBlenderMCP stopped")
        return {'FINISHED'}


class MTECMCP_OT_copy_url(bpy.types.Operator):
    bl_idname = "mtecmcp.copy_url"
    bl_label = "Copy MCP URL"

    def execute(self, context):
        context.window_manager.clipboard = STATE.started_url or f"http://{MTECMCPConfig.HOST}:{MTECMCPConfig.PORT}/mcp"
        self.report({'INFO'}, "Copied MCP URL to clipboard")
        return {'FINISHED'}


class MTECMCP_PT_panel(bpy.types.Panel):
    bl_label = "MTEC Blender MCP"
    bl_idname = "MTECMCP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MTEC MCP'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Codex ↔ Blender MCP bridge")
        if STATE.is_running():
            col.label(text="Status: Running", icon='CHECKMARK')
            col.label(text=STATE.started_url)
            row = col.row(align=True)
            row.operator("mtecmcp.stop_server", icon='CANCEL')
            row.operator("mtecmcp.copy_url", icon='COPYDOWN')
        else:
            col.label(text="Status: Stopped", icon='PAUSE')
            col.operator("mtecmcp.start_server", icon='PLAY')
        box = layout.box()
        box.label(text="Included tool categories")
        for line in [
            "Scene/object inspection",
            "Primitive creation + transforms",
            "Materials, lights, cameras",
            "Modifiers, import/export, render",
            "Generic operator bridge",
            "Python escape hatch",
        ]:
            box.label(text=f"• {line}")
        if STATE.last_error:
            err = layout.box()
            err.label(text="Last error", icon='ERROR')
            for line in str(STATE.last_error).splitlines()[:6]:
                err.label(text=line[:110])


CLASSES = [
    MTECMCPPreferences,
    MTECMCP_OT_start,
    MTECMCP_OT_stop,
    MTECMCP_OT_copy_url,
    MTECMCP_PT_panel,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    logger.info("MTECBlenderMCP registered")


def unregister():
    try:
        stop_server()
    except Exception:
        pass
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    logger.info("MTECBlenderMCP unregistered")


if __name__ == "__main__":
    register()
