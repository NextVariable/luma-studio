/* 角色与素材：角色造型版本、四视图、音色；场景、道具、风格、音色参考 */
(function(){
const {esc,$,$$}=L;
const KINDS={character:'角色',scene:'场景',prop:'道具',style:'风格',voice:'音色参考'};
const VIEWS={front:'正面',side:'侧面',three_quarter:'四分之三',back:'背面'};
const SCENE_VIEWS={primary:'设定图',wide:'全景',detail:'细节',reverse:'反打'};
const VOICES=['alloy','ash','ballad','coral','echo','fable','onyx','nova','sage','shimmer','verse','marin','cedar'];
const current=a=>a.versions.find(v=>v.id===a.selected_version)||a.versions[a.versions.length-1];
const picOf=a=>{const v=current(a);return v.file||v.views?.front||v.views?.three_quarter||Object.values(v.views||{})[0]||null};
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
  const approvals=p.creative_brief?.visual_bible?.references||[];
  const approvedVersions=new Set(approvals.filter(r=>r.asset_id===aid&&r.role===a.kind).map(r=>r.version_id));
  const versionApprovals=approvals.filter(r=>r.asset_id===aid&&r.version_id===v.id);
  const approvedViews=new Set(versionApprovals.map(r=>r.view||'primary'));
  const versionUses={};p.shots.forEach(s=>{const vid=(s.asset_bindings||{})[aid];if(vid)versionUses[vid]=(versionUses[vid]||0)+1});
  const viewsOf=x=>[...(x.file?['primary']:[]),...Object.keys(x.views||{})];
  const viewLabel=view=>a.kind==='scene'?SCENE_VIEWS[view]||view:view==='primary'?'设定图':VIEWS[view]||view;
  const visuals=a.kind==='style'?(picOf(a)?[{view:'primary',file:picOf(a)}]:[]):
    [...(v.file?[{view:'primary',file:v.file}]:[]),...Object.entries(v.views||{}).map(([view,file])=>({view,file}))];
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
      <div class="row"><button class="btn small" id="look-save">另存为新造型版本</button><span class="faint">换造型会清空视图，需要重新上传。</span></div>
      <div class="views">${Object.entries(VIEWS).map(([k,label])=>{const f=v.views?.[k];return `<button class="view-slot" data-view="${k}" style="${f?`background-image:url('${L.media(f)}')`:''}">${f?'':'＋'}<span>${label}</span></button>`}).join('')}</div>`
    :a.kind==='scene'?`<div class="row"><button class="btn small" id="ref-up">上传主设定图，生成新版本</button>${v.file?`<a class="faint" href="${L.media(v.file)}" target="_blank" rel="noopener">查看当前主设定图</a>`:''}</div>
      <div class="views">${Object.entries(SCENE_VIEWS).filter(([k])=>k!=='primary').map(([k,label])=>{const f=v.views?.[k];return `<button class="view-slot" data-scene-view="${k}" style="${f?`background-image:url('${L.media(f)}')`:''}">${f?'':'＋'}<span>${label}</span></button>`}).join('')}</div>`
    :`<div class="row"><button class="btn small" id="ref-up">上传参考图，生成新版本</button>${v.file?`<a class="faint" href="${L.media(v.file)}" target="_blank" rel="noopener">查看当前参考图</a>`:''}</div>`}
    ${['character','scene'].includes(a.kind)?'<button class="btn small" id="asset-images">生成参考与比较候选</button>':''}
    ${visuals.length?`<div class="sub">当前版本参考（${versionApprovals.length} / ${visuals.length} 已批准）</div>
      ${visuals.some(slot=>!approvedViews.has(slot.view))?'<p class="notice wait" style="margin:0 0 8px">这些视图尚未批准，正式生成不会使用；请逐个批准，或在报价中明确确认本次使用。</p>':''}
      <div class="views">${visuals.map(slot=>{const ok=approvedViews.has(slot.view);return `<figure class="view-slot" style="margin:0">
        <img src="${L.media(slot.file)}" alt="${esc(a.name)} ${esc(viewLabel(slot.view))}" style="max-width:100%;max-height:20vh;object-fit:contain">
        <figcaption><span class="chip">${ok?'已批准':'未批准'}</span><span>${esc(viewLabel(slot.view))}</span><button class="btn small" data-approve-view="${esc(slot.view)}" ${ok?'disabled':''}>${ok?'已批准':'批准此视图'}</button></figcaption></figure>`}).join('')}</div>`
      :'<p class="faint">这个版本还没有参考图。批准后才会进入分镜生成。</p>'}
    <div class="sub">版本（${a.versions.length}）</div>
    <div class="versions">${[...a.versions].reverse().map(x=>{const count=approvals.filter(r=>r.asset_id===aid&&r.version_id===x.id).length,total=viewsOf(x).length;
      return `<button data-vid="${esc(x.id)}" ${x.id===a.selected_version?'aria-current="true"':''}><span class="dot ${x.id===a.selected_version?'ok':''}"></span>${esc(x.label||'版本')}<span class="faint">${esc((x.outfit||x.description||'').slice(0,40))}</span><span class="spacer"></span>${total?`<span class="chip">${count}/${total} 已批准</span>`:'<span class="chip">无参考图</span>'}${versionUses[x.id]?`<span class="faint">绑定 ${versionUses[x.id]} 镜</span>`:''}<span class="faint">${x.created?L.timeAgo(x.created):'初始'}</span></button>`}).join('')}</div>
    <p class="faint" style="margin:0">“选用”只改变当前版本，不会改写任何已有镜头的绑定；镜头需在「镜头 › 素材」中单独更新。“已批准”按版本和视图独立记录，新版本不会继承旧版本的批准。</p>`});
  const reopen=()=>{L.render();assetDialog(aid)};
  $('#asset-images',m)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{
    m.close();await assetImages(p,a,v);
  }));
  $$('[data-approve-view]',m).forEach(button=>button.onclick=e=>L.busy(e.currentTarget,async()=>{
    const view=button.dataset.approveView,slot=visuals.find(x=>x.view===view);
    if(!slot?.file)return;
    if(approvedViews.has(view)&&!await L.confirmBox('替换这个视图的已批准参考？','新的参考用于后续生成，既有素材仍保留。','替换参考图'))return;
    const source=await L.prompt('登记参考图','图片来源或制作说明','','批准参考图');
    if(!source?.trim())return;
    const saved=await L.api('/api/assets/approve-reference',{project_id:p.id,asset_id:aid,version_id:v.id,file:slot.file,view,
      revision:p.revision,source:source.trim(),replace:approvedViews.has(view)});
    L.replaceProject(saved);m.close();L.render();L.toast('已批准 '+viewLabel(view));
  }));
  $('#e-save',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const name=$('#e-name',m).value.trim();if(!name)throw Error('名称不能为空');
    await L.save(p2=>{const x=p2.assets.find(y=>y.id===aid);x.name=name;x.description=$('#e-desc',m).value});L.toast('已保存');reopen();
  });
  $$('.versions button',m).forEach(b=>b.onclick=()=>L.busy(b,async()=>{if(b.dataset.vid===a.selected_version)return;await L.production('asset_select',{asset_id:aid,version_id:b.dataset.vid});L.toast('已选用为当前版本；已有镜头绑定不变');reopen()}));
  if(isChar){
    $('#look-save',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      const outfit=$('#look-outfit',m).value.trim();if(!outfit)throw Error('请填写造型');
      await L.production('character_look',{asset_id:aid,outfit,voice_id:$('#look-voice',m).value,label:outfit.slice(0,40)});L.toast('已保存新造型版本');reopen();
    });
    $$('.view-slot[data-view]',m).forEach(b=>b.onclick=()=>L.busy(b,async()=>{
      const label=VIEWS[b.dataset.view];
      if(!await L.confirmBox(`上传「${label}」会创建新的造型版本`,'新版本不会继承旧版本的批准状态；已有镜头仍绑定原版本，不会被改动。上传后需要批准这张视图，正式生成才会使用。','创建新版本并继续'))return;
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('character_look',{asset_id:aid,views:{...(v.views||{}),[b.dataset.view]:file},label:(v.outfit||'造型')+' · '+label});
      L.toast('已创建新造型版本并上传'+label+'视图，请批准');reopen();
    }));
  }else if(a.kind==='scene'){
    $('#ref-up',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      if(!await L.confirmBox('上传主设定图会创建新的场景版本','新版本不会继承旧版本的批准状态；已有镜头仍绑定原版本，不会被改动。','创建新版本并继续'))return;
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('asset_version',{asset_id:aid,file,label:'主设定图 '+(a.versions.length+1),description:$('#e-desc',m).value});L.toast('主设定图已保存为新版本，请批准');reopen();
    });
    $$('.view-slot[data-scene-view]',m).forEach(b=>b.onclick=()=>L.busy(b,async()=>{
      const label=SCENE_VIEWS[b.dataset.sceneView];
      if(!await L.confirmBox(`上传场景「${label}」会创建新的版本`,'新版本不会继承旧版本的批准状态；已有镜头仍绑定原版本，不会被改动。','创建新版本并继续'))return;
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('asset_view',{asset_id:aid,view:b.dataset.sceneView,file,label});
      L.toast('已保存'+label+'视图，请批准');reopen();
    }));
  }else{
    $('#ref-up',m).onclick=e=>L.busy(e.currentTarget,async()=>{
      if(!await L.confirmBox('上传参考图会创建新的素材版本','新版本不会继承旧版本的批准状态；已有镜头仍绑定原版本，不会被改动。','创建新版本并继续'))return;
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('asset_version',{asset_id:aid,file,label:'参考图 '+(a.versions.length+1),description:$('#e-desc',m).value});L.toast('参考图已保存为新版本，请批准');reopen();
    });
    $$('[data-scene-view]',m).forEach(b=>b.onclick=()=>L.busy(b,async()=>{
      const f=await L.pickFile('image/*');if(!f)return;
      const file=await L.upload(f,'visual');
      await L.production('asset_view',{asset_id:aid,view:b.dataset.sceneView,file,label:SCENE_VIEWS[b.dataset.sceneView]});
      L.toast('已上传'+SCENE_VIEWS[b.dataset.sceneView]);reopen();
    }));
  }
}
async function assetImages(project,asset,version){
  const scope={project_id:project.id,asset_id:asset.id};
  version=version||current(asset);
  const items=await L.api('/api/assets/image-candidates',scope);
  const reference=picOf(asset);
  const done=items.filter(item=>item.file),waiting=items.filter(item=>!item.file&&['queued','running','interrupted'].includes(item.state));
  const failed=items.filter(item=>!item.file&&!['queued','running','interrupted'].includes(item.state));
  const meta=item=>[item.approved?'已存入版本库':null,item.model,
    item.estimated_cny?`估价 ¥${item.estimated_cny}`:null,item.actual_cny?`实扣 ¥${item.actual_cny}`:null,
    item.created?L.timeAgo(item.created):null].filter(Boolean).join(' · ');
  const dialog=L.modal({title:asset.name+' · 制作参考',wide:true,body:`
    <label class="field"><span>画面要求</span><textarea data-instruction maxlength="2000" rows="3">${asset.kind==='character'?'四分之三角度，服装和脸部清晰，柔和光线，简洁背景。':'展示主要地标、空间布局与灯光方向，画内无人。'}</textarea></label>
    <div class="row"><button class="btn small" data-quote>预览请求与费用</button><span class="faint">候选会保留，不会覆盖已有版本。</span></div>
    ${reference?`<div class="sub">当前选用的版本</div><img src="${L.media(reference)}" alt="当前版本参考" style="max-width:100%;max-height:26vh;object-fit:contain">`:''}
    ${done.length?`<div class="sub">候选（${done.length}）</div><div class="grid2">${done.map(item=>`
      <figure style="margin:0"><img src="${L.media(item.file)}" alt="${esc(asset.name)}参考候选" style="max-width:100%;max-height:32vh;object-fit:contain">
      <figcaption class="faint">${esc(meta(item))}${item.approved?'<br><span class="chip">已批准参考</span>':`<br><button class="btn small" data-approve="${esc(item.id)}">批准为新版本</button>`}</figcaption></figure>`).join('')}</div>`:'<p class="faint">还没有制作完成的参考候选。</p>'}
    ${waiting.length?`<p class="faint">${waiting.length} 个候选仍在生成，完成后刷新查看。</p>`:''}
    ${failed.length?`<div class="sub">未完成（${failed.length}）</div>${failed.map(item=>`<p class="faint">${item.created?L.timeAgo(item.created)+' · ':''}${esc(item.state)}${item.error?' · '+esc(item.error):''}</p>`).join('')}`:''}
    <label class="row"><input type="checkbox" data-select checked><span class="faint">批准后同时设为当前版本（只影响之后新绑定的镜头）</span></label>`,
    foot:'<button class="btn" data-refresh>刷新</button><button class="btn" data-close>关闭</button>'});
  $('[data-refresh]',dialog).onclick=()=>{dialog.close();assetImages(L.project(),L.project().assets.find(x=>x.id===asset.id)).catch(L.fail)};
  $('[data-quote]',dialog).onclick=e=>L.busy(e.currentTarget,async()=>{
    let request={...scope,version_id:version.id,episode_id:L.S.eid,kind:'asset_image',instruction:$('[data-instruction]',dialog).value};
    let quote;
    try{quote=await L.api('/api/jobs/quote',request)}
    catch(err){
      if(!/未批准/.test(err.message))throw err;
      if(!await L.confirmBox('当前版本没有已批准视图','未批准的视图默认不会进入模型请求。是否明确使用未批准视图，只为本次参考图生成？','使用未批准视图预览'))return;
      request={...request,allow_unapproved:true};
      quote=await L.api('/api/jobs/quote',request);
    }
    const enabled=quote.configured&&L.S.data.spending.remaining>=quote.authorization_calls;
    const statusLabel=status=>status==='approved'?'已批准':status==='legacy'?'旧版批准':'未批准';
    dialog.close();
    const confirm=L.modal({title:'确认制作参考',body:`<p>${esc(quote.model_label)} · ${esc(L.quoteCost(quote))}${quote.art_label?' · '+esc(quote.art_label):''}</p>
      ${quote.approval_notice?`<p class="notice wait">${esc(quote.approval_notice)}</p>`:''}
      ${quote.excluded_references?.length?`<p class="faint">未进入本次请求：${quote.excluded_references.map(r=>esc(r.label+'（'+r.reason+'）')).join('、')}</p>`:''}
      <p>${esc(quote.prompt||request.instruction)}</p>
      ${quote.references.map(ref=>`<figure style="margin:0 0 8px"><img style="max-width:100%;max-height:24vh;object-fit:contain" src="${L.media(ref.file)}" alt="${esc(ref.label)}"><figcaption class="faint">${esc(statusLabel(ref.status))} · ${esc(ref.label)}</figcaption></figure>`).join('')}
      ${quote.requires_approval?`<label class="row"><input type="checkbox" data-allow-unapproved><span class="faint">我确认本次使用未批准视图；只对本次请求生效，不会自动成为正式参考。</span></label>`:''}`,
      foot:`<button class="btn" data-close>取消</button><button class="btn primary" data-send ${enabled?'':'disabled'}>确认费用并生成</button>`});
    const nonce=crypto.randomUUID();
    $('[data-send]',confirm).onclick=e=>L.busy(e.currentTarget,async()=>{
      const allow=!!$('[data-allow-unapproved]',confirm)?.checked;
      if(allow&&!request.allow_unapproved){
        request={...request,allow_unapproved:true};
        quote=await L.api('/api/jobs/quote',request);
      }
      await L.api('/api/jobs',{...request,quote_digest:quote.digest,nonce});
      confirm.close();await L.refresh();L.toast('已加入生成队列');L.openDrawer();
    });
  });
  $$('[data-approve]',dialog).forEach(button=>button.onclick=e=>L.busy(e.currentTarget,async()=>{
    const select=$('[data-select]',dialog).checked;
    if(!await L.confirmBox('批准这张参考图？',select?'会保存为新版本并设为当前版本，只影响之后新绑定的镜头。':'会保存为新版本，当前选用版本不变。','批准为新版本'))return;
    const saved=await L.api('/api/assets/approve-image',{...scope,job_id:button.dataset.approve,revision:L.project().revision,select});
    L.replaceProject(saved);dialog.close();L.render();L.toast(select?'已批准并设为当前版本':'新版本已保存');
  }));
}
L.assetDialog=assetDialog;
})();
