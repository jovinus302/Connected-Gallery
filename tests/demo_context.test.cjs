// Exercise navigation and actual request ordering without a browser or models.
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');

const app = readFileSync(resolve(__dirname, '../web/demo/app.js'), 'utf8');
const functions = app.slice(0, app.indexOf('$("source-photo").addEventListener("load",fitRegions)'));
const region = {id:'subject', label:'관심 대상', kind:'object', box:{x:0,y:0,width:.4,height:.4}};
const analysis = {description:'사진에서 확인한 내용', regions:[region]};
const ready = (id, groups=[{id:'relation',title:'관찰된 관계',reason:'사진에 함께 보이는 근거',photo_ids:['related-a','related-b','related-c','related-d']}]) => ({photo_id:id,state:'ready',revision:9,context:{summary:`${id}의 주변 사진`,groups}});
const connection = {label:region.label,complete:true,grouping_status:'ready',items:[{photo_id:'next',reason:'같은 표기'}],groups:[{id:'product',title:'같은 표기',reason:'라벨의 글자',photo_ids:['next']}]};
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
class Element {
  constructor(tag='div') {this.tagName=tag;this.children=[];this.style={};this.dataset={};this.attributes={};this.events=new Map();this._text='';this.classes=new Set();this.classList={add:(name)=>this.classes.add(name),remove:(name)=>this.classes.delete(name),contains:(name)=>this.classes.has(name),toggle:(name,on)=>{if(on===undefined)on=!this.classes.has(name);if(on)this.classes.add(name);else this.classes.delete(name);}};this.complete=true;this.naturalWidth=1536;this.naturalHeight=1024;this.clientWidth=600;this.clientHeight=400;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this._text='';this.children=[...children];}
  setAttribute(name,value){this.attributes[name]=String(value);}
  removeAttribute(name){delete this.attributes[name];if(name==='src')delete this.src;}
  addEventListener(name,fn){if(!this.events.has(name))this.events.set(name,new Set());this.events.get(name).add(fn);}
  removeEventListener(name,fn){this.events.get(name)?.delete(fn);}
  emit(name){[...(this.events.get(name)||[])].forEach(fn=>fn());}
}
function harness(route,{live=false}={}) {
  const elements=new Map(),requests=[],scrolls=[];
  const element=id=>{if(!elements.has(id)){elements.set(id,new Element());elements.get(id).value='';}return elements.get(id);};
  let now=0;
  const window={scrollY:0,scrollTo:({top})=>{window.scrollY=top;scrolls.push(top);},requestAnimationFrame:fn=>queueMicrotask(fn)};
  const sandbox={document:{getElementById:element,createElement:tag=>new Element(tag),createTextNode:text=>{const el=new Element('#text');el.textContent=text;return el;},querySelectorAll:()=>[]},window,AbortController,DOMException,crypto:{randomUUID:()=> 'test-key'},setTimeout:fn=>{queueMicrotask(fn);return 1;},clearTimeout:()=>{},Date:{now:()=>now+=1200},fetch:async(path,options)=>{requests.push({path,method:options.method||'GET',signal:options.signal});const data=await route(path,options),status=data?.httpStatus||200;return {ok:status>=200&&status<300,status,json:async()=>data};}};
  vm.createContext(sandbox);vm.runInContext(functions,sandbox);vm.runInContext(`liveEnabled=${live};revision=9;`,sandbox);
  return {element,requests,scrolls,window,exec:code=>vm.runInContext(code,sandbox),settle:async()=>{for(let i=0;i<40;i++)await Promise.resolve();}};
}
function defaultRoute(path){if(path.endsWith('/analysis'))return analysis;if(path==='/explorations/ready')return {state:'ready',revision:9,result:connection};throw new Error(`Unexpected request: ${path}`);}

