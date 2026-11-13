/* 入口：左侧导航、顶栏、视图切换、轮询 */
(function(){
const {esc,$,$$}=L;
const ICONS={
  library:'<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  script:'<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1-1.5z"/><path d="M9.5 11h6M9.5 14.5h6M9.5 18h3.5"/>',
  cast:'<circle cx="12" cy="8.5" r="3.6"/><path d="M4.5 20.5c.9-3.8 3.9-6 7.5-6s6.6 2.2 7.5 6"/>',
  shots:'<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M7 5.5v13M17 5.5v13M3 9.5h4M3 14.5h4M17 9.5h4M17 14.5h4"/>',
  delivery:'<circle cx="12" cy="12" r="8.5"/><path d="M10.2 8.8l5 3.2-5 3.2z"/>',
  jobs:'<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="8.5"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6"/>'
};
const svg=k=>`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[k]}</svg>`;
const PAGES=[['library','作品'],['script','剧本'],['cast','角色'],['shots','镜头'],['delivery','成片']];

const ORDER=PAGES.map(([key])=>key);
const scrollPositions=new Map();
let renderedPage;
let leaving=false;
L.goTo=async (index,{scope='page',sound=true,touch=false,shotId,tab}={})=>{
  if(L.pagingBlocked()||leaving||!Number.isInteger(index))return false;
  const shots=scope==='shot'?L.shots():null;
  const current=shots?shots.findIndex(shot=>shot.id===L.S.sid):ORDER.indexOf(L.S.view);
  const target=shots?shots[index]?.id:ORDER[index];
  if(!target||index===current||(!shots&&target!=='library'&&!L.project()))return false;
  if(L.S.dirty){
    leaving=true;
    try{if(!await L.leaveOk())return false}
    finally{leaving=false}
  }
  const direction=Math.sign(index-current);
  L.S.dirty=false;
  if(sound)L.sfx('swipe',direction,{touch});
  const axis=L.mobilePaging()?'x':'y';
  if(shots){L.showShot(target,direction,axis);return true}
  const view=$('#view');
  if(shotId){L.S.sid=shotId;L.ui.tab=tab||null}
  L.swap(view,direction,()=>{
    L.S.view=target;
    L.remember();
    L.render();
  },{axis});
  view.focus({preventScroll:true});
  return true;
};
L.go=(view,options)=>{
  if(view===L.S.view&&!L.S.dirty&&!L.pagingBlocked()){L.render();return}
  return L.goTo(ORDER.indexOf(view),options);
};
L.openProject=(pid,view)=>{
  L.S.pid=pid;L.S.eid=null;L.S.sid=null;L.normalize();
  const p=L.project();
  L.S.view=view||localStorage.getItem('luma:workspace:'+pid)||(p.shots.length?'shots':'script');
  L.remember();L.render();$('#view').focus({preventScroll:true});
};

L.renderTop=()=>{
  const p=L.project(),inProject=!!p&&L.S.view!=='library',ep=L.episode();
  const mine=p?L.S.data.jobs.filter(j=>j.project_id===p.id):[];
  const attention=mine.filter(j=>L.jobBucket(j)!=='done').length;
  $('#rail').innerHTML=`<button class="rail-mark" id="brand" aria-label="流幕 · 所有作品"><img src="assets/luma-mark.png?v=clapper-cutout" alt="" width="34" height="34"></button>
    ${PAGES.map(([k,v])=>{const off=k!=='library'&&!p;return `<button class="rail-item" data-view="${k}" aria-label="${v}" ${L.S.view===k?'aria-current="page"':''} ${off?'disabled':''}>${svg(k)}<span>${v}</span></button>`}).join('')}
    <span class="rail-gap"></span>
    <button class="rail-item" id="jobs-btn" aria-label="生成记录" title="生成记录" aria-expanded="${L.S.drawer}" ${p?'':'disabled'}>${svg('jobs')}<span>记录</span>${attention?`<b class="rail-badge num">${attention}</b>`:''}</button>
    <button class="rail-item" id="settings-btn" aria-label="设置">${svg('settings')}<span>设置</span></button>`;
  const sp=L.S.data.spending;
  $('#context').innerHTML=inProject?`<button class="switch" id="sw-project" aria-haspopup="menu"><b>${esc(p.title)}</b>${L.chev}</button>
    <span class="faint">/</span><button class="switch" id="sw-episode" aria-haspopup="menu"><b>${esc(ep.title)}</b>${L.chev}</button>`:'';
  $('#top-actions').innerHTML=inProject?`<button class="btn ghost small" id="quota">${sp.remaining?'<span class="num">生成额度 '+sp.remaining+'</span>':'生成已暂停'}</button>
    ${L.S.view==='delivery'?'':'<button class="btn small" id="to-delivery">去成片</button>'}`:'';
  $$('[data-view]',$('#rail')).forEach(b=>b.onclick=()=>L.go(b.dataset.view));
  $('#brand').onclick=()=>L.go('library');
  $('#settings-btn').onclick=L.settingsDialog;
  $('#quota')?.addEventListener('click',L.settingsDialog);
  $('#to-delivery')?.addEventListener('click',()=>L.go('delivery'));
  $('#jobs-btn').onclick=()=>L.S.drawer?L.closeDrawer():L.openDrawer();
  $('#sw-project')?.addEventListener('click',e=>L.menu(e.currentTarget,[
    {label:'重命名作品',run:async()=>{const t=await L.prompt('重命名作品','作品名称',p.title);if(t)L.busy(null,async()=>{await L.save(x=>{x.title=t});L.render()})}},
    {label:'历史版本',run:L.historyDialog},'-',
    ...L.S.data.projects.filter(x=>x.id!==p.id).slice(0,8).map(x=>({label:x.title,run:async()=>{if(await L.leaveOk())L.openProject(x.id)}})),
    {label:'所有作品',run:()=>L.go('library')}]));
  $('#sw-episode')?.addEventListener('click',e=>L.menu(e.currentTarget,[
    ...p.episodes.map(x=>({label:x.title,current:x.id===ep.id,hint:p.shots.filter(s=>s.episode_id===x.id).length+' 镜',run:async()=>{if(x.id!==ep.id&&await L.leaveOk()){L.S.eid=x.id;L.S.sid=null;L.normalize();L.remember();L.render()}}})),
    '-',{label:'管理剧集',run:()=>L.go('script')}]));
};

L.render=()=>{
  if(!L.S.data)return;
  L.normalize();
  if(!L.project()&&L.S.view!=='library')L.S.view='library';
  if(L.project()&&L.S.view!=='library')localStorage.setItem('luma:workspace:'+L.S.pid,L.S.view);
  const view=$('#view');
  if(renderedPage)scrollPositions.set(renderedPage,{
    top:view.scrollTop,
    lists:new Map($$('[data-scroll]',view).map(el=>[el.dataset.scroll,el.scrollTop])),
  });
  renderedPage=JSON.stringify(L.S.view==='library'?['library']:[L.S.pid,L.S.eid,L.S.view]);
  const saved=scrollPositions.get(renderedPage);
  document.body.dataset.view=L.S.view;
  L.renderTop();
  if(L.S.view==='library')L.setAmbient(null);
  try{(L.views[L.S.view]||L.views.library)(view)}catch(e){console.error(e);view.innerHTML=`<div class="library"><div class="notice stop"><p>${esc(e.message)}</p></div></div>`}
  view.scrollTop=saved?.top||0;
  for(const list of $$('[data-scroll]',view))list.scrollTop=saved?.lists.get(list.dataset.scroll)||0;
  L.renderDrawer();
};

/* Same input handler for the workspace and its shot canvas. */
const viewEl=$('#view');
const wheel=L.wheelGesture();
const scrollControls='input,select,[contenteditable],#pop,video[controls]';
const inspectorOpen=()=>!!viewEl.querySelector?.('#pop');
const gestureBlocked=()=>L.pagingBlocked()||inspectorOpen();
const gestureArea=(target,mobile)=>{
  const shotArea=L.S.view==='shots'&&(target.closest('#stage')||(!mobile&&target.closest('.strip')));
  return shotArea?{scope:'shot',boundary:shotArea}:{scope:'page',boundary:viewEl};
};
const step=(scope,direction,touch=false)=>{
  const index=scope==='shot'?L.shots().findIndex(shot=>shot.id===L.S.sid):ORDER.indexOf(L.S.view);
  return L.goTo(index+direction,{scope,touch});
};
const pageWheel=event=>{
  if(event.defaultPrevented||event.ctrlKey)return;
  const mobile=L.mobilePaging();
  const along=mobile?event.deltaX:event.deltaY,across=mobile?event.deltaY:event.deltaX;
  if(Math.abs(along)<=Math.abs(across))return;
  const delta=L.wheelPixels(event,mobile?'x':'y');
  if(mobile&&event.currentTarget!==viewEl)return;
  const {scope,boundary}=gestureArea(event.target,mobile);
  const control=event.target.closest(scrollControls+(mobile?',.strip':',textarea:focus'));
  const scrolling=gestureBlocked()||!!control||(!mobile&&L.canScrollWithin(event.target,delta,boundary));
  const direction=wheel(delta,performance.now(),{scrolling,discrete:event.deltaMode!==0,pointer:{x:event.clientX,y:event.clientY}});
  if(scrolling)return;
  event.preventDefault();
  if(direction)step(scope,direction);
};
for(const surface of new Set([viewEl,$('.topbar'),$('#rail')].filter(Boolean))){
  surface.addEventListener('wheel',pageWheel,{passive:false});
}
let touch=null;
viewEl.addEventListener('touchstart',event=>{
  touch=null;
  if(event.touches.length!==1||gestureBlocked()||event.target.closest(scrollControls+',.strip,textarea:focus'))return;
  const mobile=L.mobilePaging();
  const {scope,boundary}=gestureArea(event.target,mobile);
  const axis=mobile?'x':'y';
  touch={point:event.touches[0],scope,axis,
    up:axis==='y'&&L.canScrollWithin(event.target,-1,boundary),
    down:axis==='y'&&L.canScrollWithin(event.target,1,boundary),consumed:false};
},{passive:true});
viewEl.addEventListener('touchmove',event=>{
  if(event.touches.length!==1||gestureBlocked()){touch=null;return}
  if(!touch)return;
  if(touch.consumed){if(event.cancelable)event.preventDefault();return}
  const point=event.touches[0];
  const {axis}=touch;
  const intent=L.swipeDirection(touch.point,point,5,axis);
  if(!intent){
    if(L.swipeDirection(touch.point,point,5,axis==='x'?'y':'x'))touch=null;
    return;
  }
  if(intent>0?touch.down:touch.up){touch=null;return}
  if(event.cancelable)event.preventDefault();
  const direction=L.swipeDirection(touch.point,point,12,axis);
  if(direction){touch.consumed=true;step(touch.scope,direction,true)}
},{passive:false});
for(const type of ['touchcancel','touchend'])viewEl.addEventListener(type,()=>{touch=null},{passive:true});
document.addEventListener('keydown',event=>{
  const mobile=L.mobilePaging(),previous=mobile?'ArrowLeft':'ArrowUp',next=mobile?'ArrowRight':'ArrowDown';
  if((event.key!==previous&&event.key!==next)||event.metaKey||event.ctrlKey||event.repeat||gestureBlocked())return;
  if(event.target.closest(scrollControls+',textarea,.strip,dialog,.drawer,.menu'))return;
  const direction=event.key===next?1:-1;
  if(!mobile&&!event.altKey&&L.S.view!=='shots'&&L.canScrollWithin(event.target,direction,viewEl))return;
  event.preventDefault();
  step(!event.altKey&&L.S.view==='shots'?'shot':'page',direction);
});

/* 轮询：有进行中的任务时才刷新，且不打断正在输入、播放或弹窗中的操作 */
let sig='';
const signature=d=>JSON.stringify([d.jobs.map(j=>[j.id,j.state,j.updated]),d.projects.map(p=>[p.id,p.revision]),d.spending]);
const busyUser=()=>!!$('dialog[open]')||inspectorOpen()||$('.menu')||L.S.dirty||document.activeElement?.matches?.('input,textarea,select')||$$('video,audio').some(m=>!m.paused);
let tick=0,pendingRender=false,polling=false;
setInterval(async()=>{
  if(!L.S.data||document.hidden||polling)return;
  tick++;
  const active=L.S.data.jobs.some(j=>L.jobActive(j.state));
  if(!active&&!(pendingRender&&!busyUser())&&!(L.S.drawer&&tick%5===0))return;
  const previous=L.S.data;
  polling=true;
  try{
    const d=await L.api('/api/state'),next=signature(d);
    if(L.S.data!==previous){pendingRender=true;return}
    if(next===sig&&!pendingRender)return;
    const before=new Map(L.S.data.jobs.map(j=>[j.id,j.state]));
    const finished=d.jobs.filter(j=>L.jobActive(before.get(j.id))&&!L.jobActive(j.state));
    finished.forEach(j=>j.state==='succeeded'?L.done(L.jobName(j.kind)+'已完成'):j.state==='waiting_review'?L.done(L.jobName(j.kind)+'等你审批'):L.toast(L.jobName(j.kind)+(j.state==='failed'?'失败：':'：')+(j.error||L.jobState(j.state)),true));
    if(busyUser()){pendingRender=true;L.S.data.jobs=d.jobs;L.renderTop();L.renderDrawer();return}
    pendingRender=false;L.S.data=d;sig=next;L.render();
  }catch(e){/* 服务重启时静默等待 */}
  finally{polling=false}
},2000);

(async()=>{
  try{await L.refresh();sig=signature(L.S.data);L.render()}
  catch(e){$('#view').innerHTML=`<div class="library"><div class="empty-state"><h2>连不上流幕服务</h2><p>${esc(e.message)}</p><p class="faint">在项目目录运行 python3 studio.py 后刷新页面。</p></div></div>`}
})();
})();
