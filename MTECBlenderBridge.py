bl_info = {
    "name": "MTEC Blender Bridge",
    "author": "OpenAI + MTEC",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MTEC MCP",
    "description": "Local HTTP bridge for Codex/VS Code control of Blender",
    "category": "Development",
}

import bpy
import json
import math
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
    REVISION = "v260317c"
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
        "timestamp": now_iso(),
    }

def tool_list_objects(object_type: str = ""):
    names = []
    for obj in bpy.data.objects:
        if object_type and obj.type != object_type:
            continue
        names.append(object_summary(obj))
    return {"count": len(names), "objects": names}

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
    return object_summary(obj)

def tool_transform_object(object_name: str, location=None, rotation_deg=None, scale=None, delta: bool = False):
    obj = require_object(object_name)
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

def tool_delete_objects(object_names):
    deleted = []
    for name in object_names:
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted.append(name)
    return {"deleted": deleted, "count": len(deleted)}

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

TOOLS = {
    "get_scene_info": {"func": tool_get_scene_info, "description": "Basic scene information", "schema": {}},
    "list_objects": {"func": tool_list_objects, "description": "List scene objects", "schema": {"object_type": "Optional Blender type filter"}},
    "create_mesh_object": {"func": tool_create_mesh_object, "description": "Create a primitive mesh object", "schema": {}},
    "create_curve_object": {"func": tool_create_curve_object, "description": "Create a curve object", "schema": {}},
    "create_text_object": {"func": tool_create_text_object, "description": "Create a text object", "schema": {}},
    "transform_object": {"func": tool_transform_object, "description": "Move/rotate/scale an object", "schema": {}},
    "duplicate_object": {"func": tool_duplicate_object, "description": "Duplicate object(s)", "schema": {}},
    "delete_objects": {"func": tool_delete_objects, "description": "Delete objects", "schema": {"object_names": "List[str]"}},
    "create_material": {"func": tool_create_material, "description": "Create a basic principled material", "schema": {}},
    "assign_material": {"func": tool_assign_material, "description": "Assign first material slot", "schema": {}},
    "create_light": {"func": tool_create_light, "description": "Create a light", "schema": {}},
    "create_camera": {"func": tool_create_camera, "description": "Create a camera", "schema": {}},
    "add_modifier": {"func": tool_add_modifier, "description": "Add modifier to object", "schema": {}},
    "apply_modifier": {"func": tool_apply_modifier, "description": "Apply modifier", "schema": {}},
    "boolean_operation": {"func": tool_boolean_operation, "description": "Boolean between two objects", "schema": {}},
    "configure_render_settings": {"func": tool_configure_render_settings, "description": "Configure render settings", "schema": {}},
    "render_image": {"func": tool_render_image, "description": "Render still image", "schema": {}},
    "import_file": {"func": tool_import_file, "description": "Import supported 3D file", "schema": {}},
    "export_file": {"func": tool_export_file, "description": "Export supported 3D file", "schema": {}},
    "save_blend_file": {"func": tool_save_blend_file, "description": "Save .blend file", "schema": {}},
    "clear_scene": {"func": tool_clear_scene, "description": "Clear current scene", "schema": {}},
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
        box = layout.box()
        box.label(text="MTEC Blender Bridge")
        box.label(text=f"Revision: {MTECBRIDGE_Config.REVISION}")
        box.label(text=f"Endpoint: http://{MTECBRIDGE_Config.HOST}:{MTECBRIDGE_Config.PORT}")
        box.label(text=f"Objects: {len(bpy.data.objects)}")
        if server_running():
            box.operator("mtecbridge.stop_server", icon='PAUSE')
        else:
            box.operator("mtecbridge.start_server", icon='PLAY')
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
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    stop_http_server()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
