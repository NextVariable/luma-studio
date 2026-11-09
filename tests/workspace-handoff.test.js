const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/workspace-ui.js'),'utf8');
const navigate=source.slice(source.indexOf('function go('),source.indexOf('\nfunction bindFlowLinks'));
function fixture({view='delivery',dirty=false,cut=false,image=null}={}){
 const opened=[],messages=[];
 const c=vm.createContext({view,pid:'p1',eid:'e1',selected:'s1',shotFilter:'all',document:{querySelector:()=>null},workspaceScroll:new Map(),rememberWorkspaceScroll:()=>{},window:{scrollY:0},hasUnsavedShot:()=>dirty,hasUnsavedCut:()=>cut,render:()=>{},transitionWorkspace:()=>{},openShotTools:tab=>opened.push({tab,shot:c.selected}),shot:()=>({image}),toast:text=>messages.push(text)});
 vm.runInContext(navigate,c);return {c,opened,messages};
}
test('a missing-image delivery item opens media tools for its exact shot',()=>{
 const f=fixture();f.c.go('shots','s2');assert.equal(f.c.view,'shots');assert.deepEqual(f.opened,[{tab:'takes',shot:'s2'}]);
});
test('script outline and populated delivery items open shot intent for the target',()=>{
 for(const options of [{view:'overview'},{view:'delivery',image:'chosen.png'}]){
  const f=fixture(options);f.c.go('shots','s4');assert.deepEqual(f.opened,[{tab:'intent',shot:'s4'}]);
 }
});
test('delivery navigation recovers unsaved current intent or cut before changing context',()=>{
 for(const options of [{view:'shots',dirty:true},{view:'shots',cut:true}]){
  const f=fixture(options);f.c.go('delivery');assert.equal(f.c.view,'shots');assert.equal(f.messages.length,1);assert.deepEqual(f.opened,[{tab:options.cut?'takes':'intent',shot:'s1'}]);
 }
});
test('reselecting the current page preserves its live editing surface, explicit shot links still open',()=>{
 const f=fixture({view:'shots'});let renders=0;f.c.render=()=>renders++;
 f.c.go('shots');assert.equal(renders,0);assert.deepEqual(f.opened,[]);
 f.c.go('shots','s2');assert.equal(renders,1);assert.deepEqual(f.opened,[{tab:'intent',shot:'s2'}]);
 const story=fixture({view:'overview'});story.c.render=()=>{throw Error('current script should stay mounted')};story.c.go('script');
});
