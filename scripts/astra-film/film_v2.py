"""Continuous, contact-driven second edit. Original film.py stays reproducible."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Euler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import film as f

ROOT = f.ROOT
DEST = ROOT / 'docs/presentations/astra-film/v2'
OUT = ROOT / 'outputs/astra-film/v2'
FPS, LENGTH = 24, 93
FINISH = 89
ROUTES, PROPS, CONTACTS, EVENTS, VIS = {}, {}, [], [], {}
ACTORS, ARMS, STONES, FEET, STONE_ARMS = {}, {}, [], [], []
CAPTIONS = [
    (0, 4, '이 와인, 어디서 봤더라?'),
    (4, 10, '후보를 받아, 사진을 직접 펼쳐봅니다.'),
    (10, 16, '원본과 비교하니, 와인 연결 근거가 부족합니다.'),
    (16, 22, '같은 와인에서, 붉은 원 라벨로 단서를 좁힙니다.'),
    (22, 29, '새 사진도 원본의 라벨과 하나씩 비교합니다.'),
    (29, 33, '확인한 두 장면을, 보기 좋게 정리합니다.'),
    (33, 37, '식당 사진을 열면, 사진 전체가 새 기준이 됩니다.'),
    (37, 41, '이번에는 사진 전체에서 함께 볼 장면을 찾습니다.'),
    (41, 47, '와인이 없어도, 같은 설정 날짜로 이어집니다.'),
    (47, 51, '이번에는, 이 사람의 다른 날이 궁금합니다.'),
    (51, 56, '새로운 선택에서, 다시 사진을 찾아 펼칩니다.'),
    (56, 62, '선택한 사람을 비교하고, 확인한 장면을 모읍니다.'),
    (62, 66, '바닷가에 도착하면, 그 사진에서 다시 시작합니다.'),
    (66, 71, '새 기준으로 찾은 사진도, 직접 보고 비교합니다.'),
    (71, 77, '사진마다 근거를 살펴, 함께 볼 이유를 남깁니다.'),
    (77, 89, '작은 단서 하나에서, 다음 장면으로.'),
]
LEFT = (-3.15, .65, 3.65)
RIGHT = (3.15, .65, 3.65)
WAIT = (5.35, 1.0, 4.85)
SLOT = (3.8, -.1, .78)
PARK = (6.45, 2.2, 4.85)
ALL = dict(id='CONTINUOUS', first=1, last=FPS*LENGTH, start=0, end=LENGTH)


def fr(t): return round(t*FPS)+1
def ease(a): return a*a*(3-2*a)


def curve_pose(arm,coords,frame):
    """Key handles as well as control points; unkeyed handles cause long false loops."""
    points=[Vector(p) for p in coords]
    for i,(bp,co) in enumerate(zip(arm.data.splines[0].bezier_points,points)):
        tangent=(points[min(i+1,len(points)-1)]-points[max(0,i-1)])/(3 if i in (0,len(points)-1) else 6)
        bp.handle_left_type=bp.handle_right_type='FREE'
        bp.co=co;bp.handle_left=co-tangent;bp.handle_right=co+tangent
        for prop in ('co','handle_left','handle_right'):bp.keyframe_insert(prop,frame=frame)


def mark(t, kind, **data):
    EVENTS.append(dict(time=t, frame=fr(t), kind=kind, **data))


def pose(o, t, pos=None, scale=None):
    rows = ROUTES.setdefault(o.name, [])
    prev = rows[-1] if rows else (0, tuple(o.location), tuple(o.scale))
    rows.append((float(t), tuple(pos if pos is not None else prev[1]),
                 (scale,)*3 if isinstance(scale, (int,float)) else tuple(scale if scale is not None else prev[2])))
    rows.sort(key=lambda r:r[0])


def at(o, t):
    rows = ROUTES.get(o.name, [(0, tuple(o.location), tuple(o.scale))])
    if t <= rows[0][0]: return Vector(rows[0][1]), Vector(rows[0][2])
    for a,b in zip(rows, rows[1:]):
        if t <= b[0]:
            u=ease((t-a[0])/(b[0]-a[0])) if b[0]!=a[0] else 1
            return Vector(a[1]).lerp(Vector(b[1]),u), Vector(a[2]).lerp(Vector(b[2]),u)
    return Vector(rows[-1][1]),Vector(rows[-1][2])


def hold(o,t):
    p,s=at(o,t);pose(o,t,p,s)


def visible(o,a,b=FINISH):
    for child in [o,*o.children_recursive]:
        lo,hi=child.get('own_interval',(a,b)) if child!=o else (a,b)
        VIS[child.name]=(max(a,lo),min(b,hi))
    o['visible_seconds']=[a,b]


def photo(pid,name,a,b=FINISH,pos=LEFT,width=4.8,scale=1,crop=None):
    p=f.card(pid,pos,width,ALL,crop=crop,label=crop is None,name=name)
    p.name=name
    p.scale=(scale,)*3
    p['width']=width
    ratio=4/3 if crop is None else (crop[2]-crop[0])/(crop[3]-crop[1])*4/3
    p['height']=width/ratio
    PROPS[p.name]=p
    pose(p,0,pos,scale);visible(p,a,b)
    return p


def token(name,a,b,pos=SLOT):
    o=f.blank(pos,ALL,1.1)
    o.name=name;o['width']=1.1;o['height']=.84
    PROPS[o.name]=o;pose(o,0,pos,.6);visible(o,a,b)
    return o


def edge(o,t,side=-1):
    p,s=at(o,t)
    local=Vector((side*float(o['width'])*.5,-.10,-float(o['height'])*.5-.025))
    return p+Euler((-.2,0,0)).to_matrix() @ Vector([local[i]*s[i] for i in range(3)])


def action(o,a,b,to,scale=None,by='Explorer',side=-1,stone=0):
    """Anticipate, grip, transport with shared trajectory, settle, release."""
    start,ss=at(o,a)
    ramp=min(.3,(b-a)*.18)
    pose(o,a,start,ss);pose(o,a+ramp,start,ss)
    pose(o,b-ramp,to,scale if scale is not None else ss);pose(o,b,to,scale if scale is not None else ss)
    c=dict(object=o.name,actor=by,start=a,end=b,side=side,stone=stone,
           grip_start=a+ramp,grip_end=b-ramp,ramp=ramp)
    CONTACTS.append(c)
    if by!='Organizer':
        actor=ACTORS[by]
        offset=Vector((-.75 if side==-1 else .75,-.40,-.45))
        t0=max(0,a-1.0)
        # A separate earlier pose holds the actor until its approach starts.
        hold(actor,t0)
        p0=edge(o,a+ramp,side)+offset
        p1=edge(o,b-ramp,side)+offset
        p0.z=min(1.35,max(.85,p0.z));p1.z=min(1.35,max(.85,p1.z))
        pose(actor,a+ramp,p0);pose(actor,b-ramp,p1)
    mark(a,'carry',photo=o.get('photo_id',None),actor=by,until=b)


def go(actor,a,b,p):
    hold(ACTORS[actor],a);pose(ACTORS[actor],b,p)


def outline(o,box,a,b,color='blue'):
    ob=f.rectangle(o,box,float(o['width']),float(o['height']),f.MATS[color],.021)
    VIS[ob.name]=(a,b)
    ob['own_interval']=[a,b]
    return ob


def pointer(o,t,box):
    shot={**ALL,'first':fr(t),'last':fr(t+1)}
    w,h=float(o['width']),float(o['height'])
    point=((box[0]+box[2]-1)/2*w,-.20,(.5-(box[1]+box[3])/2)*h+.05)
    cu_before=set(bpy.data.objects)
    f.cursor_on(o,point,shot)
    for child in set(bpy.data.objects)-cu_before:
        VIS[child.name]=(t,t+.65)
        child['own_interval']=[t,t+.65]
    mark(t,'user_selection',photo=o['photo_id'],scope='whole' if box==(0,0,1,1) else 'object')


def checked(o,t,passed=True):
    before=set(bpy.data.objects)
    sign=f.empty('Claim status / checked' if passed else 'Claim status / unsupported')
    f.parent(sign,o,(0,-.12,0))
    x,z=float(o['width'])*.43,-float(o['height'])/2-.08
    material=f.MATS['blue' if passed else 'amber_edge']
    coords=[(x-.13,0,z),(x-.035,0,z-.08),(x+.14,0,z+.13)] if passed else [(x-.12,0,z),(x+.12,0,z)]
    f.tube('Confirmed mark' if passed else 'Unsupported mark',coords,.022,material,sign)
    for ob in set(bpy.data.objects)-before:
        VIS[ob.name]=(t,float(o['visible_seconds'][1]))
        ob['own_interval']=[t,float(o['visible_seconds'][1])]


def review(source,candidate,a,b,kind='label',passed=True):
    """The same reviewer leans toward reference then candidate; evidence stays still."""
    go('Reviewer',a,a+.55,(-1.25,-1.35,1.12))
    hold(ACTORS['Reviewer'],a+.95)
    pose(ACTORS['Reviewer'],a+1.75,(1.25,-1.35,1.12))
    hold(ACTORS['Reviewer'],b)
    for o,t0,t1,side in [(source,a+.25,a+1.18,1),(candidate,a+1.35,b,-1)]:
        CONTACTS.append(dict(object=o.name,actor='Reviewer',start=t0,end=t1,side=side,
                             grip_start=t0+.18,grip_end=t1-.18,stone=0,look=True))
    if kind=='label':
        scopes=[f.LABELS[int(o['photo_id'])] for o in (source,candidate)]
    elif kind=='person':
        scopes=[f.FACES[int(o['photo_id'])] for o in (source,candidate)]
    else: scopes=[(0,0,1,1)]*2
    outline(source,scopes[0],a+.2,a+1.25,'amber_edge')
    outline(candidate,scopes[1],a+1.4,b,'amber_edge')
    if kind in ('label','person'):
        for x,o,crop in zip([-.78,.78],(source,candidate),scopes):
            photo(int(o['photo_id']),f'{a} / compared {x}',a+.25,b, (x,-1.0,3.75),
                  .67 if kind=='label' else .87,crop=crop)
    checked(candidate,b-.25,passed)
    mark(a,'independent_review',anchor=source['photo_id'],candidate=candidate['photo_id'],
         relation=kind,passed=passed,end=b)


def obtain(anchor,ids,a,b,label):
    """List → opaque candidates → inspect request → actual photographs, with grip/release."""
    go('Reviewer',a-.5,a+.5,(-.8,-1.3,.83))
    mark(a,'request',anchor=anchor['photo_id'],candidates=ids,flow=label)
    t1=token(label+' / unopened candidate A',a+.55,a+2.35)
    t2=token(label+' / unopened candidate B',a+.55,a+2.35,pos=(4.8,.0,.86))
    # Returned opaque list is held visibly before the image request.
    action(t1,a+.55,a+1.35,(2.7,.0,1.8),.9)
    action(t2,a+.55,a+1.35,(4.4,.0,1.8),.9,by='Organizer',stone=2)
    pose(t1,a+1.75,(2.7,.0,1.8));pose(t2,a+1.75,(4.4,.0,1.8))
    action(t1,a+1.75,a+2.35,SLOT,.38)
    action(t2,a+1.75,a+2.35,(4.3,.0,.82),.38,by='Organizer',stone=2)
    mark(a+.55,'opaque_list',flow=label,ids=ids)
    mark(a+1.75,'inspect_request',flow=label,ids=ids)
    p=photo(ids[0],label+' / observed A',a+2.35,pos=SLOT,scale=.13)
    q=photo(ids[1],label+' / observed B',a+2.35,pos=(4.1,.15,.85),scale=.13)
    action(p,a+2.35,b,RIGHT,1)
    action(q,a+2.35,b,WAIT,.48,by='Organizer',stone=2)
    mark(a+2.35,'images_observed',flow=label,ids=ids)
    return p,q


def exchange(p,q,a,b):
    action(p,a,b,(5.25,1.1,4.85),.48,by='Organizer',side=1,stone=1)
    action(q,a,b,RIGHT,1,by='Organizer',side=-1,stone=2)


def arrange(p,q,a,b,context=False):
    if context:
        dests=[(1.75,.7,3.65),(5.3,.7,3.65)];scales=[.67,.67]
    else:
        dests=[(-2.8,.65,3.6),(2.8,.65,3.6)];scales=[1.0,1.0]
    for i,(o,d,s) in enumerate(zip((p,q),dests,scales)):
        action(o,a,b,d,s,by='Organizer',side=(-1 if i==0 else 1),stone=i)
    go('Explorer',a,b,(-3.35,-1,.9))
    go('Reviewer',a,b,(.0,-1.7,.75))
    mark(b,'arranged',photos=[p['photo_id'],q['photo_id']],context=context)


def label3d(o,value):
    w,h=float(o['width']),float(o['height'])
    t=f.text('Fixture context annotation',value,.18,(-w/2,-.07,-h/2-.33),f.MATS['text_ink'],o,bold=True)
    t.rotation_euler=(math.pi/2,0,0)
    visible(t,*o['visible_seconds'])


def rig():
    # Build one cast; remove v1 settling keys and its static arms.
    ex=f.explorer((4.5,-1,1.10),ALL,scale=.86)
    rev=f.reviewer((0,-1.4,1.03),ALL,.94)
    org=f.empty('Organizer / persistent rig',(0,0,0))
    ACTORS.update(Explorer=ex,Reviewer=rev,Organizer=org)
    for actor in (ex,rev):
        actor.animation_data_clear()
        for child in list(actor.children):
            if 'Reaching arm' in child.name or 'Contact fingertip' in child.name:
                bpy.data.objects.remove(child,do_unlink=True)
            else:child.animation_data_clear()
        for side in (-1,1):
            arm=f.tube(f'{actor.name} / articulated arm {side}',[(side*.48,-.12,-.1),(side*.65,-.23,-.3),(side*.78,-.28,-.5)],.06,
                       f.MATS['blue' if actor==ex else 'glass'],actor)
            finger=f.sphere('Gripping fingertip',(side*.78,-.28,-.5),(.13,.10,.15),f.MATS['blue' if actor==ex else 'glass'],actor,16)
            ARMS[(actor.name,side)]=(arm,finger)
        pose(actor,0)
    for side in (-1,1):
        leg=f.tube('Explorer / stepping limb '+str(side),[(side*.3,0,-.45),(side*.42,-.1,-.75),(side*.46,-.15,-1.0)],.10,f.MATS['blue'],ex)
        foot=f.sphere('Explorer / planted foot '+str(side),(side*.46,-.15,-1.0),(.20,.19,.10),f.MATS['blue'],ex,16)
        FEET.append((side,leg,foot))
    for i in range(3):
        stone=f.sphere('Organizer / moving stone '+str(i),(5.7+i*.65,-1.3,.36),(.59,.40,.25),f.MATS['stone'],segments=24)
        STONES.append(stone)
        arm=f.tube('Organizer / articulated lift '+str(i),[(0,0,0),(0,0,.1),(0,0,.2)],.060,f.MATS['stone'])
        tip=f.sphere('Organizer / photo grip '+str(i),(0,0,0),(.13,.10,.10),f.MATS['stone'],segments=16)
        STONE_ARMS.append((arm,tip));visible(arm,0,FINISH);visible(tip,0,FINISH)
    for actor in [ex,rev,*STONES]:visible(actor,0,FINISH)
    for name,o in ACTORS.items():o['persistent_agent']=name


def assign_stones():
    """Reserve each stone through release; a next approach cannot steal its current grip."""
    schedules=[[] for _ in range(3)]
    for c in sorted((c for c in CONTACTS if c['actor']=='Organizer'),key=lambda c:c['grip_start']):
        available=[i for i,rows in enumerate(schedules) if not rows or rows[-1]['grip_end']+.01<=c['grip_start']]
        if not available:raise RuntimeError('More than three simultaneous Organizer grips')
        preferred=c['stone']
        target=edge(PROPS[c['object']],c['grip_start'],c['side'])
        def travel(i):
            if not schedules[i]:return abs(target.x-(5.7+i*.65))/max(.1,c['grip_start'])
            prev=schedules[i][-1]
            gap=c['grip_start']-prev['grip_end']
            return abs(target.x-edge(PROPS[prev['object']],prev['grip_end'],prev['side']).x)/max(.01,gap)
        if preferred not in available or travel(preferred)>4:
            preferred=min(available,key=travel)
        c['stone']=preferred;schedules[preferred].append(c)
    return schedules


def stone_pose(rows,i,t):
    base=Vector((5.7+i*.65,-1.3,.36));rest=base+Vector((0,0,.20))
    def contact(c,time):
        tip=edge(PROPS[c['object']],time,c['side'])
        return Vector((tip.x,-1.45,.36)),tip
    prior=None
    for c in rows:
        if c['grip_start']<=t<=c['grip_end']:return contact(c,t)
        if t<c['grip_start']:
            stop=c['grip_start'];q,qt=contact(c,stop)
            if prior:
                start=prior['grip_end'];p,pt=contact(prior,start)
                gap=stop-start;u=ease((t-start)/gap);body=p.lerp(q,u)
                if gap<.9:return body,pt.lerp(qt,u)
                ramp=min(.55,gap/3)
                if t<start+ramp:
                    offset=(pt-p).lerp(Vector((0,0,.2)),ease((t-start)/ramp))
                elif t>stop-ramp:
                    offset=Vector((0,0,.2)).lerp(qt-q,ease((t-(stop-ramp))/ramp))
                else:offset=Vector((0,0,.2))
                return body,body+offset
            approach=max(.8,abs(q.x-base.x)/4)
            if t<stop-approach:return base,rest
            u=ease((t-(stop-approach))/approach);return base.lerp(q,u),rest.lerp(qt,u)
        prior=c
    if prior:
        p,pt=contact(prior,prior['grip_end']);u=ease(min(1,(t-prior['grip_end'])/.8))
        return p,pt.lerp(p+Vector((0,0,.2)),u)
    return base,rest


def bake():
    scene=bpy.context.scene
    channels=[o for o in bpy.data.objects if o.name in ROUTES]
    body=next(o for o in ACTORS['Explorer'].children if 'organic body' in o.name)
    stone_schedules=assign_stones()
    for frame in range(1,FPS*LENGTH+1):
        t=(frame-1)/FPS
        for o in channels:
            pos,scale=at(o,t);f.key(o,'location',frame,pos);f.key(o,'scale',frame,scale)
        for name in ('Explorer','Reviewer'):
            actor=ACTORS[name]
            p,_=at(actor,t)
            pbefore,_=at(actor,max(0,t-.06));pafter,_=at(actor,min(LENGTH,t+.06))
            velocity=(pafter-pbefore)/.12
            lean=max(-.22,min(.22,-velocity.x*.06))
            active=[c for c in CONTACTS if c['actor']==name and c['start']<=t<=c['end']]
            if active:lean+=(-.08 if edge(PROPS[active[-1]['object']],t,active[-1]['side']).x<p.x else .08)
            f.key(actor,'rotation_euler',frame,(0,lean,0))
            # Squash and recovery respond to locomotion, never independent hovering.
            if name=='Explorer':
                k=min(1,velocity.length/2.5)
                phase=math.sin(t*math.pi*3.2)
                f.key(body,'scale',frame,(1+.035*k*phase,.67,1-.035*k*phase))
            mat=Euler((0,lean,0)).to_matrix()
            sc=at(actor,t)[1]
            if name=='Explorer':
                speed=min(1,velocity.length/2.5)
                for side,leg,foot in FEET:
                    phase=t*7.5+(math.pi if side<0 else 0)
                    floor=Vector((p.x+side*.38+speed*.18*math.cos(phase),p.y-.10,.04+speed*.19*max(0,math.sin(phase))))
                    local=mat.inverted()@(floor-p)
                    tip=Vector([local[i]/sc[i] for i in range(3)])
                    start=Vector((side*.30,0,-.45));knee=start.lerp(tip,.55)+Vector((side*.10,-.05,.06))
                    curve_pose(leg,[start,knee,tip],frame)
                    f.key(foot,'location',frame,tip)
            for side in (-1,1):
                arm,finger=ARMS[(actor.name,side)]
                rest=Vector((side*.82,-.30,-.52))
                tip=rest.copy()
                chosen=[c for c in active if (-1 if c['side']==1 else 1)==side]
                if chosen:
                    c=chosen[-1]
                    target=edge(PROPS[c['object']],t,c['side'])
                    local=mat.inverted()@(target-p)
                    local=Vector([local[i]/sc[i] for i in range(3)])
                    ramp=c.get('ramp',.18 if c.get('look') else .3)
                    blend=min(1,(t-c['start'])/ramp,(c['end']-t)/ramp)
                    tip=rest.lerp(local,ease(max(0,blend)))
                else:
                    tip.z+=.10*min(1,velocity.length)*math.sin(t*7+side)
                start=Vector((side*.46,-.12,-.10))
                mid=start.lerp(tip,.5)+Vector((side*.15,-.16,-.23))
                curve_pose(arm,[start,mid,tip],frame)
                f.key(finger,'location',frame,tip)
        for i,stone in enumerate(STONES):
            p,top=stone_pose(stone_schedules[i],i,t)
            f.key(stone,'location',frame,p)
            arm,tip=STONE_ARMS[i]
            mid=p.lerp(top,.52)+Vector((.15 if i%2 else -.15,-.08,.03))
            curve_pose(arm,[p,mid,top],frame)
            f.key(tip,'location',frame,top)
    for act in bpy.data.actions:
        for layer in act.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        for point in fc.keyframe_points:
                            point.interpolation='CONSTANT' if fc.data_path in ('hide_render','hide_viewport') else 'LINEAR'


def story():
    src=photo(0,'Wine / original selected source',0,pos=(.8,.65,3.65),width=4.8,scale=1.27)
    pointer(src,1.0,(.37,.035,.63,.94))
    outline(src,(.37,.035,.63,.94),1.3,33.4)
    action(src,1.7,3.7,LEFT,1,side=1)
    a,b=obtain(src,[4,3],4,9.5,'wine / first')
    go('Explorer',9.5,11,(-3.35,-1,.9))
    review(src,a,10,12.5,'unsupported',False)
    exchange(a,b,12.5,13.7)
    review(src,b,13.7,16,'unsupported',False)
    # Both unsupported photographs and source remain through feedback.
    clue=photo(0,'Feedback / original red-circle label',16,22,pos=(.78,-1,3.45),width=.75,crop=f.LABELS[0])
    action(clue,16.35,18.4,(-.83,-1.0,3.45),by='Reviewer',side=-1)
    go('Explorer',16,17.2,(-3.7,.5,1.0))
    CONTACTS.append(dict(object=clue.name,actor='Explorer',start=18.1,end=19.3,side=-1,grip_start=18.4,grip_end=19,stone=0))
    mark(16,'conditional_retry',anchor=0,prior_candidates=[4,3],count=1,
         conditions=['all unsupported','incomplete','valid anchor','remaining budgets'])
    # The refined label stays on the table while Explorer asks the same tool again.
    for o in (a,b):
        action(o,19.1,20.5,(6.9,1.5,4.9 if o==a else 2.9),.31,by='Organizer',stone=1 if o==a else 2,side=1)
        visible(o,4+2.35,23.2)
    c,d=obtain(src,[1,2],19.6,23.1,'wine / refined')
    go('Explorer',23.1,24.6,(-3.35,-1,.9))
    review(src,c,23.1,25.5,'label')
    exchange(c,d,25.5,26.5)
    review(src,d,26.5,29,'label')
    action(src,29,32.7,PARK,.33,by='Organizer',side=1,stone=2)
    arrange(c,d,29,31.7)
    # The opened result itself becomes the new source: no replacement at a cut.
    pointer(c,33,(0,0,1,1))
    action(c,33.25,34.8,(.4,.65,3.65),1.3,by='Explorer',side=1)
    action(d,33.25,35,(6.4,1.5,4.65),.33,by='Organizer',side=1,stone=1)
    action(c,35,36.7,LEFT,1,by='Explorer',side=1)
    outline(c,(0,0,1,1),34,47.4)
    mark(34,'new_whole_photo_anchor',anchor=1)
    e,g=obtain(c,[3,4],37,40.8,'restaurant / whole-photo context')
    label3d(c,'설정 날짜 2026.06.14')
    label3d(e,'설정 날짜 2026.06.14');label3d(g,'설정 날짜 2026.06.14')
    review(c,e,41,43.2,'fixture_date')
    exchange(e,g,43.2,44.1)
    review(c,g,44.1,46.3,'fixture_date')
    arrange(e,g,46.3,47.5,True)
    # A user tap explicitly starts a different Connect; this is not wine retry.
    pointer(c,47.6,f.FACES[1]);outline(c,f.FACES[1],47.9,62.8)
    mark(47.6,'new_connect',anchor=1,selection='person')
    for i,o in enumerate((e,g)):
        action(o,49.4,51,(6.8,1.2,4.9-i*2.1),.31,by='Organizer',stone=i,side=1)
        visible(o,39.35,55)
    h,j=obtain(c,[3,5],51,55.8,'person / new Connect')
    review(c,h,56,58.15,'person')
    exchange(h,j,58.15,59.05)
    review(c,j,59.05,61.3,'person')
    action(c,61.3,62.8,(-6.4,1.8,2.6),.33,by='Organizer',side=1,stone=2)
    arrange(j,h,61.3,62.8)
    pointer(j,63,(0,0,1,1))
    action(j,63.15,64.45,(.4,.65,3.65),1.3,by='Organizer',side=-1,stone=0)
    action(h,63.2,65,(6.4,1.5,2.65),.33,by='Organizer',stone=1,side=1)
    action(j,64.55,65.8,LEFT,1,by='Organizer',side=-1,stone=0)
    outline(j,(0,0,1,1),64,77)
    mark(64,'new_whole_photo_anchor',anchor=5)
    k,l=obtain(j,[1,3],66,70.8,'beach / whole-photo context')
    # Put earlier duplicates away with a visible contact action before the new context.
    for i,o in enumerate((c,h)):
        action(o,67.4,68.6,(-6.4 if i==0 else 6.4,1.5,.3),.08,by='Organizer',stone=i,side=1 if i==0 else -1)
        visible(o,float(o['visible_seconds'][0]),68.6)
    label3d(j,'설정 날짜 2026.04.18')
    label3d(k,'설정 날짜 2026.06.14');label3d(l,'설정 날짜 2026.06.14')
    review(j,k,71,73.2,'whole_photo_person')
    exchange(k,l,73.2,74.1)
    review(j,l,74.1,76.3,'whole_photo_person')
    arrange(k,l,76.3,77.5,True)
    # Final layout reuses previously shown photographs, rather than conjuring a graph.
    final=[(src,(4.8,1,4.1),.66),(k,(0,1,4.1),.66),(j,(-4.8,1,4.1),.66),
           (d,(4.8,.8,1.95),.33),(g,(0,.8,1.95),.33),(l,(-4.8,.8,1.95),.33)]
    visible(g,39.35,FINISH)
    for i,(o,p,s) in enumerate(final):
        action(o,77.8 if i<3 else 82.0 if i==4 else 81.0,81.0 if i<3 else 84.2,p,s,
               by='Explorer' if i==2 else 'Organizer',side=1 if i==2 else -1,stone=[2,0,1,2,0,1][i])
    for a_,b_,color in [(src,k,'blue'),(k,j,'blue'),(src,d,'blue'),(k,g,'date'),(j,l,'blue')]:
        pa=at(a_,84.3)[0];pb=at(b_,84.3)[0]
        if abs(pa.x-pb.x)>1:
            direction=1 if pb.x>pa.x else -1
            pa+=Vector((direction*1.65,-.35,0));pb+=Vector((-direction*1.65,-.35,0))
        else:pa+=Vector((0,-.3,-1.20));pb+=Vector((0,-.3,.70))
        ob=f.relation(pa,pb,{**ALL,'first':fr(84.3),'last':fr(FINISH)-1},color,.0)
        ob['edge_ids']=[a_['photo_id'],b_['photo_id']]
        visible(ob,84.3,FINISH)
    mark(84.3,'final_path',edges=[[0,1],[0,2],[1,4],[1,5],[5,3]])


def build():
    f.DEST=DEST;f.OUT=OUT;f.LENGTH=LENGTH;f.SHOTS=[]
    f.build()
    scene=bpy.context.scene;scene.name='Connected Gallery / continuous second edit / 93 seconds'
    if scene.sequence_editor:
        for strip in scene.sequence_editor.strips:strip.name='Original score / 93 seconds'
    f.CURRENT=bpy.data.collections.new('Persistent cast and photographs')
    scene.collection.children.link(f.CURRENT)
    rig();story()
    slot=f.tool(ALL,(3.8,-.05,.38));visible(slot,0,FINISH)
    # One stationary camera removes repeated cut resets and lets physical motion lead attention.
    f.CAM.location=(0,-19.3,10.4)
    f.CAM.rotation_euler=(Vector((0,.2,3.1))-f.CAM.location).to_track_quat('-Z','Y').to_euler()
    brand=f.hud('CONNECTED GALLERY',.066,.066,27,'muted',True);visible(brand,0,FINISH)
    disclosure=f.hud('생성 사진 · 가상 날짜 · 고정 시나리오',.934,.954,24,'muted',align='RIGHT');visible(disclosure,0,FINISH)
    for a,b,caption in CAPTIONS:
        obj=f.hud(caption,.5,.133,42,'ink',True,'CENTER')
        obj['caption_interval']=[a,b];visible(obj,a,b)
    # Only the end card is a cut. Four seconds of truly stable typography.
    for txt,x,y,size in [('Connected Gallery',.5,.35,85),('사진 한 장에서, 다음 기억으로.',.5,.49,46),
                           ('Made with Astra · Blender / Eevee',.5,.66,36),('생성 사진 · 가상 날짜 · 고정 시나리오',.5,.86,25)]:
        ob=f.hud(txt,x,y,size,'ink',True,'CENTER');visible(ob,FINISH,LENGTH)
    bake()
    for name,(a,b) in VIS.items():
        ob=bpy.data.objects[name]
        f.show_between(ob,fr(a),fr(b)-1)
        ob['render_interval']=[a,b]
        if ob.animation_data and ob.animation_data.action:
            for layer in ob.animation_data.action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        if bag.slot_handle!=ob.animation_data.action_slot.handle:continue
                        for fc in bag.fcurves:
                            if fc.data_path in ('hide_render','hide_viewport'):
                                for pt in fc.keyframe_points:pt.interpolation='CONSTANT'
    scene['duration_seconds']=LENGTH
    scene['revision']='v2 / user requested continuous action and legible captions'
    scene['events']=json.dumps(EVENTS,ensure_ascii=False)
    scene['contacts']=json.dumps(CONTACTS,ensure_ascii=False)
    scene['captions']=json.dumps(CAPTIONS,ensure_ascii=False)
    scene['routes']=json.dumps(ROUTES,ensure_ascii=False)
    for e in EVENTS:scene.timeline_markers.new(e['kind'],frame=e['frame'])
    scene.frame_set(1)
    (DEST/'timeline.json').write_text(json.dumps(dict(duration=LENGTH,captions=CAPTIONS,events=EVENTS,contacts=CONTACTS),ensure_ascii=False,indent=2),encoding='utf-8')
    import runpy
    runpy.run_path(str(ROOT/'scripts/astra-film/score_v2.py'),run_name='__main__')
    scene.sequence_editor_clear()
    for sound in list(bpy.data.sounds):
        if sound.users==0:bpy.data.sounds.remove(sound)
    scene.sequence_editor_create().strips.new_sound('Original score / 93 seconds',str(OUT/'score.wav'),1,1)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(DEST/'connected-gallery-astra.blend'),compress=True)
    print('V2_BUILD_COMPLETE',len(bpy.data.objects),len(CONTACTS),'contacts',flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',default='build',choices=['build','stills','preview','render','encode','encode-preview','preview-from-final'])
    p.add_argument('--start',type=int,default=1);p.add_argument('--end',type=int,default=FPS*LENGTH)
    p.add_argument('--frames',default='1,73,205,275,405,570,725,835,1009,1165,1360,1537,1717,1909,1993')
    p.add_argument('--percent',type=int,default=50);p.add_argument('--samples',type=int,default=16)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    f.DEST=DEST;f.OUT=OUT;f.LENGTH=LENGTH
    if args.mode=='build':build();return
    scene=f.load()
    if args.mode=='stills':f.render_frames(scene,[int(x) for x in args.frames.split(',')],OUT/'stills',args.percent,args.samples,False,visible_only=True)
    elif args.mode in ('preview','render'):
        folder=OUT/('preview-frames' if args.mode=='preview' else 'frames')
        f.render_frames(scene,range(args.start,args.end+1),folder,args.percent if args.mode=='preview' else 100,args.samples,visible_only=True)
    elif args.mode=='encode-preview':
        f.LENGTH=args.end//FPS
        f.encode(scene,OUT/'preview-frames',OUT/'preview.mp4',audio=OUT/'score.wav')
    elif args.mode=='preview-from-final':
        f.LENGTH=16
        f.encode(scene,OUT/'frames',OUT/'preview.mp4',audio=OUT/'score.wav',percent=50)
    elif args.mode=='encode':f.encode(scene,OUT/'frames',DEST/'connected-gallery-astra.mp4',audio=OUT/'score.wav',samples=16)


if __name__=='__main__':main()
