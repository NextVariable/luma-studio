/* 生成记录抽屉：进度、审批、采纳、核实与取消 */
(function(){
const {esc,$,$$}=L;
L.ui.jobScope=L.ui.jobScope||'episode';
L.ui.jobFilter=L.ui.jobFilter||'all';
const notes=new Map();
const FIELDS={description:'画面描述',duration:'时长',framing:'景别',camera:'运镜',dialogue:'对白',lines:'逐句对白',asset_ids:'角色与素材',creative_spec:'创作规格'};
const MODES={append:['追加到末尾','保留现有镜头，把方案里的镜头接在后面。'],merge:['按顺序合并','方案第 1 镜更新现有第 1 镜的文字，以此类推；画面和锁定不变，多出的镜头追加。'],replace:['整集替换','用方案替换本集所有镜头。已有素材或锁定的镜头时不能使用。']};
const show=v=>v==null||v===''?'（空）':typeof v==='string'||typeof v==='number'?String(v):JSON.stringify(v,null,1);

L.openDrawer=()=>{L.S.drawer=true;L.renderDrawer();$('#drawer .btn')?.focus()};
L.closeDrawer=()=>{L.S.drawer=false;L.renderDrawer()};
L.renderDrawer=()=>{
  const d=$('#drawer'),open=L.S.drawer&&!!L.project();
  $('#jobs-btn')?.setAttribute('aria-expanded',open);
  if(!open){d.hidden=true;return}
  const keep=document.activeElement?.closest?.('#drawer')?document.activeElement.dataset.review||document.activeElement.id:null;
  if(d.contains(document.activeElement)&&document.activeElement.matches('textarea'))return;
  const p=L.project(),all=L.jobsFor(L.S.data.jobs,p.id,L.S.eid,L.ui.jobScope);
  const list=all.filter(j=>L.ui.jobFilter==='all'||L.jobBucket(j)===L.ui.jobFilter);
  d.hidden=false;
  d.innerHTML=`<div class="drawer-head"><h2>生成记录</h2><span class="spacer"></span><button class="btn ghost icon-btn" id="dr-close" aria-label="关闭">✕</button></div>
    <div class="drawer-tools"><div class="seg">${[['episode','本集'],['all','整部作品']].map(([k,v])=>`<button data-scope="${k}" aria-pressed="${L.ui.jobScope===k}">${v}</button>`).join('')}</div>
      <div class="filters">${[['all','全部'],['active','进行中'],['attention','需处理'],['done','已结束']].map(([k,v])=>`<button data-f="${k}" aria-pressed="${L.ui.jobFilter===k}">${v}</button>`).join('')}</div></div>
    <div class="drawer-body">${list.length?list.map(j=>card(j,p)).join(''):'<p class="muted" style="padding:20px 8px">这里还没有记录。AI 分镜、修改、配音和导出都会出现在这里。</p>'}</div>`;
  $('#dr-close',d).onclick=L.closeDrawer;
  $$('[data-scope]',d).forEach(b=>b.onclick=()=>{L.ui.jobScope=b.dataset.scope;L.renderDrawer()});
  $$('[data-f]',d).forEach(b=>b.onclick=()=>{L.ui.jobFilter=b.dataset.f;L.renderDrawer()});
  $$('[data-notes]',d).forEach(t=>t.oninput=()=>notes.set(t.dataset.notes,t.value));
  $$('[data-act]',d).forEach(b=>b.onclick=()=>act(b,p));
  if(keep)($(`[data-review="${CSS.escape(keep)}"]`,d)||$('#'+CSS.escape(keep),d))?.focus();
};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&L.S.drawer&&!$('#modal').open&&!$('.menu')){L.closeDrawer();$('#jobs-btn')?.focus()}});

