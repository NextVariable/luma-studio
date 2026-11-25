const poster = new URL('night-platform.jpg',import.meta.url).href;
const seatedCreator = new URL('seated-creator.png',import.meta.url).href;
const roomPhoto = new URL('daylight-room.jpg',import.meta.url).href;
const board = new URL('sample-board.jpg',import.meta.url).href;
const assetURL = file => '/media/'+encodeURIComponent(file);
const sans = 'Inter, -apple-system, "PingFang SC", sans-serif';
const sampleLines = ['末班车已经走了。','我等的不是车。','那就一起走吧。'];

function canvas(width,height) {
  const surface=document.createElement('canvas');
  surface.width=width; surface.height=height;
  return surface;
}
function loadImage(src) {
  return new Promise(resolve=>{
    const image=new Image();
    image.onload=()=>resolve(image);
    image.onerror=()=>resolve(null);
    image.src=src;
  });
}
function box(ctx,x,y,w,h,color,radius=0) {
  ctx.fillStyle=color;
  if (!radius) { ctx.fillRect(x,y,w,h); return; }
  ctx.beginPath(); ctx.roundRect(x,y,w,h,radius); ctx.fill();
}
function text(ctx,content,x,y,size,color='#ece8e0',weight=500,maxWidth) {
  ctx.font=weight+' '+size+'px '+sans;
  ctx.fillStyle=color;
  ctx.textBaseline='alphabetic';
  ctx.fillText(content,x,y,maxWidth);
}
function crop(ctx,image,x,y,w,h,cell) {
  if (!image) return box(ctx,x,y,w,h,'#272d30');
  const clipWidth=cell===undefined?image.width:image.width/3, clipHeight=image.height;
  const ratio=Math.max(w/clipWidth,h/clipHeight);
  const cw=w/ratio,ch=h/ratio;
  ctx.drawImage(image,clipWidth*(cell??0)+(clipWidth-cw)/2,(clipHeight-ch)/2,cw,ch,x,y,w,h);
}
function windowFrame(ctx,x,y,w,h,title,index) {
  box(ctx,x-5,y+13,w+10,h+4,'rgba(0,0,0,.26)',14);
  box(ctx,x,y,w,h,'#55504a',12);
  box(ctx,x+1,y+1,w-2,h-2,'#1d1e20',11);
  box(ctx,x+2,y+44,w-4,1,'#3b3935');
  text(ctx,index,x+22,y+29,13,'#cfaa7d',650);
  text(ctx,title,x+60,y+30,18);
}
function shotRef(work) {
  const shots=work?.shots||[];
  return shots.find(shot=>shot.image)||shots[0];
}

