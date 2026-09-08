import {steps,chapters,currentChapter,Playback} from './scenario.js';

const $=id=>document.getElementById(id);
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
let scene=null,sceneFailed=false,lastFrame=0,lastRender=0;
const names={explorer:'EXPLORER',reviewer:'REVIEWER',organizer:'ORGANIZER'};
const photoLabels=['선택한 와인병','와인과 함께한 식사','와인 진열대','야외 인물','커피와 디저트','해변 인물'];
const chapterButtons=chapters.map((chapter,i)=>{
  const button=document.createElement('button');button.type='button';button.className='chapter-button';
  const number=document.createElement('span');number.textContent=`0${i+1}`;button.append(number,document.createTextNode(chapter.label));
  button.addEventListener('click',()=>player.seek(chapter.start));$('chapters').append(button);return button;
});

function showFallback(){
  sceneFailed=true;$('fallback').hidden=false;$('viewport').hidden=true;$('scene-labels').hidden=true;
}

function update(player){
  const step=steps[player.index],number=String(player.index+1).padStart(2,'0');
  $('step-count').textContent=`${number} / ${steps.length}`;$('progress-label').textContent=`${number} / ${steps.length}`;
  $('scrubber').value=player.index;$('scrubber').setAttribute('aria-valuetext',`${player.index+1}단계: ${step.title}`);
  $('active-agent').textContent=names[step.agent];$('active-agent').style.color=step.agent==='explorer'?'#3158d4':step.agent==='reviewer'?'#ad7139':'#434941';
  $('action-title').textContent=step.title;$('action-description').textContent=step.description;
  $('evidence-label').textContent=step.label;$('evidence-value').textContent=step.evidence;
  $('motion-caption').textContent=step.caption;
  const phaseCount=step.agent==='explorer'?`LOOP ${String(step.round).padStart(2,'0')}`:step.agent==='reviewer'?`PASS ${step.round===2?'01':'02'}`:step.phase==='done'?'COMPLETE':'RESULT';
  $('scene-count').textContent=`${names[step.agent]} · ${phaseCount}`;
  $('play').replaceChildren(document.createTextNode(player.playing?'일시정지':player.index===steps.length-1?'다시 재생':'재생'));
  const symbol=document.createElement('span');symbol.setAttribute('aria-hidden','true');symbol.textContent=player.playing?'Ⅱ':'▶';$('play').append(symbol);
  $('play').setAttribute('aria-label',player.playing?'시연 일시정지':player.index===steps.length-1?'시연 다시 재생':'시연 재생');
  $('previous').disabled=player.index===0;$('next').disabled=player.index===steps.length-1;
  chapterButtons.forEach((button,i)=>{if(i===currentChapter(player.index))button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});
  $('photo-evidence').replaceChildren(...step.photos.map(id=>{
    const photo=document.createElement('div');photo.className=`photo photo-${id} evidence-thumb ${step.verdict||''}`;
    photo.setAttribute('role','img');photo.setAttribute('aria-label',`${photoLabels[id]}${step.verdict==='rejected'?' · 검토 미통과':step.verdict==='supported'?' · 검토 통과':' · 확인 전 후보'}`);
    return photo;
  }));
  const feedback=step.phase==='feedback',finished=step.phase==='done';
  $('loop-indicator').textContent=feedback?'↶ REVIEW FEEDBACK':finished?'✓ LOOP COMPLETE':step.agent==='organizer'?'↗ ORGANIZE & FINISH':step.agent==='reviewer'?'◎ INDEPENDENT REVIEW':'↻ AGENT LOOP';
  $('note-symbol').textContent=feedback?'↶':finished?'✓':step.agent==='reviewer'?'◎':'↻';
  $('loop-note').textContent=feedback?'검토에서 돌아오는 피드백은 조건부로 한 번만 허용됩니다.':finished?'확인된 결과를 만들고 멈춥니다. 실행 예산 안에서 반복합니다.':step.agent==='reviewer'?'탐색의 주장과 분리해 원본 사진과 후보를 독립적으로 비교합니다.':step.agent==='organizer'?'검토된 후보의 관계를 정리하고 결과를 구성합니다.':'도구가 돌려준 관찰 결과를 받아 다음 행동을 선택합니다.';
  const stateChanged=scene&&scene.sceneState!==step;
  if(stateChanged)scene.setState(step,!player.playing||reducedMotion.matches);
  document.body.dataset.step=String(player.index);document.body.dataset.playing=String(player.playing);
  document.body.dataset.phase=step.phase;
}

