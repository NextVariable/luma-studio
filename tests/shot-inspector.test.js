const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/canvas-ui.js'),'utf8');
const presentation=source.slice(source.indexOf('function presentShotTools('),source.indexOf('function openShotTools('));
test('the creation panel stays in flow and never makes the storyboard inert',()=>{
 for(const wide of [true,false]){
  const events=[],panel={open:false,dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v},show(){this.open=true;events.push('show')},showModal(){throw Error('creation must not be modal')}};
  panel.contains=()=>false;panel.querySelector=()=>null;
  const c=vm.createContext({document:{activeElement:null},matchMedia:()=>({matches:wide})});vm.runInContext(presentation,c);c.presentShotTools(panel);
  assert.equal(panel.dataset.docked,'true');assert.equal(panel.attrs['aria-modal'],'false');assert.deepEqual(events,['show']);
  c.presentShotTools(panel);assert.deepEqual(events,['show']);
 }
});
test('opening the inline panel preserves external focus or restores the selected editor tab',()=>{
 const selected={focus(){this.focused=true}},outside={isConnected:true,focus(){this.focused=true}},body={};
 const c=vm.createContext({document:{activeElement:outside,body}});vm.runInContext(presentation,c);
 const panel={open:false,dataset:{},setAttribute(){},contains:()=>false,querySelector:()=>selected,show(){this.open=true}};
 c.presentShotTools(panel);assert.equal(outside.focused,true);assert.equal(selected.focused,undefined);
 panel.open=false;c.document.activeElement=body;c.presentShotTools(panel);assert.equal(selected.focused,true);
});
test('creation popover Escape closes only the overlay and returns focus without scrolling',()=>{
 let handler,hidden=0,prevented=0,stopped=0,options;
 const popup={addEventListener:(name,fn)=>handler=fn,hidePopover:()=>hidden++},trigger={focus:value=>options=value};
 const c=vm.createContext({});vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/creation-ui.js'),'utf8'),c);
 c.bindCreationPopoverEscape(popup,()=>trigger);
 handler({key:'Escape',preventDefault:()=>prevented++,stopPropagation:()=>stopped++});
 assert.equal(hidden,1);assert.equal(prevented,1);assert.equal(stopped,1);assert.equal(options.preventScroll,true);
 handler({key:'ArrowDown'});assert.equal(hidden,1);
 const modal={tagName:'DIALOG',close:()=>hidden++};c.dismissCreationPopover(modal,trigger);assert.equal(hidden,2);assert.equal(options.preventScroll,true);
});
test('opening media tools activates and focuses the existing composer tab',()=>{
 const panel={open:true},tab={click(){this.clicked=true},focus(){this.focused=true}};
 const c=vm.createContext({$:s=>s==='#shot-tools'?panel:tab});
 c.setShotControlsVisible=()=>{};
 vm.runInContext(source.slice(source.indexOf('function openShotTools('),source.indexOf('function setShotControlsVisible(')),c);
 c.openShotTools('takes');assert.equal(tab.clicked,true);assert.equal(tab.focused,true);assert.equal(panel.open,true);
});
test('collapsing the editor preserves its mounted draft and returns focus to the toggle',()=>{
 const changes=[],field={value:'近景，保留对白'},panel={hidden:false,field,contains:el=>el===field},toggle={setAttribute:(k,v)=>changes.push([k,v]),focus(){this.focused=true}},desk={classList:{toggle:(...args)=>changes.push(args)}};
 const c=vm.createContext({$:s=>s==='#shot-tools'?panel:toggle,document:{activeElement:field,querySelector:()=>desk}});
 vm.runInContext(source.slice(source.indexOf('function setShotControlsVisible('),source.indexOf('function drawShots(')),c);
 c.setShotControlsVisible(false);assert.equal(panel.hidden,true);assert.equal(toggle.focused,true);assert.equal(field.value,'近景，保留对白');
 c.setShotControlsVisible(true);assert.equal(panel.hidden,false);assert.equal(panel.field,field);assert.ok(changes.some(([k,v])=>k==='aria-expanded'&&v==='true'));
});
test('reference previews use the shot-bound version even when the asset library has a newer look',()=>{
 const c=vm.createContext({shot:()=>({asset_bindings:{role:'old'}})});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/creation-ui.js'),'utf8'),c);
 const a={id:'role',selected_version:'new',versions:[{id:'old',views:{front:'old.png'}},{id:'new',views:{front:'new.png'}}]};
 assert.equal(c.shotReferenceCover(a),'old.png');
 a.id='new-role';assert.equal(c.shotReferenceCover(a),'new.png');
});
