/* Shared navigation: native data controls, accessible popovers and deliberate edge gestures. */
const workspaceOrder=['overview','shots','assets','delivery'];
const workspaceTransitionMs=300;
const workspaceNames={overview:'剧本',shots:'镜头',assets:'素材',delivery:'成片'};
const workspaceScroll=new Map(),selectPickers=new WeakMap(),enhancedForms=new WeakSet();
const workspacePaneScroll=new Map();
const workspaceDisclosureState=new Map(),workspaceDisclosures=['.story-outline','.delivery-assembly','.delivery-versions','.delivery-audio-note'];
const workspaceScrollAreas=['#content','.script-sheet','.sequence-strip','.editor-panels','.result-workspace'];
function rememberWorkspaceScroll(){const key=pid+':'+eid+':'+view;workspaceScroll.set(key,window.scrollY);workspacePaneScroll.set(key,workspaceScrollAreas.map(selector=>[selector,document.querySelector(selector)?.scrollTop||0]));workspaceDisclosureState.set(key,workspaceDisclosures.map(selector=>[selector,!!document.querySelector(selector)?.open]))}
let previousWorkspace=null,gestureState={direction:0,total:0,last:0,cooldown:0},touchOrigin=null,workspaceMotionUntil=0;
function closePickers(){document.querySelectorAll('.picker-menu:popover-open').forEach(menu=>menu.hidePopover())}
function pickerLabel(source){return source.getAttribute('aria-label')||[...(source.labels?.[0]?.childNodes||[])].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('')||'选择选项'}
function pickerIdentity(source){
 return source.id||(source.dataset.lineAudio?'line-audio-'+source.dataset.lineAudio:source.dataset.lineSpeaker!==undefined?'line-speaker-'+source.closest('[data-line-id]').dataset.lineId:source.dataset.boundAsset?'asset-binding-'+source.dataset.boundAsset:source.dataset.version?'asset-version-'+source.dataset.version:source.name?'field-'+(source.closest('form')?.id||'workspace')+'-'+source.name:'select-'+crypto.randomUUID());
}
function createSelectPicker(source){
 const wrapper=document.createElement('span');wrapper.className='select-picker'+(source.id==='projects'?' project-picker':'');
 const trigger=document.createElement('button');trigger.type='button';trigger.className='picker-trigger';trigger.id=pickerIdentity(source)+'-trigger';
 trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
 const menu=document.createElement('div');menu.className='picker-menu';menu.popover='auto';menu.id=trigger.id+'-menu';
 const list=document.createElement('div');list.role='listbox';list.id=menu.id+'-options';list.setAttribute('aria-label',pickerLabel(source));
 trigger.setAttribute('aria-controls',list.id);trigger.setAttribute('popovertarget',menu.id);menu.append(list);wrapper.append(trigger,menu);source.after(wrapper);source.hidden=true;
 let search='',searchAt=0;
 function choices(){return [...list.querySelectorAll('[role=option]:not(:disabled)')]}
 function position(){const b=trigger.getBoundingClientRect(),width=Math.min(Math.max(b.width,source.id==='projects'?300:220),innerWidth-24),height=Math.min(menu.scrollHeight,360),below=innerHeight-b.bottom-16;menu.style.width=width+'px';menu.style.left=Math.max(12,Math.min(b.left,innerWidth-width-12))+'px';menu.style.top=(below>=Math.min(height,180)?b.bottom+8:Math.max(12,b.top-height-8))+'px';menu.style.maxHeight=Math.max(120,below>=Math.min(height,180)?below:b.top-20)+'px'}
 function open(last=false){closePickers();sync();menu.showPopover();position();const options=choices(),chosen=options.find(b=>b.getAttribute('aria-selected')==='true');(last?options.at(-1):chosen||options[0])?.focus({preventScroll:true})}
 function sync(){
  const selected=source.selectedOptions[0];trigger.disabled=source.disabled;trigger.setAttribute('aria-label',pickerLabel(source));trigger.innerHTML='<span>'+esc(selected?.textContent||'选择作品')+'</span><svg aria-hidden="true" viewBox="0 0 16 16"><path d="m4 6 4 4 4-4"/></svg>';
  list.replaceChildren();[...source.options].forEach((option,index)=>{
   const item=document.createElement('button');item.type='button';item.role='option';item.tabIndex=-1;item.disabled=option.disabled;item.setAttribute('aria-selected',String(option.selected));item.dataset.optionIndex=index;
   const project=source.id==='projects'?state.projects.find(p=>p.id===option.value):null;
   item.innerHTML='<span class="picker-option-copy"><strong>'+esc(option.textContent)+'</strong>'+(project?'<small>'+project.episodes.length+' 集 · '+project.shots.length+' 镜</small>':'')+'</span><span class="picker-check" aria-hidden="true">'+(option.selected?'✓':'')+'</span>';
   item.onclick=e=>{e.preventDefault();const changed=source.selectedIndex!==index;source.selectedIndex=index;menu.hidePopover();trigger.focus({preventScroll:true});sync();if(changed){source.dispatchEvent(new Event('input',{bubbles:true}));source.dispatchEvent(new Event('change',{bubbles:true}))}};list.append(item);
  });
  menu.querySelector('.picker-footer')?.remove();if(source.id==='projects'){
   const footer=document.createElement('div');footer.className='picker-footer';
   for(const [name,action] of [['重命名作品',()=>openProjectName()],['所有作品',()=>go('library')],['新建作品',()=>$('#newdialog').showModal()]]){const button=document.createElement('button');button.type='button';button.textContent=name;button.onclick=e=>{e.preventDefault();menu.hidePopover();action()};footer.append(button)}menu.append(footer);
  }
 }
 let pointerOpen=null;
 trigger.onpointerdown=()=>{pointerOpen=menu.matches(':popover-open')};
 trigger.onclick=e=>{e.preventDefault();const wasOpen=pointerOpen??menu.matches(':popover-open');pointerOpen=null;if(wasOpen){if(menu.matches(':popover-open'))menu.hidePopover()}else open()};
 trigger.onpointercancel=()=>{pointerOpen=null};
 trigger.onkeydown=e=>{pointerOpen=null;if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open(e.key==='ArrowUp')}};
 menu.addEventListener('toggle',e=>{trigger.setAttribute('aria-expanded',String(e.newState==='open'));if(e.newState==='closed'&&menu.contains(document.activeElement))trigger.focus({preventScroll:true})});
 menu.onkeydown=e=>{
  const options=choices(),at=options.indexOf(document.activeElement);let next;
  if(e.key==='ArrowDown')next=(at+1)%options.length;else if(e.key==='ArrowUp')next=(at-1+options.length)%options.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=options.length-1;
  if(next!==undefined){e.preventDefault();options[next]?.focus();return}
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();menu.hidePopover();trigger.focus({preventScroll:true});return}
  if(e.key==='Tab'){menu.hidePopover();trigger.focus();return}
  if(e.key.length===1&&!e.ctrlKey&&!e.metaKey){search=performance.now()-searchAt>700?e.key:search+e.key;searchAt=performance.now();options.find(o=>o.textContent.trim().toLowerCase().startsWith(search.toLowerCase()))?.focus()}
 };
 const old=source.onchange;source.onchange=async function(event){try{return await old?.call(this,event)}finally{if(trigger.isConnected)sync()}};
 source.addEventListener('change',sync);sync();return {sync,trigger,menu};
}
function enhanceSelects(){document.querySelectorAll('select:not([multiple])').forEach(source=>{let picker=selectPickers.get(source);if(!picker){picker=createSelectPicker(source);selectPickers.set(source,picker)}else picker.sync()})}
function updateTabCursor(){
 const nav=document.querySelector('.workspace-tabs'),active=nav.querySelector('[aria-current=page]'),cursor=$('#tab-cursor');if(!active)return;
 const a=active.getBoundingClientRect(),n=nav.getBoundingClientRect();cursor.style.width=a.width+'px';cursor.style.transform='translateX('+(a.left-n.left+nav.scrollLeft)+'px)';cursor.hidden=false;
}
function transitionWorkspace(from,to){
 closePickers();const content=$('#content');workspaceMotionUntil=0;content.getAnimations?.().forEach(animation=>animation.cancel());if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&document.documentElement.dataset.motion!=='off'){
  const creative=workspaceOrder.includes(from)&&workspaceOrder.includes(to),direction=workspaceOrder.indexOf(to)<workspaceOrder.indexOf(from)?-1:1;
  if(creative)workspaceMotionUntil=performance.now()+workspaceTransitionMs;
  content.animate([{opacity:.8,transform:'translateY('+(creative?direction*28:8)+'px)'},{opacity:1,transform:'translateY(0)'}],{duration:creative?workspaceTransitionMs:160,easing:'cubic-bezier(.2,.75,.25,1)'});
 }
 const key=pid+':'+eid+':'+to;for(const [selector,open] of workspaceDisclosureState.get(key)||[]){const section=document.querySelector(selector);if(section)section.open=open}window.scrollTo({top:workspaceOrder.includes(to)?0:workspaceScroll.get(key)||0,behavior:'instant'});for(const [selector,top] of workspacePaneScroll.get(key)||[])document.querySelector(selector)?.scrollTo({top,behavior:'instant'});
}
function enhanceForms(){
 document.querySelectorAll('form').forEach(form=>{
  if(enhancedForms.has(form)||!form.onsubmit||form.getAttribute('method')==='dialog')return;
  enhancedForms.add(form);const original=form.onsubmit;let pending=false;
  form.onsubmit=async function(event){
   if(pending){event.preventDefault();return}pending=true;
   const buttons=[...form.querySelectorAll('button')].filter(b=>b.type==='submit'),previous=buttons.map(b=>b.disabled);
   buttons.forEach(b=>b.disabled=true);form.setAttribute('aria-busy','true');
   try{return await original.call(this,event)}finally{pending=false;form.removeAttribute('aria-busy');buttons.forEach((b,i)=>{if(b.isConnected)b.disabled=previous[i]})}
  };
 });
}
function renderNavigation(){
 enhanceSelects();enhanceForms();updateTabCursor();
 document.querySelectorAll('.job[data-job-card]').forEach(card=>{card.ontoggle=()=>{if(card.open)document.querySelectorAll('.job[data-job-card]').forEach(other=>{if(other!==card)other.open=false})}});
 const index=workspaceOrder.indexOf(view),stepper=$('#workspace-stepper');stepper.hidden=index<0||!p();
 if(index>=0){localStorage.setItem('luma-workspace:'+pid,view);$('#step-back').hidden=index===0;$('#step-next').hidden=index===workspaceOrder.length-1;$('#step-back').textContent='↑ '+workspaceNames[workspaceOrder[index-1]];$('#step-next').textContent=workspaceNames[workspaceOrder[index+1]]+' ↓';$('#step-back').onclick=()=>go(workspaceOrder[index-1]);$('#step-next').onclick=()=>go(workspaceOrder[index+1]);$('#scroll-cue').textContent=String(index+1).padStart(2,'0')+' / 04';$('#scroll-cue').setAttribute('aria-label',workspaceNames[view]+'，第 '+(index+1)+' 步，共 4 步');}
 if(previousWorkspace!==view){gestureState={direction:0,total:0,last:0,cooldown:performance.now()+workspaceTransitionMs};previousWorkspace=view}
}
function enterProject(id){
 const before=view;if(p())rememberWorkspaceScroll();
 gestureState.cooldown=performance.now()+workspaceTransitionMs;pid=id;eid=null;selected=null;const remembered=localStorage.getItem('luma-workspace:'+id);view=before==='jobs'?'jobs':workspaceOrder.includes(remembered)?remembered:p()?.shots.length?'shots':'overview';render();transitionWorkspace(before,view);
}
function openProjectName(){if(!p())return;$('#project-name').value=p().title;$('#projectnamedialog').showModal()}
function scrollCanConsume(target,direction){
 for(let el=target instanceof Element?target:null;el&&el!==document.body&&el!==document.documentElement;el=el.parentElement){
  if(el.scrollHeight>el.clientHeight+2&&/(auto|scroll)/.test(getComputedStyle(el).overflowY)&&((direction>0&&el.scrollTop+el.clientHeight<el.scrollHeight-2)||(direction<0&&el.scrollTop>2)))return true;
 }
 const root=document.scrollingElement;return direction>0?root.scrollTop+innerHeight<root.scrollHeight-3:root.scrollTop>3;
}
function gestureExcluded(target){
 // Only real overlays block navigation. The in-flow editor is not a modal.
 if(document.querySelector('dialog[open]:not([data-docked=true]),.picker-menu:popover-open'))return true;
 if(target.closest('select,.select-picker,.picker-menu,video,audio'))return true;
 const editor=target.closest('input,textarea,[contenteditable]');
 return !!editor&&editor===document.activeElement;
}
let edgeFeedbackTimer;
function edgeFeedback(direction,progress=0){
 const at=workspaceOrder.indexOf(view),name=workspaceNames[workspaceOrder[at+direction]],hint=$('#edge-switch-feedback');
 if(hint?.style){hint.style.setProperty('--edge-progress',Math.min(1,progress));hint.textContent=name?(direction>0?'↓  ':'↑  ')+name:'';hint.setAttribute('data-active',String(progress>0&&!!name));clearTimeout(edgeFeedbackTimer);if(progress>0)edgeFeedbackTimer=setTimeout(()=>hint.setAttribute('data-active','false'),650)}
}
function edgeGesture({delta,time,excluded,canScroll}){
 const direction=Math.sign(delta),index=workspaceOrder.indexOf(view);
 if(!direction||index<0)return false;
 if(excluded||canScroll||time<gestureState.cooldown){gestureState.total=0;gestureState.last=time;edgeFeedback(0);return false}
 if(index+direction<0||index+direction>=workspaceOrder.length){gestureState.total=0;edgeFeedback(0);return false}
 if(direction!==gestureState.direction||time-gestureState.last>240)gestureState.total=0;
 gestureState.direction=direction;gestureState.last=time;gestureState.total+=Math.abs(delta);
 edgeFeedback(direction,gestureState.total/24);
 if(gestureState.total<24)return false;
 edgeFeedback(0);go(workspaceOrder[index+direction]);gestureState.cooldown=time+workspaceTransitionMs;gestureState.last=time;gestureState.total=0;return true;
}
function workspaceMotionActive(time){return workspaceOrder.includes(view)&&time<workspaceMotionUntil}
let wheelMotionLatched=false,lastWorkspaceWheel=-Infinity;
function consumeWorkspaceWheel(input){
 const quiet=input.time-lastWorkspaceWheel;lastWorkspaceWheel=input.time;
 if(input.excluded){wheelMotionLatched=false;return edgeGesture(input)}
 // Keep the tail of this gesture out of the incoming page, even after its shorter animation ends.
 if(workspaceMotionActive(input.time)){wheelMotionLatched=true;return true}
 if(wheelMotionLatched&&quiet<100)return true;
 wheelMotionLatched=false;
 const changed=edgeGesture(input);if(changed)wheelMotionLatched=true;return changed;
}
function touchDestination(start,end,{excluded=false,canScroll=false,time=performance.now()}={}){
 if(!start||!end||excluded)return null;const delta=start.y-end.clientY;
 if((delta>0&&!start.atBottom)||(delta<0&&!start.atTop)||Math.abs(delta)<36||Math.abs(delta)<Math.abs(start.x-end.clientX)*1.15||canScroll)return null;
 const at=workspaceOrder.indexOf(view),next=at+Math.sign(delta);return at>=0&&next>=0&&next<4&&time>gestureState.cooldown?workspaceOrder[next]:null;
}
function initializeNavigation(){
 document.querySelectorAll('[data-close-sheet]').forEach(button=>button.onclick=()=>button.closest('dialog').close('cancel'));
 for(const [dialogId,returnId] of [['#episodedialog','#episodes-trigger'],['#projectnamedialog','#projects-trigger']]){
  $(dialogId).addEventListener('close',()=>$(returnId)?.focus({preventScroll:true}));
 }
 document.querySelector('.brand').onclick=e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();go('library')};
 document.addEventListener('scroll',e=>{if(!(e.target instanceof Element)||!e.target.closest('.picker-menu'))closePickers()},{capture:true,passive:true});
 window.addEventListener('resize',()=>{closePickers();updateTabCursor()});
 document.querySelector('.workspace-tabs').onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const index=workspaceOrder.indexOf(view),next=e.key==='Home'?0:e.key==='End'?3:(index+(e.key==='ArrowRight'?1:3))%4;e.preventDefault();go(workspaceOrder[next]);document.querySelector('.workspace-tabs [aria-current=page]')?.focus()};
 document.addEventListener('wheel',e=>{if(Math.abs(e.deltaY)<Math.abs(e.deltaX)||e.ctrlKey||e.metaKey)return;const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?innerHeight:1);if(consumeWorkspaceWheel({delta,time:performance.now(),excluded:gestureExcluded(e.target),canScroll:scrollCanConsume(e.target,Math.sign(delta))}))e.preventDefault()},{passive:false});
 document.addEventListener('touchstart',e=>{const t=e.touches[0];touchOrigin=t?{x:t.clientX,y:t.clientY,target:e.target,atTop:!scrollCanConsume(e.target,-1),atBottom:!scrollCanConsume(e.target,1)}:null},{passive:true});
 document.addEventListener('touchmove',e=>{if(workspaceMotionActive(performance.now())&&!gestureExcluded(e.target))e.preventDefault()},{passive:false});
 document.addEventListener('touchend',e=>{const end=e.changedTouches[0],start=touchOrigin;touchOrigin=null;if(!end||!start)return;const target=touchDestination(start,end,{excluded:gestureExcluded(start.target),canScroll:scrollCanConsume(start.target,Math.sign(start.y-end.clientY))});if(target)go(target)},{passive:true});
 document.addEventListener('keydown',e=>{if(e.target.closest('input,textarea,select,[contenteditable]'))return;if(e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)&&!document.querySelector('dialog[open]:not([data-docked=true]),.picker-menu:popover-open')){const at=workspaceOrder.indexOf(view),next=at+(e.key==='ArrowDown'?1:-1);if(at>=0&&next>=0&&next<4){e.preventDefault();go(workspaceOrder[next])}}});
 $('#project-name-cancel').onclick=()=>$('#projectnamedialog').close();
 $('#project-name-form').onsubmit=async e=>{e.preventDefault();const title=$('#project-name').value.trim();if(!title){toast('请输入作品名称');return}const submit=e.target.querySelector('[type=submit]');submit.disabled=true;try{p().title=title;await save();$('#projectnamedialog').close();toast('作品已重命名')}catch(error){toast(error.message)}finally{submit.disabled=false}};
}
