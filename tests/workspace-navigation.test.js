const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/navigation-ui.js'),'utf8');
function fixture(view='shots'){
 const navigation=[],cue={textContent:''};const c=vm.createContext({view,$:()=>cue,go:next=>{navigation.push(next);c.view=next}});vm.runInContext(source,c);return {c,navigation,cue,send:(delta,time,other={})=>c.edgeGesture({delta,time,excluded:false,canScroll:false,...other})};
}
test('direct wheel input changes page without requiring a pause or a second gesture',()=>{
 const {send,navigation}=fixture();assert.equal(send(24,1000),true);assert.deepEqual(navigation,['assets']);
 assert.equal(send(100,1050),false);assert.equal(send(24,1550),true);assert.deepEqual(navigation,['assets','delivery']);
});
test('small trackpad deltas accumulate promptly and separated tiny noise does not switch',()=>{
 const {send,navigation}=fixture();send(8,1000);send(8,1010);assert.equal(send(8,1020),true);
 const tiny=fixture();tiny.send(3,1000);tiny.send(3,1400);assert.deepEqual(tiny.navigation,[]);
});
test('ordinary scrolling and active editing keep their native behavior',()=>{
 for(const reason of [{canScroll:true},{excluded:true}]){const {send,navigation}=fixture();send(120,1000,reason);send(120,1400,reason);assert.deepEqual(navigation,[])}
});
test('wheel momentum during a transition is consumed without scrolling or skipping the incoming page',()=>{
 const {c,navigation}=fixture('delivery');vm.runInContext('workspaceMotionUntil=1480',c);
 assert.equal(c.consumeWorkspaceWheel({delta:120,time:1100,excluded:false,canScroll:true}),true);
 assert.equal(c.consumeWorkspaceWheel({delta:-120,time:1200,excluded:false,canScroll:false}),true);
 assert.deepEqual(navigation,[]);
 assert.equal(c.consumeWorkspaceWheel({delta:120,time:1500,excluded:false,canScroll:true}),false);
 assert.equal(c.consumeWorkspaceWheel({delta:120,time:1200,excluded:true,canScroll:true}),false);
});
test('reaching the edge can continue directly into the next page in the same gesture',()=>{
 const {send,navigation}=fixture();send(80,1000,{canScroll:true});assert.equal(send(24,1020),true);assert.deepEqual(navigation,['assets']);
});
test('a long momentum tail cannot skip a second page after the shorter animation',()=>{
 const {c,navigation}=fixture();const input=time=>({delta:30,time,excluded:false,canScroll:false});
 assert.equal(c.consumeWorkspaceWheel(input(1000)),true);
 for(let time=1020;time<=1500;time+=20)assert.equal(c.consumeWorkspaceWheel(input(time)),true);
 assert.deepEqual(navigation,['assets']);
 assert.equal(c.consumeWorkspaceWheel(input(1620)),true);assert.deepEqual(navigation,['assets','delivery']);
});
test('inline editor is not treated as a modal; focused fields and real overlays are protected',()=>{
 let overlay=null;const field={};const c=vm.createContext({document:{querySelector:()=>overlay,activeElement:field}});vm.runInContext(source,c);
 const plain={closest:()=>null};assert.equal(c.gestureExcluded(plain),false);
 const editor={closest:s=>s==='input,textarea,[contenteditable]'?field:null};assert.equal(c.gestureExcluded(editor),true);
 c.document.activeElement=null;assert.equal(c.gestureExcluded(editor),false);
 overlay={};assert.equal(c.gestureExcluded(plain),true);
});
test('direction changes reset partial input and boundary pages never wrap',()=>{
 const {send,navigation}=fixture();send(12,1000);send(-12,1010);assert.deepEqual(navigation,[]);send(-12,1020);assert.deepEqual(navigation,['overview']);send(-120,2000);assert.deepEqual(navigation,['overview']);
 const end=fixture('delivery');end.send(120,1000);assert.deepEqual(end.navigation,[]);
});
test('touch navigation only begins from a page edge, never from an ordinary scroll or horizontal swipe',()=>{
 const {c}=fixture();const start={x:100,y:500,atBottom:true,atTop:false},up={clientX:110,clientY:300};
 assert.equal(c.touchDestination(start,up,{time:1000}),'assets');
 assert.equal(c.touchDestination({...start,atBottom:false},up,{time:1000}),null);
 assert.equal(c.touchDestination(start,{clientX:400,clientY:300},{time:1000}),null);
 assert.equal(c.touchDestination(start,up,{time:1000,excluded:true}),null);
 assert.equal(c.touchDestination(start,up,{time:1000,canScroll:true}),null);
});
test('form submissions stay pending until completion and ignore repeated activation',async()=>{
 let calls=0,finish,prevented=0;
 const button={type:'submit',disabled:false,isConnected:true},attrs={};
 const form={onsubmit:async e=>{e.preventDefault();calls++;await new Promise(resolve=>finish=resolve)},getAttribute:()=>null,querySelectorAll:()=>[button],setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k]};
 const c=vm.createContext({document:{querySelectorAll:()=>[form]}});vm.runInContext(source,c);c.enhanceForms();
 const event={preventDefault(){prevented++}},first=form.onsubmit(event);await form.onsubmit(event);
 assert.equal(calls,1);assert.equal(prevented,2);assert.equal(button.disabled,true);assert.equal(attrs['aria-busy'],'true');finish();await first;
 assert.equal(button.disabled,false);assert.equal(attrs['aria-busy'],undefined);
});

