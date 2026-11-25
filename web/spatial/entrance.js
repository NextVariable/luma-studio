import { cameraAt, makeScene, portalRect, ramp } from './renderer.js';
import { makeArt } from './art.js';

const SEEN = 'luma:spatial-entrance-v2';
const LINK = new URL(location.href);
const preview = document.documentElement.hasAttribute('data-spatial-preview');
const replay = LINK.searchParams.get('entrance')==='1';
const surface = document.querySelector('#studio-surface');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
function seen() {
  try { return sessionStorage.getItem(SEEN)==='1'; } catch { return false; }
}
function remember() {
  if (preview) return;
  try { sessionStorage.setItem(SEEN,'1'); } catch { /* session storage can be disabled */ }
  if (replay) {
    LINK.searchParams.delete('entrance');
    history.replaceState(history.state,'',LINK);
  }
}
function showEntrance({reverse=false}={}) {
  if (document.querySelector('.spatial-entrance')) return;
  const intro=document.createElement('section');
  intro.className='spatial-entrance spatial-fallback';
  intro.setAttribute('aria-label','流幕开场');
  intro.tabIndex=0;
  intro.innerHTML=`
    <div class="spatial-track"><div class="spatial-frame">
      <canvas class="spatial-scene" aria-hidden="true" hidden></canvas>
      <div class="spatial-chrome">
        <div class="spatial-brand"><img src="/assets/luma-mark.png" alt="">Luma <span>流幕</span></div>
        <div class="spatial-bottom">
          <h1 class="spatial-title spatial-visually-hidden">Enter your studio.</h1>
          <div class="spatial-actions">
            <button class="spatial-scroll spatial-backward" type="button" hidden><i aria-hidden="true"></i>后退</button>
            <button class="spatial-scroll spatial-forward" type="button" hidden>前进 <i aria-hidden="true"></i></button>
            <button class="spatial-enter" type="button">进入工作室 <span aria-hidden="true">↗</span></button>
          </div>
        </div>
      </div>
      <div class="spatial-progress" aria-hidden="true" hidden></div>
    </div></div>`;
  document.body.append(intro);
  surface.inert=true;
  const canvas=intro.querySelector('canvas');
  const chrome=intro.querySelector('.spatial-chrome');
  const backward=intro.querySelector('.spatial-backward');
  const forward=intro.querySelector('.spatial-forward');
  const bar=intro.querySelector('.spatial-progress');
  const title=intro.querySelector('.spatial-title');
  const brand=intro.querySelector('.spatial-brand');
  const enterButton=intro.querySelector('.spatial-enter');
  const life=new AbortController();
  let scene, frame, alive=true, workspaceReady=false, waitingForStudio=false, pointer=[0,0], target=[0,0];
  const clock=performance.now();
  let lastDraw=0, reverseFrom;
  if (reverse && !reduced.matches) intro.style.visibility='hidden';
  const on=(node,event,fn,options={})=>node.addEventListener(event,fn,{...options,signal:life.signal});
  function unmap() {
    if (!surface.classList.contains('spatial-portal')) return;
    surface.classList.remove('spatial-portal');
    surface.style.removeProperty('opacity');
    surface.style.removeProperty('transform');
  }
  function close() {
    if (!alive) return;
    alive=false; life.abort(); cancelAnimationFrame(frame);
    unmap(); surface.inert=false;
    intro.remove(); scene?.dispose(); scene=null;
    remember();
    (document.querySelector('#view')||surface.querySelector('iframe'))?.focus({preventScroll:true});
    document.dispatchEvent(new Event('luma:spatial-entered'));
  }
  function fallback() {
    cancelAnimationFrame(frame);
    unmap();
    const previous=scene; scene=null; previous?.dispose();
    intro.classList.add('spatial-fallback');
    intro.scrollTop=0;
    intro.style.removeProperty('visibility');
    canvas.hidden=true; backward.hidden=forward.hidden=bar.hidden=true;
    for (const el of [chrome,title,brand,enterButton]) el.style.removeProperty('opacity');
    enterButton.disabled=false;
  }
  function render(now) {
    if (!alive || !scene) return;
    const width=intro.clientWidth, height=intro.clientHeight;
    const range=intro.scrollHeight-height;
    if (reverseFrom!==undefined) {
      const t=Math.min(1,(now-reverseFrom)/1450);
      intro.scrollTop=range*.988*(1-t);
      if (t===1) reverseFrom=undefined;
    }
    const progress=Math.min(1,Math.max(0,intro.scrollTop/Math.max(1,range)));
    if (progress>=.999 && workspaceReady) return close();
    if (progress>=.999) waitingForStudio=true;
    if (document.hidden || width===0 || height===0) {
      frame=requestAnimationFrame(render);
      return;
    }
    // Limit pixel count on high-DPI panels instead of allocating post-processing buffers.
    const ratio=Math.min(devicePixelRatio,1.55,Math.sqrt(1900000/(width*height)));
    const w=Math.round(width*ratio),h=Math.round(height*ratio);
    if (canvas.width!==w||canvas.height!==h) {canvas.width=w;canvas.height=h;}
    pointer=pointer.map((value,i)=>value+(target[i]-value)*.09);
    const p=waitingForStudio&&!workspaceReady?Math.min(progress,.975):progress;
    if (art.resize(width/height)) scene.update();
    const camera=cameraAt(p,width/height,pointer);
    if(now-lastDraw>18 || progress!==render.progress) {
      scene.draw(camera,(now-clock)*.001,ramp(.77,.92,p),p);
      lastDraw=now; render.progress=progress;
    }
    title.style.opacity=brand.style.opacity=String(1-ramp(.26,.66,p));
    enterButton.style.opacity=String(1-.40*ramp(.45,.83,p));
    backward.disabled=p<=.005; forward.disabled=p>=.998;
    bar.style.setProperty('--progress',p.toFixed(3));
    if (workspaceReady && p>.76) {
      const [x,y,rw,rh]=portalRect(camera,width,height);
      surface.classList.add('spatial-portal');
      surface.style.transform=`translate(${x}px,${y}px) scale(${rw/width},${rh/height})`;
      surface.style.opacity=String(ramp(.76,.986,p));
    } else unmap();
    frame=requestAnimationFrame(render);
  }
  on(enterButton,'click',close);
  const stopReverse=()=>{reverseFrom=undefined;};
  const move=direction=>{
    stopReverse();
    intro.scrollBy({top:direction*intro.clientHeight*.86,behavior:'smooth'});
  };
  on(forward,'click',()=>move(1));
  on(backward,'click',()=>move(-1));
  on(intro,'wheel',stopReverse,{passive:true});
  on(intro,'touchstart',stopReverse,{passive:true});
  on(intro,'pointermove',event=>{
    if(event.pointerType==='mouse')target=[event.clientX/Math.max(1,intro.clientWidth)*2-1,
      1-event.clientY/Math.max(1,intro.clientHeight)*2];
  },{passive:true});
  on(intro,'pointerleave',()=>{target=[0,0];},{passive:true});
  on(document,'keydown',event=>{
    if (event.key==='Escape') {
      event.preventDefault(); event.stopImmediatePropagation(); close();
    } else if (['ArrowDown','ArrowUp','PageDown','PageUp','Home','End',' '].includes(event.key)&&
               !(event.key===' '&&event.target.closest('button'))) {
      event.preventDefault(); event.stopImmediatePropagation();
      if (!scene) return;
      stopReverse();
      const amount=event.key==='Home'?-intro.scrollHeight:event.key==='End'?intro.scrollHeight:
        intro.clientHeight*(event.key.startsWith('Page')||event.key===' '?.82:.22);
      intro.scrollBy({top:['ArrowUp','PageUp'].includes(event.key)?-amount:amount,behavior:'smooth'});
    }
  },{capture:true});
  on(reduced,'change',event=>{if(event.matches)fallback();});
  on(canvas,'webglcontextlost',event=>{
    event.preventDefault();
    if (scene && alive) fallback();
  });
  intro.focus({preventScroll:true});
  if (reduced.matches) return;

  const ready = preview ? new Promise(resolve=>{
    const iframe=surface.querySelector('iframe');
    if (iframe.contentDocument?.querySelector('#rail [data-view]')) resolve();
    else {
      let timer=setTimeout(resolve,3000);
      on(iframe,'load',()=>{clearTimeout(timer);resolve();},{once:true});
      life.signal.addEventListener('abort',()=>clearTimeout(timer),{once:true});
    }
  }) : Promise.resolve(window.L?.studioReady);
  ready.finally(()=>{workspaceReady=true;});
  const work = () => {
    if (preview) return null;
    const data=window.L?.S.data;
    return window.L?.project()||data?.projects?.[0]||null;
  };
  const art=makeArt();
  Promise.race([ready,new Promise(resolve=>setTimeout(resolve,240))]).then(async()=>{
    const initial=work();
    await art.load(null);
    if (initial) await art.load(initial);
    if (!alive || reduced.matches) return;
    try {
      scene=makeScene(canvas,art.wall,art.main,art.room,art.actor);
      intro.classList.remove('spatial-fallback');
      canvas.hidden=backward.hidden=forward.hidden=bar.hidden=false;
      if (reverse) {
        intro.scrollTop=(intro.scrollHeight-intro.clientHeight)*.988;
        reverseFrom=performance.now();
      }
      frame=requestAnimationFrame(now=>{
        render(now);
        intro.style.removeProperty('visibility');
        if(reverse)intro.focus({preventScroll:true});
      });
      ready.then(async()=>{
        const current=work();
        if (!current || current===initial || !alive || !scene) return;
        await art.load(current);
        if (alive)scene?.update();
      }).catch(()=>{});
    } catch(error) {
      console.warn('Luma entrance is using the lightweight fallback.',error);
      canvas.getContext('webgl')?.getExtension('WEBGL_lose_context')?.loseContext();
      fallback();
    }
  }).catch(fallback);
}

if (surface && window.L) window.L.returnToSpace=()=>showEntrance({reverse:true});

if (surface && LINK.searchParams.get('entrance')!=='off' && (preview||replay||!seen())) showEntrance();
