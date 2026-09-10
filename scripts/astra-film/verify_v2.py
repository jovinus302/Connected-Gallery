"""Read evaluated geometry; report motion, contact and semantic evidence separately."""
import json
import math
import argparse
import sys
from pathlib import Path
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/presentations/astra-film/v2'
p=argparse.ArgumentParser();p.add_argument('--scene',default=str(DEST/'connected-gallery-astra.blend'));p.add_argument('--report',default=str(DEST/'scene-validation.json'))
args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
bpy.ops.wm.open_mainfile(filepath=args.scene)
sc=bpy.context.scene
events=json.loads(sc['events']);contacts=json.loads(sc['contacts']);captions=json.loads(sc['captions'])
actors={o['persistent_agent']:o for o in bpy.data.objects if 'persistent_agent' in o}
moving_objects={name:actors[name] for name in ('Explorer','Reviewer')}
moving_objects.update({f'Organizer {i}':bpy.data.objects['Organizer / moving stone '+str(i)] for i in range(3)})
checks=[];motions={k:[] for k in moving_objects};errors=[]
def check(name,ok,evidence):checks.append(dict(claim=name,passed=bool(ok),evidence=evidence))
def fingertip(actor,side):
    children=sorted([o for o in actor.children if 'Gripping fingertip' in o.name],key=lambda o:o.name)
    return children[0 if side==-1 else 1]
def point(obj,side):
    return obj.matrix_world@Vector((side*float(obj['width'])*.5,-.10,-float(obj['height'])*.5-.025))

camera_positions=[]
for frame in range(1,int((sc['duration_seconds']-4)*24)+1):
    sc.frame_set(frame);t=(frame-1)/24
    camera_positions.append(tuple(sc.camera.matrix_world.translation))
    for name in motions:motions[name].append(tuple(moving_objects[name].matrix_world.translation))
    for c in contacts:
        if not (c['grip_start']+.045<=t<=c['grip_end']-.045):continue
        obj=bpy.data.objects[c['object']]
        hand=bpy.data.objects['Organizer / photo grip '+str(c['stone'])] if c['actor']=='Organizer' else fingertip(actors[c['actor']],-1 if c['side']==1 else 1)
        distance=(hand.matrix_world.translation-point(obj,c['side'])).length
        if distance>.025:errors.append(dict(frame=frame,actor=c['actor'],object=c['object'],distance=round(distance,5)))
check('One persistent camera has no reset between actions',len(set(camera_positions))==1,len(set(camera_positions)))
check('Same two articulated agents and one Organizer persist',set(actors)=={'Explorer','Reviewer','Organizer'},list(actors))
stats={}
routes=json.loads(sc['routes'])
for name,positions in motions.items():
    distances=[(Vector(b)-Vector(a)).length for a,b in zip(positions,positions[1:])]
    max_i=max(range(len(distances)),key=distances.__getitem__)
    stats[name]=dict(total_distance=sum(distances),max_frame_step=distances[max_i],max_step_time=(max_i+1)/24,
                     moving_frames=sum(d>.004 for d in distances),frames=len(distances))
    worst_t=(max_i+1)/24
    if name in actors:print('WORST_ROUTE',name,[r for r in routes[actors[name].name] if abs(r[0]-worst_t)<1.1],flush=True)
check('Agent motion is present across the film',all(stats[n]['moving_frames']>450 for n in ('Explorer','Reviewer')),stats)
check('No frame-to-frame agent jump exceeds 0.45 stage units',all(v['max_frame_step']<.45 for v in stats.values()),stats)
check('Hands follow the photo during authored contact',not errors,{'failed_samples':len(errors),'examples':errors[:20]})
curve_errors=[]
for frame in [108,175,205,275,320,445,640,890,1270,1550,1840,1940]:
    sc.frame_set(frame)
    for ob in bpy.data.objects:
        if ob.type!='CURVE' or ob.hide_render or not any(n in ob.name for n in ('articulated','stepping limb')):continue
        coords=[p.co for p in ob.data.splines[0].bezier_points]
        low=[min(p[i] for p in coords)-.28 for i in range(3)]
        high=[max(p[i] for p in coords)+.28 for i in range(3)]
        evaluated=ob.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
        if any(any(v.co[i]<low[i] or v.co[i]>high[i] for i in range(3)) for v in mesh.vertices):
            curve_errors.append([frame,ob.name])
        evaluated.to_mesh_clear()
