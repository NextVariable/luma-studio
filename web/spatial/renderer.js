// Screen surfaces in metres. The viewer starts inside the room, on the positive Z side.
const TAU = Math.PI * 2;
const FLOOR = -2.85;
const WALL_RADIUS = 13.1;
const MAIN_Z = .42;
const MAIN_WIDTH = 6.9;
const mix = (a, b, t) => a + (b - a) * t;
export const ramp = (a, b, p) => {
  const t = Math.min(1, Math.max(0, (p - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
const length = v => Math.hypot(...v);
const unit = v => v.map(x => x / length(v));
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const dot = (a,b) => a.reduce((sum,x,i) => sum+x*b[i], 0);

export function cameraAt(progress, aspect, pointer = [0, 0]) {
  const focal = 1 / Math.tan(39 * Math.PI / 360);
  const dockDistance = MAIN_WIDTH * focal / (2 * aspect);
  const wideDistance = Math.max(21.5, dockDistance * 1.82);
  const travel = ramp(0, 1, progress);
  const straighten = 1 - ramp(.24, .72, progress);
  const eye = [(-3.9 + pointer[0] * .6)*straighten, (1.5 + pointer[1]*.3)*straighten,
    MAIN_Z + mix(wideDistance, dockDistance, travel)];
  const aim = [-.42*straighten, -1.43*straighten, MAIN_Z];
  const forward = unit(aim.map((point,i) => point-eye[i]));
  const right = unit(cross(forward,[0,1,0]));
  const up = cross(right,forward);
  return {eye, forward, right, up, focal, aspect};
}

export function portalRect(camera, width, height) {
  const corners = [[-MAIN_WIDTH / 2, MAIN_WIDTH / camera.aspect / 2],
    [MAIN_WIDTH / 2, -MAIN_WIDTH / camera.aspect / 2]].map(([x,y]) => {
    const point = [x-camera.eye[0], y-camera.eye[1], MAIN_Z-camera.eye[2]];
    const depth = dot(point,camera.forward);
    return [width*(1+camera.focal*dot(point,camera.right)/(camera.aspect*depth))/2,
      height*(1-camera.focal*dot(point,camera.up)/depth)/2];
  });
  return [corners[0][0],corners[0][1],corners[1][0]-corners[0][0],corners[1][1]-corners[0][1]];
}

const roomVertex = `
attribute vec2 aPoint;
varying vec2 vRay;
void main(){vRay=aPoint;gl_Position=vec4(aPoint,0.,1.);}
`;
const roomFragment = `
precision highp float;
varying vec2 vRay;
uniform vec3 uEye,uRight,uUp,uForward;
uniform vec3 uPlateEye,uPlateRight,uPlateUp,uPlateForward;
uniform vec2 uLens;
uniform float uTime,uRoomBlend;
uniform sampler2D uPlate;
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec2 p){
  vec2 i=floor(p),f=fract(p); f=f*f*(3.-2.*f);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+1.),f.x),f.y);
}
float boxEntry(vec3 origin,vec3 direction,vec3 lo,vec3 hi){
  vec3 toA=(lo-origin)/direction, toB=(hi-origin)/direction;
  vec3 first=min(toA,toB), last=max(toA,toB);
  float near=max(first.x,max(first.y,first.z)), far=min(last.x,min(last.y,last.z));
  return far>=max(near,0.)&&near>0.?near:1000.;
}
void main(){
  vec3 d=normalize(uForward+(vRay.x*uRight*uLens.x+vRay.y*uUp)/uLens.y);
  vec3 lo=vec3(-10.4,-2.85,-7.2),hi=vec3(10.4,4.5,110.);
  vec3 travel=(mix(lo,hi,step(0.,d))-uEye)/d;
  float t=min(min(travel.x,travel.y),travel.z);
  vec3 p=uEye+d*t;
  float wall=step(travel.z,t+.001), vertical=step(travel.y,t+.001), floorSide=vertical*step(d.y,0.);
  vec2 material=wall>.5?p.xy:vertical>.5?p.xz:p.zy;
  float plaster=.93+.07*noise(material*1.6)+.028*noise(material*45.);
  float left=exp(-.011*pow(p.x+9.,2.)-.018*pow(p.z-2.,2.));
  float warm=exp(-.045*pow(p.y-2.8,2.)-.026*pow(p.x-5.5,2.)-.032*pow(p.z+5.,2.));
  vec3 c=(vec3(.145,.134,.119)+vec3(.33,.29,.238)*left+vec3(.16,.11,.064)*warm)*plaster;
  float baseShadow=.70+.30*smoothstep(0.,1.55,p.y+2.85);
  c*=mix(baseShadow,1.,vertical);
  if(wall>.5){
    float joints=smoothstep(.003,.023,abs(fract((p.x+1.8)/3.6)-.5));
    c*=mix(.68,1.,joints);
    float screenSpill=exp(-pow(p.x/7.2,2.)-pow((p.y+.03)/1.7,2.));
    c+=vec3(.057,.071,.077)*screenSpill*(.97+.03*sin(uTime*.38));
    float led=(1.-smoothstep(.015,.04,abs(p.y-3.86)))*smoothstep(-7.5,-7.,p.x)*(1.-smoothstep(7.,7.5,p.x));
    c+=led*vec3(.67,.48,.28);
    float alcove=smoothstep(8.3,8.38,p.x);
    c*=1.-alcove*.30;
  } else if(vertical<.5){
    float bars=1.-smoothstep(.023,.05,abs(fract((p.z+4.6)/2.25)-.5));
    float opening=smoothstep(-5.2,-5.08,p.z)*(1.-smoothstep(8.1,8.2,p.z))
      *smoothstep(-1.65,-1.57,p.y)*(1.-smoothstep(3.65,3.78,p.y));
    if(p.x<0.){
      float horizon=smoothstep(-1.2,2.7,p.y);
      vec3 pane=mix(vec3(.47,.48,.46),vec3(.88,.83,.71),horizon);
      pane*=.79+.20*noise(vec2(p.z*.3,p.y*.7)+uTime*.015);
      c=mix(c,mix(pane,vec3(.20,.172,.141),bars),opening);
    } else {
      float slat=smoothstep(.1,.22,fract(p.z*4.4));
      c*=mix(.65,1.,slat); c+=vec3(.075,.048,.025)*opening;
    }
  } else if(floorSide>.5){
    float plank=smoothstep(.002,.022,abs(fract(p.x/1.36)-.5));
    float seam=smoothstep(.002,.013,abs(fract((p.z+floor((p.x+.68)/1.36)*1.2)/5.3)-.5));
    float gloss=.6+.4*noise(vec2(p.x*7.,p.z*.38));
    c=(vec3(.124,.111,.097)+vec3(.41,.34,.253)*left)*(.76+.24*plank*seam)*gloss;
    float pool=exp(-pow((p.x+5.5-.26*p.z)/2.4,2.)-pow((p.z-1.)/6.6,2.));
    c+=vec3(.24,.19,.13)*pool*(.76+.24*smoothstep(.22,.68,fract((p.z-p.x*.27)/2.25)));
    c-=vec3(.035)*exp(-pow(p.x/6.5,2.)-pow((p.z-1.)/2.4,2.));
  } else {
    c*=.86;
    float light=(1.-smoothstep(.027,.068,abs(abs(p.x)-7.8)))*smoothstep(-6.9,-6.55,p.z)*(1.-smoothstep(12.,12.6,p.z));
    c+=light*vec3(.72,.56,.39);
    c+=exp(-35.*abs(abs(p.x)-7.8))*vec3(.14,.095,.06);
    c*=.91+.09*smoothstep(.01,.05,abs(fract(p.z/2.2)-.5));
  }
  float vignette=1.-.25*dot(vRay*vec2(.62,.62),vRay);
  c=pow(max(c*vignette,0.),vec3(.80));
  c+=.012*(hash(gl_FragCoord.xy)-.5);
  // Reproject the same daylight room onto its wall, floor and nearer sofa volume.
  // The reference view has no parallax error. A moving camera samples fixed world positions.
  float sofa=boxEntry(uEye,d,vec3(-3.3,-2.84,12.9),vec3(9.3,-1.20,16.4));
  vec3 at=uEye+d*min(t,sofa)-uPlateEye;
  float depth=max(.02,dot(at,uPlateForward));
  vec2 point=vec2(dot(at,uPlateRight)*uLens.y/uLens.x,-dot(at,uPlateUp)*uLens.y)/depth*.5+.5;
  vec2 edge=min(point,1.-point);
  float inPlate=smoothstep(-.045,-.002,min(edge.x,edge.y));
  vec3 photo=texture2D(uPlate,point).rgb;
  c=mix(c,vec3(.68,.56,.43),.48);
  gl_FragColor=vec4(mix(c,photo,inPlate*uRoomBlend),1.);
}
`;
const screenVertex = `
attribute vec3 aWorld;
attribute vec2 aUV;
uniform vec3 uEye,uRight,uUp,uForward;
uniform vec2 uLens;
uniform float uReflection;
varying vec2 vUV;
varying vec3 vPosition;
void main(){
  vec3 p=aWorld; if(uReflection>.5)p.y=-5.7-p.y;
  vec3 relative=p-uEye;
  float z=dot(relative,uForward);
  gl_Position=vec4(dot(relative,uRight)*uLens.y/uLens.x,dot(relative,uUp)*uLens.y,z*1.002-.12,z);
  vUV=aUV; vPosition=p;
}
`;
const screenFragment = `
precision highp float;
uniform sampler2D uImage;
uniform float uReflection,uFade,uTime,uPortal,uDock,uActor;
uniform vec3 uEye;
varying vec2 vUV;
varying vec3 vPosition;
void main(){
  if(uActor>.5){
    vec4 person=texture2D(uImage,vUV);
    // Hide the lower body along the sloping near edge of the sofa back.
    float sofaEdge=mix(1.0,.76,vUV.x);
    person.a *= (1.-smoothstep(sofaEdge-.014,sofaEdge,vUV.y))*uFade;
    if(person.a<.015)discard;
    gl_FragColor=person;
    return;
  }
  vec2 size=vec2(.991,.977);
  vec2 corner=max(abs(vUV-.5)-size*.5+vec2(.006,.018),0.)/vec2(.006,.018);
  if(uPortal<.5&&length(corner)>1.0)discard;
  vec3 color=texture2D(uImage,vUV).rgb;
  float edge=smoothstep(.0,.005,min(vUV.x,1.-vUV.x))*smoothstep(.0,.012,min(vUV.y,1.-vUV.y));
  float glint=exp(-pow((vUV.x-.17-uEye.x*.085)/.19,2.))*(.3+.7*vUV.y);
  color=mix(vec3(.41,.37,.33)*(.5+.5*glint),color,edge);
  color+=vec3(.090,.079,.066)*glint*.38*(1.-uPortal);
  color=mix(color,vec3(.063,.067,.074),uPortal*uDock*.83);
  if(uReflection>.5){
    float a=.115*exp(-.10*dot(vPosition.xz,vPosition.xz)/10.)
      * smoothstep(0.,.24,vUV.y)*smoothstep(0.,.14,1.-vUV.y);
    gl_FragColor=vec4(color,a*uFade);
  } else gl_FragColor=vec4(color,uFade);
}
`;

function program(gl, vs, fs) {
  const shaders = [[gl.VERTEX_SHADER,vs],[gl.FRAGMENT_SHADER,fs]].map(([type,source]) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader,source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
    return shader;
  });
  const result = gl.createProgram();
  shaders.forEach(shader => gl.attachShader(result,shader)); gl.linkProgram(result);
  shaders.forEach(shader => gl.deleteShader(shader));
  if (!gl.getProgramParameter(result,gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(result));
  return result;
}

function strip(steps, position) {
  const vertices = [];
  for (let i=0;i<=steps;i++) {
    const u=i/steps;
    for (const y of [0,1]) vertices.push(...position(u,y),u,1-y);
  }
  return new Float32Array(vertices);
}

export function makeScene(canvas, wallArt, mainArt, roomArt, actorArt) {
  const gl = canvas.getContext('webgl',{antialias:false,alpha:false, powerPreference:'high-performance'});
  if (!gl) throw Error('WebGL unavailable');
  const room = program(gl,roomVertex,roomFragment), screen = program(gl,screenVertex,screenFragment);
  const resources = [];
  const mesh = (vertices,dynamic=false) => {
    const buffer=gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.bufferData(gl.ARRAY_BUFFER,vertices,dynamic?gl.DYNAMIC_DRAW:gl.STATIC_DRAW);
    resources.push(() => gl.deleteBuffer(buffer));
    return buffer;
  };
  const texture = source => {
    const tex=gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D,tex);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);
    resources.push(() => gl.deleteTexture(tex));
    return tex;
  };
  const quad=mesh(new Float32Array([-1,-1,1,-1,-1,1,1,1]));
  const wallShape=strip(76,(u,y) => {
    const angle=(u-.5)*TAU/3.96;
    return [Math.sin(angle)*WALL_RADIUS,mix(-2.00,4.24,y),WALL_RADIUS*(1-Math.cos(angle))-.34];
  });
  const wall=mesh(wallShape), main=mesh(new Float32Array(20),true), actor=mesh(new Float32Array(20),true);
  const wallTex=texture(wallArt), mainTex=texture(mainArt), roomTex=texture(roomArt);
  const actorTex=texture(actorArt);
  const roomPoint=gl.getAttribLocation(room,'aPoint');
  const world=gl.getAttribLocation(screen,'aWorld'), uv=gl.getAttribLocation(screen,'aUV');
  const locations = p => Object.fromEntries(['Eye','Right','Up','Forward','Lens','Time','Reflection','Fade','Portal','Dock','Actor','Image']
    .map(key=>[key,gl.getUniformLocation(p,'u'+key)]));
  const roomU=locations(room), screenU=locations(screen);
  const photoUniforms=Object.fromEntries(['Eye','Right','Up','Forward','Blend','Sampler'].map(
    key=>[key,gl.getUniformLocation(room,key==='Blend'?'uRoomBlend':key==='Sampler'?'uPlate':'uPlate'+key)]));
  gl.useProgram(screen); gl.uniform1i(screenU.Image,0);
  gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  const uniforms=(u,camera,time) => {
    gl.uniform3fv(u.Eye,camera.eye); gl.uniform3fv(u.Right,camera.right);
    gl.uniform3fv(u.Up,camera.up); gl.uniform3fv(u.Forward,camera.forward);
    gl.uniform2f(u.Lens,camera.aspect,camera.focal); gl.uniform1f(u.Time,time);
  };
  function drawScreen(buffer,tex,count,reflect,isMain,fade=1,isActor=0) {
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.enableVertexAttribArray(world); gl.vertexAttribPointer(world,3,gl.FLOAT,false,20,0);
    gl.enableVertexAttribArray(uv); gl.vertexAttribPointer(uv,2,gl.FLOAT,false,20,12);
    gl.uniform1f(screenU.Reflection,reflect); gl.uniform1f(screenU.Fade,fade); gl.uniform1f(screenU.Portal,isMain);
    gl.uniform1f(screenU.Actor,isActor);
    gl.bindTexture(gl.TEXTURE_2D,tex); gl.drawArrays(gl.TRIANGLE_STRIP,0,count);
    gl.disableVertexAttribArray(world); gl.disableVertexAttribArray(uv);
  }
  let ratio;
  return {
    draw(camera,time,docking,progress) {
      const plate=cameraAt(0,camera.aspect);
      if (ratio!==camera.aspect) {
        ratio=camera.aspect;
        gl.bindBuffer(gl.ARRAY_BUFFER,main);
        // Portrait screens keep a compact viewing composition. Near the portal
        // the native workbench assumes the exact viewport dimensions.
        gl.bufferSubData(gl.ARRAY_BUFFER,0,strip(1,(u,y) => [(u-.5)*MAIN_WIDTH,(y-.5)*MAIN_WIDTH/ratio,MAIN_Z]));
        // Place the cutout in the initial camera's view plane, in front of the curved display.
        const depth=11.5, height=.348, width=height*actorArt.width/actorArt.height/ratio;
        const center=ratio<.8?.69:.684, top=ratio<.8?.46:.398;
        const person=strip(1,(u,y)=>{
          const x=(2*(center+(u-.5)*width)-1)*ratio*depth/plate.focal;
          const v=(1-2*(top+(1-y)*height))*depth/plate.focal;
          return plate.eye.map((position,i)=>position + plate.forward[i]*depth + plate.right[i]*x + plate.up[i]*v);
        });
        gl.bindBuffer(gl.ARRAY_BUFFER,actor);
        gl.bufferSubData(gl.ARRAY_BUFFER,0,person);
      }
      gl.viewport(0,0,canvas.width,canvas.height);
      gl.clear(gl.DEPTH_BUFFER_BIT);
      gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST);
      gl.useProgram(room); uniforms(roomU,camera,time);
      gl.uniform3fv(photoUniforms.Eye,plate.eye); gl.uniform3fv(photoUniforms.Right,plate.right);
      gl.uniform3fv(photoUniforms.Up,plate.up); gl.uniform3fv(photoUniforms.Forward,plate.forward);
      gl.uniform1f(photoUniforms.Blend,1-ramp(.60,.94,progress));
      gl.uniform1i(photoUniforms.Sampler,0);
      gl.bindTexture(gl.TEXTURE_2D,roomTex);
      gl.bindBuffer(gl.ARRAY_BUFFER,quad); gl.enableVertexAttribArray(roomPoint);
      gl.vertexAttribPointer(roomPoint,2,gl.FLOAT,false,0,0); gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
      gl.disableVertexAttribArray(roomPoint);
      gl.useProgram(screen); uniforms(screenU,camera,time); gl.uniform1f(screenU.Dock,docking);
      gl.enable(gl.BLEND);
      const reflection=ramp(.65,.95,progress)*.28;
      if(reflection>0){
        drawScreen(wall,wallTex,wallShape.length/5,1,0,reflection);
        drawScreen(main,mainTex,4,1,1,reflection);
      }
      gl.disable(gl.BLEND); gl.enable(gl.DEPTH_TEST);
      drawScreen(wall,wallTex,wallShape.length/5,0,0); drawScreen(main,mainTex,4,0,1);
      const foreground=1-ramp(.33,.59,progress);
      if(foreground>0){
        gl.enable(gl.BLEND); gl.depthMask(false);
        drawScreen(actor,actorTex,4,0,0,foreground,1);
        gl.depthMask(true);
      }
    },
    update() {
      for (const [tex,source] of [[wallTex,wallArt],[mainTex,mainArt],[roomTex,roomArt]]) {
        gl.bindTexture(gl.TEXTURE_2D,tex);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);
      }
    },
    dispose() {
      resources.forEach(release => release());
      gl.deleteProgram(room); gl.deleteProgram(screen);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    },
  };
}
