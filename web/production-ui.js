async function productionEdit(fields,options={}){
 const savedDraftKey=draftKey(),targetProjectId=pid;
 const result=await api('/api/production',{project_id:targetProjectId,revision:p().revision,...fields});
 state.projects=state.projects.map(x=>x.id===targetProjectId?result:x);if(options.draftFields)clearDraft(options.draftFields,savedDraftKey);await refresh(false);render();return result;
}
async function uploadMedia(file){
 if(!file)throw Error('请选择素材');
 const r=await fetch('/api/upload/'+file.name.split('.').pop().toLowerCase(),{method:'POST',headers:{'X-Auteur':'studio'},body:file});
 const d=await r.json();if(!r.ok)throw Error(d.error);return d;
}
const mediaNames={image:'画面',video:'视频',audio:'配音'};
function candidateOutdated(s,t){return t.source!=='import'&&t.basis&&flowStatus().shots.find(x=>x.shot_id===s.id)?.basis!==t.basis}
function mediaPreview(t){return t.kind==='audio'?`<audio controls preload="none" src="/media/${esc(t.file)}"></audio>`:t.kind==='image'?`<img alt="${esc(t.label||'素材备选')}" loading="lazy" src="/media/${esc(t.file)}">`:`<video controls preload="metadata" src="/media/${esc(t.file)}"></video>`}
let assetSelection=null,assetCategory='all',assetToolsOpen=false,assetToolsProject=null,assetQuery='';
const assetKindNames={character:'角色',scene:'场景',prop:'道具',style:'风格',voice:'声音'};
function assetCover(a){const v=a.versions.find(v=>v.id===a.selected_version);return v?.views?.front||Object.values(v?.views||{})[0]||v?.file}
function updateAssetSaveState(){
 document.querySelectorAll('[data-saveasset]').forEach(button=>{
  const asset=p().assets.find(a=>a.id===button.dataset.saveasset),name=document.querySelector('[data-asset-name="'+CSS.escape(asset.id)+'"]'),description=document.querySelector('[data-asset="'+CSS.escape(asset.id)+'"]');
  button.disabled=!name.value.trim()||(name.value.trim()===asset.name&&description.value===(asset.description||''));
 });
}
function drawAssets(){
 const oldAssetDialog=$('#asset-tools'),assetScroll=oldAssetDialog?.scrollTop||0,assetFocus=document.activeElement?.id,assetCaret=document.activeElement?.selectionStart,assetCaretEnd=document.activeElement?.selectionEnd,previousAsset=oldAssetDialog?.dataset.currentAsset,assetExpanded=new Set([...document.querySelectorAll('#asset-tools details[open]')].map(d=>d.className));
 if(assetToolsProject!==pid){assetToolsOpen=false;assetToolsProject=pid}
 const assets=p().assets,visible=assets.filter(a=>(assetCategory==='all'||a.kind===assetCategory)&&(a.name+' '+a.description).toLowerCase().includes(assetQuery.toLowerCase()));
 if(!visible.some(a=>a.id===assetSelection))assetSelection=visible[0]?.id;
 const chosen=visible.find(a=>a.id===assetSelection),v=chosen?.versions.find(v=>v.id===chosen.selected_version);
 $('#content').innerHTML=`<div class="library-heading"><div><h2>素材库</h2></div><div class="actions">${state.dify.assets?'<button id="design" class="text-button">创作建议</button>':''}<button id="addasset" class="primary">新增素材</button></div></div>
 <div class="asset-navigation"><div class="collection-toolbar"><label class="collection-search">搜索素材<input id="asset-search" type="search" placeholder="搜索角色、场景、道具" value="${esc(assetQuery)}"></label><span>${visible.length} 项素材</span></div><div class="library-filter" role="group" aria-label="素材分类">${[['all','全部'],...Object.entries(assetKindNames)].map(([k,n])=>`<button data-asset-category="${k}" aria-pressed="${assetCategory===k}">${n}<span>${assets.filter(a=>k==='all'||a.kind===k).length}</span></button>`).join('')}</div></div>
 <div class="asset-browser gallery-browser ${assetToolsOpen&&chosen?'has-selection':''}"><section class="asset-collection" aria-label="素材资料库"><div class="asset-contact-sheet">${visible.map(a=>{const file=assetCover(a);return `<button class="asset-tile ${a.id===assetSelection?'is-selected':''}" data-open-asset="${esc(a.id)}" aria-label="编辑${esc(a.name)}" aria-pressed="${a.id===assetSelection}"><span class="asset-art ${file&&a.kind!=='voice'?'has-image':''}" data-kind="${esc(a.kind)}">${file&&a.kind!=='voice'?`<img alt="${esc(a.name)}参考素材" src="/media/${esc(file)}" loading="lazy">`:`<span class="asset-placeholder"><span class="asset-placeholder-description">${esc(a.description||'补充文字设定，开始制作。')}</span><small>尚无${a.kind==='voice'?'声音样本':'参考图'}</small></span>`}</span><span class="asset-tile-info"><strong>${esc(a.name)}</strong><small>${assetKindNames[a.kind]} · ${a.versions.length} 版</small></span></button>`}).join('')||'<div class="library-empty"><h3>还没有这类素材</h3><p>添加参考图片或人物设定，供镜头制作使用。</p></div>'}</div></section>
 ${chosen?`<dialog id="asset-tools" data-docked="true" aria-modal="false" data-current-asset="${esc(chosen.id)}" aria-label="素材详情"><div class="tools-dialog-top"><strong>${esc(chosen.name)}</strong><div class="asset-dialog-browse"><button type="button" class="icon-button" data-cycle-asset="-1" aria-label="上一项素材" ${visible.indexOf(chosen)===0?'disabled':''}>${uiIcon('chevron-left')}</button><span>${visible.indexOf(chosen)+1} / ${visible.length}</span><button type="button" class="icon-button" data-cycle-asset="1" aria-label="下一项素材" ${visible.indexOf(chosen)===visible.length-1?'disabled':''}>${uiIcon('chevron-right')}</button></div><button id="close-asset-tools" class="icon-button" aria-label="关闭素材详情" autofocus>${uiIcon('x')}</button></div><section class="asset asset-detail" aria-label="${esc(chosen.name)}素材编辑"><div class="asset-detail-heading"><span>${assetKindNames[chosen.kind]}</span><span class="version-stamp">版本 ${chosen.versions.findIndex(x=>x.id===v.id)+1} / ${chosen.versions.length}</span></div><div class="asset-detail-body"><div class="asset-visual-column ${assetCover(chosen)?'has-preview':'no-preview'}">${assetCover(chosen)?`<div class="asset-preview">${mediaPreview({kind:chosen.kind==='voice'?'audio':'image',file:assetCover(chosen),label:chosen.name})}</div>`:`<div class="asset-preview-empty">${uiIcon(chosen.kind==='character'?'user':chosen.kind==='scene'?'map-pin':'folder')}<p>${chosen.kind==='voice'?'尚无声音样本':'尚无参考图'}</p></div>`}<button type="button" class="text-button" data-import-asset="${esc(chosen.id)}">${uiIcon('upload')}添加参考素材</button></div><div class="asset-fields-column"><details class="asset-text-editor" open><summary>文字设定</summary><label>名称<input id="asset-name:${esc(chosen.id)}" data-asset-name="${esc(chosen.id)}" value="${esc(chosen.name)}" maxlength="200"></label><label>外观与风格<textarea id="asset:${esc(chosen.id)}" data-asset="${esc(chosen.id)}" rows="3">${esc(chosen.description)}</textarea></label><div class="asset-save-row"><button id="asset-save:${esc(chosen.id)}" class="primary" data-saveasset="${esc(chosen.id)}">保存设定</button></div></details>${characterControls(chosen,v)}<details class="reference-upload"><summary>${chosen.kind==='voice'?'声音样本':'参考图片'}与历史版本</summary>${mediaImportField(chosen.kind==='voice'?'添加声音样本':'添加通用参考图',`data-asset-file="${esc(chosen.id)}" accept="${chosen.kind==='voice'?'audio/*':'image/png,image/jpeg,image/webp'}"`)}<label>当前设定<select data-version="${esc(chosen.id)}">${chosen.versions.map((x,i)=>`<option value="${esc(x.id)}" ${x.id===chosen.selected_version?'selected':''}>版本 ${i+1} · ${esc(x.label||x.name)}</option>`).join('')}</select></label><p class="muted">更换素材后，请到镜头里确认是否采用。</p></details></div></div></section></dialog>`:''}</div>`;
 const dialog=$('#asset-tools');if(dialog){dialog.addEventListener('keydown',event=>{if(event.key==='Escape'&&!document.querySelector('.picker-menu:popover-open')){event.preventDefault();dialog.close();return}if(event.defaultPrevented||!['ArrowLeft','ArrowRight'].includes(event.key)||event.target.closest('input,textarea,select,[contenteditable],.select-picker')||document.querySelector('.picker-menu:popover-open'))return;const button=dialog.querySelector('[data-cycle-asset="'+(event.key==='ArrowRight'?'1':'-1')+'"]');if(button&&!button.disabled){event.preventDefault();button.click()}});if(oldAssetDialog?.open)dialog.dataset.continuation='true';if(previousAsset===chosen.id)dialog.querySelectorAll('details').forEach(d=>d.open=assetExpanded.has(d.className));bind('#close-asset-tools',()=>{assetToolsOpen=false;dialog.close()});dialog.oncancel=()=>{assetToolsOpen=false};dialog.onclose=()=>{assetToolsOpen=false;document.querySelector('.asset-browser')?.classList.remove('has-selection');document.querySelector('[data-open-asset="'+CSS.escape(assetSelection)+'"]')?.focus({preventScroll:true})};if(assetToolsOpen){const opener=document.activeElement;dialog.show();if(opener?.isConnected&&!dialog.contains(opener))opener.focus({preventScroll:true});if(previousAsset===chosen.id)requestAnimationFrame(()=>{if(!dialog.isConnected||!dialog.open)return;if(assetFocus){const field=dialog.querySelector('#'+CSS.escape(assetFocus));field?.focus({preventScroll:true});if(assetCaret!=null&&field?.setSelectionRange)try{field.setSelectionRange(assetCaret,assetCaretEnd)}catch{}}dialog.scrollTop=assetScroll})}}
 document.querySelectorAll('[data-cycle-asset]').forEach(button=>button.onclick=()=>{const next=visible.indexOf(chosen)+Number(button.dataset.cycleAsset);if(next<0||next>=visible.length)return;assetSelection=visible[next].id;assetToolsOpen=true;const direction=button.dataset.cycleAsset;render();requestAnimationFrame(()=>{const target=document.querySelector('[data-cycle-asset="'+direction+'"]:not(:disabled)')||document.querySelector('[data-cycle-asset]:not(:disabled)')||$('#close-asset-tools');target?.focus({preventScroll:true})})});
 $('#asset-search').oninput=e=>{assetQuery=e.target.value;const start=e.target.selectionStart,end=e.target.selectionEnd;render();$('#asset-search').focus();try{$('#asset-search').setSelectionRange(start,end)}catch{}};
 bindCharacterAssets();
 document.querySelectorAll('[data-asset-name],[data-asset]').forEach(field=>field.addEventListener('input',updateAssetSaveState));
 document.querySelectorAll('[data-import-asset]').forEach(button=>button.onclick=()=>document.querySelector('[data-asset-file="'+CSS.escape(button.dataset.importAsset)+'"]')?.click());
 bind('#addasset',()=>$('#assetdialog').showModal());bind('#design',()=>run('assets'));
 document.querySelectorAll('[data-asset-category]').forEach(b=>b.onclick=()=>{assetCategory=b.dataset.assetCategory;render();[...document.querySelectorAll('[data-asset-category]')].find(x=>x.dataset.assetCategory===assetCategory)?.focus({preventScroll:true})});
 document.querySelectorAll('[data-open-asset]').forEach(button=>button.onclick=()=>{assetSelection=button.dataset.openAsset;assetToolsOpen=true;render()});
 document.querySelectorAll('[data-saveasset]').forEach(b=>b.onclick=async()=>{if(b.disabled)return;b.disabled=true;try{let a=p().assets.find(a=>a.id===b.dataset.saveasset);a.name=document.querySelector(`[data-asset-name="${a.id}"]`).value.trim();a.description=document.querySelector(`[data-asset="${a.id}"]`).value;await save({draftFields:['asset:'+a.id,'asset-name:'+a.id]});toast('新设定已保存，旧版本保留')}catch(e){toast(e.message)}finally{if(b.isConnected)updateAssetSaveState()}});
 document.querySelectorAll('[data-version]').forEach(el=>el.onchange=async()=>{try{await productionEdit({action:'asset_select',asset_id:el.dataset.version,version_id:el.value});toast('新设定已选用，已有镜头保持原版本')}catch(e){toast(e.message)}});
 document.querySelectorAll('[data-asset-file]').forEach(el=>el.onchange=async()=>{try{const a=p().assets.find(a=>a.id===el.dataset.assetFile),file=el.files[0],d=await uploadMedia(file);if(!d.streams.includes(a.kind==='voice'?'audio':'video'))throw Error('文件类型与素材不符');await productionEdit({action:'asset_version',asset_id:a.id,file:d.file,label:file.name});toast('参考素材已保存为新版本')}catch(e){toast(e.message)}});
}
function productionReferences(s){
 const refs=s.asset_ids.map(id=>{const a=p().assets.find(a=>a.id===id);const v=a?.versions.find(v=>v.id===s.asset_bindings?.[id]);return `<p>${esc(a?.name)} · ${v?.file||Object.keys(v?.views||{}).length?'已有参考图':'仅文字设定'}${a&&s.asset_bindings?.[id]!==a.selected_version?' · 有新版本':''}</p>${a?`<label>使用版本<select data-bound-asset="${esc(a.id)}" ${s.locked?'disabled':''}>${a.versions.map((v,i)=>`<option value="${esc(v.id)}" ${s.asset_bindings?.[a.id]===v.id?'selected':''}>版本 ${i+1} · ${esc(v.outfit||v.label||v.name)}${v.voice_id?' · '+esc(v.voice_id):''}</option>`).join('')}</select></label>`:''}`}).join('');
 return `${refs||'<p class="muted">尚未使用的素材</p>'}<button id="bind-current" ${s.locked?'disabled':''}>更新为素材当前设定</button><p class="muted">生成方式和参考图用途在制作准备中选择。</p><label>承接镜头<select id="continuity" ${s.locked?'disabled':''}><option value="">独立构图</option>${shots().filter(x=>x.id!==s.id).map(x=>`<option value="${esc(x.id)}" ${s.continuity_from===x.id?'selected':''}>镜头 ${shots().indexOf(x)+1} · ${esc(x.description.slice(0,18))}</option>`).join('')}</select></label>`;
}
function isPartialTake(s,t){const g=t.generation_segment;return !!g&&(g.start!==0||Math.abs(g.end-s.duration)>.001)}
function cutDraftDefaults(s){
 const sources=s.takes.filter(t=>['video','image'].includes(t.kind)&&!isPartialTake(s,t)),chosen=s.selected_takes.video||s.selected_takes.image;
 return s.clip||{source_take_id:chosen||sources[sources.length-1]?.id,trim_start:s.selected_takes.video?s.trim_start||0:0,trim_end:null};
}
function hasUnsavedCut(){
 const s=shot(),source=$('#cut-source');if(!s||!source)return false;
 const saved=cutDraftDefaults(s),pick=s.takes.find(t=>t.id===source.value);
 return source.value!==saved.source_take_id||(pick?.kind==='video'&&(Number($('#cut-start')?.value||0)!==saved.trim_start||($('#cut-end')?.value===''?null:Number($('#cut-end')?.value))!==saved.trim_end));
}
function cutControls(s){
 const sources=s.takes.filter(t=>['video','image'].includes(t.kind)&&!isPartialTake(s,t));if(!sources.length)return '';
 const cur=cutDraftDefaults(s);
 const pick=sources.find(t=>t.id===cur.source_take_id)||sources[0];
 return `<fieldset class="cut" ${s.locked?'disabled':''}><legend>剪辑片段</legend><label>使用的备选<select id="cut-source">${sources.map(t=>`<option value="${esc(t.id)}" ${t.id===pick.id?'selected':''}>${mediaNames[t.kind]} · ${esc(t.label)}${s.selected_takes[t.kind]===t.id?'（已选用）':''}</option>`).join('')}</select></label>${`<label ${pick.kind==='video'?'':'hidden'}>起点 / 秒<input id="cut-start" type="number" min="0" step="0.1" value="${cur.trim_start||0}"></label><label ${pick.kind==='video'?'':'hidden'}>终点 / 秒（留空为到素材结尾）<input id="cut-end" type="number" min="0" step="0.1" value="${cur.trim_end??''}"></label>`}<button id="cut-save">保存剪辑片段</button><p class="muted">镜头时长仍为 ${s.duration} 秒：片段较短时停在最后一帧，较长时截断。保存后该备选会同步成为已选画面，需要重新审核。</p></fieldset>`;
}
function syncCutFields(reset=false){
 const source=$('#cut-source');if(!source)return;
 const t=shot()?.takes.find(t=>t.id===source.value),form=$('#cut-save')?.closest('fieldset');
 form?.querySelectorAll('label').forEach((label,i)=>{if(i>0)label.hidden=t?.kind!=='video'});
 if(reset){if($('#cut-start'))$('#cut-start').value=0;if($('#cut-end'))$('#cut-end').value=''}
}
function bindCut(s){
 const save=$('#cut-save');if(!save)return;
 $('#cut-source').onchange=()=>{syncCutFields(true);rememberDraft();updateShotSaveState()};
 save.onclick=async()=>{try{if(hasUnsavedShot()){toast('请先保存镜头修改，再设置剪辑片段');return}const end=$('#cut-end')?.value;await productionEdit({action:'set_clip',shot_id:s.id,source_take_id:$('#cut-source').value,trim_start:Number($('#cut-start')?.value||0),trim_end:end===''||end==null?null:Number(end)},{draftFields:['cut-source','cut-start','cut-end']});toast('剪辑片段已保存，请重新审核')}catch(e){toast(e.message)}};
}
function mediaImportField(label,attributes,icon='upload',hint='从本机选择文件'){
 return `<label class="media-import-entry">${uiIcon(icon)}<span><strong>${label}</strong><small>${hint}</small></span><span class="import-entry-action" aria-hidden="true">${uiIcon('plus')}</span><input type="file" aria-label="${label}" ${attributes}></label>`;
}
function takesPanel(s){
 return `<section id="panel-takes" role="tabpanel" aria-labelledby="tab-takes" data-editor-panel="takes" hidden><div class="shot-generation-actions">${['image','video','audio'].filter(kind=>state.dify[kind]).map(kind=>`<button data-generate="${kind}" ${s.locked||!state.spending?.remaining?'disabled':''}>生成${mediaNames[kind]}</button>`).join('')}<span class="muted">${!state.spending?.remaining?'生成已暂停；可导入本地素材。':''}</span></div><details class="import-section" ${s.takes.length?'':'open'}><summary>导入素材</summary><div class="media-import-grid">${mediaImportField('画面图片',`id="image-file" accept="image/png,image/jpeg,image/webp" ${s.locked?'disabled':''}`,'photo','PNG、JPG、WebP')}${mediaImportField('镜头视频',`id="video-file" accept="video/mp4,video/quicktime" ${s.locked?'disabled':''}`,'movie','MP4、MOV')}${mediaImportField('对白音轨',`id="audio-file" accept="audio/*" ${s.locked?'disabled':''}`,'upload','选择音频文件')}</div></details><div class="take-list">${s.takes.slice().reverse().map(t=>`<article class="take ${s.selected_takes[t.kind]===t.id?'take-selected':''}">${mediaPreview(t)}<p>${mediaNames[t.kind]} · ${esc(t.label)}</p>${(s.lines||[]).some(l=>l.audio_take_id===t.id)?'<p class="muted">已用于逐句配音；采用为整镜音轨会替换逐句安排。</p>':''}${candidateOutdated(s,t)?'<p class="candidate-warning">镜头设定已变化，采用前请重新比较。</p>':''}<button data-select-take="${esc(t.id)}" ${s.locked||isPartialTake(s,t)||s.selected_takes[t.kind]===t.id?'disabled':''}>${s.selected_takes[t.kind]===t.id?'已选用':isPartialTake(s,t)?'局部片段 · 请先拼接':t.kind==='audio'?'采用为整镜音轨':'采用此版本'}</button></article>`).join('')||'<div class="candidate-empty">还没有素材备选<br><small>导入或生成后，素材会保存在这里。</small></div>'}</div>${segmentAssemblyControls(s)}${cutControls(s)}</section>`;
}
function bindProductionShot(s){
 if(!s)return;
 bind('#bind-current',()=>{if(hasUnsavedShot())throw Error('请先保存镜头修改，再切换参考');return productionEdit({action:'bind_current',shot_id:s.id})});
 bindSegmentAssembly(s);bindCut(s);bindLines(s);bindLineAudio(s);
 document.querySelectorAll('[data-bound-asset]').forEach(el=>el.onchange=async()=>{try{
  if(hasUnsavedShot())throw Error('请先保存镜头修改，再切换角色版本');
  await productionEdit({action:'bind_asset_version',shot_id:s.id,asset_id:el.dataset.boundAsset,version_id:el.value});toast('这一镜已采用该版本，请重新确认');
 }catch(e){el.value=s.asset_bindings[el.dataset.boundAsset];toast(e.message)}});
 const fm=$('#frame-mode');if(fm)fm.onchange=async()=>{try{if(hasUnsavedShot())throw Error('请先保存镜头修改');await productionEdit({action:'set_frame_mode',shot_id:s.id,frame_mode:fm.value})}catch(e){fm.value=s.frame_mode||'references';toast(e.message)}};
 const cont=$('#continuity');if(cont)cont.onchange=async()=>{const previous=s.continuity_from;try{if(hasUnsavedShot())throw Error('请先保存镜头修改');s.continuity_from=cont.value||null;await save()}catch(e){s.continuity_from=previous;cont.value=previous||'';toast(e.message)}};
 ['image','video','audio'].forEach(kind=>{const el=$('#'+kind+'-file');if(el)el.onchange=()=>importShotMedia(s,el.files[0],kind).catch(error=>toast(error.message))});
 document.querySelectorAll('[data-select-take]').forEach(b=>b.onclick=async()=>{try{if(hasUnsavedShot()||hasUnsavedCut())throw Error('请先保存镜头与剪辑修改，再选用素材');const t=s.takes.find(x=>x.id===b.dataset.selectTake);if(candidateOutdated(s,t)&&!await confirmAction('这个备选来自修改前的镜头设定。仍然采用，并在交付前重新审核？'))return;await productionEdit({action:'select_take',shot_id:s.id,take_id:b.dataset.selectTake});toast('已采用，审核后可导出')}catch(e){toast(e.message)}});
}
function budgetPanel(){return `<section class="budget-panel" data-settings-panel="budget"><h3>${state.spending?.remaining?'生成已开启':'生成已暂停'}</h3><p>还可发起生成 ${state.spending?.remaining||0} 次。达到上限后自动暂停。</p><form id="budget-form"><label>本次生成上限<input name="remaining" type="number" min="0" max="20" value="0" required></label><button>应用上限</button><button type="button" id="pause-calls">立即暂停</button></form><details><summary>次数如何计算？</summary><p>每次发起生成或继续确认后的制作流程计为一次操作，一次流程可能调用多个模型。这不是服务商账户余额，也不是费用预算。本机累计已放行 ${state.spending?.used||0} 次。设为 0 会暂停后续提交，已经开始的任务仍可能计费。</p></details></section>`}
function bindBudget(){
 $('#budget-form').onsubmit=async e=>{e.preventDefault();try{const n=Number(new FormData(e.target).get('remaining'));if(n&&!await confirmAction(`授权最多 ${n} 次外部操作？一次工作流可能消耗多条 Dify 消息。`))return;await api('/api/settings/spending',{remaining:n});await refresh()}catch(e){toast(e.message)}};
 bind('#pause-calls',async()=>{await api('/api/settings/spending',{remaining:0});await refresh();toast('后续付费提交已暂停')});
}

