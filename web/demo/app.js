/* Photo context and subject connections are independent authenticated views. */
"use strict";
const $ = id => document.getElementById(id);
let catalog = [], total = 0, revision = 0, current = null, history = [], generation = 0, active = null;
let searchGeneration = 0;
let liveEnabled = true, activeRun = null;
let photoGeneration = 0, analysisRequest = null, contextRequest = null, libraryScroll = 0;
const contextAttempts = new Set();
function node(tag, cls, text) { const el=document.createElement(tag); if(cls)el.className=cls; if(text!==undefined)el.textContent=text; return el; }
function show(id) { ["login","library","detail"].forEach(x=>$(x).classList.toggle("hidden",x!==id)); $("logout").classList.toggle("hidden",id==="login"); }
function notify(text) { $("global-error").textContent=text; $("global-error").classList.remove("hidden"); setTimeout(()=>$("global-error").classList.add("hidden"),5000); }
async function api(path, body, signal) {
  const options={credentials:"same-origin",cache:"no-store",signal};
  if(body!==undefined){options.method="POST";options.headers={"Content-Type":"application/json"};options.body=JSON.stringify(body);}
  const response=await fetch(path,options);
  if(response.status===401){generation++;active?.abort();stopPhotoRequests();current=null;history=[];show("login");throw new Error("로컬 세션이 필요합니다. 시작 도구에서 다시 연결해주세요.");}
  if(!response.ok){const error=new Error(response.status===403?"이 데모에서는 허용되지 않는 요청입니다.":"요청을 완료하지 못했어요. 다시 시도해주세요.");error.status=response.status;throw error;}
  return response.json();
}
function cancelRun(id){if(id)api(`/runs/${encodeURIComponent(id)}/cancel`,{}).catch(()=>{});}
function stopRequest(){generation++;searchGeneration++;active?.abort();active=null;const id=activeRun;activeRun=null;cancelRun(id);}
function stopPhotoRequests(){photoGeneration++;analysisRequest?.abort();contextRequest?.abort();analysisRequest=null;contextRequest=null;}
function preview(id){return `/assets/${encodeURIComponent(id)}/preview`;}
function photoCard(asset,index){
  const button=node("button","photo-card");button.setAttribute("aria-label",asset.description||`사진 ${index+1} 열기`);
  const frame=node("div","photo-frame"), image=node("img");image.src=preview(asset.id);image.alt=asset.description||"샘플 사진";image.loading="lazy";
  frame.append(image,node("span","photo-number",`${String(index+1).padStart(2,"0")} · ${asset.region_count}개 대상`));
  const caption=node("div","photo-caption");caption.append(node("p","",asset.description||"사진 분석을 준비하고 있어요"),node("span","arrow","↗"));button.append(frame,caption);button.onclick=()=>openPhoto(asset.id);return button;
}
async function loadCatalog(){
  const request=++searchGeneration, query=$("search").value.trim();
  try{const data=await api(`/demo/catalog?q=${encodeURIComponent(query)}`);if(request!==searchGeneration)return;
    catalog=data.assets;total=data.total;revision=data.revision;liveEnabled=data.live_enabled!==false;$("grid").replaceChildren(...catalog.map(photoCard));
    $("library-stat").textContent=`${total}장의 가상 사진`;$("grid-title").textContent=query?`‘${query}’ 검색 결과`:"모든 사진";
    $("grid-count").textContent=`${catalog.length}장`;$("grid-empty").classList.toggle("hidden",catalog.length>0);$("clear-search").classList.toggle("hidden",!query);show("library");
  }catch(error){if(error.name!=="AbortError"&&$("login").classList.contains("hidden"))notify(error.message);}
}
function remember(){if(current)history.push({id:current.id,revision:current.revision,analysis:current.analysis,region:current.region,result:current.result,prepared:current.prepared,context:current.context,expanded:[...current.expanded],scroll:window.scrollY});else libraryScroll=window.scrollY;}
async function openPhoto(id,restore=null){
  stopRequest();stopPhotoRequests();const ticket=photoGeneration;
  if(!restore)remember();current={id,revision,analysis:null,region:null,result:null,context:null,expanded:new Set()};show("detail");window.scrollTo({top:0,behavior:"instant"});
  $("source-photo").src=preview(id);$("source-photo").alt="선택한 사진";$("regions").replaceChildren();$("region-chips").replaceChildren();$("source-description").textContent="";$("source-count").textContent="";resetResults();resetContext();
  // Context loading is independent of target selection. A subject click must
  // never cancel this photo's context, or let an older photo overwrite it.
  // A fresh context response checks existence and revision before history is
  // reused. This promise covers the initial render, never model preparation.
  const contextLoaded=loadContext(id,ticket);
  analysisRequest=new AbortController();const signal=analysisRequest.signal;
  try{
    const initialContext=restore?await contextLoaded:null;
    if(ticket!==photoGeneration||current?.id!==id)return;
    const reuse=restore&&initialContext&&restore.revision===initialContext.revision&&restore.revision===revision;
    current.revision=reuse?restore.revision:revision;
    const analysis=(reuse&&restore.analysis)||await api(`/assets/${encodeURIComponent(id)}/analysis`,undefined,signal);if(ticket!==photoGeneration||current?.id!==id)return;
    current.analysis=analysis;$("source-photo").alt=analysis.description||"선택한 사진";$("source-description").textContent=analysis.description||"";
    $("source-count").textContent=`${analysis.regions.length}개 대상`;paintRegions();
    if(!analysis.regions.length)$("region-chips").append(node("p","fine",analysis.pending?"이 사진의 대상을 아직 준비하고 있어요.":"선택할 대상을 찾지 못했어요. 다른 사진을 열어보세요."));
    if(reuse){
      current.expanded=new Set(restore.expanded||[]);if(current.context)renderContext(current.context);
      const region=analysis.regions.find(item=>item.id===restore.region?.id);
      if(region){current.region=region;highlightRegion();if(restore.result){current.result=restore.result;renderResult(restore.result,restore.prepared===true);}else void selectRegion(region);}
    }
    if(restore)await restorePhotoScroll(restore.scroll||0,id,ticket);
  }catch(error){if(ticket!==photoGeneration||error.name==="AbortError")return;if(error.status===404)unavailablePhoto(id,ticket);else notify(error.message);}
}
function unavailablePhoto(id,ticket){
  if(ticket!==photoGeneration||current?.id!==id)return;
  stopRequest();stopPhotoRequests();history=history.filter(entry=>entry.id!==id);current=null;
  $("source-photo").removeAttribute("src");$("regions").replaceChildren();$("region-chips").replaceChildren();$("result-content").replaceChildren();$("context-content").replaceChildren();
  show("library");notify("이 사진은 더 이상 갤러리에 없어요. 다른 사진을 선택해주세요.");void loadCatalog();window.scrollTo({top:libraryScroll,behavior:"instant"});
}
async function restorePhotoScroll(top,id,ticket){
  const img=$("source-photo");
  if(!img.complete)await new Promise(resolve=>{const done=()=>{img.removeEventListener("load",done);img.removeEventListener("error",done);resolve();};img.addEventListener("load",done,{once:true});img.addEventListener("error",done,{once:true});});
  await new Promise(resolve=>window.requestAnimationFrame(resolve));
  if(ticket===photoGeneration&&current?.id===id)window.scrollTo({top,behavior:"instant"});
}
function resetContext(){
  $("photo-context").setAttribute("aria-busy","true");
  $("capture-info").textContent="";$("capture-info").classList.add("hidden");$("context-state").className="status-badge pending";$("context-state").textContent="확인 중";
  $("context-content").replaceChildren(node("p","context-message","이 사진과 함께 볼 사진을 확인하고 있어요."));
}
function applyContext(data,id,ticket){
  if(ticket!==photoGeneration||current?.id!==id||data.photo_id!==id)return false;
  current.context=data;renderContext(data);return true;
}
async function loadContext(id,ticket=photoGeneration){
  contextRequest?.abort();contextRequest=new AbortController();const signal=contextRequest.signal;
  const valid=()=>ticket===photoGeneration&&current?.id===id&&!signal.aborted;
  const accept=data=>{if(!applyContext(data,id,ticket))throw new Error("Unexpected context photo");if(Number.isInteger(data.revision))revision=Math.max(revision,data.revision);};
  const failed=error=>{if(!valid()||error.name==="AbortError")return;if(error.status===404)unavailablePhoto(id,ticket);else applyContext({photo_id:id,state:"failed",revision,context:null},id,ticket);};
  async function continuePreparation(data){
    try{
      const key=`${id}:${data.revision}`;
      if(liveEnabled&&["pending","failed"].includes(data.state)&&!contextAttempts.has(key)){
        contextAttempts.add(key);data=await api(`/assets/${encodeURIComponent(id)}/context/prepare`,{},signal);if(!valid())return;accept(data);
      }
      const deadline=Date.now()+330000;
      while(valid()&&data.state==="running"){
        if(Date.now()>=deadline){$("context-content").append(node("p","context-message","준비가 계속되고 있어요. 잠시 후 다시 확인해주세요."),contextRefresh(id));return;}
        await delay(1200,signal);data=await api(`/assets/${encodeURIComponent(id)}/context`,undefined,signal);if(!valid())return;accept(data);
      }
    }catch(error){failed(error);}
  }
  try{
    const data=await api(`/assets/${encodeURIComponent(id)}/context`,undefined,signal);if(!valid())return null;accept(data);
    void continuePreparation(data);return data;
  }catch(error){failed(error);return null;}
}
function contextRefresh(id){const button=node("button","context-refresh","다시 확인");button.onclick=()=>{if(current?.id===id)loadContext(id);};return button;}
function renderContext(data){
  const content=$("context-content"),badge=$("context-state"),capture=$("capture-info");content.replaceChildren();
  $("photo-context").setAttribute("aria-busy",String(data.state==="running"));
  const date=data.capture?.date,source=data.capture?.source;
  const hasDate=typeof date==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(date)&&["demo_fixture","exif","media_store"].includes(source);
  capture.textContent=hasDate?`${source==="demo_fixture"?"데모 설정 날짜":"촬영일"} · ${date.replaceAll("-",".")}`:"";capture.classList.toggle("hidden",!hasDate);
  const state=data.state;badge.className=`status-badge${["pending","running"].includes(state)?" pending":""}`;
  const labels={ready:"함께 볼 사진",empty:"확인 완료",pending:"준비 전",running:"준비 중",failed:"확인 필요"};badge.textContent=labels[state]||"확인 필요";
  if(state!=="ready"){
    const messages={empty:"현재 확보한 사진에서는 함께 볼 만한 관계를 확인하지 못했어요.",pending:"이 사진의 주변 관계는 아직 준비되지 않았어요.",running:"함께 볼 사진과 그 이유를 준비하고 있어요.",failed:"이 사진의 주변 관계를 확인하지 못했어요. 잠시 후 다시 확인해주세요."};
    content.append(node("p","context-message",messages[state]||messages.failed));
    if(["pending","failed"].includes(state))content.append(contextRefresh(data.photo_id));return;
  }
  if(data.context?.summary)content.append(node("p","context-summary",data.context.summary));
  const groups=data.context?.groups||[];
  if(!groups.length){content.append(node("p","context-message","함께 볼 사진 목록을 불러오지 못했어요."));return;}
  groups.forEach((group,index)=>{
    const ids=[...new Set(group.photo_ids||[])].filter(id=>typeof id==="string"&&id!==current.id);if(!ids.length)return;
    const groupId=group.id||String(index),expanded=current.expanded.has(groupId),section=node("section","context-group"),heading=node("div","group-heading");
    heading.append(node("h3","",group.title),node("span","",`${ids.length}장`));section.append(heading);if(group.reason)section.append(node("p","group-reason",group.reason));
    const grid=node("div","context-grid");
    (expanded?ids:ids.slice(0,3)).forEach((id,i)=>{const button=node("button","context-card"),img=node("img");img.src=preview(id);img.alt=`${group.title} · 사진 ${i+1}`;img.loading="lazy";button.setAttribute("aria-label",`${group.title} · 사진 ${i+1} 열기`);button.append(img,node("span","",`사진 열기 ↗`));button.onclick=()=>openPhoto(id);grid.append(button);});section.append(grid);
    if(ids.length>3){const more=node("button","context-expand",expanded?"접기":`사진 ${ids.length}장 모두 보기`);more.setAttribute("aria-expanded",String(expanded));more.onclick=()=>{if(expanded)current.expanded.delete(groupId);else current.expanded.add(groupId);renderContext(data);};section.append(more);}
    content.append(section);
  });
}
function regionLayers(regions){
  // Preserve displayed numbering while allowing a smaller selectable subject
  // to receive pointer hits above a surrounding scene rectangle.
  const ordered=regions.map((region,index)=>({id:region.id,index,area:region.box.width*region.box.height})).sort((a,b)=>b.area-a.area||a.index-b.index);
  return new Map(ordered.map((entry,index)=>[entry.id,index+1]));
}
function paintRegions(){
  const layer=$("regions"),chips=$("region-chips");layer.replaceChildren();chips.replaceChildren();
  const layers=regionLayers(current?.analysis?.regions||[]);
  (current?.analysis?.regions||[]).forEach((region,index)=>{
    const box=node("button","region-box"),b=region.box;box.dataset.id=region.id;box.title=region.label;box.setAttribute("aria-label",`${region.label} 연결하기`);
    box.style.left=`${b.x*100}%`;box.style.top=`${b.y*100}%`;box.style.width=`${b.width*100}%`;box.style.height=`${b.height*100}%`;box.style.zIndex=String(layers.get(region.id));box.append(node("span","",String(index+1)));box.onclick=()=>selectRegion(region);layer.append(box);
    const chip=node("button","region-chip");chip.dataset.id=region.id;chip.append(node("span","",String(index+1)),document.createTextNode(region.label));chip.onclick=()=>selectRegion(region);chips.append(chip);
  });fitRegions();
}
function fitRegions(){const img=$("source-photo"),stage=$("photo-stage"),layer=$("regions");if(!img.naturalWidth)return;
  const scale=Math.min(img.clientWidth/img.naturalWidth,img.clientHeight/img.naturalHeight),w=img.naturalWidth*scale,h=img.naturalHeight*scale;
  layer.style.width=`${w}px`;layer.style.height=`${h}px`;layer.style.left=`${(stage.clientWidth-w)/2}px`;layer.style.top=`${(stage.clientHeight-h)/2}px`;layer.style.right="auto";layer.style.bottom="auto";
}
function highlightRegion(){document.querySelectorAll(".region-box,.region-chip").forEach(el=>el.classList.toggle("selected",el.dataset.id===current?.region?.id));$("trail-label").textContent=current?.region?.label||"대상 선택";}
function resetResults(){
  $("trail-label").textContent="대상 선택";$("ready-badge").classList.add("hidden");$("result-title").textContent="선택한 부분에서 이어집니다";
  $("result-subtitle").textContent="관심 있는 대상을 고르면, 관련 사진을 관계별로 정리해 보여드려요.";
  const placeholder=node("div","result-placeholder"),glyph=node("div","connection-glyph");glyph.append(node("span"),node("span"),node("span"));placeholder.append(glyph,node("p","","사진 속 대상을 선택해보세요"));const small=node("small","","같은 사진에서도 선택한 부분에 따라 연결되는 사진이 달라집니다.");placeholder.append(small);$("result-content").replaceChildren(placeholder);
}
function loading(){const box=node("div","loading");box.append(node("span","spinner"),node("p","","관련 사진을 찾고 관계를 확인하고 있어요."),node("small","","처음 선택한 대상은 준비에 시간이 걸릴 수 있어요."));$("result-content").replaceChildren(box);$("result-title").textContent=current.region.label;$("result-subtitle").textContent="사진에 담긴 근거를 살펴 연결 결과를 정리합니다.";$("ready-badge").textContent="준비 중";$("ready-badge").className="status-badge pending";}
const delay=(ms,signal)=>new Promise((resolve,reject)=>{const timeout=setTimeout(done,ms);function done(){signal.removeEventListener("abort",cancel);resolve();}function cancel(){clearTimeout(timeout);reject(new DOMException("Aborted","AbortError"));}signal.addEventListener("abort",cancel,{once:true});if(signal.aborted)cancel();});
async function selectRegion(region){
  stopRequest();const ticket=generation;active=new AbortController();const signal=active.signal;current.region=region;current.result=null;highlightRegion();loading();
  const explore={anchor:{photo_id:current.id,region_id:region.id,box:region.box,label:region.label,kind:region.kind},direction:"related",request_revision:revision};
  try{const ready=await api("/explorations/ready",explore,signal);if(ticket!==generation)return;revision=ready.revision;
    if(ready.state==="ready"){current.result=ready.result;renderResult(ready.result,true);return;}
    if(!liveEnabled){$("ready-badge").textContent="준비 필요";$("result-subtitle").textContent="이 대상의 연결은 아직 준비되지 않았어요.";const box=node("div","empty");box.append(node("p","","준비가 끝나면 이 대상을 다시 선택해주세요."),node("small","","현재 데모는 미리 준비된 결과만 보여줍니다."));const refresh=node("button","retry","준비 상태 다시 확인");refresh.onclick=()=>selectRegion(region);box.append(refresh);$("result-content").replaceChildren(box);return;}
    // Let creation return its run ID even if the user navigates meanwhile, so
    // that obsolete server work can be explicitly cancelled rather than leaked.
    let run=await api("/runs",{role:"explorer",photo_ids:[],explore,idempotency_key:crypto.randomUUID()});
    if(ticket!==generation){cancelRun(run.id);return;}activeRun=run.id;
    const deadline=Date.now()+180000;
    while(["queued","running"].includes(run.status)){if(Date.now()>deadline)throw new Error("준비가 계속되고 있어요. 잠시 후 이 대상을 다시 선택해주세요.");await delay(1000,signal);run=await api(`/runs/${encodeURIComponent(run.id)}`,undefined,signal);if(ticket!==generation)return;}
    if(!run.result)throw new Error("연결을 준비하지 못했어요. 잠시 후 다시 시도해주세요.");
    if(ticket!==generation)return;activeRun=null;current.result=run.result;renderResult(run.result,false);
  }catch(error){if(ticket!==generation||error.name==="AbortError")return;const id=activeRun;activeRun=null;cancelRun(id);$("ready-badge").classList.add("hidden");const box=node("div","empty");box.append(node("p","",error.message));const retry=node("button","retry","다시 시도");retry.onclick=()=>selectRegion(region);box.append(retry);$("result-content").replaceChildren(box);}
}
function renderResult(result,prepared){
  prepared=prepared&&result.complete!==false&&result.grouping_status==="ready";current.prepared=prepared;
  $("result-title").textContent=current.region?.label||result.label;const badge=$("ready-badge");badge.className="status-badge";badge.textContent=prepared?"준비된 연결":"연결 결과";
  const items=new Map((result.items||[]).map(x=>[x.photo_id,x])),groups=result.groups||[];
  $("result-subtitle").textContent=items.size?`${items.size}장의 관련 사진 · 원하는 사진을 열어 다른 대상을 선택할 수 있어요.`:"현재 사진에서 확인할 수 있는 관련 결과가 없어요.";
  const content=$("result-content");content.replaceChildren();
  if(result.grouping_status!=="ready"){content.append(node("p","notice",result.grouping_status==="failed"?"관계별 정리를 완료하지 못했어요. 확인된 사진을 먼저 보여드려요.":"이전 형식의 연결 결과입니다. 관계별 정리는 아직 준비되지 않았어요."));}
  if(result.complete===false)content.append(node("p","notice","검색이 완전히 끝나지 않았어요. 현재까지 확인된 결과입니다."));
  if(!items.size){content.append(node("p","empty",result.complete===false?"아직 확인된 연결이 없어요.":"확인된 관련 사진이 없어요. 다른 대상을 선택해보세요."));return;}
  const seen=new Set();
  function appendGroup(title,reason,ids){const valid=ids.filter(id=>items.has(id)&&!seen.has(id));if(!valid.length)return;
    const section=node("section","result-group"),heading=node("div","group-heading");heading.append(node("h3","",title),node("span","",String(valid.length)));section.append(heading);if(reason)section.append(node("p","group-reason",reason));
    const grid=node("div","group-grid");valid.forEach(id=>{seen.add(id);const item=items.get(id),button=node("button","result-card"),img=node("img");img.src=preview(id);img.alt=item.reason||"연결된 사진";button.setAttribute("aria-label",`${item.reason||"연결된 사진"} 열기`);button.append(img,node("p","",item.reason),node("span","open-hint","이 사진에서 이어가기 ↗"));button.onclick=()=>openPhoto(id);grid.append(button);});section.append(grid);content.append(section);
  }
  groups.forEach(g=>appendGroup(g.title,g.reason,g.photo_ids||[]));appendGroup("관련 사진","",[...items.keys()]);
}
$("source-photo").addEventListener("load",fitRegions);window.addEventListener("resize",fitRegions);
$("back").onclick=()=>{stopRequest();const previous=history.pop();if(previous)openPhoto(previous.id,previous);else{stopPhotoRequests();current=null;show("library");window.scrollTo({top:libraryScroll,behavior:"instant"});}};
$("search-form").onsubmit=e=>{e.preventDefault();loadCatalog();};$("clear-search").onclick=()=>{$("search").value="";loadCatalog();};
$("login-form").onsubmit=async e=>{e.preventDefault();$("login-error").textContent="";const key=$("key").value;$("key").value="";try{await api("/demo/session",{key});await loadCatalog();}catch(error){$("login-error").textContent="시작 키가 만료되었거나 이미 사용됐어요. 시작 도구에서 새 키를 받아주세요.";}};
$("logout").onclick=async()=>{try{await api("/demo/logout",{});}finally{stopRequest();stopPhotoRequests();current=null;history=[];catalog=[];contextAttempts.clear();$("grid").replaceChildren();$("source-photo").removeAttribute("src");$("result-content").replaceChildren();$("context-content").replaceChildren();show("login");}};
loadCatalog();
