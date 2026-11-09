const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const workspace=fs.readFileSync(path.join(__dirname,'../web/workspace-ui.js'),'utf8');
const app=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const returnSource=workspace.match(/^function creativeReturnView\(\)[^\n]+/m)[0];
const settingsSource=app.slice(app.indexOf('function settings(){'),app.indexOf("$('#new').onclick="));
function fixture(){
 const content={innerHTML:''},storage=new Map(),grid={},panels=['appearance','budget','connections'].map(name=>({dataset:{settingsPanel:name},hidden:false})),buttons=panels.map(panel=>({dataset:{settingsSection:panel.dataset.settingsPanel},attrs:{},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]}}));
 const c=vm.createContext({settingsSection:'appearance',uiIcon:()=>'',pid:'p1',workspaceOrder:['overview','shots','assets','delivery'],localStorage:{getItem:k=>storage.get(k)},$:s=>s==='#content'?content:{},p:()=>({id:'p1'}),state:{dify:{}},kinds:{},esc:s=>s,budgetPanel:()=>'',bindBudget:()=>{},bind:()=>{},document:{querySelector:()=>grid,querySelectorAll:s=>s==='[data-settings-panel]'?panels:s==='[data-settings-section]'?buttons:[]}});
 vm.runInContext(returnSource+'\n'+settingsSource,c);
 return {c,storage,content,panels,buttons,grid};
}
test('settings returns to the current work creative page, including assets and delivery',()=>{
 const {c,storage,content}=fixture();
 for(const page of ['overview','shots','assets','delivery']){
  storage.set('luma-workspace:p1',page);c.settings();
  assert.match(content.innerHTML,new RegExp('data-flow="'+page+'">返回创作'));
  assert.ok(!content.innerHTML.includes('${creativeReturnView()}'));
 }
});
test('return location is project scoped and invalid locations fall back to the shot workspace',()=>{
 const {c,storage}=fixture();storage.set('luma-workspace:p1','assets');storage.set('luma-workspace:p2','delivery');
 assert.equal(c.creativeReturnView(),'assets');c.pid='p2';assert.equal(c.creativeReturnView(),'delivery');
 storage.set('luma-workspace:p2','settings');assert.equal(c.creativeReturnView(),'shots');
});

test('settings categories expose one panel and retain the selected section across redraws',()=>{
 const {c,panels,buttons,grid}=fixture();c.settings();
 assert.deepEqual(panels.map(p=>p.hidden),[false,true,true]);
 buttons[2].onclick();assert.deepEqual(panels.map(p=>p.hidden),[true,true,false]);assert.equal(grid.hidden,true);
 c.settings();assert.deepEqual(panels.map(p=>p.hidden),[true,true,false]);
 buttons[1].onclick();assert.deepEqual(panels.map(p=>p.hidden),[true,false,true]);assert.equal(grid.hidden,false);
});
