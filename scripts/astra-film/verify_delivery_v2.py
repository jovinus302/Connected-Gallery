"""Read the final editable delivery and verify its linked sequence and packed inputs."""
import hashlib
import json
from pathlib import Path
import bpy

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/presentations/astra-film/v2'
OUT=ROOT/'outputs/astra-film/v2'
count=int(json.loads((DEST/'timeline.json').read_text(encoding='utf-8'))['duration'])*24
bpy.ops.wm.open_mainfile(filepath=str(DEST/'connected-gallery-edit.blend'))
sc=bpy.context.scene
checks=[]
def check(name,ok,evidence):checks.append(dict(claim=name,passed=bool(ok),evidence=evidence))
images=[s for s in sc.sequence_editor.strips if s.type=='IMAGE']
sounds=[s for s in sc.sequence_editor.strips if s.type=='SOUND']
check('Final edit contains the complete frame sequence',len(images)==1 and len(images[0].elements)==count,{'strips':len(images),'frames':len(images[0].elements) if images else 0})
if images:
    folder=Path(bpy.path.abspath(images[0].directory))
    missing=[e.filename for e in images[0].elements if not (folder/e.filename).is_file()]
    check('All relative image paths resolve',not missing,{'missing':missing,'directory':str(folder.relative_to(ROOT))})
expected=hashlib.sha256((OUT/'score.wav').read_bytes()).hexdigest()
actual=[hashlib.sha256(s.sound.packed_file.data).hexdigest() if s.sound.packed_file else None for s in sounds]
check('Final soundtrack is the exact packed generated score',actual==[expected],actual)
sheet=bpy.data.images['Original six-photo sheet']
check('Original source sheet is embedded without alteration',sheet.packed_file and hashlib.sha256(sheet.packed_file.data).hexdigest()==hashlib.sha256((ROOT/'docs/presentations/agent-loop/assets/gallery.png').read_bytes()).hexdigest(),sheet.name)
fonts=[f for f in bpy.data.fonts if not f.name.startswith('Bfont')]
check('Both Korean fonts are embedded',len(fonts)==2 and all(f.packed_file for f in fonts),[f.name for f in fonts])
check('Editable sequence duration and frame rate match delivery',sc.frame_end==count and sc.render.fps==24,{'last_frame':sc.frame_end,'fps':sc.render.fps})
check('The editable 3D scene is also preserved',any('persistent_agent' in o for o in bpy.data.objects),len(bpy.data.objects))
report={'verdict':'PASS' if all(c['passed'] for c in checks) else 'FAIL','checks':checks}
(DEST/'delivery-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('V2_DELIVERY',report['verdict'],len(checks),'checks',flush=True)
for c in checks:
    if not c['passed']:print('FAILED',c,flush=True)
if report['verdict']!='PASS':raise SystemExit(1)
