import bpy, math, random
from mathutils import Vector

random.seed(12)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for datablock in bpy.data.materials:
    bpy.data.materials.remove(datablock)

def mat(name, color, metallic=0, roughness=.4):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Metallic'].default_value=metallic; p.inputs['Roughness'].default_value=roughness
    return m
silver=mat('Polerat aluminium',(.69,.72,.74),.82,.23)
chrome=mat('Krom',(.78,.82,.84),.95,.13)
darksteel=mat('Mörkt stål',(.15,.16,.15),.7,.34)
rubber=mat('Svart gummi',(.035,.034,.032),.02,.82)
leather=mat('Slitet svart läder',(.065,.058,.052),.05,.72)
black=mat('Svart lack',(.025,.027,.027),.38,.31)
meshmat=mat('Tankemblem mörk metall',(.15,.145,.125),.55,.44)
red=mat('Baklykta röd',(.42,.015,.008),.1,.23)
glass=mat('Strålkastarglas',(.81,.83,.78),.16,.18)
gold=mat('Mässingsdetaljer',(.5,.39,.16),.75,.28)
ground=mat('Varmgrå studiobakgrund',(.30,.31,.30),0,.85)

def finish(o,name,material,smooth=True):
    o.name=name; o.data.materials.append(material)
    if smooth and o.type=='MESH':
        for p in o.data.polygons:p.use_smooth=True
    return o
def uv(name,loc,scale,material,segments=32,rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments,ring_count=rings,location=loc)
    o=bpy.context.object; o.scale=scale; return finish(o,name,material)
def cyl(name,a,b,r,material,verts=24,r2=None):
    a,b=Vector(a),Vector(b); d=b-a
    bpy.ops.mesh.primitive_cone_add(vertices=verts,radius1=r,radius2=r if r2 is None else r2,depth=d.length,location=(a+b)/2)
    o=bpy.context.object; o.rotation_euler=d.to_track_quat('Z','Y').to_euler()
    return finish(o,name,material)
def tube(name,points,r,material,cyclic=False,res=12):
    c=bpy.data.curves.new(name,'CURVE');c.dimensions='3D';c.resolution_u=24;c.bevel_depth=r;c.bevel_resolution=3
    s=c.splines.new('BEZIER');s.bezier_points.add(len(points)-1)
    for p,v in zip(s.bezier_points,points):p.co=v;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
    s.use_cyclic_u=cyclic;o=bpy.data.objects.new(name,c);bpy.context.collection.objects.link(o);o.data.materials.append(material);return o
def ring(name,x,y,z,rad,thick,material):
    pts=[(x+rad*math.cos(t*2*math.pi/64),y,z+rad*math.sin(t*2*math.pi/64)) for t in range(64)]
    return tube(name,pts,thick,material,True)
def panel(name,rings,material):
    n=len(rings[0]); verts=[v for r in rings for v in r];faces=[]
    for k in range(len(rings)-1):
        for j in range(n):faces.append((k*n+j,k*n+(j+1)%n,(k+1)*n+(j+1)%n,(k+1)*n+j))
    faces.append(tuple(reversed(range(n))));faces.append(tuple((len(rings)-1)*n+j for j in range(n)))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    o=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(o);finish(o,name,material)
    mod=o.modifiers.new('Mjuka kanter','BEVEL');mod.width=.012;mod.segments=2
    o.modifiers.new('Viktade normaler','WEIGHTED_NORMAL')
    return o

