/* 镜头工作台：中央画面、右侧检查器、底部按时长排列的镜头序列 */
(function(){
const {esc,$,$$}=L;
const FRAMINGS=['大远景','远景','全景','中景','近景','特写','大特写'];
const CAMERAS=['固定机位','推镜','拉镜','摇镜','移镜','跟拍','升降','手持'];
L.ui=L.ui||new Object();L.ui.filter=L.ui.filter||'all';if(!['settings','dialogue','media','make'].includes(L.ui.tab))L.ui.tab=null;

const item=s=>L.ready()?.shots.find(x=>x.shot_id===s.id);
const strict=p=>!!(p.creative_context||p.episodes.some(e=>e.creative_spec)||p.shots.some(s=>s.creative_spec));
const startOf=(list,s)=>L.total(list.slice(0,list.indexOf(s)));

function mediaTag(file,{controls=false,id=''}={}){
  if(!file)return '';
  return L.isVideo(file)?`<video ${id?`id="${id}"`:''} src="${L.media(file)}" playsinline preload="metadata" ${controls?'controls':''}></video>`:`<img src="${L.media(file)}" alt="">`;
}
function thumb(s){
  const f=s.image||s.video;
  return f?`<div class="thumb" style="background-image:url('${L.thumb(f)}')"></div>`:`<div class="thumb lit" style="background:${L.glow(s.id)}"></div>`;
}
L.setAmbient=s=>{
  const host=document.querySelector('.ambient');if(!host)return;
  const f=s?.image||s?.video,bg=f?`url('${L.thumb(f)}')`:L.glow(s?.id||L.S.pid||'luma');
  const cur=[...host.querySelectorAll('.ambient-media')].at(-1);
  if(cur&&cur.dataset.bg===bg)return;
  const layer=document.createElement('div');layer.className='ambient-media'+(f?'':' glow');layer.dataset.bg=bg;layer.style.backgroundImage=bg;
  host.insertBefore(layer,host.querySelector('.ambient-veil'));
  const target=getComputedStyle(layer).opacity;
  if(L.reduced()||!cur){[...host.querySelectorAll('.ambient-media')].filter(x=>x!==layer).forEach(x=>x.remove());return}
  [...host.querySelectorAll('.ambient-media')].filter(x=>x!==cur&&x!==layer).forEach(x=>x.remove());
  layer.animate([{opacity:0},{opacity:target}],{duration:260,easing:'ease-out'}).onfinish=()=>cur.remove();
};

L.views.shots=view=>{
  const p=L.project(),list=L.shots(),s=L.shot(),r=L.ready();
  L.setAmbient(s);
  if(!s){
    view.innerHTML=`<div class="bench"><section class="stage empty"><div class="stage-glow lit" style="background:${L.glow(L.S.pid)}"></div><div class="stage-empty"><h2>这一集还没有镜头</h2><p>在剧本页让 AI 拆分镜头，或者直接添加第一个镜头。</p><div class="row" style="justify-content:center;margin-top:18px"><button class="btn primary" id="first-shot">添加镜头</button><button class="btn" id="to-script">去写剧本</button></div></div></section></div>`;
    $('#first-shot',view).onclick=addShot;$('#to-script',view).onclick=()=>L.go('script');return;
  }
  const it=item(s),visible=L.filterShots(list,r?.shots,L.ui.filter),done=list.filter(x=>item(x)?.ready).length;
  view.innerHTML=`<div class="bench">
    <div class="shot-workspace${L.ui.tab&&!L.mobilePaging()?' has-inspector':''}">
      <section class="stage" id="stage">${stage(p,list,s,it)}</section>${shotPanel(p,s,it)}
    </div>
    <section class="reel" aria-label="镜头序列">
      <div class="reel-head"><span class="num">${list.length} 镜 ${L.clock(L.total(list))}</span><span class="num">${done} / ${list.length} 可交付</span><span class="faint swipe-hint">${L.mobilePaging()?'在画面上左右滑动切换镜头':'画面或镜头条上滚动切镜头'}</span><span class="spacer"></span>
        <div class="filters" role="group" aria-label="筛选镜头">${[['all','全部'],['missing','缺画面'],['review','待处理'],['ready','可交付']].map(([k,v])=>`<button data-filter="${k}" aria-pressed="${L.ui.filter===k}">${v}</button>`).join('')}</div></div>
      <div class="strip" id="strip" role="listbox" aria-label="镜头">${list.map((x,i)=>{const st=L.shotState(x,item(x));
        return `<button class="shot ${visible.includes(x)?'':'dim'}" role="option" data-sid="${esc(x.id)}" ${x.id===s.id?'aria-current="true" aria-selected="true"':'aria-selected="false"'} style="width:${Math.max(84,Math.round(x.duration*28))}px" title="${esc(L.shotTitle(x,i)+' · '+st.label)}">${thumb(x)}<span class="dot ${st.tone}"></span><span class="lbl num">${String(i+1).padStart(2,'0')}</span></button>`}).join('')}
        <button class="shot-add" id="add-shot" aria-label="添加镜头">＋</button></div>
    </section>
    ${composer(p,list,s,it)}
  </div>`;
  bindStrip(view,list);
  $$('[data-filter]',view).forEach(b=>b.onclick=async()=>{if(!await L.leaveOk())return;L.ui.filter=b.dataset.filter;L.render()});
  bindParts(view,p,s,list,it);
};
const POPS={settings:'镜头设置',dialogue:'对白',media:'素材',make:'制作准备'};

/* 画面区与场记板的绑定；切换镜头时只重建这两块 */
function bindParts(view,p,s,list,it){
  bindStage(view,s);
  bindComposer(view,p,s,it);
  $$('[data-pop]',view).forEach(b=>b.onclick=async()=>{
    const tab=b.dataset.pop;
    if(!await L.leaveOk())return;
    if(tab==='media'&&L.ui.tab!==tab){
      try{await L.refresh()}catch(e){L.fail(e);return}
      if(!b.isConnected||L.S.sid!==s.id)return;
    }
    L.ui.tab=tab===L.ui.tab?null:tab;
    L.render();
    if(!L.mobilePaging())$('#pop-body')?.querySelector('button,input,select,textarea')?.focus();
  });
  if(L.ui.tab){
    const tab=L.ui.tab,body=$('#pop-body',view),pop=$('#pop',view);
    L.trackDirty(body);
    const close=async()=>{
      if(!await L.leaveOk())return;
      if(pop.open)pop.close();
      L.ui.tab=null;
      L.render();
      $(`#stage .stage-top [data-pop="${tab}"]`,view)?.focus({preventScroll:true});
    };
    $('#pop-close',view).onclick=close;
    if(pop.tagName==='DIALOG'){
      pop.oncancel=e=>{e.preventDefault();close()};
      pop.onclick=e=>{if(e.target===pop){
        const rect=pop.getBoundingClientRect();
        if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)close();
      }};
      pop.showModal();
    }else pop.onkeydown=e=>{if(e.key==='Escape'){e.stopPropagation();close()}};
    ({settings:bindSettings,dialogue:bindDialogue,media:bindMedia,make:bindMake})[tab](body,p,s,list,it);
  }
}
L.showShot=(id,direction,axis)=>{
  const view=$('#view'),stageEl=$('#stage',view);
  L.S.sid=id;L.remember();
  if(L.S.view!=='shots'||!stageEl||!$('.slate',view)||L.ui.tab)return L.render();
  const p=L.project(),list=L.shots(),s=L.shot(),it=item(s);
  L.setAmbient(s);
  L.swap(stageEl,direction,()=>{stageEl.innerHTML=stage(p,list,s,it)},
    {content:'.stage-media,.stage-shade,.stage-glow,.stage-empty,.stage-info',axis});
  $('.slate',view).outerHTML=composer(p,list,s,it);
  $$('.shot',view).forEach(b=>{const on=b.dataset.sid===id;if(on)b.setAttribute('aria-current','true');else b.removeAttribute('aria-current');b.setAttribute('aria-selected',on)});
  bindParts(view,p,s,list,it);
  $('.shot[aria-current="true"]',view)?.scrollIntoView({block:'nearest',inline:'nearest'});
};
function shotPanel(p,s,it){
  const tab=L.ui.tab;
  if(!tab)return '';
  const tag=L.mobilePaging()?'dialog':'aside';
  const content=({settings,dialogue,media,make})[tab](p,s,it);
  return `<${tag} class="pop panel" id="pop" aria-labelledby="pop-title"${tag==='aside'?' role="region"':''}>
    <div class="pop-head"><h2 id="pop-title">${esc(POPS[tab])}</h2><span class="spacer"></span><button class="btn ghost icon-btn" id="pop-close" aria-label="关闭">✕</button></div>
    <div class="pop-body" id="pop-body">${content}</div></${tag}>`;
}

function stage(p,list,s,it){
  const st=L.shotState(s,it),i=list.indexOf(s),start=startOf(list,s),f=s.image||s.video;
  const lines=Array.isArray(s.lines)?s.lines.length:(s.dialogue?1:0);
  const takes=s.takes.filter(t=>t.kind!=='audio').length;
  return `${f?`<div class="stage-media">${mediaTag(f,{id:'stage-video'})}</div><div class="stage-shade"></div>`:`<div class="stage-glow lit" style="background:${L.glow(s.id)}"></div><div class="stage-empty"><h2>还没有画面</h2><p>导入一张图片或一段视频，作为这一镜的画面。</p><div class="row" style="justify-content:center;margin-top:16px"><button class="btn primary" data-pop="media">导入画面</button></div></div>`}
    <div class="stage-top"><span class="chip"><span class="dot ${st.tone}"></span>${esc(st.label)}</span>${s.locked?'<span class="chip">已锁定</span>':''}
      <span class="spacer"></span>
      <button class="chip tool ${L.ui.tab==='dialogue'?'on':''}" data-pop="dialogue">对白${lines?' '+lines:''}</button>
      <button class="chip tool ${L.ui.tab==='media'?'on':''}" data-pop="media">素材${takes?' '+takes:''}${it?.stale_media?'<span class="dot stop"></span>':''}</button>
      <button class="chip tool ${L.ui.tab==='make'?'on':''}" data-pop="make">制作</button>
      <button class="chip tool ${L.ui.tab==='settings'?'on':''}" data-pop="settings" aria-label="镜头设置">···</button></div>
    <div class="stage-info"><div class="stage-no num">SHOT ${String(i+1).padStart(2,'0')}　/　${L.clock(start)} – ${L.clock(start+s.duration)}</div>
      <h1 class="stage-title">${esc(L.shotTitle(s,i))}</h1></div>
    ${s.video?'<button class="btn primary icon-btn play" id="play" aria-label="播放">▶</button>':''}`;
}

/* 场记板：直接编辑这一镜 */
function composer(p,list,s,it){
  const dis=s.locked?'disabled':'',i=list.indexOf(s);
  const cast=(s.asset_ids||[]).map(id=>p.assets.find(a=>a.id===id)).filter(Boolean).slice(0,4);
  const pic=a=>{const v=a.versions.find(x=>x.id===(s.asset_bindings||new Object())[a.id])||a.versions.at(-1);return v?.views?.front||v?.views?.three_quarter||v?.file||null};
  const dlg=Array.isArray(s.lines)?s.lines.map(l=>l.text).filter(Boolean).join(' / '):(s.dialogue||'');
  const ready=s.approved&&!s.needs_review;
  const main=s.locked?`<button class="btn" id="unlock">解除锁定</button>`
    :ready?`<button class="btn" id="unapprove">取消确认</button>`
    :it?.stale_media?`<button class="btn primary" data-pop="media">先确认画面</button>`
    :!(s.image||s.video)?`<button class="btn" data-pop="media" title="有画面后才能确认">先导入画面</button>`
    :`<button class="btn primary" id="approve">确认镜头</button>`;
  return `<section class="slate" aria-label="编辑镜头 ${i+1}">
    <div class="slate-tag"><span class="num">镜头 ${String(i+1).padStart(2,'0')}</span><span class="num">${s.duration} 秒</span><span class="slate-state"><span class="dot ${L.shotState(s,it).tone}"></span>${esc(L.shotState(s,it).label)}</span><span class="spacer"></span><span class="faint" id="dirty-note"></span></div>
    <div class="slate-main">
      <div class="slate-cast">${cast.map(a=>{const f=pic(a);return `<button class="cast-ref" data-pop="settings" title="${esc(a.name)}" style="${f?`background-image:url('${L.thumb(f)}')`:''}">${f?'':esc(a.name.slice(0,1))}<span>${esc(a.name)}</span></button>`}).join('')}<button class="cast-ref add" data-pop="settings" aria-label="选择出场角色" ${dis}>＋<span>角色</span></button></div>
      <div class="slate-body">
        <textarea class="slate-text" id="c-desc" data-track rows="2" maxlength="4000" aria-label="画面描述" placeholder="这一镜发生什么？写下画面、动作和情绪。" ${dis}>${esc(L.realText(s.description))}</textarea>
        <div class="params">
   <label class="pm"><span aria-hidden="true">时长</span><input class="num" id="c-dur" data-track type="number" min="1" max="60" step="0.5" value="${esc(s.duration)}" aria-label="时长（秒）" ${dis}><span>秒</span></label>
          <label class="pm"><span aria-hidden="true">景别</span><select id="c-framing" data-track aria-label="景别" ${dis}>${[...new Set([s.framing,...FRAMINGS].filter(Boolean))].map(x=>`<option ${x===s.framing?'selected':''}>${esc(x)}</option>`).join('')}</select></label>
          <label class="pm"><span aria-hidden="true">运镜</span><input id="c-camera" data-track list="cameras" maxlength="200" value="${esc(s.camera||'')}" aria-label="运镜" ${dis}><datalist id="cameras">${CAMERAS.map(x=>`<option value="${x}">`).join('')}</datalist></label>
   <span class="pm static">${esc((p.creative_brief||new Object()).format||'16:9')}</span>
   <button class="pm" data-pop="dialogue" title="编辑对白">${dlg?`“${esc(dlg.length>22?dlg.slice(0,21)+'…':dlg)}”`:'添加对白'}</button>
        </div>
      </div>
      <div class="slate-act">
        <button class="btn" id="c-save" hidden>保存修改</button>
        ${s.locked?'':'<button class="btn" id="revise"><span class="spark">✦</span>AI 改写</button>'}
 ${main}
      </div>
    </div>
  </section>`;
}
function bindComposer(view,p,s,it){
  const box=$('.slate',view);L.trackDirty(box);
  const desc=$('#c-desc',view),save=$('#c-save',view);
  const fit=()=>{desc.style.height='auto';desc.style.height=Math.min(desc.scrollHeight,140)+'px'};fit();
  box.addEventListener('input',()=>{fit();save.hidden=false;$('#dirty-note',view).textContent='有未保存的修改'});
  const persist=()=>{
    const dur=Number($('#c-dur',view).value);if(!(dur>=1&&dur<=60))throw Error('时长需在 1 到 60 秒之间');
    return saveShot(s.id,x=>{x.description=desc.value;x.duration=dur;x.framing=$('#c-framing',view).value;x.camera=$('#c-camera',view).value},'镜头已保存');
  };
  save.onclick=e=>L.busy(e.currentTarget,persist);
  box.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();save.click()}});
  $('#unlock',view)?.addEventListener('click',e=>L.busy(e.currentTarget,()=>saveShot(s.id,x=>{x.locked=false},'已解除锁定')));
  $('#approve',view)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{
    if(L.S.dirty)await persist();
    await saveShot(s.id,x=>{x.approved=true;x.needs_review=false},'镜头已确认');L.sfx('ok');
  }));
  $('#unapprove',view)?.addEventListener('click',e=>L.busy(e.currentTarget,()=>saveShot(s.id,x=>{x.approved=false;x.needs_review=true},'已取消确认')));
  $('#revise',view)?.addEventListener('click',()=>reviseDialog(s));
}

