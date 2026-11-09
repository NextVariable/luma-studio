/* The storyboard is the sole shot workspace renderer. */
let workQuery='',shotControlsVisible=true;
function projectLibrary(){
 const projects=state.projects.filter(x=>x.title.toLowerCase().includes(workQuery.toLowerCase()));
 function entry(project){
  const visual=project.shots.find(s=>s.video||s.image),script=project.episodes.find(e=>e.script)?.script||'';
  return `<button class="work-entry" aria-label="打开作品：${esc(project.title)}" data-open-project="${esc(project.id)}"><span class="work-entry-preview">${visual?visual.video?`<video muted preload="metadata" src="/media/${esc(visual.video)}#t=0.1"></video>`:`<img alt="${esc(project.title)}已选画面" src="/media/${esc(visual.image)}">`:`<span class="work-script-preview">${esc(script?script.slice(0,140):'写下第一段故事，开始制作。')}</span>`}<span class="work-resume">继续创作 ${uiIcon('arrow-up-right')}</span></span><span class="work-entry-copy"><strong>${esc(project.title)}</strong><small>${project.episodes.length} 集 / ${project.shots.length} 镜</small></span></button>`;
 }
 $('#content').innerHTML=`<section class="work-library"><header class="work-library-heading"><div><h1>我的作品</h1></div><div class="actions"><button id="library-import">导入短剧项目</button><button class="primary" id="library-new">${uiIcon('plus')}新建作品</button></div></header><div class="collection-toolbar"><label class="collection-search">搜索作品<input id="work-search" type="search" placeholder="查找作品" value="${esc(workQuery)}"></label><span id="work-result-count">${projects.length} 部作品</span></div><div class="work-entries">${projects.map(project=>entry(project)).join('')||`<div class="work-empty"><h3>${workQuery?'没有找到作品':'从一个故事开始'}</h3><p>${workQuery?'换个关键词试试。':'新建作品，写下第一集剧本。'}</p></div>`}</div></section>`;
 bind('#library-import',openDramaImport);
 bind('#library-new',()=>$('#newdialog').showModal());
 $('#work-search').oninput=e=>{workQuery=e.target.value;const start=e.target.selectionStart;projectLibrary();$('#work-search').focus();try{$('#work-search').setSelectionRange(start,start)}catch{}};
 document.querySelectorAll('[data-open-project]').forEach(button=>button.onclick=()=>enterProject(button.dataset.openProject));
}
function bindCanvasShell(){
 $('#new').hidden=view==='library';
}
function presentShotTools(dialog){
 // This is one in-flow creation panel at every width, never a second floating inspector.
 dialog.dataset.docked='true';dialog.setAttribute('aria-modal','false');if(!dialog.open){const previous=document.activeElement;dialog.show();const target=previous?.isConnected&&!dialog.contains(previous)&&previous!==document.body?previous:dialog.querySelector('[role=tab][aria-selected=true]');target?.focus({preventScroll:true})}
}
function openShotTools(tab='intent'){
 const dialog=$('#shot-tools');if(!dialog)return;
 setShotControlsVisible(true);
 if(!dialog.open)presentShotTools(dialog);
 $('#tab-'+tab)?.click();$('#tab-'+tab)?.focus();
}
function setShotControlsVisible(visible){
 shotControlsVisible=visible;const dialog=$('#shot-tools'),desk=document.querySelector('.editing-desk'),toggle=$('#toggle-shot-controls');
 if(!dialog||!desk||!toggle)return;
 dialog.hidden=!visible;desk.classList.toggle('controls-hidden',!visible);toggle.setAttribute('aria-expanded',String(visible));toggle.setAttribute('aria-label',visible?'收起镜头编辑':'展开镜头编辑');toggle.title=visible?'收起镜头编辑':'展开镜头编辑';
 if(!visible&&dialog.contains(document.activeElement))toggle.focus({preventScroll:true});
}
function drawShots(){
 if(!['intent','dialogue','takes'].includes(shotToolTab))shotToolTab='intent';
 const activeTool=document.activeElement,toolsFocus=activeTool?.id?'#'+CSS.escape(activeTool.id):activeTool?.dataset.key?'[data-key="'+CSS.escape(activeTool.dataset.key)+'"]':null;
 const expandedTools=new Set([...document.querySelectorAll('#shot-tools details[data-disclosure][open]')].map(d=>d.dataset.disclosure));
 const oldTools=$('#shot-tools');if(oldTools)oldTools.onclose=null;
 const toolsScroll=oldTools?.scrollTop||0,toolsContext=[pid,eid,selected].join(':'),reopenTools=oldTools?.open&&oldTools.dataset.context===toolsContext;
 const items=shots(),visible=items.filter(item=>shotFilter==='missing'?!(item.image||item.video):shotFilter==='review'?(!item.approved||item.needs_review):shotFilter==='ready'?flowStatus().shots.some(r=>r.shot_id===item.id&&r.ready):true);
 if(visible.length&&!visible.some(item=>item.id===selected))selected=visible[0].id;
 const s=visible.some(item=>item.id===selected)?shot():null,number=items.findIndex(item=>item.id===s?.id)+1;
 const status=item=>item.locked?'已锁定':item.needs_review?'待确认':item.approved?'已确认':'草稿';
 const thumbnail=item=>item.image?`<img alt="" src="/media/${esc(item.image)}">`:item.video?`<video muted preload="metadata" src="/media/${esc(item.video)}#t=0.1"></video>`:`<span class="sequence-treatment">${esc(item.description||'待写画面描述')}</span>`;
 const media=s?.video?`<video controls preload="metadata" src="/media/${esc(s.video)}#t=${s.trim_start||0}"></video>`:s?.image?`<img alt="镜头 ${number} 已选画面" src="/media/${esc(s.image)}">`:'';
 $('#content').innerHTML=`<section class="studio-canvas"><div class="editing-desk ${s?'':'is-empty'}">
 <section class="canvas-main result-workspace" aria-label="镜头画面与分镜"><header class="result-heading"><span>镜头 <strong>${number?String(number).padStart(2,'0'):'—'}</strong><span class="result-state">${s?status(s):items.length?'筛选无结果':'尚无镜头'}</span></span><div class="result-episode-slot"></div><div class="actions">${s?`<button id="toggle-shot-controls" class="icon-button" aria-label="收起镜头编辑" aria-controls="shot-tools" aria-expanded="true">${uiIcon('adjustments-horizontal')}</button>`:''}<button id="toggle-board" class="icon-button" aria-label="${canvasBoardView?'显示单镜画面':'显示分镜板'}" aria-pressed="${canvasBoardView}">${uiIcon('layout-grid')}</button><button id="expand-current-frame" class="icon-button" aria-label="放大当前画面" ${media?'':'disabled'}>${uiIcon('maximize')}</button></div></header><div id="canvas-activity" aria-live="polite"></div>
 ${s?`<div class="result-stage-wrap" ${canvasBoardView?'hidden':''}><div class="viewer-surface"><div class="shot-stage ${media?'has-media':'is-storyboard'}">${media||`<div class="viewer-empty"><span class="frame-slug"><span class="frame-framing">${esc(s.framing||'分镜')}</span><span class="frame-duration">${s.duration} 秒</span></span><p class="frame-treatment">${esc(s.description||'描述这一镜，让故事有画面。')}</p><div class="frame-empty-footer"><span>待添加画面</span><div class="actions"><button id="import-current-frame" class="primary">${uiIcon('upload')}导入画面</button><button id="choose-current-frame" class="text-button">${uiIcon('folder')}素材库</button></div></div></div>`}</div></div><p class="viewer-description">${esc(s.description||'这一镜还没有画面描述。')}</p></div>
 <div class="storyboard-gallery" ${canvasBoardView?'':'hidden'}>${visible.map(item=>`<button class="board-tile ${item.id===s.id?'is-current':''}" data-canvas-select="${esc(item.id)}" aria-label="打开镜头 ${items.indexOf(item)+1}"><span class="board-image">${thumbnail(item)}</span><span><strong>镜头 ${String(items.indexOf(item)+1).padStart(2,'0')}</strong><small>${esc(item.framing)} · ${item.duration} 秒</small></span><p>${esc(item.description)}</p></button>`).join('')}</div>`:`<div class="canvas-empty"><h3>${items.length?'没有符合条件的镜头':'从第一镜开始'}</h3><p>${items.length?'更换筛选，查看其他镜头。':'拆分剧本，或添加一个镜头。'}</p>${items.length?'<button id="clear-filter">显示全部镜头</button>':'<button id="first-shot">添加第一镜</button>'}</div>`}
 </section>${shotToolsMarkup(s)}<section class="shot-sequence" aria-label="本集镜头"><div class="sequence-heading"><strong>分镜 <span>${items.length}</span></strong><div class="actions"><select id="sequence-filter" aria-label="筛选镜头">${[['all','全部镜头'],['missing','缺少画面'],['review','待确认'],['ready','可导出']].map(([v,n])=>`<option value="${v}" ${shotFilter===v?'selected':''}>${n}</option>`).join('')}</select><button id="addshot" class="icon-button" aria-label="添加镜头">${uiIcon('plus')}</button></div></div><div class="sequence-strip">${visible.map(item=>`<button class="sequence-shot ${item.id===s?.id?'is-current':''}" data-canvas-select="${esc(item.id)}" aria-label="选择镜头 ${items.indexOf(item)+1}" aria-pressed="${item.id===s?.id}"><span class="sequence-thumbnail">${thumbnail(item)}<span class="shot-index">${String(items.indexOf(item)+1).padStart(2,'0')}</span></span><span class="sequence-copy"><strong>${esc(item.framing||'镜头')}</strong><small>${item.duration} 秒</small></span></button>`).join('')||`<p class="muted">${items.length?'没有符合筛选的镜头。':'还没有镜头。'}</p>`}</div></section></div>
 <input id="current-frame-file" type="file" accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime" hidden>${s?`<dialog id="frame-preview" aria-label="放大镜头画面"><header><strong>镜头 ${String(number).padStart(2,'0')}</strong><button id="close-frame-preview" class="icon-button" aria-label="关闭画面预览">${uiIcon('x')}</button></header>${media}</dialog>`:''}</section>`;
 const episodeContext=$('#episodebar');if(episodeContext)document.querySelector('.result-episode-slot').append(episodeContext);
 const dialog=$('#shot-tools');
 if(dialog){
  bindShotEditor(s);dialog.querySelectorAll('details[data-disclosure]').forEach(d=>d.open=expandedTools.has(d.dataset.disclosure));presentShotTools(dialog);bindCreationControls();setShotControlsVisible(shotControlsVisible);bind('#toggle-shot-controls',()=>setShotControlsVisible(!shotControlsVisible));
  if(reopenTools)requestAnimationFrame(()=>{if(!dialog.isConnected||!dialog.open)return;const focus=toolsFocus&&dialog.querySelector(toolsFocus);if(focus&&!focus.disabled)focus.focus({preventScroll:true});dialog.scrollTop=toolsScroll});
 }
 document.querySelectorAll('[data-canvas-select]').forEach(button=>button.onclick=()=>{if(selected===button.dataset.canvasSelect&&!button.classList.contains('board-tile'))return;const sequence=document.querySelector('.sequence-strip'),left=sequence?.scrollLeft||0;selected=button.dataset.canvasSelect;if(button.classList.contains('board-tile'))canvasBoardView=false;render();animateShotChange();document.querySelector('.sequence-strip')?.scrollTo({left});if(matchMedia('(min-width:760px)').matches)document.querySelector('.sequence-shot.is-current')?.focus({preventScroll:true})});
 const rail=document.querySelector('.sequence-strip');
 rail.onkeydown=e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...rail.querySelectorAll('[data-canvas-select]')],at=buttons.indexOf(e.target);if(at<0)return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:Math.max(0,Math.min(buttons.length-1,at+(['ArrowDown','ArrowRight'].includes(e.key)?1:-1)));if(next===at)return;buttons[next]?.click();requestAnimationFrame(()=>document.querySelector('.sequence-shot.is-current')?.focus({preventScroll:true}))};
 requestAnimationFrame(()=>document.querySelector('.sequence-shot.is-current')?.scrollIntoView({block:'nearest',inline:'nearest'}));
 bind('#addshot',addShot);bind('#first-shot',addShot);bind('#clear-filter',()=>{shotFilter='all';render()});$('#sequence-filter').onchange=e=>{shotFilter=e.target.value;render()};
 if(s){
  bindResultControls(s);
  bind('#revise-shot',async()=>{if(!$('#revision-instruction').value.trim())throw Error('请先写下修改要求');await run('revision',{shot_id:s.id,instruction:$('#revision-instruction').value})});
  document.querySelectorAll('[data-generate]').forEach(button=>button.onclick=()=>run(button.dataset.generate,{shot_id:s.id}).catch(e=>toast(e.message)));
  updateCanvasActivity();
  document.querySelectorAll('.shot-stage').forEach(frame=>{
   frame.ondragover=e=>{e.preventDefault();frame.classList.add('is-dragging')};frame.ondragleave=()=>frame.classList.remove('is-dragging');
   frame.ondrop=async e=>{e.preventDefault();frame.classList.remove('is-dragging');const file=e.dataTransfer.files[0];if(!file)return;try{const target=shot(),kind=file.type.startsWith('image/')?'image':file.type.startsWith('video/')?'video':null;if(!kind)throw Error('请拖入图片或视频');await importShotMedia(target,file,kind);openShotTools('takes')}catch(error){toast(error.message)}};
  });
 }
}
function currentCanvasJobs(){return state.jobs.filter(job=>job.project_id===pid&&job.episode_id===eid&&job.target_shot_id===selected&&['revision','image','video','audio'].includes(job.kind)&&!(p().applied||[]).includes(job.id)&&job.state!=='cancelled')}
function updateCanvasActivity(){
 const host=$('#canvas-activity');if(!host)return;
 const job=currentCanvasJobs()[0];if(!job){host.replaceChildren();return}
 const ready=job.state==='succeeded',stale=job.fresh===false,proposal=ready&&job.kind==='revision'&&!stale;
 host.innerHTML=`<div class="canvas-task"><div><span>${esc(kinds[job.kind])}</span><strong>镜头 ${String(shots().findIndex(s=>s.id===job.target_shot_id)+1).padStart(2,'0')} · ${proposal?'修改方案已就绪':ready?(stale?'旧方案，仅供参考':'素材备选已就绪'):esc(statuses[job.state]||job.state)}</strong></div>${proposal?'<button id="canvas-show-proposal">查看修改</button>':ready&&!stale&&job.kind!=='revision'?'<button id="canvas-show-candidates">比较素材</button>':'<button data-flow="jobs">查看记录</button>'}</div>`;
 bind('#canvas-show-proposal',async()=>{try{if(hasUnsavedShot()||hasUnsavedCut())throw Error('请先保存镜头与剪辑修改，再查看方案');const preview=await chooseRevision(job);if(!preview)return;await api('/api/apply',{project_id:pid,job_id:job.id,revision:p().revision,preview_digest:preview.digest});await refresh();toast('修改已应用，请重新确认这一镜')}catch(error){await refresh();toast(error.message)}});
 bind('#canvas-show-candidates',()=>openShotTools('takes'));
 host.querySelectorAll('[data-flow]').forEach(button=>button.onclick=()=>go(button.dataset.flow));
}
let canvasPollBusy=false,canvasInputRevision=0;
document.addEventListener('input',()=>canvasInputRevision++);
function canvasCanRefresh(){
 const video=document.querySelector('.shot-stage>video');
 return view==='shots'&&!document.querySelector('dialog[open]:not([data-docked=true]),.picker-menu:popover-open')&&!document.activeElement?.matches('input,textarea,select')&&!hasUnsavedShot()&&!hasUnsavedCut()&&(!video||video.paused);
}
function deliveryCanRefresh(){
 const video=document.querySelector('.delivery-stage>video');
 return view==='delivery'&&!document.querySelector('dialog[open]:not([data-docked=true]),.picker-menu:popover-open')&&(!video||video.paused);
}
async function pollCanvas(){
 const delivery=view==='delivery';
 if(canvasPollBusy)return;
 if(delivery){if(!deliveryCanRefresh()||!activeTaskStates.includes(currentDeliveryJob()?.state))return}
 else if(!canvasCanRefresh()||!currentCanvasJobs().some(job=>activeTaskStates.includes(job.state)))return;
 const context=[view,pid,eid,selected].join(':'),before=state,inputRevision=canvasInputRevision;
 canvasPollBusy=true;
 try{const next=await api('/api/state');
  if(state===before&&context===[view,pid,eid,selected].join(':')&&inputRevision===canvasInputRevision&&(delivery?deliveryCanRefresh():canvasCanRefresh())){state=next;render()}
 }catch{}finally{canvasPollBusy=false}
}
setInterval(pollCanvas,4000);
