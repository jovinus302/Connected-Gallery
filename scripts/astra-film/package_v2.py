"""Package the finished second edit with a complete, portable image sequence."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/presentations/astra-film/v2'
OUT=ROOT/'outputs/astra-film/v2'
for name in ('scene-validation.json','media-validation.json','delivery-validation.json'):
    assert json.loads((DEST/name).read_text(encoding='utf-8'))['verdict']=='PASS',name
count=int(json.loads((DEST/'timeline.json').read_text(encoding='utf-8'))['duration'])*24
frames=[OUT/'frames'/f'frame_{i:04d}.png' for i in range(1,count+1)]
assert all(p.is_file() for p in frames)
files=[p for p in DEST.iterdir() if p.is_file() and p.suffix!='.blend1' and p.name!='package-validation.json']
files += frames+[OUT/'score.wav',OUT/'frames/render-evidence.json']
files += [ROOT/'scripts/astra-film'/name for name in ['film.py','film_v2.py','score_v2.py','verify_media.py','verify_v2.py','verify_media_v2.py','verify_delivery_v2.py','package_v2.py']]
files += [ROOT/'docs/presentations/agent-loop/assets'/name for name in ['gallery.png','concept.png']]
files += [DEST.parent/name for name in ['sources.md','scenario.md']]
files=sorted(set(files));target=OUT/'connected-gallery-astra-v2-production.zip'
with zipfile.ZipFile(target,'w',allowZip64=True) as z:
    for p in files:
        z.write(p,p.relative_to(ROOT).as_posix(),compress_type=zipfile.ZIP_STORED if p.suffix in ('.png','.mp4','.blend','.wav') else zipfile.ZIP_DEFLATED)
        if p.suffix=='.png' and p.stem.endswith('00'):print('PACKED',p.name,flush=True)
with zipfile.ZipFile(target) as z:
    bad=z.testzip();entries=len(z.infolist())
assert bad is None,bad
h=hashlib.sha256()
with target.open('rb') as stream:
    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
report={'verdict':'PASS','archive':str(target.relative_to(ROOT)),'bytes':target.stat().st_size,
        'sha256':h.hexdigest(),'entries':entries,'png_frames':len(frames),'crc_test':'all members passed',
        'contents':f'Full v2 movie, editable 3D scene, VSE edit, all {count} PNGs, PCM score, source photographs, source notes and reproduction scripts.'}
(DEST/'package-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
