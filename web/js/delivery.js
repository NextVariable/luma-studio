/* 成片：交付检查、导出、当前与历史成片 */
(function(){
const {esc,$,$$}=L;
L.ui.film=L.ui.film||null;

const ACTION_TAB={media:'media',make:'make',dialogue:'dialogue',shot:null};
const CHECK_TONE={blocked:'wait',review:'wait',reuse:'ok',optional:''};
function checklistRow(item,shot){
  return `<div>
    <button class="check" data-sid="${esc(item.shot_id)}" data-action="shot"><span class="n num">${String(item.number).padStart(2,'0')}</span>
      <span class="dot ${item.ready?'ok':'wait'}"></span><span class="grow">${esc(L.shotTitle(shot||{}))}</span>
      <span class="faint">${item.ready?'可交付':'待处理'}</span></button>
    ${(item.checks||[]).map(check=>`<button class="check" data-sid="${esc(item.shot_id)}" data-action="${esc(check.action)}">
      <span class="n" aria-hidden="true"></span><span class="dot ${CHECK_TONE[check.status]||''}"></span>
      <span class="why grow">${esc(check.label)}</span><span aria-hidden="true">›</span></button>`).join('')}
  </div>`;
}

L.views.delivery=view=>{
  const p=L.project(),ep=L.episode(),r=L.ready(),list=L.shots();
  const films=L.films(L.S.data.jobs,p.id,ep.id);
  const running=L.S.data.jobs.find(j=>j.project_id===p.id&&j.kind==='export'&&j.episode_id===ep.id&&L.jobActive(j.state));
  const current=films.find(f=>L.deliveryIsCurrent(f.result,r));
  const shown=films.find(f=>f.job.id===L.ui.film)||current||films[0];
  const vertical=(p.creative_brief?.format)==='9:16';
  const items=r?.shots||[];
  const blocked=items.filter(x=>!x.ready);
  L.setAmbient(list.find(s=>s.image)||list.find(s=>s.video)||{id:p.id});
  view.innerHTML=`<div class="delivery">
    <section class="delivery-preview">
      <div class="screen ${vertical?'vertical':''} ${shown?'':'lit'}" style="${shown?'':`background:${L.glow(p.id)}`}">${shown?`<video src="${L.media(shown.result.file)}" controls playsinline preload="metadata"></video>`
 :`<div class="stage-empty"><h2>${running?'正在导出…':'还没有成片'}</h2><p>${running?'导出在本机进行，完成后会出现在这里。':blocked.length?'确认所有镜头后，就可以导出这一集。':items.length?'所有镜头都已就绪，可以导出。':'这一集还没有镜头，先去镜头页添加。'}</p></div>`}</div>
      <div class="film-meta"><h1>${esc(ep.title)}</h1>
        ${shown?`<span class="chip"><span class="dot ${shown===current?'ok':'wait'}"></span>${shown===current?'当前成片':'历史成片，之后镜头有改动'}</span><span class="faint num">${L.clock(shown.result.duration)}</span>`:''}
 <span class="spacer"></span>
        ${shown?`<a class="btn" href="${L.media(shown.result.file)}" download>下载 MP4</a>`:''}
 <button class="btn primary" id="export" ${!r?.can_export||running?'disabled':''}>${running?'导出中…':current?'重新导出':'导出成片'}</button></div>
      ${!r?.can_export&&!running&&items.length?`<p class="faint">还有 ${blocked.length} 个镜头没有就绪，处理完交付清单中的问题后就能导出。</p>`:''}
      ${r?.can_export&&items.some(x=>x.dialogue_without_audio)?'<p class="faint">有镜头写了对白但没有配音，导出时会用画面原声或静音，并保留字幕。</p>':''}
    </section>
    <aside class="side-stack delivery-list" data-scroll="delivery" aria-label="交付检查与导出记录" tabindex="0">
      <section class="panel"><div class="panel-head"><h2>本集制作清单</h2><span class="spacer"></span><span class="faint num">${items.filter(x=>x.ready).length} / ${items.length} 可交付</span></div>
        <div class="panel-body" style="padding:10px 8px 12px;gap:2px">
 ${r?.continuity?.requires_confirmation?`<div class="notice wait" style="margin:0 8px 8px"><div class="grow"><p>${esc(r.continuity.reason||'本集开头的剧情状态需要确认')}</p></div><button class="btn small" id="cont">去确认</button></div>`:''}
 ${items.length?items.map(x=>checklistRow(x,list.find(s=>s.id===x.shot_id))).join(''):'<button class="check" data-action="shot">还没有镜头，去添加 ›</button>'}
 </div></section>
      ${films.length?`<section class="panel"><div class="panel-head"><h2>导出记录</h2></div><div class="panel-body"><div class="films">${films.map(f=>`<button class="film" data-film="${esc(f.job.id)}" ${f===shown?'aria-current="true"':''}><span class="dot ${f===current?'ok':''}"></span><span style="flex:1">${f===current?'当前成片':'历史成片'}</span><span class="faint num">${L.clock(f.result.duration)}</span><span class="faint">${L.timeAgo(f.job.updated)}</span></button>`).join('')}</div></div></section>`:''}
    </aside></div>`;
  $('#export',view).onclick=e=>L.busy(e.currentTarget,async()=>{await L.run('export',{episode_id:ep.id});L.toast('开始导出这一集');L.render()});
  $$('.check',view).forEach(b=>b.onclick=()=>{
    const shotId=b.dataset.sid,tab=ACTION_TAB[b.dataset.action];
    if(L.goTo)return L.go('shots',{shotId,tab});
    if(shotId)L.S.sid=shotId;
    L.ui.tab=tab||'content';
    return L.go('shots');
  });
  $$('.film',view).forEach(b=>b.onclick=()=>{L.ui.film=b.dataset.film;L.render()});
  $('#cont',view)?.addEventListener('click',()=>L.continuityDialog());
};
})();
