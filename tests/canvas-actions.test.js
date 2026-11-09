const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const runSource=source.match(/^async function run\(kind[^\n]+/m)[0];
function workspace(options={}){
 const events=[];
 const context=vm.createContext({
  view:options.view||'shots',pid:'p1',eid:'e1',state:{spending:{remaining:options.remaining??1},dify:{revision:true,audio:true,shots:true}},
  kinds:{revision:'单镜修订',audio:'配音',shots:'分镜'},p:()=>({id:'p1'}),episode:()=>({title:'第1集'}),
  hasUnsavedShot:()=>!!options.dirty,hasUnsavedCut:()=>false,confirmAction:async()=>options.confirm!==false,
  crypto:{randomUUID:()=> 'request-1'},api:async(route,body)=>{events.push({route,body})},
  clearDraft:fields=>events.push({clear:fields}),refresh:async()=>events.push({refresh:true}),toast:message=>events.push({toast:message})
 });
 vm.runInContext(runSource,context);return {context,events};
}
test('confirmed single-shot revision stays on the canvas with the target intact',async()=>{
 const {context,events}=workspace();await context.run('revision',{shot_id:'s2',instruction:'改近景'});
 assert.equal(context.view,'shots');const request=events.find(e=>e.route==='/api/jobs');
 assert.equal(request.body.shot_id,'s2');assert.equal(request.body.instruction,'改近景');assert.equal(request.body.episode_id,'e1');
 assert.ok(events.some(e=>e.clear?.includes('revision-instruction')));assert.ok(events.some(e=>e.refresh));
});
test('single-shot media returns to the same canvas, whole-episode planning opens records',async()=>{
 const media=workspace();await media.context.run('audio',{shot_id:'s2'});assert.equal(media.context.view,'shots');
 const planning=workspace();await planning.context.run('shots');assert.equal(planning.context.view,'jobs');
});
test('zero allowance never submits a paid job',async()=>{
 const {context,events}=workspace({remaining:0});await context.run('revision',{shot_id:'s2',instruction:'改近景'});
 assert.equal(events.some(e=>e.route),false);assert.equal(context.view,'shots');
});
test('unsaved intent and declined confirmation never submit a job',async()=>{
 for(const options of [{dirty:true},{confirm:false}]){const {context,events}=workspace(options);await context.run('revision',{shot_id:'s2'});assert.equal(events.some(e=>e.route),false)}
});
test('local export stays on the delivery page even when model allowance is zero',async()=>{
 const {context,events}=workspace({view:'delivery',remaining:0});await context.run('export');
 assert.equal(context.view,'delivery');assert.equal(events.find(e=>e.route==='/api/jobs').body.kind,'export');
});
