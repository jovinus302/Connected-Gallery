"""Verify the produced PNG sequence, MP4 timing/tracks, and original PCM audio."""
import argparse
import hashlib
import json
import struct
import wave
from pathlib import Path

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/presentations/astra-film'
OUT=ROOT/'outputs/astra-film'

def boxes(data):
    offset=0
    while offset+8<=len(data):
        size,kind=struct.unpack_from('>I4s',data,offset)
        header=8
        if size==1:size=struct.unpack_from('>Q',data,offset+8)[0];header=16
        if size==0:size=len(data)-offset
        if size<header or offset+size>len(data):raise ValueError('Invalid MP4 box size')
        yield kind.decode('ascii'),data[offset+header:offset+size]
        offset+=size

def child(data,kind):return next(b for k,b in boxes(data) if k==kind)
def timing(data):
    at=20 if data[0]==1 else 12
    scale=struct.unpack_from('>I',data,at)[0]
    duration=struct.unpack_from('>Q' if data[0]==1 else '>I',data,at+4)[0]
    return {'timescale':scale,'ticks':duration,'seconds':duration/scale}

def inspect_mp4(path):
    data=path.read_bytes();moov=child(data,'moov');tracks=[]
    for kind,track in boxes(moov):
        if kind!='trak':continue
        tkhd=child(track,'tkhd');mdia=child(track,'mdia')
        handler=child(mdia,'hdlr')[8:12].decode('ascii')
        stbl=child(child(mdia,'minf'),'stbl')
        stts=child(stbl,'stts');count=struct.unpack_from('>I',stts,4)[0]
        entries=[struct.unpack_from('>II',stts,8+i*8) for i in range(count)]
        codec,description=next(boxes(child(stbl,'stsd')[8:]))
        row={'kind':handler,'codec':codec,'timing':timing(child(mdia,'mdhd')),
             'sample_count':struct.unpack_from('>I',child(stbl,'stsz'),8)[0],
             'sample_duration_entries':entries}
        if handler=='vide':
            row['width'],row['height']=[v/65536 for v in struct.unpack_from('>II',tkhd,len(tkhd)-8)]
            row['fps']=sum(c for c,d in entries)/row['timing']['seconds']
        if handler=='soun':
            row['channels']=struct.unpack_from('>H',description,16)[0]
            row['sample_rate']=struct.unpack_from('>I',description,24)[0]/65536
        tracks.append(row)
    return {'path':str(path.relative_to(ROOT)),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'duration':timing(child(moov,'mvhd')),'tracks':tracks}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--preview',action='store_true');args=ap.parse_args()
    folder=OUT/('preview-frames' if args.preview else 'frames')
    movie=OUT/'preview.mp4' if args.preview else DEST/'connected-gallery-astra.mp4'
    checks=[]
    def check(name,ok,evidence):checks.append({'claim':name,'pass':bool(ok),'evidence':evidence})
    frames=sorted(folder.glob('frame_*.png'))
    check('Every frame exists in order',[p.name for p in frames]==['frame_%04d.png'%i for i in range(1,1297)],len(frames))
    sizes=set();bad=[];hashes=[];black=[]
    for p in frames:
        try:
            with Image.open(p) as im:
                sizes.add(im.size);im.verify()
            with Image.open(p) as im:
                tiny=np.asarray(im.resize((64,36)).convert('RGB'))
                if tiny.max()<10:black.append(p.name)
            hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
        except Exception as exc:bad.append([p.name,str(exc)])
    check('All PNGs decode',not bad,bad)
    check('No empty black output',not black,black)
    check('Consistent image resolution',sizes==({(480,270)} if args.preview else {(1920,1080)}),list(sizes))
    mp4=inspect_mp4(movie)
    v=next(t for t in mp4['tracks'] if t['kind']=='vide')
    a=next(t for t in mp4['tracks'] if t['kind']=='soun')
    expected=(480,270) if args.preview else (1920,1080)
    check('H.264 / 1296 frames / 24 fps / 54 seconds',v['codec']=='avc1' and v['sample_count']==1296 and
          v['fps']==24 and v['timing']['seconds']==54 and (v['width'],v['height'])==expected,v)
    check('AAC stereo / 48 kHz soundtrack',a['codec']=='mp4a' and a['channels']==2 and a['sample_rate']==48000,a)
    with wave.open(str(OUT/'score.wav'),'rb') as wav:
        n,rate,channels=wav.getnframes(),wav.getframerate(),wav.getnchannels()
        pcm=np.frombuffer(wav.readframes(n),dtype=np.int16).astype(np.float64)/32768
    check('Original PCM is exactly 54 seconds with headroom',n==54*rate and channels==2 and np.abs(pcm).max()<.72,
          {'seconds':n/rate,'rate':rate,'channels':channels,'peak_dbfs':20*np.log10(np.abs(pcm).max())})
    # Static holds are intentional; the last card must be a literal 2.5 second hold.
    # Preview renders can differ by numerical noise; the final uses exact pose reuse.
    if not args.preview:
        check('Credit card is unchanged for the last 60 rendered frames',len(set(hashes[-60:]))==1,len(set(hashes[-60:])))
        evidence=json.loads((folder/'render-evidence.json').read_text())
        bad_reuse=[]
        for row in evidence['held_frames']:
            source=int(Path(row['source']).stem.split('_')[1])
            if hashes[row['frame']-1]!=hashes[source-1]:bad_reuse.append(row['frame'])
        check('Exact-pose holds reuse matching image bytes',not bad_reuse,{'holds':len(evidence['held_frames']),'bad':bad_reuse})
    result={'verdict':'PASS' if all(c['pass'] for c in checks) else 'FAIL','checks':checks,'mp4':mp4,
            'unique_frame_hashes':len(set(hashes)),'limitations':'No audience study; audio levels are measured, not a listening-panel verdict.'}
    target=OUT/('preview-validation.json' if args.preview else 'media-validation.json')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('MEDIA_VALIDATION',result['verdict'],len(checks),'checks',flush=True)
    for c in checks:
        if not c['pass']:print('FAILED',c,flush=True)
    if result['verdict']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