# Wheels lie in the XZ plane. Camera sees the near side at negative Y.
axles=[(-1.36,.55),(1.37,.55)]
for label,(x,z) in zip(('Fram','Bak'),axles):
    ring(label+' däck',x,0,z,.505,.083,rubber)
    ring(label+' slitbanans mitt',x,0,z,.51,.014,darksteel)
    for side in (-.061,.061):
        ring(label+' fälg',x,side,z,.416,.019,chrome)
        ring(label+' fälgkant',x,side,z,.439,.009,silver)
    cyl(label+' trumbroms',(x,-.105,z),(x,.105,z),.105,silver)
    cyl(label+' nav',(x,-.145,z),(x,.145,z),.066,chrome)
    for i in range(36):
        a=2*math.pi*i/36
        end=(x+.418*math.cos(a),(-.057 if i%2 else .057),z+.418*math.sin(a))
        start=(x+.065*math.cos(a+.28),(.12 if i%2 else -.12),z+.065*math.sin(a+.28))
        cyl(label+' eker %02d'%i,start,end,.0032,chrome,8)
    # Tiny offset shoulder around the tire makes the vintage ribbed profile legible.
    for side in (-.077,.077):ring(label+' däcksida',x,side,z,.49,.019,rubber)

# Pressed steel fenders, arced over the tire circumference.
def fender(name,x,z,a0,a1,material,width=.25):
    verts=[];N=48
    for y in (-width/2,width/2):
        for i in range(N+1):
            a=a0+(a1-a0)*i/N;verts.append((x+.575*math.cos(a),y,z+.575*math.sin(a)))
    faces=[(i,i+1,N+2+i,N+1+i) for i in range(N)]
    m=bpy.data.meshes.new(name);m.from_pydata(verts,[],faces);m.update();o=bpy.data.objects.new(name,m);bpy.context.collection.objects.link(o);finish(o,name,material)
    q=o.modifiers.new('Skärmens plåt','SOLIDIFY');q.thickness=.018
    q=o.modifiers.new('Rundad kant','BEVEL');q.width=.016;q.segments=2
    for y in (-width/2,width/2):
        pts=[(x+.575*math.cos(a0+(a1-a0)*i/32),y,z+.575*math.sin(a0+(a1-a0)*i/32)) for i in range(33)]
        tube(name+' kant',pts,.009,chrome)
fender('Framskärm',-1.36,.55,.24,math.pi-.17,silver)
fender('Bakskärm',1.37,.55,.48,2.55,silver,.30)
for y in (-.14,.14):
    tube('Framskärmsstag',[(-1.36,y,.55),(-1.29,y,.73),(-1.16,y,.96)],.009,chrome)
    tube('Bakskärmsstag',[(1.37,y,.55),(1.55,y,.75),(1.72,y,1.02)],.009,chrome)

# Front forks and steering head.
for y in (-.105,.105):
    cyl('Framgaffel krom',(-1.36,y,.55),(-1.00,y,1.70),.033,chrome)
    cyl('Framgaffel damask',(-1.28,y,.81),(-1.13,y,1.30),.044,rubber)
    for i in range(8):
        z=.86+i*.055;x=-1.36+(z-.55)*.313
        ring('Gaffeldamask veck',x,y,z,.047,.007,darksteel)
    cyl('Övre gaffelben',(-1.03,y,1.59),(-.96,y,1.79),.042,silver)
for z in (1.63,1.77):cyl('Gaffelkrona',(-1.02,-.21,z),(-1.02,.21,z),.04,silver)
tube('Styre',[(-1.00,-.44,1.88),(-.94,-.28,1.91),(-.94,.28,1.91),(-1.00,.44,1.88)],.016,chrome)
for y in (-.48,.48):cyl('Handtag',(-1.00,y,1.88),(-1.00,y+(-.14 if y<0 else .14),1.88),.026,rubber)
uv('Strålkastarhus',(-1.15,-.015,1.65),(.15,.16,.15),chrome)
uv('Strålkastarglas',(-1.258,-.015,1.65),(.041,.122,.122),glass)
ring('Strålkastarring',-1.265,-.015,1.65,.124,.013,chrome)
tube('Lamphållare',[(-1.08,-.09,1.64),(-.99,-.09,1.59)],.013,darksteel)