export function makeArt() {
  const wall=canvas(2800,670), main=canvas(1280,800), room=canvas(1280,800), actor=canvas(720,480);
  let still, samples, daylight, projectCover, currentWork, projectShots=[];
  function draw(work=currentWork) {
    currentWork=work;
    const title=work?.title||'末班车之后';
    const lines=(work?.script||'').split(/[\r\n]+/).map(line=>line.trim()).filter(Boolean);
    const shots=work?.shots||[];
    const shot=shotRef(work);
    const artNotes=work?.creative_brief?.style||(work?'为这一场确定光线、人物动作和视线。':'雨夜站台，保持同场光线与人物视线。');
    const ctx=wall.getContext('2d');
    const background=ctx.createLinearGradient(0,0,1400,670);
    background.addColorStop(0,'#47352d'); background.addColorStop(.46,'#292527');
    background.addColorStop(1,'#161a1c');
    box(ctx,0,0,2800,670,background);
    box(ctx,14,14,2772,642,'#232425',15);
    const halo=ctx.createLinearGradient(20,0,2770,550);
    halo.addColorStop(0,'#3e8a9f'); halo.addColorStop(.19,'#185993');
    halo.addColorStop(.66,'#174271'); halo.addColorStop(1,'#2e5b87');
    box(ctx,19,19,2762,632,halo,12);
    box(ctx,34,51,2732,1,'#a79b893d');
    text(ctx,'Luma 流幕',76,43,16,'#eee4d6',650);
    text(ctx,'创作工作室',2584,43,14,'#e1d5c5');

    windowFrame(ctx,99,83,461,410,'剧本','01');
    box(ctx,111,130,437,350,'#d8cbb6',4);
    text(ctx,title,148,182,32,'#2a2421',720,370);
    text(ctx,work?(work.episodes?.[0]?.title||'剧本'):'第一场　外景 / 站台 / 夜',149,221,15,'#71583e',600,350);
    box(ctx,149,239,354,1,'#ab9276');
    (work?(lines.length?lines.slice(0,5):['尚未写入剧本。']):['末班车驶离后的站台。','雨声压过远处的铁轨。',...sampleLines]).forEach((line,i)=>{
      text(ctx,line,149,278+i*32,16,'#46382e',490,360);
    });

    windowFrame(ctx,575,145,445,396,'创作助手','02');
    text(ctx,'镜头连续性',601,226,24,'#fff0df',640);
    const note=Array.from(artNotes).slice(0,46);
    for(let i=0;i<note.length;i+=18)text(ctx,note.slice(i,i+18).join(''),601,264+i/18*25,17,'#cdc1b1',470,351);
    text(ctx,'剧本　／　角色　／　分镜',601,368,16,'#e7ba85',550);
    box(ctx,598,444,381,54,'#313136',8);
    text(ctx,'描述这一镜的动作…',614,477,15,'#b6ada3');
    text(ctx,'↗',949,478,18,'#e7ba85');

    windowFrame(ctx,1889,68,470,334,'影视分镜','03');
    for(let i=0;i<(work?Math.min(3,shots.length):3);i++){
      const x=1910+i*141;
      crop(ctx,work?projectShots[i]:samples,x,135,128,100,work?undefined:i);
      text(ctx,String(i+1).padStart(2,'0')+'  '+(shots[i]?.framing||['全景','中景','近景'][i]),x,263,15);
    }
    box(ctx,1910,294,424,1,'#474039');
    text(ctx,shot?.description||(work?'等待添加分镜。':'阿远看向青禾，停了一拍。'),1910,329,17,'#cabdb0',500,420);

    windowFrame(ctx,2384,90,318,428,'视觉素材','04');
    crop(ctx,projectCover||still,2400,151,286,156);
    text(ctx,projectCover?'作品画面':'夜晚站台 · 概念美术',2400,334,17);
    const assets=work?.assets?.filter(asset=>asset.kind==='character'||asset.kind==='scene').slice(0,3)||
      [{name:'阿远',kind:'character'},{name:'青禾',kind:'character'},{name:'夜晚站台',kind:'scene'}];
    assets.forEach((asset,i)=>{
      box(ctx,2401,356+42*i,284,1,'#474039');
      text(ctx,asset.name,2401,383+42*i,14,'#dfd7cc',520,153);
      text(ctx,asset.kind==='scene'?'场景':'角色',2628,383+42*i,13,'#ae9679');
    });

    windowFrame(ctx,1940,418,387,170,'时间线','05');
    for(let i=0;i<(work?Math.min(3,shots.length):3);i++){
      const x=1959+i*115;
      crop(ctx,work?projectShots[i]:samples,x,472,105,54,work?undefined:i);
      text(ctx,'0'+(i+1)+'   '+(shots[i]?.duration||5)+' s',x,550,13,'#e0c7ac');
    }
    box(ctx,2095,467,2,96,'#e4aa79');

    const m=main.getContext('2d');
    const width=main.width, height=main.height;
    const scale=Math.min(1,width/740), inset=Math.round(24*scale);
    const header=height*.096, foot=height*.126;
    const bottom=height-foot, top=header+inset*.7;
    box(m,0,0,width,height,'#151618');
    box(m,0,0,width,header,'#202121');
    box(m,0,header,width,1,'#51483e');
    text(m,'Luma 流幕',inset*1.75,header*.64,25*scale,'#f6ece0',640);
    text(m,'放映预览',width-inset*5,header*.62,18*scale,'#e1c6a3',540);
    crop(m,projectCover||still,inset,top,width-inset*2,bottom-top);
    const fade=m.createLinearGradient(0,bottom-height*.23,0,bottom);
    fade.addColorStop(0,'transparent'); fade.addColorStop(1,'rgba(9,13,17,.94)');
    box(m,inset,bottom-height*.24,width-inset*2,height*.24,fade);
    text(m,title,inset*2.3,bottom-53*scale,46*scale,'#f5ede2',620,width-inset*5);
    text(m,projectCover?'作品预览':'概念美术预览',inset*2.3,bottom-21*scale,18*scale,'#dac3a6',480);
    const playhead=bottom+foot*.32;
    box(m,inset*1.8,playhead,width-inset*3.6,2,'#68605a');
    box(m,inset*1.8,playhead,(width-inset*3.6)/3,2,'#dfae78');
    const playX=inset*2, playY=bottom+foot*.65;
    m.beginPath();m.moveTo(playX,playY-11*scale);m.lineTo(playX,playY+11*scale);
    m.lineTo(playX+20*scale,playY);m.closePath();m.fillStyle='#f5ede2';m.fill();
    const running=shots.reduce((sum,s)=>sum+(Number(s.duration)||0),0);
    text(m,'00:00:00 / '+String(work?running:15).padStart(2,'0')+' s',playX+52*scale,playY+7*scale,16*scale,'#c9c2b9');
    text(m,(work?shots.length:3)+' 镜',width-inset*5,playY+7*scale,16*scale,'#c9c2b9');
  }
  function drawRoom() {
    crop(room.getContext('2d'),daylight,0,0,room.width,room.height);
  }
  return {wall,main,room,actor,
    resize(aspect) {
      const width=Math.min(1440,Math.max(270,Math.round(800*aspect)));
      if(main.width===width)return false;
      main.width=room.width=width;draw();drawRoom();
      return true;
    },
    async load(work) {
      if (!daylight) {
        const [posterImage,boardImage,roomImage,person]=await Promise.all(
          [poster,board,roomPhoto,seatedCreator].map(loadImage));
        still=posterImage; samples=boardImage; daylight=roomImage;
        if(person)actor.getContext('2d').drawImage(person,0,0,actor.width,actor.height);
        drawRoom();
      }
      if(work){
        const file=shotRef(work)?.image;
        [projectCover,...projectShots]=await Promise.all([
          file?loadImage(assetURL(file)):null,
          ...work.shots.slice(0,3).map(shot=>shot.image?loadImage(assetURL(shot.image)):null),
        ]);
      }
      draw(work);
    },
  };
}
