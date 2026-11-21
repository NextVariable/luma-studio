/* A shared two-person platform, viewed from the current shot's own camera. */
L.shotCamera=async shot=>{
  const p=L.project(), base={project_id:p.id, revision:p.revision, shot_id:shot.id};
  const preview=camera=>L.api('/api/camera/preview',{...base,camera});
  const initial=await preview();
  if(L.S.sid!==shot.id)return;
  let camera={...initial.camera}, sequence=0,timer;
  const names={wide:'双人全景',left:initial.actors[0].name+'单人',right:initial.actors[1].name+'单人'};
  const m=L.modal({title:'镜头机位',wide:true,body:`
    <figure class="rehearsal-frame"><img data-frame style="display:block;width:100%;max-height:45dvh;object-fit:contain" alt="当前机位构图"></figure>
    <div class="row wrap" role="group" aria-label="机位预设">${Object.entries(names).map(([id,name])=>`<button class="btn small" data-angle="${id}">${L.esc(name)}</button>`).join('')}</div>
    <label class="field"><span>绕拍角度 <output data-degrees></output></span><input type="range" aria-label="绕拍角度" min="-55" max="55" step="1" data-key="angle"></label>
    <label class="field"><span>机位距离 <output data-meters></output></span><input type="range" aria-label="机位距离" min="1.8" max="10" step=".1" data-key="distance"></label>`,
    foot:'<button class="btn ghost" data-close>取消</button><button class="btn primary" data-apply>保存构图参考</button>'});
  const el=q=>m.querySelector(q), frame=el('[data-frame]'),apply=el('[data-apply]');
  function controls(){
    m.querySelectorAll('[data-angle]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.angle===camera.view));
    m.querySelectorAll('[data-key]').forEach(input=>input.value=camera[input.dataset.key]);
    el('[data-degrees]').value=camera.angle+'°';el('[data-meters]').value=camera.distance+' m';
  }
  function update(){
    controls();const token=++sequence;
    clearTimeout(timer);apply.disabled=true;
    timer=setTimeout(async()=>{
      try{
        const data=await preview({...camera});
        if(token!==sequence||!m.open)return;
        frame.src=data.image;apply.disabled=!!shot.locked;
      }catch(error){if(token===sequence&&m.open)L.fail(error)}
    },65);
  }
  frame.src=initial.image;controls();apply.disabled=!!shot.locked;
  m.querySelectorAll('[data-angle]').forEach(b=>b.onclick=()=>{camera={...initial.presets[b.dataset.angle]};update()});
  m.querySelectorAll('[data-key]').forEach(input=>input.oninput=()=>{camera[input.dataset.key]=Number(input.value);update()});
  apply.onclick=()=>L.busy(apply,async()=>{
    const saved=await L.api('/api/camera/apply',{...base,camera});
    m.close();L.replaceProject(saved);await L.refresh();L.render();L.toast('已保存构图参考');
    await L.storyboardQuote(shot.id);
  });
  m.addEventListener('close',()=>{clearTimeout(timer);sequence++},{once:true});
};


L.storyboardQuote=async (shotId,model="doubao-seedream-5-0-flash-260915")=>{
  const p=L.project();
  const request={project_id:p.id,episode_id:L.S.eid,kind:'image',shot_id:shotId,storyboard:true,model};
  const quote=await L.api('/api/jobs/quote',request);
  const images=quote.references.map(r=>`<figure style="margin:0;flex:1"><img src="${L.media(r.file)}" alt="${L.esc(r.label)}" style="width:100%;max-height:26vh;object-fit:contain"><figcaption>${L.esc(r.label)}</figcaption></figure>`).join('');
  const enabled=quote.configured&&L.S.data.spending.remaining>=quote.authorization_calls;
  const m=L.modal({title:'正式分镜图',body:`<div class="row">${images}</div><label>分镜模型 <select data-model><option value="doubao-seedream-5-0-flash-260915">Seedream 5.0 Flash</option><option value="doubao-seedream-4-5-251128">Seedream 4.5</option><option value="fal-ai/nano-banana/edit">Nano Banana Edit</option></select></label><p>1 张 · ${L.esc(L.quoteCost(quote))}</p>
    <p>生成结果会进入本镜的画面候选。${enabled?'':quote.configured?'当前外部调用已暂停。':'生成前需在本机配置 '+(quote.provider==='ark'?'ARK_API_KEY':'FAL_KEY')+'。'}</p>`,
    foot:`<button class="btn" data-close>关闭</button><button class="btn primary" data-submit ${enabled?'':'disabled'}>确认费用并生成</button>`});
  const picker=m.querySelector('[data-model]');
  picker.value=model;
  picker.onchange=()=>{m.close();L.storyboardQuote(shotId,picker.value).catch(L.fail)};
  const nonce=crypto.randomUUID();
  const submit=m.querySelector('[data-submit]');
  submit.onclick=()=>L.busy(submit,async()=>{
    await L.api('/api/jobs',{...request,quote_digest:quote.digest,nonce});
    m.close();await L.refresh();L.render();L.toast('已提交分镜图，可在生成记录查看');
  });
};
