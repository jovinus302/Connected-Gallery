import * as THREE from './vendor/three.module.min.js';
import {photoNames} from './storyboard.js?v=embodied3';

const V=(x=0,y=0,z=0)=>new THREE.Vector3(x,y,z);
const clamp=(v,a=0,b=1)=>THREE.MathUtils.clamp(v,a,b);
const smooth=t=>{t=clamp(t);return t*t*t*(t*(t*6-15)+10);};
const range=(p,a,b)=>smooth((p-a)/(b-a));
const mix=(a,b,t)=>a.clone().lerp(b,t);
const home={explorer:V(-4.5,1.5,.5),reviewer:V(4.8,1.8,.3),organizer:V(11.8,1.2,.4)};
const toolHome=V(-.25,.9,-2.8);
const labels=['선택 원본','함께한 식사','발견한 곳','야외 인물','커피 · 디저트','해변 인물'];
const actions=p=>p<.16?'anticipate':p<.3?'reach':p<.78?'carry':p<.92?'release':'hold';

// Every transform is sampled from presentation time, including the grippers.
// Pictures, card edges, tools, agents and their shadows share the same space.
export class AgentScene {
  constructor(container,markers,onFailure) {
    this.container=container;this.markers=markers;this.failed=false;
    this.photoLayer=document.getElementById('photo-stage-overlay');
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#e6e3da');this.scene.fog=new THREE.Fog('#e6e3da',24,66);
    this.renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=.96;
    this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;container.append(this.renderer.domElement);
    this.renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();this.failed=true;onFailure();});
    this.camera=new THREE.PerspectiveCamera(38,1,.1,100);this.camera.position.set(-8,7,15);this.look=V(-1,1,0);
    this.textures=[];this.grips=[];this.progress=0;
    this.setupLighting();this.setupRoom();this.setupAgents();this.setupPhotos();this.setupTools();
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(container);this.resize();
  }
  material(options){return new THREE.MeshPhysicalMaterial(options);}
  mesh(geometry,material,parent=this.scene){const mesh=new THREE.Mesh(geometry,material);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;}

  setupLighting(){
    this.scene.add(new THREE.HemisphereLight(0xe2efff,0x6b6251,.85));
    const key=new THREE.DirectionalLight(0xfff1d9,3.1);key.position.set(-7,13,7);key.castShadow=true;
    Object.assign(key.shadow.camera,{left:-18,right:20,top:15,bottom:-12,near:1,far:45});key.shadow.mapSize.set(2048,2048);key.shadow.normalBias=.035;key.shadow.bias=-.0002;this.scene.add(key);
    const rim=new THREE.DirectionalLight(0xb2ccff,2.4);rim.position.set(4,5,-6);this.scene.add(rim);
    const fill=new THREE.DirectionalLight(0xffffff,.8);fill.position.set(10,4,10);this.scene.add(fill);
    const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=512;const ctx=canvas.getContext('2d');
    const gradient=ctx.createLinearGradient(0,0,0,512);gradient.addColorStop(0,'#ced7e2');gradient.addColorStop(.5,'#70766e');gradient.addColorStop(1,'#c9c1b0');ctx.fillStyle=gradient;ctx.fillRect(0,0,1024,512);
    ctx.fillStyle='#fffaf0';ctx.fillRect(110,60,180,230);ctx.fillRect(680,100,45,230);
    const texture=new THREE.CanvasTexture(canvas);texture.mapping=THREE.EquirectangularReflectionMapping;texture.colorSpace=THREE.SRGBColorSpace;
    const pmrem=new THREE.PMREMGenerator(this.renderer);this.environment=pmrem.fromEquirectangular(texture);this.scene.environment=this.environment.texture;pmrem.dispose();texture.dispose();
  }
  setupRoom(){
    const floor=this.mesh(new THREE.PlaneGeometry(220,160),this.material({color:0xa4a295,roughness:.87,metalness:.05}));floor.rotation.x=-Math.PI/2;floor.position.y=-.5;floor.castShadow=false;
    const porcelain=this.material({color:0xd8d5c9,roughness:.6,metalness:.06});
    for(const x of [-3,5,12]){
      const base=this.mesh(new THREE.CylinderGeometry(3.7,3.8,.28,96),porcelain);base.position.set(x,-.35,-.3);
      const rim=this.mesh(new THREE.TorusGeometry(3.52,.012,8,96),this.material({color:0xa19f94,roughness:.8}));rim.rotation.x=Math.PI/2;rim.position.set(x,-.2,-.3);
    }
    const architecture=this.material({color:0xbdb9ad,roughness:.82});
    for(let i=0;i<7;i++){const slab=this.mesh(new THREE.BoxGeometry(.2,9,1.1),architecture);slab.position.set(-13+i*5,4,-10-(i%2)*1.6);slab.rotation.y=-.35;slab.castShadow=false;}
    const arch=new THREE.CatmullRomCurve3([V(-3,0,-5.5),V(-3,4,-5.5),V(-1,6,-5.5),V(1,4,-5.5),V(1,0,-5.5)]);
    this.mesh(new THREE.TubeGeometry(arch,64,.065,10,false),this.material({color:0xaaa798,metalness:.3,roughness:.35}));
  }
  setupAgents(){
    this.agents={};const explorer=new THREE.Group();this.scene.add(explorer);this.agents.explorer=explorer;
    const geometry=new THREE.SphereGeometry(1,64,48),positions=geometry.attributes.position;
    for(let i=0;i<positions.count;i++){const x=positions.getX(i),y=positions.getY(i),z=positions.getZ(i),phi=Math.atan2(y,x);const r=1+.27*Math.cos(phi*5+.3)*Math.pow(Math.hypot(x,y),3);positions.setXYZ(i,x*r,y*r,z*r*.85);}geometry.computeVertexNormals();
    this.blue=this.material({color:0x1245d8,metalness:.42,roughness:.2,clearcoat:1,clearcoatRoughness:.16});this.blob=this.mesh(geometry,this.blue,explorer);
    this.hands=[0,1].map(()=>{const hand=this.mesh(new THREE.SphereGeometry(.25,32,20),this.blue);hand.scale.set(.75,1.3,.85);return hand;});
    this.tendrils=[0,1].map(()=>Array.from({length:16},()=>this.mesh(new THREE.CylinderGeometry(.08,.08,1,12),this.blue)));
    const reviewer=new THREE.Group();this.scene.add(reviewer);this.agents.reviewer=reviewer;
    const gold=this.material({color:0xc98a2a,metalness:.58,roughness:.21,clearcoat:1});this.ring=this.mesh(new THREE.TorusGeometry(.9,.19,32,96),gold,reviewer);
    const inner=this.mesh(new THREE.TorusGeometry(.69,.035,12,96),this.material({color:0x6d4f24,metalness:.8,roughness:.2}),reviewer);inner.position.z=.06;
    const lens=this.mesh(new THREE.CircleGeometry(.66,64),this.material({color:0xd4eaff,transparent:true,opacity:.13,roughness:.08,metalness:.1,side:THREE.DoubleSide,depthWrite:false}),reviewer);lens.position.z=.02;lens.castShadow=false;
    this.reviewHands=[0,1].map(()=>{const hand=this.mesh(new THREE.SphereGeometry(.17,24,16),gold);hand.scale.set(.7,1.3,.8);return hand;});
    this.reviewTendrils=[0,1].map(()=>Array.from({length:16},()=>this.mesh(new THREE.CylinderGeometry(.055,.055,1,10),gold)));
    const organizer=new THREE.Group();this.scene.add(organizer);this.agents.organizer=organizer;
    const charcoal=this.material({color:0x252c2a,metalness:.35,roughness:.26,clearcoat:.8});this.pebbles=[];
    for(let i=0;i<3;i++){const pebble=this.mesh(new THREE.SphereGeometry(1,48,32),charcoal,organizer);pebble.scale.set(1.15,.32,.7);pebble.position.y=(i-1)*.58;this.pebbles.push(pebble);}
    this.organizerHands=[0,1].map(()=>{const hand=this.mesh(new THREE.SphereGeometry(.22,24,16),charcoal);hand.scale.set(1.2,.55,1);return hand;});
  }
  setupPhotos(){
    this.photos=[];const sheet=new THREE.TextureLoader().load('./assets/gallery.png',()=>{for(const photo of this.photos)photo.texture.needsUpdate=true;this.render(this.progress);});sheet.colorSpace=THREE.SRGBColorSpace;this.textures.push(sheet);
    const paper=this.material({color:0xfffdf5,roughness:.58,metalness:0});
    for(let id=0;id<6;id++){
      const group=new THREE.Group();this.scene.add(group);this.mesh(new THREE.BoxGeometry(3.02,2.53,.14),paper,group);
      const texture=sheet.clone();texture.repeat.set(1/3,.5);texture.offset.set((id%3)/3,id<3?.5:0);texture.colorSpace=THREE.SRGBColorSpace;this.textures.push(texture);
      const picture=this.mesh(new THREE.PlaneGeometry(2.86,2.145),this.material({map:texture,roughness:.72,metalness:0}),group);picture.position.set(0,.11,.077);picture.castShadow=false;
      const element=document.createElement('div');element.className='shot-photo';element.dataset.photoId=String(id);element.hidden=true;element.setAttribute('aria-label',photoNames[id]);
      const caption=document.createElement('div');caption.className='photo-caption';const title=document.createElement('strong');title.textContent=labels[id];const status=document.createElement('span');caption.append(title,status);element.append(caption);this.photoLayer.append(element);
      const sealCanvas=document.createElement('canvas');sealCanvas.width=128;sealCanvas.height=128;const ctx=sealCanvas.getContext('2d');ctx.fillStyle='#f5f7e9';ctx.beginPath();ctx.arc(64,64,54,0,Math.PI*2);ctx.fill();ctx.fillStyle='#506e3d';ctx.font='bold 68px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('✓',64,68);
      const sealTexture=new THREE.CanvasTexture(sealCanvas);sealTexture.colorSpace=THREE.SRGBColorSpace;this.textures.push(sealTexture);
      const seal=this.mesh(new THREE.PlaneGeometry(.5,.5),new THREE.MeshBasicMaterial({map:sealTexture,transparent:true,depthWrite:false}),group);seal.position.set(1.15,-.98,.09);seal.visible=false;seal.castShadow=false;
      this.photos.push({group,element,status,texture,seal,id,active:false});
    }
  }
  setupTools(){
    this.tool=new THREE.Group();this.scene.add(this.tool);this.tool.position.copy(toolHome);
    const shell=this.material({color:0x7f8a78,roughness:.44,metalness:.25});const body=this.mesh(new THREE.BoxGeometry(2.0,.6,1.4),shell,this.tool);body.position.y=-.35;
    const slot=this.mesh(new THREE.BoxGeometry(1.65,.035,.15),this.material({color:0x25382f,roughness:.5}),this.tool);slot.position.set(0,-.026,.06);
    this.toolLights=[];for(let i=0;i<5;i++){const dot=this.mesh(new THREE.SphereGeometry(.035,10,8),new THREE.MeshBasicMaterial({color:0xd8f0ba}),this.tool);dot.position.set(-.6+i*.3,-.28,.71);this.toolLights.push(dot);}
    this.token=new THREE.Group();this.scene.add(this.token);
    this.tokenBody=this.mesh(new THREE.IcosahedronGeometry(.27,1),this.material({color:0x4269e0,metalness:.4,roughness:.22}),this.token);
    this.tokenHalo=this.mesh(new THREE.TorusGeometry(.42,.025,12,48),this.material({color:0x4269e0,metalness:.3,roughness:.3}),this.token);
    this.trail=Array.from({length:10},()=>{const dot=this.mesh(new THREE.SphereGeometry(.03,8,6),new THREE.MeshBasicMaterial({color:0x6489dc}));dot.castShadow=false;return dot;});
  }
  resize(){const width=this.container.clientWidth,height=this.container.clientHeight;if(!width||!height)return;this.renderer.setSize(width,height,false);this.camera.aspect=width/height;this.camera.updateProjectionMatrix();this.narrow=width<480;if(this.story){this.cameraFrom=null;this.render(this.progress);}}
  setState(step,story,snap=false){
    this.cameraFrom={position:this.camera.position.clone(),look:this.look.clone()};this.sceneState=step;this.story=story;this.instant=snap;
    this.photos.forEach(photo=>{photo.active=story.photos.includes(photo.id);photo.element.hidden=!photo.active;photo.group.visible=photo.active;photo.element.dataset.role=photo.id===0?'original':'candidate';photo.checked=false;});this.render(snap?1:0);
  }
  card(photo,position,rotation=V(-.08,-.2,-.02),scale=1){photo.group.position.copy(position);photo.group.rotation.set(rotation.x,rotation.y,rotation.z);photo.group.scale.setScalar(scale);}
  poseHand(hand,rest,photo,local,p,agent){
    const contact=photo.group.localToWorld(local.clone()),attachment=range(p,.12,.3)*(1-range(p,.78,.94));hand.position.copy(rest).lerp(contact,attachment);hand.rotation.z=attachment*.15;
    this.grips.push({agent,card:photo.id,tip:hand.position.toArray(),contact:contact.toArray(),attached:p>=.3&&p<=.78});
  }
  arrange(p){
    const s=this.story,step=this.sceneState,shot=s.shot,carry=range(p,.3,.78),reach=range(p,.1,.3),settle=range(p,.78,.94);
    const explorer=this.agents.explorer,reviewer=this.agents.reviewer,organizer=this.agents.organizer;
    Object.entries(this.agents).forEach(([name,agent])=>{agent.position.copy(home[name]);agent.rotation.set(0,0,0);agent.scale.setScalar(1);});this.blob.scale.set(1,1,1);this.blob.rotation.set(.08,-.28,.12);this.grips=[];
    this.hands[0].position.copy(home.explorer).add(V(-.85,-.72,.45));this.hands[1].position.copy(home.explorer).add(V(1.0,-.5,.55));
    this.reviewHands[0].position.copy(home.reviewer).add(V(-1,-.7,0));this.reviewHands[1].position.copy(home.reviewer).add(V(1,-.7,0));
    this.organizerHands[0].position.copy(home.organizer).add(V(-.9,-.6,.9));this.organizerHands[1].position.copy(home.organizer).add(V(.9,-.6,.9));
    this.pebbles.forEach((pebble,i)=>{pebble.position.set(0,(i-1)*.58,0);pebble.rotation.set(0,(i-1)*.08,(i-1)*.12);});
    [...this.hands,...this.reviewHands,...this.organizerHands].forEach(hand=>hand.rotation.set(0,0,0));
    this.toolLights.forEach(dot=>dot.material.color.set(0xd8f0ba));this.token.position.copy(toolHome);
    this.token.visible=s.payload.direction!=='none';this.tokenBody.material.color.set(s.payload.direction==='feedback'?0xc88828:0x315edc);this.tokenHalo.material.color.copy(this.tokenBody.material.color);
    let center=V(-2.8,1.05,.2),offset=V(3.1,4.25,11.3),arc=.7;
    const photos=s.photos.filter(id=>id!==0).map(id=>this.photos[id]);
    const localStand=i=>this.narrow?V(-1.95+i*.6,2.7-i*2.6,.5+i*.7):V(-2.1+i*3.0,1.6,.7-i*.45);
    const searchStand=i=>this.narrow?V(-1.1+i*.8,2.6-i*2.55,-1.1+i*.7):V(-1.2+i*2.55,1.9,-1.4-i*.65);
    const scale=this.narrow?.76:.91;
    photos.forEach((photo,i)=>this.card(photo,localStand(i),V(-.09,-.15+i*.12,(i-.5)*-.035),scale));
    if(shot==='decide'){
      if(s.photos.includes(0)){
        const photo=this.photos[0],pos=mix(V(-2.15,1.4,.4),V(-2.0,1.95,1.1),carry);pos.y+=Math.sin(carry*Math.PI)*.28;
        this.card(photo,pos,V(-.1,-.22+carry*.32,-.07+carry*.08),this.narrow?.9:1.03);
        this.poseHand(this.hands[0],V(-4.9,.75,1),photo,V(-1.55,-.62,0),p,'explorer');this.poseHand(this.hands[1],V(-3.5,.9,1),photo,V(1.55,-.62,0),p,'explorer');
        center=V(-2.7,1.05,.3);offset=step.round===1?V(2.6,4.9,11.8):V(-2.2,3.8,10.7);
      }else{
        photos.forEach((photo,i)=>{photo.group.position.y+=carry*.28;photo.group.rotation.y+=carry*(i===0?.23:-.18);});
        this.poseHand(this.hands[1],V(-3.5,1.0,.6),photos[0],V(-1.55,-.65,0),p,'explorer');center.x=-2.1;offset=V(-3.4,3.5,11.5);
      }
      explorer.position.x+=Math.sin(carry*Math.PI)*.35;this.blob.rotation.y+=carry*.6;this.blob.scale.set(1+.08*reach,1-.06*reach,1);
      const requestStart=step.round===3?home.explorer.clone().add(V(1.5,.1,.8)):V(-2.0,1.65,1.2);
      this.token.position.copy(mix(requestStart,toolHome.clone().add(V(0,.5,0)),range(p,.57,.91)));
      if(step.round===3)this.tokenBody.material.color.set(0xc88828);
    }else if(shot==='search'||shot==='inspect'){
      center=V(-2.0,1.15,-.5);offset=shot==='inspect'?V(-2.9,3.4,10.6):V(3.4,5.3,12.6);
      photos.forEach((photo,i)=>{const start=toolHome.clone().add(V((i-.5)*.28,.3,-.1)),end=searchStand(i),t=range(p,.25+i*.07,.75+i*.07);this.card(photo,mix(start,end,t),V(-.2+.11*t,Math.PI*(1-t)-.25+i*.2,(i-.5)*.1*t),scale);photo.group.scale.multiplyScalar(.55+.45*t);});
      this.hands[1].position.copy(mix(V(-3.5,1.0,.6),toolHome.clone().add(V(-.7,.2,.45)),reach*(1-settle)));
      explorer.position.x+=.4*reach*(1-settle);this.blob.rotation.y=.2+.3*reach;this.blob.rotation.z=.12-.2*reach;
      this.token.position.copy(toolHome).add(V(0,.35,0));this.toolLights.forEach((dot,i)=>dot.material.color.set(i<=Math.floor(p*6)?0xdfffb6:0x506149));
    }else if(shot==='return'){
      center=V(-2.35,1.0,.1);offset=V(2.4,3.7,11.2);
      photos.forEach((photo,i)=>{const position=mix(searchStand(i),localStand(i),carry);position.y+=Math.sin(carry*Math.PI)*.55;this.card(photo,position,V(-.09,-.25+carry*.22+i*.13,(i-.5)*.06),scale);this.poseHand(this.hands[i],home.explorer.clone().add(V(i?1:-.7,-.6,.5)),photo,V(-1.55,-.7,0),p,'explorer');});
      this.blob.rotation.y=.25-.6*carry;explorer.position.x+=Math.sin(carry*Math.PI)*.7;this.token.position.copy(mix(toolHome.clone().add(V(0,.4,0)),V(-3.7,1.8,1),carry));
    }else if(shot==='submit'){
      explorer.position.copy(mix(home.explorer,V(2.0,1.45,.9),carry));explorer.position.y+=Math.sin(carry*Math.PI)*.45;this.blob.rotation.y=.2+Math.sin(carry*Math.PI)*.5;this.blob.rotation.z=-.12*Math.sin(carry*Math.PI);
      photos.forEach((photo,i)=>{const destination=this.narrow?V(4.8+i*.6,2.7-i*2.5,.5+i*.6):V(4.0+i*2.55,1.65,.9-i*.6),position=mix(localStand(i),destination,carry);position.y+=Math.sin(carry*Math.PI)*.4;this.card(photo,position,V(-.08,-.1+Math.sin(carry*Math.PI)*.5,(i-.5)*.06),scale);this.poseHand(this.hands[i],explorer.position.clone().add(V(i?.9:-.8,-.6,.55)),photo,V(-1.55,-.6,0),p,'explorer');});
      reviewer.position.set(this.narrow?6.6:7.8,2.0,-.5);reviewer.rotation.y=-.3;
      center=V(THREE.MathUtils.lerp(-2.0,4.5,carry),1.25,.15);offset=V(-3.6+Math.sin(carry*Math.PI)*1.6,1.5,11.6);arc=1.4;this.token.position.copy(photos[0].group.position).add(V(0,-1.35,.35));
    }else if(shot==='review'){
      const positions=this.narrow?[V(3.3,2.8,.2),V(6.0,2.8,.1),V(4.7,.45,1.3)]:[V(2.0,1.9,.45),V(5.0,1.9,.6),V(8.0,1.9,.1)];
      s.photos.forEach((id,i)=>{
        const begin=[0,.24,.60][i],end=[.2,.51,.89][i],lift=range(p,begin,begin+.08)*(1-range(p,end-.08,end));
        const position=positions[i].clone().add(V(0,lift*.17,lift*.5));
        this.card(this.photos[id],position,V(-.04-lift*.13,(1-i)*.12+lift*.1,0),this.narrow?.73:.87);
      });
      const scanA=range(p,.14,.38),scanB=range(p,.51,.74);
      const first=mix(this.photos[s.photos[0]].group.position,this.photos[s.photos[1]].group.position,scanA),lensPoint=mix(first,this.photos[s.photos[2]].group.position,scanB);
      reviewer.position.copy(lensPoint).add(V(0,.12,1.0));reviewer.scale.setScalar(this.narrow?.68:.82);reviewer.rotation.set(.04,Math.sin(p*Math.PI*2)*.12,0);
      this.reviewHands.forEach((hand,i)=>{
        const contacts=s.photos.map(id=>this.photos[id].group.localToWorld(V(i?1.55:-1.55,-.55,0)));
        const contact=mix(mix(contacts[0],contacts[1],scanA),contacts[2],scanB),rest=reviewer.position.clone().add(V(i?.95:-.95,-.55,-.15));
        hand.position.copy(rest).lerp(contact,range(p,.08,.14)*(1-range(p,.78,.94)));
        const selected=scanB===1?2:scanA===1&&scanB===0?1:scanA===0?0:-1;
        if(selected>=0)this.grips.push({agent:'reviewer',card:s.photos[selected],tip:hand.position.toArray(),contact:contacts[selected].toArray(),attached:p>=.3&&p<=.78});
      });
      center=V(5.0,this.narrow?1.35:1.1,.35);offset=this.narrow?V(.7,3.4,9.5):V(1.25,3.4,10.8);arc=-.6;
      photos.forEach((photo,i)=>{photo.checked=p>=(i===0?.51:.82);if(s.verdict==='rejected'&&photo.checked)photo.group.rotation.x+=range(p,i===0?.52:.83,i===0?.66:.95)*.16;});
    }else if(shot==='feedback'){
      const t=range(p,.18,.83),start=home.reviewer.clone().add(V(-.7,-.25,.7)),end=home.explorer.clone().add(V(1.5,.1,.8));
      this.token.position.copy(mix(start,end,t));this.token.position.y+=Math.sin(t*Math.PI)*1.1;reviewer.rotation.y=-.35;this.reviewHands[0].position.copy(start).add(V(-.4,0,0));
      this.hands[1].position.copy(mix(home.explorer.clone().add(V(1,-.5,.5)),end.clone().add(V(-.3,0,0)),range(p,.63,.85)));
      this.blob.rotation.y=.25-.5*range(p,.7,.94);this.blob.scale.setScalar(1+.035*Math.sin(range(p,.8,.98)*Math.PI));
      center=mix(V(3.8,1.1,.3),V(-3.4,1.1,.8),t);offset=V(-1.3,4.2,11.7);arc=-1;
    }else if(shot==='organize'||shot==='done'){
      const t=shot==='done'?1:carry;center=V(12.0,1.05,.5);offset=shot==='done'?mix(V(-2.4,4.7,11.7),V(3.8,7.1,16.7),range(p,.08,.9)):V(-2.4,4.7,11.7);
      photos.forEach((photo,i)=>{const from=V(7.2+i*1.3,2.5,-.5-i*.5),to=V(10.5+i*3.1,1.6,1.0),pos=mix(from,to,t);pos.y+=Math.sin(t*Math.PI)*.5;this.card(photo,pos,V(-.08,-.35*(1-t)+(i-.5)*.08,-.13*(1-t)),scale);if(shot==='organize')this.poseHand(this.organizerHands[i],home.organizer.clone().add(V(i?1:-1,-.65,.7)),photo,V(0,-1.32,0),p,'organizer');});
      organizer.position.set(12.0,1.2-t,1.1);this.pebbles.forEach((pebble,i)=>{pebble.position.x=(i-1)*1.55*t;pebble.position.y=(i-1)*.58*(1-t);pebble.rotation.z=(i-1)*.12*(1-t);});
    }
    // Close shots isolate the acting pair of hands; wide/transfer shots retain
    // the other cast members to establish the shared work space.
    const isolated=['review','inspect'].includes(shot);
    Object.entries(this.agents).forEach(([name,agent])=>agent.visible=!isolated||name===step.agent);
    this.hands.forEach(hand=>hand.visible=explorer.visible);this.reviewHands.forEach(hand=>hand.visible=reviewer.visible);this.organizerHands.forEach(hand=>hand.visible=organizer.visible);
    this.token.scale.setScalar(shot==='search'||shot==='inspect'?1-.55*carry:1);this.token.rotation.set(p*.8,p*2.8,p*.4);
    this.photos.forEach(photo=>{if(!photo.active)return;const checked=shot!=='review'||photo.id===0||photo.checked,verdict=photo.id===0?'source':checked?s.verdict:'candidate';photo.element.dataset.verdict=verdict;photo.status.textContent=photo.id===0?'원본 유지':verdict==='supported'?'✓ 근거 확인':verdict==='rejected'?'× 근거 부족':shot==='inspect'?'직접 확인':'검색 후보';photo.seal.visible=photo.id!==0&&verdict==='supported';});
    return {center,offset,arc};
  }
  project(position){const point=position.clone().project(this.camera);return {x:(point.x*.5+.5)*this.container.clientWidth,y:(-.5*point.y+.5)*this.container.clientHeight,z:point.z};}
  render(progress=0){
    if(this.failed||!this.story)return;this.progress=progress;const p=this.instant?1:clamp(progress),{center,offset,arc}=this.arrange(p);
    offset.x+=Math.sin(range(p,0,.88)*Math.PI)*arc;offset.y+=Math.sin(p*Math.PI)*.45;
    const fit=Math.max(.9,(this.narrow?(this.story.shot==='review'?.9:1.0):1.28)/this.camera.aspect);offset.multiplyScalar(fit);const desired=center.clone().add(offset),look=center.clone();
    if(this.sceneState.phase==='decide'&&this.sceneState.round===1&&!this.instant){const establish=1-range(p,0,.65);desired.lerp(center.clone().add(V(-6,8,17).multiplyScalar(fit)),establish);look.lerp(V(.2,1,-.5),establish*.7);}
    if(this.cameraFrom&&!this.instant){const blend=range(p,0,.22);this.camera.position.copy(mix(this.cameraFrom.position,desired,blend));this.look.copy(mix(this.cameraFrom.look,look,blend));}else{this.camera.position.copy(desired);this.look.copy(look);}
    this.camera.lookAt(this.look);this.camera.updateMatrixWorld();this.scene.updateMatrixWorld(true);
    for(const [name,tendrils,hands] of [['explorer',this.tendrils,this.hands],['reviewer',this.reviewTendrils,this.reviewHands]]){
      tendrils.forEach((segments,i)=>{
        const start=this.agents[name].position.clone().add(V(i?.75:-.5,-.45,.15)),end=hands[i].position;
        const curve=new THREE.CubicBezierCurve3(start,start.clone().add(V(i?.6:-.5,-.75,.25)),end.clone().add(V(-.25,-.4,0)),end);
        segments.forEach((segment,j)=>{segment.visible=this.agents[name].visible;const a=curve.getPoint(j/segments.length),b=curve.getPoint((j+1)/segments.length),direction=b.clone().sub(a);segment.position.copy(a).lerp(b,.5);segment.quaternion.setFromUnitVectors(V(0,1,0),direction.clone().normalize());segment.scale.set(1,direction.length()+.025,1);});
      });
    }
    const cardFrames=[];
    this.photos.forEach(photo=>{if(!photo.active)return;
      const corners=[V(-1.51,-1.265,.08),V(1.51,-1.265,.08),V(1.51,1.265,.08),V(-1.51,1.265,.08)].map(v=>this.project(photo.group.localToWorld(v))),xs=corners.map(v=>v.x),ys=corners.map(v=>v.y);
      const bounds={left:Math.min(...xs),top:Math.min(...ys),right:Math.max(...xs),bottom:Math.max(...ys)};bounds.width=bounds.right-bounds.left;bounds.height=bounds.bottom-bounds.top;
      const point=this.project(photo.group.localToWorld(V(0,-1.38,.08))),width=Math.max(95,Math.min(170,bounds.width+10));photo.element.style.width=`${width}px`;photo.element.style.left=`${clamp(point.x,width/2+9,this.container.clientWidth-width/2-9)}px`;photo.element.style.top=`${clamp(point.y,112,this.container.clientHeight-122)}px`;
      cardFrames.push({id:photo.id,active:true,position:photo.group.position.toArray(),bounds,depth:.14,quaternion:photo.group.quaternion.toArray()});
    });
    const names=this.story.shot==='submit'||this.story.shot==='feedback'?['explorer','reviewer']:[this.sceneState.agent];
    this.markers.querySelectorAll('[data-marker]').forEach(label=>{const name=label.dataset.marker,agent=this.agents[name],point=this.project(agent.position.clone().add(V(0,name==='reviewer'?1.5:-1.45,.1)));label.hidden=!names.includes(name)||point.x<32||point.x>this.container.clientWidth-32||point.z>1;
      if(this.story.shot==='review'){label.style.left='50%';label.style.top='112px';}
      else{label.style.left=`${clamp(point.x,52,this.container.clientWidth-52)}px`;label.style.top=`${clamp(point.y,112,this.container.clientHeight-121)}px`;}
    });
    this.trail.forEach((dot,i)=>{dot.visible=this.token.visible;dot.material.color.copy(this.tokenBody.material.color);dot.position.copy(this.token.position).add(V((i+1)*.11,Math.sin(i*.4+p*4)*.025,-(i+1)*.09));dot.scale.setScalar(1-i*.07);});
    this.renderer.render(this.scene,this.camera);
    this.container.dataset.frame=JSON.stringify({phase:this.sceneState.phase,round:this.sceneState.round,progress:p,actionPhase:actions(p),camera:{position:this.camera.position.toArray(),look:this.look.toArray()},cards:cardFrames,agents:Object.fromEntries(Object.entries(this.agents).map(([name,agent])=>[name,agent.position.toArray()])),grips:this.grips,token:{position:this.token.position.toArray(),direction:this.story.payload.direction}});
  }
  dispose(){this.resizeObserver.disconnect();this.scene.traverse(object=>{object.geometry?.dispose();const materials=object.material?(Array.isArray(object.material)?object.material:[object.material]):[];materials.forEach(material=>material.dispose());});this.textures.forEach(texture=>texture.dispose());this.environment.dispose();this.renderer.dispose();}
}
