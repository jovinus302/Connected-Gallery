"""Reopen the delivered Blender edit and verify its complete media references."""
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT/'docs/presentations/astra-film/v3'
SOURCE = ROOT/'docs/presentations/astra-film/v2/connected-gallery-astra.mp4'
checks = []


def check(name, passed, evidence):
    checks.append(dict(name=name, passed=bool(passed), evidence=evidence))


bpy.ops.wm.open_mainfile(filepath=str(DEST/'connected-gallery-edit.blend'))
scene = bpy.context.scene
strips = list(scene.sequence_editor.strips)
check('Final edit is 2400 frames', scene.frame_start == 1 and scene.frame_end == 2400, [scene.frame_start,scene.frame_end])
movie = next(s for s in strips if s.type=='MOVIE')
path = Path(bpy.path.abspath(movie.filepath)).resolve()
check('Source video uses portable relative path and starts after introduction',
      movie.filepath.startswith('//') and path == SOURCE.resolve() and movie.frame_start == 169 and movie.frame_final_end == 2401,
      {'path':movie.filepath,'first':movie.frame_start,'end_exclusive':movie.frame_final_end})
images = next(s for s in strips if s.type=='IMAGE')
directory = Path(bpy.path.abspath(images.directory))
missing = [e.filename for e in images.elements if not (directory/e.filename).is_file()]
check('All 2400 overlay frames resolve relative to the edit', len(images.elements)==2400 and not missing and images.directory.startswith('//'),
      {'directory':images.directory,'count':len(images.elements),'missing':missing[:5]})
sounds = [s for s in strips if s.type=='SOUND']
main = next(s for s in sounds if s.frame_start==169)
lead = next(s for s in sounds if s.frame_start==1)
check('Main audio remains aligned with the source video',
      Path(bpy.path.abspath(main.sound.filepath)).resolve()==SOURCE.resolve() and main.frame_final_end==2401 and main.volume==1,
      {'first':main.frame_start,'end_exclusive':main.frame_final_end,'volume':main.volume})
check('Intro lead-in ends where source sound begins', lead.frame_final_end==169, lead.frame_final_end)
bpy.ops.wm.open_mainfile(filepath=str(DEST/'connected-gallery-roles.blend'))
fonts = {o.data.font.name:o.data.font for o in bpy.context.scene.objects if o.type=='FONT'}
check('All used fonts are packed into the 3D scene', all(f.packed_file for f in fonts.values()), list(fonts))
result = dict(verdict='PASS' if all(c['passed'] for c in checks) else 'FAIL',checks=checks)
(DEST/'delivery-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
if result['verdict'] != 'PASS':
    raise SystemExit(1)