function card(j,p){
  const r=L.parseResult(j),tone=L.jobTone(j.state),ep=p.episodes.find(e=>e.id===j.episode_id);
  const target=j.target_shot_id&&p.shots.find(s=>s.id===j.target_shot_id);
  let extra='';
  if(j.state==='waiting_review'&&r.form){
    const ok=L.reviewSupport(r.form),key=j.id+':'+r.review_id;
    extra=`<div class="review-form">${esc(r.form.form_content||'')}</div>
      ${j.fresh===false?'<p class="err">作品在此之后改过，不能审批这个旧方案，请重新发起。</p>':''}
      ${ok?(r.form.inputs||[]).map(()=>`<textarea class="textarea" data-notes="${esc(key)}" rows="3" maxlength="10000" placeholder="修改意见（可选），例如：第三镜改近景，保留人物和台词。">${esc(notes.get(key)||'')}</textarea>`).join('')
        :'<p class="faint">这个表单有工作室暂不支持的字段，请到 Dify 里处理。</p>'}
      <div class="row wrap">${(r.form.user_actions||[]).map(a=>`<button class="btn small ${a.id==='approve'?'primary':''}" data-act="review" data-job="${esc(j.id)}" data-review="${esc(a.id)}" ${!ok||j.fresh===false||!r.review_id?'disabled':''}>${esc(a.title||a.id)}</button>`).join('')}</div>
      <p class="faint" style="margin:0">批准只代表通过这份创作方案，不会自动生成画面。提交审批会消耗 1 次生成额度。</p>`;
  }
  const btns=[];
  if(L.canAdopt(j,p))btns.push(`<button class="btn small primary" data-act="adopt" data-job="${esc(j.id)}" ${j.fresh===false?'disabled title="作品已变化，需重新生成"':''}>${j.kind==='revision'?'查看修改并应用':'采纳'}</button>`);
  if(j.kind==='export'&&j.state==='succeeded')btns.push(`<button class="btn small" data-act="film" data-job="${esc(j.id)}">查看成片</button>`);
  if(['image','video','audio','assemble'].includes(j.kind)&&j.state==='succeeded'&&target)btns.push(`<button class="btn small" data-act="shot" data-job="${esc(j.id)}">去这一镜</button>`);
  if(L.canReconcile(j))btns.push(`<button class="btn small" data-act="reconcile" data-job="${esc(j.id)}">${L.parseResult(j).candidate_file?'恢复入库':'查询远程结果'}</button>`);
  if(L.canCancel(j))btns.push(`<button class="btn small ghost danger" data-act="cancel" data-job="${esc(j.id)}">取消</button>`);
  return `<article class="job"><div class="job-top"><span class="dot ${tone}"></span><b>${esc(L.jobName(j.kind))}</b><span class="faint">${esc(L.jobState(j.state))}</span><time>${L.timeAgo(j.updated)}</time></div>
    ${(ep&&L.ui.jobScope==='all')||target?`<div class="faint">${ep&&L.ui.jobScope==='all'?esc(ep.title):''}${target?' '+esc(L.shotTitle(target)):''}</div>`:''}
    ${j.error?`<div class="err">${esc(j.error)}</div>`:''}
    ${j.kind!=='export'&&j.state==='succeeded'&&j.fresh===false&&L.canAdopt(j,p)?'<p class="faint" style="margin:0">相关设定在此之后改过，这份结果已过时，请重新生成。</p>':''}
    ${extra}${btns.length?`<div class="row wrap">${btns.join('')}</div>`:''}</article>`;
}

async function act(b,p){
  const j=L.S.data.jobs.find(x=>x.id===b.dataset.job);if(!j)return;
  const kind=b.dataset.act;
  if(kind==='film'){L.S.eid=j.episode_id||L.S.eid;L.ui.film=j.id;L.closeDrawer();return L.go('delivery')}
  if(kind==='shot')return L.busy(b,async()=>{
    if(!await L.leaveOk())return;
    await L.refresh();L.S.dirty=false;
    L.S.eid=j.episode_id||L.S.eid;L.S.sid=j.target_shot_id;L.ui.tab=j.kind==='audio'?'dialogue':'media';
    L.closeDrawer();return L.go('shots');
  });
  if(kind==='adopt')return adopt(j,p);
  await L.busy(b,async()=>{
    if(kind==='review'){
      const r=L.parseResult(j);
      await L.api('/api/review',{project_id:p.id,job_id:j.id,revision:p.revision,review_id:r.review_id,action:b.dataset.review,notes:notes.get(j.id+':'+r.review_id)||''});
      L.toast('审批已提交，Dify 会继续执行');
    }
    if(kind==='reconcile'){await L.api('/api/reconcile',{project_id:p.id,job_id:j.id});L.toast(L.parseResult(j).candidate_file?'正在恢复入库':'正在查询远程结果，不会重复提交')}
    if(kind==='cancel'){
      if(!await L.confirmBox('取消这条任务？','本地会停止跟进；已经发出的外部调用可能仍在执行并计费。','取消任务',true))return;
      await L.api('/api/cancel',{id:j.id});L.toast('已取消');
    }
    await L.refresh();L.render();
  });
}

