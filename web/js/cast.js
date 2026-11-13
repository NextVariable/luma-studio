/* 角色与素材：角色造型版本、四视图、音色；场景、道具、风格、音色参考 */
(function(){
const {esc,$,$$}=L;
const KINDS={character:'角色',scene:'场景',prop:'道具',style:'风格',voice:'音色参考'};
const VIEWS={front:'正面',side:'侧面',three_quarter:'四分之三',back:'背面'};
const VOICES=['alloy','ash','ballad','coral','echo','fable','onyx','nova','sage','shimmer','verse','marin','cedar'];
const current=a=>a.versions.find(v=>v.id===a.selected_version)||a.versions[a.versions.length-1];
const picOf=a=>{const v=current(a);return v.views?.front||v.views?.three_quarter||v.file||null};
const usedBy=(p,a)=>p.shots.filter(s=>(s.asset_ids||[]).includes(a.id)).length;

L.views.cast=view=>{
  const p=L.project(),people=p.assets.filter(a=>a.kind==='character'),things=p.assets.filter(a=>a.kind!=='character');
  view.innerHTML=`<section class="cast">
    <div class="cast-head"><h1>角色与素材</h1><span class="spacer"></span>
      <button class="btn" id="suggest"><span class="spark">✦</span>AI 角色与场景建议${L.S.data.dify.assets?'':'（未连接）'}</button>
      <button class="btn primary" id="add-asset">新建素材</button></div>
    <div class="cast-list" data-scroll="assets" role="region" aria-label="角色和素材列表" tabindex="0">
    ${people.length?`<div class="people">${people.map(a=>{const pic=picOf(a),v=current(a);
      return `<button class="person" data-aid="${esc(a.id)}"><div class="portrait ${pic?'':'lit'}" style="${pic?`background-image:url('${L.thumb(pic)}')`:`background:${L.glow(a.id)}`}">${pic?'':esc(a.name.slice(0,1))}</div>
 <div class="meta"><h3>${esc(a.name)}</h3><div class="faint">${esc(v.outfit||'未设定造型')}</div><div class="faint">用于 ${usedBy(p,a)} 个镜头</div></div></button>`}).join('')}</div>`
    :`<div class="empty-state"><h2>还没有角色</h2><p>新建角色并设定造型，镜头会固定引用某个造型版本，换装不会悄悄改掉已确认的镜头。</p></div>`}
    ${things.length?`<div><div class="sub" style="margin-bottom:14px">场景、道具与风格</div><div class="things">${things.map(a=>{const pic=picOf(a);
      return `<button class="thing" data-aid="${esc(a.id)}"><div class="pic" style="${pic?`background-image:url('${L.thumb(pic)}')`:`background:${L.glow(a.id)}`}"></div><div><h3>${esc(a.name)}</h3><div class="faint">${KINDS[a.kind]} · 用于 ${usedBy(p,a)} 个镜头</div></div></button>`}).join('')}</div></div>`:''}
    </div>
  </section>`;
  $$('[data-aid]',view).forEach(b=>b.onclick=()=>assetDialog(b.dataset.aid));
  $('#add-asset',view).onclick=addAsset;
  $('#suggest',view).onclick=e=>L.busy(e.currentTarget,async()=>{const id=await L.run('assets');if(id){L.toast('已开始生成建议，完成后在生成记录里采纳');L.openDrawer()}});
};

function addAsset(){
  const m=L.modal({title:'新建素材',body:`<div class="field"><span>类型</span><div class="seg" id="kind">${Object.entries(KINDS).map(([k,v],i)=>`<button data-k="${k}" aria-pressed="${i===0}">${v}</button>`).join('')}</div></div>
    <label class="field"><span>名称</span><input class="input" id="a-name" maxlength="100"></label>
    <label class="field"><span>描述</span><textarea class="textarea" id="a-desc" maxlength="4000" rows="4" placeholder="外貌、性格、关键道具或场景特征。"></textarea></label>`,
    foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" id="a-ok">新建</button>`});
  let kind='character';
  $$('#kind button',m).forEach(b=>b.onclick=()=>{kind=b.dataset.k;$$('#kind button',m).forEach(x=>x.setAttribute('aria-pressed',x===b))});
  $('#a-ok',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const name=$('#a-name',m).value.trim();if(!name)throw Error('请填写名称');
    const id=crypto.randomUUID();
    await L.save(p=>p.assets.push({id,kind,name,description:$('#a-desc',m).value,version:1}));
    m.close();L.render();assetDialog(id);
  });
}

function assetDialog(aid){
  const p=L.project(),a=p.assets.find(x=>x.id===aid);if(!a)return;
  const v=current(a),isChar=a.kind==='character';
  const m=L.modal({title:a.name,wide:true,body:`
    <div class="grid2">
      <label class="field"><span>名称</span><input class="input" id="e-name" maxlength="100" value="${esc(a.name)}"></label>
      <div class="field"><span>类型</span><div class="input" style="opacity:.7">${KINDS[a.kind]}</div></div>
    </div>
    <label class="field"><span>描述</span><textarea class="textarea" id="e-desc" rows="3" maxlength="4000">${esc(a.description||'')}</textarea></label>
    <div class="row"><button class="btn small" id="e-save">保存名称和描述</button><span class="faint">只改当前设定，已绑定旧版本的镜头不受影响。</span></div>
    ${isChar?`<div class="sub">当前造型</div>
      <div class="grid2"><label class="field"><span>造型</span><input class="input" id="look-outfit" maxlength="500" value="${esc(v.outfit||'')}" placeholder="例如：黑色雨衣，短发"></label>
 <label class="field"><span>配音音色</span><select class="select" id="look-voice">${VOICES.map(x=>`<option ${((v.voice_id||'alloy')===x)?'selected':''}>${x}</option>`).join('')}</select></label></div>
      <div class="row"><button class="btn small" id="look-save">另存为新造型版本</button><span class="faint">换造型会清空四视图，需要重新上传。</span></div>
      <div class="views">${Object.entries(VIEWS).map(([k,label])=>{const f=v.views?.[k];return `<button class="view-slot" data-view="${k}" style="${f?`background-image:url('${L.media(f)}')`:''}">${f?'':'＋'}<span>${label}</span></button>`}).join('')}</div>`
    :`<div class="row"><button class="btn small" id="ref-up">上传参考图，生成新版本</button>${v.file?`<a class="faint" href="${L.media(v.file)}" target="_blank" rel="noopener">查看当前参考图</a>`:''}</div>`}
    <div class="sub">版本（${a.versions.length}）</div>
    <div class="versions">${[...a.versions].reverse().map(x=>`<button data-vid="${esc(x.id)}" ${x.id===a.selected_version?'aria-current="true"':''}><span class="dot ${x.id===a.selected_version?'ok':''}"></span>${esc(x.label||'版本')}<span class="faint">${esc((x.outfit||x.description||'').slice(0,40))}</span><span class="spacer"></span><span class="faint">${x.created?L.timeAgo(x.created):'初始'}</span></button>`).join('')}</div>
    <p class="faint" style="margin:0">选用其他版本只影响之后新绑定的镜头；已有镜头在「镜头 › 素材」里单独更新。</p>`});
  const reopen=()=>{L.render();assetDialog(aid)};
  $('#e-save',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const name=$('#e-name',m).value.trim();if(!name)throw Error('名称不能为空');
    await L.save(p2=>{const x=p2.assets.find(y=>y.id===aid);x.name=name;x.description=$('#e-desc',m).value});L.toast('已保存');reopen();
  });
  $$('.versions button',m).forEach(b=>b.onclick=()=>L.busy(b,async()=>{if(b.dataset.vid===a.selected_version)return;await L.production('asset_select',{asset_id:aid,version_id:b.dataset.vid});L.toast('已选用这个版本');reopen()}));
  if(isChar){
    $('#look-save',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      const outfit=$('#look-outfit',m).value.trim();if(!outfit)throw Error('请填写造型');
      await L.production('character_look',{asset_id:aid,outfit,voice_id:$('#look-voice',m).value,label:outfit.slice(0,40)});L.toast('已保存新造型版本');reopen();
    });
    $$('.view-slot',m).forEach(b=>b.onclick=()=>L.busy(b,async()=>{
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('character_look',{asset_id:aid,views:{...(v.views||{}),[b.dataset.view]:file},label:(v.outfit||'造型')+' · '+VIEWS[b.dataset.view]});
      L.toast('已上传'+VIEWS[b.dataset.view]+'视图');reopen();
    }));
  }else{
    $('#ref-up',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('asset_version',{asset_id:aid,file,label:'参考图 '+(a.versions.length+1),description:$('#e-desc',m).value});L.toast('参考图已保存为新版本');reopen();
    });
  }
}
L.assetDialog=assetDialog;
})();
