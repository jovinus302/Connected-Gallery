"""Quiet original score, with contact sounds aligned to the second edit."""
import json
import math
import wave
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/astra-film/v2'
DEST=ROOT/'docs/presentations/astra-film/v2'
timeline=json.loads((DEST/'timeline.json').read_text(encoding='utf-8'))
SR,SECONDS=48000,int(timeline['duration'])
rng=np.random.default_rng(20260911)
music=np.zeros((SR*SECONDS,2),dtype=np.float32)
foley=np.zeros_like(music)


def add(track,sig,start,level=.02,pan=0):
    i=round(start*SR);n=min(len(sig),len(track)-i)
    if n<=0:return
    track[i:i+n,0]+=sig[:n]*math.cos((pan+1)*math.pi/4)*level
    track[i:i+n,1]+=sig[:n]*math.sin((pan+1)*math.pi/4)*level


def note(track,midi,start,dur,level,pan=0,pad=False):
    t=np.arange(round(dur*SR))/SR;hz=440*2**((midi-69)/12)
    if pad:env=np.minimum(1,t/1.5)*np.minimum(1,(dur-t)/2)
    else:env=(1-np.exp(-t*65))*np.exp(-t*3.8)*np.minimum(1,(dur-t)/.15)
    sig=(np.sin(2*np.pi*hz*t)+.13*np.sin(2*np.pi*hz*2.001*t))*env
    add(track,sig,start,level,pan)


for start,chord in [(0,[50,57,61,66]),(15,[47,54,57,62]),(29,[43,50,57,61]),
                    (43,[50,57,62,66]),(57,[47,54,61,66]),(70,[43,55,62,69]),(82,[50,57,62,66])]:
    for i,n in enumerate(chord):note(music,n,start,min(17,SECONDS-start),.018,(i-1.5)*.3,True)
for i,t in enumerate(np.arange(2.0,SECONDS-4,2.4)):
    note(music,[74,69,73,78,76,69][i%6],float(t),1.1,.010,math.sin(i)*.5)

sounds=[]
for c in timeline['contacts']:
    if c.get('look'):continue
    when=c['grip_end'];n=round(.13*SR);t=np.arange(n)/SR
    if c['actor']=='Organizer':
        sig=np.sin(2*np.pi*110*t)*np.exp(-t*43)
        add(foley,sig,when,.024,0)
    else:
        noise=rng.normal(0,1,n)
        sig=np.convolve(noise,np.ones(13)/13,mode='same')*np.sin(np.pi*t/.13)**2
        add(foley,sig,when,.025,-.2)
    sounds.append({'time':when,'kind':'contact_settle','actor':c['actor']})
for e in timeline['events']:
    if e['kind']=='user_selection':
        note(foley,81,e['time']+.2,.25,.030,-.2)
        sounds.append({'time':e['time']+.2,'kind':'user_tap'})
    if e['kind']=='independent_review':
        note(foley,81 if e['passed'] else 66,e['end']-.25,.45,.014,.15)
for n,delta in [(74,0),(81,.25),(86,.5)]:note(music,n,SECONDS-4+delta,1.8,.020)

mix=music+foley
fade=np.minimum(np.minimum(1,np.arange(len(mix))/(SR*.8)),np.minimum(1,(len(mix)-1-np.arange(len(mix)))/(SR*2)))
mix*=fade[:,None]
mix*=10**(-6/20)/max(1e-9,float(np.abs(mix).max()))
OUT.mkdir(parents=True,exist_ok=True)
pcm=np.round(mix*32767).astype('<i2')
with wave.open(str(OUT/'score.wav'),'wb') as w:
    w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR);w.writeframes(pcm.tobytes())
report={'seconds':SECONDS,'sample_rate':SR,'channels':2,'peak_dbfs':20*np.log10(float(np.abs(mix).max())),
        'rms_dbfs':20*np.log10(float(np.sqrt(np.mean(mix**2)))),'clipped_samples':int(np.count_nonzero(np.abs(mix)>=1)),
        'source':'Original deterministic synthesis; no samples, narration, environmental recordings, or external services.',
        'change':'Sparse notes; no decorative request/return arpeggios. Foley occurs at authored contact release.',
        'events':sounds}
(DEST/'audio-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=False))
