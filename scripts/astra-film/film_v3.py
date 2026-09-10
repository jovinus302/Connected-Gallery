"""Add a role introduction and a rotating 3D legend to the unchanged v2 film.

Run with Blender's Python. Intermediate RGBA frames stay under outputs/.
The source MP4 and packed 3D scene are read only. No model/network calls.
"""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'docs/presentations/astra-film/v2'
DEST = ROOT / 'docs/presentations/astra-film/v3'
OUT = ROOT / 'outputs/astra-film/v3'
FPS, INTRO, DURATION = 24, 7, 100
COUNT = FPS * DURATION
ROLES = [
    ('Explorer', '탐색', '관련 사진을 찾고 확인해요', (.035, .12, .62, 1)),
    ('Reviewer', '검토', '연결 근거를 확인해요', (.58, .27, .055, 1)),
    ('Organizer', '정리', '확인된 사진을 묶어요', (.07, .10, .12, 1)),
]
# Times are seconds in the original v2 film; do not imply every review retries.
STATES = [
    (0, 1.7, None, '사진에서 대상을 선택해요'),
    (1.7, 4, 0, '선택한 사진을 살펴봐요'),
    (4, 10, 0, '후보를 찾아 직접 확인해요'),
    (10, 16, 1, '원본과 연결 근거를 비교해요'),
    (16, 19.6, 1, '검토 → 탐색 · 단서를 전달해요'),
    (19.6, 23.1, 0, '받은 단서로 다시 찾아봐요'),
    (23.1, 29, 1, '새 후보의 근거를 비교해요'),
    (29, 33, 2, '확인한 사진을 묶어 보여줘요'),
    (33, 37, None, '다음 사진을 열어요'),
    (37, 41, 0, '사진 전체로 후보를 찾아요'),
    (41, 46.3, 1, '함께 볼 이유를 확인해요'),
    (46.3, 47.6, 2, '확인된 사진을 정리해요'),
    (47.6, 51, None, '새로운 대상을 선택해요'),
    (51, 56, 0, '선택한 사람의 사진을 찾아요'),
    (56, 61.3, 1, '같은 사람인지 비교해요'),
    (61.3, 63, 2, '확인한 장면을 모아줘요'),
    (63, 66, None, '도착한 사진에서 다시 시작해요'),
    (66, 71, 0, '새 기준으로 후보를 찾아요'),
    (71, 76.3, 1, '사진마다 연결 근거를 살펴요'),
    (76.3, 84.3, 2, '확인한 사진의 흐름을 정리해요'),
    (84.3, 89, None, '찾고 · 검토하고 · 정리해요'),
]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def frame(t):
    return round(t * FPS) + 1


def state_at(n):
    return next((s for s in STATES if frame(INTRO+s[0]) <= n < frame(INTRO+s[1])), None)


def ease(t):
    return max(0, min(1, t)) ** 2 * (3 - 2 * max(0, min(1, t)))


def keyed(obj, prop, n, val):
    setattr(obj, prop, val)
    obj.keyframe_insert(data_path=prop, frame=n)


def empty(scene, name, parent=None, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None)
    scene.collection.objects.link(o)
    o.parent = parent
    o.location = loc
    return o


