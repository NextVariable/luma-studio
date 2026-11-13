const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const core=fs.readFileSync('web/js/core.js','utf8');
const start=core.indexOf('L.quoteCost=');
const source=core.slice(start,core.indexOf('\n};',core.indexOf('L.run=',start))+3);

test('generation confirmation displays provider price and sends its digest only on approval',async()=>{
  const calls=[];
  let approve=false;
  const L={
    S:{eid:'e',data:{spending:{remaining:3}}},
    project:()=>({id:'p'}), needService:async()=>true, jobName:()=> '生成视频', refresh:async()=>{},
    api:async(path,body)=>{
      calls.push([path,body]);
      if(path==='/api/jobs/quote')return {provider:'fal',model_label:'Kling',duration:5,estimated_usd:'0.35',
        authorization_calls:1,reference_count:1,digest:'quoted'};
      return {id:'j'};
    },
    confirmBox:async(_title,message)=>{
      assert.match(message,/fal · Kling · 5 秒/);
      assert.match(message,/\$0\.35/);
      assert.match(message,/本机授权 1 次/);
      return approve;
    }
  };
  vm.runInNewContext(source,{L,crypto:{randomUUID:()=> 'nonce'}});
  const target={shot_id:'s',segment_id:'clip',preparation_digest:'plan'};
  assert.equal(await L.run('video',target),null);
  assert.deepEqual(calls.map(c=>c[0]),['/api/jobs/quote']);
  approve=true;
  assert.equal(await L.run('video',target),'j');
  assert.equal(calls.at(-1)[0],'/api/jobs');
  assert.equal(calls.at(-1)[1].quote_digest,'quoted');
  assert.equal(calls.at(-1)[1].preparation_digest,'plan');
});
