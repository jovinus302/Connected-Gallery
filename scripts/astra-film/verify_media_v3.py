"""Check delivered v3 media and every rendered RGBA overlay frame."""
import hashlib
import json
from pathlib import Path

from PIL import Image
from verify_media import inspect_mp4

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT/'docs/presentations/astra-film/v3'
OUT = ROOT/'outputs/astra-film/v3'
manifest = json.loads((DEST/'timeline.json').read_text(encoding='utf-8'))
checks = []


def check(name, passed, evidence):
    checks.append(dict(name=name, passed=bool(passed), evidence=evidence))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1048576), b''):
            h.update(part)
    return h.hexdigest()


movie = DEST/'connected-gallery-astra.mp4'
info = inspect_mp4(movie)
check('MP4 contains H.264 video and AAC sound',
      {r['codec'] for r in info['tracks']} == {'avc1','mp4a'}, info)
video = next(t for t in info['tracks'] if t['kind']=='vide')
audio = next(t for t in info['tracks'] if t['kind']=='soun')
check('Video is 100 seconds and 2400 frames', video['sample_count']==2400 and abs(video['timing']['seconds']-100)<.01, video)
check('Video is native 1920×1080 at 24fps', (video['width'],video['height'],video['fps']) == (1920,1080,24),
      [video['width'],video['height'],video['fps']])
check('Audio covers the complete edit', abs(audio['timing']['seconds']-100)<.1, audio)
bad = []
for n in range(1,2401):
    path = OUT/'overlay'/f'frame_{n:04d}.png'
    try:
        with Image.open(path) as im:
            if im.size != (1920,1080) or im.mode != 'RGBA':
                bad.append([n,'wrong dimensions or mode'])
            alpha = im.getchannel('A')
            box = alpha.getbbox()
            if 169 <= n <= 2304:
                if box is None or box[0]<1430 or box[1]<10 or box[2]>1895 or box[3]>171:
                    bad.append([n,'outside corner',box])
            elif n >= 2305 and box is not None:
                bad.append([n,'overlay obscures end card'])
            elif n <= 168 and alpha.getextrema() != (255,255):
                bad.append([n,'incomplete intro backdrop'])
    except Exception as exc:
        bad.append([n,str(exc)])
check('All 2400 overlays decode and respect introduction/corner/end-card bounds', not bad, {'violations':bad[:12],'count':len(bad)})
for name, expected in manifest['source_sha256'].items():
    check('Original v2 input unchanged: '+name, sha(DEST.parent/'v2'/name)==expected, expected)
record = json.loads((OUT/'overlay/render-settings.json').read_text())
check('Rendered frames use delivered scene', record['scene_sha256']==sha(DEST/'connected-gallery-roles.blend'), record)
result = dict(verdict='PASS' if all(c['passed'] for c in checks) else 'FAIL',
              movie_sha256=sha(movie), bytes=movie.stat().st_size, checks=checks)
(DEST/'media-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
if result['verdict'] != 'PASS':
    raise SystemExit(1)