async function adopt(j,p){
  try{
    if(j.kind==='revision'){
      const pv=await L.api('/api/revision-preview',{project_id:p.id,job_id:j.id,revision:p.revision});
      const m=L.modal({title:'镜头 '+pv.number+' 的修改',wide:true,body:`
        ${pv.instruction?`<p class="muted" style="margin:0">你的要求：${esc(pv.instruction)}</p>`:''}
 ${pv.changes.length?`<div class="diff"><div class="h">项目</div><div class="h">修改前</div><div class="h">修改后</div>${pv.changes.map(c=>`<div class="h">${esc(FIELDS[c.field]||c.field)}</div><div>${esc(show(c.before))}</div><div>${esc(show(c.after))}</div>`).join('')}</div>`:'<p class="muted">这次修改没有改变镜头内容。</p>'}
 ${pv.media_impact?.length?`<div class="notice"><div class="grow"><b>素材影响</b>
 ${pv.media_impact.map(item=>`<p>${esc(item.label)} · ${esc({keep:'可沿用',review:'需重新确认',removed:'取消选用'}[item.status])}${item.replacement?' · 如重做，'+esc(L.quoteCost(item.replacement)):item.status!=='keep'&&item.replacement_needed!==false?' · 如重做，按新参数报价':''}</p>`).join('')}
 </div></div>`:''}
 <p class="muted">应用修改不生成素材，也不扣额度。</p>
 ${pv.effects.length?`<div class="notice wait"><div class="grow">${pv.effects.map(e=>`<p>${esc(e)}</p>`).join('')}</div></div>`:''}`,
        foot:`<button class="btn ghost" data-close>暂不应用</button><button class="btn primary" id="rv-apply">应用修改</button>`});
      $('#rv-apply',m).onclick=e=>L.busy(e.currentTarget,async()=>{
        const saved=await L.api('/api/apply',{project_id:p.id,job_id:j.id,revision:p.revision,preview_digest:pv.digest});
 L.replaceProject(saved);await L.refresh();m.close();L.S.sid=pv.target_shot_id;L.ui.tab=null;L.closeDrawer();L.go('shots');L.done('修改已应用，这一镜需要重新确认');
      });
      return;
    }
    const r=L.parseResult(j),whole=j.kind==='shots'&&j.scope==='episode';
    if(!whole){
      const n=j.kind==='script'?(r.result?.characters?.length||0)+(r.result?.scenes?.length||0):(r.result?.assets?.length||r.result?.shots?.length||0);
      if(!await L.confirmBox('采纳'+L.jobName(j.kind)+'？','会把 '+n+' 项结果加入作品，原有内容保留。','采纳'))return;
      const saved=await L.api('/api/apply',{project_id:p.id,job_id:j.id,revision:p.revision});
      L.replaceProject(saved);await L.refresh();L.render();L.done('已采纳');return;
    }
    let mode='append',pv=null;
    const m=L.modal({title:'采纳 AI 分镜',wide:true,body:`<div class="seg" id="modes">${Object.entries(MODES).map(([k,v])=>`<button data-m="${k}" aria-pressed="${k===mode}">${v[0]}</button>`).join('')}</div>
      <p class="muted" id="mode-note" style="margin:0"></p><div id="plan"></div>`,
      foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="ad-ok" disabled>采纳方案</button>`});
    const load=async()=>{
      $('#mode-note',m).textContent=MODES[mode][1];$('#plan',m).innerHTML='<p class="faint">正在预览…</p>';$('#ad-ok',m).disabled=true;
      try{pv=await L.api('/api/apply-preview',{project_id:p.id,job_id:j.id,revision:p.revision,mode})}catch(e){$('#plan',m).innerHTML=`<div class="notice stop"><p>${esc(e.message)}</p></div>`;return}
      const label={new:'新增',update:'更新',keep:'保留',skip_locked:'跳过',remove:'移除'};
      $('#plan',m).innerHTML=`${pv.blocked?`<div class="notice stop"><p>${esc(pv.blocked)}</p></div>`:''}
        <div class="row wrap" style="margin:10px 0">${Object.entries(pv.counts).filter(x=>x[1]).map(([k,v])=>`<span class="chip">${label[k]} ${v}</span>`).join('')}</div>
        <div class="plan-list">${pv.items.map(x=>`<div class="plan-item ${x.action}"><b>${label[x.action]}</b><span>${esc(x.description||x.old_description||'')}${x.action==='update'?`<div class="faint">原：${esc(x.old_description)}</div>`:''}</span></div>`).join('')}</div>`;
      $('#ad-ok',m).disabled=!!pv.blocked;
    };
    $$('#modes button',m).forEach(b=>b.onclick=()=>{mode=b.dataset.m;$$('#modes button',m).forEach(x=>x.setAttribute('aria-pressed',x===b));load()});
    $('#ad-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      const saved=await L.api('/api/apply',{project_id:p.id,job_id:j.id,revision:p.revision,mode});
      L.replaceProject(saved);await L.refresh();m.close();L.closeDrawer();L.go('shots');L.done('分镜已采纳，请逐镜确认');
    });
    load();
  }catch(e){L.fail(e)}
}
})();
