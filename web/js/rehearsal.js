/* A draft cut uses the current episode, including shots that still need artwork. */
L.openRehearsal=async()=>{
  const project=L.project(), episode=L.episode();
  const shots=await L.api('/api/rehearsal',{project_id:project.id,episode_id:episode.id});
  if(!shots.length||L.S.pid!==project.id||L.S.eid!==episode.id)return;
  const m=L.modal({title:episode.title+' · 整集预演',wide:true,body:`
    <figure class="rehearsal-frame"><div data-picture></div><figcaption></figcaption></figure>
    <div class="row wrap"><span data-position class="num"></span><span data-description></span></div>
    <div class="row wrap" data-shots role="group" aria-label="跳至镜头"></div>`,
    foot:'<button class="btn" data-edit>编辑当前镜头</button><button class="btn primary" data-play>播放预演</button>'});
  const find=q=>m.querySelector(q), picture=find('[data-picture]'), caption=find('figcaption');
  if(project.creative_brief?.format==='9:16')picture.parentElement.classList.add('portrait');
  const voice=new Audio();
  let i=0, offset=0, epoch=0, playing=false, frame=0, activeCue=null, video=null;
  function stopMedia(){voice.pause();video?.pause()}
  function draw(){
    const shot=shots[i], cut=shot.clip;
    stopMedia();activeCue=null;video=null;picture.replaceChildren();
    if(cut){
      const el=document.createElement(cut.kind==='video'?'video':'img');
      if(cut.kind==='video'){
        video=el;el.playsInline=true;el.muted=shot.audio.length>0;
        el.currentTime=cut.trim_start||0;
      }else el.alt=shot.description;
      el.src=L.media(cut.file);
      picture.append(el);
    }else picture.textContent='待补画面';
    find('[data-description]').textContent=shot.description;
    Array.from(find('[data-shots]').children).forEach((b,n)=>b.setAttribute('aria-pressed',String(i===n)));
    sync();
  }
  function playElement(el){
    el.play().catch(err=>{
      if(playing&&err.name!=='AbortError'){pause();L.toast('媒体未能播放，请检查素材后重试')}
    });
  }
  function sync(){
    const shot=shots[i],cut=shot.clip;
    find('[data-position]').textContent='镜头 '+(i+1)+' / '+shots.length+' · '+L.clock(Math.floor(offset))+' / '+L.clock(shot.duration);
    caption.textContent=shot.captions.find(c=>offset>=c.start&&offset<c.end)?.text||'';
    const cue=shot.audio.find(c=>offset>=c.start&&offset<c.end);
    if(cue!==activeCue){
      voice.pause();activeCue=cue;
      if(cue){voice.src=L.media(cue.file);voice.currentTime=Math.max(0,offset-cue.start);if(playing)playElement(voice)}
    }
    if(video&&cut.trim_end!=null&&offset+cut.trim_start>=cut.trim_end)video.pause();
  }
  function pause(){
    playing=false;cancelAnimationFrame(frame);stopMedia();
    find('[data-play]').textContent=i===shots.length-1&&offset>=shots[i].duration?'重新播放':'播放预演';
  }
  function startMedia(){
    if(video){
      const cut=shots[i].clip, time=(cut.trim_start||0)+offset;
      if(cut.trim_end==null||time<cut.trim_end){video.currentTime=time;playElement(video)}
    }
    if(activeCue){voice.currentTime=offset-activeCue.start;playElement(voice)}
  }
  function jump(n){
    i=n;offset=0;epoch=performance.now();draw();
    if(playing&&video)playElement(video);
    if(!playing)find('[data-play]').textContent='播放预演';
  }
  function tick(now){
    if(!m.open){pause();return}
    offset=Math.min(shots[i].duration,(now-epoch)/1000);
    sync();
    if(offset>=shots[i].duration){
      if(i===shots.length-1){pause();return}
      jump(i+1);
    }
    frame=requestAnimationFrame(tick);
  }
  shots.forEach((shot,n)=>{
    const b=document.createElement('button');b.className='btn small';b.textContent=String(n+1).padStart(2,'0');
    b.setAttribute('aria-label','跳至镜头 '+(n+1));b.onclick=()=>jump(n);find('[data-shots]').append(b);
  });
  find('[data-play]').onclick=()=>{
    if(playing){pause();return}
    if(offset>=shots[i].duration)jump(0);
    playing=true;epoch=performance.now()-offset*1000;startMedia();
    find('[data-play]').textContent='暂停';frame=requestAnimationFrame(tick);
  };
  find('[data-edit]').onclick=()=>{m.close();L.ui.tab=null;L.S.sid=shots[i].id;L.remember();L.render()};
  const visibility=()=>{if(document.hidden&&playing)pause()};
  document.addEventListener('visibilitychange',visibility);
  m.addEventListener('close',()=>{
    pause();voice.removeAttribute('src');voice.load();picture.replaceChildren();
    document.removeEventListener('visibilitychange',visibility);
  },{once:true});
  draw();
};
