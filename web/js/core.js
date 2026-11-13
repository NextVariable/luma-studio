/* 核心：接口、状态、弹窗、提示。所有视图通过 window.L 共享。 */
(function(){
const L=window.L={};
const KEY='luma:';
L.S={data:null,pid:localStorage.getItem(KEY+'project'),eid:null,sid:null,view:localStorage.getItem(KEY+'view')||'library',drawer:false,dirty:false};

L.$=(sel,root=document)=>root.querySelector(sel);
L.$$=(sel,root=document)=>[...root.querySelectorAll(sel)];
L.esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
L.chev='<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 4l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
L.media=name=>'/media/'+encodeURIComponent(name);
L.thumb=name=>'/thumb/'+encodeURIComponent(name);
L.isVideo=name=>/\.(mp4|mov)$/i.test(name||'');

L.api=async(path,body)=>{
  const opt=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Auteur':'studio'},body:JSON.stringify(body)};
  const r=await fetch(path,opt);let d={};
  try{d=await r.json()}catch(e){throw Error('服务没有返回有效数据，请确认流幕仍在运行')}
  if(!r.ok){const e=Error(d.error||'请求失败');e.server=true;throw e}
  return d;
};
L.upload=async(file,need)=>{
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  const r=await fetch('/api/upload/'+ext,{method:'POST',headers:{'X-Auteur':'studio'},body:file});
  const d=await r.json();if(!r.ok)throw Error(d.error||'上传失败');
  const wrong=need==='visual'&&!d.streams.includes('video')?'这个文件没有画面，请选择图片或视频':need==='audio'&&!d.streams.includes('audio')?'这个文件没有声音，请选择音频':null;
  if(wrong){L.api('/api/upload/discard',{file:d.file}).catch(()=>null);throw Error(wrong)}
  return d.file;
};
L.pickFile=accept=>new Promise(resolve=>{
  const i=document.createElement('input');i.type='file';i.accept=accept;
  i.onchange=()=>resolve(i.files[0]||null);
  i.oncancel=()=>resolve(null);
  i.click();
});

/* 状态读取 */
L.project=()=>L.S.data?.projects.find(p=>p.id===L.S.pid)||null;
L.episode=()=>{const p=L.project();return p?.episodes.find(e=>e.id===L.S.eid)||p?.episodes[0]||null};
L.shots=()=>{const p=L.project(),e=L.episode();return p&&e?p.shots.filter(s=>s.episode_id===e.id):[]};
L.shot=()=>L.shots().find(s=>s.id===L.S.sid)||null;
L.ready=()=>{const p=L.project(),e=L.episode();return p&&e?L.S.data.readiness?.[p.id]?.[e.id]:null};
L.remember=()=>{
  localStorage.setItem(KEY+'view',L.S.view);
  if(L.S.pid)localStorage.setItem(KEY+'project',L.S.pid);
  if(L.S.pid&&L.S.eid)localStorage.setItem(KEY+'episode:'+L.S.pid,L.S.eid);
  if(L.S.pid&&L.S.eid&&L.S.sid)localStorage.setItem(KEY+'shot:'+L.S.pid+':'+L.S.eid,L.S.sid);
};
L.normalize=()=>{
  const d=L.S.data;if(!d)return;
  if(L.S.pid&&!d.projects.some(p=>p.id===L.S.pid)){L.S.pid=null;if(L.S.view!=='library')L.S.view='library'}
  const p=L.project();if(!p){L.S.eid=L.S.sid=null;return}
  if(!p.episodes.some(e=>e.id===L.S.eid))L.S.eid=localStorage.getItem(KEY+'episode:'+p.id);
  if(!p.episodes.some(e=>e.id===L.S.eid))L.S.eid=p.episodes[0].id;
  const list=L.shots();
  if(!list.some(s=>s.id===L.S.sid))L.S.sid=localStorage.getItem(KEY+'shot:'+p.id+':'+L.S.eid);
  if(!list.some(s=>s.id===L.S.sid))L.S.sid=list[0]?.id||null;
};
L.refresh=async()=>{L.S.data=await L.api('/api/state');L.normalize();};

/* 写操作：都以服务端返回的作品为准 */
L.replaceProject=p=>{const d=L.S.data;d.projects=d.projects.map(x=>x.id===p.id?p:x);if(!d.projects.some(x=>x.id===p.id))d.projects.push(p)};
L.save=async(mutate)=>{
  const p=structuredClone(L.project());mutate(p);
  const saved=await L.api('/api/save',{project:p,revision:p.revision});
  L.replaceProject(saved);L.S.dirty=false;await L.refresh();return saved;
};
L.production=async(action,fields={})=>{
  const p=L.project();
  const saved=await L.api('/api/production',{project_id:p.id,revision:p.revision,action,...fields});
  L.replaceProject(saved);await L.refresh();return saved;
};
L.serviceConnected=kind=>Boolean(kind==='audio'?L.S.data.openai_direct:(L.S.data.dify[kind] || (kind==='revision'&&L.S.data.openai_direct)));
L.needService=async kind=>{
  if(L.serviceConnected(kind))return true;
  const direct=['audio','revision'].includes(kind);
  if(await L.confirmBox(L.jobName(kind)+'还没有连接',direct?(kind==='audio'?'在设置中连接 OpenAI 配音服务，也可以导入已有音轨。':'在设置中连接 OpenAI 直连服务，或使用已有 Dify 应用。'):'这项功能需要先在设置里连接对应的 Dify 应用。连接只保存在本机，检查连接不会消耗额度。','打开设置'))L.settingsDialog();
  return false;
};
L.quoteCost=q=>q.estimated_usd!=null?'预计 $'+q.estimated_usd+'（美元）':q.billing;
L.confirmGeneration=async(title,request,confirm=true)=>{
  const q=await L.api('/api/jobs/quote',request);
  const remaining=L.S.data.spending.remaining;
  if(remaining<q.authorization_calls)throw Error('本次需要 '+q.authorization_calls+' 次本机授权，目前剩余 '+remaining+' 次');
  const provider={fal:'fal',openai:'OpenAI',dify:'Dify'}[q.provider]||q.provider;
  const details=[provider,q.model_label||q.model,q.duration!=null?q.duration+' 秒':null].filter(Boolean).join(' · ');
  const references=q.reference_count?'。将发送 '+q.reference_count+' 个选中的参考素材':'';
  const message=details+'。'+L.quoteCost(q)+'。本机授权 '+q.authorization_calls+' 次，剩余 '+remaining+' 次'+references+'。实际费用由服务商结算。';
  return !confirm||await L.confirmBox(title,message,'开始生成')?q.digest:null;
};
L.run=async(kind,extra={},{confirm=true}={})=>{
  const p=L.project();
  const request={project_id:p.id,episode_id:L.S.eid,kind,...extra};
  if(kind!=='export'&&kind!=='assemble'){
    if(!await L.needService(kind))return null;
    request.quote_digest=await L.confirmGeneration(L.jobName(kind),request,confirm);
    if(!request.quote_digest)return null;
  }
  const r=await L.api('/api/jobs',{...request,nonce:crypto.randomUUID()});
  await L.refresh();return r.id;
};

/* 音效：轻点、滑动、完成、出错。用 Web Audio 合成，可在设置里关闭 */
L.sound={on:localStorage.getItem('luma:sound')!=='off'};
let audio=null,swipe=null,touchSwipe=0,swipeRequest=0,audioHintShown=false;
const ac=()=>audio||(audio=new (window.AudioContext||window.webkitAudioContext)());
const tone=(c,t,f1,f2,dur,vol,type='sine')=>{const o=c.createOscillator(),g=c.createGain();o.type=type;o.frequency.setValueAtTime(f1,t);o.frequency.exponentialRampToValueAtTime(f2,t+dur);g.gain.setValueAtTime(vol,t);g.gain.exponentialRampToValueAtTime(.0001,t+dur);o.connect(g).connect(c.destination);o.start(t);o.stop(t+dur+.02)};
function audioActivated(){
  const activation=window.navigator?.userActivation;
  return !activation||activation.isActive||activation.hasBeenActive;
}
function unlockAudio(){
  if(!L.sound.on)return;
  try{const c=ac();if(c.state!=='running')return c.resume().catch(()=>null)}catch(e){/* No Web Audio support. */}
}
function playSwipe(c,t,direction){
  if(swipe){
    const old=swipe;
    old.gain.gain.cancelScheduledValues(t);
    old.gain.gain.setTargetAtTime(.0001,t,.006);
    old.source.stop(t+.03);
  }
  const duration=.17,len=Math.floor(c.sampleRate*duration),buf=c.createBuffer(1,len,c.sampleRate);
  const samples=buf.getChannelData(0);
  for(let i=0;i<len;i++)samples[i]=(Math.random()*2-1)*(1-i/len);
  const source=c.createBufferSource(),filter=c.createBiquadFilter(),gain=c.createGain();
  source.buffer=buf;
  filter.type='bandpass';filter.Q.value=.85;
  filter.frequency.setValueAtTime(direction<0?2250:650,t);
  filter.frequency.exponentialRampToValueAtTime(direction<0?650:2250,t+duration);
  gain.gain.setValueAtTime(.0001,t);
  gain.gain.exponentialRampToValueAtTime(.15,t+.026);
  gain.gain.exponentialRampToValueAtTime(.0001,t+duration);
  source.connect(filter).connect(gain).connect(c.destination);
  const current={source,gain};
  swipe=current;
  source.onended=()=>{if(swipe===current)swipe=null};
  source.start(t);
}
L.sfx=(kind,direction=1,{touch=false}={})=>{
  if(!L.sound.on)return;
  try{
    const c=ac();
    const request=kind==='swipe'?++swipeRequest:0;
    const play=()=>{
      if(!L.sound.on||c.state!=='running'||(request&&request!==swipeRequest))return;
      const t=c.currentTime;
      if(kind==='tap')tone(c,t,1500,820,.045,.035);
      if(kind==='ok'){tone(c,t,660,700,.12,.04);tone(c,t+.08,990,1040,.18,.035)}
      if(kind==='err')tone(c,t,240,150,.22,.06,'triangle');
      if(kind==='swipe')playSwipe(c,t,direction);
    };
    if(c.state==='running')play();
    else if(audioActivated())unlockAudio()?.then(play).catch(()=>null);
    else if(touch&&kind==='swipe')touchSwipe=direction;
    else if(kind==='swipe'&&!audioHintShown){
      audioHintShown=true;
      L.toast('点击一下页面，即可听到滑动音效');
    }
  }catch(e){/* No Web Audio support. */}
};
L.setSound=on=>{
  L.sound.on=on;localStorage.setItem('luma:sound',on?'on':'off');
  if(on)L.sfx('ok');
  else {touchSwipe=0;swipeRequest++}
};
/* The browser unlocks audio on a trusted click, key or touch release. */
for(const event of ['pointerdown','pointerup','keydown','touchend','click']){
  document.addEventListener(event,input=>{
    if(!input.isTrusted||!audioActivated())return;
    const direction=touchSwipe;
    if((event==='touchend'||event==='pointerup'||event==='click')&&direction){
      touchSwipe=0;
      L.sfx('swipe',direction);
    }else unlockAudio();
  },true);
}
document.addEventListener('touchcancel',()=>{touchSwipe=0},true);
document.addEventListener('pointerdown',e=>{
  if(e.target.closest('[data-view],.shot,#brand,#to-delivery,.check'))return;
  if(e.target.closest('button:not(:disabled),a.btn,.work,label.pm,.cast-pick label'))L.sfx('tap');
},true);

/* 过渡只作用于内容，导航、操作栏与滚动容器保持原位。 */
const swaps=new WeakMap();
const PAGE_EASE='cubic-bezier(.2,.75,.25,1)';
L.reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
L.swap=(el,direction,mutate,{content,axis='y'}={})=>{
  swaps.get(el)?.();
  if(!direction||!el||L.reduced()){mutate();return}
  const original=()=>[...el.children].filter(node=>!content||node.matches(content));
  const rect=el.getBoundingClientRect();
  const clip=document.createElement('div');
  clip.className='swap-clip';
  clip.setAttribute('aria-hidden','true');
  clip.inert=true;
  clip.style.cssText=content
    ?'position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:2'
    :`position:fixed;left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px;overflow:hidden;pointer-events:none;z-index:6`;
  const ghost=document.createElement(el.tagName);
  ghost.className=el.className+' swap-ghost';
  ghost.style.cssText='position:absolute;inset:0;margin:0;overflow:hidden;width:100%;height:100%;background:transparent;border:0;box-shadow:none';
  for(const node of original())ghost.appendChild(node.cloneNode(true));
  ghost.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
  ghost.querySelectorAll('video,audio').forEach(media=>{
    media.removeAttribute('autoplay');
    media.muted=true;
  });
  clip.appendChild(ghost);
  (content?el:document.body).appendChild(clip);
  ghost.scrollTop=el.scrollTop;
  mutate();
  if(content)el.appendChild(clip);
  const animations=[];
  const translate=value=>axis==='x'?`${value}px 0`:`0 ${value}px`;
  const motion=(node,from,to,fadeIn)=>{
    animations.push(node.animate([{translate:translate(from)},{translate:translate(to)}],{duration:290,easing:PAGE_EASE,fill:'both'}));
    animations.push(node.animate([{opacity:fadeIn?0:1},{opacity:fadeIn?1:0}],{duration:260,easing:'ease-out',fill:'both'}));
  };
  motion(ghost,0,-direction*20,false);
  for(const node of original())motion(node,direction*20,0,true);
  const finish=()=>{
    if(swaps.get(el)!==finish)return;
    swaps.delete(el);
    clip.remove();
    animations.forEach(animation=>animation.cancel());
  };
  swaps.set(el,finish);
  Promise.allSettled(animations.map(animation=>animation.finished)).then(finish);
};
L.pagingBlocked=()=>!!L.$('dialog[open]')||!!L.$('.menu');

/* 提示 */
L.toast=(msg,err=false)=>{
  const t=document.createElement('div');t.className='toast'+(err?' err':'');t.textContent=msg;
  const open=L.$$('dialog[open]').at(-1);
  const host=open?L.$('.toasts-in',open)||L.$('#toasts'):L.$('#toasts');
  host.appendChild(t);setTimeout(()=>t.remove(),err?6000:3200);
};
L.done=msg=>{L.toast(msg);L.sfx('ok')};
L.fail=e=>{console.error(e);L.toast(e.message||String(e),true);if(e.server)L.sfx('err')};
L.busy=async(btn,fn)=>{
  if(btn?.disabled)return;
  if(btn)btn.disabled=true;
  try{return await fn()}catch(e){L.fail(e)}finally{if(btn&&btn.isConnected)btn.disabled=false}
};

/* 弹窗 */
L.modal=({title,body,foot='',wide=false,focusField=true,onMount})=>{
  const m=L.$('#modal');m.className='modal'+(wide?' wide':'');
  m.setAttribute('aria-label',title);
  m.innerHTML=`<div class="modal-head"><h2>${L.esc(title)}</h2><span class="spacer"></span><button class="btn ghost icon-btn" data-close aria-label="关闭">✕</button></div><div class="modal-body">${body}</div>${foot?`<div class="modal-foot">${foot}</div>`:''}<div class="toasts-in" aria-live="polite"></div>`;
  L.$$('[data-close]',m).forEach(b=>b.onclick=()=>m.close());
  if(!m.open)m.showModal();
  onMount?.(m);
  if(focusField)L.$('input,textarea,select',L.$('.modal-body',m))?.focus();
  return m;
};
L.closeModal=()=>{const m=L.$('#modal');if(m.open)m.close()};
L.layer=({title,body,foot})=>{
  const m=document.createElement('dialog');m.className='modal layer';
  m.setAttribute('aria-label',title);
  m.innerHTML=`<div class="modal-head"><h2>${L.esc(title)}</h2></div><div class="modal-body">${body}</div><div class="modal-foot">${foot}</div><div class="toasts-in" aria-live="polite"></div>`;
  document.body.appendChild(m);m.addEventListener('close',()=>m.remove(),{once:true});
  L.$$('[data-close]',m).forEach(b=>b.onclick=()=>m.close());
  m.showModal();return m;
};
L.confirmBox=(title,text,ok='确定',danger=false)=>new Promise(resolve=>{
  let done=false;
  const m=L.layer({title,body:`<p class="muted" style="margin:0;line-height:1.7">${L.esc(text)}</p>`,
    foot:`<button class="btn ghost" data-close>取消</button><button class="btn ${danger?'danger':'primary'}" data-ok>${L.esc(ok)}</button>`});
  L.$('[data-ok]',m).onclick=()=>{done=true;m.close();resolve(true)};
  m.addEventListener('close',()=>{if(!done)resolve(false)},{once:true});
  L.$('[data-ok]',m).focus();
});
L.prompt=(title,label,value='',ok='保存')=>new Promise(resolve=>{
  let done=false;
  const m=L.layer({title,body:`<label class="field"><span>${L.esc(label)}</span><input class="input" data-in maxlength="200" value="${L.esc(value)}"></label>`,
    foot:`<button class="btn ghost" data-close>取消</button><button class="btn primary" data-ok>${L.esc(ok)}</button>`});
  const input=L.$('[data-in]',m);
  const go=()=>{const v=input.value.trim();if(!v)return L.toast('请填写'+label,true);done=true;m.close();resolve(v)};
  L.$('[data-ok]',m).onclick=go;input.onkeydown=e=>{if(e.key==='Enter')go()};
  m.addEventListener('close',()=>{if(!done)resolve(null)},{once:true});
  input.focus();input.select();
});

/* 浮动菜单 */
L.menu=(anchor,items)=>{
  L.closeMenu();
  const m=document.createElement('div');m.className='menu';m.setAttribute('role','menu');
  m.innerHTML=items.map((it,i)=>it==='-'?'<hr>':`<button role="menuitem" data-i="${i}" ${it.current?'aria-current="true"':''}>${L.esc(it.label)}${it.hint?`<span class="faint">${L.esc(it.hint)}</span>`:''}</button>`).join('');
  document.body.appendChild(m);
  const r=anchor.getBoundingClientRect();
  m.style.left=Math.min(r.left,innerWidth-m.offsetWidth-12)+'px';m.style.top=(r.bottom+6)+'px';
  L.$$('button',m).forEach(b=>b.onclick=()=>{L.closeMenu();items[+b.dataset.i].run()});
  L.$('button',m)?.focus();
  setTimeout(()=>{document.addEventListener('click',L.closeMenu,{once:true})});
  m.onkeydown=e=>{
    const bs=L.$$('button',m),i=bs.indexOf(document.activeElement);
    if(e.key==='Escape'){L.closeMenu();anchor.focus()}
    if(e.key==='ArrowDown'){e.preventDefault();bs[(i+1)%bs.length].focus()}
    if(e.key==='ArrowUp'){e.preventDefault();bs[(i-1+bs.length)%bs.length].focus()}
  };
};
L.closeMenu=()=>L.$$('.menu').forEach(m=>m.remove());

/* 未保存修改 */
L.trackDirty=root=>{L.S.dirty=false;root.addEventListener('input',e=>{if(e.target.matches('[data-track]'))L.S.dirty=true})};
L.leaveOk=async()=>!L.S.dirty||await L.confirmBox('放弃未保存的修改？','当前页面有还没保存的修改，离开后会丢失。','放弃修改',true);
})();
