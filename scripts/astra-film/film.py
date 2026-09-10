"""Build the editable, photo-grounded Connected Gallery film in Blender 5.2.

Blender --background --python scripts/astra-film/film.py -- --mode build
No model calls, generated photographs, network requests, or private photographs.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "docs/presentations/astra-film"
OUT = ROOT / "outputs/astra-film"
SHEET = ROOT / "docs/presentations/agent-loop/assets/gallery.png"
FPS, LENGTH = 24, 54
COLORS = {
    "paper": (0.95, 0.92, 0.85, 1), "cream": (0.78, 0.73, 0.62, 1),
    "blue": (0.012, 0.048, 0.50, 1), "ink": (0.024, 0.030, 0.029, 1),
    "amber": (0.59, 0.28, 0.055, 1), "date": (0.24, 0.20, 0.13, 1),
    "muted": (0.17, 0.18, 0.16, 1), "white": (1, 1, 1, 1),
}
NAMES = ["집 식탁", "식당", "매장", "거리", "카페", "바닷가"]
DATES = {0: "2026.08.29", 1: "2026.06.14", 3: "2026.06.14", 4: "2026.06.14", 5: "2026.04.18"}
LABELS = {0: (.39, .47, .59, .88), 1: (.11, .55, .32, .93), 2: (.40, .42, .61, .81)}
FACES = {1: (.48, .04, .87, .60), 3: (.30, .08, .72, .65), 5: (.27, .07, .71, .71)}

# Every entry is a public action fixture, not an actual model decision or run.
SPECS = [
    ("S01", 0, 1.5, "intro", "이 와인, 어디서 봤더라?", "사진 한 장에서 시작합니다", 0, [0]),
    ("S02", 1.5, 3, "select_wine", "이 와인, 어디서 봤더라?", "궁금한 대상을 선택", 0, [0]),
    ("S03", 3, 4, "search", "눈앞의 단서로 찾기", "선택한 와인으로 요청", 0, [0]),
    ("S04", 4, 5, "tokens", "후보가 돌아옵니다", "아직 확인하지 않은 후보", 0, []),
    ("S05", 5, 6, "inspect_request", "이번에는 직접 봅니다", "후보의 사진을 요청", 0, []),
    ("S06", 6, 8, "observe", "사진을 펼쳐봅니다", "관찰한 뒤 독립 검토로", 0, [4, 3]),
    ("S07", 8, 10, "review_reject", "선택한 라벨을 확인할 수 없음", "원본과 후보를 따로 비교", 0, [0, 4]),
    ("S08", 10, 12, "review_reject", "선택한 라벨을 확인할 수 없음", "두 후보 모두 와인 연결 근거 부족", 0, [0, 3]),
    ("S09", 12, 14, "feedback", "단서를 더 구체적으로", "붉은 원 라벨의 와인병", 0, [0, 4, 3]),
    ("S10", 14, 15, "search_refined", "같은 와인, 더 구체적인 단서", "붉은 원 라벨의 와인병", 0, [0]),
    ("S11", 15, 16, "tokens_new", "새 후보도 직접 확인합니다", "목록을 받은 뒤 사진 확인 요청", 0, []),
    ("S12", 16, 18, "observe", "다른 장면에서 찾은 단서", "이미지를 관찰한 뒤 제출", 0, [1, 2]),
    ("S13", 18, 20, "review_label", "붉은 원이 있는 크림색 라벨", "원본과 식당 사진을 비교", 0, [0, 1]),
    ("S14", 20, 21.5, "review_label", "붉은 원이 있는 크림색 라벨", "원본과 매장 사진을 비교", 0, [0, 2]),
    ("S15", 21.5, 23, "results", "붉은 원 라벨이 보이는 장면", "확인된 사진에 읽을 순서를", 0, [1, 2]),
    ("S16", 23, 25, "open_restaurant", "사진을 열면, 함께 볼 이유까지.", "이제 식당 사진 전체가 기준", 1, [1]),
    ("S17", 25, 26.5, "context_tokens", "사진 전체를 살펴봅니다", "새 기준에서 후보를 확보하고 관찰", 1, [1]),
    ("S18", 26.5, 28.5, "context_observe", "다시 만난 거리와 카페", "새 맥락의 후보로 전체 사진을 확인", 1, [1, 3, 4]),
    ("S19a", 28.5, 29.75, "context_review", "같은 데모 설정 날짜 · 2026.06.14", "식당과 거리의 사진·날짜·설명을 확인", 1, [1, 3]),
    ("S19b", 29.75, 31, "context_review", "같은 데모 설정 날짜 · 2026.06.14", "식당과 카페도 별도로 확인", 1, [1, 4]),
    ("S20", 31, 33, "context_restaurant", "와인이 없어도, 함께 볼 이유", "같은 데모 설정 날짜 · 2026.06.14", 1, [1, 3, 4]),
    ("S21", 33, 35, "select_person", "이번에는, 이 사람의 다른 날.", "사용자의 새로운 선택", 1, [1]),
    ("S22", 35, 36, "person_tokens", "새 관심에서 다시 시작", "선택한 사람으로 요청 → 후보 → 사진 확인", 1, [1]),
    ("S23", 36, 37, "observe", "다른 장면의 사람을 봅니다", "이미지를 받은 뒤 독립 검토로", 1, [3, 5]),
    ("S24a", 37, 38, "review_person", "선택한 사람을 원본과 비교", "거리 사진의 인물을 확인", 1, [1, 3]),
    ("S24b", 38, 39, "review_person", "선택한 사람을 원본과 비교", "바닷가 사진도 따로 확인", 1, [1, 5]),
    ("S24c", 39, 40.5, "results", "이 사람이 보이는 장면", "관계와 설명을 확인한 뒤 정리", 1, [3, 5]),
    ("S25", 40.5, 43, "open_beach", "", "", 5, [5]),
    ("S26", 43, 44.5, "beach_tokens", "도착한 사진에서, 새로운 맥락", "바닷가 사진 전체가 새로운 기준", 5, [5]),
    ("S27", 44.5, 46, "context_observe", "다른 날의 장면을 다시 살펴봅니다", "새로 확보한 식당·거리의 전체 사진 확인", 5, [5, 1, 3]),
    ("S28a", 46, 47, "context_review", "이 사람이 보이는 다른 장면", "바닷가와 식당의 사진·설명을 독립 확인", 5, [5, 1]),
    ("S28b", 47, 48, "context_review", "이 사람이 보이는 다른 장면", "거리도 새 기준에서 별도로 확인", 5, [5, 3]),
    ("S29", 48, 50, "context_beach", "이 사람이 보이는 다른 장면", "데모 설정 날짜 · 바닷가 04.18 / 식당·거리 06.14", 5, [5, 1, 3]),
    ("S30", 50, 51.5, "path", "", "작은 단서에서 이어진 장면들", 5, [0, 1, 2, 3, 4, 5]),
    ("S31", 51.5, 54, "end", "", "", None, []),
]

SHOTS = []
for ident, a, b, kind, title, detail, anchor, photos in SPECS:
    SHOTS.append(dict(id=ident, start=a, end=b, first=round(a * FPS) + 1,
                      last=round(b * FPS), kind=kind, title=title, detail=detail,
                      anchor=anchor, photos=photos))

CURRENT = None
CAM = None
MATS = {}
PHOTO_MATS = {}
FONTS = {}


def mat(name, color, rough=.45, metal=0., emission=False, transmission=0.):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = color
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    if emission:
        # Film type should retain contrast independently of specular stage light.
        ink = m.node_tree.nodes.new('ShaderNodeEmission')
        ink.inputs['Color'].default_value = color
        ink.inputs['Strength'].default_value = 1
        m.node_tree.links.new(ink.outputs[0], m.node_tree.nodes.get('Material Output').inputs['Surface'])
    if transmission:
        p.inputs['Transmission Weight'].default_value = transmission
        p.inputs['IOR'].default_value = 1.46
    return m


def add_noise(m, scale, strength, distance):
    n = m.node_tree.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = 2
    bump = m.node_tree.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = strength
    bump.inputs['Distance'].default_value = distance
    m.node_tree.links.new(n.outputs['Fac'], bump.inputs['Height'])
    m.node_tree.links.new(bump.outputs['Normal'], m.node_tree.nodes.get('Principled BSDF').inputs['Normal'])


def relink(obj):
    if CURRENT:
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        CURRENT.objects.link(obj)
    return obj


def empty(name, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None)
    (CURRENT or bpy.context.scene.collection).objects.link(o)
    o.location = loc
    return o


def parent(obj, root, loc=(0, 0, 0)):
    obj.parent = root
    obj.location = loc
    return obj


def cube(name, loc, size, material, bevel=.05, root=None):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = relink(bpy.context.object)
    o.name = name
    o.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if root:
        parent(o, root, loc)
    else:
        o.location = loc
    o.data.materials.append(material)
    if bevel:
        mod = o.modifiers.new('Soft physical edges', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
        o.modifiers.new('Corner normals', 'WEIGHTED_NORMAL')
    return o


def sphere(name, loc, scale, material, root=None, segments=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=20)
    o = relink(bpy.context.object)
    o.name = name
    o.scale = scale
    if root:
        parent(o, root, loc)
    else:
        o.location = loc
    o.data.materials.append(material)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def tube(name, coords, radius, material, root=None, cyclic=False):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.resolution_u = 12
    data.bevel_depth = radius
    data.bevel_resolution = 3
    s = data.splines.new('BEZIER')
    s.bezier_points.add(len(coords) - 1)
    for point, co in zip(s.bezier_points, coords):
        point.co = co
        point.handle_left_type = point.handle_right_type = 'VECTOR' if cyclic else 'AUTO'
    s.use_cyclic_u = cyclic
    o = bpy.data.objects.new(name, data)
    (CURRENT or bpy.context.scene.collection).objects.link(o)
    if root:
        parent(o, root)
    data.materials.append(material)
    return o


def text(name, value, size, pos, material, root=None, bold=False, align='LEFT'):
    c = bpy.data.curves.new(name, 'FONT')
    c.body, c.size, c.align_x = value, size, align
    c.font = FONTS['bold' if bold else 'regular']
    c.space_character = 1.06
    c.resolution_u = 6
    c.extrude = .0002
    o = bpy.data.objects.new(name, c)
    (CURRENT or bpy.context.scene.collection).objects.link(o)
    if root:
        parent(o, root, pos)
    else:
        o.location = pos
    c.materials.append(material)
    o['editable_text'] = value
    return o


def hud(value, x, y, pixels=36, color='ink', bold=False, align='LEFT'):
    # Camera-local film typography. 0,0 top left; camera field of view fixed.
    dist = 8
    width = dist * CAM.data.sensor_width / CAM.data.lens
    height = width * 9 / 16
    return text('Film typography / ' + value[:30], value, height * pixels / 1080,
                ((x - .5) * width, (.5 - y) * height, -dist),
                MATS['text_' + color], CAM, bold or color == 'muted', align)


def key(obj, prop, frame, value):
    setattr(obj, prop, value)
    obj.keyframe_insert(data_path=prop, frame=frame)


def move(obj, shot, start, end, seconds=.5, delay=0.):
    a = shot['first'] + round(delay * FPS)
    b = min(shot['last'], a + max(1, round(seconds * FPS)))
    key(obj, 'location', a, start)
    key(obj, 'location', b, end)


def show_between(obj, first, last):
    for f, hide in [(0, True), (first - 1, True), (first, False), (last, False), (last + 1, True)]:
        key(obj, 'hide_render', f, hide)
        key(obj, 'hide_viewport', f, hide)


def show_group(root, shot, after=0., until=None):
    objects = [root] + list(root.children_recursive)
    for o in objects:
        o['_appear'] = after
        if until is not None:
            o['_until'] = until


def photo_material(pid, crop=None):
    cache = (pid, tuple(crop) if crop else None)
    if cache in PHOTO_MATS:
        return PHOTO_MATS[cache]
    m = mat('Photo %s / %s' % cache, (1, 1, 1, 1), rough=.84)
    ns, links = m.node_tree.nodes, m.node_tree.links
    p = ns.get('Principled BSDF')
    uv = ns.new('ShaderNodeTexCoord')
    mapping = ns.new('ShaderNodeVectorMath')
    mapping.operation = 'MULTIPLY_ADD'
    x0, y0, x1, y1 = crop or (0, 0, 1, 1)
    # Crop coordinates are top-down within the unchanged 3x2 sheet.
    mapping.inputs[1].default_value = ((x1-x0)/3, (y1-y0)/2, 1)
    mapping.inputs[2].default_value = ((pid % 3+x0)/3, (1-(pid//3+1)/2)+(1-y1)/2, 0)
    im = ns.new('ShaderNodeTexImage')
    im.image = bpy.data.images.get('Original six-photo sheet')
    im.interpolation = 'Linear'
    im.extension = 'EXTEND'
    links.new(uv.outputs['UV'], mapping.inputs[0])
    links.new(mapping.outputs['Vector'], im.inputs['Vector'])
    # Lightly self-lit photographic prints retain evidence through warm lighting.
    diffuse = ns.new('ShaderNodeMixRGB')
    diffuse.blend_type = 'MULTIPLY'
    diffuse.inputs[0].default_value = 1
    diffuse.inputs[2].default_value = (.12,.12,.12,1)
    links.new(im.outputs['Color'], diffuse.inputs[1])
    links.new(diffuse.outputs[0], p.inputs['Base Color'])
    links.new(im.outputs['Color'], p.inputs['Emission Color'])
    p.inputs['Emission Strength'].default_value = 1.0
    p.inputs['Specular IOR Level'].default_value = .12
    PHOTO_MATS[cache] = m
    return m


def card(pid, pos, width, shot, crop=None, label=True, tilt=-.20, yaw=0., name='Photo'):
    ratio = 4/3 if crop is None else (crop[2]-crop[0])/(crop[3]-crop[1])*4/3
    ph = width/ratio
    margin = .08
    root = empty('%s / %s / photo %d' % (shot['id'], name, pid), pos)
    root.rotation_euler = (tilt, 0, yaw)
    root['photo_id'] = pid
    root['whole_image'] = crop is None
    root['crop'] = list(crop or (0,0,1,1))
    root['shot'] = shot['id']
    cube('Cotton paper / real thickness', (0,0,0), (width+margin*2,.065,ph+margin*2+.14), MATS['paper'], .035, root)
    # Front UV plane has +U right, +V up and its normal toward the camera.
    mesh = bpy.data.meshes.new('Photograph surface')
    mesh.from_pydata([(-width/2,-.041,-ph/2+.05), (width/2,-.041,-ph/2+.05),
                       (width/2,-.041,ph/2+.05), (-width/2,-.041,ph/2+.05)], [], [(0,1,2,3)])
    mesh.uv_layers.new()
    for loop, uv in zip(mesh.uv_layers.active.data, [(0,0),(1,0),(1,1),(0,1)]):
        loop.uv = uv
    o = bpy.data.objects.new('Actual image / %d' % pid, mesh)
    CURRENT.objects.link(o)
    parent(o, root)
    mesh.materials.append(photo_material(pid,crop))
    if label:
        t = text('Photo label', NAMES[pid], .19, (-width/2,-.053,-ph/2-.105), MATS['text_muted'], root)
        t.rotation_euler = (math.pi/2,0,0)
    return root


def blank(pos, shot, width=1.4, index=0):
    root = empty('Unobserved candidate token', pos)
    root.rotation_euler.x = -.2
    root['is_candidate_token'] = True
    cube('Opaque candidate back', (0,0,0), (width,.12,width*.76), MATS['token'], .08, root)
    for j in range(3):
        sphere('Information pip', ((j-1)*.22,-.077,0), (.045,.024,.045), MATS['blue'], root,16)
    return root


def rectangle(root, box, width, height, material, radius=.022, offset=-.09):
    x0,y0,x1,y1 = box
    x0,x1=(x0-.5)*width,(x1-.5)*width
    z0,z1=(.5-y0)*height+.05,(.5-y1)*height+.05
    return tube('Selection boundary', [(x0,offset,z0),(x1,offset,z0),(x1,offset,z1),(x0,offset,z1)], radius,material,root,True)


def cursor_on(root, pos, shot, after=.0):
    cu=empty('USER / pointer tap')
    parent(cu,root,pos)
    verts=[(0,0,0),(0,0,-.42),(.105,0,-.32),(.22,0,-.51),(.31,0,-.46),(.195,0,-.27),(.36,0,-.27)]
    me=bpy.data.meshes.new('Pointer silhouette')
    me.from_pydata(verts,[],[tuple(range(len(verts)))])
    ob=bpy.data.objects.new('User pointer / white',me)
    CURRENT.objects.link(ob);parent(ob,cu)
    me.materials.append(MATS['text_white'])
    tube('Pointer dark edge',verts,.014,MATS['text_ink'],cu,True)
    start=Vector(pos)+Vector((.5,-.025,-.4))
    move(cu,shot,start,pos,.20,after)
    key(cu,'scale',shot['first']+round((after+.2)*FPS),(1,1,1))
    key(cu,'scale',shot['first']+round((after+.3)*FPS),(.78,.78,.78))
    key(cu,'scale',shot['first']+round((after+.45)*FPS),(1,1,1))
    show_group(cu,shot,after,after+.6)


def tendril(root, side, tip, material):
    start=Vector((side*.55,-.10,-.18))
    end=Vector(tip)
    tube('Reaching arm', [start, start+Vector((side*.25,-.20,-.30)),
                         end+Vector((-side*.2,.08,-.12)), end], .055, material, root)
    sphere('Contact fingertip',end,(.13,.10,.17),material,root)


def explorer(pos, shot, target=None, scale=1., carry=None):
    root=empty('Explorer / embodied action',pos)
    root.scale=(scale,scale,scale)
    body=sphere('Explorer / blue organic body',(0,0,0),(1,.67,1),MATS['blue'],root,64)
    for v in body.data.vertices:
        x,y,z=v.co
        phi=math.atan2(z,x)
        rad=1+.24*math.cos(phi*5+.42)*(math.hypot(x,z)**3)
        v.co=(x*rad,y*rad,z*rad)
    body.rotation_euler.y=-.08
    end=Vector(target)-Vector(pos) if target is not None else Vector((1.25,-.25,.45))
    end/=scale
    tendril(root,1,end,MATS['blue'])
    tendril(root,-1,(-.85,-.22,-.6),MATS['blue'])
    # One action with a settling hold; no indefinite spinning or floating.
    f=shot['first'];d=min(16,shot['last']-f)
    key(body,'rotation_euler',f,(0,-.16,-.06))
    key(body,'rotation_euler',f+d,(0,.09,.02))
    key(body,'scale',f,(1,.67,1))
    key(body,'scale',f+max(2,d//2),(1.06,.69,.93))
    key(body,'scale',f+d,(1,.67,1))
    if carry:
        move(root,shot,Vector(pos)+Vector(carry),pos,.45)
    return root


def reviewer(pos, shot, width=1., target=None):
    root=empty('Reviewer / independent comparison',pos)
    root.scale=(width,width,width)
    bpy.ops.mesh.primitive_torus_add(major_segments=64,minor_segments=20,major_radius=.63,minor_radius=.185)
    ring=relink(bpy.context.object);ring.name='Reviewer / thick amber glass'
    parent(ring,root);ring.rotation_euler=(math.pi/2,0,0)
    ring.data.materials.append(MATS['glass'])
    for p in ring.data.polygons:p.use_smooth=True
    bpy.ops.mesh.primitive_torus_add(major_segments=64,minor_segments=12,major_radius=.60,minor_radius=.026)
    edge=relink(bpy.context.object);parent(edge,root,(0,-.145,0));edge.rotation_euler=(math.pi/2,0,0)
    edge.data.materials.append(MATS['amber_edge'])
    tendril(root,-1,(-.94,-.06,-.34),MATS['glass'])
    tendril(root,1,(.94,-.06,-.34),MATS['glass'])
    f=shot['first'];end=min(shot['last'],f+18)
    key(root,'rotation_euler',f,(0,-.12,-.11))
    key(root,'rotation_euler',f+max(2,(end-f)//2),(0,.08,.08))
    key(root,'rotation_euler',end,(0,0,0))
    return root


def organizer(pos,shot,spread=True):
    root=empty('Organizer / arrange reviewed photos',pos)
    for i in range(3):
        end=((i-1)*.76,0,0 if spread else i*.32)
        stone=sphere('Organizer / charcoal river stone',end,(.66,.42,.23),MATS['stone'],root)
        stone.rotation_euler=(.02,(i-1)*.15,(i-1)*.16)
        if spread:move(stone,shot,(0,0,(i-1)*.35+.30),end,.35)
    return root


def tool(shot,pos=(3.9,.4,.42)):
    root=empty('Tool / quiet physical slot',pos)
    cube('Tool ceramic housing',(0,0,0),(2.2,1.4,.6),MATS['ceramic'],.18,root)
    cube('Request-response slot',(0,-.55,.23),(1.5,.12,.07),MATS['ink'],.018,root)
    for j in range(3):sphere('Slot light',((j-1)*.18,-.70,-.02),(.025,.022,.025),MATS['amber_edge'],root,16)
    return root


def relation(a,b,shot,color='blue',after=.4,tag=None):
    a,b=Vector(a),Vector(b)
    delta=b-a
    bend=(a+b)/2+Vector((0,-.1,-.25))
    ob=tube('Verified relationship / '+color,[a,bend,b],.020,MATS[color])
    ob['relationship_kind']=color
    ob['verified_after']=after
    ob.data.bevel_factor_end=0
    ob.data.keyframe_insert(data_path='bevel_factor_end',frame=shot['first']+round(after*FPS))
    ob.data.bevel_factor_end=1
    ob.data.keyframe_insert(data_path='bevel_factor_end',frame=min(shot['last'],shot['first']+round((after+.25)*FPS)))
    return ob


def seal(root,shot,after,passed=True):
    sign=empty('Claim status / checked' if passed else 'Claim status / unsupported')
    parent(sign,root,(0,-.12,0))
    # Kept at the lower paper border, outside all photo evidence.
    width=next(c.dimensions.x for c in root.children if c.type=='MESH' and 'Cotton paper' in c.name)
    ph=width*.75
    x,z=width*.43,-ph/2-.08
    m=MATS['blue'] if passed else MATS['amber_edge']
    if passed:tube('Confirmed mark',[(x-.13,0,z),(x-.035,0,z-.08),(x+.14,0,z+.13)],.022,m,sign)
    else:tube('Unsupported mark',[(x-.12,0,z),(x+.12,0,z)],.022,m,sign)
    show_group(sign,shot,after)


def stage(scene):
    cube('Atelier / seamless floor',(0,3,-.5),(160,160,.3),MATS['floor'],.08)
    cube('Atelier / warm plaster backdrop',(0,11,7),(90,.35,17),MATS['floor'],.10)
    cube('Atelier / travertine worktop',(0,1,-.20),(19,9,.30),MATS['travertine'],.24)
    cube('Atelier / rear ledge',(0,8,.65),(40,1.5,1.1),MATS['floor'],.22)
    for x in [-10.7,11.1]:
        cube('Atelier / architectural pier',(x,6,4.2),(.35,1.2,9.3),MATS['cream'],.07)
    # A small real plant remains peripheral; it supplies soft physical shadows.
    for x,y in [(-9,3.4),(10.7,5.3)]:
        sphere('Stone planter',(x,y,.4),(.65,.65,.75),MATS['travertine'])
        for j in range(7):
            angle=j*2.399
            top=Vector((x+math.cos(angle)*.7,y+math.sin(angle)*.6,2+j*.18))
            tube('Plant stem',[(x,y,.5),(x+.08,y,1.5),top],.018,MATS['leaf'])
            leaf=sphere('Olive leaf',top,(.36,.13,.035),MATS['leaf'],segments=16)
            leaf.rotation_euler=(.4,angle,.5)
    def area(name,loc,power,color,size,aim=(0,1,0)):
        data=bpy.data.lights.new(name,'AREA');data.energy=power;data.color=color;data.shape='DISK';data.size=size
        ob=bpy.data.objects.new(name,data);scene.collection.objects.link(ob);ob.location=loc
        ob.rotation_euler=(Vector(aim)-ob.location).to_track_quat('-Z','Y').to_euler()
    area('Large warm window',(-5,-4,12),1650,(1,.86,.68),7)
    area('Soft photographic fill',(6,-4,8),1100,(.82,.90,1),7)
    area('Glass and blue rim',(1,6,10),1800,(1,.91,.78),5)
    sun=bpy.data.lights.new('Late afternoon sunlight','SUN');sun.energy=1.0;sun.angle=.13;sun.color=(1,.88,.71)
    ob=bpy.data.objects.new('Late afternoon sunlight',sun);scene.collection.objects.link(ob);ob.rotation_euler=(.40,-.45,-.5)


def camera_pose(shot,shift=0,closer=0):
    a=shot['first'];settle=min(shot['last'],a+18)
    end=Vector((shift,-18+closer,10.2-closer*.28));target=Vector((0,0,3.05))
    start=end+Vector((-.28, -.28, .13))
    if shot['kind']=='intro':start=end+Vector((-1.0,-1.3,1.0))
    if shot['kind']=='path':start=end+Vector((-.3,1.1,-.3))
    if shot['kind']=='end':start=end
    for f,p in [(a,start),(settle,end),(shot['last'],end)]:
        key(CAM,'location',f,p)
        key(CAM,'rotation_euler',f,(target-p).to_track_quat('-Z','Y').to_euler())


def film_header(shot):
    if shot['kind']=='end':return
    hud('CONNECTED GALLERY',.068,.062,25,'muted')
    if shot['title']:hud(shot['title'],.067,.139,48,'ink',True)
    if shot['detail']:hud(shot['detail'],.07,.90,32,'muted')
    hud('생성 사진 · 가상 날짜 · 고정 시나리오',.93,.958,25,'muted',align='RIGHT')


def build_shot(s):
    global CURRENT
    CURRENT=bpy.data.collections.new('%s / %05.2f-%05.2f / %s' % (s['id'],s['start'],s['end'],s['kind']))
    bpy.context.scene.collection.children.link(CURRENT)
    kind=s['kind'];first=s['first'];span=s['end']-s['start']
    camera_pose(s, shift=-.15 if kind.startswith('review') else .1,
                closer=.4 if kind.startswith('open_') else 0)
    film_header(s)
    if kind in ('intro','select_wine','select_person','open_restaurant','open_beach'):
        pid=0 if kind in ('intro','select_wine') else 5 if kind=='open_beach' else 1
        w=7.1 if pid!=5 else 8.5
        pos=(1.30,.50,2.90 if pid!=5 else 3.25)
        cr=card(pid,pos,w,s)
        if kind.startswith('open_'):
            key(cr,'scale',first,(.83,.83,.83));key(cr,'scale',first+18,(1,1,1))
            cursor_on(cr,(w*.17,-.20,w*.1),s)
        else:
            actor=explorer((-4.9,-.20,1.20),s,(-2.45,.5,1.3),.90)
        if kind in ('select_wine','select_person'):
            box=(.37,.035,.63,.94) if pid==0 else FACES[1]
            outline=rectangle(cr,box,w,w*.75,MATS['blue'])
            outline['_appear']=.25
            pt=((box[0]+box[2]-1)/2*w,-.20,(.5-(box[1]+box[3])/2)*w*.75+.05)
            cursor_on(cr,pt,s)
        if kind=='intro':
            reviewer((5.9,2.6,1.0),s,.55)
            organizer((6.8,2.5,.28),s,False)
        if kind=='open_restaurant':
            outline=rectangle(cr,(0,0,1,1),w,w*.75,MATS['blue'],.012)
            outline['_appear']=.65
            explorer((-4.6,.10,1.20),s,(-2.3,.40,1.2),.75)
        if kind=='open_beach':
            organizer((-4.6,.1,.5),s)
            hud('데모 설정 날짜 · 2026.04.18',.075,.87,29,'muted')
    elif kind in ('search','search_refined'):
        cr=card(0,(-2.15,.65,3.35),5.7,s)
        rectangle(cr,(.37,.035,.63,.94),5.7,5.7*.75,MATS['blue'],.017)
        explorer((-5.25,-.35,1.05),s,(-4.65,.5,1.2),.80)
        tool(s)
        request=card(0,(.1,-.2,2.5),.7,s,crop=LABELS[0],label=False,name='Selected source request')
        move(request,s,(.0,-.25,2.9),(3.9,-.1,.95),.5)
        show_group(request,s,0.,.75)
    elif kind in ('tokens','inspect_request','tokens_new'):
        tool(s,(3.5,.50,.50))
        ex=explorer((-3.4,-.2,1.15),s,(-.3,-.1,2.0),1.05)
        for i in range(2):
            end=(-.45+i*2.0,.1,2.8)
            token=blank(end,s,1.65,i)
            if kind=='inspect_request':move(token,s,end,(3.5,.35,1.0),.5)
            else:move(token,s,(3.5,.35,1.0),end,.35)
        if kind=='tokens_new':
            hud('후보',.50,.70,28,'muted',align='CENTER')
    elif kind=='observe':
        for i,pid in enumerate(s['photos']):
            end=(-2.4+i*5.1,.45,3.2)
            cr=card(pid,end,4.8,s)
            move(cr,s,Vector(end)+Vector((.55,.2,-.45)),end,.25)
            key(cr,'rotation_euler',first,(-.20,0,.06 if i else -.06))
            key(cr,'rotation_euler',first+6,(-.20,0,0))
        explorer((-5.9,-.7,1.0),s,(-4.78,.4,1.30),.65)
        reviewer((5.75,-.5,.83),s,.55)
        hud('관찰한 사진',.50,.84,26,'muted',align='CENTER')
        # A physical handoff occurs after the image observation hold.
        submit=blank((1.0,-.65,.85),s,.42)
        move(submit,s,(1.0,-.65,.85),(5.4,-.65,.85),.25,max(.5,span-.5))
        show_group(submit,s,max(.5,span-.5))
    elif kind in ('review_reject','review_label','review_person','context_review'):
        p0,p1=s['photos'];width=5.35
        c0=card(p0,(-3.42,.6,3.2),width,s)
        c1=card(p1,(3.42,.6,3.2),width,s)
        rr=reviewer((0,-1.2,.86),s,.88)
        move(rr,s,(-.28,-1.2,.86),(.18,-1.2,.86),min(.5,span/2))
        scope0 = LABELS[p0] if kind=='review_label' else FACES[p0] if kind=='review_person' else (0,0,1,1)
        scope1 = LABELS[p1] if kind=='review_label' else FACES[p1] if kind=='review_person' else (0,0,1,1)
        cue0=rectangle(c0,scope0,width,width*.75,MATS['amber_edge'],.013)
        cue0['_appear']=.05;cue0['_until']=min(.65,span-.25)
        cue1=rectangle(c1,scope1,width,width*.75,MATS['amber_edge'],.013)
        cue1['_appear']=min(.45,span/3)
        if kind=='review_label':
            for x,pid in [(-1.3,p0),(1.3,p1)]:
                cr=card(pid,(x,-2.4,2.25),.84,s,crop=LABELS[pid],label=False,name='Visible label insert')
        if kind=='review_person':
            for x,pid in [(-1.25,p0),(1.25,p1)]:
                cr=card(pid,(x,-2.1,2.0),1.05,s,crop=FACES[pid],label=False,name='Visible face insert')
        if kind=='review_reject':
            cr=card(0,(-.1,-1.2,3.4),.70,s,crop=LABELS[0],label=False,name='Original label remains')
        if kind=='context_review':
            hud('데모 설정 날짜 · '+DATES[p0],.18,.79,27,'muted',align='CENTER')
            hud('데모 설정 날짜 · '+DATES[p1],.80,.79,27,'muted',align='CENTER')
        seal(c1,s,max(.65,span-.65),kind!='review_reject')
        # Original and candidate remain fully visible through feedback/decision.
    elif kind=='feedback':
        c0=card(0,(-3.25,.6,3.2),4.4,s)
        c4=card(4,(3.4,.8,2.0),3.1,s)
        c3=card(3,(3.4,1.0,4.6),3.1,s)
        explorer((-5.7,-.55,1.0),s,(-5.3,.3,1.6),.60)
        reviewer((.2,.5,.65),s,.58)
        clue=card(0,(.2,-1,3.2),1.02,s,crop=LABELS[0],label=False,name='Evidence carried back to Explorer')
        move(clue,s,(1.35,-.9,3.15),(-.85,-1.5,3.15),.5,.15)
        rectangle(c0,(.37,.035,.63,.94),4.4,3.3,MATS['blue'],.018)
        hud('와인 연결 근거 부족',.81,.78,25,'muted',align='CENTER')
    elif kind=='results':
        ids=s['photos'] if s['anchor']==0 else list(reversed(s['photos']))
        for i,pid in enumerate(ids):
            end=(-2.65+i*5.75,.6,3.25 if i==0 else 2.95)
            cr=card(pid,end,5.8 if i==0 else 4.5,s)
            move(cr,s,Vector(end)+Vector((0,0,.30)),end,.25)
            seal(cr,s,.75)
        organizer((.0,-.65,.25),s)
        reviewer((.2,.9,1.0),s,.42)
        hud('원본은 출발점으로 유지',.08,.825,24,'muted')
    elif kind in ('context_tokens','beach_tokens','person_tokens'):
        pid=s['anchor'];cr=card(pid,(-2.75,.8,3.15),5.2,s)
        box=FACES[1] if kind=='person_tokens' else (0,0,1,1)
        rectangle(cr,box,5.2,3.9,MATS['blue'],.018)
        explorer((-.1,-.65,1.05),s,(1.2,.2,2.1),.7)
        tool(s,(4.8,.5,.45))
        for i in range(2):
            end=(2.4+i*1.7,.65,3.3)
            token=blank(end,s,1.35,i)
            move(token,s,(4.8,.65,1.0),end,.40,.20)
            show_group(token,s,.20)
        hud('선택한 사람' if kind=='person_tokens' else '사진 전체가 기준',.23,.79,28,'muted',align='CENTER')
    elif kind=='context_observe':
        for i,pid in enumerate(s['photos']):
            pos=((-4.55,0,4.0),(0,.2,3.3),(4.55,.2,3.3))[i]
            cr=card(pid,pos,4.1,s)
            if i:move(cr,s,Vector(pos)+Vector((0,.4,-.25)),pos,.30)
            else:rectangle(cr,(0,0,1,1),4.1,3.075,MATS['blue'],.014)
        explorer((-1.4,-.65,.82),s,(.6,-.4,.8),.58)
    elif kind in ('context_restaurant','context_beach'):
        ids=s['photos']
        positions=[(0,1.25,3.6),(-4.95,.4,2.25),(4.95,.4,2.25)]
        widths=[5.0,3.35,3.35]
        for i,pid in enumerate(ids):
            cr=card(pid,positions[i],widths[i],s)
            if i:move(cr,s,Vector(positions[i])+Vector((0,0,.2)),positions[i],.25)
        organizer((0,-.3,.28),s)
        reviewer((0,1,.6),s,.42)
        color='date' if kind=='context_restaurant' else 'blue'
        relation((-2.3,.0,2.6),(-3.25,-.05,2.2),s,color,.30)
        relation((2.3,.0,2.6),(3.25,-.05,2.2),s,color,.30)
    elif kind=='path':
        places={0:(-4.8,1,3.6),1:(0,1,3.6),5:(4.8,1,3.6),2:(-4.8,-.1,.80),4:(0,-.1,.80),3:(4.8,-.1,.80)}
        for pid,co in places.items():card(pid,co,3.65 if pid in [0,1,5] else 1.9,s,label=True)
        for a,b in [(0,1),(1,5)]:
            relation((places[a][0]+1.92,.4,3.5),(places[b][0]-1.92,.4,3.5),s,'blue',0.)
        for a,b,c in [(0,2,'blue'),(1,4,'date'),(5,3,'blue')]:
            relation((places[a][0],.25,2.14),(places[b][0],-.3,1.56),s,c,0.)
        hud('라벨',.337,.42,24,'muted',align='CENTER')
        hud('사람',.665,.42,24,'muted',align='CENTER')
        hud('설정 날짜',.435,.625,23,'muted',align='CENTER')
    elif kind=='end':
        hud('Connected Gallery',.5,.36,85,'ink',True,'CENTER')
        hud('사진 한 장에서, 다음 기억으로.',.5,.49,48,'ink',False,'CENTER')
        hud('Made with Astra · Blender / Eevee',.5,.665,38,'muted',False,'CENTER')
        hud('생성 사진 · 가상 날짜 · 고정 시나리오',.5,.88,25,'muted',False,'CENTER')
    for ob in CURRENT.objects:
        after=float(ob.get('_appear',0.))
        until=ob.get('_until',None)
        show_between(ob,s['first']+round(after*FPS),
                     min(s['last'],s['first']+round(float(until)*FPS)-1) if until is not None else s['last'])
    CURRENT=None


def configure(scene,percent=100,samples=32):
    scene.render.engine='BLENDER_EEVEE'
    scene.render.resolution_x=1920;scene.render.resolution_y=1080;scene.render.resolution_percentage=percent
    scene.render.fps=FPS;scene.frame_start=1;scene.frame_end=LENGTH*FPS
    scene.render.image_settings.media_type='IMAGE'
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGB'
    scene.render.image_settings.compression=15
    scene.render.film_transparent=False
    scene.eevee.taa_render_samples=samples
    scene.eevee.use_raytracing=True
    scene.eevee.use_fast_gi=True
    scene.eevee.fast_gi_quality=.35
    scene.eevee.shadow_ray_count=2
    scene.eevee.shadow_step_count=6
    scene.render.use_file_extension=True
    scene.render.use_compositing=False
    scene.view_settings.view_transform='AgX'
    scene.view_settings.look='AgX - Medium High Contrast'
    scene.view_settings.exposure=.20


def build():
    global CAM
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene;scene.name='Connected Gallery / 54s / Astra'
    configure(scene)
    font_path=Path('C:/Windows/Fonts')
    FONTS['regular']=bpy.data.fonts.load(str(font_path/'malgun.ttf'))
    FONTS['bold']=bpy.data.fonts.load(str(font_path/'malgunbd.ttf'))
    for key_,color in COLORS.items():
        MATS[key_]=mat(key_,color,.4)
        ink = (.028,.032,.029,1) if key_=='muted' else color
        MATS['text_'+key_]=mat('Typography '+key_,ink,emission=True)
    MATS['paper']=mat('Cotton photographic paper',COLORS['paper'],.86)
    MATS['floor']=mat('Warm plaster',(0.82,.77,.66,1),.88)
    MATS['travertine']=mat('Fine limestone',(0.73,.66,.54,1),.78)
    MATS['ceramic']=mat('Satin ceramic',(0.50,.54,.47,1),.36)
    MATS['token']=mat('Opaque unobserved candidate',(0.63,.67,.74,1),.35)
    MATS['leaf']=mat('Olive leaves',(.14,.19,.10,1),.8)
    MATS['blue']=mat('Explorer / lacquer blue',COLORS['blue'],.19,.30)
    bp=MATS['blue'].node_tree.nodes.get('Principled BSDF')
    bp.inputs['Coat Weight'].default_value=.7;bp.inputs['Coat Roughness'].default_value=.16
    MATS['stone']=mat('Organizer / charcoal basalt',(.018,.023,.025,1),.31,.15)
    MATS['glass']=mat('Reviewer / honey glass',(.86,.51,.15,1),.12,.02,transmission=.80)
    MATS['amber_edge']=mat('Reviewer / warm reflected edge',(.52,.23,.043,1),.21,.48)
    add_noise(MATS['travertine'],45,.20,.025)
    add_noise(MATS['floor'],8,.08,.02)
    add_noise(MATS['paper'],125,.06,.003)
    add_noise(MATS['stone'],60,.12,.013)
    add_noise(MATS['blue'],160,.025,.006)
    image=bpy.data.images.load(str(SHEET));image.name='Original six-photo sheet';image.pack()
    scene.world=bpy.data.worlds.new('Soft cream atmosphere');scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.72,.76,.82,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.40
    cdata=bpy.data.cameras.new('Film camera / 46mm');cdata.lens=46;cdata.sensor_width=36;cdata.clip_end=200
    CAM=bpy.data.objects.new('Film camera',cdata);scene.collection.objects.link(CAM);scene.camera=CAM
    stage(scene)
    for s in SHOTS:
        build_shot(s)
        marker=scene.timeline_markers.new(s['id']+' / '+s['kind'],frame=s['first'])
    scene['production']='Astra / Blender Eevee / generated photographs / fixed scenario'
    scene['duration_seconds']=54
    scene['credit']='Made with Astra · Blender / Eevee'
    scene['source_sheet_sha256']=__import__('hashlib').sha256(SHEET.read_bytes()).hexdigest()
    scene['shot_manifest']=json.dumps(SHOTS,ensure_ascii=False)
    # Camera cut boundaries remain discontinuous; action curves settle with AUTO_CLAMPED handles.
    for act in bpy.data.actions:
        for layer in act.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for p in fc.keyframe_points:
                            if fc.data_path in ('hide_render','hide_viewport'):
                                p.interpolation='CONSTANT'
                            else:
                                p.interpolation='BEZIER'
                                p.handle_left_type=p.handle_right_type='AUTO_CLAMPED'
    scene.frame_set(1)
    scene.render.filepath=str(OUT/'frames'/'frame_')
    if (OUT/'score.wav').exists():
        scene.sequence_editor_create().strips.new_sound('Original score / 54 seconds',str(OUT/'score.wav'),1,1)
    scene.render.use_sequencer=False
    # These system fonts permit editable document embedding (OS/2 fsType=8).
    # Pack them and the source photographs so the authored scene is portable.
    bpy.ops.file.pack_all()
    DEST.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    (DEST/'timeline.json').write_text(json.dumps(SHOTS,ensure_ascii=False,indent=2),encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-astra.blend'),compress=True)
    print('FILM_BUILD_COMPLETE',len(SHOTS),'shots',len(bpy.data.objects),'objects',flush=True)


def load():
    bpy.ops.wm.open_mainfile(filepath=str(DEST/'connected-gallery-astra.blend'))
    return bpy.context.scene


def render_frames(scene,frames,directory,percent,samples,resume=True,visible_only=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    configure(scene,percent,samples)
    began=time.time()
    # The film has no simulations, time-driven shaders or drivers. Its only
    # changing state is keyed object transforms/visibility and curve draw length.
    # Preserve a held pose exactly instead of resampling static Eevee noise.
    channels=[]
    for owner in [*bpy.data.objects,*bpy.data.curves]:
        ad=owner.animation_data
        if ad and ad.drivers:raise RuntimeError('Hold reuse does not support drivers')
        if not ad or not ad.action:continue
        paths=set()
        for layer in ad.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    if bag.slot_handle!=ad.action_slot.handle:continue
                    paths.update(fc.data_path for fc in bag.fcurves)
        channels.extend((owner,p) for p in sorted(paths))
    def state_digest():
        values=[]
        if visible_only:
            for ob in bpy.data.objects:
                if ob.hide_render or ob.type=='EMPTY':continue
                item=[ob.name,tuple(v for row in ob.matrix_world for v in row)]
                if ob.type=='CURVE':
                    item.extend([ob.data.bevel_factor_start,ob.data.bevel_factor_end])
                    for spline in ob.data.splines:
                        item.extend((tuple(p.co),tuple(p.handle_left),tuple(p.handle_right)) for p in spline.bezier_points)
                values.append(item)
            return hashlib.sha256(repr(values).encode()).hexdigest()
        for owner,path in channels:
            value=owner.path_resolve(path)
            values.append(tuple(value) if hasattr(value,'__len__') else value)
        return hashlib.sha256(repr(values).encode()).hexdigest()
    cache={};reuse=[];rendered=0
    for index,frame in enumerate(frames):
        target=directory/('frame_%04d.png'%frame)
        scene.frame_set(frame)
        digest=state_digest()
        if resume and target.exists():
            cache.setdefault(digest,target)
            continue
        if digest in cache:
            shutil.copyfile(cache[digest],target)
            reuse.append({'frame':frame,'source':cache[digest].name,'state_sha256':digest})
        else:
            scene.render.filepath=str(target)
            bpy.ops.render.render(write_still=True)
            cache[digest]=target;rendered+=1
        if frame%24==0 or index==0:
            print('FRAME_DONE',frame,'rendered',rendered,'held',len(reuse),'elapsed',round(time.time()-began,2),flush=True)
    (directory/'render-evidence.json').write_text(json.dumps({'percent':percent,'samples':samples,
        'fingerprint':'visible world matrices and curve geometry' if visible_only else 'all keyed channels',
        'rendered_this_run':rendered,'held_frames':reuse,'elapsed_seconds':time.time()-began},indent=2),encoding='utf-8')
    print('RENDER_SET_COMPLETE',str(directory),flush=True)


def encode(scene,source,output,step=1,audio=None,samples=32,percent=100):
    # VSE encodes the already-rendered frames; no 3D rerender is needed.
    if Path(output).parent==DEST:
        scene.frame_set(1)
        configure(scene,100,samples)
        for area in bpy.context.window.screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.type='RENDERED'
        bpy.ops.file.make_paths_relative()
        bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-astra.blend'),compress=True)
    scene=bpy.data.scenes.new('Final edit / image sequence + original score')
    bpy.context.window.scene=scene
    first_image=bpy.data.images.load(str(Path(source)/'frame_0001.png'))
    scene.render.resolution_x=first_image.size[0]
    scene.render.resolution_y=first_image.size[1]
    bpy.data.images.remove(first_image)
    scene.render.resolution_percentage=percent
    scene.render.fps=FPS;scene.frame_start=1;scene.frame_end=LENGTH*FPS
    ed=scene.sequence_editor_create()
    frames=list(range(1,LENGTH*FPS+1,step))
    path=Path(source)
    strip=ed.strips.new_image('Rendered Eevee image sequence',str(path/('frame_%04d.png'%frames[0])),1,1)
    for f in frames[1:]:strip.elements.append('frame_%04d.png'%f)
    if step!=1:strip.frame_final_duration=LENGTH*FPS
    if audio:
        ed.strips.new_sound('Original synthesized score and Foley',str(audio),2,1)
    scene.render.image_settings.media_type='VIDEO'
    scene.render.image_settings.file_format='FFMPEG'
    scene.render.ffmpeg.format='MPEG4';scene.render.ffmpeg.codec='H264'
    scene.render.ffmpeg.constant_rate_factor='HIGH'
    scene.render.ffmpeg.ffmpeg_preset='GOOD'
    scene.render.ffmpeg.audio_codec='AAC';scene.render.ffmpeg.audio_bitrate=192
    scene.render.ffmpeg.audio_mixrate=48000
    scene.render.filepath=str(output)
    scene.render.use_sequencer=True;scene.render.use_compositing=False
    scene.view_settings.view_transform='Standard'
    scene.view_settings.look='None'
    if Path(output).parent==DEST:
        for area in bpy.context.window.screen.areas:
            if area.type=='VIEW_3D':
                area.type='SEQUENCE_EDITOR'
                area.spaces.active.view_type='SEQUENCER_PREVIEW'
        bpy.ops.file.make_paths_relative()
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-edit.blend'),compress=True)
    bpy.ops.render.render(animation=True)
    print('ENCODE_COMPLETE',str(output),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['build','stills','preview','render','encode','encode-preview'],default='build')
    parser.add_argument('--frames',default='')
    parser.add_argument('--percent',type=int,default=50)
    parser.add_argument('--samples',type=int,default=16)
    parser.add_argument('--start',type=int,default=1)
    parser.add_argument('--end',type=int,default=1296)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.mode=='build':build();return
    scene=load()
    if args.mode=='stills':
        frames=[int(x) for x in args.frames.split(',')] if args.frames else [60,222,324,462,774,828,1020,1182,1272]
        render_frames(scene,frames,OUT/'stills',args.percent,args.samples,False)
    elif args.mode=='preview':
        render_frames(scene,range(1,1297),OUT/'preview-frames',args.percent,args.samples)
        encode(scene,OUT/'preview-frames',OUT/'preview.mp4',audio=OUT/'score.wav')
    elif args.mode=='render':
        render_frames(scene,range(args.start,args.end+1),OUT/'frames',100,args.samples)
    elif args.mode=='encode':
        encode(scene,OUT/'frames',DEST/'connected-gallery-astra.mp4',audio=OUT/'score.wav')
    elif args.mode=='encode-preview':
        encode(scene,OUT/'preview-frames',OUT/'preview.mp4',audio=OUT/'score.wav')


if __name__=='__main__':main()