async function importShotMedia(s,file,kind){
 if(!file)return;
 if(s.locked)throw Error('请先解除镜头锁定');
 if(hasUnsavedShot()||hasUnsavedCut())throw Error('请先保存镜头与剪辑修改，再导入素材');
 const data=await uploadMedia(file);
 if(!data.streams.includes(kind==='image'?'video':kind))throw Error('文件不包含对应画面或声音');
 await productionEdit({action:'add_take',shot_id:s.id,kind,file:data.file,label:file.name});
 toast('已加入备选，选用后才会更新画面或声音');
}

function segmentAssemblyControls(s){
 const segments=s.preparation?.segments;if(!segments?.length)return '';
 return `<details class="import-section"><summary>片段素材与拼接</summary><p>逐段选用已有素材，视频长度须足够。拼接只在本机进行，完成后作为新的完整镜头备选保留。</p>${segments.map((seg,i)=>{const choice=s.segment_sources?.[seg.id]||{},takes=s.takes.filter(t=>t.kind===seg.kind&&(!t.generation_segment||t.generation_segment.id===seg.id));return `<fieldset data-segment-source="${esc(seg.id)}" ${s.locked?'disabled':''}><legend>片段 ${i+1} · ${seg.start}–${seg.end} 秒</legend><label>片段素材<select data-segment-take id="segment-take-${esc(seg.id)}"><option value="">待选择</option>${takes.map(t=>`<option value="${esc(t.id)}" ${t.id===choice.take_id?'selected':''}>${esc(t.label)}</option>`).join('')}</select></label><label>素材起点 / 秒<input data-segment-trim id="segment-trim-${esc(seg.id)}" type="number" min="0" step="0.001" value="${choice.trim_start||0}" ${seg.kind==='image'?'disabled':''}></label></fieldset>`}).join('')}<button id="save-segment-sources">保存片段选用</button><button id="assemble-shot" ${s.locked?'disabled':''}>拼接为完整镜头备选</button></details>`;
}
function segmentSourceDraft(){return Object.fromEntries([...document.querySelectorAll('[data-segment-source]')].flatMap(card=>{const take=card.querySelector('[data-segment-take]').value;return take?[[card.dataset.segmentSource,{take_id:take,trim_start:Number(card.querySelector('[data-segment-trim]').value)}]]:[]}))}
function hasUnsavedAssembly(){const s=shot();if(!s||!document.querySelector('[data-segment-source]'))return false;const saved=Object.fromEntries(s.preparation.segments.filter(x=>s.segment_sources?.[x.id]).map(x=>[x.id,{take_id:s.segment_sources[x.id].take_id,trim_start:s.segment_sources[x.id].trim_start}]));return JSON.stringify(segmentSourceDraft())!==JSON.stringify(saved)}
function bindSegmentAssembly(s){
 bind('#save-segment-sources',async()=>{
  if(hasUnsavedShot()||hasUnsavedCut())throw Error('请先保存镜头与剪辑修改');
  const sources=segmentSourceDraft(),current=flowStatus().shots.find(x=>x.shot_id===s.id)?.basis;
  const stale=Object.entries(sources).some(([id,choice])=>{const old=s.segment_sources?.[id],t=s.takes.find(x=>x.id===choice.take_id);return (old&&old.basis!==current)||(t?.source!=='import'&&t?.basis!==current)});
  if(stale&&!await confirmAction('部分片段素材来自返工前。请检查画面、角色与对白是否仍适用，确认继续使用这些素材？'))return;
  await productionEdit({action:'bind_segment_sources',shot_id:s.id,sources,acknowledge_stale:stale},{draftFields:[...document.querySelectorAll('[data-segment-take],[data-segment-trim]')].map(el=>el.id)});toast('片段选用已保存');
 });
 bind('#assemble-shot',()=>run('assemble',{shot_id:s.id}));
}