check('Evaluated arms stay around their current contact path without false loops',not curve_errors,curve_errors)
overlaps=[]
blue=next(o for o in actors['Explorer'].children if 'organic body' in o.name)
glass=next(o for o in actors['Reviewer'].children if 'thick amber glass' in o.name)
for frame in range(385,490):
    sc.frame_set(frame)
    bounds=[]
    for ob in (blue,glass):
        coords=[ob.matrix_world@Vector(co) for co in ob.bound_box]
        bounds.append(([min(v[i] for v in coords) for i in range(3)],[max(v[i] for v in coords) for i in range(3)]))
    separated=any(bounds[0][1][i]<bounds[1][0][i] or bounds[1][1][i]<bounds[0][0][i] for i in range(3))
    if not separated:overlaps.append(frame)
check('The two bodies stay separated during feedback and departure',not overlaps,overlaps)
check('One main sentence stays at least four seconds',all(b-a>=4 for a,b,_ in captions),
      {'count':len(captions),'durations':[b-a for a,b,_ in captions]})
flows={}
for e in events:
    if 'flow' in e:flows.setdefault(e['flow'],[]).append(e)
expected={'wine / first':[4,3],'wine / refined':[1,2],'restaurant / whole-photo context':[3,4],
          'person / new Connect':[3,5],'beach / whole-photo context':[1,3]}
for name,ids in expected.items():
    rows=flows.get(name,[])
    order=[r['kind'] for r in rows]
    ok=order==['request','opaque_list','inspect_request','images_observed'] and all(r.get('ids',r.get('candidates'))==ids for r in rows)
    check('Separate acquisition / '+name,ok,rows)
    observed=next(r for r in rows if r['kind']=='images_observed')
    sc.frame_set(round(observed['time']*24)+5)
    actual=sorted(o['photo_id'] for o in bpy.data.objects if o.get('whole_image') and name in o.name and not o.hide_render)
    check('Acquired image meshes / '+name,actual==sorted(ids),actual)
reviews=[e for e in events if e['kind']=='independent_review']
check('Every acquired candidate has an independent review',
      [(e['anchor'],e['candidate'],e['passed']) for e in reviews]==[(0,4,False),(0,3,False),(0,1,True),(0,2,True),
        (1,3,True),(1,4,True),(1,3,True),(1,5,True),(5,1,True),(5,3,True)],reviews)
sc.frame_set(round(18.5*24)+1)
feedback=sorted(set(o['photo_id'] for o in bpy.data.objects if 'photo_id' in o and not o.hide_render))
check('Feedback retains original and both unsupported candidates',feedback==[0,3,4],feedback)
retry=[e for e in events if e['kind']=='conditional_retry']
check('One qualified retry retains wine selection',len(retry)==1 and retry[0]['anchor']==0 and len(retry[0]['conditions'])==4,retry)
sc.frame_set(2041)
edges=[list(o['edge_ids']) for o in bpy.data.objects if 'edge_ids' in o and not o.hide_render]
check('Final path has exactly five supported edges',sorted(edges)==sorted([[0,1],[0,2],[1,4],[1,5],[5,3]]),edges)
photos=sorted(o['photo_id'] for o in bpy.data.objects if o.get('whole_image') and not o.hide_render)
check('Six actual photos remain in final path',photos==list(range(6)),photos)
check('Original photograph sheet and editable fonts are embedded',
      bpy.data.images['Original six-photo sheet'].packed_file is not None and all(font.packed_file for font in bpy.data.fonts if not font.name.startswith('Bfont')),
      {'fonts':[font.name for font in bpy.data.fonts]})
report={'verdict':'PASS' if all(x['passed'] for x in checks) else 'FAIL','checks':checks,
        'limits':'Geometry, sequence, and timing checks do not establish natural acting or viewer comprehension. Continuous playback must be assessed separately.'}
Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('V2_SCENE',report['verdict'],json.dumps(stats),flush=True)
for row in checks:
    if not row['passed']:print('FAILED',json.dumps(row,ensure_ascii=False),flush=True)
if report['verdict']!='PASS':raise SystemExit(1)
