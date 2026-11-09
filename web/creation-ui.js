/* Shared creation controls. UI drafts never bypass saved-input, version or allowance checks. */
let shotIntentMode='setup',canvasBoardView=false;
let stagedShotReferences=new Set();
let referenceReturnLabel='';
function dismissCreationPopover(popup,trigger){if(popup.tagName==='DIALOG')popup.close();else popup.hidePopover();trigger?.focus({preventScroll:true})}
function bindCreationPopoverEscape(popup,returnTrigger){popup.addEventListener('keydown',e=>{if(e.key!=='Escape')return;e.preventDefault();e.stopPropagation();dismissCreationPopover(popup,returnTrigger())})}
function referenceReturnTrigger(){return [...document.querySelectorAll('[data-open-shot-references]')].find(b=>b.getAttribute('aria-label')===referenceReturnLabel)||document.querySelector('[data-open-shot-references]')}
function uiIcon(name){return `<img class="ui-icon" src="/icons/${name}.svg" alt="" aria-hidden="true">`}
function setShotIntentMode(mode){
 shotIntentMode=mode;
 document.querySelectorAll('[data-intent-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.intentMode===mode)));
 document.querySelectorAll('[data-intent-panel]').forEach(panel=>panel.hidden=panel.dataset.intentPanel!==mode);
 const footer=document.querySelector('.editor-actions');if(footer)footer.hidden=shotToolTab==='takes'||(shotToolTab==='intent'&&mode==='revision');
}
function referenceTrayMarkup(s){
 return `<div class="reference-tray" id="shot-reference-tray"></div><select id="refs" aria-label="使用的素材" multiple hidden ${s.locked?'disabled':''}>${p().assets.map(a=>`<option value="${esc(a.id)}" ${s.asset_ids.includes(a.id)?'selected':''}>${esc(a.name)}</option>`).join('')}</select>
 <dialog id="shot-reference-picker" class="picker-menu reference-picker" aria-label="选择镜头参考"><div class="reference-picker-top"><div><h3>镜头参考</h3></div><button type="button" class="icon-button" id="cancel-shot-references" aria-label="关闭参考选择">${uiIcon('x')}</button></div><label class="reference-search-label">搜索素材<input id="shot-reference-search" type="search" placeholder="搜索角色、场景、道具" autocomplete="off"></label><div id="shot-reference-grid" class="reference-picker-grid"></div><footer><span id="shot-reference-count" role="status"></span><div class="actions"><button type="button" id="discard-shot-references">取消</button><button type="button" id="apply-shot-references" class="primary">带入这一镜</button></div></footer></dialog>`;
}
function shotReferenceVersion(a){const current=shot();return a.versions.find(v=>v.id===current?.asset_bindings?.[a.id])||a.versions.find(v=>v.id===a.selected_version)}
function shotReferenceCover(a){const v=shotReferenceVersion(a);return v?.views?.front||Object.values(v?.views||{})[0]||v?.file}
function updateReferenceTray(){
 const tray=$('#shot-reference-tray'),select=$('#refs');if(!tray||!select)return;
 const ids=[...select.selectedOptions].map(o=>o.value),assets=ids.map(id=>p().assets.find(a=>a.id===id)).filter(Boolean);
 tray.innerHTML=assets.map(a=>{const file=shotReferenceCover(a);return `<button type="button" class="reference-thumb ${file&&a.kind!=='voice'?'has-image':'reference-chip'}" data-open-shot-references aria-label="选择参考：${esc(a.name)}" ${shot()?.locked?'disabled':''}><span>${file&&a.kind!=='voice'?`<img class="reference-image" src="/media/${esc(file)}" alt="">`:uiIcon(a.kind==='character'?'user':a.kind==='scene'?'map-pin':a.kind==='voice'?'microphone':'folder')}</span><small>${esc(a.name)}</small></button>`}).join('')+`<button type="button" class="reference-thumb reference-chip add-reference" data-open-shot-references aria-label="选择参考素材" ${shot()?.locked?'disabled':''}><span>${uiIcon('plus')}</span><small>参考素材</small></button>`;
 tray.querySelectorAll('[data-open-shot-references]').forEach(b=>b.onclick=()=>openShotReferences(b));
}
function drawShotReferenceChoices(){
 const focusedReference=document.activeElement?.dataset.stageReference;
 const query=$('#shot-reference-search').value.trim().toLowerCase(),assets=p().assets.filter(a=>(a.name+' '+a.description).toLowerCase().includes(query));
 $('#shot-reference-grid').innerHTML=assets.map(a=>{const file=shotReferenceCover(a);return `<button type="button" class="reference-pick" data-stage-reference="${esc(a.id)}" aria-pressed="${stagedShotReferences.has(a.id)}"><span class="reference-pick-image">${file&&a.kind!=='voice'?`<img src="/media/${esc(file)}" alt="${esc(a.name)}">`:uiIcon(a.kind==='character'?'user':a.kind==='scene'?'map-pin':a.kind==='voice'?'microphone':'folder')}</span><span><strong>${esc(a.name)}</strong><small>${esc(assetKindNames[a.kind])}${file?' · 有参考素材':' · 文字设定'}</small></span><span class="reference-pick-check">${stagedShotReferences.has(a.id)?uiIcon('check'):''}</span></button>`}).join('')||'<p class="reference-no-results">没有找到匹配的素材</p>';
 document.querySelectorAll('[data-stage-reference]').forEach(b=>b.onclick=()=>{const id=b.dataset.stageReference;if(stagedShotReferences.has(id))stagedShotReferences.delete(id);else stagedShotReferences.add(id);drawShotReferenceChoices()});
 $('#shot-reference-count').textContent='已选 '+stagedShotReferences.size+' 项';
 if(focusedReference)document.querySelector('[data-stage-reference="'+CSS.escape(focusedReference)+'"]')?.focus({preventScroll:true});
}
function openShotReferences(trigger=document.activeElement){
 const select=$('#refs'),picker=$('#shot-reference-picker');if(!select||!picker||shot()?.locked)return;
 referenceReturnLabel=trigger?.getAttribute('aria-label')||'';closePickers();stagedShotReferences=new Set([...select.selectedOptions].map(o=>o.value));$('#shot-reference-search').value='';drawShotReferenceChoices();picker.showModal();$('#shot-reference-search').focus({preventScroll:true});
}
function updateCreationSummaries(){
 updateReferenceTray();
 const duration=document.querySelector('[data-key=duration]'),framing=document.querySelector('[data-key=framing]'),camera=document.querySelector('[data-key=camera]');
 if($('#duration-chip-label')&&duration)$('#duration-chip-label').textContent=duration.value+' 秒';
 if($('#framing-chip-label')&&framing)$('#framing-chip-label').textContent=framing.value||'景别';
 if($('#camera-chip-label')&&camera)$('#camera-chip-label').textContent=camera.value||'运镜';
 updateStoryboardPreview();
}
function updateStoryboardPreview(){
 const frame=document.querySelector('.shot-stage.is-storyboard');if(!frame)return;
 const description=document.querySelector('[data-key=description]'),duration=document.querySelector('[data-key=duration]'),framing=document.querySelector('[data-key=framing]');
 const set=(selector,text)=>{const node=frame.querySelector(selector);if(node)node.textContent=text};
 if(description)set('.frame-treatment',description.value||'描述这一镜，让故事有画面。');
 if(duration)set('.frame-duration',duration.value+' 秒');
 if(framing)set('.frame-framing',framing.value||'分镜');
 set('.frame-empty-footer>span',hasUnsavedShot()?'分镜草稿 · 待添加画面':'待添加画面');
}
function bindCreationControls(){
 document.querySelectorAll('[data-intent-mode]').forEach(b=>b.onclick=()=>setShotIntentMode(b.dataset.intentMode));setShotIntentMode(shotIntentMode);
 const referencePicker=$('#shot-reference-picker');
 if(referencePicker){
  $('#shot-reference-search').oninput=drawShotReferenceChoices;
  bindCreationPopoverEscape(referencePicker,referenceReturnTrigger);
  for(const id of ['cancel-shot-references','discard-shot-references'])$('#'+id).onclick=()=>dismissCreationPopover(referencePicker,referenceReturnTrigger());
  $('#apply-shot-references').onclick=()=>{for(const option of $('#refs').options)option.selected=stagedShotReferences.has(option.value);rememberDraft();updateShotSaveState();dismissCreationPopover(referencePicker,referenceReturnTrigger())};
 }
 document.querySelectorAll('[data-parameter-popover]').forEach(button=>{const popup=document.getElementById(button.dataset.parameterPopover);bindCreationPopoverEscape(popup,()=>button);popup.querySelector('[data-close-parameter]').onclick=()=>dismissCreationPopover(popup,button);button.onclick=()=>{
  const popup=document.getElementById(button.dataset.parameterPopover);if(popup.matches(':popover-open')){popup.hidePopover();return}
  closePickers();popup.showPopover();const r=button.getBoundingClientRect();popup.style.left=Math.min(Math.max(12,r.left),innerWidth-popup.offsetWidth-12)+'px';popup.style.top=Math.max(12,r.top-popup.offsetHeight-9)+'px';popup.querySelector('input')?.focus({preventScroll:true});
 }});
 updateCreationSummaries();
}
function bindResultControls(s){
 bind('#toggle-board',()=>{canvasBoardView=!canvasBoardView;render()});
 bind('#import-current-frame',()=>$('#current-frame-file').click());
 const upload=$('#current-frame-file');if(upload)upload.onchange=()=>{const file=upload.files[0];if(!file)return;const kind=file.type.startsWith('image/')?'image':file.type.startsWith('video/')?'video':null;if(!kind){toast('请选择图片或视频');return}importShotMedia(s,file,kind).catch(e=>toast(e.message))};
 bind('#choose-current-frame',()=>openShotTools('takes'));
 bind('#expand-current-frame',()=>$('#frame-preview').showModal());bind('#close-frame-preview',()=>$('#frame-preview').close());
 document.querySelectorAll('[data-open-shot-references]').forEach(b=>b.onclick=()=>{openShotTools('intent');openShotReferences(b)});
}

function animateShotChange(){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.dataset.motion==='off')return;
 document.querySelector('.shot-stage')?.animate([{opacity:.45,transform:'scale(.985)'},{opacity:1,transform:'scale(1)'}],{duration:220,easing:'cubic-bezier(.2,.7,.2,1)'});
}
