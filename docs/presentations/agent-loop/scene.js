import * as THREE from './vendor/three.module.min.js';
import {photoNames,photoRegions} from './storyboard.js';

const V=(x=0,y=0,z=0)=>new THREE.Vector3(x,y,z);
const ease=t=>{t=THREE.MathUtils.clamp(t,0,1);return t*t*t*(t*(t*6-15)+10);};

// A perspective camera shared by real 3D agents and frontal photo billboards.
// Motion uses presentation time, so pause, speed and reduced motion cannot drift.
export class AgentScene {
  constructor(container,markers,onFailure) {
    this.container=container;this.markers=markers;this.failed=false;
    this.stage=container.closest('.stage');this.photoLayer=document.getElementById('photo-stage-overlay');this.payload=document.getElementById('payload');
    this.scene=new THREE.Scene();this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));this.renderer.setClearColor(0,0);
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure=1;container.append(this.renderer.domElement);
    this.renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();this.failed=true;onFailure();});
    this.camera=new THREE.PerspectiveCamera(32,1,.1,120);this.camera.position.set(-1,.65,16.8);
    this.look=V(0,.15,0);this.camera.lookAt(this.look);this.progress=0;
    this.setupLighting();this.setupAgents();this.setupPhotos();this.setupTools();
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(container);this.resize();
  }

  setupLighting() {
    this.scene.add(new THREE.HemisphereLight(0xfffcf0,0x829182,1.8));
    [[0xfff9ea,3.7,[-7,9,10]],[0xd6e5ff,1.8,[10,4,5]],[0xffffff,2,[-4,-2,3]]].forEach(([color,intensity,pos])=>{
      const light=new THREE.DirectionalLight(color,intensity);light.position.set(...pos);this.scene.add(light);
    });
    const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=512;
    const ctx=canvas.getContext('2d');const gradient=ctx.createLinearGradient(0,0,0,512);
    gradient.addColorStop(0,'#f5f7ea');gradient.addColorStop(.58,'#768074');gradient.addColorStop(1,'#d3d0b9');
    ctx.fillStyle=gradient;ctx.fillRect(0,0,1024,512);ctx.fillStyle='#fffef8';ctx.fillRect(85,35,125,220);ctx.fillRect(620,60,100,200);
    const environment=new THREE.CanvasTexture(canvas);environment.mapping=THREE.EquirectangularReflectionMapping;environment.colorSpace=THREE.SRGBColorSpace;
    const pmrem=new THREE.PMREMGenerator(this.renderer);this.environment=pmrem.fromEquirectangular(environment);this.scene.environment=this.environment.texture;pmrem.dispose();environment.dispose();
  }

  setupAgents() {
    this.agents={};
    const shape=new THREE.SphereGeometry(1,72,48),p=shape.attributes.position;
    for(let i=0;i<p.count;i++){
      const x=p.getX(i),y=p.getY(i),z=p.getZ(i),phi=Math.atan2(y,x);
      const radius=1+.36*Math.cos(phi*5+.3)*Math.pow(Math.hypot(x,y),3);
      p.setXYZ(i,x*radius,y*radius,z*radius*.57);
    }shape.computeVertexNormals();
    const explorer=new THREE.Group();this.blob=new THREE.Mesh(shape,new THREE.MeshPhysicalMaterial({color:0x1139bd,metalness:.46,roughness:.23,clearcoat:1,clearcoatRoughness:.2}));
    explorer.add(this.blob);explorer.position.set(-3.5,.1,.5);this.scene.add(explorer);this.agents.explorer=explorer;
    const reviewer=new THREE.Group();this.ring=new THREE.Mesh(new THREE.TorusGeometry(.8,.245,32,88),new THREE.MeshPhysicalMaterial({color:0xd09a47,roughness:.16,metalness:.22,transmission:.35,thickness:.6,clearcoat:1}));
    reviewer.add(this.ring);reviewer.position.set(12,1.7,.8);this.scene.add(reviewer);this.agents.reviewer=reviewer;
    const organizer=new THREE.Group();this.pebbles=[];
    const charcoal=new THREE.MeshPhysicalMaterial({color:0x171c19,roughness:.4,metalness:.25,clearcoat:.6});
    for(let i=0;i<3;i++){
      const mesh=new THREE.Mesh(new THREE.SphereGeometry(1,40,24),charcoal);mesh.scale.set(.94-i*.1,.26,.56);mesh.position.y=(i-1)*.5;mesh.rotation.z=(i-1)*.13;
      organizer.add(mesh);this.pebbles.push(mesh);
    }organizer.position.set(20.6,0,.5);this.scene.add(organizer);this.agents.organizer=organizer;
  }

  setupPhotos() {
    this.photos=[];
    for(let id=0;id<6;id++){
      const element=document.createElement('div');element.className='shot-photo';element.dataset.photoId=String(id);element.hidden=true;
      const photo=document.createElement('div');photo.className=`photo photo-${id}`;photo.setAttribute('role','img');photo.setAttribute('aria-label',photoNames[id]);
      const region=document.createElement('span');region.className='photo-region';region.hidden=true;
      const finding=document.createElement('span');finding.className='photo-finding';
      const scan=document.createElement('span');scan.className='scan-line';photo.append(region,scan,finding);
      const caption=document.createElement('div');caption.className='photo-caption';const title=document.createElement('strong');title.textContent=['선택 원본','함께한 식사','발견한 곳','야외 인물','커피 · 디저트','해변 인물'][id];
      const status=document.createElement('span');caption.append(title,status);element.append(photo,caption);this.photoLayer.append(element);
      this.photos.push({element,region,finding,scan,title,status,position:V(),from:V(),target:V(),width:3.1});
    }
  }

  setupTools() {
    this.tool=new THREE.Group();
    const body=new THREE.Mesh(new THREE.BoxGeometry(1.35,.32,.35),new THREE.MeshStandardMaterial({color:0xd3dbbf,roughness:.65,metalness:.15}));this.tool.add(body);
    for(let i=0;i<3;i++){
      const dot=new THREE.Mesh(new THREE.SphereGeometry(.055,12,8),new THREE.MeshBasicMaterial({color:0x667752}));dot.position.set((i-1)*.24,.03,.21);this.tool.add(dot);
    }this.tool.position.set(1.4,-1.8,.1);this.scene.add(this.tool);
    this.link=new THREE.Line(new THREE.BufferGeometry().setFromPoints([V(),V(1,0,0)]),new THREE.LineDashedMaterial({color:0x71915c,transparent:true,opacity:.32,dashSize:.12,gapSize:.1}));
    this.scene.add(this.link);
  }

  layout() {
    const s=this.story,mobile=this.container.clientWidth<700,station=s.station;
    this.mobile=mobile;
    let center=station+(s.shot==='review'?.2:['search','inspect'].includes(s.shot)?.7:s.shot==='return'?-.45:0);
    let z=s.shot==='inspect'||s.shot==='review'?11.4:s.shot==='done'?14:s.shot==='search'?13.8:13.1;
    if(mobile){
      const tangent=Math.tan(THREE.MathUtils.degToRad(16));
      z=Math.max(4.8/(2*this.camera.aspect*tangent),this.container.clientHeight/(2*tangent*80));center=station;
    }
    this.targetCamera=V(center+.2,.38,z);this.targetLook=V(center,.05,0);
    this.agentTargets={explorer:V(-3.7,.2,.5),reviewer:V(12,1,.65),organizer:V(20.4,.25,.5)};
    if(s.shot==='submit')this.agentTargets.reviewer.set(8.65,.3,.65);
    if(mobile){this.agentTargets.explorer.set(-1.4,1.48,.3);this.agentTargets.reviewer.set(10.65,1.75,.3);this.agentTargets.organizer.set(22.6,1.5,.3);}
    s.photos.forEach((id,i)=>{
      const photo=this.photos[id];photo.width=mobile?1.82:s.shot==='review'?2.85:s.photos.length===1?3.75:3.3;
      if(mobile){
        if(s.photos.length===3)photo.target.set(station+(i===0?-1.13:1.06),i===0?-.2:i===1?1.08:-1.38,0);
        else photo.target.set(station+(s.photos.length===1?.48:i===0?-1.02:1.08),-.23,0);
      }else{
        const x=s.photos.length===3?station-2.9+i*3.15:s.photos.length===1?station+1.25:station-.15+i*3.65;
        photo.target.set(x,.38,0);
      }
    });
    this.toolTarget=mobile?V(station+1.2,-1.8,.1):V(station+1.4,-1.95,.1);
    this.payloadStart=V(-2.4,-1.7,.8);this.payloadEnd=V(1.4,-1.7,.8);
    if(mobile){this.payloadStart.set(-.6,-1.72,.8);this.payloadEnd.set(.5,-1.72,.8);}
    if(s.payload.direction==='return') [this.payloadStart,this.payloadEnd]=[this.payloadEnd,this.payloadStart];
    if(s.payload.direction==='handoff'){this.payloadStart.set(.5,-1.65,.8);this.payloadEnd.set(12.4,-1.65,.8);}
    if(s.payload.direction==='feedback'){this.payloadStart.set(11.9,-.3,.8);this.payloadEnd.set(mobile?.3:-.5,-.5,.8);}
  }

  resize() {
    const width=this.container.clientWidth,height=this.container.clientHeight;if(!width||!height)return;
    this.renderer.setSize(width,height,false);this.camera.aspect=width/height;this.camera.updateProjectionMatrix();
    if(this.story){this.layout();this.startCamera=this.targetCamera.clone();this.startLook=this.targetLook.clone();this.photos.forEach(photo=>photo.from.copy(photo.target));this.render(1);}
  }

  setState(step,story,snap=false) {
    this.sceneState=step;this.story=story;this.instant=snap;this.progress=0;
    this.startCamera=this.camera.position.clone();this.startLook=this.look.clone();
    this.photos.forEach(photo=>photo.from.copy(photo.position));
    this.layout();
    this.photos.forEach((photo,id)=>{
      const active=story.photos.includes(id);photo.element.hidden=!active;if(!active)return;
      photo.element.dataset.role=id===0?'original':'candidate';photo.element.dataset.verdict=id===0?'source':story.verdict;
      photo.status.textContent=id===0?'선택 원본':story.verdict==='supported'?'검토 통과':story.verdict==='rejected'?'검토 미통과':story.focus?'이미지 확인':'검색 후보';
      photo.finding.textContent=story.verdict==='supported'?'형태·라벨 확인':'직접 근거 부족';
      const region=photoRegions[id];photo.region.hidden=!region||!(story.focus||id===0);
      if(region){const [x,y,w,h]=region;Object.assign(photo.region.style,{left:`${x}%`,top:`${y}%`,width:`${w}%`,height:`${h}%`});}
      if(snap||photo.position.lengthSq()===0)photo.from.copy(photo.target);
    });
    if(snap){this.startCamera.copy(this.targetCamera);this.startLook.copy(this.targetLook);}
    this.render(snap?1:0);
  }

  project(position) {
    const p=position.clone().project(this.camera);return {x:(p.x*.5+.5)*this.container.clientWidth,y:(-.5*p.y+.5)*this.container.clientHeight,z:p.z};
  }

  render(progress=0) {
    if(this.failed||!this.story)return;
    this.progress=progress;const p=this.instant?1:progress,t=ease(p/.58),s=this.story,step=this.sceneState;
    this.camera.position.lerpVectors(this.startCamera,this.targetCamera,t);this.look.lerpVectors(this.startLook,this.targetLook,t);
    this.camera.lookAt(this.look);this.camera.updateMatrixWorld();
    const gesture=Math.sin(Math.PI*Math.min(p/.6,1));
    for(const [name,agent]of Object.entries(this.agents)){
      agent.position.copy(this.agentTargets[name]);agent.scale.setScalar(this.mobile?.5:.85);
      const participating=name===step.agent||(s.shot==='feedback'&&name==='explorer')||(s.shot==='submit'&&name==='reviewer');
      agent.visible=participating;
    }
    this.blob.rotation.set(-.04,-.15+gesture*.3,.1+gesture*.15);
    const reach=s.payload.direction==='outbound'?gesture*.13:s.payload.direction==='return'?-gesture*.08:0;
    this.blob.scale.set(1+reach,1-reach,1);this.agents.explorer.position.x+=gesture*.16;
    this.ring.rotation.set(.12,gesture*.4,-.1);
    if(s.shot==='review'&&!this.mobile){
      const from=this.photos[s.photos[0]].target,to=this.photos[s.photos[2]].target;
      this.agents.reviewer.position.set(THREE.MathUtils.lerp(from.x,to.x,ease(p/.58)),.85,.8);
      this.agents.reviewer.scale.setScalar(.47);
    }
    this.pebbles.forEach((pebble,i)=>{pebble.rotation.z=(i-1)*.13*(1-(s.shot==='organize'?t:1));pebble.position.x=s.shot==='organize'?(i-1)*.25*(1-t):0;});
    this.tool.visible=['search','inspect','return','decide'].includes(s.shot);this.tool.position.copy(this.toolTarget);
    this.tool.scale.setScalar(this.mobile?.5:.8);this.tool.rotation.y=s.shot==='search'?gesture*.2:0;
    this.photos.forEach(photo=>{
      if(photo.element.hidden)return;
      photo.position.lerpVectors(photo.from,photo.target,t);
      const point=this.project(photo.position);
      const cameraSpace=photo.position.clone().applyMatrix4(this.camera.matrixWorldInverse);
      const width=photo.width*this.container.clientHeight/(2*Math.tan(THREE.MathUtils.degToRad(this.camera.fov/2))*-cameraSpace.z);
      Object.assign(photo.element.style,{left:`${point.x}px`,top:`${point.y}px`,width:`${width}px`});
      photo.scan.style.top=`${18+Math.min(p/.58,1)*60}%`;
    });
    const payloadPosition=V().lerpVectors(this.payloadStart,this.payloadEnd,t),point=this.project(payloadPosition);
    if(s.payload.direction!=='none'){
      const halfW=this.payload.offsetWidth/2+14;
      this.payload.style.left=`${THREE.MathUtils.clamp(point.x,halfW,this.container.clientWidth-halfW)}px`;
      this.payload.style.top=`${THREE.MathUtils.clamp(point.y,155,this.container.clientHeight-128)}px`;
    }
    this.link.visible=['outbound','return','feedback','handoff'].includes(s.payload.direction);
    this.link.material.color.set(s.payload.direction==='feedback'?0xba8638:0x6885d1);
    this.link.geometry.setFromPoints([this.payloadStart,this.payloadEnd]);this.link.computeLineDistances();
    this.markers.querySelectorAll('[data-marker]').forEach(label=>{
      const name=label.dataset.marker,active=s.shot==='feedback'?'explorer':s.shot==='submit'?'reviewer':step.agent;
      label.hidden=name!==active;if(label.hidden)return;
      const agent=this.agents[name];const position=agent.position.clone();
      if(this.mobile)position.y-=.52;else if(s.shot==='review')position.y+=1.4;else{position.x-=1.5;position.y+=.65;}
      const projected=this.project(position);
      label.style.left=`${THREE.MathUtils.clamp(projected.x,58,this.container.clientWidth-58)}px`;
      label.style.top=`${THREE.MathUtils.clamp(projected.y,this.mobile?120:96,this.container.clientHeight-148)}px`;
    });
    this.renderer.render(this.scene,this.camera);
  }

  dispose() {
    this.resizeObserver.disconnect();this.scene.traverse(object=>{object.geometry?.dispose();
      const materials=object.material?(Array.isArray(object.material)?object.material:[object.material]):[];materials.forEach(material=>material.dispose());});
    this.environment.dispose();this.renderer.dispose();
  }
}