def emission(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value = color
    mat.node_tree.links.new(emit.outputs[0], nodes.new('ShaderNodeOutputMaterial').inputs[0])
    return mat


def plate(scene, name, root, pos, width, height, mat):
    mesh = bpy.data.meshes.new(name)
    vertices = [(-width/2, 0, -height/2), (width/2, 0, -height/2),
                (width/2, 0, height/2), (-width/2, 0, height/2)]
    if name == 'Role panel backdrop':
        radius = .14
        vertices = []
        for x, z, angle in [(width/2-radius, height/2-radius, 0),
                             (-width/2+radius, height/2-radius, 90),
                             (-width/2+radius, -height/2+radius, 180),
                             (width/2-radius, -height/2+radius, 270)]:
            for step in range(9):
                a = math.radians(angle+step*90/8)
                vertices.append((x+radius*math.cos(a), 0, z+radius*math.sin(a)))
    mesh.from_pydata(vertices, [], [tuple(range(len(vertices)))])
    o = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(o)
    o.parent, o.location = root, pos
    mesh.materials.append(mat)
    return o


def text(scene, root, value, pos, size, mat, bold=True, align='CENTER'):
    curve = bpy.data.curves.new(value, 'FONT')
    curve.body, curve.size, curve.align_x = value, size, align
    curve.font = bpy.data.fonts.load('C:/Windows/Fonts/malgunbd.ttf' if bold else 'C:/Windows/Fonts/malgun.ttf', check_existing=True)
    curve.resolution_u = 4
    o = bpy.data.objects.new('Role text / ' + value, curve)
    scene.collection.objects.link(o)
    o.parent, o.location = root, pos
    o.rotation_euler = (math.pi/2, 0, 0)
    curve.materials.append(mat)
    return o


def interval(o, start, end):
    for n, hide in [(0, True), (frame(start)-1, True), (frame(start), False),
                    (frame(end)-1, False), (frame(end), True)]:
        keyed(o, 'hide_render', n, hide)
    o['visible_seconds'] = [start, end]


def configure(scene):
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, COUNT
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.compression = 25
    scene.render.use_sequencer = False
    scene.render.use_compositing = False
    scene.eevee.taa_render_samples = 16
    scene.eevee.use_raytracing = False
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'


def snapshot_agents(scene):
    """Freeze the actual v2 meshes, including limbs, into independent miniatures."""
    source_scene = bpy.context.scene
    source_scene.frame_set(1)
    deps = bpy.context.evaluated_depsgraph_get()
    ex = next(o for o in source_scene.objects if o.get('persistent_agent') == 'Explorer')
    rev = next(o for o in source_scene.objects if o.get('persistent_agent') == 'Reviewer')
    stones = sorted([o for o in source_scene.objects if o.name.startswith('Organizer / moving stone')], key=lambda o:o.name)
    groups = [(ex, list(ex.children_recursive)), (rev, list(rev.children_recursive)), (None, stones)]
    saved = []
    for i, (actor, objects) in enumerate(groups):
        entries = []
        for j, o in enumerate(objects):
            if o.type not in ('MESH', 'CURVE'):
                continue
            evaluated = o.evaluated_get(deps)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=deps)
            clone = bpy.data.objects.new('Miniature ' + ROLES[i][0] + ' / ' + o.name, mesh)
            scene.collection.objects.link(clone)
            if actor:
                matrix = actor.matrix_world.inverted() @ o.matrix_world
            else:
                matrix = o.matrix_world.copy()
                matrix.translation = Vector(((j-1)*.76, 0, (j-1)*.06))
            entries.append((clone, matrix))
        saved.append(entries)
    return saved