test('opening a work resumes its saved creative page with a valid fallback',()=>{
 for(const [saved,expected] of [['overview','overview'],['assets','assets'],['delivery','delivery'],['settings','shots'],[null,'shots']]){
  const c=vm.createContext({view:'library',pid:'old',eid:'e1',selected:'s1',p:()=>({shots:[{}]}),window:{scrollY:0},performance:{now:()=>100},localStorage:{getItem:()=>saved},render(){},transitionWorkspace(){}});
  vm.runInContext(source,c);c.transitionWorkspace=()=>{};c.rememberWorkspaceScroll=()=>{};c.enterProject('next');assert.equal(c.view,expected);assert.equal(c.pid,'next');assert.equal(c.selected,null);
 }
});
test('creative navigation restores pane positions while keeping the outer page fixed',()=>{
 const areas={'#content':{scrollTop:90},'.script-sheet':{scrollTop:160},'.story-outline':{open:true}},outer=[];
 for(const area of Object.values(areas))area.scrollTo=({top})=>area.scrollTop=top;
 const c=vm.createContext({view:'overview',pid:'p1',eid:'e1',window:{scrollY:200,scrollTo:options=>outer.push(options.top)},matchMedia:()=>({matches:true}),document:{querySelector:s=>areas[s],querySelectorAll:()=>[]},$:s=>areas[s]});
 vm.runInContext(source,c);c.rememberWorkspaceScroll();areas['#content'].scrollTop=0;areas['.script-sheet'].scrollTop=0;areas['.story-outline'].open=false;c.transitionWorkspace('shots','overview');
 assert.equal(areas['#content'].scrollTop,90);assert.equal(areas['.script-sheet'].scrollTop,160);assert.equal(areas['.story-outline'].open,true);assert.deepEqual(outer,[0]);
 c.pid='p2';areas['#content'].scrollTop=0;c.transitionWorkspace('shots','overview');assert.equal(areas['#content'].scrollTop,0);
});
test('creative transitions settle promptly without scale or rebound and respect motion preference',()=>{
 const calls=[],content={animate:(frames,options)=>calls.push({frames,options}),getAnimations:()=>[]};
 const c=vm.createContext({view:'shots',performance:{now:()=>1000},document:{documentElement:{dataset:{}},querySelectorAll:()=>[],querySelector:()=>null},$:()=>content,pid:'p1',eid:'e1',window:{scrollTo(){}},matchMedia:()=>({matches:false})});
 vm.runInContext(source,c);c.transitionWorkspace('overview','shots');assert.equal(calls[0].options.duration,300);assert.equal(calls[0].frames.length,2);assert.equal(calls[0].frames[0].transform,'translateY(28px)');assert.equal(calls[0].frames[1].transform,'translateY(0)');assert.equal(c.workspaceMotionActive(1301),false);
 assert.equal(c.workspaceMotionActive(1100),true);c.document.documentElement.dataset.motion='off';c.transitionWorkspace('shots','assets');assert.equal(calls.length,1);assert.equal(c.workspaceMotionActive(1100),false);
});
