/* Product flow: visible readiness, local drafts and delivery based on selected media. */
function flowStatus(){return state.readiness?.[pid]?.[eid]||{shots:[],ready_count:0,can_export:false}}
async function openContinuity(){
 const project=p(),episodeId=eid,dialog=$('#continuitydialog');
 const preview=await api('/api/continuity/preview',{project_id:project.id,episode_id:episodeId});
 if(pid!==project.id||eid!==episodeId)return;
 if(!preview.status.requires_confirmation){await refresh();return}
 const {status,before,after,before_carry,after_carry}=preview;
 const upstream=project.episodes.find(e=>e.id===status.upstream_episode_id);
 const labels={events:'剧情事件',knownBy:'人物已知',unresolvedConflicts:'未解冲突',setups:'铺垫',payoffs:'揭晓',relationshipChanges:'关系变化',injuries:'伤势',possessions:'随身物品',locationState:'地点状态',emotionalState:'情绪',cliffhanger:'集尾悬念'};
 const assetNames=new Map(project.assets.map(a=>[a.id,a.name]));
 function stateText(value){
  if(Array.isArray(value))return value.map(stateText).join('\n');
  if(value&&typeof value==='object')return Object.entries(value).map(([k,v])=>`${assetNames.get(k)||'状态'} · ${stateText(v)}`).join('\n');
  return value==null?'':String(value);
 }
 function comparison(label,oldValue,newValue){
  return `<section class="revision-change"><h3>${esc(label)}</h3><div class="revision-columns"><div><span>本集原承接</span><p>${esc(oldValue||'无记录')}</p></div><div><span>上集最新状态</span><p>${esc(newValue||'无记录')}</p></div></div></section>`;
 }
 const changes=Object.entries(labels).filter(([key])=>JSON.stringify(before?.[key])!==JSON.stringify(after?.[key]))
  .map(([key,label])=>comparison(label,stateText(before?.[key]),stateText(after?.[key])));
 const olderShots=new Map((before_carry||[]).flatMap(e=>e.shots.map(s=>[s.id,s])));
 const latestShots=new Map(after_carry.flatMap(e=>e.shots.map(s=>[s.id,s])));
 const episodeTitles=new Map(project.episodes.map(e=>[e.id,e.title]));
 const shotLabels=new Map();
 for(const carry of [...(before_carry||[]),...after_carry])carry.shots.forEach((s,index)=>shotLabels.set(s.id,`${episodeTitles.get(carry.episode_id)||'前集'} · 第 ${index+1} 镜`));
 const outfits=new Map(project.assets.flatMap(a=>a.versions.map((v,index)=>[`${a.id}:${v.id}`,`${v.outfit||v.name}（第 ${index+1} 版）`])));
 function shotState(s){
  return [s?.subject_state,...Object.entries(s?.looks||{}).map(([a,v])=>`${assetNames.get(a)||'角色'} · ${outfits.get(`${a}:${v}`)||'历史造型'}`)].filter(Boolean).join('\n');
 }
 const carryChanges=[...new Set([...olderShots.keys(),...latestShots.keys()])].filter(id=>JSON.stringify(olderShots.get(id))!==JSON.stringify(latestShots.get(id)));
 if(carryChanges.length)changes.push(`<details><summary>镜头状态与造型 · ${carryChanges.length} 处</summary>${carryChanges.map(id=>comparison(shotLabels.get(id),shotState(olderShots.get(id)),shotState(latestShots.get(id)))).join('')}</details>`);
 $('#continuity-note').textContent=status.upstream_pending?'请先确认上集的承接。':`检查「${upstream?.title||'前集'}」带来的变化。确认后，受影响的镜头仍需重新检查制作准备和素材。`;
 $('#continuity-diff').innerHTML=changes.join('')||'<p>人物和剧情状态没有可显示的文字变化。</p>';
 const form=$('#continuity-form'),choice=$('#continuity-choice'),resolution=$('#continuity-resolution'),reason=$('#continuity-reason'),submit=$('#continuity-confirm'),jump=$('#continuity-upstream');
 form.reset();choice.hidden=submit.hidden=status.upstream_pending;
 jump.hidden=!status.upstream_pending||!upstream;
 jump.onclick=()=>{dialog.close();eid=upstream.id;selected=null;render()};
 resolution.onchange=()=>{reason.required=!choice.hidden&&resolution.value==='keep';$('#continuity-reason-label').hidden=!reason.required};
 resolution.onchange();
 let pending=false;
 form.onsubmit=async event=>{
  event.preventDefault();
  if(pending||status.upstream_pending)return;
  pending=submit.disabled=true;
  try{
   await api('/api/continuity/confirm',{project_id:project.id,episode_id:episodeId,revision:preview.revision,digest:preview.digest,resolution:resolution.value,reason:reason.value});
   dialog.close();await refresh();toast('已确认剧集承接');
  }catch(error){toast(error.message)}
  finally{pending=submit.disabled=false}
 };
 dialog.showModal();
}
function go(viewName,shotId){
 if((viewName==='script'?'overview':viewName)===view&&!shotId)return;
 const menu=document.querySelector('.episode-options');if(menu)menu.open=false;
 if(view==='shots'&&viewName==='delivery'&&(hasUnsavedShot()||hasUnsavedCut())){toast('请先保存镜头与剪辑修改，再预览成片');openShotTools(hasUnsavedCut()?'takes':'intent');return}
 const before=view;rememberWorkspaceScroll();
 view=viewName==='script'?'overview':viewName;if(shotId){selected=shotId;shotFilter='all'}render();if(before!==view)transitionWorkspace(before,view);if(shotId&&view==='shots')openShotTools(before==='delivery'&&!(shot()?.image||shot()?.video)?'takes':'intent');
}
function creativeReturnView(){const saved=localStorage.getItem('luma-workspace:'+pid);return workspaceOrder.includes(saved)?saved:'shots'}
function bindFlowLinks(){document.querySelectorAll('[data-flow]').forEach(b=>b.onclick=()=>go(b.dataset.flow,b.dataset.targetShot));}
const activeTaskStates=['queued','running','submitting','waiting_review'];
function currentDeliveryJob(){return state.jobs.find(j=>j.project_id===pid&&j.episode_id===eid&&j.kind==='export')}
function bindMediaPreviews(){
 document.querySelectorAll('video[controls],audio[controls]').forEach(media=>{
  media.tabIndex=0;if(!media.getAttribute('aria-label'))media.setAttribute('aria-label',media.tagName==='VIDEO'?'视频预览':'音轨试听');
 });
}
function episodeExports(){return state.jobs.filter(j=>j.project_id===pid&&j.episode_id===eid&&j.kind==='export'&&j.state==='succeeded').map(j=>({job:j,result:JSON.parse(j.result||'{}')})).filter(x=>x.result.file);}
function briefForm(){const b=p().creative_brief;return `<form id="brief-form"><div class="brief-layout"><div class="two"><label>画幅<select name="format"><option value="16:9" ${b.format==='16:9'?'selected':''}>横屏 · 16:9</option><option value="9:16" ${b.format==='9:16'?'selected':''}>竖屏 · 9:16</option></select></label><label>制作方式<select name="method"><option value="mixed" ${b.method==='mixed'?'selected':''}>混合制作</option><option value="illustrated" ${b.method==='illustrated'?'selected':''}>画面漫剧</option><option value="video" ${b.method==='video'?'selected':''}>视频漫剧</option></select></label></div><label>统一视觉风格<textarea name="style" maxlength="2000" rows="2" placeholder="例如：赛璐璐风格，夜景偏冷色，服装沿用角色参考图。">${esc(b.style)}</textarea></label></div><div class="form-footer"><p class="muted">修改风格或制作方式后，已有镜头需复核。</p><button>保存设定</button></div></form>`}
function clearUnchangedHomeDraft(){const clean=[];if($('#story-draft')?.value===episode().script)clean.push('story-draft');for(const [k,v] of Object.entries(p().creative_brief))if(document.querySelector('#brief-form [name="'+k+'"]')?.value===v)clean.push(k);clearDraft(clean);render()}
function bindBrief(){$('#brief-form').onsubmit=async e=>{e.preventDefault();try{p().creative_brief=Object.fromEntries(new FormData(e.target));await save({draftFields:['format','method','style']});clearUnchangedHomeDraft();toast('创作设定已保存')}catch(err){toast(err.message)}}}
const storySurfaces=new Map();
function setStoryOutlineVisible(visible){
 storySurfaces.set(pid+':'+eid,visible?'outline':'writing');
 document.querySelector('.script-sheet').classList.toggle('has-outline',visible);
 const outline=$('#story-outline');outline.hidden=!visible;outline.open=visible;
 const button=$('#story-outline-view');button.setAttribute('aria-expanded',String(visible));button.textContent=(visible?'收起分镜':'查看分镜')+' '+shots().length;
}
function updateStoryState(){
 const field=$('#story-draft');if(!field)return;
 $('#story-word-count').textContent=field.value.length+' 字';
 $('#save-story').disabled=field.value===episode().script;
 $('#create-story').disabled=!state.spending?.remaining||!field.value.trim();
}
function overview(){
 const items=shots();
 $('#content').innerHTML=`<div class="script-desk"><section class="script-sheet"><div class="script-heading"><div><span class="eyebrow">剧本</span><h2>剧本</h2><div class="page-episode-slot"></div></div><div class="actions"><button id="open-story-settings" class="text-button">${uiIcon('adjustments-horizontal')}制作设定</button><button id="story-outline-view" class="text-button" aria-expanded="false" aria-controls="story-outline">查看分镜 ${items.length}</button><button id="import-story" class="text-button">${uiIcon('upload')}导入文本</button></div><input id="story-file" type="file" accept=".txt,text/plain" hidden></div><form id="story-composer" class="story-composer"><label for="story-draft" class="sr-only">故事内容</label><textarea id="story-draft" placeholder="写下故事，或导入已有剧本…" rows="12">${esc(episode().script)}</textarea><div class="composer-footer"><span id="story-word-count" role="status">${episode().script.length} 字</span><div class="actions"><button type="button" id="save-story">保存剧本</button><button class="primary" id="create-story" ${state.spending?.remaining?'':'disabled'}>拆分镜头 ${uiIcon('arrow-right')}</button></div></div></form><p class="generation-note">${state.spending?.remaining?'根据已保存剧本生成分镜，确认后才进入制作。':'生成已暂停，可继续编辑和保存剧本。'}</p><details id="story-outline" class="story-outline" hidden><summary>本集分镜 <span>${items.length} 镜</span></summary><h3>分镜摘要</h3>${items.map((s,i)=>`<button data-flow="shots" data-target-shot="${esc(s.id)}"><span>${String(i+1).padStart(2,'0')}</span><p>${esc(s.description)}</p><small>${s.duration} 秒</small></button>`).join('')||'<p class="muted">拆分剧本后在这里查看镜头。</p>'}</details></section><dialog id="story-settings-dialog" aria-label="制作设定"><header class="story-settings-heading"><h2>制作设定</h2><button id="close-story-settings" class="icon-button" aria-label="关闭制作设定">${uiIcon('x')}</button></header><section id="creative-settings">${briefForm()}</section></dialog></div>`;
 bind('#story-outline-view',()=>setStoryOutlineVisible(!document.querySelector('.script-sheet').classList.contains('has-outline')));setStoryOutlineVisible(storySurfaces.get(pid+':'+eid)==='outline');
 bind('#open-story-settings',()=>$('#story-settings-dialog').showModal());bind('#close-story-settings',()=>$('#story-settings-dialog').close());
 $('#story-draft').addEventListener('input',updateStoryState);
 bind('#import-story',()=>$('#story-file').click());
 $('#story-file').onchange=async e=>{try{const file=e.target.files[0];if(file){$('#story-draft').value=await file.text();rememberDraft();updateStoryState();toast('剧本已载入，请保存')}}catch(error){toast(error.message)}};
 async function persistStory(){episode().script=$('#story-draft').value;await save({draftFields:['story-draft']});clearUnchangedHomeDraft()}
 bind('#save-story',async()=>{await persistStory();toast('故事已保存')});
 $('#story-composer').onsubmit=async e=>{e.preventDefault();if(!state.spending?.remaining){toast('生成已暂停。可以先保存故事，或到设置中调整生成次数。');return}try{await persistStory();await run('shots')}catch(err){toast(err.message)}};
 bindBrief();
}
function deliveryIsCurrent(result,status){return !!status.can_export&&!!result.review_basis&&result.review_basis===status.review_basis&&result.delivery_basis===status.delivery_basis}
function delivery(){
 const assemblyOpen=document.querySelector('.delivery-assembly')?.open,versionsOpen=document.querySelector('.delivery-versions')?.open;
 const f=flowStatus(),blocked=f.shots.filter(s=>!s.ready),voice=f.shots.filter(s=>s.dialogue_without_audio),exports=episodeExports(),latest=exports[0],b=p().creative_brief,task=currentDeliveryJob(),pending=task&&activeTaskStates.includes(task.state),nextBlocked=blocked[0],nextShot=nextBlocked&&shots().find(s=>s.id===nextBlocked.shot_id),nextNumber=nextShot?shots().indexOf(nextShot)+1:0;
 $('#content').innerHTML=`<div class="toolbar page-heading"><div><div class="delivery-title-row"><h2>成片</h2><div class="page-episode-slot"></div></div><p class="muted">${esc(b.format)} · ${shots().reduce((n,s)=>n+s.duration,0)} 秒 · ${f.ready_count} / ${shots().length} 镜可导出</p></div><button id="delivery-export" class="primary" ${f.can_export&&!pending?'':'disabled'}>${pending?'正在导出…':'导出当前成片'}</button></div>
 ${task?`<p class="delivery-progress" role="status">${pending?'正在合成影片，完成后将在此处显示。':task.state==='failed'?'导出失败：'+esc(task.error||'请检查素材后重试'):task.state==='succeeded'?'影片已导出，可预览或下载。':task.state==='interrupted'?'导出已中断，请在记录中核实。':''}</p>`:''}
 <div class="delivery-layout ${latest?'has-film':'no-film'}"><section class="delivery-stage" aria-label="成片预览">${latest?`<video controls preload="metadata" src="/media/${esc(latest.result.file)}"></video><div class="delivery-preview-caption"><span>${deliveryIsCurrent(latest.result,f)?'当前成片':'历史成片，与当前剪辑可能不同'}</span><a href="/media/${esc(latest.result.file)}" download>下载 MP4</a></div>`:`<div class="delivery-no-film"><h3>${nextShot?'还有 '+blocked.length+' 镜需要完成':!shots().length?'先建立这一集的镜头':f.can_export?'准备导出这一集':'继续检查镜头'}</h3><p>${nextShot?'镜头 '+nextNumber+'：'+esc(nextBlocked.reason||'待完成制作'):shots().length?'完成制作后，在这里预览与下载。':'写下剧本或添加镜头，开始制作。'}</p><button data-flow="shots" ${nextShot?`data-target-shot="${esc(nextShot.id)}"`:''}>${nextShot?'处理镜头 '+nextNumber:shots().length?'查看镜头':'创建镜头'}</button></div>`}</section>
 ${!shots().length?'':blocked.length?`<p class="delivery-list-note">按顺序检查镜头，选中一镜即可继续编辑。</p>`:'<div class="notice">所有镜头已确认，可以导出。</div>'}
 </div><section class="delivery-cut-rail" aria-label="镜头顺序">${shots().map((s,i)=>{const ready=f.shots.find(x=>x.shot_id===s.id);return `<button class="delivery-cut" data-flow="shots" data-target-shot="${esc(s.id)}" aria-label="编辑镜头 ${i+1}：${esc(ready?.ready?'已就绪':ready?.reason||'待制作')}"><span class="delivery-cut-frame">${s.image?`<img alt="" src="/media/${esc(s.image)}">`:s.video?`<video muted preload="metadata" src="/media/${esc(s.video)}#t=0.1"></video>`:`<span>${String(i+1).padStart(2,'0')}</span>`}</span><span class="delivery-cut-copy"><span><strong>镜头 ${i+1}</strong><small>${s.duration} 秒</small></span><span class="delivery-cut-description">${esc(s.description||'还没有画面描述')}</span></span><span class="delivery-cut-state"><em>${esc(ready?.ready?'已就绪':ready?.reason||'待制作')}</em>${uiIcon('arrow-up-right')}</span></button>`}).join('')}</section>${voice.length?`<details class="delivery-audio-note"><summary>${voice.length} 镜尚未选用独立配音</summary><p>${voice.map(s=>`镜头 ${s.number}`).join('、')} 有对白文字，尚未选用独立配音。导出使用视频原声或静音，并保留字幕；如需配音，请回到对应镜头添加音轨。</p></details>`:''}
 <details class="delivery-assembly" ${assemblyOpen?'open':''}><summary>查看镜头与音轨</summary><div class="assembly-list">${shots().map((s,i)=>`<article class="assembly-row"><div class="assembly-frame" style="aspect-ratio:${b.format==='9:16'?'9/16':'16/9'}">${s.video?`<video controls preload="metadata" src="/media/${esc(s.video)}#t=${s.trim_start||0}${s.clip?.trim_end!=null?','+s.clip.trim_end:''}"></video>`:s.image?`<img alt="镜头 ${i+1} 当前画面" src="/media/${esc(s.image)}">`:'<span>还没有画面</span>'}</div><div><h3>镜头 ${i+1} · ${s.duration} 秒</h3><p>${esc(s.description)}</p><p class="muted">${s.video?'视频起点 '+s.trim_start+' 秒'+(s.clip?.trim_end!=null?' · 终点 '+s.clip.trim_end+' 秒':''):s.image?'静态图片画面':'等待画面'} · ${s.lines?.some(l=>l.audio_take_id)?'逐句配音':s.audio?'独立配音':s.video?'视频原声 / 静音':'静音'}</p>${s.audio?`<audio controls preload="none" src="/media/${esc(s.audio)}"></audio>`:''}${(f.shots.find(x=>x.shot_id===s.id)?.audio_schedule||[]).map(x=>`<p>逐句音轨 · ${x.start.toFixed(2)}–${x.end.toFixed(2)} 秒 · ${esc(x.text)}</p><audio controls preload="none" src="/media/${esc(x.file)}"></audio>`).join('')}<p>${s.dialogue?'字幕：'+esc(s.dialogue):'无字幕'}</p><div class="actions"><button data-flow="shots" data-target-shot="${esc(s.id)}">调整素材与时长</button><button data-order="${esc(s.id)}" data-delta="-1" ${i===0?'disabled':''} aria-label="镜头 ${i+1} 前移">前移</button><button data-order="${esc(s.id)}" data-delta="1" ${i===shots().length-1?'disabled':''} aria-label="镜头 ${i+1} 后移">后移</button></div></div></article>`).join('')}</div></details>
 <details class="delivery-versions" ${versionsOpen?'open':''}><summary>已导出的版本</summary><section class="delivery-history"><h2>成片版本</h2>${exports.map(({job,result:r})=>`<article class="delivery-result"><h3>${new Date(job.updated*1000).toLocaleString()} · ${r.duration} 秒</h3><p class="muted">${deliveryIsCurrent(r,f)?'与当前剪辑一致':'历史成片 · 与当前剪辑的一致性未确认'}</p><video controls preload="metadata" src="/media/${esc(r.file)}"></video><p><a href="/media/${esc(r.file)}" download>下载 MP4</a>${r.manifest?` · <a href="/media/${esc(r.manifest)}" download>下载制作清单</a>`:''}</p></article>`).join('')||'<p class="muted">导出后在这里预览和下载。</p>'}</section></details>`;
 bind('#delivery-export',()=>run('export'));document.querySelectorAll('[data-order]').forEach(el=>el.onclick=async()=>{try{selected=el.dataset.order;await move(Number(el.dataset.delta))}catch(e){toast(e.message)}});
}
function draftKey(){return p()?`auteur-draft:${pid}:${eid}:${view}:${view==='shots'?selected||'':''}`:null}
function draftControls(){return [...document.querySelectorAll('#dialogue-lines, #script, #story-draft, [data-key], #refs, #revision-instruction, #cut-source, #cut-start, #cut-end, [data-segment-take], [data-segment-trim], [data-asset], [data-asset-name], #brief-form [name], [data-look-field]')];}
function controlKey(el){return el.id||el.dataset.key||(el.dataset.assetName?'asset-name:'+el.dataset.assetName:el.dataset.asset?'asset:'+el.dataset.asset:el.name)}
function draftValue(el){return el.multiple?[...el.selectedOptions].map(o=>o.value):el.value}
const draftBaselines=new WeakMap();
function sameDraftValue(a,b){return JSON.stringify(a)===JSON.stringify(b)}
function draftCanRestore(draft,key,current){
 if(key==='revision-instruction')return true;
 if(draft.bases&&Object.hasOwn(draft.bases,key))return sameDraftValue(current,draft.bases[key])||sameDraftValue(current,draft.fields[key]);
 return draft.revision===p().revision;
}
function rememberDraft(){
 const key=draftKey();if(!key)return;let previous;try{previous=JSON.parse(localStorage.getItem(key))}catch{}
 const fields={...(previous?.fields||{})},bases={...(previous?.bases||{})};
 for(const el of draftControls()){
  const name=controlKey(el),value=draftValue(el),base=draftBaselines.get(el);
  // A conflicting draft stays untouched until explicitly compared or discarded.
  if(previous?.fields&&Object.hasOwn(previous.fields,name)&&!draftCanRestore(previous,name,base)&&sameDraftValue(value,base))continue;
  if(sameDraftValue(value,base)){delete fields[name];delete bases[name]}else{fields[name]=value;bases[name]=base}
 }
 try{if(Object.keys(fields).length)localStorage.setItem(key,JSON.stringify({revision:p().revision,fields,bases}));else localStorage.removeItem(key);const note=$('#draft-note');if(note&&!Number(note.dataset.conflicts)){note.textContent=Object.keys(fields).length?'未保存 · 草稿已保留':'';note.classList.toggle('idle',!Object.keys(fields).length)}}catch{toast('本机草稿空间不足，请及时保存修改')}
}
function clearDraft(fields,key=draftKey()){if(!key)return;if(fields){let draft;try{draft=JSON.parse(localStorage.getItem(key))}catch{}if(draft){fields.forEach(k=>{delete draft.fields[k];if(draft.bases)delete draft.bases[k]});if(draft.fields['revision-instruction']==='')delete draft.fields['revision-instruction'];if(Object.keys(draft.fields).length){localStorage.setItem(key,JSON.stringify(draft));return}}}localStorage.removeItem(key)}
function displayDraftValue(key,value){
 if(key==='cut-source')return shot()?.takes.find(t=>t.id===value)?.label||'已移除素材';
 if(key==='dialogue-lines'){try{return JSON.parse(value)?.map(l=>l.text).join('\n')||'无对白'}catch{return '无法读取旧对白'}}
 if(key==='refs'&&Array.isArray(value))return value.map(id=>p().assets.find(a=>a.id===id)?.name||'已移除素材').join('、')||'未引用素材';
 if(key==='method')return {mixed:'混合制作',illustrated:'画面漫剧',video:'视频漫剧'}[value]||value;
 return value==null||value===''?'未填写':String(value)+(key==='duration'?' 秒':'');
}
function compareDraft(draft,conflicts){
 const labels={description:'动作与画面',duration:'时长',framing:'景别',camera:'机位与运镜',dialogue:'对白',refs:'引用素材','dialogue-lines':'逐句对白','story-draft':'故事',script:'剧本',format:'画幅',method:'制作方式',style:'视觉风格','cut-source':'剪辑素材','cut-start':'片段起点','cut-end':'片段终点'};
 const dialog=document.createElement('dialog');dialog.className='draft-comparison form-sheet';dialog.setAttribute('aria-label','比较本机草稿');
 dialog.innerHTML='<form method="dialog"><header class="sheet-heading"><h2>比较本机草稿</h2><button type="button" class="icon-button" data-close-sheet aria-label="关闭草稿比较">'+uiIcon('x')+'</button></header><section class="sheet-body"><p>以下草稿没有覆盖当前内容，请比较后选择。</p>'+conflicts.map(({el,key})=>`<section class="revision-change"><h3>${esc(labels[key]||'素材设定')}</h3><div class="revision-columns"><div><span>当前内容</span><p>${esc(displayDraftValue(key,draftBaselines.get(el)))}</p></div><div><span>本机草稿</span><p>${esc(displayDraftValue(key,draft.fields[key]))}</p></div></div></section>`).join('')+'</section><div class="actions"><button value="cancel">稍后处理</button><button value="current">保留当前内容</button><button value="draft" class="primary">恢复为未保存修改</button></div></form>';
 dialog.querySelector('[data-close-sheet]').onclick=()=>dialog.close('cancel');
 dialog.onclose=()=>{if(dialog.returnValue==='current'){clearDraft(conflicts.map(x=>x.key));render()}else if(dialog.returnValue==='draft'){
  draft.bases=draft.bases||{};for(const {el,key} of conflicts)draft.bases[key]=draftBaselines.get(el);
  draft.revision=p().revision;localStorage.setItem(draftKey(),JSON.stringify(draft));render();
 }dialog.remove()};document.body.append(dialog);dialog.showModal();
}
function bindDrafts(){
 const controls=draftControls();if(!controls.length)return;let draft;try{draft=JSON.parse(localStorage.getItem(draftKey()))}catch{}
 const conflicts=[];
 controls.forEach(el=>{const current=el.id==='dialogue-lines'?JSON.stringify(shot().lines??null):draftValue(el),key=controlKey(el);draftBaselines.set(el,current);if(!draft||!Object.hasOwn(draft.fields,key))return;
  if(!draftCanRestore(draft,key,current)){conflicts.push({el,key});return}
  const value=draft.fields[key];if(el.multiple)[...el.options].forEach(o=>o.selected=value.includes(o.value));else el.value=value;
 });
 const note=document.createElement('p');note.id='draft-note';note.className='draft-note'+(draft?'':' idle');note.setAttribute('role','status');note.dataset.conflicts=String(conflicts.length);note.textContent=conflicts.length?'内容已更新，旧草稿未覆盖当前内容':draft?(Object.keys(draft.fields).every(k=>k==='revision-instruction')?'修改要求已保留':'修改已暂存本机，尚未保存到作品'):'';$('#content').prepend(note);
 if(conflicts.length){const compare=document.createElement('button');compare.textContent='比较草稿';compare.onclick=()=>{const latest=JSON.parse(localStorage.getItem(draftKey()));const pending=controls.map(el=>({el,key:controlKey(el)})).filter(({el,key})=>latest&&Object.hasOwn(latest.fields,key)&&!draftCanRestore(latest,key,draftBaselines.get(el)));if(pending.length)compareDraft(latest,pending);else render()};note.append(' ',compare)}
 if(draft){const discard=document.createElement('button');discard.textContent='放弃草稿';discard.onclick=()=>{clearDraft();render()};note.append(' ',discard)}
 controls.forEach(el=>{el.addEventListener('input',rememberDraft);if(el.tagName==='SELECT')el.addEventListener('change',rememberDraft)});
 if($('#story-word-count')&&$('#story-draft'))$('#story-word-count').textContent=$('#story-draft').value.length+' 字';
}