def build():
    DEST.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = {p.name:sha(p) for p in [SOURCE/'connected-gallery-astra.mp4', SOURCE/'connected-gallery-astra.blend']}
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE/'connected-gallery-astra.blend'))
    source_objects = list(bpy.data.objects)
    source_scenes = list(bpy.data.scenes)
    scene = bpy.data.scenes.new('v3 / introduction and 3D role legend')
    snapshots = snapshot_agents(scene)
    bpy.context.window.scene = scene
    for o in source_objects:
        bpy.data.objects.remove(o, do_unlink=True)
    for old in source_scenes:
        bpy.data.scenes.remove(old)
    configure(scene)
    world = bpy.data.worlds.new('Role studio')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.8, .85, 1, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .65
    scene.world = world
    data = bpy.data.cameras.new('Fixed screen camera')
    data.type, data.ortho_scale = 'ORTHO', 19.2
    camera = bpy.data.objects.new('Fixed screen camera', data)
    scene.collection.objects.link(camera)
    camera.location = (0, -25, 0)
    camera.rotation_euler = (math.pi/2, 0, 0)
    scene.camera = camera
    for name, loc, power, size in [('Key', (-4, -10, 9), 1600, 9), ('Fill', (9, -6, 4), 1000, 7)]:
        data = bpy.data.lights.new(name, 'AREA')
        data.energy, data.shape, data.size = power, 'DISK', size
        light = bpy.data.objects.new(name, data)
        scene.collection.objects.link(light)
        light.location = loc
        light.rotation_euler = (-light.location).to_track_quat('-Z', 'Y').to_euler()
    cream = emission('Role panel / warm ivory', (.86, .83, .77, 1))
    ink = emission('Role label / ink', (.028, .034, .041, 1))
    muted = emission('Role label / secondary', (.065, .075, .085, 1))
    intro = plate(scene, 'Introduction background', None, (0, 3, 0), 20, 12, cream)
    interval(intro, 0, INTRO)
    heading = text(scene, None, '세 Agent가 함께, 사진을 연결합니다.', (0, -.5, 3.5), .55, ink)
    sub = text(scene, None, '찾고 확인하고  →  근거를 검토하고  →  결과를 정리해요', (0, -.5, 2.75), .29, muted, False)
    for o in (heading, sub):
        interval(o, 0, 5.5)
    panel = empty(scene, 'Role panel / shared introduction to corner')
    panel['corner_bounds_pixels'] = [1433, 12, 1891, 168]
    backdrop = plate(scene, 'Role panel backdrop', panel, (0, .8, -.08), 4.58, 1.96, cream)
    spins = []
    moving_labels = []
    role_shaders = []
    compact_positions = [(backdrop, -.08, -.13)]
    for i, (name, korean, desc, color) in enumerate(ROLES):
        x = (i-1)*1.43
        root = empty(scene, name + ' / symbol position', panel, (x, 0, .24))
        pivot = empty(scene, name + ' / slow 3D rotation', root)
        for clone, matrix in snapshots[i]:
            clone.parent = pivot
            clone.matrix_basis = matrix
        materials = {}
        for clone, _ in snapshots[i]:
            for slot in clone.material_slots:
                original = slot.material
                if original.name not in materials:
                    copy = original.copy()
                    copy.name = name + ' / legend / ' + original.name
                    materials[original.name] = copy
                slot.material = materials[original.name]
        shaders = []
        for mat in materials.values():
            shader = mat.node_tree.nodes.get('Principled BSDF')
            if shader:
                shaders.append((shader.inputs['Base Color'], tuple(shader.inputs['Base Color'].default_value)))
        role_shaders.append(shaders)
        base = .25 if i != 2 else .30
        pivot.scale = (base,)*3
        spins.append((root, pivot, base))
        label = text(scene, panel, korean, (x, -.6, -.39), .285, ink)
        english = text(scene, panel, name, (x, -.6, -.63), .17, muted, False)
        moving_labels.extend([(label, .80), (english, .64)])
        compact_positions.extend([(label, -.39, -.26), (english, -.63, -.47)])
        accent = emission(name + ' / activity color', color)
        bar = plate(scene, name + ' / active underline', panel, (x, -.6, -.77), 1.05, .035, accent)
        compact_positions.append((bar, -.77, -.58))
        # Explain roles in the introduction only; the labels travel into the corner.
        t = text(scene, None, desc, ((i-1)*5.0, -.5, -3.2), .31, ink)
        interval(t, 0, 5.5)
        for n in range(1, COUNT+1):
            sec = (n-1)/FPS
            if sec < 5.5:
                active = (sec < 1.9 and i == 0) or (1.9 <= sec < 3.7 and i == 1) or (3.7 <= sec < 5.5 and i == 2)
            else:
                current = state_at(n)
                active = current is not None and current[2] == i
            keyed(bar, 'hide_render', n, not active or sec >= INTRO+89)
        interval(root, 0, INTRO+89)
    # Activity is accumulated, so idle symbols stop without resetting their rotation.
    phases = [0., 0., 0.]
    strengths = [1., .45, .45]
    for n in range(1, COUNT+1):
        sec = (n-1)/FPS
        u = ease((sec-5.5)/1.5)
        keyed(panel, 'location', n, (7.02*u, 0, 4.63*u))
        size = 3.5 + (1-3.5)*u
        keyed(panel, 'scale', n, (size,)*3)
        keyed(backdrop, 'scale', n, (1, 1, 1-(1-1.56/1.96)*u))
        for obj, a, b in compact_positions:
            keyed(obj, 'location', n, (obj.location.x, obj.location.y, a+(b-a)*u))
        for label, initial in moving_labels:
            keyed(label, 'scale', n, (initial+(1-initial)*u,)*3)
        current = state_at(n)
        for i, (root, pivot, base) in enumerate(spins):
            intro_active = sec < 5.5 and ((sec < 1.9 and i == 0) or (1.9 <= sec < 3.7 and i == 1) or (3.7 <= sec and i == 2))
            active = intro_active or (current is not None and current[2] == i)
            if active:
                phases[i] += 2*math.pi/(FPS*10)
            target = 1.0 if active or 5.5 <= sec < INTRO else .45
            strengths[i] += (target-strengths[i]) * .24
            # A gentle yaw keeps the amber ring and the three stones recognizable.
            keyed(pivot, 'rotation_euler', n, (.10*math.sin(phases[i]), 0, .48*math.sin(phases[i])))
            amount = base * (.82+.18*strengths[i])
            keyed(pivot, 'scale', n, (amount,)*3)
            for socket, color in role_shaders[i]:
                mix = strengths[i]
                socket.default_value = tuple(color[j]*mix+.22*(1-mix) for j in range(3)) + (1,)
                socket.keyframe_insert(data_path='default_value', frame=n)
    for a, b, who, label in STATES:
        t = text(scene, panel, label, (0, -.6, -.84), .225, ink, True)
        interval(t, INTRO+a, INTRO+b)
    # Remove all corner elements for the original four-second end card.
    for o in [panel, *panel.children_recursive]:
        if 'visible_seconds' not in o and 'active underline' not in o.name:
            interval(o, 0, INTRO+89)
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for k in fc.keyframe_points:
                            k.interpolation = 'CONSTANT' if fc.data_path == 'hide_render' else 'LINEAR'
    scene['source_sha256'] = json.dumps(source_hashes)
    scene['role_states'] = json.dumps(STATES, ensure_ascii=False)
    scene['intro_seconds'], scene['duration_seconds'] = INTRO, DURATION
    scene.frame_set(1)
    bpy.data.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-roles.blend'), compress=True)
    manifest = dict(intro=INTRO, duration=DURATION, fps=FPS, source_sha256=source_hashes,
                    roles=[dict(name=r[0], role=r[1], explanation=r[2]) for r in ROLES],
                    states=[dict(start=a+INTRO, end=b+INTRO, first=frame(a+INTRO), last=frame(b+INTRO)-1,
                                 agent=ROLES[i][0] if i is not None else None, label=s) for a,b,i,s in STATES])
    (DEST/'timeline.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('V3_BUILD_OK', len(scene.objects), flush=True)


def render(args):
    bpy.ops.wm.open_mainfile(filepath=str(DEST/'connected-gallery-roles.blend'))
    scene = bpy.context.scene
    scene.render.resolution_percentage = args.percent
    folder = OUT / ('stills' if args.frames else 'overlay')
    folder.mkdir(parents=True, exist_ok=True)
    if not args.frames:
        evidence = {'scene_sha256': sha(DEST/'connected-gallery-roles.blend'), 'percent': args.percent, 'fps': FPS}
        record = folder/'render-settings.json'
        if record.exists() and json.loads(record.read_text()) != evidence:
            raise RuntimeError('Scene or resolution changed. Preserve the previous overlay directory before rendering again.')
        record.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    frames = [int(x) for x in args.frames.split(',')] if args.frames else range(args.start, args.end+1)
    started = time.monotonic()
    for n in frames:
        scene.frame_set(n)
        scene.render.filepath = str(folder / f'frame_{n:04d}.png')
        bpy.ops.render.render(write_still=True)
        if n % 24 == 0:
            print('OVERLAY_PROGRESS', n, round(time.monotonic()-started, 2), flush=True)


def edit(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = 'v3 / original film and role introduction'
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, args.end
    scene.view_settings.view_transform, scene.view_settings.look = 'Standard', 'None'
    scene.render.use_sequencer, scene.render.use_compositing = True, False
    ed = scene.sequence_editor_create()
    movie = ed.strips.new_movie('Unchanged v2 film / +7 seconds', str(SOURCE/'connected-gallery-astra.mp4'), 1, frame(INTRO))
    movie.frame_final_end = COUNT+1
    sound = ed.strips.new_sound('Original synchronized soundtrack', str(SOURCE/'connected-gallery-astra.mp4'), 2, frame(INTRO))
    sound.frame_final_end = COUNT+1
    # Quiet musical lead-in taken from the same film, crossfading into its full score.
    lead = ed.strips.new_sound('Introduction / quiet lead-in from existing score', str(SOURCE/'connected-gallery-astra.mp4'), 3, 1)
    lead.frame_final_end = frame(INTRO)
    for n, v in [(1, 0), (25, .30), (frame(5.5), .30), (frame(INTRO)-1, 0)]:
        keyed(lead, 'volume', n, v)
    folder = OUT/'overlay'
    overlay = ed.strips.new_image('3D role symbols and introduction', str(folder/'frame_0001.png'), 4, 1)
    for n in range(2, args.end+1):
        if not (folder/f'frame_{n:04d}.png').is_file():
            raise FileNotFoundError(folder/f'frame_{n:04d}.png')
        overlay.elements.append(f'frame_{n:04d}.png')
    overlay.blend_type = 'ALPHA_OVER'
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format, scene.render.ffmpeg.codec = 'MPEG4', 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'
    scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
    scene.render.ffmpeg.audio_codec, scene.render.ffmpeg.audio_bitrate = 'AAC', 192
    scene.render.ffmpeg.audio_mixrate = 48000
    output = DEST/'connected-gallery-astra.mp4' if args.end == COUNT else OUT/'preview.mp4'
    scene.render.filepath = str(output)
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.type = 'SEQUENCE_EDITOR'
            area.spaces.active.view_type = 'SEQUENCER_PREVIEW'
    # Establish the file location before making media paths portable.
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-edit.blend'), compress=True)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-edit.blend'), compress=True)
    bpy.ops.render.render(animation=True)
    print('V3_ENCODE_OK', str(output), flush=True)


