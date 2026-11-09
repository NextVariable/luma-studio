const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/workspace-ui.js'),'utf8');
function fixture(items,readiness){
 const content={innerHTML:''};
 const c=vm.createContext({pid:'p1',eid:'e1',state:{jobs:[],readiness:{p1:{e1:readiness}}},shots:()=>items,p:()=>({creative_brief:{format:'16:9'}}),$:()=>content,document:{querySelector:()=>null,querySelectorAll:()=>[]},bind(){},uiIcon:()=>'',esc:String});
 vm.runInContext(source,c);c.delivery();return content.innerHTML;
}
test('delivery resumes the first unfinished shot instead of the previously selected shot',()=>{
 const html=fixture([{id:'done',duration:5,description:'开场'},{id:'missing',duration:6,description:'转场'}],{shots:[{shot_id:'done',ready:true},{shot_id:'missing',ready:false,reason:'尚未选用画面'}],ready_count:1,can_export:false});
 assert.match(html,/data-target-shot="missing">处理镜头 2/);
 assert.doesNotMatch(html,/data-target-shot="done">处理镜头/);
});
test('an empty episode offers creation without claiming it is ready to export',()=>{
 const html=fixture([],{shots:[],ready_count:0,can_export:false});
 assert.match(html,/先建立这一集的镜头/);assert.match(html,/>创建镜头<\/button>/);assert.doesNotMatch(html,/准备导出这一集|所有镜头已确认/);
});
test('a rendered file is current only when both render and creative review identities match',()=>{
 const c=vm.createContext({});vm.runInContext(source,c);
 const status={can_export:true,delivery_basis:'same-bytes',review_basis:'new-shot'};
 assert.equal(c.deliveryIsCurrent({delivery_basis:'same-bytes',review_basis:'old-shot'},status),false);
 assert.equal(c.deliveryIsCurrent({delivery_basis:'same-bytes'},status),false);
 assert.equal(c.deliveryIsCurrent({delivery_basis:'same-bytes',review_basis:'new-shot'},status),true);
 assert.equal(c.deliveryIsCurrent({delivery_basis:'same-bytes',review_basis:'new-shot'},{...status,can_export:false}),false);
});
