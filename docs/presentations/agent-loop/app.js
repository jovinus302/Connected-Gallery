import {steps,chapters,currentChapter,Playback} from './scenario.js';
import {storyFor} from './storyboard.js';
const $=id=>document.getElementById(id),reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
let scene=null,failed=false,lastFrame=0,lastRender=0;
const names={explorer:'EXPLORER',reviewer:'REVIEWER',organizer:'ORGANIZER'};
const actionTitles=['선택한 와인으로 검색.','검색 도구가 후보를 찾습니다.','후보 정보가 돌아옵니다.','이제 사진을 직접 확인.','후보 이미지를 가져옵니다.','이미지가 관찰로 돌아옵니다.','후보를 독립 검토에 전달.','원본과 후보를 비교합니다.','근거 부족을 탐색에 돌려줍니다.','피드백으로 검색을 바꿉니다.','구체적인 단서로 다시 검색.','새 후보 정보가 돌아옵니다.','새 후보도 직접 확인.','비교할 이미지를 가져옵니다.','확인한 이미지가 돌아옵니다.','새 후보를 검토에 전달.','라벨과 형태의 근거를 확인.','검토된 사진을 관계별로.','사진과 연결 이유가 남습니다.'];
const chapterButtons=chapters.map((chapter,i)=>{
  const button=document.createElement('button');button.type='button';button.className='chapter-button';const n=document.createElement('span');n.textContent=`0${i+1}`;
  button.append(n,document.createTextNode(chapter.label));button.addEventListener('click',()=>player.seek(chapter.start));$('chapters').append(button);return button;
});
function fallback(){failed=true;$('fallback').hidden=false;$('viewport').hidden=true;$('scene-labels').hidden=true;$('photo-stage-overlay').hidden=true;$('payload').hidden=true;}
function update(player){
  const step=steps[player.index],story=storyFor(step),number=String(player.index+1).padStart(2,'0');
  $('step-count').textContent=`${number} / ${steps.length}`;$('progress-label').textContent=`${number} / ${steps.length}`;
  $('scrubber').value=player.index;$('scrubber').setAttribute('aria-valuetext',`${player.index+1}단계: ${step.title}`);
  $('active-agent').textContent=step.phase==='feedback'?'REVIEWER → EXPLORER':step.phase==='submit'?'EXPLORER → REVIEWER':names[step.agent];
  $('scene-count').textContent=step.agent==='explorer'?`LOOP ${String(step.round).padStart(2,'0')}`:step.agent==='reviewer'?`REVIEW ${step.round===2?'01':'02'}`:step.phase==='done'?'COMPLETE':'RESULT';
  $('action-title').textContent=actionTitles[player.index];$('action-description').textContent=step.description;
  $('evidence-label').textContent=step.label;$('evidence-value').textContent=step.evidence;$('motion-caption').textContent=step.caption;
  $('request-text').textContent=story.request;$('observation').textContent=story.observation;$('camera-label').textContent=story.camera;
  document.querySelector('.stage').dataset.shot=story.shot;
  $('payload').dataset.direction=story.payload.direction;$('payload').hidden=failed||story.payload.direction==='none';
  $('payload-title').textContent=story.payload.title;$('payload-detail').textContent=story.payload.detail;
  document.querySelectorAll('[data-cast]').forEach(el=>el.classList.toggle('active',el.dataset.cast===step.agent));
  $('loop-indicator').textContent=step.phase==='feedback'?'↶ REVIEW FEEDBACK':step.phase==='done'?'✓ LOOP COMPLETE':step.agent==='organizer'?'↗ ORGANIZE & FINISH':step.agent==='reviewer'?'◎ INDEPENDENT REVIEW':step.phase==='observe'?'↶ OBSERVATION → AGENT':'↻ AGENT LOOP';
  $('play').replaceChildren(document.createTextNode(player.playing?'일시정지':player.index===18?'다시 재생':'재생'));
  const icon=document.createElement('span');icon.setAttribute('aria-hidden','true');icon.textContent=player.playing?'Ⅱ':'▶';$('play').append(icon);
  $('play').setAttribute('aria-label',player.playing?'시연 일시정지':player.index===18?'시연 다시 재생':'시연 재생');
  $('previous').disabled=player.index===0;$('next').disabled=player.index===18;
  chapterButtons.forEach((button,i)=>{if(i===currentChapter(player.index))button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});
  if(scene&&scene.sceneState!==step)scene.setState(step,story,!player.playing||reducedMotion.matches);
  document.body.dataset.step=String(player.index);document.body.dataset.phase=step.phase;document.body.dataset.playing=String(player.playing);
}
const player=new Playback(update,reducedMotion.matches);
$('play').addEventListener('click',()=>player.toggle());$('previous').addEventListener('click',()=>player.seek(player.index-1));$('next').addEventListener('click',()=>player.seek(player.index+1));$('restart').addEventListener('click',()=>player.seek(0));
$('scrubber').addEventListener('input',event=>player.seek(Number(event.target.value)));$('speed').addEventListener('change',event=>{player.speed=Number(event.target.value);});
$('notes-toggle').addEventListener('click',()=>{const open=$('notes-toggle').getAttribute('aria-expanded')!=='true';$('notes-toggle').setAttribute('aria-expanded',String(open));$('presenter-notes').hidden=!open;$('notes-toggle').textContent=open?'구조 설명 −':'구조 설명 ＋';});
$('fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{$('fullscreen').textContent='브라우저 전체화면을 사용해주세요';}});
document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'전체화면 종료 ↙':'전체화면 ↗';});
document.addEventListener('keydown',event=>{
  if(event.ctrlKey||event.altKey||event.metaKey||event.target.closest('button,input,select,textarea,a,[contenteditable]'))return;
  if(event.code==='Space'){event.preventDefault();player.toggle();}if(event.key==='ArrowRight'){event.preventDefault();player.seek(player.index+1);}if(event.key==='ArrowLeft'){event.preventDefault();player.seek(player.index-1);}if(event.key==='Home'){event.preventDefault();player.seek(0);}
});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&player.playing){player.playing=false;player.emit();}lastFrame=0;});
reducedMotion.addEventListener('change',()=>{if(reducedMotion.matches){player.playing=false;player.emit();scene?.setState(steps[player.index],storyFor(steps[player.index]),true);}});
update(player);$('load-notice').hidden=true;
async function start(){
  try{const {AgentScene}=await import('./scene.js');scene=new AgentScene($('viewport'),$('scene-labels'),fallback);scene.setState(steps[0],storyFor(steps[0]),reducedMotion.matches);}
  catch(error){console.warn('3D unavailable; using the concept fallback.',error);fallback();}
  document.body.dataset.ready='true';if(!reducedMotion.matches&&!document.hidden){player.playing=true;player.emit();}requestAnimationFrame(frame);
}
function frame(now){
  if(!document.hidden){const delta=lastFrame?Math.min(now-lastFrame,250):0;lastFrame=now;player.tick(delta);
    if(scene&&!failed&&player.playing&&!reducedMotion.matches&&now-lastRender>=1000/30){lastRender=now;scene.render(player.elapsed/steps[player.index].duration);}}
  requestAnimationFrame(frame);
}
window.addEventListener('pagehide',event=>{if(!event.persisted)scene?.dispose();});start();
