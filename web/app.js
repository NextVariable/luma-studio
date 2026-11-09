const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state={projects:[],jobs:[],dify:{}},pid=localStorage.getItem('auteur-project'),view=localStorage.getItem('auteur-view')||'library',selected=null,eid=null;
if(!['library','overview','script','assets','shots','delivery','jobs','settings'].includes(view))view='library';
if(localStorage.getItem('luma-layout-version')!=='canvas-v1'){view='library';localStorage.setItem('luma-layout-version','canvas-v1')}
const kinds={script:'剧本解析',assets:'角色与场景设计',shots:'导演分镜',revision:'镜头修改',image:'镜头画面生成',video:'镜头视频生成',audio:'对白配音',plan:'生成规划',qc:'素材质检',assemble:'片段拼接',export:'成片导出'},statuses={queued:'等待执行',running:'执行中',succeeded:'已完成',failed:'失败',cancelled:'已取消',interrupted:'中断，待核实',waiting_review:'等待创作审批',submitting:'提交审批中',blocked:'需要修改 / 补充'};
function toast(t){
 clearTimeout(window.tt);const globalNotice=$('#toast');globalNotice.style.display='none';
 const dialog=[...document.querySelectorAll('dialog[open]:not([data-docked=true])')].at(-1);
 if(dialog){let notice=dialog.querySelector('.dialog-feedback');if(!notice){notice=document.createElement('p');notice.className='dialog-feedback';notice.setAttribute('role','status');dialog.prepend(notice)}notice.textContent=t;window.tt=setTimeout(()=>notice.remove(),5000)}
 else{globalNotice.textContent=t;globalNotice.style.display='block';window.tt=setTimeout(()=>globalNotice.style.display='none',5000)}
}
async function api(path,body){let r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Auteur':'studio'},body:JSON.stringify(body)});let d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d}
function p(){return state.projects.find(x=>x.id===pid)}
async function refresh(draw=true){state=await api('/api/state');if(!p())pid=state.projects[0]?.id;if(draw)render()}
async function save(options={}){let current=p(),savedDraftKey=draftKey();try{let result=await api('/api/save',{project:current,revision:current.revision});state.projects=state.projects.map(x=>x.id===current.id?result:x);if(options.clearDraft)clearDraft(undefined,savedDraftKey);else if(options.draftFields)clearDraft(options.draftFields,savedDraftKey);await refresh(false);render();return result}catch(e){await refresh();throw e}}
function episode(){return p()?.episodes.find(e=>e.id===eid)}
function shots(){return p()?.shots.filter(s=>s.episode_id===eid)||[]}
function shot(){return shots().find(s=>s.id===selected)}
function reorderEpisode(next){let i=0;p().shots=p().shots.map(s=>s.episode_id===eid?next[i++]:s)}
const adoptActions={new:'新增',update:'更新文字',keep:'保留',skip_locked:'已锁定，跳过',remove:'移除'};
const adoptNotes={append:'现有镜头原样保留，方案镜头加在后面，全部标为待复核。',merge:'方案第 N 镜更新现有第 N 镜的文字，镜头编号、素材候选、已选画面和素材版本都保留，改动的镜头标为待复核；锁定的镜头跳过。',replace:'本集现有镜头被方案替换，旧镜头不再属于作品，但可在作品历史版本中找回。只在没有素材候选且没有锁定镜头时可用。'};
async function chooseAdoption(job){
 const dialog=$('#adoptdialog'),select=$('#adopt-mode'),list=$('#adopt-list'),blocked=$('#adopt-blocked'),ok=$('#adopt-confirm');
 async function load(){
  $('#adopt-note').textContent=adoptNotes[select.value];ok.disabled=true;
  try{const r=await api('/api/apply-preview',{project_id:pid,job_id:job.id,revision:p().revision,mode:select.value});
   list.innerHTML=r.items.map(x=>`<li><span class="pill">${adoptActions[x.action]}</span> ${esc((x.description||x.old_description||'').slice(0,40))}${x.action==='update'?` <span class="muted">← ${esc(x.old_description.slice(0,24))}</span>`:''}</li>`).join('');
   blocked.hidden=!r.blocked;blocked.textContent=r.blocked||'';ok.disabled=!!r.blocked;
  }catch(e){list.innerHTML='';blocked.hidden=false;blocked.textContent=e.message}
 }
 select.value='append';select.onchange=load;dialog.returnValue='cancel';await load();
 return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='confirm'?select.value:null);dialog.showModal()});
}
async function chooseRevision(job){
 if(view==='shots'&&(hasUnsavedShot()||hasUnsavedCut()))throw Error('请先保存镜头修改，再查看方案');
 const preview=await api('/api/revision-preview',{project_id:pid,job_id:job.id,revision:p().revision}),dialog=$('#revisiondialog');
 const labels={description:'画面',duration:'时长',framing:'景别',camera:'镜头运动',dialogue:'对白',lines:'逐句对白',asset_ids:'使用的素材',creative_spec:'创作设定'};
 function display(field,value){if(value==null||value==='')return '未填写';if(field==='creative_spec'){const names={narrativePurpose:'叙事目的',action:'动作',durationSec:'时长',shotSize:'景别',cameraMovement:'运镜',cameraAngle:'角度',cameraPosition:'机位',composition:'构图',lighting:'光照',subjectState:'人物状态',emotion:'情绪',sound:'声音',continuityIn:'入镜状态',continuityOut:'出镜状态'};return Object.entries(names).filter(([k])=>value[k]!=null).map(([k,label])=>label+'：'+value[k]).join('\n')};if(field==='asset_ids')return value.map(id=>p().assets.find(a=>a.id===id)?.name||id).join('、')||'无';if(field==='lines')return value.map(l=>`${p().assets.find(a=>a.id===l.speaker_asset_id)?.name||'旁白'}：${l.text}`).join('\n');return String(value)+(field==='duration'?' 秒':'')}
 $('#revision-title').textContent=`镜头 ${preview.number} · 修改前后`;
 $('#revision-note').textContent=[preview.instruction,...(preview.effects||[])].filter(Boolean).join('；');
 $('#revision-diff').innerHTML=preview.changes.map(c=>`<section class="revision-change"><h3>${esc(labels[c.field]||c.field)}</h3><div class="revision-columns"><div><span>修改前</span><p>${esc(display(c.field,c.before))}</p></div><div><span>修改后</span><p>${esc(display(c.field,c.after))}</p></div></div></section>`).join('')||'<p>这份方案没有改变当前内容。</p>';
 dialog.returnValue='cancel';return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='confirm'?preview:null);dialog.showModal()});
}
function confirmAction(message){const dialog=$('#confirmdialog'),action=message.startsWith('恢复')?['恢复作品版本','恢复此版本']:message.includes('授权最多')?['设置生成上限','应用上限']:message.includes('仍然采用')?['采用素材','采用此素材']:['确认操作','确认'];$('#confirm-title').textContent=action[0];dialog.querySelector('[value=confirm]').textContent=action[1];$('#confirm-message').textContent=message;dialog.returnValue='cancel';return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='confirm');dialog.showModal()})}
function bind(id,fn){const el=$(id);if(!el)return;let pending=false;el.onclick=async()=>{if(pending)return;pending=true;const disabled=el.disabled;el.disabled=true;try{await fn()}catch(error){toast(error.message)}finally{pending=false;if(el.isConnected)el.disabled=disabled}}}
function input(label,key,value,type='text'){return `<label>${label}<input data-key="${key}" type="${type}" value="${esc(value)}" ${type==='number'?'min="0" max="86400"':''}></label>`}
function renderContents(){
 if(view==='script')view='overview';
 if(p()&&!p().episodes.some(e=>e.id===eid))eid=p().episodes.find(e=>e.id===localStorage.getItem('auteur-episode-'+pid))?.id||p().episodes[0].id;
 if(eid&&p()){localStorage.setItem('auteur-episode-'+pid,eid);if(!shot()){const remembered=localStorage.getItem(`auteur-shot:${pid}:${eid}`);if(shots().some(s=>s.id===remembered))selected=remembered}}
 $('#episodebar').hidden=!p();
 if(p()){$('#episodes').innerHTML=p().episodes.map(e=>`<option value="${esc(e.id)}" ${e.id===eid?'selected':''}>${esc(e.title)}</option>`).join('');$('#episode-summary').textContent=`${shots().length} 镜 · ${shots().reduce((n,s)=>n+s.duration,0)} 秒`;}
 const continuityButton=$('#episode-continuity');
 if(continuityButton)continuityButton.hidden=!flowStatus().continuity?.requires_confirmation;
 $('#projects').innerHTML=state.projects.length?state.projects.map(x=>`<option value="${x.id}" ${x.id===pid?'selected':''}>${esc(x.title)}</option>`).join(''):'<option>还没有作品</option>';
 $('#title').textContent=p()?.title||'从一个故事开始';
 $('#connection').textContent=state.spending?.remaining?`可生成 ${state.spending.remaining} 次`:'生成已暂停';
 $('#jobcount').textContent=state.jobs.filter(j=>j.project_id===pid&&['queued','running','waiting_review','submitting'].includes(j.state)).length;$('#jobcount').hidden=Number($('#jobcount').textContent)===0;
 document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
 if(view==='library'){projectLibrary();return}
 if(view==='settings'){settings();return}
 if(!p()){view='library';projectLibrary();return}
 localStorage.setItem('auteur-project',pid);
 const screens={overview,shots:drawShots,assets:drawAssets,delivery,jobs};
 (screens[view]||overview)();
}

