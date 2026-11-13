/* 剧本：按集写剧本、管理剧集与创作设定、发起 AI 分镜 */
(function(){
const {esc,$,$$}=L;
const METHODS={mixed:'混合制作',illustrated:'画面漫剧',video:'视频漫剧'};
let scriptPanel='text';

L.views.script=view=>{
  const p=L.project(),ep=L.episode(),r=L.ready(),brief=p.creative_brief||{format:'16:9',method:'mixed',style:''};
  const words=t=>t.replace(/\s/g,'').length;
  const cont=r?.continuity;
  view.innerHTML=`<div class="desk" data-script-panel="${scriptPanel}">
    <div class="script-mobile-tabs" role="group" aria-label="剧本工作区">
      <button class="btn small" data-panel="text" aria-controls="script-sheet" aria-pressed="${scriptPanel==='text'}">剧本</button>
      <button class="btn small" data-panel="tools" aria-controls="script-tools" aria-pressed="${scriptPanel==='tools'}">剧集与设定</button>
    </div>
    <section class="panel script-sheet" id="script-sheet">
      <div class="sheet-head"><h1>${esc(ep.title)}</h1><span class="faint num" id="wc">${words(ep.script||'')} 字</span><span class="spacer"></span>
 <button class="btn ghost small" id="read-script">阅读全文</button><button class="btn ghost small" id="load-txt">从文件载入</button></div>
      ${cont?.requires_confirmation?`<div style="padding:14px 22px 0"><div class="notice wait"><div class="grow"><b>上一集的剧情状态变了</b><p class="muted">${esc(cont.reason||'本集开头的人物和道具状态需要重新确认后才能继续制作。')}</p></div><button class="btn small" id="cont-open">比较并确认</button></div></div>`:''}
      <textarea class="script-text" id="script" data-scroll="script-text" data-track maxlength="100000" placeholder="写下这一集的故事、场景和对白。写好后可以让 AI 拆成分镜。">${esc(ep.script||'')}</textarea>
      <div class="script-foot"><span class="faint" id="save-state">已保存</span><span class="spacer"></span>
        <button class="btn" id="save-script">保存剧本</button>
        <button class="btn ${L.S.data.dify.shots?'primary':''}" id="split"><span class="spark">✦</span>AI 拆分镜头${L.S.data.dify.shots?'':'（未连接）'}</button></div>
    </section>
    <aside class="side-stack script-tools" id="script-tools" data-scroll="script-tools" aria-label="剧集和创作设定" tabindex="0">
      <section class="panel"><div class="panel-head"><h2>剧集</h2><span class="spacer"></span><button class="btn ghost small" id="ep-add">新建剧集</button></div>
        <div class="panel-body" style="padding-top:10px"><div class="ep-list">${p.episodes.map(e=>{
   const n=p.shots.filter(s=>s.episode_id===e.id).length;
   return `<button data-eid="${esc(e.id)}" ${e.id===ep.id?'aria-current="true"':''}>${esc(e.title)}<span class="count num">${n} 镜</span></button>`}).join('')}</div>
   <button class="btn ghost small" id="ep-rename" style="align-self:flex-start">重命名本集</button></div></section>
      <section class="panel"><div class="panel-head"><h2>创作设定</h2></div>
        <div class="panel-body">
   <div class="field"><span>画幅</span><div class="seg" id="fmt">${['16:9','9:16'].map(f=>`<button data-f="${f}" aria-pressed="${(brief.format||'16:9')===f}">${f==='16:9'?'横屏 16:9':'竖屏 9:16'}</button>`).join('')}</div></div>
          <label class="field"><span>制作方式</span><select class="select" id="method" data-track>${Object.entries(METHODS).map(([k,v])=>`<option value="${k}" ${brief.method===k?'selected':''}>${v}</option>`).join('')}</select></label>
   <label class="field"><span>统一视觉风格</span><textarea class="textarea" id="style" data-track rows="3" maxlength="2000" placeholder="例如：赛璐璐风格，夜景偏冷色，服装沿用角色设定。">${esc(brief.style||'')}</textarea></label>
   <p class="faint" style="margin:0">修改画幅、风格或制作方式后，已有镜头需要重新确认。</p>
          <button class="btn" id="save-brief" style="align-self:flex-start">保存设定</button>
        </div></section>
    </aside></div>`;
  const panels=$$('.script-mobile-tabs button',view);
  panels.forEach(button=>button.onclick=()=>{
    scriptPanel=button.dataset.panel;
    $('.desk',view).dataset.scriptPanel=scriptPanel;
    panels.forEach(tab=>tab.setAttribute('aria-pressed',tab===button));
  });
  L.trackDirty(view);
  const ta=$('#script',view);
  ta.addEventListener('input',()=>{$('#wc',view).textContent=words(ta.value)+' 字';$('#save-state',view).textContent='有未保存的修改'});
  const persist=()=>L.save(p2=>{const e=p2.episodes.find(x=>x.id===ep.id);e.script=ta.value;if(p2.episodes.length===1)p2.script=ta.value});
  $('#save-script',view).onclick=e=>L.busy(e.currentTarget,async()=>{await persist();L.toast('剧本已保存');L.render()});
  ta.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();$('#save-script',view).click()}});
  $('#split',view).onclick=e=>L.busy(e.currentTarget,async()=>{
    if(!ta.value.trim())throw Error('先写下这一集的剧本，再拆分镜头');
    if(ta.value!==(ep.script||''))await persist();
    const id=await L.run('shots',{episode_id:L.S.eid});
    if(id){L.toast('已开始 AI 分镜，完成后在生成记录里审批和采纳');L.openDrawer()}
  });
  $('#read-script',view).onclick=()=>{
    L.modal({title:ep.title,wide:true,body:`<div class="script-reader">${esc(ta.value.trim()||'这一集还没有剧本。')}</div>`});
  };
  $('#load-txt',view).onclick=async()=>{const f=await L.pickFile('.txt,.md,text/plain');if(f){ta.value=await f.text();ta.dispatchEvent(new Event('input',{bubbles:true}));L.toast('已载入，确认后请保存剧本')}};
  $$('.ep-list button',view).forEach(b=>b.onclick=async()=>{if(await L.leaveOk()){L.S.eid=b.dataset.eid;L.S.sid=null;L.normalize();L.render()}});
  $('#ep-add',view).onclick=async()=>{
    const title=await L.prompt('新建剧集','剧集名称','第 '+(p.episodes.length+1)+' 集','新建剧集');if(!title)return;
    try{const id=crypto.randomUUID();await L.save(p2=>p2.episodes.push({id,title,script:''}));L.S.eid=id;L.S.sid=null;L.render();L.toast('已新建剧集')}catch(e){L.fail(e)}
  };
  $('#ep-rename',view).onclick=async()=>{
    const title=await L.prompt('重命名剧集','剧集名称',ep.title);if(!title)return;
    try{await L.save(p2=>{p2.episodes.find(x=>x.id===ep.id).title=title});L.render()}catch(e){L.fail(e)}
  };
  let fmt=brief.format||'16:9';
  $$('#fmt button',view).forEach(b=>b.onclick=()=>{fmt=b.dataset.f;L.S.dirty=true;$$('#fmt button',view).forEach(x=>x.setAttribute('aria-pressed',x===b))});
  $('#save-brief',view).onclick=e=>L.busy(e.currentTarget,async()=>{
    await L.save(p2=>{p2.creative_brief={...p2.creative_brief,format:fmt,method:$('#method',view).value,style:$('#style',view).value}});
    L.toast('创作设定已保存');L.render();
  });
  $('#cont-open',view)?.addEventListener('click',()=>L.continuityDialog());
};

