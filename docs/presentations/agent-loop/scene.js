import * as THREE from './vendor/three.module.min.js';

// The sculptures and paths are actual geometry; the concept PNG is fallback only.
export class AgentScene {
  constructor(container, markers, onFailure) {
    this.container = container; this.markers = markers; this.onFailure = onFailure;
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#efede6');
    this.renderer = new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.7));
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.08;
    container.append(this.renderer.domElement);
    this.renderer.domElement.addEventListener('webglcontextlost', event => {
      event.preventDefault(); this.failed = true; onFailure();
    });
    this.camera = new THREE.OrthographicCamera(-7,7,4.7,-4.7,.1,100);
    this.camera.position.set(0,10,18); this.camera.lookAt(0,.3,0);
    this.setupLighting(); this.setupFloor(); this.setupAgents(); this.setupPaths(); this.setupPhotos();
    this.clock = 0; this.localClock = 0; this.sceneState = null;
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container); this.resize();
  }

  setupLighting() {
    this.scene.add(new THREE.HemisphereLight(0xfff9ed,0x8e8c7a,1.35));
    const key = new THREE.DirectionalLight(0xfff7e9,3.2);
    key.position.set(-5,10,6); key.castShadow = true;
    key.shadow.mapSize.set(1536,1536);
    Object.assign(key.shadow.camera,{left:-10,right:10,top:9,bottom:-9,near:.5,far:35});
    key.shadow.bias = -.0004; key.shadow.normalBias = .025;
    key.shadow.radius = 4; this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xdce7ff,1); fill.position.set(6,5,-4); this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffffff,1.6); rim.position.set(-2,3,-6); this.scene.add(rim);
    const canvas = document.createElement('canvas'); canvas.width=1024; canvas.height=512;
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0,0,0,512);
    gradient.addColorStop(0,'#faf6ed'); gradient.addColorStop(.52,'#a8a59b'); gradient.addColorStop(1,'#e2dac9');
    ctx.fillStyle=gradient; ctx.fillRect(0,0,1024,512);
    ctx.fillStyle='#ffffff'; ctx.fillRect(100,65,150,170); ctx.fillRect(640,90,70,220);
    ctx.fillStyle='#ded9cc'; ctx.fillRect(380,75,140,160);
    const environment=new THREE.CanvasTexture(canvas); environment.mapping=THREE.EquirectangularReflectionMapping;
    environment.colorSpace=THREE.SRGBColorSpace;
    const pmrem=new THREE.PMREMGenerator(this.renderer);
    this.environment=pmrem.fromEquirectangular(environment); this.scene.environment=this.environment.texture;
    pmrem.dispose(); environment.dispose();
  }

  setupFloor() {
    const floor=new THREE.Mesh(new THREE.PlaneGeometry(70,70),new THREE.MeshStandardMaterial({color:0xefede6,roughness:.98}));
    floor.rotation.x=-Math.PI/2; floor.position.y=-.07; floor.receiveShadow=true; this.scene.add(floor);
    // Soft contact ellipses keep the objects grounded even on low-end renderers.
    const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
    const ctx=canvas.getContext('2d');const gradient=ctx.createRadialGradient(64,64,0,64,64,64);
    gradient.addColorStop(0,'rgba(40,34,21,.22)');gradient.addColorStop(.4,'rgba(40,34,21,.11)');gradient.addColorStop(1,'rgba(40,34,21,0)');
    ctx.fillStyle=gradient;ctx.fillRect(0,0,128,128);
    this.shadowTexture=new THREE.CanvasTexture(canvas);
    [[-3.1,0,2.5,1.8],[1.55,-1.2,2.6,1.8],[4.1,1.3,2.7,1.5]].forEach(([x,z,w,h])=>{
      const shadow=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:this.shadowTexture,transparent:true,depthWrite:false}));
      shadow.rotation.x=-Math.PI/2;shadow.position.set(x,-.055,z);this.scene.add(shadow);
    });
  }

  setupAgents() {
    this.agents={};
    const blue=new THREE.MeshPhysicalMaterial({color:0x1237bc,metalness:.48,roughness:.23,clearcoat:1,clearcoatRoughness:.15});
    const geometry=new THREE.SphereGeometry(1,80,56);
    const position=geometry.attributes.position;
    for(let i=0;i<position.count;i++){
      const x=position.getX(i),y=position.getY(i),z=position.getZ(i);
      const angle=Math.atan2(y,x), equator=Math.sqrt(x*x+y*y);
      const radius=1+.37*Math.cos(5*angle+.3)*Math.pow(equator,3);
      position.setXYZ(i,x*radius,y*radius,z*.57*radius);
    }
    geometry.computeVertexNormals();
    const explorer=new THREE.Group();
    this.blob=new THREE.Mesh(geometry,blue);this.blob.castShadow=true;
    this.blob.rotation.set(-.12,.22,.12);explorer.add(this.blob);
    explorer.position.set(-3.1,1.45,.15);explorer.scale.setScalar(.96);
    this.scene.add(explorer);this.agents.explorer=explorer;

    const amber=new THREE.MeshPhysicalMaterial({color:0xffe5b3,metalness:.05,roughness:.1,transmission:.88,thickness:1.3,attenuationColor:new THREE.Color(0xa26729),attenuationDistance:1.8,ior:1.45,clearcoat:1,envMapIntensity:1.45});
    const reviewer=new THREE.Group();
    this.ring=new THREE.Mesh(new THREE.TorusGeometry(.8,.255,32,100),amber);
    this.ring.rotation.set(.08,-.26,-.13);this.ring.castShadow=true;reviewer.add(this.ring);
    const inner=new THREE.Mesh(new THREE.CircleGeometry(.53,48),new THREE.MeshPhysicalMaterial({color:0xf0ce8d,transparent:true,opacity:.08,roughness:.1,metalness:.2,side:THREE.DoubleSide,depthWrite:false}));
    inner.rotation.copy(this.ring.rotation);reviewer.add(inner);
    reviewer.position.set(1.5,1.55,-1.35);this.scene.add(reviewer);this.agents.reviewer=reviewer;

    const organizer=new THREE.Group();this.pebbles=[];
    const charcoal=new THREE.MeshPhysicalMaterial({color:0x161819,roughness:.48,metalness:.28,clearcoat:.45});
    for(let i=0;i<3;i++){
      const pebble=new THREE.Mesh(new THREE.SphereGeometry(1,48,32),charcoal);
      pebble.scale.set(.95-i*.08,.27,.58);pebble.position.set((i-1)*.04,i*.5+.3,0);
      pebble.rotation.set(0,.12+i*.17,i===2?.2:-.05);pebble.castShadow=true;
      organizer.add(pebble);this.pebbles.push(pebble);
    }
    organizer.position.set(4.15,.08,1.25);this.scene.add(organizer);this.agents.organizer=organizer;
    this.activeHalo=new THREE.Mesh(new THREE.RingGeometry(1.2,1.23,80),new THREE.MeshBasicMaterial({color:0x7188d1,transparent:true,opacity:.38,side:THREE.DoubleSide,depthWrite:false}));
    this.activeHalo.rotation.x=-Math.PI/2;this.activeHalo.position.y=.005;this.scene.add(this.activeHalo);
  }

  path(points,color,radius=.013,opacity=.55,closed=false) {
    const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)),closed,'catmullrom',.35);
    const mesh=new THREE.Mesh(new THREE.TubeGeometry(curve,120,radius,6,closed),new THREE.MeshBasicMaterial({color,transparent:true,opacity,depthWrite:false}));
    this.scene.add(mesh);return {curve,mesh};
  }

  setupPaths() {
    // Clockwise action -> tool -> observation -> agent, always closed.
    this.orbit=this.path([[-3.35,.05,-1.28],[-1.08,.05,.05],[-1.45,.05,2.35],[-3.9,.05,3.15],[-5.15,.05,1.15]],0x758acc,.018,.46,true);
    this.handoff=this.path([[-2.25,.65,.4],[-.9,.48,.05],[.3,.38,-.15],[1.25,.4,-.5]],0xb6b1a1,.012,.35);
    this.returnPath=this.path([[1.6,.3,-1.9],[.7,.22,-2.8],[-1.4,.2,-3.1],[-3.6,.35,-1.35]],0xb68340,.025,.08);
    this.exitPath=this.path([[2,.28,-.25],[3.2,.25,.25],[4.5,.22,2.65]],0x777d68,.016,.18);
    const arrow=(path,at,color)=>{
      const mesh=new THREE.Mesh(new THREE.ConeGeometry(.065,.18,12),new THREE.MeshBasicMaterial({color,transparent:true,opacity:.7}));
      mesh.position.copy(path.curve.getPointAt(at));
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),path.curve.getTangentAt(at).normalize());
      this.scene.add(mesh);return mesh;
    };
    this.orbitArrows=[.18,.48,.88].map(at=>arrow(this.orbit,at,0x758acc));
    this.feedbackArrow=arrow(this.returnPath,.9,0xb68340);
    this.loopBeads=[];
    for(let i=0;i<5;i++){
      const bead=new THREE.Mesh(new THREE.SphereGeometry(i===0?.072:.035,14,10),new THREE.MeshBasicMaterial({color:0x355dde,transparent:true,opacity:1-i*.16}));
      this.scene.add(bead);this.loopBeads.push(bead);
    }
    this.packet=new THREE.Mesh(new THREE.SphereGeometry(.095,20,16),new THREE.MeshPhysicalMaterial({color:0xdcb474,roughness:.1,metalness:.45}));
    this.scene.add(this.packet);
    this.toolTray=new THREE.Group();
    const base=new THREE.Mesh(new THREE.BoxGeometry(1.4,.09,.84),new THREE.MeshStandardMaterial({color:0xdedfd5,roughness:.8}));
    base.receiveShadow=true;base.castShadow=true;this.toolTray.add(base);
    for(let i=0;i<3;i++){
      const slot=new THREE.Mesh(new THREE.BoxGeometry(.065,.02,.42),new THREE.MeshStandardMaterial({color:0x879089}));
      slot.position.set(-.24+i*.24,.065,0);this.toolTray.add(slot);
    }
    this.toolTray.position.set(-1.1,.06,1.2);this.scene.add(this.toolTray);
    this.markerPositions={explorer:[-3.1,3,.15],reviewer:[1.5,2.95,-1.35],organizer:[4.15,2.15,1.25],decide:[-4.7,.1,-1.55],tool:[-.65,.12,2.12],observe:[-3.75,.12,3.55],feedback:[-.8,.5,-2.7]};
  }

  setupPhotos() {
    this.photos=[];
    const texture=new THREE.TextureLoader().load('assets/gallery.png',()=>this.render(0,false),undefined,()=>{
      this.container.dispatchEvent(new CustomEvent('asseterror',{bubbles:true}));
    });texture.colorSpace=THREE.SRGBColorSpace;this.galleryTexture=texture;
    for(let i=0;i<6;i++){
      const group=new THREE.Group();
      const frame=new THREE.Mesh(new THREE.BoxGeometry(1.2,.045,.96),new THREE.MeshStandardMaterial({color:0xfffdf7,roughness:.65}));
      frame.castShadow=true;frame.receiveShadow=true;group.add(frame);
      const tile=texture.clone();tile.repeat.set(1/3,1/2);tile.offset.set((i%3)/3,i<3?.5:0);tile.needsUpdate=true;
      const photo=new THREE.Mesh(new THREE.PlaneGeometry(1.08,.81),new THREE.MeshBasicMaterial({map:tile}));
      photo.rotation.x=-Math.PI/2;photo.position.y=.025;group.add(photo);
      group.position.set(-5+i*.27,.15,1.8+i*.15);group.rotation.y=(i-2)*.15;
      this.scene.add(group);this.photos.push(group);
    }
    this.sourcePhoto=this.photos[0];
  }

  resize() {
    const width=this.container.clientWidth,height=this.container.clientHeight;
    if(!width||!height)return;
    this.renderer.setSize(width,height,false);
    const aspect=width/height;
    // Portrait framing uses the same world width; labels retain screen-pixel size.
    const halfWidth=6.3,halfHeight=halfWidth/aspect;
    this.camera.left=-halfWidth;this.camera.right=halfWidth;
    this.camera.top=halfHeight;this.camera.bottom=-halfHeight;this.camera.updateProjectionMatrix();
    this.projectMarkers();this.render(0,false);
  }

  setState(step,snap=false) {
    this.sceneState=step;this.localClock=0;
    this.photoTargets=this.photos.map((_,i)=>new THREE.Vector3(-5.1+(i%2)*.25,.09+i*.025,1.3+Math.floor(i/2)*.26));
    this.photoTargets[0].set(-4.45,.12,-.55);
    const chosen=step.photos;
    chosen.forEach((id,i)=>{
      if(['review','submit'].includes(step.phase))this.photoTargets[id].set(.6+i*1.3,.12,.35);
      else if(['organize','done'].includes(step.phase))this.photoTargets[id].set(3.15+i*1.38,.12,3.1);
      else if(step.phase==='tool')this.photoTargets[id].set(-2.2+i*1.22,.18,1.48);
      else this.photoTargets[id].set(-3.2+i*1.27,.17,2.35);
    });
    this.markers.querySelectorAll('.agent-label').forEach(el=>el.classList.toggle('active',el.dataset.marker===step.agent));
    this.markers.querySelectorAll('.orbit-label').forEach(el=>el.classList.toggle('active',el.dataset.marker===step.phase));
    this.markers.querySelector('.feedback-label').classList.toggle('active',step.phase==='feedback');
    if(snap)this.photos.forEach((photo,i)=>photo.position.copy(this.photoTargets[i]));
    this.render(0,false,snap);
  }

  projectMarkers() {
    if(!this.markerPositions)return;
    const width=this.container.clientWidth,height=this.container.clientHeight;
    this.camera.updateMatrixWorld();
    for(const el of this.markers.querySelectorAll('[data-marker]')){
      const p=new THREE.Vector3(...this.markerPositions[el.dataset.marker]).project(this.camera);
      el.style.left=`${(p.x*.5+.5)*width}px`;el.style.top=`${(-p.y*.5+.5)*height}px`;
    }
  }

  render(delta,animate,snap=false) {
    if(this.failed)return;
    const step=this.sceneState;
    if(animate){this.clock+=Math.min(delta,.1);this.localClock+=Math.min(delta,.1);}
    const time=this.clock,local=this.localClock;
    if(step){
      const exploring=step.agent==='explorer',reviewing=step.agent==='reviewer',organizing=step.agent==='organizer';
      this.blob.rotation.z=.12+(exploring?Math.sin(time*1.25)*.075:0);
      this.blob.rotation.y=.22+(exploring?Math.sin(time*.75)*.19:0);
      const breath=exploring?1+Math.sin(time*2.5)*.022:1;this.blob.scale.set(breath,1/breath,1);
      this.agents.explorer.position.y=1.45+(exploring?Math.sin(time*1.7)*.055:0);
      this.ring.rotation.y=-.26+(reviewing?Math.sin(time*1.4)*.4:0);
      this.agents.reviewer.position.x=1.5+(reviewing?Math.sin(time*1.25)*.22:0);
      this.pebbles.forEach((pebble,i)=>{
        pebble.position.y=i*.5+.3+(organizing&&step.phase!=='done'?Math.sin(time*2-i*.6)*.07:0);
        pebble.rotation.y=.12+i*.17+(organizing?Math.sin(time*.9+i)*.14:0);
      });
      const agent=this.agents[step.agent];this.activeHalo.position.set(agent.position.x,.005,agent.position.z);
      this.activeHalo.material.color.set(step.agent==='explorer'?0x7188d1:step.agent==='reviewer'?0xcaa775:0x777d68);
      this.orbit.mesh.material.opacity=exploring?.52:.16;
      this.orbitArrows.forEach(arrow=>{arrow.material.opacity=exploring?.75:.2;});
      this.feedbackArrow.visible=step.phase==='feedback';
      const phaseStart={decide:.02,tool:.27,observe:.63,submit:.94};
      const start=phaseStart[step.phase]??0;
      this.loopBeads.forEach((bead,i)=>{
        bead.visible=exploring&&['decide','tool','observe'].includes(step.phase);
        const travel=Math.min(local/4,1)*.29;
        bead.position.copy(this.orbit.curve.getPointAt((start+travel-i*.012+1)%1));bead.position.y=.095;
      });
      this.returnPath.mesh.material.opacity=step.phase==='feedback'?.82:.08;
      this.handoff.mesh.material.opacity=step.phase==='submit'?.65:.17;
      this.exitPath.mesh.material.opacity=organizing?.58:.12;
      this.packet.visible=['feedback','submit','organize'].includes(step.phase);
      if(this.packet.visible){
        const path=step.phase==='feedback'?this.returnPath:step.phase==='submit'?this.handoff:this.exitPath;
        this.packet.position.copy(path.curve.getPointAt(snap?.6:Math.min(local/3.3,1)));
      }
      this.toolTray.children[0].material.color.set(step.phase==='tool'?0xcbd3e7:0xdedfd5);
      this.photos.forEach((photo,i)=>{
        if(!this.photoTargets)return;
        const lerp=snap?1:animate?1-Math.exp(-delta*4.5):0;
        photo.position.lerp(this.photoTargets[i],lerp);
        const selected=step.photos.includes(i);
        const targetRotation=selected?(['organize','done'].includes(step.phase)?0:(i%2?-.1:.09)):(i-2)*.15;
        photo.rotation.y=THREE.MathUtils.lerp(photo.rotation.y,targetRotation,lerp);
        const targetScale=selected?1: i===0?.93:.78;
        photo.scale.lerp(new THREE.Vector3(targetScale,targetScale,targetScale),lerp);
      });
    }
    this.renderer.render(this.scene,this.camera);
  }

  dispose() {
    this.resizeObserver.disconnect();
    this.scene.traverse(object=>{
      object.geometry?.dispose();
      const materials=object.material?(Array.isArray(object.material)?object.material:[object.material]):[];
      materials.forEach(material=>{material.map?.dispose();material.dispose();});
    });
    this.environment.dispose();this.galleryTexture.dispose();this.shadowTexture.dispose();this.renderer.dispose();
  }
}