def composite_stills(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.view_settings.view_transform, scene.view_settings.look = 'Standard', 'None'
    scene.render.use_sequencer, scene.render.use_compositing = True, False
    scene.render.image_settings.file_format = 'PNG'
    ed = scene.sequence_editor_create()
    ed.strips.new_movie('Source film', str(SOURCE/'connected-gallery-astra.mp4'), 1, frame(INTRO))
    (OUT/'review').mkdir(parents=True, exist_ok=True)
    for n in [int(x) for x in args.frames.split(',')]:
        overlay = ed.strips.new_image('Role preview', str(OUT/'stills'/f'frame_{n:04d}.png'), 2, 1)
        overlay.frame_final_duration = COUNT
        overlay.blend_type = 'ALPHA_OVER'
        scene.frame_set(n)
        scene.render.filepath = str(OUT/'review'/f'frame_{n:04d}.png')
        bpy.ops.render.render(write_still=True)
        ed.strips.remove(overlay)


def video_stills(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage, scene.render.fps = 100, FPS
    scene.view_settings.view_transform, scene.view_settings.look = 'Standard', 'None'
    scene.render.use_sequencer, scene.render.use_compositing = True, False
    scene.render.image_settings.file_format = 'PNG'
    scene.sequence_editor_create().strips.new_movie('Final encoded movie', str(DEST/'connected-gallery-astra.mp4'), 1, 1)
    (OUT/'decoded').mkdir(parents=True, exist_ok=True)
    for n in [int(x) for x in args.frames.split(',')]:
        scene.frame_set(n)
        scene.render.filepath = str(OUT/'decoded'/f'frame_{n:04d}.png')
        bpy.ops.render.render(write_still=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['build', 'render', 'encode', 'composite-stills', 'video-stills'], default='build')
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=COUNT)
    p.add_argument('--frames', default='')
    p.add_argument('--percent', type=int, default=100)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not 1 <= args.start <= args.end <= COUNT:
        p.error('Frame range must be within 1..2400')
    if args.mode == 'encode' and args.end % FPS:
        p.error('Encode a whole number of seconds')
    if args.mode == 'build':
        build()
    elif args.mode == 'render':
        render(args)
    elif args.mode == 'composite-stills':
        composite_stills(args)
    elif args.mode == 'video-stills':
        video_stills(args)
    else:
        edit(args)


if __name__ == '__main__':
    main()
