/* A wheel gesture owns one action until its momentum ends or direction reverses. */
(function(root){
const L=root.L=root.L||{};

L.wheelPixels=(event,axis='y')=>{
  const scale=event.deltaMode===1?16:event.deltaMode===2?(event.currentTarget?.clientHeight||600):1;
  return (axis==='x'?event.deltaX:event.deltaY)*scale;
};

L.wheelGesture=({threshold=5,gap=135}={})=>{
  let last=-Infinity,direction=0,distance=0,consumed=false,peak=0,previous=0,firedAt=-Infinity,lastPointer;
  return (delta,now,{scrolling=false,discrete=false,pointer}={})=>{
    if(!delta)return 0;
    const next=Math.sign(delta),magnitude=Math.abs(delta),elapsed=now-last;
    // A mouse can report equal, separately spaced detents in pixel mode.
    // Once a burst decays, equal tail events are still part of that burst.
    const separateDetent=elapsed>=42&&magnitude>=threshold&&
      (discrete||(Math.abs(magnitude-previous)<.05&&previous>=peak-.05));
    const renewedForce=magnitude>=Math.max(threshold,previous*2.2,peak*.55)&&previous<=peak*.35;
    const newImpulse=consumed&&now-firedAt>=42&&
      (separateDetent||renewedForce||elapsed>=42&&magnitude>=Math.max(8,peak*1.3));
    const movedPointer=pointer&&lastPointer&&elapsed>=28&&
      Math.hypot(pointer.x-lastPointer.x,pointer.y-lastPointer.y)>32;
    if(elapsed>gap||next!==direction||newImpulse||movedPointer){
      distance=0;consumed=false;peak=0;
    }
    last=now;lastPointer=pointer;direction=next;previous=magnitude;peak=Math.max(peak,magnitude);
    if(scrolling){consumed=true;firedAt=now;return 0}
    if(consumed)return 0;
    distance+=magnitude;
    if(distance<threshold)return 0;
    consumed=true;firedAt=now;
    return direction;
  };
};

L.mobilePaging=()=>root.matchMedia?.('(max-width: 760px), (hover: none) and (pointer: coarse)').matches??false;

L.swipeDirection=(start,end,threshold=12,axis='y')=>{
  if(!start||!end)return 0;
  const dx=end.clientX-start.clientX,dy=end.clientY-start.clientY;
  const [along,across]=axis==='x'?[dx,dy]:[dy,dx];
  return Math.abs(along)>=threshold&&Math.abs(along)>=Math.abs(across)*1.2?-Math.sign(along):0;
};

L.canScrollWithin=(el,dy,boundary)=>{
  for(let n=el;n&&n!==boundary?.parentElement&&n!==document.body;n=n.parentElement){
    if(n.scrollHeight>n.clientHeight+1&&/(auto|scroll)/.test(getComputedStyle(n).overflowY)){
      if(dy>0?n.scrollTop+n.clientHeight<n.scrollHeight-1:n.scrollTop>1)return true;
    }
    if(n===boundary)break;
  }
  return false;
};
})(typeof window!=='undefined'?window:globalThis);
