const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

const source=fs.readFileSync('web/spatial/renderer.js','utf8');
const renderer=import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('projected docking frame exactly covers landscape and portrait viewports',async()=>{
  const {cameraAt,portalRect}=await renderer;
  for (const [width,height] of [[1440,900],[1920,1080],[390,844],[768,1024],[2560,1080]]) {
    const camera=cameraAt(1,width/height,[1,-1]);
    const rect=portalRect(camera,width,height);
    assert.ok(rect.every((value,i)=>Math.abs(value-[0,0,width,height][i])<.01));
    const before=portalRect(cameraAt(.8,width/height),width,height);
    assert.ok(before[0]>0&&before[1]>0&&before[2]<width&&before[3]<height);
  }
});

test('scroll depth advances the real camera and keeps reversible spatial coordinates',async()=>{
  const {cameraAt,portalRect}=await renderer;
  const aspect=1440/900;
  const outward=cameraAt(.2,aspect,[.5,-.1]);
  const inward=cameraAt(.5,aspect,[.5,-.1]);
  assert.ok(outward.eye[2]>inward.eye[2]);
  assert.ok(portalRect(outward,1440,900)[2]<portalRect(inward,1440,900)[2]);
  assert.deepEqual(cameraAt(.2,aspect,[.5,-.1]),outward);
  assert.notDeepEqual(cameraAt(0,aspect,[.5,-.1]).eye,cameraAt(0,aspect,[0,0]).eye);
  assert.deepEqual(cameraAt(.82,aspect,[.5,-.1]).eye,cameraAt(.82,aspect,[0,0]).eye);
});
