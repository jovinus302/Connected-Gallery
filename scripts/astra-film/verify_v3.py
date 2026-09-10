"""Check the role overlay and preserved source; run with Blender Python.

This checks layout and authored timing, not audience comprehension.
"""
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import film_v3 as film

checks = []


def check(name, passed, evidence):
    checks.append(dict(name=name, passed=bool(passed), evidence=evidence))


def bounds(scene, obj):
    coords = [world_to_camera_view(scene, scene.camera, obj.matrix_world @ Vector(c)) for c in obj.bound_box]
    return [min(v.x for v in coords)*1920, (1-max(v.y for v in coords))*1080,
            max(v.x for v in coords)*1920, (1-min(v.y for v in coords))*1080]


manifest = json.loads((film.DEST/'timeline.json').read_text(encoding='utf-8'))
for filename, expected in manifest['source_sha256'].items():
    check('Source file unchanged: '+filename, film.sha(film.SOURCE/filename) == expected, expected)
bpy.ops.wm.open_mainfile(filepath=str(film.DEST/'connected-gallery-roles.blend'))
scene = bpy.context.scene
check('Native 1080p at 24fps', (scene.render.resolution_x,scene.render.resolution_y,scene.render.fps)==(1920,1080,24),
      [scene.render.resolution_x, scene.render.resolution_y, scene.render.fps])
check('100 second edit', scene.frame_end == 2400, scene.frame_end)
panel = bpy.data.objects['Role panel / shared introduction to corner']
box = list(panel['corner_bounds_pixels'])
bars = [bpy.data.objects[r[0]+' / active underline'] for r in film.ROLES]
pivots = [bpy.data.objects[r[0]+' / slow 3D rotation'] for r in film.ROLES]
wrong_states, hidden_labels, outside, rotating_idle = [], [], [], []
last_rotations = None
for n in range(1, film.COUNT+1):
    scene.frame_set(n)
    t = (n-1)/film.FPS
    if film.INTRO <= t < film.INTRO+89:
        state = film.state_at(n)
        actual = [i for i,o in enumerate(bars) if not o.hide_render]
        expected = [state[2]] if state[2] is not None else []
        if actual != expected:
            wrong_states.append([n, actual, expected])
        for o in panel.children_recursive:
            if o.type not in ('FONT', 'MESH') or o.hide_render:
                continue
            b = bounds(scene, o)
            if b[0] < box[0]-2 or b[1] < box[1]-2 or b[2] > box[2]+2 or b[3] > box[3]+2:
                outside.append([n, o.name, b])
        visible_text = [o.data.body for o in panel.children if o.type=='FONT' and not o.hide_render]
        if not all(r[1] in visible_text and r[0] in visible_text for r in film.ROLES) or state[3] not in visible_text:
            hidden_labels.append(n)
        if last_rotations:
            for i,o in enumerate(pivots):
                if i != state[2] and any(abs(a-b)>1e-6 for a,b in zip(o.rotation_euler,last_rotations[i])):
                    rotating_idle.append([n,film.ROLES[i][0]])
    if t >= film.INTRO+89:
        if any(not o.hide_render for o in panel.children_recursive if o.type in ('MESH','FONT')):
            hidden_labels.append(n)
    last_rotations = [tuple(o.rotation_euler) for o in pivots]
check('Active symbols match every authored state', not wrong_states, wrong_states[:10])
check('All names and current descriptions visible; end card clear', not hidden_labels, hidden_labels[:10])
check('Corner overlay stays within reserved bounds', not outside, {'box':list(box),'violations':outside[:10], 'count':len(outside)})
check('Inactive symbols stop rotating without resetting', not rotating_idle, rotating_idle[:10])

# Check actual projected photograph frames and captions from the unmodified 3D source.
# This catches collisions in-between representative screenshots.
bpy.ops.wm.open_mainfile(filepath=str(film.SOURCE/'connected-gallery-astra.blend'))
scene = bpy.context.scene
objects = [o for o in scene.objects if 'Cotton paper' in o.name or 'caption_interval' in o]
collisions = []
for n in range(1, 89*film.FPS+1):
    scene.frame_set(n)
    for o in objects:
        if o.hide_render:
            continue
        b = bounds(scene,o)
        if b[0] < box[2] and b[2] > box[0] and b[1] < box[3] and b[3] > box[1]:
            collisions.append([n,o.name,b])
check('Overlay avoids source photo frames and captions', not collisions,
      {'objects':len(objects),'frame_count':89*film.FPS,'collisions':collisions[:12], 'count':len(collisions)})
result = dict(verdict='PASS' if all(c['passed'] for c in checks) else 'FAIL', checks=checks)
(film.DEST/'scene-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
if result['verdict'] != 'PASS':
    raise RuntimeError('v3 scene validation failed')
