const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'../web');
const workspace=fs.readFileSync(path.join(root,'workspace-ui.js'),'utf8');
const drafts=workspace.slice(workspace.indexOf('const draftBaselines='),workspace.indexOf('\nfunction render(){'));
function fixture(){
 const storage=new Map(),project={revision:4},controls=[{id:'framing',value:'中景'},{id:'revision-instruction',value:''}];
 const context=vm.createContext({localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},p:()=>project,draftKey:()=> 'shot1',draftControls:()=>controls,controlKey:el=>el.id,draftValue:el=>el.value,$:()=>null,toast:()=>{}});
 vm.runInContext(drafts,context);context.controls=controls;vm.runInContext('controls.forEach(el=>draftBaselines.set(el,el.value))',context);
 return {context,storage,project,controls,draft:()=>JSON.parse(storage.get('shot1'))};
}
test('typing a revision request stores no unedited shot fields',()=>{
 const f=fixture();f.controls[1].value='改为近景';f.context.rememberDraft();
 assert.deepEqual(f.draft().fields,{'revision-instruction':'改为近景'});
});
test('editing and reverting a field removes the draft instead of keeping stale intent',()=>{
 const f=fixture();f.controls[0].value='近景';f.context.rememberDraft();assert.equal(f.draft().bases.framing,'中景');
 f.controls[0].value='中景';f.context.rememberDraft();assert.equal(f.storage.has('shot1'),false);
});
test('remote changes block conflicting restoration, while unrelated revisions preserve valid edits',()=>{
 const f=fixture();const d={revision:3,fields:{framing:'近景'},bases:{framing:'中景'}};
 assert.equal(f.context.draftCanRestore(d,'framing','远景'),false);
 assert.equal(f.context.draftCanRestore(d,'framing','中景'),true);
 assert.equal(f.context.draftCanRestore({revision:3,fields:{framing:'近景'}},'framing','远景'),false);
 assert.equal(f.context.draftCanRestore({revision:3,fields:{'revision-instruction':'再试'}},'revision-instruction',''),true);
});
test('saving another field does not erase a withheld conflicting draft',()=>{
 const f=fixture();f.storage.set('shot1',JSON.stringify({revision:3,fields:{framing:'远景'},bases:{framing:'特写'}}));
 f.controls[1].value='保留对白';f.context.rememberDraft();assert.equal(f.draft().fields.framing,'远景');assert.equal(f.draft().bases.framing,'特写');
});
test('outdated dialogue draft cannot silently replace the new saved lines',()=>{
 const f=fixture(),saved=[{id:'l1',text:'新对白'}];f.storage.set('shot1',JSON.stringify({revision:3,fields:{'dialogue-lines':JSON.stringify([{id:'l1',text:'旧对白'}])}}));
 const editor=fs.readFileSync(path.join(root,'editor-ui.js'),'utf8');vm.runInContext(editor.slice(editor.indexOf('function linesForEditor'),editor.indexOf('function linesEditor')),f.context);
 assert.deepEqual(f.context.linesForEditor({lines:saved}),saved);
});
const canvas=fs.readFileSync(path.join(root,'canvas-ui.js'),'utf8');
async function polling(mutate){
 let resolve,draws=0;const initial={jobs:[]};
 const c=vm.createContext({activeTaskStates:['queued','running','submitting','waiting_review'],view:'shots',pid:'p',eid:'e',selected:'s',state:initial,document:{addEventListener:()=>{},querySelector:()=>null,activeElement:null},hasUnsavedShot:()=>false,hasUnsavedCut:()=>false,currentCanvasJobs:()=>[{state:'running'}],api:()=>new Promise(r=>resolve=r),render:()=>draws++,setInterval:()=>{}});
 vm.runInContext(canvas.slice(canvas.indexOf('let canvasPollBusy=')),c);const running=c.pollCanvas();mutate(c);resolve({jobs:[{state:'succeeded'}]});await running;return {c,draws,initial};
}
test('poll response cannot overwrite a keystroke or navigation made during the request',async()=>{
 for(const mutate of [c=>vm.runInContext('canvasInputRevision++',c),c=>c.selected='s2',c=>c.state={newSave:true}]){
  const result=await polling(mutate);assert.equal(result.draws,0);
 }
});
test('idle canvas accepts a completed task update',async()=>{const result=await polling(()=>{});assert.equal(result.draws,1);assert.equal(result.c.state.jobs[0].state,'succeeded')});
test('delivery progress refreshes in place and a late response cannot interrupt navigation',async()=>{
 for(const navigate of [false,true]){
  let finish,draws=0;
  const c=vm.createContext({activeTaskStates:['queued','running'],view:'delivery',pid:'p',eid:'e',selected:'s',state:{jobs:[]},document:{addEventListener:()=>{},querySelector:()=>null,activeElement:null},currentDeliveryJob:()=>({state:'running'}),api:()=>new Promise(resolve=>finish=resolve),render:()=>draws++,setInterval:()=>{}});
  vm.runInContext(canvas.slice(canvas.indexOf('let canvasPollBusy=')),c);const pending=c.pollCanvas();if(navigate)c.view='overview';finish({jobs:[{state:'succeeded'}]});await pending;assert.equal(draws,navigate?0:1);
 }
});
