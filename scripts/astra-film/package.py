"""Package the verified film and its editable sources without unrelated files."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/presentations/astra-film'
OUT=ROOT/'outputs/astra-film'

def sha_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def main():
    for name in ['scene-validation.json','media-validation.json']:
        report=json.loads((OUT/name).read_text(encoding='utf-8'))
        if report['verdict']!='PASS':raise RuntimeError('Package requires passing '+name)
    for name in ['scene-validation.json','media-validation.json','audio-validation.json','preview-validation.json']:
        (DEST/name).write_bytes((OUT/name).read_bytes())
    files=sorted(p for p in DEST.iterdir() if p.is_file() and p.suffix not in ('.blend1','.blend2') and p.name!='.gitignore')
    files+=sorted((ROOT/'scripts/astra-film').glob('*.py'))
    files+=[ROOT/'docs/presentations/agent-loop/assets/gallery.png',ROOT/'docs/presentations/agent-loop/assets/concept.png',OUT/'score.wav']
    files+=sorted((OUT/'frames').glob('frame_*.png'))
    files+=[OUT/'frames/render-evidence.json']
    if len(list((OUT/'frames').glob('frame_*.png')))!=1296:raise RuntimeError('Missing final frames')
    manifest=[]
    for p in files:
        manifest.append({'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha_file(p)})
    archive=OUT/'connected-gallery-astra-production.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
        z.writestr('production-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip()
        if bad:raise RuntimeError('Archive CRC failed: '+bad)
        entries=len(z.infolist())
    result={'archive':str(archive),'bytes':archive.stat().st_size,'entries':entries,'crc_check':'PASS',
            'sha256':sha_file(archive)}
    (OUT/'package-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PACKAGE_COMPLETE',json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