# Rigid triangular main frame, visible behind tank and engine.
for y in (-.16,.16):
    tube('Ram övre', [(-.98,y,1.60),(-.58,y,1.46),(.43,y,1.39),(.76,y,1.20)],.024,darksteel)
    tube('Ram diagonal',[(-.97,y,1.59),(-.72,y,1.12),(-.44,y,.60),(.28,y,.52)],.022,darksteel)
    tube('Ram undervagga',[(-.44,y,.60),(-.19,y,.36),(.58,y,.38),(1.37,y,.55)],.023,darksteel)
    tube('Bakram övre',[(.58,y,1.19),(.97,y,1.11),(1.37,y,.55)],.021,darksteel)
    tube('Bakram diagonal',[(.47,y,.48),(.73,y,.96),(.97,y,1.11)],.017,darksteel)

# Sculpted teardrop tank: each cross section is elliptical and narrows at the tail.
tank_sections=[(-.80,.99,.065,.055),(-.72,1.11,.24,.19),(-.49,1.16,.31,.245),(-.15,1.15,.325,.25),(.19,1.13,.27,.22),(.43,1.13,.15,.14),(.54,1.12,.025,.035)]
rings=[]
for x,zc,w,h in tank_sections:
    rings.append([(x,w*math.cos(2*math.pi*j/32),zc+h*math.sin(2*math.pi*j/32)) for j in range(32)])
panel('Handformad droppformad bensintank',rings,silver)
cyl('Tanklock',(-.43,0,1.407),(-.43,0,1.444),.067,chrome)
ring('Tanklock kant',-.43,0,1.44,.065,.005,darksteel)
for y in (-1,1):
    yy=y*.305
    uv('Tankens svarta sidopanel',(-.26,yy,1.113),(.297,.021,.113),black)
    uv('Tankemblem',(-.27,yy+y*.025,1.118),(.155,.012,.066),meshmat)
    uv('Emblem mässing',(-.27,yy+y*.04,1.118),(.027,.013,.031),gold)
    for z in (1.21,1.232,1.254):
        tube('Tanksida rand',[(-.69,yy*.65,z),(-.51,yy*.93,z),(-.36,yy,z)],.006,darksteel)

# Single cylinder with individually modelled cooling fins.
uv('Vevhus',(-.13,-.015,.64),(.38,.245,.225),silver)
uv('Vänster växellådskåpa',(.11,-.213,.45),(.43,.066,.20),silver)
uv('Rund kopplingskåpa',(.30,-.282,.45),(.203,.043,.17),chrome)
uv('Främre liten kåpa',(-.27,-.284,.45),(.105,.04,.105),silver)
cyl('Cylinder',(-.31,-.005,.70),(-.31,-.005,1.05),.165,darksteel)
for i in range(9):
    z=.75+i*.037
    cyl('Kylfläns %02d'%i,(-.31,-.006,z),(-.31,-.006,z+.011),.205 if i<6 else .18,silver,32)
uv('Cylinderhuvud',(-.31,-.008,1.087),(.22,.19,.075),silver)
for i in range(4):
    cyl('Topplock fläns',(-.49+i*.115,-.01,1.13),(-.49+i*.115,-.01,1.15),.045,silver)
uv('Tändstift',(-.25,-.11,1.19),(.029,.026,.038),glass)
tube('Tändkabel',[(-.25,-.11,1.22),(-.34,-.15,1.27),(-.51,-.16,1.16)],.008,rubber)
for p in [(-.32,-.29,.46),(-.05,-.29,.55),(.40,-.29,.47)]:
    cyl('Kåpans bult',(p[0],p[1]-.007,p[2]),(p[0],p[1]-.019,p[2]),.012,darksteel,12)