function render(){
 const context=$('#episodebar'),home=document.querySelector('.project-bar');if(context&&home&&!home.contains(context))home.append(context);
 document.body.dataset.view=view;renderContents();
 const working=!!p()&&!['library','jobs','settings'].includes(view);
 document.querySelector('.project-bar').hidden=true;document.querySelector('.workspace-tabs').hidden=!working;const showContext=working&&view!=='assets';$('#episodebar').hidden=!showContext;if(showContext&&view!=='shots')document.querySelector('.page-episode-slot')?.append($('#episodebar'));document.querySelector('.project-switch').hidden=!p()||['library','settings'].includes(view);
 for(const [id,active] of [['open-story',['overview','script'].includes(view)],['open-shots',view==='shots'],['open-assets',view==='assets'],['open-delivery',view==='delivery']]){const b=document.getElementById(id);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')}
 if(view==='overview'&&p()){
  const oldKey=`auteur-draft:${pid}:${eid}:script:`,key=draftKey();
  if(!localStorage.getItem(key)){try{const old=JSON.parse(localStorage.getItem(oldKey));if(old?.fields?.script!==undefined){old.fields['story-draft']=old.fields.script;delete old.fields.script;if(old.bases?.script!==undefined){old.bases['story-draft']=old.bases.script;delete old.bases.script}localStorage.setItem(key,JSON.stringify(old));localStorage.removeItem(oldKey)}}catch{}}
 }
 bindFlowLinks();bindDrafts();bindReferenceChoices();syncCutFields();updateStoryState();updateAssetSaveState();updateShotSaveState();
 if(view==='shots'&&shot())localStorage.setItem(`auteur-shot:${pid}:${eid}`,selected);
 if(p()){localStorage.setItem('auteur-view',view);document.documentElement.style.setProperty('--frame-ratio',p().creative_brief.format==='9:16'?'9/16':'16/9')}
 document.querySelectorAll('#nav button').forEach(b=>{const active=b.dataset.view===view;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
 bindCanvasShell();bindMediaPreviews();renderNavigation();
}