const player=new Playback(update,reducedMotion.matches);
$('play').addEventListener('click',()=>player.toggle());
$('previous').addEventListener('click',()=>player.seek(player.index-1));
$('next').addEventListener('click',()=>player.seek(player.index+1));
$('restart').addEventListener('click',()=>player.seek(0));
$('scrubber').addEventListener('input',event=>player.seek(Number(event.target.value)));
$('speed').addEventListener('change',event=>{player.speed=Number(event.target.value);});
$('notes-toggle').addEventListener('click',()=>{
  const expanded=$('notes-toggle').getAttribute('aria-expanded')!=='true';
  $('notes-toggle').setAttribute('aria-expanded',String(expanded));$('presenter-notes').hidden=!expanded;
  $('notes-toggle').textContent=expanded?'구조 설명 −':'구조 설명 ＋';
});
$('fullscreen').addEventListener('click',async()=>{
  try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}
  catch{$('fullscreen').textContent='브라우저 전체화면을 사용해주세요';}
});
document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'전체화면 종료 ↙':'전체화면 ↗';});
document.addEventListener('keydown',event=>{
  if(event.ctrlKey||event.altKey||event.metaKey||event.target.closest('button,input,select,textarea,a,[contenteditable]'))return;
  if(event.code==='Space'){event.preventDefault();player.toggle();}
  if(event.key==='ArrowRight'){event.preventDefault();player.seek(player.index+1);}
  if(event.key==='ArrowLeft'){event.preventDefault();player.seek(player.index-1);}
  if(event.key==='Home'){event.preventDefault();player.seek(0);}
});
document.addEventListener('visibilitychange',()=>{
  // Pause deliberately; coming back never skips unseen presentation steps.
  if(document.hidden&&player.playing){player.playing=false;player.emit();}
  lastFrame=0;
});
reducedMotion.addEventListener('change',()=>{
  player.reducedMotion=reducedMotion.matches;
  if(reducedMotion.matches){player.playing=false;player.emit();scene?.setState(steps[player.index],true);}
});
$('viewport').addEventListener('asseterror',()=>{
  $('load-notice').textContent='사진 파일을 불러오지 못했습니다. assets 폴더가 함께 있는지 확인해주세요.';$('load-notice').hidden=false;
});
update(player);$('load-notice').hidden=true;

async function start(){
  try{
    const {AgentScene}=await import('./scene.js');
    scene=new AgentScene($('viewport'),$('scene-labels'),showFallback);scene.setState(steps[0],true);
  }catch(error){console.warn('3D presentation unavailable; using the concept fallback.',error);showFallback();}
  document.body.dataset.ready='true';
  // Start with a short, useful opening scene; reduced motion stays user-controlled.
  if(!reducedMotion.matches&&!document.hidden){player.playing=true;player.emit();}
  requestAnimationFrame(frame);
}

function frame(now){
  if(!document.hidden){
    const delta=lastFrame?Math.min(now-lastFrame,250):0;lastFrame=now;
    player.tick(delta);
    if(scene&&!sceneFailed&&player.playing&&!reducedMotion.matches&&now-lastRender>=1000/30){
      const seconds=lastRender?Math.min((now-lastRender)/1000,.1):0;lastRender=now;
      scene.render(seconds,true);
    }
  }
  requestAnimationFrame(frame);
}
window.addEventListener('pagehide',event=>{if(!event.persisted)scene?.dispose();});
start();