# Carburettor and separate air box.
uv('Förgasare',(.04,-.07,.91),(.095,.09,.105),silver)
cyl('Insug',(-.17,-.06,.99),(.02,-.06,.93),.047,darksteel)
uv('Rund luftburk',(.40,-.20,.82),(.18,.075,.18),silver)
cyl('Luftburkens mitt',(.40,-.288,.82),(.40,-.31,.82),.034,darksteel)
tube('Luftslang',[(.15,-.07,.91),(.24,-.13,.88),(.30,-.17,.85)],.038,rubber)

# Solo saddle, stitched rim and exposed springs.
seat_sections=[(.37,1.25,.16,.012),(.46,1.27,.255,.055),(.74,1.31,.285,.06),(1.04,1.30,.24,.04),(1.16,1.29,.09,.015)]
seat_rings=[]
for x,zc,w,h in seat_sections:
    seat_rings.append([(x,w*math.cos(2*math.pi*j/24),zc+h*math.sin(2*math.pi*j/24)) for j in range(24)])
panel('Svart solosadel',seat_rings,leather)
for y in (-.205,.205):
    tube('Sadelns sydda kant',[(.43,y*.72,1.28),(.61,y,1.31),(.92,y*.94,1.325),(1.12,y*.55,1.295)],.006,darksteel)
    x=.78
    cyl('Sadel fjäder kärna',(x,y,.97),(x,y,1.245),.018,darksteel)
    pts=[(x+.054*math.cos(t),y+.054*math.sin(t),.97+.27*t/(10*math.pi)) for t in [i*10*math.pi/100 for i in range(101)]]
    tube('Sadel spiralfjäder',pts,.009,chrome)
    cyl('Fjäderfäste',(x,y,.965),(x,y,.99),.066,darksteel)

# Rear suspension and chain drive.
for y in (-.16,.16):
    cyl('Bakre stötdämpare',(.92,y,1.07),(1.18,y,.69),.043,chrome)
    for i in range(7):
        x=.965+i*.026;z=1.0-i*.05
        uv('Stötdämparfjäder', (x,y,z),(.037,.052,.011),silver,16,8)
for x,z,r in ((.18,.49,.19),(1.37,.55,.13)):
    ring('Kedjedrev',x,-.18,z,r,.014,darksteel)
tube('Övre kedjelopp',[(.18,-.19,.68),(.65,-.19,.665),(1.37,-.19,.68)],.010,darksteel)
tube('Undre kedjelopp',[(.18,-.19,.30),(.65,-.19,.35),(1.37,-.19,.42)],.010,darksteel)
tube('Kedjeskydd',[(.29,-.205,.72),(.87,-.205,.71),(1.23,-.205,.68)],.026,silver)

# Two part chrome exhaust: pipe bends round engine into low straight silencer.
tube('Avgaskrök',[(-.38,-.30,1.095),(-.48,-.35,.93),(-.49,-.38,.69),(-.32,-.39,.39),(.14,-.39,.27),(.70,-.39,.25)],.036,chrome)
cyl('Lång ljuddämpare',(.46,-.39,.255),(1.81,-.39,.255),.052,chrome,32,r2=.062)
cyl('Ljuddämparände',(1.79,-.39,.255),(1.89,-.39,.255),.054,darksteel)
for x in (.61,1.22):tube('Ljuddämparfäste',[(x,-.39,.31),(x,-.19,.49)],.012,darksteel)

# Pedal, footrest, kickstarter, brake rods and small controls.
cyl('Fotpinne',(.24,-.17,.37),(.24,-.48,.37),.024,rubber)
tube('Växelpedal',[(.04,-.25,.42),(-.08,-.43,.40)],.013,chrome)
cyl('Växelpedal gummi',(-.09,-.43,.40),(-.13,-.50,.40),.024,rubber)
tube('Kickstart',[(.35,-.30,.42),(.46,-.41,.51),(.50,-.45,.63)],.018,chrome)
cyl('Kickstart gummi',(.49,-.45,.63),(.67,-.45,.63),.026,rubber)
tube('Bakbromsstag',[(.32,-.27,.43),(.87,-.24,.45),(1.31,-.19,.54)],.008,chrome)
tube('Sidostöd',[(.06,-.17,.38),(-.23,-.30,.06)],.020,darksteel)