/* 跨集承接确认 */
const stateText=v=>v==null?'（无）':typeof v==='string'?v:JSON.stringify(v,null,2);
L.continuityDialog=async()=>{
  try{
    const p=L.project(),pv=await L.api('/api/continuity/preview',{project_id:p.id,episode_id:L.S.eid});
    const st=pv.status||{};
    if(st.upstream_pending){
      const up=p.episodes.find(e=>e.id===st.upstream_episode_id);
      return L.modal({title:'先确认上一集',body:`<p class="muted">${esc(up?.title||'上一集')}的承接状态还没确认，确认后才能处理本集。</p>`,
 foot:`<button class="btn ghost" data-close>关闭</button><button class="btn primary" id="go-up">去${esc(up?.title||'上一集')}</button>`,
 onMount:m=>{$('#go-up',m).onclick=()=>{m.close();L.S.eid=st.upstream_episode_id;L.normalize();L.render()}}});
    }
    const m=L.modal({title:'确认本集开头的剧情状态',wide:true,body:`
      <p class="muted" style="margin:0">${esc(st.reason||'上一集结尾的状态和本集开头记录的不一致。')}</p>
      <div class="diff"><div class="h">项目</div><div class="h">本集原来记录</div><div class="h">上一集结尾</div>
 <div class="h">开头状态</div><div>${esc(stateText(pv.before))}</div><div>${esc(stateText(pv.after))}</div>
        <div class="h">承接内容</div><div>${esc(stateText(pv.before_carry))}</div><div>${esc(stateText(pv.after_carry))}</div></div>
      <div class="seg" id="res"><button data-r="inherit" aria-pressed="true">采用上一集结尾</button><button data-r="keep" aria-pressed="false">保留本集原状态</button></div>
      <label class="field" id="reason-wrap" hidden><span>保留的理由（必填）</span><textarea class="textarea" id="reason" maxlength="2000" rows="3"></textarea></label>
      <p class="faint" style="margin:0">确认后，受影响的镜头需要重新确认；已有素材和制作准备不会被自动替换。</p>`,
      foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="cont-ok">确认承接</button>`});
    let res='inherit';
    $$('#res button',m).forEach(b=>b.onclick=()=>{res=b.dataset.r;$$('#res button',m).forEach(x=>x.setAttribute('aria-pressed',x===b));$('#reason-wrap',m).hidden=res!=='keep'});
    $('#cont-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      const reason=$('#reason',m).value.trim();if(res==='keep'&&!reason)throw Error('请写下保留原状态的理由');
      const saved=await L.api('/api/continuity/confirm',{project_id:p.id,episode_id:L.S.eid,revision:pv.revision,digest:pv.digest,resolution:res,reason});
      L.replaceProject(saved);await L.refresh();m.close();L.toast('已确认承接');L.render();
    });
  }catch(e){L.fail(e)}
};
})();
