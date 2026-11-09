/* The editor keeps saved shot intent, candidate media and revision requests distinct. */
let shotToolTab='intent',shotFilter='all';
function linesForEditor(s){
 try{const d=JSON.parse(localStorage.getItem(draftKey()));if(d?.fields['dialogue-lines']!==undefined&&draftCanRestore(d,'dialogue-lines',JSON.stringify(s.lines??null)))return JSON.parse(d.fields['dialogue-lines'])}catch{}
 return s.lines??null;
}
function linesEditor(s){
 const lines=linesForEditor(s),chars=p().assets.filter(a=>a.kind==='character');
 return `<fieldset class="lines" ${s.locked?'disabled':''}><legend>逐句对白</legend>${lines.map((l,i)=>`<div class="line-row" data-line-id="${esc(l.id)}"><label>说话人<select data-line-speaker="${i}"><option value="">旁白</option>${chars.map(a=>`<option value="${esc(a.id)}" ${l.speaker_asset_id===a.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label><label>台词<textarea data-line-text="${i}" rows="2" placeholder="输入这一句对白…">${esc(l.text)}</textarea></label><button data-line-del="${i}" aria-label="删除第 ${i+1} 句">删除</button>${lineAudioControls(s,l)}</div>`).join('')}<div class="actions"><button id="line-add">添加一句</button></div><details class="help-disclosure"><summary>字幕时间如何安排？</summary><p>已选音轨按实际时长安排；未选音轨按字数估算，不自动对齐语音。</p></details></fieldset>`;
}
function readLines(){
 const field=$('#dialogue-lines');if(!field||JSON.parse(field.value)===null)return null;
 return [...document.querySelectorAll('[data-line-id]')].map(el=>({...((JSON.parse(field.value)||[]).find(l=>l.id===el.dataset.lineId)||{}),id:el.dataset.lineId,speaker_asset_id:el.querySelector('[data-line-speaker]').value||null,text:el.querySelector('[data-line-text]').value}));
}
function bindLines(s){
 const stage=(lines,index)=>{$('#dialogue-lines').value=JSON.stringify(lines);rememberDraft();render();requestAnimationFrame(()=>{const fields=document.querySelectorAll('[data-line-text]');(fields[Math.min(index,fields.length-1)]||$('#line-add'))?.focus()})};
 bind('#lines-start',()=>stage([{id:crypto.randomUUID(),speaker_asset_id:null,text:$('[data-key=dialogue]')?.value||s.dialogue||''}],0));
 bind('#line-add',()=>{const lines=readLines();stage([...lines,{id:crypto.randomUUID(),speaker_asset_id:null,text:''}],lines.length)});
 document.querySelectorAll('[data-line-del]').forEach(b=>b.onclick=()=>{const index=Number(b.dataset.lineDel),lines=readLines().filter((_,i)=>i!==index);stage(lines,index)});
 document.querySelectorAll('[data-line-text],[data-line-speaker]').forEach(el=>el.addEventListener('input',()=>{$('#dialogue-lines').value=JSON.stringify(readLines());rememberDraft()}));
}
function hasUnsavedShot(){const s=shot();if(!s||!$('#shot-tools'))return false;return JSON.stringify(readLines())!==JSON.stringify(s.lines??null)||[...document.querySelectorAll('[data-key]')].some(el=>String(el.type==='number'?Number(el.value):el.value)!==String(s[el.dataset.key]??(el.type==='number'?0:'')))||($('#refs')&&JSON.stringify([...$('#refs').selectedOptions].map(o=>o.value).sort())!==JSON.stringify([...s.asset_ids].sort()))}
function bindShotTabs(){
 const tabs=[...document.querySelectorAll('[data-shot-tab]')];
 function activate(name,focus=false){shotToolTab=name;const surface=document.querySelector('#shot-tools');if(surface?.dataset)surface.dataset.panel=name;tabs.forEach(t=>{const active=t.dataset.shotTab===name;t.setAttribute('aria-selected',String(active));t.tabIndex=active?0:-1;if(active&&focus)t.focus()});document.querySelectorAll('[data-editor-panel]').forEach(panel=>panel.hidden=panel.dataset.editorPanel!==name);const footer=document.querySelector('.editor-actions');if(footer)footer.hidden=name==='takes'||(name==='intent'&&typeof shotIntentMode!=='undefined'&&shotIntentMode==='revision')}
 tabs.forEach((t,i)=>{t.onclick=()=>activate(t.dataset.shotTab);t.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;activate(tabs[n].dataset.shotTab,true)}}});activate(shotToolTab);
}
function shotToolsMarkup(s){
 if(!s)return '';
 return `<dialog id="shot-tools" data-context="${esc([pid,eid,s.id].join(':'))}" aria-label="镜头编辑与素材">
 <div class="tools-dialog-top"><div class="editor-tabs" role="tablist" aria-label="镜头编辑分区">${[['intent','画面'],['dialogue','对白'],['takes','素材']].map(([id,name])=>`<button id="tab-${id}" role="tab" data-shot-tab="${id}" aria-controls="panel-${id}">${name}</button>`).join('')}</div><button id="history" class="icon-button composer-history" type="button" aria-label="作品历史版本" title="作品历史版本">${uiIcon('history')}</button><span id="shot-save-state" role="status">${s.locked?'已锁定':'已保存'}</span></div>
 <div class="shot-editor">
 <div class="editor-panels"><section id="panel-intent" role="tabpanel" aria-labelledby="tab-intent" data-editor-panel="intent"><div class="composer-context"><div class="intent-modes" role="group" aria-label="创作方式"><button type="button" data-intent-mode="setup" aria-pressed="${shotIntentMode==='setup'}">画面设定</button><button type="button" data-intent-mode="revision" aria-pressed="${shotIntentMode==='revision'}">局部修改</button></div>${referenceTrayMarkup(s)}</div>
 <section data-intent-panel="setup"><label class="prompt-label"><span>画面描述</span><textarea data-key="description" ${s.locked?'disabled':''} placeholder="描述人物、动作和这一镜要表达的情绪…">${esc(s.description)}</textarea></label><div class="parameter-row"><button type="button" data-parameter-popover="duration-popover" class="parameter-chip" ${s.locked?'disabled':''}>${uiIcon('movie')}<span id="duration-chip-label">${s.duration} 秒</span></button><button type="button" data-parameter-popover="framing-popover" class="parameter-chip" ${s.locked?'disabled':''}>${uiIcon('maximize')}<span id="framing-chip-label">${esc(s.framing||'景别')}</span></button><button type="button" data-parameter-popover="camera-popover" class="parameter-chip camera-chip" ${s.locked?'disabled':''}>${uiIcon('adjustments-horizontal')}<span id="camera-chip-label">${esc(s.camera||'运镜')}</span></button></div>
 <div id="duration-popover" class="picker-menu parameter-popover" popover="auto" role="dialog" aria-label="镜头时长"><label>镜头时长 / 秒<input data-key="duration" type="number" min="1" max="60" step="0.1" value="${s.duration}" ${s.locked?'disabled':''}></label><button type="button" data-close-parameter>完成</button></div>
 <div id="framing-popover" class="picker-menu parameter-popover" popover="auto" role="dialog" aria-label="镜头景别"><label>景别<input data-key="framing" value="${esc(s.framing||'')}" ${s.locked?'disabled':''} placeholder="例如：中景、近景、特写"></label><button type="button" data-close-parameter>完成</button></div>
 <div id="camera-popover" class="picker-menu parameter-popover" popover="auto" role="dialog" aria-label="机位与运镜"><label>机位与运镜<input data-key="camera" value="${esc(s.camera||'')}" ${s.locked?'disabled':''}></label><button type="button" data-close-parameter>完成</button></div>
 <details class="reference-details" data-disclosure="references"><summary>更多设定</summary><div class="composer-details-body"><div class="shot-order"><button id="left" class="icon-button" aria-label="镜头前移" ${shots().indexOf(s)===0?'disabled':''}>${uiIcon('chevron-left')}</button><button id="right" class="icon-button" aria-label="镜头后移" ${shots().indexOf(s)===shots().length-1?'disabled':''}>${uiIcon('chevron-right')}</button><button id="lock" class="text-button">${s.locked?'解除锁定':'锁定'}</button></div>${productionReferences(s)}</div></details></section>
 <button type="button" id="open-preparation">制作准备</button>${creativeShotDetails(s)}${shotRevisionControls(s)}</section>
 <section id="panel-dialogue" role="tabpanel" aria-labelledby="tab-dialogue" data-editor-panel="dialogue" hidden><input id="dialogue-lines" type="hidden" value="${esc(JSON.stringify(linesForEditor(s)))}">${linesForEditor(s)!==null?linesEditor(s):`<label class="prompt-label"><span>对白与字幕</span><textarea data-key="dialogue" ${s.locked?'disabled':''} placeholder="写下这一镜的对白或旁白…">${esc(s.dialogue||'')}</textarea></label><button id="lines-start" class="text-button" ${s.locked?'disabled':''}>逐句编辑</button>`}</section>${takesPanel(s)}</div>
 <div class="editor-actions"><button id="save-shot" class="primary" ${s.locked?'disabled':''}>保存镜头</button><button id="approve" ${s.locked||(s.approved&&!s.needs_review)?'disabled':''}>${s.approved&&!s.needs_review?'已确认':'确认这一镜'}</button></div></div>
 </dialog><dialog id="versions-dialog" class="versions-dialog" aria-labelledby="versions-title"><header><div><h2 id="versions-title">作品历史版本</h2><p>${esc(p().title)} · 恢复会影响整个作品</p></div><button id="close-versions" class="icon-button" aria-label="关闭历史版本">${uiIcon('x')}</button></header><div id="versions" aria-live="polite"></div></dialog>`;
}
const shotDraftFields=['description','duration','framing','camera','dialogue','trim_start','refs','dialogue-lines'];
async function saveShotEdits(){
 const s=shot();if(!s||s.locked)throw Error('请先解除镜头锁定');
 const lines=readLines();if(lines!==null)s.lines=lines;else delete s.lines;
 document.querySelectorAll('[data-key]').forEach(el=>s[el.dataset.key]=el.type==='number'?Number(el.value):el.value);
 s.asset_ids=[...$('#refs').selectedOptions].map(o=>o.value);
 await save({draftFields:shotDraftFields});toast('镜头已保存');
}
async function approveShot(){
 const s=shot();if(!s||s.locked)throw Error('请先解除镜头锁定');
 if(hasUnsavedShot())throw Error('请先保存镜头修改，再确认审核');
 if(hasUnsavedCut())throw Error('请先到素材中保存剪辑片段，再确认审核');
 s.approved=true;s.needs_review=false;await save();toast('镜头已确认');
}
function updateShotSaveState(){
 const host=$('#shot-save-state');if(!host)return;
 host.textContent=hasUnsavedShot()?'有未保存修改':hasUnsavedCut()?'剪辑片段尚未保存':shot()?.locked?'已锁定':'已保存';
 $('#save-shot').disabled=!!shot()?.locked||!hasUnsavedShot();
 if(typeof updateCreationSummaries==='function')updateCreationSummaries();
}
function bindShotEditor(s){
 if(!s)return;
 bind('#open-preparation',()=>openPreparation(s.id));
 if(s.locked)document.querySelectorAll('[data-key]').forEach(el=>el.disabled=true);
 bind('#save-shot',saveShotEdits);bind('#approve',approveShot);
 bind('#lock',async()=>{if(hasUnsavedShot()||hasUnsavedCut())throw Error('请先保存镜头与剪辑修改，再调整锁定');s.locked=!s.locked;await save()});
 bind('#left',()=>move(-1));bind('#right',()=>move(1));
 bindProductionShot(s);bindShotTabs();
 const dialog=$('#shot-tools');
 dialog.addEventListener('input',updateShotSaveState);dialog.addEventListener('change',updateShotSaveState);
 dialog.addEventListener('keydown',e=>{if(e.defaultPrevented)return;if(e.key==='Escape'&&dialog.dataset.docked==='true'&&!document.querySelector('.picker-menu:popover-open')){e.preventDefault();document.querySelector('.sequence-shot.is-current')?.focus();return}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if(hasUnsavedShot())saveShotEdits().catch(error=>toast(error.message))}});
 bind('#close-versions',()=>$('#versions-dialog').close());
 bind('#history',async()=>{const dialog=$('#versions-dialog');$('#versions').textContent='正在读取历史版本…';dialog.showModal();let list;try{list=await api('/api/versions/'+pid)}catch(error){dialog.close();throw error}if(!dialog.isConnected)return;$('#versions').innerHTML=list.map(v=>`<div class="version-row"><span><strong>版本 ${v.project.revision}<small>${v.project.shots.length} 镜</small></strong><time>${new Date(v.created*1000).toLocaleString()}</time></span><button class="text-button" data-restore="${v.id}" aria-label="恢复作品到版本 ${v.project.revision}">恢复</button></div>`).join('')||'<p>还没有历史版本</p>';document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{if(!await confirmAction('恢复整个作品到该版本？当前设定仍保存在历史中。'))return;try{const old=list.find(v=>v.id===b.dataset.restore).project;old.revision=p().revision;state.projects=state.projects.map(x=>x.id===pid?old:x);await save()}catch(e){toast(e.message)}})});
}

function bindReferenceChoices(){
 const select=$('#refs');if(!select)return;
 document.querySelectorAll('[data-toggle-reference]').forEach(button=>{
  const option=[...select.options].find(o=>o.value===button.dataset.toggleReference);
  button.setAttribute('aria-pressed',String(option.selected));
  button.onclick=()=>{option.selected=!option.selected;button.setAttribute('aria-pressed',String(option.selected));rememberDraft();updateShotSaveState()};
 });
}

function shotRevisionControls(s){
 return `<section class="revision-assistant" data-intent-panel="revision" hidden><label class="prompt-label" for="revision-instruction"><span>修改要求</span><textarea id="revision-instruction" rows="7" ${s.locked?'disabled':''} placeholder="改成近景，人物和对白保持不变。"></textarea></label><p class="revision-status">${s.locked?'请先解除镜头锁定。':!state.dify.revision?'修改服务尚未连接。':!state.spending?.remaining?'生成已暂停，修改要求会保留在草稿中。':'先生成建议，再比较并确认修改。'}</p><button id="revise-shot" class="primary" ${s.locked||!state.dify.revision||!state.spending?.remaining?'disabled':''}>${uiIcon('arrow-up-right')}生成修改建议</button></section>`;
}