# Position the single cylinder and its cases farther forward under the tank.
engine_names={'Vevhus','Vänster växellådskåpa','Rund kopplingskåpa','Främre liten kåpa','Cylinder','Cylinderhuvud','Tändstift','Förgasare','Insug'}
for obj in bpy.data.objects:
    if obj.name in engine_names or obj.name.startswith(('Kylfläns','Topplock fläns','Kåpans bult','Tändkabel')):
        obj.location.x-=.10
        if obj.name=='Cylinder' or obj.name.startswith('Kylfläns'):
            obj.scale.x*=1.12
for pt in bpy.data.objects['Avgaskrök'].data.splines[0].bezier_points[:2]:
    pt.co.x-=.10
    pt.handle_left_type='AUTO';pt.handle_right_type='AUTO'

# Rear lamp and inclined registration plate.
uv('Baklyktehus',(1.78,0,1.19),(.085,.072,.06),silver)
uv('Baklykteglas',(1.857,0,1.19),(.030,.055,.05),red)
def plate():
    vs=[(1.83,-.155,1.08),(1.83,.155,1.08),(1.97,.155,.88),(1.97,-.155,.88)]
    mesh=bpy.data.meshes.new('Skylt');mesh.from_pydata(vs,[],[(0,1,2,3)]);mesh.update()
    o=bpy.data.objects.new('Registreringsskylt',mesh);bpy.context.collection.objects.link(o);o.data.materials.append(glass)
    m=o.modifiers.new('Tunn plåt','SOLIDIFY');m.thickness=.008
plate()

# Simple photographic studio presentation.
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,.042));finish(bpy.context.object,'Mark',ground)
world=bpy.context.scene.world or bpy.data.worlds.new('Studio')
bpy.context.scene.world=world;world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Color'].default_value=(.42,.45,.48,1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value=.55
def area(name,loc,power,size,target):
    d=bpy.data.lights.new(name,'AREA');d.energy=power;d.shape='DISK';d.size=size
    o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=loc
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
area('Stor mjukbox',(-3.5,-4,5),850,4,(0,0,.8))
area('Kantljus',(2,2.5,4),1000,3,(0,0,1))
camd=bpy.data.cameras.new('Kamera');cam=bpy.data.objects.new('Kamera',camd);bpy.context.collection.objects.link(cam)
cam.location=(-3.25,-6.9,2.35);target=Vector((.22,0,.94));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();camd.type='ORTHO';camd.ortho_scale=4.75
scene=bpy.context.scene;scene.camera=cam
scene.use_nodes=False
scene.render.engine='CYCLES';scene.cycles.samples=32
scene.render.resolution_x=1500;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
scene.view_settings.view_transform='AgX'
for name in ('Handformad droppformad bensintank','Svart solosadel'):
    obj=bpy.data.objects[name]
    sub=obj.modifiers.new('Mjukare form','SUBSURF');sub.levels=2;sub.render_levels=2
    obj.modifiers.move(len(obj.modifiers)-1,0)
leather_bsdf=leather.node_tree.nodes['Principled BSDF']
leather_bsdf.inputs['Base Color'].default_value=(.012,.009,.007,1)
leather_bsdf.inputs['Metallic'].default_value=0
leather_bsdf.inputs['Roughness'].default_value=1
leather_bsdf.inputs['Specular IOR Level'].default_value=0
leather.diffuse_color=(.012,.009,.007,1)
scene.render.image_settings.file_format='PNG'
scene.render.filepath=r'D:\PythonProjects\BlenderMCP\bsa_500_render.png'
bpy.ops.wm.save_as_mainfile(filepath=r'D:\PythonProjects\BlenderMCP\bsa_500_custom.blend')
print('BSA_MODEL_DONE objects=',len(bpy.data.objects))