test('opening a photo loads context immediately, independently of analysis and subject selection',async()=>{
  const analysisPending=deferred();
  const h=harness(path=>path.endsWith('/analysis')?analysisPending.promise:path.endsWith('/context')?ready('a'):defaultRoute(path));
  const opened=h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.requests.filter(r=>r.path==='/assets/a/context').length,1);
  assert.match(h.element('context-content').textContent,/a의 주변 사진/);
  assert.equal(h.exec('current.region'),null);
  analysisPending.resolve(analysis);await opened;
});

test('late context responses from a previous photo cannot overwrite the current photo',async()=>{
  const old=deferred();
  const h=harness(path=>path==='/assets/a/context'?old.promise:path==='/assets/b/context'?ready('b'):defaultRoute(path));
  await h.exec('openPhoto("a")');await h.exec('openPhoto("b")');await h.settle();
  assert.equal(h.requests.find(r=>r.path==='/assets/a/context').signal.aborted,true);
  old.resolve(ready('a'));await h.settle();
  assert.match(h.element('context-content').textContent,/b의 주변 사진/);
  assert.doesNotMatch(h.element('context-content').textContent,/a의 주변 사진/);
});

test('selecting a subject keeps the opened photo context request alive',async()=>{
  const context=deferred();
  const h=harness(path=>path.endsWith('/context')?context.promise:defaultRoute(path));
  await h.exec('openPhoto("a")');await h.exec('selectRegion(current.analysis.regions[0])');
  assert.equal(h.requests.find(r=>r.path==='/assets/a/context').signal.aborted,false);
  context.resolve(ready('a'));await h.settle();
  assert.match(h.element('context-content').textContent,/a의 주변 사진/);
  assert.equal(h.element('result-title').textContent,region.label);
  assert.match(h.element('result-content').textContent,/같은 표기/);
});

test('prepared-only pending context never starts work or claims that no relation exists',async()=>{
  const h=harness(path=>path.endsWith('/context')?{photo_id:'a',state:'pending',revision:9,context:null}:defaultRoute(path));
  await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.requests.filter(r=>r.method==='POST').length,0);
  assert.equal(h.element('context-state').textContent,'준비 전');
  assert.match(h.element('context-content').textContent,/아직 준비되지/);
});

test('verified empty and failed context are visibly different states',async()=>{
  const h=harness(path=>path.endsWith('/context')?{photo_id:path.includes('/a/')?'a':'b',state:path.includes('/a/')?'empty':'failed',revision:9,context:null}:defaultRoute(path));
  await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.element('context-state').textContent,'확인 완료');
  assert.match(h.element('context-content').textContent,/관계를 확인하지 못했어요/);
  assert.equal(h.element('context-content').children.some(el=>el.tagName==='button'),false);
  await h.exec('openPhoto("b")');await h.settle();
  assert.equal(h.element('context-state').textContent,'확인 필요');
  assert.equal(h.element('context-content').children.some(el=>el.tagName==='button'),true);
});

test('live mode prepares once and polls until ready without a separate Organize action',async()=>{
  let gets=0;
  const h=harness(path=>{if(path.endsWith('/context/prepare'))return {photo_id:'a',state:'running',revision:9,context:null};if(path.endsWith('/context'))return ++gets===1?{photo_id:'a',state:'pending',revision:9,context:null}:ready('a');return defaultRoute(path);},{live:true});
  await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.requests.filter(r=>r.path.endsWith('/context/prepare')).length,1);
  assert.equal(gets,2);
  assert.match(h.element('context-content').textContent,/a의 주변 사진/);
});

test('failed preparation does not retry endlessly on refresh or reopening at the same revision',async()=>{
  const h=harness(path=>path.endsWith('/context')||path.endsWith('/context/prepare')?{photo_id:'a',state:'failed',revision:9,context:null}:defaultRoute(path),{live:true});
  await h.exec('openPhoto("a")');await h.settle();await h.exec('loadContext("a")');await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.requests.filter(r=>r.path.endsWith('/context/prepare')).length,1);
  assert.equal(h.element('context-state').textContent,'확인 필요');
});

