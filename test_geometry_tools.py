"""Run with Blender --background --factory-startup --python test_geometry_tools.py."""
import ast
import importlib.util
import sys
import tempfile
from zipfile import ZipFile
from pathlib import Path
import unittest

import bpy
import bmesh
from mathutils import Matrix

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('geometry_test',ROOT/'mtec_geometry_tools.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)


class GeometryTests(unittest.TestCase):
    def setUp(self):
        if bpy.context.mode != 'OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)

    def member(self,name='Part',**kw):
        args=dict(name=name,start=[0,0,0],end=[0,0,100],profile='L',width=30,height=20,thickness=2,reference_normal=[1,0,0])
        args.update(kw);return g.create_profile_member(**args)

    def volume(self,name):
        bm=bmesh.new();bm.from_mesh(bpy.data.objects[name].data)
        try:return bm.calc_volume(signed=True)
        finally:bm.free()

    def test_inch_angle_dimension_and_volume(self):
        self.member(end=[0,0,10],width=.75,height=.75,thickness=.125,units='in')
        report=g.validate_meshes(['Part'],units='in',require_closed=True,
                                expected_dimensions={'Part':[.75,.75,10]},tolerance=.00001)
        self.assertTrue(report['valid'],report)
        self.assertAlmostEqual(self.volume('Part'),(.75*.125*2-.125**2)*10*.0254**3,places=10)

    def test_u_channel_closed_and_volume(self):
        result=self.member(profile='U')
        self.assertTrue(result['validation']['valid'])
        self.assertAlmostEqual(self.volume('Part'),(30*2+2*18*2)*100*1e-9,places=10)

    def test_hollow_rectangle_keeps_interior(self):
        result=self.member(profile='RECT',hollow=True)
        self.assertTrue(result['validation']['valid'])
        self.assertAlmostEqual(self.volume('Part'),(30*20-26*16)*100*1e-9,places=10)

    def test_solid_rectangle_volume(self):
        self.member(profile='RECT',thickness=0)
        self.assertAlmostEqual(self.volume('Part'),30*20*100*1e-9,places=10)

    def test_oblique_member_orientation(self):
        self.member(start=[12,-4,9],end=[42,36,-71],reference_normal=[0,0,1])
        obj=bpy.data.objects['Part'];top=[obj.matrix_world@v.co for v in obj.data.vertices if v.co.z>0]
        z=obj.matrix_world.to_3x3().col[2]
        self.assertAlmostEqual(z.dot(top[0]-obj.matrix_world.translation),(.03**2+.04**2+.08**2)**.5,places=7)
        self.assertEqual(g.validate_meshes(['Part'],require_closed=True)['valid'],True)

    def test_invalid_inputs_leave_no_objects_or_meshes(self):
        count=len(bpy.data.meshes)
        for kw in [dict(end=[0,0,0]),dict(width=-1),dict(thickness=30),dict(reference_normal=[0,0,1]),
                   dict(units='feet'),dict(start=[float('nan'),0,0]),dict(material_name='Missing'),
                   dict(profile='U',thickness=16),dict(hollow=True),dict(profile='RECT',hollow=True,thickness=11)]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.member(**kw)
        self.assertIsNone(bpy.data.objects.get('Part'));self.assertEqual(len(bpy.data.meshes),count)

    def test_duplicate_name_rejected(self):
        self.member()
        with self.assertRaises(ValueError):self.member()
        self.assertIsNone(bpy.data.objects.get('Part.001'))

    def test_dimension_check_is_read_only(self):
        self.member();obj=bpy.data.objects['Part'];mesh=obj.data
        result=g.validate_meshes(['Part'],units='mm',expected_dimensions={'Part':[31,20,100]},tolerance=.01)
        self.assertFalse(result['valid']);self.assertIs(obj.data,mesh)

    def test_evaluated_modifier_bounds(self):
        self.member();obj=bpy.data.objects['Part'];mod=obj.modifiers.new('Scale geometry','ARRAY');mod.count=2
        mod.relative_offset_displace=(1,0,0)
        raw=g.validate_meshes(['Part'],evaluated=False)['objects'][0]['bounds']['dimensions'][0]
        applied=g.validate_meshes(['Part'],evaluated=True)['objects'][0]['bounds']['dimensions'][0]
        self.assertAlmostEqual(applied,raw*2,places=4);self.assertEqual(len(obj.modifiers),1)

    def test_replace_preserves_object_and_shared_peer(self):
        self.member();obj=bpy.data.objects['Part'];old=obj.data
        peer=bpy.data.objects.new('Peer',old);bpy.context.scene.collection.objects.link(peer)
        mat=bpy.data.materials.new('Fixture');old.materials.append(mat)
        obj.matrix_world=Matrix.Translation((1,2,3));matrix=obj.matrix_world.copy()
        mod=obj.modifiers.new('Keep','BEVEL');mod.width=.001
        col=bpy.data.collections.new('Fixture collection');bpy.context.scene.collection.children.link(col);col.objects.link(obj)
        source=self.member('Source',width=40);src=bpy.data.objects['Source']
        g.replace_mesh_geometry('Part',[list(v.co) for v in src.data.vertices],[list(f.vertices) for f in src.data.polygons],units='m',require_closed=True)
        self.assertIs(obj,bpy.data.objects['Part']);self.assertIs(peer.data,old)
        self.assertIs(obj.data.materials[0],mat);self.assertEqual(obj.matrix_world,matrix)
        self.assertEqual(obj.modifiers[0].as_pointer(),mod.as_pointer());self.assertIn(obj.name,col.objects)

    def test_replace_failure_preserves_mesh_and_cleans_candidate(self):
        self.member();obj=bpy.data.objects['Part'];old=obj.data;count=len(bpy.data.meshes)
        for verts,faces in [([[0,0,0],[1,0,0],[2,0,0]],[[0,1,2]]),
                            ([[0,0,0],[1,0,0],[0,1,0]],[[0,1,9]]),
                            ([[0,0,0],[1,0,0],[0,1,0]],[[0,1,2]])]:
            with self.assertRaises(ValueError):g.replace_mesh_geometry('Part',verts,faces,require_closed=True)
            self.assertIs(obj.data,old);self.assertEqual(len(bpy.data.meshes),count)

    def test_vertex_groups_require_explicit_clear(self):
        self.member();obj=bpy.data.objects['Part'];obj.vertex_groups.new(name='Old indices')
        vertices=[list(v.co) for v in obj.data.vertices];faces=[list(f.vertices) for f in obj.data.polygons]
        with self.assertRaises(ValueError):g.replace_mesh_geometry('Part',vertices,faces,units='m')
        g.replace_mesh_geometry('Part',vertices,faces,units='m',clear_vertex_groups=True)
        self.assertFalse(obj.vertex_groups)

    def test_surface_boundary_is_intentional(self):
        mesh=g.candidate_mesh('Surface',[[0,0,0],[1,0,0],[0,1,0]],[[0,1,2]],'m',False)
        obj=bpy.data.objects.new('Surface',mesh);bpy.context.scene.collection.objects.link(obj)
        self.assertTrue(g.validate_meshes(['Surface'])['valid'])
        self.assertFalse(g.validate_meshes(['Surface'],require_closed=True)['valid'])

    def test_zero_world_scale_is_degenerate(self):
        self.member();bpy.data.objects['Part'].scale=(0,0,0)
        self.assertFalse(g.validate_meshes(['Part'],require_closed=True)['valid'])

    def test_loose_vertices_rejected(self):
        self.member();obj=bpy.data.objects['Part'];old=obj.data
        vertices=[list(v.co) for v in old.vertices]+[[8,8,8]]
        faces=[list(f.vertices) for f in old.polygons]
        with self.assertRaises(ValueError):g.replace_mesh_geometry('Part',vertices,faces,units='m',require_closed=True)
        self.assertIs(obj.data,old)

    def test_packaged_addon_import_and_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            with ZipFile(ROOT/'dist/MTECBlenderBridge.zip') as archive:
                self.assertEqual(set(archive.namelist()),{
                    'mtec_blender_bridge/__init__.py','mtec_blender_bridge/mtec_geometry_tools.py',
                    'mtec_blender_bridge/mtec_codex_mcp_server.py','mtec_blender_bridge/setup_codex.py',
                    'mtec_blender_bridge/requirements.txt'})
                archive.extractall(directory)
            package=Path(directory)/'mtec_blender_bridge'
            spec=importlib.util.spec_from_file_location('mtec_packed_test',package/'__init__.py',submodule_search_locations=[str(package)])
            bridge=importlib.util.module_from_spec(spec);sys.modules[spec.name]=bridge
            try:
                spec.loader.exec_module(bridge)
                bridge.register()
                try:
                    result=bridge.TOOLS['create_profile_member']['func']('Packed',[0,0,0],[0,0,100])
                    self.assertTrue(result['validation']['valid'])
                finally:bridge.unregister()
            finally:
                for name in list(sys.modules):
                    if name.startswith('mtec_packed_test'):del sys.modules[name]

    def test_tool_registry_and_mcp_argument_parity(self):
        spec=importlib.util.spec_from_file_location('bridge_test',ROOT/'MTECBlenderBridge.py')
        bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
        import inspect
        functions={n.name:n for n in ast.parse((ROOT/'mtec_codex_mcp_server.py').read_text()).body if isinstance(n,ast.FunctionDef)}
        for name in ['validate_meshes','replace_mesh_geometry','create_profile_member']:
            self.assertIn(name,bridge.TOOLS)
            signature=list(inspect.signature(bridge.TOOLS[name]['func']).parameters)
            self.assertEqual(signature,[a.arg for a in functions[name].args.args])


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GeometryTests))
    if not result.wasSuccessful():raise RuntimeError('Geometry workflow tests failed')
