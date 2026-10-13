"""Reusable mesh workflows for Blender; no project-specific dimensions."""
import math

import bpy
import bmesh
from mathutils import Matrix, Vector

UNITS = {"m": 1.0, "mm": 0.001, "in": 0.0254}


def unit_scale(units):
    if units not in UNITS:
        raise ValueError("units must be m, mm or in")
    return UNITS[units]


def vector3(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three finite numbers")
    numbers = [float(v) for v in value]
    if not all(math.isfinite(v) for v in numbers):
        raise ValueError(f"{name} must contain three finite numbers")
    return Vector(numbers)


def require_mesh(name):
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != 'MESH':
        raise ValueError(f"Mesh object not found: {name}")
    return obj


def require_object_mode():
    if bpy.context.mode != 'OBJECT':
        raise ValueError("Switch to OBJECT mode before changing geometry")


def mesh_report(mesh, matrix=None, scale=1.0, require_closed=False):
    matrix = matrix if matrix is not None else Matrix.Identity(4)
    points = [matrix @ v.co for v in mesh.vertices]
    finite = all(all(math.isfinite(c) for c in p) for p in points)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.transform(matrix)
        boundary = sum(e.is_boundary for e in bm.edges)
        non_manifold = sum(not e.is_manifold for e in bm.edges)
        inconsistent = sum(e.is_manifold and not e.is_contiguous for e in bm.edges)
        loose = sum(not e.link_faces for e in bm.edges)
        loose_vertices = sum(not v.link_faces for v in bm.verts)
        degenerate = sum(not math.isfinite(f.calc_area()) or f.calc_area() <= 1e-18 for f in bm.faces)
    finally:
        bm.free()
    bounds = None
    if points and finite:
        low = [min(p[i] for p in points) / scale for i in range(3)]
        high = [max(p[i] for p in points) / scale for i in range(3)]
        bounds = {"min": low, "max": high, "dimensions": [b-a for a,b in zip(low,high)]}
    valid = bool(mesh.polygons) and finite and not degenerate and not inconsistent and not loose_vertices
    # Open boundaries are allowed for intentional surfaces; loose edges and
    # branching edges still indicate invalid surface topology.
    valid = valid and (non_manifold == 0 if require_closed else non_manifold == boundary)
    return {"valid": bool(valid), "vertices": len(mesh.vertices), "faces": len(mesh.polygons),
            "boundary_edges": boundary, "non_manifold_edges": non_manifold,
            "loose_edges": loose, "degenerate_faces": degenerate,
            "loose_vertices": loose_vertices,
            "inconsistent_winding_edges": inconsistent,
            "finite_coordinates": finite, "bounds": bounds}


def validate_meshes(object_names, evaluated=True, units="mm", require_closed=False,
                    expected_dimensions=None, tolerance=0.1):
    """Read-only inspection; expected_dimensions maps object names to XYZ sizes."""
    scale = unit_scale(units)
    if not object_names or len(set(object_names)) != len(object_names):
        raise ValueError("object_names must be non-empty and unique")
    objects = [require_mesh(name) for name in object_names]
    if any(obj.mode == 'EDIT' for obj in objects):
        raise ValueError("Leave EDIT mode before validating mesh data")
    expected_dimensions = expected_dimensions or {}
    if not isinstance(expected_dimensions, dict) or set(expected_dimensions) - set(object_names):
        raise ValueError("expected_dimensions must map requested object names to dimensions")
    expected = {name: vector3(value, name) for name, value in expected_dimensions.items()}
    if any(any(v < 0 for v in value) for value in expected.values()):
        raise ValueError("Expected dimensions must be non-negative")
    tolerance = float(tolerance)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    deps = bpy.context.evaluated_depsgraph_get()
    reports = []
    for obj in objects:
        ev = obj.evaluated_get(deps) if evaluated else None
        try:
            mesh = ev.to_mesh() if ev else obj.data
            report = mesh_report(mesh, ev.matrix_world if ev else obj.matrix_world, scale, require_closed)
            report["object_name"] = obj.name
            if obj.name in expected:
                actual = report["bounds"]["dimensions"] if report["bounds"] else None
                errors = [abs(a-b) for a,b in zip(actual, expected[obj.name])] if actual else None
                matches = errors is not None and all(e <= tolerance for e in errors)
                report.update(expected_dimensions=list(expected[obj.name]), dimension_errors=errors,
                              dimensions_match=matches, valid=report["valid"] and matches)
            reports.append(report)
        finally:
            if ev:
                ev.to_mesh_clear()
    return {"valid": all(r["valid"] for r in reports), "units": units,
            "evaluated": evaluated, "require_closed": require_closed, "objects": reports}


def candidate_mesh(name, vertices, faces, units, require_closed):
    scale = unit_scale(units)
    if not vertices or not faces:
        raise ValueError("vertices and faces must be non-empty")
    coords = [vector3(v, "vertex") * scale for v in vertices]
    for face in faces:
        if len(face) < 3 or len(set(face)) != len(face):
            raise ValueError("Each face needs at least three distinct vertex indices")
        if any(type(i) is not int or i < 0 or i >= len(coords) for i in face):
            raise ValueError("Face vertex index out of range")
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(coords, [], faces)
        mesh.update()
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(mesh)
        finally:
            bm.free()
        report = mesh_report(mesh, require_closed=require_closed)
        if not report["valid"]:
            raise ValueError(f"Invalid candidate mesh: {report}")
        return mesh
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise


def replace_mesh_geometry(object_name, vertices, faces, units="mm",
                          require_closed=False, clear_vertex_groups=False):
    """Replace local geometry, keeping object identity, transforms and modifiers."""
    require_object_mode()
    obj = require_mesh(object_name)
    if obj.data.shape_keys:
        raise ValueError("Replacement of meshes with shape keys is not supported")
    if obj.vertex_groups and not clear_vertex_groups:
        raise ValueError("Vertex groups reference old indices; set clear_vertex_groups=True explicitly")
    old = obj.data
    mesh = candidate_mesh(f"{object_name}_mesh", vertices, faces, units, require_closed)
    try:
        for material in old.materials:
            mesh.materials.append(material)
        if clear_vertex_groups:
            obj.vertex_groups.clear()
        obj.data = mesh
    except Exception:
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
        raise
    if not old.users:
        bpy.data.meshes.remove(old)
    bpy.context.view_layer.update()
    return {"object_name": obj.name, "units": units, "shared_users_updated": False,
            "preserved": ["object identity", "transform", "collections", "material slots", "modifiers"],
            "validation": mesh_report(mesh, obj.matrix_world, unit_scale(units), require_closed)}


def create_profile_member(name, start, end, profile="L", width=19.05, height=19.05,
                          thickness=3.175, units="mm", reference_normal=None,
                          hollow=False, material_name="", collection_name=""):
    """Straight L/U/rectangular extrusion; section origin is its lower corner."""
    require_object_mode()
    if not name or bpy.data.objects.get(name):
        raise ValueError("Provide a non-empty, unused object name")
    scale = unit_scale(units)
    a, b = vector3(start,"start") * scale, vector3(end,"end") * scale
    direction = b-a
    if direction.length <= 1e-9:
        raise ValueError("start and end must differ")
    w,h,t = [float(v) for v in (width,height,thickness)]
    if not all(math.isfinite(v) for v in (w,h,t)) or w <= 0 or h <= 0 or t < 0:
        raise ValueError("Section dimensions must be finite; width/height positive, thickness non-negative")
    profile = profile.upper()
    if profile not in {'L','U','RECT'}:
        raise ValueError("profile must be L, U or RECT")
    if hollow and profile != 'RECT':
        raise ValueError("hollow applies only to RECT")
    if profile != 'RECT' or hollow:
        if t <= 0 or t >= min(w,h) or (profile == 'U' and 2*t >= w) or (hollow and 2*t >= min(w,h)):
            raise ValueError("Thickness leaves no usable interior section")
    material = bpy.data.materials.get(material_name) if material_name else None
    if material_name and material is None:
        raise ValueError(f"Material not found: {material_name}")
    z = direction.normalized()
    ref = vector3(reference_normal,"reference_normal") if reference_normal is not None else min(
        (Vector((1,0,0)),Vector((0,1,0)),Vector((0,0,1))),key=lambda axis: abs(axis.dot(z)))
    x = ref-z*ref.dot(z)
    if x.length < 1e-9:
        raise ValueError("reference_normal must not be parallel to member")
    x.normalize();y=z.cross(x)
    if profile == 'L':
        section=[(0,0),(w,0),(w,t),(t,t),(t,h),(0,h)]
    elif profile == 'U':
        section=[(0,0),(w,0),(w,h),(w-t,h),(w-t,t),(t,t),(t,h),(0,h)]
    else:
        section=[(0,0),(w,0),(w,h),(0,h)]
        if hollow:
            section += [(t,t),(w-t,t),(w-t,h-t),(t,h-t)]
    n=len(section);length=direction.length/scale
    vertices=[(u,v,d) for d in (0,length) for u,v in section]
    if hollow:
        faces=[]
        for i in range(4):
            j=(i+1)%4
            faces.extend([(i,j,n+j,n+i),(4+j,4+i,n+4+i,n+4+j),
                          (j,i,4+i,4+j),(n+i,n+j,n+4+j,n+4+i)])
    else:
        faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
        faces += [(i,(i+1)%n,n+(i+1)%n,n+i) for i in range(n)]
    mesh=candidate_mesh(name+'_mesh',vertices,faces,units,True)
    obj=None;created_collection=None
    try:
        if material:
            mesh.materials.append(material)
        col=bpy.data.collections.get(collection_name) if collection_name else bpy.context.scene.collection
        if col is None:
            col=bpy.data.collections.new(collection_name);created_collection=col
            bpy.context.scene.collection.children.link(col)
        # Existing collections must belong to the current scene.
        def contains(parent):
            return parent == col or any(contains(child) for child in parent.children)
        if not contains(bpy.context.scene.collection):
            raise ValueError("Collection is not linked to the current scene")
        obj=bpy.data.objects.new(name,mesh);col.objects.link(obj)
        obj.matrix_world=Matrix((x,y,z)).transposed().to_4x4();obj.matrix_world.translation=a
        obj['mtec_profile']=profile;obj['mtec_units']=units
        bpy.context.view_layer.update()
        return {"object_name":obj.name,"profile":profile,"units":units,"length":length,
                "section":{"width":w,"height":h,"thickness":t if profile!='RECT' or hollow else None,"hollow":hollow},
                "validation":mesh_report(mesh,obj.matrix_world,scale,True)}
    except Exception:
        if obj:
            bpy.data.objects.remove(obj,do_unlink=True)
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
        if created_collection:
            bpy.data.collections.remove(created_collection)
        raise