function bindStage(view,s){
  const v=$('#stage-video',view),b=$('#play',view);
  if(v&&b){
    const sync=()=>{b.textContent=v.paused?'▶':'❚❚';b.setAttribute('aria-label',v.paused?'播放':'暂停')};
    b.onclick=()=>{v.paused?v.play():v.pause()};v.onplay=v.onpause=v.onended=sync;
    v.currentTime=s.trim_start||0;
  }
}
function bindStrip(view,list){
  $$('.shot',view).forEach(b=>b.onclick=async()=>{if(!await L.goTo(list.findIndex(shot=>shot.id===b.dataset.sid),{scope:'shot'}))return;$(`.shot[data-sid="${CSS.escape(b.dataset.sid)}"]`)?.focus()});
  $('#strip',view).onkeydown=async e=>{
    if(!['ArrowLeft','ArrowRight'].includes(e.key)||e.target.closest('.shot-add'))return;
    e.preventDefault();const i=list.findIndex(x=>x.id===L.S.sid),n=list[i+(e.key==='ArrowRight'?1:-1)];
    if(n&&await L.goTo(list.indexOf(n),{scope:'shot'})){$(`.shot[data-sid="${CSS.escape(n.id)}"]`)?.focus()}
  };
  $('#add-shot',view).onclick=addShot;
  $$('.shot',view).forEach(b=>{
    b.draggable=true;
    b.ondragstart=e=>{e.dataTransfer.setData('text/plain',b.dataset.sid);e.dataTransfer.effectAllowed='move';b.classList.add('dragging')};
    b.ondragend=()=>b.classList.remove('dragging');
    b.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='move';b.classList.add('drop')};
    b.ondragleave=()=>b.classList.remove('drop');
    b.ondrop=e=>{e.preventDefault();b.classList.remove('drop');reorder(e.dataTransfer.getData('text/plain'),b.dataset.sid)};
  });
  $('.shot[aria-current="true"]',view)?.scrollIntoView({block:'nearest',inline:'nearest'});
}