test('an envelope for a different photo is rejected even if the request is current',async()=>{
  const h=harness(path=>path.endsWith('/context')?ready('wrong-photo'):defaultRoute(path));
  await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.exec('current.context.photo_id'),'a');
  assert.equal(h.exec('current.context.state'),'failed');
  assert.doesNotMatch(h.element('context-content').textContent,/wrong-photo/);
});

test('Back restores the photo, selected connection, context, expanded group and scroll',async()=>{
  const h=harness(path=>path.endsWith('/context')?ready(path.split('/')[2]):defaultRoute(path));
  await h.exec('openPhoto("a")');await h.settle();await h.exec('selectRegion(current.analysis.regions[0])');
  h.exec('current.expanded.add("relation");renderContext(current.context)');h.window.scrollY=735;
  await h.exec('openPhoto("b")');await h.settle();
  await h.exec('openPhoto(history[history.length-1].id,history.pop())');
  assert.equal(h.exec('current.id'),'a');assert.equal(h.exec('current.region.id'),'subject');
  assert.equal(h.exec('current.expanded.has("relation")'),true);
  assert.match(h.element('context-content').textContent,/a의 주변 사진/);
  assert.match(h.element('result-content').textContent,/같은 표기/);
  assert.equal(h.window.scrollY,735);
  assert.equal(h.requests.filter(r=>r.path==='/assets/a/context').length,2);
});

for(const state of ['pending','running'])test(`Back restores scroll before ${state} context preparation finishes and late work stays cancelled`,async()=>{
  const unfinished=deferred();let gets=0;
  const h=harness(path=>{
    if(path==='/assets/a/context/prepare')return unfinished.promise;
    if(path==='/assets/a/context'){
      gets++;if(gets===1)return ready('a');
      if(gets===2)return {photo_id:'a',state,revision:9,context:null};
      return unfinished.promise;
    }
    if(path.endsWith('/context'))return ready(path.split('/')[2]);
    return defaultRoute(path);
  },{live:true});
  await h.exec('openPhoto("a")');await h.settle();h.window.scrollY=620;
  await h.exec('openPhoto("b")');await h.settle();
  let restored=false;
  const back=h.exec('openPhoto(history[history.length-1].id,history.pop())').then(()=>{restored=true;});
  await h.settle();
  assert.equal(restored,true,'Back must not await model preparation');assert.equal(h.window.scrollY,620);
  assert.equal(h.exec('current.context.state'),state);
  await h.exec('openPhoto("c")');await h.settle();
  const pending=h.requests.findLast(r=>r.path.includes('/assets/a/context'));
  assert.equal(pending.signal.aborted,true);
  unfinished.resolve(ready('a'));await back;await h.settle();
  assert.equal(h.exec('current.id'),'c');assert.equal(h.window.scrollY,0);
  assert.match(h.element('context-content').textContent,/c의 주변 사진/);
});

for(const observed of [false,true])test(`Back refetches analysis and clears old selection/results after a ${observed?'known':'newly discovered'} revision change`,async()=>{
  let changed=false,analysisGets=0;
  const replacement={description:'갱신된 사진 분석',regions:[{...region,id:'new-subject',label:'새 대상'}]};
  const h=harness(path=>{
    if(path.endsWith('/context'))return {...ready(path.split('/')[2]),revision:changed?10:9};
    if(path==='/assets/a/analysis')return ++analysisGets===1?analysis:replacement;
    return defaultRoute(path);
  });
  await h.exec('openPhoto("a")');await h.settle();await h.exec('selectRegion(current.analysis.regions[0])');
  h.exec('current.expanded.add("relation")');h.window.scrollY=470;
  await h.exec('openPhoto("b")');await h.settle();changed=true;
  if(observed)h.exec('revision=10');
  await h.exec('openPhoto(history[history.length-1].id,history.pop())');
  assert.equal(analysisGets,2);assert.equal(h.exec('current.revision'),10);
  assert.equal(h.exec('current.analysis.description'),replacement.description);
  assert.equal(h.exec('current.region'),null);assert.equal(h.exec('current.result'),null);
  assert.equal(h.exec('current.expanded.size'),0);
  assert.doesNotMatch(h.element('result-content').textContent,/같은 표기/);
  assert.equal(h.requests.filter(r=>r.path==='/explorations/ready').length,1);
  assert.equal(h.window.scrollY,470);
});

