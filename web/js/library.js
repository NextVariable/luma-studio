/* 作品库 */
(function(){
const {esc,$,$$}=L;

function cover(p){
  const s=p.shots.find(x=>x.image||x.video);
  if(!s)return '<div class="cover empty"></div>';
  return `<div class="cover" style="background-image:url('${L.thumb(s.image||s.video)}')"></div>`;
}

L.views=L.views||new Object();
L.views.library=view=>{
  const ps=[...L.S.data.projects].sort((a,b)=>(b.updated||0)-(a.updated||0));
  const first=ps.find(p=>p.shots.some(s=>s.image||s.video));
  const f=first&&(first.shots.find(s=>s.image||s.video));
  L.setAmbient(f||(ps[0]?{id:ps[0].id}:null));
  view.innerHTML=`<section class="library">
    <div class="lib-compact"><h1>作品</h1><button class="btn" id="import-compact">导入短剧包</button><button class="btn primary" id="new-compact">新建作品</button></div>
    <div class="lib-hero">
      <h1>今天想拍什么？</h1>
      <p>写下故事，拆分镜头、设定角色，在本机导出成片。</p>
      <div class="slate big">
 <div class="slate-tag"><span>新作品</span><span class="num">第 1 集</span></div>
        <textarea class="slate-text" id="story" rows="3" maxlength="100000" placeholder="例如：雨夜，阿青在巷口等一个不会来的人。她看见来人，却转身离开。"></textarea>
        <div class="slate-row">
          <input class="slate-title" id="story-title" maxlength="200" placeholder="作品名称（可不填）">
          <div class="seg" id="story-fmt"><button data-f="16:9" aria-pressed="true">横屏</button><button data-f="9:16" aria-pressed="false">竖屏</button></div>
          <span class="spacer"></span>
          <button class="btn ghost" id="import-drama">导入短剧包</button>
   <button class="btn primary" id="new-work">开始创作</button>
        </div>
      </div>
    </div>
    ${ps.length?`<div class="lib-head"><h2>我的作品</h2><span class="faint num">${ps.length} 部</span></div>
      <div class="library-list" data-scroll="works" role="region" aria-label="作品列表" tabindex="0"><div class="wall">${ps.map(p=>{
        const sec=L.total(p.shots),s=p.shots.find(x=>x.image||x.video),pic=s&&(s.image||s.video);
        return `<button class="work" data-pid="${esc(p.id)}">
   <div class="cover ${pic?'':'lit'}" style="${pic?`background-image:url('${L.thumb(pic)}')`:`background:${L.glow(p.id)}`}"></div>
   <div class="meta"><h3>${esc(p.title)}</h3><div class="facts"><span>${p.episodes.length} 集</span><span>${p.shots.length} 镜</span><span class="num">${L.clock(sec)}</span>${p.updated?`<span>${L.timeAgo(p.updated)}</span>`:''}</div></div></button>`}).join('')}</div></div>`
    :`<p class="faint lib-empty">作品会出现在这里。</p>`}
  </section>`;
  let fmt='16:9';
  $$('#story-fmt button',view).forEach(b=>b.onclick=()=>{fmt=b.dataset.f;$$('#story-fmt button',view).forEach(x=>x.setAttribute('aria-pressed',x===b))});
  const story=$('#story',view);
  story.addEventListener('input',()=>{story.style.height='auto';story.style.height=Math.min(story.scrollHeight,260)+'px'});
  story.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter')$('#new-work',view).click()});
  $('#new-work',view).onclick=e=>L.busy(e.currentTarget,async()=>{
    const text=story.value.trim(),typed=$('#story-title',view).value.trim();
    if(!text&&!typed){story.focus();throw Error('先写下故事或作品名称，再开始创作')}
    const title=typed||(text?text.split(/[。，,.\n！？!?]/)[0].slice(0,18):'')||'未命名作品';
    await createWork(title,text,fmt);
  });
  $$('.work',view).forEach(b=>b.onclick=()=>L.openProject(b.dataset.pid));
  $('#import-drama',view).onclick=importDrama;
  $('#import-compact',view).onclick=importDrama;
  $('#new-compact',view).onclick=newWork;
};

async function createWork(title,script,format,modal){
  const p=await L.api('/api/projects',{title,script});
  if(format==='9:16')await L.api('/api/save',{project:{...p,creative_brief:{...p.creative_brief,format}},revision:p.revision});
  modal?.close();
  await L.refresh();L.toast('已新建「'+title+'」');L.openProject(p.id,'script');
}

function newWork(){
  const m=L.modal({title:'新建作品',body:`<label class="field"><span>作品名称</span><input class="input" id="nw-title" maxlength="200" placeholder="例如：雨夜"></label>
    <label class="field"><span>第 1 集剧本（可以之后再写）</span><textarea class="textarea" id="nw-script" rows="8" maxlength="100000" placeholder="写下故事、场景和对白。"></textarea></label>
    <label class="field"><span>画幅</span><select class="select" id="nw-format"><option value="16:9">横屏 16:9</option><option value="9:16">竖屏 9:16</option></select></label>`,
    foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="nw-ok">新建作品</button>`});
  $('#nw-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const title=$('#nw-title',m).value.trim();if(!title)throw Error('请填写作品名称');
    await createWork(title,$('#nw-script',m).value,$('#nw-format',m).value,m);
  });
}

function importDrama(){
  L.pickFile('.json,application/json').then(async file=>{
    if(!file)return;
    try{
      if(file.size>1.8*1024*1024)throw Error('短剧包超过 1.8 MB，请拆分后再导入');
      let bundle;try{bundle=JSON.parse(await file.text())}catch(e){throw Error('这个文件不是有效的 JSON 短剧包')}
      const pv=await L.api('/api/import/drama/preview',{bundle});
      const sum=pv.summary||new Object(),miss=sum.missing_reference_assets||[],unmapped=sum.unmapped_files||[];
      const shotNo=id=>{const i=(pv.shot_ids||[]).indexOf(id);return i>=0?'镜头 '+(i+1):id};
      const m=L.modal({title:'导入短剧包',wide:true,body:`
        <div><h3 style="margin:0 0 10px;font-size:20px">${esc(sum.title||'未命名作品')}</h3>
          <div class="row wrap"><span class="chip">${esc(sum.episodes)} 集</span><span class="chip">${esc(sum.shots)} 个镜头</span><span class="chip">${esc(sum.assets)} 项角色与素材</span><span class="chip num">${L.clock(sum.seconds)}</span></div></div>
        ${miss.length?`<div class="notice"><div class="grow"><b>${miss.length} 项素材还没有参考图</b><p class="muted">${miss.map(id=>esc((pv.asset_names||new Object())[id]||id)).join('、')}。导入后可以在「角色」里补上。</p></div></div>`:''}
        ${(pv.warnings||[]).length?`<div class="notice wait"><div class="grow"><b>导入前请留意（${pv.warnings.length}）</b>${pv.warnings.map(w=>`<p class="muted">${w.shot_id?esc(shotNo(w.shot_id))+'：':''}${esc(w.message||w.rule||String(w))}</p>`).join('')}</div></div>`:''}
        ${unmapped.length?`<div class="notice wait"><div class="grow"><b>有 ${unmapped.length} 个文件没有被读取</b><p class="muted">${unmapped.map(esc).join('、')}</p></div></div>`:''}
        <div><div class="sub" style="margin-bottom:8px">第一个镜头</div><div class="notice"><p>${esc(pv.sample?.description||'')}</p></div></div>
        <details><summary class="faint" style="cursor:pointer">字段如何对应到流幕</summary>
   <div class="map-grid">${Object.entries(pv.mapping||new Object()).map(([k,v])=>`<span class="faint">${esc(k.split('/').join(' / '))}</span><span>${esc(v)}</span>`).join('')}</div>
   <p class="faint">读取的文件：${(sum.source_files||[]).map(esc).join('、')}</p></details>
        <p class="faint" style="margin:0">导入会新建一部作品，不会改动已有作品；不会生成任何画面。</p>`,
 foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="dr-ok">导入为新作品</button>`});
      $('#dr-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
        const p=await L.api('/api/import/drama/apply',{id:pv.id,digest:pv.digest});
 m.close();await L.refresh();L.toast('短剧包已导入');L.openProject(p.id,'shots');
      });
    }catch(e){L.fail(e)}
  });
}
})();