async function reorder(from,to){
  if(!from||from===to)return;
  const list=L.shots(),a=list.findIndex(x=>x.id===from),b=list.findIndex(x=>x.id===to);
  if(a<0||b<0)return;
  if(!await L.leaveOk())return;
  if(!await L.confirmBox('把镜头 '+(a+1)+' 移到第 '+(b+1)+' 位？','调整顺序后，前后相关的镜头可能需要重新确认。','移动'))return;
  L.busy(null,async()=>{
    await L.save(p2=>{
      const moving=p2.shots.find(x=>x.id===from),target=p2.shots.find(x=>x.id===to);
      p2.shots=p2.shots.filter(x=>x.id!==from);
      const at=p2.shots.indexOf(target)+(a<b?1:0);
      p2.shots.splice(at,0,moving);
    });
    L.S.sid=from;L.toast('顺序已调整');L.render();
  });
}
async function saveShot(sid,fn,msg){
  await L.save(p=>{fn(p.shots.find(x=>x.id===sid),p)});
  if(msg)L.toast(msg);L.render();
}

/* 镜头设置：出场角色、承接、顺序、锁定与删除 */
function settings(p,s){
  const others=L.shots().filter(x=>x.id!==s.id),dis=s.locked?'disabled':'';
  return `<div class="field"><span>出场角色与素材</span>${p.assets.length?`<div class="cast-pick">${p.assets.map(a=>`<label><input type="checkbox" data-track value="${esc(a.id)}" ${(s.asset_ids||[]).includes(a.id)?'checked':''} ${dis}>${esc(a.name)}</label>`).join('')}</div>`:`<p class="faint" style="margin:0">还没有角色或素材。<button class="btn ghost small" id="to-cast">去新建</button></p>`}</div>
    <label class="field"><span>承接镜头（画面需与之连贯）</span><select class="select" id="f-cont" data-track ${dis}><option value="">不承接</option>${others.map(x=>`<option value="${esc(x.id)}" ${s.continuity_from===x.id?'selected':''}>${esc(L.shotTitle(x))}</option>`).join('')}</select></label>
    <button class="btn primary small" id="set-save" style="align-self:flex-start" ${dis}>保存设置</button>
    <div class="sub">顺序与管理</div>
    <div class="row wrap"><button class="btn small" id="mv-up" ${dis}>前移</button><button class="btn small" id="mv-down" ${dis}>后移</button><button class="btn small" id="lock">${s.locked?'解除锁定':'锁定镜头'}</button><button class="btn small danger" id="del" ${dis}>删除镜头</button></div>
    <p class="faint" style="margin:0">也可以在下方镜头条里直接拖动调整顺序。锁定后这一镜不能编辑。</p>`;
}
function bindSettings(view,p,s){
  $('#to-cast',view)?.addEventListener('click',()=>L.go('cast'));
  $('#set-save',view).onclick=e=>L.busy(e.currentTarget,()=>saveShot(s.id,x=>{x.asset_ids=$$('.cast-pick input:checked',view).map(i=>i.value);x.continuity_from=$('#f-cont',view).value||null},'设置已保存'));
  const move=d=>e=>L.busy(e.currentTarget,async()=>{
    if(!await L.leaveOk())return;
    await L.save(p2=>{const eps=p2.shots.filter(x=>x.episode_id===s.episode_id),i=eps.findIndex(x=>x.id===s.id),j=i+d;if(j<0||j>=eps.length)throw Error(d<0?'已经是第一个镜头':'已经是最后一个镜头');
      const a=p2.shots.indexOf(eps[i]),b=p2.shots.indexOf(eps[j]);[p2.shots[a],p2.shots[b]]=[p2.shots[b],p2.shots[a]]});
    L.toast('顺序已调整，前后镜头可能需要重新确认');L.render();
  });
  $('#mv-up',view).onclick=move(-1);$('#mv-down',view).onclick=move(1);
  $('#lock',view).onclick=e=>L.busy(e.currentTarget,()=>saveShot(s.id,x=>{x.locked=!x.locked},s.locked?'已解除锁定':'已锁定'));
  $('#del',view).onclick=async()=>{if(await L.confirmBox('删除这个镜头？','镜头会从本集移除，可以在作品菜单的历史版本里找回。','删除',true))L.busy(null,async()=>{await L.save(p2=>{p2.shots=p2.shots.filter(x=>x.id!==s.id)});L.S.sid=null;L.ui.tab=null;L.normalize();L.toast('已删除');L.render()})};
}

