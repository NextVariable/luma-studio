const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/../web/production-ui.js','utf8'),app=fs.readFileSync(__dirname+'/../web/app.js','utf8');
test('partial candidates stay previewable but never become whole-shot cut defaults',()=>{
 const c=vm.createContext({});vm.runInContext(source,c);
 const s={duration:4,takes:[{id:'whole',kind:'video'},{id:'part',kind:'video',generation_segment:{start:2,end:4}}],selected_takes:{}};
 assert.equal(c.cutDraftDefaults(s).source_take_id,'whole');assert.equal(c.isPartialTake(s,s.takes[1]),true);
});
function pollingContext({view='shots',dirty=false,busy=false}={}){
 let draws=0,reads=0;const c=vm.createContext({view,pid:'p',state:{jobs:[{id:'j',project_id:'p',state:'running'}]},p:()=>({revision:1}),document:{querySelector:()=>null,querySelectorAll:()=>[],activeElement:null},hasUnsavedShot:()=>dirty,hasUnsavedCut:()=>false,hasUnsavedAssembly:()=>busy,refresh:async()=>{reads++;c.state.jobs[0].state='succeeded'},render:()=>draws++});
 vm.runInContext(app.slice(app.indexOf('async function pollProductionProgress()'),app.indexOf("bind('#asset-close'")),c);return {c,counts:()=>({draws,reads})};
}
test('completed local job updates the canvas without navigating away',async()=>{const x=pollingContext();await x.c.pollProductionProgress();assert.deepEqual(x.counts(),{draws:1,reads:1})});
test('completed export updates the delivery view',async()=>{const x=pollingContext({view:'delivery'});await x.c.pollProductionProgress();assert.equal(x.counts().draws,1)});
test('background progress never replaces unsaved shot or segment choices',async()=>{for(const options of [{dirty:true},{busy:true}]){const x=pollingContext(options);await x.c.pollProductionProgress();assert.deepEqual(x.counts(),{draws:0,reads:0})}});