test('Back to a deleted photo returns to the refreshed library instead of reusing its saved detail',async()=>{
  let deleted=false;
  const h=harness(path=>{
    if(path.startsWith('/demo/catalog?'))return {assets:[],total:0,revision:10,live_enabled:false};
    if(path==='/assets/a/context'&&deleted)return {httpStatus:404};
    if(path.endsWith('/context'))return ready(path.split('/')[2]);
    return defaultRoute(path);
  });
  h.window.scrollY=120;await h.exec('openPhoto("a")');await h.settle();await h.exec('selectRegion(current.analysis.regions[0])');
  await h.exec('openPhoto("b")');await h.settle();deleted=true;
  await h.exec('openPhoto(history[history.length-1].id,history.pop())');await h.settle();
  assert.equal(h.exec('current'),null);assert.equal(h.exec('history.some(entry=>entry.id==="a")'),false);
  assert.equal(h.element('library').classList.contains('hidden'),false);
  assert.equal(h.element('detail').classList.contains('hidden'),true);
  assert.equal(h.element('source-photo').src,undefined);
  assert.equal(h.element('result-content').children.length,0);
  assert.equal(h.exec('revision'),10);assert.equal(h.window.scrollY,120);
  assert.equal(h.requests.filter(r=>r.path.startsWith('/demo/catalog?')).length,1);
});

test('an analysis 404 also clears the deleted photo and aborts its independent context request',async()=>{
  const context=deferred();
  const h=harness(path=>{
    if(path.startsWith('/demo/catalog?'))return {assets:[],total:0,revision:10,live_enabled:false};
    if(path.endsWith('/context'))return context.promise;
    if(path.endsWith('/analysis'))return {httpStatus:404};
    return defaultRoute(path);
  });
  await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.exec('current'),null);
  assert.equal(h.requests.find(r=>r.path==='/assets/a/context').signal.aborted,true);
  context.resolve(ready('a'));await h.settle();
  assert.equal(h.element('library').classList.contains('hidden'),false);
  assert.equal(h.element('context-content').children.length,0);
});

test('restoration waits for the image size and never scrolls a later photo',async()=>{
  const h=harness(path=>path.endsWith('/context')?ready(path.split('/')[2]):defaultRoute(path));
  await h.exec('openPhoto("a")');await h.settle();h.window.scrollY=510;await h.exec('openPhoto("b")');await h.settle();
  h.element('source-photo').complete=false;
  const back=h.exec('openPhoto(history[history.length-1].id,history.pop())');await h.settle();
  assert.equal(h.window.scrollY,0);
  await h.exec('openPhoto("c")');h.element('source-photo').emit('load');await back;
  assert.equal(h.exec('current.id'),'c');assert.equal(h.window.scrollY,0);
});

test('capture metadata identifies synthetic dates instead of claiming an actual capture date',async()=>{
  const h=harness(path=>path.endsWith('/context')?{...ready('a'),capture:{date:'2026-09-03',source:'demo_fixture'}}:defaultRoute(path));
  await h.exec('openPhoto("a")');await h.settle();
  assert.equal(h.element('capture-info').textContent,'데모 설정 날짜 · 2026.09.03');
  h.exec('renderContext({...current.context,capture:null})');assert.equal(h.element('capture-info').classList.contains('hidden'),true);
});