/* 对白 */
function dialogue(p,s){
  const dis=s.locked?'disabled':'';
  const speakers=p.assets.filter(a=>a.kind==='character');
  const audios=s.takes.filter(t=>t.kind==='audio');
  if(!Array.isArray(s.lines)){
    return `<label class="field"><span>对白（整镜一段）</span><textarea class="textarea" id="d-text" data-track rows="4" maxlength="4000" ${dis}>${esc(s.dialogue||'')}</textarea></label>
      <div class="row"><button class="btn primary small" id="d-save" ${dis}>保存对白</button><button class="btn ghost small" id="d-lines" ${dis}>改为逐句编辑</button></div>
      <div class="sub">整镜音轨</div>
      ${audios.length?audios.map(t=>`<div class="audio-row"><input type="radio" name="aud" value="${esc(t.id)}" ${s.selected_takes.audio===t.id?'checked':''} ${dis} aria-label="选用${esc(t.label)}"><audio src="${L.media(t.file)}" controls preload="none"></audio><span class="faint">${esc(t.label)}</span></div>`).join(''):'<p class="faint" style="margin:0">还没有音轨。没有配音时，导出会使用画面原声或静音，并保留字幕。</p>'}
      <div class="row"><button class="btn small" id="a-import" ${dis}>导入音轨</button><button class="btn small" id="a-gen" ${dis||(!L.serviceConnected('audio')?'disabled':'')}><span class="spark">✦</span>AI 配音</button></div>
      ${!L.serviceConnected('audio')?'<p class="faint" style="margin:0">配音服务未连接，可以先导入录好的音轨。</p>':''}`;
  }
  return `<div class="row"><span class="sub" style="margin:0">逐句对白</span><span class="spacer"></span><button class="btn ghost small" id="d-plain" ${dis}>改回整段</button></div>
    ${s.lines.map((l,i)=>{const own=audios.filter(t=>!t.line_id||t.line_id===l.id);
      return `<div class="line-card" data-i="${i}"><div class="row"><select class="select" data-k="speaker" data-track style="width:auto" ${dis}><option value="">旁白</option>${speakers.map(a=>`<option value="${esc(a.id)}" ${l.speaker_asset_id===a.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select><span class="spacer"></span><button class="btn ghost small" data-del ${dis}>删除</button></div>
 <textarea class="textarea" data-k="text" data-track rows="2" maxlength="2000" style="min-height:56px" ${dis}>${esc(l.text||'')}</textarea>
 ${l.id?`<div class="row"><select class="select" data-k="take" style="flex:1" ${dis}><option value="">未选音轨</option>${own.map(t=>`<option value="${esc(t.id)}" ${l.audio_take_id===t.id?'selected':''}>${esc(t.label)}</option>`).join('')}</select>
          <input class="input num" data-k="start" type="number" min="0" step="0.1" placeholder="起点 秒" style="width:92px" value="${l.audio_start??''}" ${dis} aria-label="起点（秒）"></div>
 <div class="row"><button class="btn small" data-imp ${dis}>导入这句音轨</button><button class="btn small" data-gen ${dis||(!L.serviceConnected('audio')?'disabled':'')}><span class="spark">✦</span>AI 配音</button><span class="spacer"></span><button class="btn ghost small" data-bind ${dis}>应用音轨</button></div>`:'<p class="faint" style="margin:0">保存后可以为这句添加音轨。</p>'}</div>`}).join('')}
    <div class="row"><button class="btn small" id="l-add" ${dis}>添加一句</button><span class="spacer"></span><button class="btn primary small" id="l-save" ${dis}>保存对白</button></div>
    <p class="faint" style="margin:0">字幕按每句的音轨时间排列；没有音轨时按字数估算。</p>`;
}
function readLines(view,s){
  return $$('.line-card',view).map((c,i)=>({id:s.lines[i]?.id||null,speaker_asset_id:$('[data-k="speaker"]',c).value||null,text:$('[data-k="text"]',c).value}));
}
function bindDialogue(view,p,s){
  const setLines=(lines,button=null)=>L.busy(button,async()=>{
    await L.production('set_lines',{shot_id:s.id,lines});
    L.S.dirty=false;
    L.toast('对白已保存');L.render();
  });
  if(!Array.isArray(s.lines)){
    $('#d-save',view).onclick=e=>L.busy(e.currentTarget,()=>saveShot(s.id,x=>{x.dialogue=$('#d-text',view).value},'对白已保存'));
    $('#d-lines',view).onclick=e=>{
      const text=$('#d-text',view).value.trim();
      return setLines(text?L.linesFromDialogue(text):[],e.currentTarget);
    };
    $$('[name="aud"]',view).forEach(r=>r.onchange=()=>L.busy(null,async()=>{await L.production('select_take',{shot_id:s.id,take_id:r.value});L.toast('已选用这条音轨');L.render()}));
    $('#a-import',view).onclick=e=>L.busy(e.currentTarget,async()=>{const f=await L.pickFile('audio/*');if(!f)return;const file=await L.upload(f,'audio');await L.production('add_take',{shot_id:s.id,kind:'audio',file,label:f.name.slice(0,60)});const t=L.shot().takes.at(-1);await L.production('select_take',{shot_id:s.id,take_id:t.id});L.toast('音轨已导入并选用');L.render()});
    $('#a-gen',view).onclick=e=>L.busy(e.currentTarget,async()=>{if(await L.run('audio',{shot_id:s.id}))L.toast('已开始配音')});
    return;
  }
  $('#d-plain',view).onclick=async()=>{if(await L.confirmBox('改回整段对白？','逐句的音轨选择会被清除，对白文字合并为一段。','改回整段'))setLines(null)};
  $('#l-add',view).onclick=async()=>{
    const lines=readLines(view,s);
    const text=await L.prompt('添加一句','对白','','添加');
    if(text?.trim())await setLines([...lines,{text:text.trim(),speaker_asset_id:null}]);
  };
  $('#l-save',view).onclick=e=>setLines(readLines(view,s),e.currentTarget);
  $$('.line-card',view).forEach(c=>{
    const i=+c.dataset.i,l=s.lines[i];
    $('[data-del]',c).onclick=()=>setLines(L.removeLine(readLines(view,s),i));
    if(!l.id)return;
    $('[data-imp]',c).onclick=e=>L.busy(e.currentTarget,async()=>{const f=await L.pickFile('audio/*');if(!f)return;const file=await L.upload(f,'audio');await L.production('add_take',{shot_id:s.id,kind:'audio',file,label:f.name.slice(0,60),line_id:l.id});L.toast('已导入，选好后点「应用音轨」');L.render()});
    $('[data-gen]',c).onclick=e=>L.busy(e.currentTarget,async()=>{if(await L.run('audio',{shot_id:s.id,line_id:l.id}))L.toast('已开始为这句配音')});
    $('[data-bind]',c).onclick=e=>L.busy(e.currentTarget,async()=>{
      const take=$('[data-k="take"]',c).value,raw=$('[data-k="start"]',c).value;
      await L.production('bind_line_audio',{shot_id:s.id,line_id:l.id,take_id:take||null,start:raw===''?null:Number(raw)});L.toast(take?'这句音轨已应用':'已取消这句音轨');L.render();
    });
  });
}

/* 素材 */
function media(p,s,it){
  const dis=s.locked?'disabled':'';
  const visuals=s.takes.filter(t=>t.kind!=='audio'),basis=it?.basis;
  const sel=s.selected_takes||{};
  const binds=Object.entries(s.asset_bindings||{}).map(([aid,vid])=>({a:p.assets.find(a=>a.id===aid),vid})).filter(x=>x.a);
  const sv=s.video&&s.takes.find(t=>t.id===sel.video);
  return `${it?.stale_media?`<div class="notice stop"><div class="grow"><b>画面来自修改前的镜头</b><p class="muted">镜头内容改过了。确认这张画面仍然适用，或者换一个新的。</p></div></div>
      <div class="row"><button class="btn primary small" id="keep-media" ${dis}>确认沿用</button><button class="btn small" id="swap-media" ${dis}>导入新画面</button></div>`:''}
    <div class="row"><span class="sub" style="margin:0">画面候选（${visuals.length}）</span><span class="spacer"></span><button class="btn small" id="m-import" ${dis}>导入图片或视频</button></div>
    ${visuals.length?`<div class="takes">${visuals.map(t=>{const on=sel[t.kind]===t.id,old=L.candidateOutdated(t,basis),part=L.isPartialTake(t,s);
      return `<button class="take" data-take="${esc(t.id)}" aria-pressed="${on}" ${dis||(part?'disabled':'')} title="${esc(t.label)}">${mediaTag(t.file)}<span class="tag">${on?'使用中':t.source==='import'?'导入':t.source==='assembly'?'拼接':'生成'}</span>${old?'<span class="warn">设定已变</span>':''}${part?'<span class="warn">局部片段</span>':''}</button>`}).join('')}</div>`
    :'<p class="faint" style="margin:0">还没有画面。导入一张图片或一段视频作为这一镜的画面。</p>'}
    ${sv?`<div class="sub">剪辑范围</div><div class="grid2"><label class="field"><span>起点（秒）</span><input class="input num" id="c-in" type="number" min="0" step="0.1" value="${s.clip?.trim_start??s.trim_start??0}" ${dis}></label>
      <label class="field"><span>终点（秒，可空）</span><input class="input num" id="c-out" type="number" min="0" step="0.1" value="${s.clip?.trim_end??''}" ${dis}></label></div>
      <div class="row"><button class="btn small" id="c-save" ${dis}>应用剪辑</button><span class="faint">较短的素材停在最后一帧，较长的会被截断。</span></div>`:''}
    ${binds.length?`<div class="sub">角色与素材版本</div>${binds.map(({a,vid})=>`<div class="row"><span style="flex:1">${esc(a.name)}</span><select class="select" data-bind-asset="${esc(a.id)}" style="width:auto;max-width:190px" ${dis}>${a.versions.map(v=>`<option value="${esc(v.id)}" ${v.id===vid?'selected':''}>${esc(v.label||v.outfit||'版本')}${v.id===a.selected_version?'（当前）':''}</option>`).join('')}</select></div>`).join('')}
      <button class="btn ghost small" id="bind-current" style="align-self:flex-start" ${dis}>全部更新为素材当前版本</button>`:''}`;
}
function bindMedia(view,p,s,list,it){
  const importVisual=async()=>{const f=await L.pickFile('image/*,video/mp4,video/quicktime');if(!f)return;const file=await L.upload(f,'visual');const kind=L.isVideo(file)?'video':'image';
    await L.production('add_take',{shot_id:s.id,kind,file,label:f.name.slice(0,60)});const t=L.shot().takes.at(-1);await L.production('select_take',{shot_id:s.id,take_id:t.id});L.toast('画面已导入并选用');L.render()};
  $('#m-import',view).onclick=e=>L.busy(e.currentTarget,importVisual);
  $('#swap-media',view)?.addEventListener('click',e=>L.busy(e.currentTarget,importVisual));
  $('#keep-media',view)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{await L.production('confirm_media',{shot_id:s.id});L.done('已确认沿用这张画面');L.render()}));
  $$('[data-take]',view).forEach(b=>b.onclick=()=>L.busy(b,async()=>{
    const t=s.takes.find(x=>x.id===b.dataset.take);if(b.getAttribute('aria-pressed')==='true')return;
    if(L.candidateOutdated(t,it?.basis)&&!(await L.confirmBox('选用旧画面？','这个候选是用设定改动前的内容生成的，选用后需要重新确认画面。','仍要选用')))return;
    await L.production('select_take',{shot_id:s.id,take_id:t.id});
    L.toast(item(L.shot())?.stale_media?'已选中旧画面，请确认沿用或更换':'已选用');L.render();
  }));
  $('#c-save',view)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{
    const a=Number($('#c-in',view).value||0),raw=$('#c-out',view).value,b=raw===''?null:Number(raw);
    await L.production('set_clip',{shot_id:s.id,source_take_id:s.selected_takes.video,trim_start:a,trim_end:b});L.toast('剪辑已应用，这一镜需要重新确认');L.render();
  }));
  $$('[data-bind-asset]',view).forEach(sel=>sel.onchange=()=>L.busy(null,async()=>{await L.production('bind_asset_version',{shot_id:s.id,asset_id:sel.dataset.bindAsset,version_id:sel.value});L.toast('已更换版本，这一镜需要重新确认');L.render()}));
  $('#bind-current',view)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{await L.production('bind_current',{shot_id:s.id});L.toast('已更新为当前版本');L.render()}));
}

/* 制作：制作准备、片段选用与本机拼接 */
function make(p,s){
  return `<div id="prep" class="side-stack"><p class="faint">正在读取制作准备…</p></div>`;
}
const generationModes={
  text_to_image:'文字生图',reference_to_image:'参考图生图',
  text_to_video:'文字生视频',reference_to_video:'参考图生视频',image_to_video:'首帧生视频',start_end_frames:'首尾帧生视频',
};
const referenceRoles={reference_image:'参考图',first_frame:'视频首帧',last_frame:'视频尾帧'};

async function bindMake(view,p,s){
  const box=$('#prep',view);
  const open=()=>L.api('/api/preparation/open',{project_id:p.id,shot_id:s.id});
  try{
    let data=await open();
    if(!box.isConnected)return;
    const plan=structuredClone(data.plan),chosen={...(s.segment_sources||{})};
    const nonces=new Map();
    let changed=false;
    const dis=s.locked?'disabled':'';
    const choices=kind=>Object.entries(data.models||{}).flatMap(([model,profile])=>
      profile.kind===kind?profile.modes.map(mode=>({model,mode,profile})):[]);
    const choiceFor=seg=>choices(seg.kind).find(c=>c.model===seg.model&&c.mode===seg.mode);
    const opt=(value,label,selected=false)=>`<option value="${esc(value)}" ${selected?'selected':''}>${esc(label)}</option>`;
    const pick=seg=>s.takes.filter(t=>t.kind===seg.kind);
    const generationOptions=seg=>{
      const selected=choiceFor(seg),profile=selected?.profile;
      return `<label class="field"><span>生成方式与模型</span><select class="select" data-model ${dis}>
        ${opt('','请选择生成方式')}${choices(seg.kind).map((c,i)=>opt(i,
          (generationModes[c.mode]||c.mode)+' · '+(c.profile.label||c.model),c.model===seg.model&&c.mode===seg.mode)).join('')}
        </select></label>
        ${profile?`<label class="field"><span>分辨率</span><select class="select" data-resolution ${dis}>
          ${opt('','请选择分辨率')}${profile.resolutions.map(r=>opt(r,r==='auto'?'由模型决定':r,r===seg.parameters.resolution)).join('')}
        </select></label>
        ${Object.entries(profile.role_limits).filter(([,limit])=>limit>0).map(([role,limit])=>{
          const ids=new Set(seg.references.filter(r=>r.role===role).map(r=>r.reference_id));
          return `<label class="field"><span>${esc(referenceRoles[role]||role)}</span><select class="select" aria-label="${esc(referenceRoles[role]||role)}" data-role="${esc(role)}" ${limit>1?'multiple':''} ${dis}>
            ${limit===1?opt('','请选择图片'):''}${data.references.map(r=>opt(r.reference_id,r.label,ids.has(r.reference_id))).join('')}
          </select></label>`;
        }).join('')}`:''}`;
    };
    const isActive=seg=>L.S.data.jobs.some(job=>job.project_id===p.id&&job.target_shot_id===s.id&&job.kind===seg.kind
      &&(L.jobActive(job.state)||job.state==='interrupted')&&job.generation_unit?.segment?.id===seg.id);
    const canGenerate=seg=>!s.locked&&!changed&&!L.S.dirty&&data.status?.ready&&!!data.status.plan_digest&&choiceFor(seg)?.profile.connected&&!isActive(seg);
    const syncButtons=()=>{
      $$('[data-generate]',box).forEach((b,i)=>{b.disabled=!canGenerate(plan.segments[i]);b.textContent=isActive(plan.segments[i])?'已有生成任务':plan.segments[i].kind==='image'?'生成图片':'生成视频'});
      const hint=$('[data-prep-draft]',box);
      if(hint)hint.hidden=!changed;
    };
    const edit=()=>{changed=true;L.S.dirty=true;syncButtons()};
    const savePlan=async segments=>{
      if($('#c-save')?.hidden===false)throw Error('请先保存镜头下方的修改，再保存制作准备');
      const r=await L.api('/api/preparation/save',{project_id:p.id,shot_id:s.id,revision:data.revision,basis:data.basis,plan:{...plan,segments}});
      L.S.dirty=false;
      L.replaceProject(r.project);await L.refresh();L.render();
      L.toast(r.status.ready?'制作准备已保存，可以生成':'制作准备已保存');
    };
    const submit=async seg=>{
      if(!canGenerate(seg))throw Error('请先保存制作准备，并检查是否已有生成任务');
      const title=seg.kind==='image'?'生成图片':'生成视频';
      const request={project_id:p.id,episode_id:s.episode_id,shot_id:s.id,kind:seg.kind,
        segment_id:seg.id,preparation_digest:data.status.plan_digest};
      const quote_digest=await L.confirmGeneration(title,request);
      if(!quote_digest)return;
      if(!canGenerate(seg))throw Error('制作准备已变化，请重新保存后生成');
      const nonce=nonces.get(seg.id)||crypto.randomUUID();
      nonces.set(seg.id,nonce);
      await L.api('/api/jobs',{...request,quote_digest,nonce});
      nonces.delete(seg.id);
      await L.refresh();
      const sheet=$('#pop',view);
      if(sheet){if(sheet.open)sheet.close();L.ui.tab=null}
      L.render();L.openDrawer();L.toast('已提交生成，完成后在「素材」查看候选');
    };
    function renderPanel(){
      const issues=[...new Set((data.status?.issues||[]).map(i=>i.message))];
      box.innerHTML=`
        <details ${data.fal_configured?'':'open'}><summary>${data.fal_configured?'fal Key 已配置':'连接图片与视频服务'}</summary>
          <label class="field"><span>fal API Key</span><input class="input" data-fal-key type="password" autocomplete="off"></label>
          <button class="btn small" data-connect-fal>保存 Key 到本机</button>
        </details>
        ${issues.length?`<div class="notice ${s.preparation?'wait':''}"><div class="grow">${issues.map(message=>`<p class="muted">${esc(message)}</p>`).join('')}</div></div>`:'<p class="muted">制作准备已就绪。</p>'}
        <p class="faint" data-prep-draft hidden>保存修改后才能生成。</p>
        ${plan.segments.map((g,i)=>`<div class="line-card" data-seg="${esc(g.id)}">
          <div class="row prep-segment-head"><b class="num">片段 ${i+1}</b><span class="faint num">${L.clock(g.start)} – ${L.clock(g.end)}</span><span class="spacer"></span>
            <div class="seg">${['image','video'].map(k=>`<button data-kind="${k}" aria-pressed="${g.kind===k}" ${dis}>${k==='image'?'图片':'视频'}</button>`).join('')}</div></div>
          <label class="field"><span>画面与动作</span><textarea class="textarea" data-ins rows="2" style="min-height:56px" maxlength="10000" ${dis}>${esc(g.instruction||'')}</textarea></label>
          ${plan.segments.length>1?`<label class="field"><span>开始状态</span><input class="input" data-state="start_state" maxlength="10000" value="${esc(g.start_state)}" ${dis}></label>
            <label class="field"><span>结束状态</span><input class="input" data-state="end_state" maxlength="10000" value="${esc(g.end_state)}" ${dis}></label>`:''}
          <div class="side-stack" style="gap:8px" data-generation-options>${generationOptions(g)}</div>
          ${plan.segments.length>1?`<label class="field"><span>选用素材</span><select class="select" data-src ${dis}>${opt('','未选择')}${pick(g).map(t=>opt(t.id,t.label,chosen[g.id]?.take_id===t.id)).join('')}</select></label>`:''}
          <button class="btn small" data-generate disabled></button>
        </div>`).join('')}
        <div class="row wrap"><button class="btn small" id="p-split" ${dis}>平分为两段</button>${plan.segments.length>1?`<button class="btn small" id="p-merge" ${dis}>合并为一段</button>`:''}<span class="spacer"></span><button class="btn primary small" id="p-save" ${dis}>保存制作准备</button></div>
        ${s.preparation&&plan.segments.length>1?`<div class="row wrap"><button class="btn small" id="p-bind" ${dis}>确认片段选用</button><button class="btn small" id="p-assemble" ${dis}>拼接成整镜</button></div>`:''}`;
      $$('[data-seg]',box).forEach((card,i)=>{
        const seg=plan.segments[i];
        const options=$('[data-generation-options]',card);
        $$('[data-kind]',card).forEach(button=>button.onclick=()=>{
          if(seg.kind===button.dataset.kind)return;
          seg.kind=button.dataset.kind;
          seg.model=null;seg.mode=null;seg.references=[];
          seg.parameters={aspect_ratio:seg.parameters.aspect_ratio,resolution:null};
          $$('[data-kind]',card).forEach(b=>b.setAttribute('aria-pressed',b===button));
          options.innerHTML=generationOptions(seg);
          const sources=$('[data-src]',card);
          if(sources)sources.innerHTML=opt('','未选择')+pick(seg).map(t=>opt(t.id,t.label)).join('');
          delete chosen[seg.id];edit();
        });
        card.oninput=e=>{
          if(e.target.matches('[data-ins]')){seg.instruction=e.target.value;edit()}
          if(e.target.matches('[data-state]')){seg[e.target.dataset.state]=e.target.value;edit()}
        };
        card.onchange=e=>{
          const input=e.target;
          if(input.matches('[data-model]')){
            const selected=input.value===''?null:choices(seg.kind)[Number(input.value)];
            seg.model=selected?.model||null;seg.mode=selected?.mode||null;seg.references=[];
            seg.parameters={aspect_ratio:seg.parameters.aspect_ratio,resolution:selected?.profile.resolutions[0]||null};
            options.innerHTML=generationOptions(seg);$('[data-model]',options).focus();edit();
          }
          if(input.matches('[data-resolution]')){seg.parameters.resolution=input.value||null;edit()}
          if(input.matches('[data-role]')){
            const role=input.dataset.role;
            seg.references=[...seg.references.filter(r=>r.role!==role),...[...input.selectedOptions].filter(o=>o.value).map(o=>({role,reference_id:o.value}))];
            edit();
          }
          if(input.matches('[data-src]'))chosen[seg.id]={take_id:input.value,trim_start:0};
        };
        $('[data-generate]',card).onclick=e=>L.busy(e.currentTarget,()=>submit(seg));
      });
      $('[data-connect-fal]',box).onclick=e=>L.busy(e.currentTarget,async()=>{
        const field=$('[data-fal-key]',box);
        await L.api('/api/settings/fal',{api_key:field.value.trim()});field.value='';
        data=await open();if(!box.isConnected)return;
        renderPanel();L.toast('已保存 fal Key，尚未运行模型');
      });
      $('#p-save',box).onclick=e=>L.busy(e.currentTarget,()=>savePlan(plan.segments));
      $('#p-split',box).onclick=e=>L.busy(e.currentTarget,()=>{
        const last=plan.segments.at(-1),mid=Math.round((last.start+last.end)/2*10)/10;
        if(mid<=last.start||mid>=last.end)throw Error('片段太短，不能再分');
        return savePlan([...plan.segments.slice(0,-1),{...last,end:mid},{...structuredClone(last),id:crypto.randomUUID(),start:mid,references:[]}]);
      });
      $('#p-merge',box)?.addEventListener('click',e=>L.busy(e.currentTarget,()=>savePlan([{...plan.segments[0],end:plan.segments.at(-1).end}])));
      $('#p-bind',box)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{
        if(changed)throw Error('请先保存制作准备');
        const sources={};
        for(const seg of plan.segments){
          const source=chosen[seg.id];
          if(!source?.take_id)throw Error('请为每个片段选好素材');
          sources[seg.id]={take_id:source.take_id,trim_start:source.trim_start||0};
        }
        try{await L.production('bind_segment_sources',{shot_id:s.id,sources})}
        catch(err){if(!/返工前/.test(err.message))throw err;if(!await L.confirmBox('使用返工前的片段素材？',err.message,'仍然使用'))return;await L.production('bind_segment_sources',{shot_id:s.id,sources,acknowledge_stale:true})}
        L.toast('片段选用已确认');L.render();
      }));
      $('#p-assemble',box)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{
        if(changed)throw Error('请先保存制作准备');
        if(await L.run('assemble',{shot_id:s.id}))L.toast('正在本机拼接，完成后出现在画面候选里');
      }));
      syncButtons();
    }
    renderPanel();
  }catch(e){if(box.isConnected)box.innerHTML=`<div class="notice stop"><p>${esc(e.message)}</p></div>`}
}

/* 添加镜头 */
async function addShot(){
  if(!await L.leaveOk())return;
  const p=L.project(),ep=L.episode();
  const post=async fields=>{const r=await L.api('/api/shots',{project_id:p.id,episode_id:ep.id,revision:p.revision,fields});L.replaceProject(r.project);await L.refresh();L.S.sid=r.shot_id;L.ui.tab=null;L.remember();L.render();L.toast('已添加镜头')};
  if(!strict(p))return L.busy(null,()=>post({description:'',duration:3}));
  const scenes=ep.creative_spec?.screenplay?.scenes||[],chars=p.assets.filter(a=>a.kind==='character'),places=p.assets.filter(a=>a.kind==='scene');
  const m=L.modal({title:'添加镜头',body:`
    ${scenes.length?`<label class="field"><span>场景</span><select class="select" id="n-scene">${scenes.map(x=>`<option value="${esc(x.id)}">${esc(x.title||x.heading||x.id)}</option>`).join('')}</select></label>`
      :`<label class="field"><span>地点</span><select class="select" id="n-loc">${places.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')}</select></label>`}
    <div class="grid2"><label class="field"><span>画面主体</span><select class="select" id="n-sub">${p.assets.filter(a=>a.kind!=='voice').map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')}</select></label>
      <label class="field"><span>角色造型</span><select class="select" id="n-ver"></select></label></div>
    <label class="field"><span>这一镜的作用</span><input class="input" id="n-purpose" maxlength="500" placeholder="例如：交代人物处境"></label>
    <label class="field"><span>画面描述</span><textarea class="textarea" id="n-desc" rows="3" maxlength="4000"></textarea></label>
    <label class="field"><span>时长（秒）</span><input class="input num" id="n-dur" type="number" min="1" max="60" step="0.5" value="3"></label>`,
    foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="n-ok">添加镜头</button>`});
  const fill=()=>{const a=p.assets.find(x=>x.id===$('#n-sub',m).value);const vs=a?.kind==='character'?a.versions.filter(v=>v.outfit):[];
    $('#n-ver',m).innerHTML=vs.length?vs.map(v=>`<option value="${esc(v.id)}">${esc(v.outfit)}</option>`).join(''):`<option value="">${a?.kind==='character'?'请先在角色页设定造型':'不需要'}</option>`};
  $('#n-sub',m).onchange=fill;fill();
  $('#n-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    await post({scene_id:$('#n-scene',m)?.value,location_id:$('#n-loc',m)?.value,subject_id:$('#n-sub',m).value,version_id:$('#n-ver',m).value||null,
      purpose:$('#n-purpose',m).value,description:$('#n-desc',m).value.trim()||(()=>{throw Error('请写下这一镜的画面描述')})(),duration:Number($('#n-dur',m).value)||3});m.close();
  });
}

/* AI 改写这一镜 */
async function reviseDialog(s){
  if(!await L.needService('revision'))return;
  const m=L.modal({title:'AI 改写这一镜',body:`<p class="muted" style="margin:0">${esc(L.shotTitle(s))}</p>
    <label class="field"><span>想怎么改</span><textarea class="textarea" id="rv-text" rows="5" maxlength="2000" placeholder="例如：改成近景，雨更大，她先沉默再开口。"></textarea></label>
    <p class="faint" style="margin:0">AI 只改这一镜的文字设定，完成后会先给你看修改前后的差异，确认了才会应用。画面和音轨不会被替换。</p>`,
    foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="rv-ok"><span class="spark">✦</span>开始修改</button>`});
  $('#rv-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const instruction=$('#rv-text',m).value.trim();if(!instruction)throw Error('请写下想怎么改');
    m.close();if(await L.run('revision',{shot_id:s.id,instruction}))L.toast('已开始改写，完成后在生成记录里查看前后差异');
  });
}
})();