async function addShot(){
 const project=p(),ep=episode();
 if(hasUnsavedShot()||hasUnsavedCut()||hasUnsavedAssembly())throw Error('请先保存当前镜头修改');
 async function submit(fields){
  const result=await api('/api/shots',{project_id:project.id,episode_id:ep.id,revision:project.revision,fields});
  selected=result.shot_id;shotFilter='all';await refresh();openShotTools('intent');
 }
 const strict=project.creative_context||project.episodes.some(e=>e.creative_spec)||project.shots.some(s=>s.creative_spec);
 if(!strict){await submit({});return}
 const scenes=ep.creative_spec?.screenplay?.scenes||[],subjects=project.assets.filter(a=>['character','scene','prop'].includes(a.kind)),locations=project.assets.filter(a=>a.kind==='scene');
 if(!subjects.length||!locations.length)throw Error('请先在素材中建立镜头主体和场景');
 const dialog=document.createElement('dialog');dialog.className='form-sheet';dialog.setAttribute('aria-label','添加镜头');
 const options=items=>items.map(a=>`<option value="${esc(a.id)}">${esc(a.name||a.id)}</option>`).join('');
 dialog.innerHTML=`<form><header class="sheet-heading"><h2>添加镜头</h2><button type="button" class="icon-button" aria-label="关闭窗口">×</button></header><section class="sheet-body">
 <label>所属场景${scenes.length?`<select name="scene_id">${options(scenes.map(s=>({id:s.id,name:s.id+' · '+(project.assets.find(a=>a.id===s.location)?.name||'场景')})))}</select>`:'<input name="scene_id" required placeholder="例如：码头夜景">'}
 </label>${scenes.length?'':`<label>地点<select name="location_id">${options(locations)}</select></label>`}
 <label>画面主体<select name="subject_id">${options(subjects)}</select></label>
 <label data-outfit>角色造型<select name="version_id"></select></label>
 <label>这一镜要表达什么<input name="purpose" required maxlength="500"></label>
 <label>动作与画面<textarea name="description" required rows="3" maxlength="5000"></textarea></label>
 <label>时长（秒）<input name="duration" type="number" min="1" max="60" step="0.5" value="5" required></label>
 <p class="muted">新镜头将在本集末尾加入，保存后可继续设置构图、对白和素材。</p>
 </section><footer class="form-footer"><button type="submit">添加镜头</button></footer></form>`;
 document.body.append(dialog);dialog.querySelector('[aria-label="关闭窗口"]').onclick=()=>dialog.close();
 dialog.onclose=()=>dialog.remove();
 const form=dialog.querySelector('form'),subject=form.elements.subject_id,version=form.elements.version_id;
 const syncOutfit=()=>{const a=subjects.find(a=>a.id===subject.value);dialog.querySelector('[data-outfit]').hidden=a.kind!=='character';version.required=a.kind==='character';version.innerHTML=options(a.versions.filter(v=>v.outfit).map(v=>({id:v.id,name:v.outfit+' · '+v.name})));};
 subject.onchange=syncOutfit;syncOutfit();
 let pending=false;
 form.onsubmit=async event=>{event.preventDefault();if(pending)return;pending=true;const button=form.querySelector('[type=submit]');button.disabled=true;
  try{const fields=Object.fromEntries(new FormData(form));fields.duration=Number(fields.duration);await submit(fields);dialog.close()}
  catch(error){toast(error.message)}finally{pending=false;button.disabled=false}
 };
 dialog.showModal();
}
async function move(n){let i=shots().findIndex(x=>x.id===selected),j=i+n;if(j<0||j>=shots().length)return;let next=shots();[next[i],next[j]]=[next[j],next[i]];reorderEpisode(next);await save()}
async function run(kind,extra={}){if(!p())return;if(typeof hasUnsavedAssembly==='function'&&hasUnsavedAssembly()){toast('请先保存片段选用');return}if(view==='shots'&&(hasUnsavedShot()||hasUnsavedCut())){toast('请先保存镜头修改，再发起制作');return}if(!['export','assemble'].includes(kind)&&!state.spending?.remaining){toast('生成已暂停，请先在设置中调整生成次数。');return}if(!['export','assemble'].includes(kind)&&!state.dify[kind]){toast('这项功能还未连接服务，请到设置中检查。');return}if(!await confirmAction(`${kinds[kind]}将使用当前已保存的「${episode().title}」${kind==='export'?'与素材生成 MP4':kind==='assemble'?'在本机拼接已有片段，不消耗模型额度':'调用 Dify，可能消耗模型额度'}，是否开始？`))return;await api('/api/jobs',{project_id:pid,episode_id:eid,kind,...extra,nonce:crypto.randomUUID()});if(kind==='revision')clearDraft(['revision-instruction']);const stayOnCanvas=view==='shots'&&['revision','image','video','audio','assemble'].includes(kind),stayOnDelivery=kind==='export'&&view==='delivery';if(!stayOnCanvas&&!stayOnDelivery)view='jobs';await refresh();toast(stayOnDelivery?'正在导出，完成后会在这里显示':stayOnCanvas?'任务已提交，结果会显示在当前画布':'任务已提交')}
const reviewDrafts={};
let jobScope='episode',jobStatus='all',jobQuery='',settingsSection='appearance';
function matchesJobStatus(job,status){return status==='active'?['queued','running','submitting'].includes(job.state):status==='attention'?['waiting_review','failed','blocked','interrupted'].includes(job.state):status==='done'?job.state==='succeeded':true}
function reviewContent(content){
 let text=String(content||'请到 Dify 查看审批内容'),plan;
 try{plan=JSON.parse(text.slice(text.indexOf('{'),text.lastIndexOf('}')+1))}catch{}
 if(!Array.isArray(plan?.shots)||!plan.shots.length)return `<pre class="review-content">${esc(text)}</pre>`;
 return `<div class="review-content"><p><strong>${plan.shots.length} 个镜头 · ${esc(plan.seconds??plan.shots.reduce((n,s)=>n+Number(s.duration||0),0))} 秒</strong></p>${plan.shots.map((s,i)=>`<section class="review-shot"><h4>镜头 ${i+1} · ${esc(s.duration)} 秒 · ${esc(s.framing)}</h4><p>${esc(s.description)}</p><p class="muted">运镜：${esc(s.camera)}</p>${s.dialogue?`<p>对白：${esc(s.dialogue)}</p>`:''}<p class="muted">引用：${(s.asset_ids||[]).map(id=>esc(p().assets.find(a=>a.id===id)?.name||id)).join('、')||'无'}</p></section>`).join('')}</div>`;
}
function reviewPanel(j,r){
 const form=r.form||{},inputs=form.inputs||[],supported=inputs.length<=1&&inputs.every(f=>f.type==='paragraph'),stale=j.fresh===false;
 return `<div class="notice">${stale?'作品已变化，不能批准旧方案。请检查远程运行，或基于当前版本重新规划。':'请审核当前方案。通过只代表创作方案通过，不会自动发起媒体生成。'}</div>${reviewContent(form.form_content)}<label>修改意见<textarea data-review-notes="${esc(j.id)}" rows="4" placeholder="例如：第三镜改近景，保留人物和台词。">${esc(reviewDrafts[j.id+':'+r.review_id]||'')}</textarea></label><div class="actions">${(form.user_actions||[]).map(a=>`<button data-review="${esc(j.id)}" data-action="${esc(a.id)}" ${!supported||stale||!r.review_id?'disabled':''}>${esc(a.title||a.id)}</button>`).join('')}</div>${!supported?'<p>此表单包含当前工作室不支持的输入，请到 Dify 处理后核实状态。</p>':''}`;
}
function jobs(){
 const expanded=new Set([...document.querySelectorAll('details[data-job-output][open]')].map(el=>el.dataset.jobOutput));
 const allJobs=state.jobs.filter(j=>j.project_id===pid&&(jobScope==='project'||j.episode_id===eid||!j.episode_id));let list=allJobs.filter(j=>matchesJobStatus(j,jobStatus));
 $('#content').innerHTML=`<div class="toolbar page-heading"><div><h2>生成记录</h2><p class="muted">${esc(p().title)} · ${esc(episode().title)}</p></div><div class="actions"><button class="text-button" data-flow="${creativeReturnView()}">返回制作 ↗</button><select id="job-scope" aria-label="任务范围"><option value="episode" ${jobScope==='episode'?'selected':''}>当前剧集</option><option value="project" ${jobScope==='project'?'selected':''}>整部作品</option></select><button id="refresh">刷新状态</button><details class="job-tools"><summary>制作工具</summary><div><button id="qc">检查素材</button><button id="genplan">规划生成</button></div></details></div></div><div class="collection-toolbar"><label class="collection-search">搜索记录<input id="job-search" type="search" placeholder="搜索类型、剧集或状态" value="${esc(jobQuery)}"></label><span id="record-result-count" aria-live="polite">${list.length} 条记录</span></div><div class="record-filters" role="group" aria-label="筛选生成记录">${[['all','全部'],['active','进行中'],['attention','待处理'],['done','已完成']].map(([k,n])=>`<button data-job-status="${k}" aria-pressed="${jobStatus===k}">${n}<span>${allJobs.filter(j=>matchesJobStatus(j,k)).length}</span></button>`).join('')}</div>${list.map(j=>{
 let r=j.result?JSON.parse(j.result):null;
 return `<details class="job" data-state="${esc(j.state)}" data-job-card="${esc(j.id)}" data-search="${esc((kinds[j.kind]+' '+(j.episode_title||'')+' '+(statuses[j.state]||j.state)).toLowerCase())}" ${expanded.has(j.id+':card')?'open':''} data-job-output="${esc(j.id)}:card"><summary class="job-summary"><span class="job-kind-icon">${uiIcon(j.kind==='export'?'movie':'file-text')}</span><span class="job-label"><strong>${esc(kinds[j.kind])}</strong><small>${esc(j.episode_title||'历史记录')}</small></span><time>${new Date(j.created*1000).toLocaleString()}</time><span class="pill">${esc(statuses[j.state]||j.state)}</span></summary><div class="job-body">${j.error?`<p>${esc(j.error)}</p>`:''}${r?.file?`<details class="job-export-preview" data-job-output="${esc(j.id)}:export" ${expanded.has(j.id+':export')?'open':''}><summary>预览导出结果</summary><video controls preload="metadata" src="/media/${esc(r.file)}"></video></details><p><a href="/media/${esc(r.file)}" download>下载 MP4</a>${r.manifest?` · <a href="/media/${esc(r.manifest)}" download>制作清单</a>`:''}</p>`:''}${r?.result?`<details data-job-output="${esc(j.id)}" ${expanded.has(j.id)?'open':''}><summary>${j.state==='blocked'?'查看需要修改的问题':'查看结果'}</summary>${['shots','revision'].includes(j.kind)&&r.result.shots?.length?reviewContent(JSON.stringify(r.result)):`<pre>${esc(JSON.stringify(r.result,null,2))}</pre>`}</details>${j.state==='succeeded'&&['script','assets','shots','revision'].includes(j.kind)&&!(p().applied||[]).includes(j.id)?`<button data-apply="${esc(j.id)}" ${j.fresh===false?'disabled':''}>${j.kind==='revision'?'应用到这一镜':'采纳本次方案'}</button>`:''}`:''}${j.generation_unit?`<details data-job-output="${esc(j.id)}:basis" ${expanded.has(j.id+':basis')?'open':''}><summary>生成参数（技术信息）</summary><p>单元 ${esc(j.generation_unit.id)} · ${j.generation_unit.shot_ids.length} 镜${j.generation_unit.line_id?' · 对白 '+esc(j.generation_unit.line_id):''}</p><pre>${esc(JSON.stringify({parameters:j.generation_unit.parameters,references:j.generation_unit.references,input_digest:j.generation_unit.input_digest},null,2))}</pre><p class="muted">这是提交时的参数与文件校验记录，不代表供应商已执行，也不冻结云端应用后续修改。</p></details>`:''}${r?.run_id?`<details class="technical-detail" data-job-output="${esc(j.id)}:run" ${expanded.has(j.id+':run')?'open':''}><summary>用量与技术信息</summary>${r?.current_node?`<p>当前步骤：${esc(r.current_node.title)} · ${esc(({running:'进行中',waiting_review:'等待审批',finished:'已结束',succeeded:'已完成'})[j.state==='succeeded'||j.state==='blocked'?'finished':r.current_node.status]||r.current_node.status)}</p>`:''}<p>远程运行：${esc(r.run_id)}</p>${r.tokens!=null?`<p>模型用量：${esc(r.tokens)} tokens</p>`:''}</details>`:''}${(p().applied||[]).includes(j.id)?'<p class="muted">已采纳，可在镜头页继续编辑。</p>':''}${!(p().applied||[]).includes(j.id)&&j.fresh===false&&j.state==='succeeded'&&['script','assets','shots','revision'].includes(j.kind)?'<p class="muted">相关创作设定已变化，此方案保留供参考，不能直接采纳。</p>':''}${j.state==='waiting_review'&&r?reviewPanel(j,r):''}${['interrupted','waiting_review','failed'].includes(j.state)&&r?.run_id?`<button data-reconcile="${esc(j.id)}">查询最新进度</button>`:''}${['queued','running','waiting_review'].includes(j.state)?`<button data-cancel="${esc(j.id)}">取消本地任务</button>`:''}</div></details>`;
 }).join('')||`<div class="empty"><h2>${jobStatus==='all'?'还没有生成记录':'没有这类记录'}</h2><p>${jobStatus==='all'?'生成或导出后，在这里查看结果。':'选择其他分类查看。'}</p></div>`}`;
 const filterRecords=()=>{let count=0;document.querySelectorAll('[data-job-card]').forEach(row=>{row.hidden=!row.dataset.search.includes(jobQuery.toLowerCase());if(!row.hidden)count++});$('#record-result-count').textContent=count+' 条记录';$('#record-search-empty').hidden=count>0||!jobQuery.trim()||!list.length};
 const noResults=document.createElement('p');noResults.id='record-search-empty';noResults.className='muted';noResults.textContent='没有匹配的记录';$('#content').append(noResults);$('#job-search').oninput=e=>{jobQuery=e.target.value;filterRecords()};filterRecords();
 document.querySelectorAll('[data-review-notes]').forEach(el=>el.oninput=()=>{const job=list.find(j=>j.id===el.dataset.reviewNotes),r=JSON.parse(job.result);reviewDrafts[job.id+':'+r.review_id]=el.value});
 document.querySelectorAll('[data-job-status]').forEach(b=>b.onclick=()=>{jobStatus=b.dataset.jobStatus;render();document.querySelector('[data-job-status="'+jobStatus+'"]')?.focus({preventScroll:true})});
 $('#job-scope').onchange=e=>{jobScope=e.target.value;render()};
 bind('#refresh',()=>refresh());bind('#qc',()=>run('qc'));bind('#genplan',()=>run('plan'));
 document.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async()=>{try{await api('/api/cancel',{id:b.dataset.cancel});await refresh();toast('已取消本地结果采纳，已发出的外部调用可能仍在执行')}catch(e){toast(e.message)}});
 document.querySelectorAll('[data-apply]').forEach(b=>b.onclick=async()=>{try{const job=list.find(j=>j.id===b.dataset.apply);let mode,preview;if(job.kind==='revision'){preview=await chooseRevision(job);if(!preview)return}else if(job.kind==='shots'&&job.scope==='episode'){mode=await chooseAdoption(job);if(!mode)return}else if(!await confirmAction('将这次建议添加到作品？系统会校验来源版本与引用。'))return;await api('/api/apply',{project_id:pid,job_id:b.dataset.apply,revision:p().revision,mode,preview_digest:preview?.digest});if(preview){view='shots';selected=preview.target_shot_id;shotFilter='all'}await refresh();toast(preview?'修改已应用，请重新确认这一镜':'建议已采纳')}catch(e){await refresh();toast(e.message)}});
 document.querySelectorAll('[data-review]').forEach(b=>b.onclick=async()=>{try{let job=list.find(j=>j.id===b.dataset.review),r=JSON.parse(job.result),notes=document.querySelector(`[data-review-notes="${job.id}"]`).value;if(!await confirmAction(`提交「${b.textContent}」并继续此 Dify 运行？`))return;b.disabled=true;await api('/api/review',{project_id:pid,job_id:job.id,revision:p().revision,review_id:r.review_id,action:b.dataset.action,notes});await refresh();toast('审批已提交，正在跟进原运行')}catch(e){await refresh();toast(e.message)}});
 document.querySelectorAll('[data-reconcile]').forEach(b=>b.onclick=async()=>{try{await api('/api/reconcile',{project_id:pid,job_id:b.dataset.reconcile});await refresh();toast('正在查询原运行，不会重新提交生成')}catch(e){toast(e.message)}});
}
function settings(){
 const motionOff=localStorage.getItem('luma-background-motion')==='off';
 $('#content').innerHTML=`<div class="settings"><div class="page-heading"><div><h2>设置</h2><p class="muted">创作偏好与制作服务</p></div>${p()?`<button class="text-button" data-flow="${creativeReturnView()}">返回创作 ↗</button>`:''}</div><div class="settings-layout"><nav class="settings-nav" aria-label="设置分类">${[['appearance','界面与操作','adjustments-horizontal'],['budget','生成用量','history'],['connections','制作服务','folder']].map(([id,name,icon])=>`<button data-settings-section="${id}" aria-current="${settingsSection===id?'page':'false'}">${uiIcon(icon)}${name}</button>`).join('')}</nav><div class="settings-content"><div class="settings-grid"><section class="appearance-panel" data-settings-panel="appearance"><div class="setting-section-heading"><span class="section-symbol" aria-hidden="true">◐</span><h3>界面与动效</h3></div><div class="setting-row appearance-row"><div><h4>流光动效</h4><p>标识依次点亮，导航平滑切换</p></div><button id="toggle-motion" class="toggle-switch" aria-label="界面动效" aria-pressed="${!motionOff}"><span></span></button></div><p class="muted">自动跟随系统的减少动态设置。</p><div class="shortcut-guide"><div><span>切换创作页</span><span><kbd>Alt</kbd> <kbd>↑ / ↓</kbd></span></div><div><span>选择创作标签</span><kbd>← / →</kbd></div><p>内容区可独立滚动，到边缘后继续滑动切换创作页。</p></div></section>${budgetPanel()}</div><section class="connections-panel" data-settings-panel="connections"><div class="setting-section-heading"><span class="section-symbol" aria-hidden="true">↗</span><h3>制作服务</h3><span class="muted">${Object.values(state.dify).filter(Boolean).length} 项已配置</span></div><div class="connection-grid">${['shots','revision','audio','image','video'].map(k=>`<article class="connection-item"><div><h4>${({shots:'分镜创作',revision:'镜头修改',audio:'对白配音',image:'画面生成',video:'视频生成'})[k]}</h4><span class="service-state ${state.dify[k]?'configured':''}" id="connection-${k}" role="status">${state.dify[k]?'已配置':'未连接'}</span></div>${state.dify[k]?`<button class="text-button" data-check-connection="${k}">检查连接 ↗</button>`:'<span class="muted">可先导入本地素材</span>'}</article>`).join('')}</div><details class="service-settings"><summary>管理服务连接</summary><p class="muted">Dify 执行创作流程。检查连接不运行模型。</p>${Object.entries(kinds).filter(([k])=>!['export','shots','revision','audio','image','video'].includes(k)).map(([k,v])=>`<div class="setting-row"><span>${v}</span><span class="pill" id="connection-${k}" role="status">${state.dify[k]?'已配置':'未连接'}</span>${state.dify[k]?`<button data-check-connection="${k}">检查连接</button>`:''}</div>`).join('')}<form id="dify-config"><label>制作能力<select name="kind">${Object.entries(kinds).filter(([k])=>k!=='export').map(([k,v])=>`<option value="${k}" ${k==='shots'?'selected':''}>${v}</option>`).join('')}</select></label><label>Dify API 地址<input name="base_url" type="url" value="${esc(state.dify_base_url||'https://api.dify.ai/v1')}" required></label><label>应用 API Key<input name="api_key" type="password" autocomplete="off" placeholder="app-…" required></label><button class="primary">保存连接</button></form><p class="muted">凭据仅保存本机。保存配置不会发起生成。</p><button id="recheck">刷新配置状态</button></details></section></div></div></div>`;
 const applySettingsSection=()=>{document.querySelectorAll('[data-settings-panel]').forEach(el=>el.hidden=el.dataset.settingsPanel!==settingsSection);document.querySelector('.settings-grid').hidden=settingsSection==='connections';document.querySelectorAll('[data-settings-section]').forEach(b=>{if(b.dataset.settingsSection===settingsSection)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')})};
 document.querySelectorAll('[data-settings-section]').forEach(b=>b.onclick=()=>{settingsSection=b.dataset.settingsSection;applySettingsSection()});applySettingsSection();
 bindBudget();
 bind('#toggle-motion',()=>{const off=document.documentElement.dataset.motion==='off';localStorage.setItem('luma-background-motion',off?'on':'off');document.documentElement.dataset.motion=off?'on':'off';render();$('#toggle-motion')?.focus({preventScroll:true})});
 document.querySelectorAll('[data-check-connection]').forEach(button=>button.onclick=async()=>{
  const badge=$('#connection-'+button.dataset.checkConnection);button.disabled=true;badge.textContent='正在检查…';
  try{const result=await api('/api/settings/dify/check',{kind:button.dataset.checkConnection});badge.textContent=result.message;badge.title=result.app_name}
  catch(error){badge.textContent=error.message}finally{button.disabled=false}
 });
 bind('#recheck',()=>refresh());$('#dify-config').onsubmit=async e=>{e.preventDefault();try{let form=new FormData(e.target);await api('/api/settings/dify',{base_url:form.get('base_url'),api_key:form.get('api_key'),kind:form.get('kind')});e.target.reset();await refresh();toast('连接配置已保存，仍需真实调用验证')}catch(err){toast(err.message)}};
}
$('#new').onclick=()=>$('#newdialog').showModal();$('#close').onclick=()=>$('#newdialog').close();$('#newform').onsubmit=async e=>{e.preventDefault();try{let f=new FormData(e.target),x=await api('/api/projects',{title:f.get('title'),script:f.get('script')});pid=x.id;eid=null;view='overview';$('#newdialog').close();e.target.reset();await refresh()}catch(e){toast(e.message)}};
$('#episodes').onchange=e=>{eid=e.target.value;selected=null;render()};
function editEpisode(creating){if(!p())return;document.querySelector('.episode-options').open=false;$('#episodeform').dataset.creating=String(creating);$('#episode-dialog-title').textContent=creating?'新建一集':'重命名剧集';$('#episode-name').value=creating?`第 ${p().episodes.length+1} 集`:episode().title;$('#episodedialog').showModal()}
bind('#add-episode',()=>editEpisode(true));bind('#rename-episode',()=>editEpisode(false));
bind('#episode-continuity',openContinuity);
bind('#episode-close',()=>$('#episodedialog').close());
$('#episodeform').onsubmit=async e=>{e.preventDefault();try{let title=$('#episode-name').value.trim();if(!title)throw Error('请输入剧集名称');if(e.target.dataset.creating==='true'){let ep={id:crypto.randomUUID(),title,script:''};p().episodes.push(ep);await save();eid=ep.id;selected=null;view='overview'}else{episode().title=title;await save()}$('#episodedialog').close();render();toast('剧集已保存')}catch(err){toast(err.message)}};
$('#projects').onchange=e=>enterProject(e.target.value);document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>go(b.dataset.view));
document.documentElement.dataset.motion=localStorage.getItem('luma-background-motion')||'on';
initializeNavigation();refresh().catch(e=>toast(e.message));setInterval(pollProductionProgress,1500);
async function pollProductionProgress(){
 const watching=view==='jobs'||(['shots','delivery'].includes(view)&&state.jobs.some(j=>j.project_id===pid&&['queued','running'].includes(j.state)));
 if(!watching||document.querySelector('dialog[open]:not([data-docked=true]),.picker-menu:popover-open')||document.activeElement?.matches('input,textarea,select')||[...document.querySelectorAll('video,audio')].some(media=>!media.paused))return;
 if(view==='shots'&&(hasUnsavedShot()||hasUnsavedCut()||hasUnsavedAssembly()))return;
 try{const before=JSON.stringify([p()?.revision,state.jobs.map(j=>[j.id,j.state,j.updated])]);await refresh(false);const after=JSON.stringify([p()?.revision,state.jobs.map(j=>[j.id,j.state,j.updated])]);if(before!==after)render()}catch{}
}

bind('#asset-close',()=>$('#assetdialog').close());
$('#assetform').onsubmit=async e=>{e.preventDefault();try{let f=new FormData(e.target);const created={id:crypto.randomUUID(),kind:f.get('kind'),name:f.get('name').trim(),description:f.get('description'),version:1};p().assets.push(created);assetSelection=created.id;assetCategory='all';assetToolsProject=pid;assetToolsOpen=true;await save();$('#assetdialog').close();e.target.reset();toast('素材已添加')}catch(err){toast(err.message)}};

bind('#open-story',()=>go('overview'));bind('#open-shots',()=>go('shots'));

bind('#open-assets',()=>go('assets'));bind('#open-delivery',()=>go('delivery'));
