"""Read the saved Blender scene and check film-specific observable invariants."""
import hashlib
import json
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'docs/presentations/astra-film'
OUT = ROOT / 'outputs/astra-film'
bpy.ops.wm.open_mainfile(filepath=str(DEST / 'connected-gallery-astra.blend'))
scene = bpy.context.scene
shots = json.loads(scene['shot_manifest'])

# This oracle records the approved story's visible whole photographs, separately
# from the builder. Cropped insets can repeat a source but cannot add photographs.
EXPECTED = {
    'S01':[0], 'S02':[0], 'S03':[0], 'S04':[], 'S05':[],
    'S06':[3,4], 'S07':[0,4], 'S08':[0,3], 'S09':[0,3,4],
    'S10':[0], 'S11':[], 'S12':[1,2], 'S13':[0,1], 'S14':[0,2],
    'S15':[1,2], 'S16':[1], 'S17':[1], 'S18':[1,3,4],
    'S19a':[1,3], 'S19b':[1,4], 'S20':[1,3,4], 'S21':[1],
    'S22':[1], 'S23':[3,5], 'S24a':[1,3], 'S24b':[1,5],
    'S24c':[3,5], 'S25':[5], 'S26':[5], 'S27':[1,3,5],
    'S28a':[1,5], 'S28b':[3,5], 'S29':[1,3,5], 'S30':[0,1,2,3,4,5], 'S31':[],
}
checks = []
def check(name, ok, evidence):
    checks.append({'claim':name, 'pass':bool(ok), 'evidence':evidence})

check('54 seconds / 24 fps / 1080p',
      (scene.frame_start,scene.frame_end,scene.render.fps,scene.render.resolution_x,scene.render.resolution_y)==(1,1296,24,1920,1080),
      {'frames':[scene.frame_start,scene.frame_end],'fps':scene.render.fps,'size':[scene.render.resolution_x,scene.render.resolution_y]})
check('35 contiguous shots', len(shots)==35 and shots[0]['first']==1 and shots[-1]['last']==1296 and
      all(a['last']+1==b['first'] for a,b in zip(shots,shots[1:])),len(shots))
check('Blender Eevee scene',scene.render.engine=='BLENDER_EEVEE',scene.render.engine)

image=bpy.data.images.get('Original six-photo sheet')
source=(ROOT/'docs/presentations/agent-loop/assets/gallery.png').read_bytes()
packed=image.packed_file.data if image and image.packed_file else b''
check('Original source sheet embedded unchanged',packed==source,hashlib.sha256(packed).hexdigest())
used_fonts={o.data.font for o in scene.objects if o.type=='FONT'}
fonts=[{'name':f.name,'packed':bool(f.packed_file)} for f in used_fonts]
check('Korean fonts embedded',len(fonts)==2 and all(f['packed'] for f in fonts),fonts)
sounds=[{'name':s.name,'packed':bool(s.packed_file)} for s in bpy.data.sounds]
check('Original soundtrack embedded',len(sounds)==1 and sounds[0]['packed'],sounds)

geometry=[]
for shot in shots:
    frame=shot['last']-2
    scene.frame_set(frame)
    roots=[o for o in scene.objects if 'photo_id' in o and not o.hide_render]
    actual=sorted(set(o['photo_id'] for o in roots if o['whole_image']))
    check(shot['id']+' whole-photo scope',actual==EXPECTED[shot['id']],{'frame':frame,'actual':actual,'expected':EXPECTED[shot['id']]})
    check(shot['id']+' insets retain available sources',all(o['photo_id'] in EXPECTED[shot['id']] for o in roots),[o['photo_id'] for o in roots if not o['whole_image']])
    for root in roots:
        surface=next(o for o in root.children if o.name.startswith('Actual image'))
        points=[world_to_camera_view(scene,scene.camera,surface.matrix_world@v.co) for v in surface.data.vertices]
        bounds=[min(p.x for p in points),min(p.y for p in points),max(p.x for p in points),max(p.y for p in points)]
        geometry.append({'shot':shot['id'],'photo':root['photo_id'],'whole':bool(root['whole_image']),'bounds':bounds})
        check(shot['id']+' photo '+str(root['photo_id'])+' stays in frame',all(0<p.x<1 and 0<p.y<1 and p.z>0 for p in points),bounds)
    if shot['kind']=='end':
        visible_text=[o.data.body for o in scene.objects if o.type=='FONT' and not o.hide_render]
        check('Credit matches required wording','Made with Astra · Blender / Eevee' in visible_text,visible_text)
    if shot['id'] in ('S04','S05','S11'):
        tokens=[o for o in scene.objects if o.get('is_candidate_token') and not o.hide_render]
        check(shot['id']+' candidate list is opaque and contains no photograph',len(tokens)==2 and not roots,len(tokens))
    if shot['id']=='S30':
        lines=[o for o in scene.objects if 'relationship_kind' in o and not o.hide_render]
        check('Final path has five evidenced edges, not a complete graph',len(lines)==5,len(lines))

end_poses=[]
for frame in range(1237,1297):
    scene.frame_set(frame)
    visible=[o for o in scene.objects if not o.hide_render]
    end_poses.append([(o.name,tuple(round(v,6) for row in o.matrix_world for v in row)) for o in visible])
check('End card holds unchanged for 60 frames',all(p==end_poses[0] for p in end_poses),60)

edit_path=DEST/'connected-gallery-edit.blend'
if edit_path.exists():
    bpy.ops.wm.open_mainfile(filepath=str(edit_path))
    edit=bpy.context.scene
    strips=list(edit.sequence_editor.strips)
    pictures=[s for s in strips if s.type=='IMAGE']
    audio=[s for s in strips if s.type=='SOUND']
    check('Editable VSE contains one complete image sequence',len(pictures)==1 and len(pictures[0].elements)==1296 and pictures[0].frame_final_duration==1296,
          [{'elements':len(s.elements),'duration':s.frame_final_duration} for s in pictures])
    missing=[]
    for strip in pictures:
        folder=Path(bpy.path.abspath(strip.directory))
        missing.extend(e.filename for e in strip.elements if not (folder/e.filename).is_file())
    check('All editable sequence paths resolve',not missing,missing)
    check('Editable VSE soundtrack is embedded',len(audio)==1 and bool(audio[0].sound.packed_file),[s.name for s in audio])
    check('Editable output preserves 54s / 1080p / 24fps',
          (edit.frame_start,edit.frame_end,edit.render.fps,edit.render.resolution_x,edit.render.resolution_y)==(1,1296,24,1920,1080),
          [edit.frame_start,edit.frame_end,edit.render.fps,edit.render.resolution_x,edit.render.resolution_y])

# Find possible title conflicts for visual review rather than calling layout taste a test.
title_candidates=[g for g in geometry if g['whole'] and g['bounds'][3]>.84 and g['bounds'][0]<.7]
report={'verdict':'PASS' if all(c['pass'] for c in checks) else 'FAIL',
        'scope':'Serialized scene and geometry only; not audience comprehension or real model accuracy.',
        'checks':checks,'possible_title_conflicts':title_candidates,
        'camera_projected_photo_bounds':geometry}
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'scene-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('SCENE_VALIDATION',report['verdict'],len(checks),'checks',len(title_candidates),'title candidates',flush=True)
for c in checks:
    if not c['pass']:print('FAILED',c,flush=True)
for g in title_candidates:print('REVIEW_LAYOUT',g,flush=True)
if report['verdict']!='PASS':raise RuntimeError('Saved scene verification failed')
