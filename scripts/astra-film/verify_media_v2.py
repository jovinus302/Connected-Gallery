"""Media checks for the continuous second edit; no perceptual-quality score."""
import argparse
import hashlib
import json
import math
import wave
from pathlib import Path

import numpy as np
from PIL import Image
from verify_media import inspect_mp4

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/presentations/astra-film/v2'
OUT=ROOT/'outputs/astra-film/v2'
full_seconds=int(json.loads((DEST/'timeline.json').read_text(encoding='utf-8'))['duration'])
p=argparse.ArgumentParser();p.add_argument('--preview',action='store_true');p.add_argument('--preview-from-final',action='store_true');p.add_argument('--seconds',type=int,default=full_seconds)
a=p.parse_args();seconds=a.seconds;count=seconds*24
is_preview=a.preview or a.preview_from_final
folder=OUT/('preview-frames' if a.preview and not a.preview_from_final else 'frames')
movie=OUT/'preview.mp4' if is_preview else DEST/'connected-gallery-astra.mp4'
checks=[]
def check(name,ok,evidence):checks.append(dict(claim=name,passed=bool(ok),evidence=evidence))
files=[folder/f'frame_{i:04d}.png' for i in range(1,count+1)]
check('All expected image frames exist',all(f.exists() for f in files),{'frames':count})
bad=[];sizes=set();hashes=[]
for path in files:
    try:
        with Image.open(path) as im:sizes.add(im.size);im.verify()
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception as exc:bad.append([path.name,str(exc)])
check('All image frames decode',not bad,bad)
source_size=(960,540) if a.preview and not a.preview_from_final else (1920,1080)
video_size=(960,540) if is_preview else (1920,1080)
check('Consistent source image resolution',sizes=={source_size},list(sizes))
mp4=inspect_mp4(movie);v=next(x for x in mp4['tracks'] if x['kind']=='vide');audio=next(x for x in mp4['tracks'] if x['kind']=='soun')
check('H.264, 24 fps, resolution and the full authored duration',v['codec']=='avc1' and v['sample_count']==count and v['fps']==24 and v['timing']['seconds']==seconds and (v['width'],v['height'])==video_size,
      v)
check('AAC stereo at 48 kHz',audio['codec']=='mp4a' and audio['channels']==2 and audio['sample_rate']==48000,audio)
with wave.open(str(OUT/'score.wav'),'rb') as w:
    n,sr,ch=w.getnframes(),w.getframerate(),w.getnchannels()
    data=np.frombuffer(w.readframes(n),dtype='<i2').astype(np.float64)/32768
check('Original score matches the full duration with headroom',n==full_seconds*sr and sr==48000 and ch==2 and np.abs(data).max()<.51,
      {'duration':n/sr,'peak_dbfs':20*math.log10(float(np.abs(data).max())),'clipped_samples':int(np.count_nonzero(np.abs(data)>=1))})
if not is_preview:
    check('The four-second end credit remains identical',len(set(hashes[-96:]))==1,len(set(hashes[-96:])))
    check('Continuous actions are not a sequence of long static holds',len(set(hashes[:-96]))>1200,{'distinct_frames_before_credit':len(set(hashes[:-96]))})
report={'verdict':'PASS' if all(x['passed'] for x in checks) else 'FAIL','checks':checks,'mp4':mp4,'source_frames':str(folder.relative_to(ROOT)),
        'limitation':'Timing and successful decoding do not prove natural motion, comprehension, or perceptual sound quality.'}
target=DEST/('preview-validation.json' if is_preview else 'media-validation.json')
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('V2_MEDIA',report['verdict'],len(checks),'checks',flush=True)
for c in checks:
    if not c['passed']:print('FAILED',c,flush=True)
if report['verdict']!='PASS':raise SystemExit(1)
