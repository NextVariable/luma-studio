/* 设置：服务连接与生成额度；作品历史版本 */
(function(){
const {esc,$,$$}=L;
const SERVICES=[
  ['shots','AI 分镜','把一集剧本拆成镜头方案，支持在 Dify 里审批'],
  ['revision','AI 修改这一镜','按你的要求改写单个镜头'],
  ['image','画面生成','为镜头生成图片'],
  ['video','视频生成','为镜头生成视频'],
];
const MORE=[['assets','角色与场景建议'],['script','剧本拆解'],['plan','制作规划'],['qc','质量检查']];

L.settingsDialog=()=>{
  const d=L.S.data,sp=d.spending;
  const m=L.modal({title:'设置',wide:true,focusField:false,body:`
    <div class="row"><div><b>音效</b><div class="faint">点击、切页、切镜头和完成提示</div></div><span class="spacer"></span><div class="seg" id="snd"><button data-on="1" aria-pressed="${L.sound.on}">开</button><button data-on="0" aria-pressed="${!L.sound.on}">关</button></div></div>
    <h3 class="settings-section">生成额度</h3>
    <div class="notice ${sp.remaining?'':'wait'}"><div class="grow"><b class="num">${sp.remaining?'本批还可以生成 '+sp.remaining+' 次':'生成已暂停'}</b>
      <p class="muted">每次外部调用或提交审批扣 1 次，单镜修改如需复审会额外调用一次，累计已用 ${sp.used} 次。额度为 0 时暂停新调用。服务商余额请到对应平台查看。</p></div></div>
    <div class="row settings-actions"><label class="field"><span>授权次数（0–20）</span><input class="input num" id="sp-n" type="number" min="0" max="20" value="${sp.remaining}"></label>
      <button class="btn" id="sp-pause" ${sp.remaining?'':'disabled'}>立即暂停</button><button class="btn primary" id="sp-save">更新额度</button></div>
    <h3 class="settings-section">服务连接</h3>
    <div class="line-card">
      <div class="row settings-service-head"><span class="dot ${d.openai_direct?'ok':''}"></span><b>OpenAI 直连</b><span class="faint">${d.openai_direct?'已配置':'未连接'}</span></div>
      <div class="faint">用于新配音和单镜修改。导演分镜继续由 Dify 执行。</div>
      <div class="row"><input class="input" id="openai-key" type="password" autocomplete="off" aria-label="OpenAI API Key" placeholder="粘贴 OpenAI API Key"><button class="btn small" id="openai-save">保存</button></div>
    </div>
    <label class="field"><span>Dify 地址</span><input class="input" id="dify-base" value="${esc(d.dify_base_url||'')}" placeholder="https://api.dify.ai/v1"></label>
    <div class="side-stack" style="gap:8px">${SERVICES.map(([k,name,desc])=>row(k,name,desc,d.dify[k])).join('')}</div>
    <details><summary class="faint" style="cursor:pointer">其他工作流</summary><div class="side-stack" style="gap:8px;margin-top:10px">${MORE.map(([k,name])=>row(k,name,'',d.dify[k])).join('')}</div></details>
    <p class="faint" style="margin:0">Key 只保存在本机，保存后不会再显示。「检查连接」只读取应用信息，不运行模型、不消耗额度。</p>`});
  $$('#snd button',m).forEach(b=>b.onclick=()=>{L.setSound(b.dataset.on==='1');$$('#snd button',m).forEach(x=>x.setAttribute('aria-pressed',x===b))});
  $('#sp-save',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const n=Number($('#sp-n',m).value);if(!Number.isInteger(n)||n<0||n>20)throw Error('授权次数需为 0 到 20 的整数');
    if(n>0&&!await L.confirmBox('授权 '+n+' 次生成？','之后的 AI 分镜、修改、配音和审批会消耗这些次数，每次都可能产生服务商费用。','授权'))return;
    await L.api('/api/settings/spending',{remaining:n});await L.refresh();L.toast(n?'已授权 '+n+' 次':'生成已暂停');L.renderTop();L.settingsDialog();
  });
  $('#sp-pause',m).onclick=e=>L.busy(e.currentTarget,async()=>{await L.api('/api/settings/spending',{remaining:0});await L.refresh();L.toast('生成已暂停');L.renderTop();L.settingsDialog()});
  $('#openai-save',m).onclick=e=>L.busy(e.currentTarget,async()=>{
    const key=$('#openai-key',m).value.trim();
    if(!key)throw Error('请粘贴 OpenAI API Key');
    await L.api('/api/settings/openai',{api_key:key});
    await L.refresh();L.toast('直连配置已保存');L.settingsDialog();
  });
  $$('[data-svc]',m).forEach(box=>{
    const kind=box.dataset.svc;
    $('[data-save]',box).onclick=e=>L.busy(e.currentTarget,async()=>{
      const key=$('[data-key]',box).value.trim();if(!key)throw Error('请粘贴已发布应用的 API Key（以 app- 开头）');
      await L.api('/api/settings/dify',{base_url:$('#dify-base',m).value.trim(),api_key:key,kind});
      await L.refresh();L.toast('已保存，建议检查连接');L.settingsDialog();
    });
    $('[data-check]',box)?.addEventListener('click',e=>L.busy(e.currentTarget,async()=>{
      const out=$('[data-out]',box);out.textContent='检查中…';
      try{const r=await L.api('/api/settings/dify/check',{kind});out.textContent='已连通：'+(r.app_name||'未命名应用')+'。生成效果还需实际验收。';out.style.color='var(--ok)'}
      catch(err){out.textContent=err.message;out.style.color='var(--stop)'}
    }));
  });
};
function row(k,name,desc,on){
  return `<div class="line-card" data-svc="${k}"><div class="row settings-service-head"><span class="dot ${on?'ok':''}"></span><b>${esc(name)}</b><span class="faint">${on?'已配置':'未连接'}</span>${on?'<button class="btn small" data-check>检查连接</button>':''}</div>
    ${desc?`<div class="faint">${esc(desc)}</div>`:''}
    <div class="row"><input class="input" data-key type="password" autocomplete="off" placeholder="${on?'更换 Key：粘贴新的 app- Key':'粘贴 app- 开头的 API Key'}"><button class="btn small" data-save>保存</button></div>
    <div class="faint" data-out aria-live="polite"></div></div>`;
}

L.historyDialog=async()=>{
  try{
    const p=L.project(),rows=await L.api('/api/versions/'+encodeURIComponent(p.id));
    const m=L.modal({title:'历史版本',body:rows.length?`<p class="faint" style="margin:0">每次保存前的作品都会留一份。恢复会把整部作品换回当时的样子，当前状态也会先存为一个版本。</p>
      <div class="films">${rows.map((r,i)=>`<button class="film" data-i="${i}"><span style="flex:1">${new Date(r.created*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</span><span class="faint">${r.project.episodes.length} 集</span><span class="faint">${r.project.shots.length} 镜</span></button>`).join('')}</div>`:'<p class="muted">还没有历史版本。</p>'});
    $$('[data-i]',m).forEach(b=>b.onclick=async()=>{
      const old=rows[+b.dataset.i].project;
      if(!await L.confirmBox('恢复到这个版本？','作品会回到 '+new Date(rows[+b.dataset.i].created*1000).toLocaleString('zh-CN')+' 的状态。被锁定的镜头不能通过恢复删除。','恢复'))return;
      L.busy(null,async()=>{const cur=L.project();const saved=await L.api('/api/save',{project:{...old,revision:cur.revision},revision:cur.revision});L.replaceProject(saved);await L.refresh();L.toast('已恢复');L.render()});
    });
  }catch(e){L.fail(e)}
};
})();
