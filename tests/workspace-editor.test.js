const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const editor=fs.readFileSync(path.join(__dirname,'../web/editor-ui.js'),'utf8');
function tabFixture(){
 const tabs=['intent','dialogue','takes'].map(name=>({dataset:{shotTab:name},attrs:{},setAttribute(k,v){this.attrs[k]=v},focus(){this.focused=true}}));
 const panels=tabs.map(t=>({dataset:{editorPanel:t.dataset.shotTab}})),footer={};
 const c=vm.createContext({document:{querySelectorAll:selector=>selector==='[data-shot-tab]'?tabs:panels,querySelector:()=>footer}});
 vm.runInContext(editor,c);c.bindShotTabs();return {c,tabs,panels,footer};
}
test('the three editor tabs expose exactly one panel and keyboard navigation wraps correctly',()=>{
 const {tabs,panels,footer}=tabFixture();
 for(let i=0;i<tabs.length;i++){
  tabs[i].onclick();assert.equal(tabs.filter(t=>t.attrs['aria-selected']==='true').length,1);
  assert.equal(panels.filter(p=>!p.hidden).length,1);assert.equal(panels[i].hidden,false);assert.equal(footer.hidden,i===2);
 }
 tabs[2].onkeydown({key:'ArrowRight',preventDefault(){}});assert.equal(panels[0].hidden,false);assert.equal(tabs[0].focused,true);
 tabs[0].onkeydown({key:'End',preventDefault(){}});assert.equal(panels[2].hidden,false);
});
test('starting and adding dialogue never inserts fabricated words and focuses the new line',()=>{
 const handlers={},hidden={value:'null'},input={focus(){this.focused=true}},callbacks=[];
 let drafted=0;
 const c=vm.createContext({crypto:{randomUUID:()=> 'new-line'},$:selector=>selector==='#dialogue-lines'?hidden:selector==='[data-key=dialogue]'?{value:''}:null,bind:(id,fn)=>handlers[id]=fn,rememberDraft:()=>drafted++,render(){},requestAnimationFrame:fn=>callbacks.push(fn),document:{querySelectorAll:selector=>selector==='[data-line-text]'?[input]:[]}});
 vm.runInContext(editor,c);c.bindLines({dialogue:''});handlers['#lines-start']();callbacks.shift()();
 assert.equal(JSON.parse(hidden.value)[0].text,'');assert.equal(input.focused,true);assert.equal(drafted,1);
 c.readLines=()=>[{id:'old',text:'原对白'}];handlers['#line-add']();callbacks.shift()();
 assert.deepEqual(JSON.parse(hidden.value).map(l=>l.text),['原对白','']);assert.equal(drafted,2);
});
function editFixture(options={}){
 const s={id:'s1',locked:!!options.locked,lines:[{id:'l1',text:'旧台词'}],asset_ids:['a1'],image:'old.png',takes:[{id:'t1',file:'old.png'}]},calls=[];
 const c=vm.createContext({shot:()=>s,readLines:()=>[],document:{querySelectorAll:()=>[{dataset:{key:'framing'},value:'近景',type:'text'}]},$:()=>({selectedOptions:[{value:'a1'}]}),save:async options=>calls.push(options),toast:()=>{},hasUnsavedCut:()=>false,hasUnsavedShot:()=>!!options.dirty});
 vm.runInContext(editor,c);c.readLines=()=>[];c.hasUnsavedShot=()=>!!options.dirty;return {c,s,calls};
}
test('saving an empty dialogue list preserves deletion, selected media and takes',async()=>{
 const {c,s,calls}=editFixture();await c.saveShotEdits();assert.deepEqual(s.lines,[]);assert.equal(s.framing,'近景');assert.equal(s.image,'old.png');assert.equal(s.takes[0].id,'t1');assert.equal(calls.length,1);assert.ok(calls[0].draftFields.includes('dialogue-lines'));
});
test('locked edits and dirty approvals never save',async()=>{
 const locked=editFixture({locked:true});await assert.rejects(locked.c.saveShotEdits(),/解除/);assert.equal(locked.calls.length,0);
 const dirty=editFixture({dirty:true});await assert.rejects(dirty.c.approveShot(),/先保存/);assert.equal(dirty.calls.length,0);
});
test('approval uses the same operation as the canvas and marks only the active shot',async()=>{
 const {c,s,calls}=editFixture();s.needs_review=true;await c.approveShot();assert.equal(s.approved,true);assert.equal(s.needs_review,false);assert.equal(calls.length,1);
});
test('media imports require saved unlocked intent before uploading',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../web/production-ui.js'),'utf8');
 for(const options of [{locked:true},{dirty:true}]){
  let uploaded=false;const c=vm.createContext({hasUnsavedCut:()=>false,hasUnsavedShot:()=>!!options.dirty,uploadMedia:async()=>{uploaded=true},productionEdit:()=>{},toast:()=>{}});
  vm.runInContext(source,c);await assert.rejects(c.importShotMedia({id:'s1',locked:!!options.locked},{name:'a.png'},'image'));assert.equal(uploaded,false);
 }
});
test('pending asynchronous buttons ignore duplicate clicks and become available again',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8').match(/^function bind\(id,fn\)[^\n]+/m)[0];
 const el={disabled:false,isConnected:true};let calls=0,finish;const c=vm.createContext({$:()=>el,toast:()=>{}});vm.runInContext(source,c);
 c.bind('#save',()=>{calls++;return new Promise(resolve=>finish=resolve)});const first=el.onclick();await el.onclick();assert.equal(calls,1);assert.equal(el.disabled,true);finish();await first;assert.equal(el.disabled,false);
});
test('pending clip edits are detected and block approval without changing saved data',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../web/production-ui.js'),'utf8');
 const s={id:'s1',selected_takes:{video:'v1'},takes:[{id:'v1',kind:'video'}],clip:{source_take_id:'v1',trim_start:1,trim_end:3}},controls={'#cut-source':{value:'v1'},'#cut-start':{value:'1'},'#cut-end':{value:'3'}};
 const c=vm.createContext({shot:()=>s,$:selector=>controls[selector]});vm.runInContext(source,c);assert.equal(c.hasUnsavedCut(),false);controls['#cut-end'].value='2.5';assert.equal(c.hasUnsavedCut(),true);assert.equal(s.clip.trim_end,3);
 const f=editFixture();f.c.hasUnsavedCut=()=>true;await assert.rejects(f.c.approveShot(),/剪辑/);assert.equal(f.calls.length,0);
});
test('manual imports do not claim model-input freshness, generated takes still do',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../web/production-ui.js'),'utf8'),c=vm.createContext({flowStatus:()=>({shots:[{shot_id:'s1',basis:'new'}]})});vm.runInContext(source,c);
 assert.equal(c.candidateOutdated({id:'s1'},{source:'import',basis:'old'}),false);assert.equal(c.candidateOutdated({id:'s1'},{source:'dify',basis:'old'}),true);
});
test('failed line audio changes restore the previously saved controls',async()=>{
 const audio={dataset:{lineAudio:'l1'},value:'new'},start={dataset:{lineStart:'l1'},value:'10'},messages=[];
 const c=vm.createContext({document:{querySelectorAll:selector=>selector==='[data-line-audio]'?[audio]:selector==='[data-line-start]'?[start]:[],querySelector:selector=>selector.startsWith('[data-line-audio')?audio:start},hasUnsavedShot:()=>false,hasUnsavedCut:()=>false,productionEdit:async()=>{throw Error('超出镜头')},toast:t=>messages.push(t)});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/character-ui.js'),'utf8'),c);c.bindLineAudio({id:'s1',lines:[{id:'l1',audio_take_id:'old',audio_start:0}]});await audio.onchange();assert.equal(audio.value,'old');assert.equal(start.value,0);assert.deepEqual(messages,['超出镜头']);
});
test('reference choice buttons restore and toggle the draft-backed selection',()=>{
 const option={value:'role',selected:true},button={dataset:{toggleReference:'role'},attrs:{},setAttribute(k,v){this.attrs[k]=v}};
 let drafted=0,updated=0;
 const c=vm.createContext({$:()=>({options:[option]}),document:{querySelectorAll:()=>[button]},rememberDraft:()=>drafted++,updateShotSaveState:()=>updated++});
 vm.runInContext(editor,c);c.updateShotSaveState=()=>updated++;c.bindReferenceChoices();assert.equal(button.attrs['aria-pressed'],'true');
 button.onclick();assert.equal(option.selected,false);assert.equal(button.attrs['aria-pressed'],'false');assert.equal(drafted,1);assert.equal(updated,1);
 button.onclick();assert.equal(option.selected,true);
});
test('a delayed production response updates its original project after navigation',async()=>{
 let finish;
 const c=vm.createContext({pid:'p1',state:{projects:[{id:'p1',revision:1},{id:'p2',revision:1}]},draftKey:()=> 'draft:p1',p:()=>({revision:1}),api:()=>new Promise(resolve=>finish=resolve),refresh:async()=>{},render:()=>{}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/production-ui.js'),'utf8'),c);
 const pending=c.productionEdit({action:'set_clip'});c.pid='p2';finish({id:'p1',revision:2});await pending;
 assert.equal(c.state.projects[0].id,'p1');assert.equal(c.state.projects[0].revision,2);assert.equal(c.state.projects[1].id,'p2');assert.equal(c.state.projects[1].revision,1);
});
