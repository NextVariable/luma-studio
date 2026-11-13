const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function run(context, name) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'web', 'js', name), 'utf8'), context);
}

test('one wheel gesture switches once and allows a quick reversal', () => {
  const context = vm.createContext({});
  run(context, 'gesture.js');
  const wheel = context.L.wheelGesture();
  assert.equal(wheel(2, 0), 0);
  assert.equal(wheel(3, 12), 1);
  assert.equal(wheel(15, 30), 0);
  assert.equal(wheel(4, 55), 0);
  assert.equal(wheel(1, 70), 0);
  assert.equal(wheel(16, 84), 1);
  assert.equal(wheel(-6, 96), -1);
  assert.equal(wheel(7, 110), 1);
  assert.equal(wheel(9, 260), 1);
  assert.equal(context.L.wheelPixels({deltaMode: 1, deltaY: 3}), 48);
});

test('scrolling to an edge consumes the same gesture, even if it has momentum', () => {
  const context = vm.createContext({});
  run(context, 'gesture.js');
  const wheel = context.L.wheelGesture();
  assert.equal(wheel(150, 0, {scrolling: true}), 0);
  assert.equal(wheel(150, 25), 0);
  assert.equal(wheel(120, 180), 1);
  assert.equal(context.L.swipeDirection({clientX: 0, clientY: 100}, {clientX: 150, clientY: 40}, 44), 0);
  assert.equal(context.L.swipeDirection({clientX: 0, clientY: 100}, {clientX: 5, clientY: 40}, 44), 1);
});

test('completion while editing updates the job then refreshes readiness when the editor is idle', async () => {
  const old = {projects: [{id: 'p', revision: 1}], jobs: [{id: 'j', state: 'running', updated: 1}], spending: {}};
  const fresh = {projects: [{id: 'p', revision: 2}], jobs: [{id: 'j', state: 'succeeded', updated: 2}], spending: {}};
  let poll;
  const element = {setAttribute() {}, addEventListener() {}};
  const ctx = vm.createContext({
    document: {createElement: () => element, body: {appendChild() {}}, addEventListener() {}, hidden: false},
    setInterval: callback => { poll = callback; },
    L: {$: s => ['.menu', 'dialog[open]'].includes(s) ? null : element, $$: () => [], S: {data: old, dirty: true, drawer: false},
      refresh: async () => {}, api: async () => fresh, jobActive: state => state === 'running', jobName: () => '导出', done() {}},
  });
  run(ctx, 'gesture.js');
  run(ctx, 'app.js');
  let renders = 0;
  ctx.L.render = () => { renders += 1; };
  ctx.L.renderTop = ctx.L.renderDrawer = () => {};
  await new Promise(resolve => setImmediate(resolve));
  renders = 0;
  await poll();
  assert.equal(ctx.L.S.data.jobs[0].state, 'succeeded');
  assert.equal(ctx.L.S.data.projects[0].revision, 1);
  assert.equal(renders, 0);
  ctx.L.S.dirty = false;
  await poll();
  assert.equal(ctx.L.S.data.projects[0].revision, 2);
  assert.equal(renders, 1);
});

test('buttons and gesture steps share bounded navigation and an open dialog freezes the index', async () => {
  const handlers = {};
  const view = {scrollTop: 0, addEventListener: (type, listener) => { handlers[type] = listener; }, focus() {}};
  const state = {view: 'cast', pid: 'p', eid: 'e', sid: 'a'};
  const history = [];
  let dialog = false, now = 0;
  const ctx = vm.createContext({
    document: {addEventListener() {}}, setInterval() {}, performance: {now: () => now},
    L: {$: () => view, S: state, project: () => ({}), shots: () => [{id:'a'}, {id:'b'}],
      pagingBlocked: () => dialog, remember() {}, canScrollWithin: () => false, sfx() {},
      swap: (_, direction, change) => { history.push(direction); change(); },
      showShot: (id, direction) => { history.push(direction); state.sid = id; },
      refresh: () => new Promise(() => {})},
  });
  run(ctx, 'gesture.js');
  run(ctx, 'app.js');
  ctx.L.render = () => {};
  function wheel(deltaY, at, extra = {}) {
    now = at;
    let cancelled = false;
    handlers.wheel({deltaY, deltaX: 0, deltaMode: 0, target: {closest: () => null}, preventDefault: () => { cancelled = true; }, ...extra});
    return cancelled;
  }
  assert.equal(wheel(5, 0), true);
  assert.equal(state.view, 'shots');
  wheel(80, 10);
  assert.equal(state.view, 'shots');
  wheel(-5, 20);
  assert.equal(state.view, 'cast');
  assert.deepEqual(history, [1, -1]);
  await ctx.L.go('shots');
  await ctx.L.goTo(1, {scope:'shot'});
  assert.equal(state.sid, 'b');
  assert.equal(await ctx.L.goTo(2, {scope:'shot'}), false);
  dialog = true;
  assert.equal(wheel(-8, 200), false);
  assert.equal(await ctx.L.goTo(2), false);
  assert.equal(state.view, 'shots');
  assert.equal(state.sid, 'b');
  dialog = false;
  assert.equal(wheel(-10, 220, {ctrlKey:true}), false);
  assert.equal(wheel(-10, 230, {deltaX:40}), false);
});

test('touch paging starts at 12 pixels, once per touch, while scrollable content keeps control', () => {
  const handlers = {};
  const view = {scrollTop: 0, addEventListener: (type, listener) => { handlers[type] = listener; }, focus() {}};
  const stage = {};
  const state = {view: 'script', pid: 'p', eid: 'e', sid: 'one'};
  let canScroll = false;
  const ctx = vm.createContext({
    document: {addEventListener() {}}, setInterval() {},
    L: {$: () => view, S: state, project: () => ({}), pagingBlocked: () => false,
      shots: () => [{id:'one'}, {id:'two'}], showShot: id => { state.sid = id; }, remember() {}, sfx() {},
      swap: (_, __, change) => change(), refresh: () => new Promise(() => {})},
  });
  run(ctx, 'gesture.js');
  run(ctx, 'app.js');
  ctx.L.render = () => {};
  ctx.L.canScrollWithin = (_, __, boundary) => boundary===view && canScroll;

  const event = (y, kind='content') => ({
    touches:[{clientX:10,clientY:y}],
    target:{closest:selector => kind==='stage'&&selector==='#stage'?stage:kind==='card'&&selector.includes('button')?{}:null},
    cancelable:true, preventDefault() {},
  });
  handlers.touchstart(event(100));
  handlers.touchmove(event(89));
  assert.equal(state.view, 'script');
  handlers.touchmove(event(88));
  assert.equal(state.view, 'cast');
  handlers.touchmove(event(48));
  assert.equal(state.view, 'cast');
  handlers.touchend(event(48));
  canScroll = true;
  handlers.touchstart(event(100,'card'));
  handlers.touchmove(event(80,'card'));
  canScroll = false;
  handlers.touchmove(event(35));
  assert.equal(state.view, 'cast');
  handlers.touchend(event(35));
  handlers.touchstart(event(100,'card'));
  handlers.touchmove(event(88,'card'));
  assert.equal(state.view, 'shots');
  handlers.touchend(event(88));
  canScroll = true;
  handlers.touchstart(event(100,'stage'));
  handlers.touchmove(event(88,'stage'));
  assert.equal(state.view, 'shots');
  assert.equal(state.sid, 'two');
});

test('mobile swipes horizontally, preserves vertical scrolling and leaves the filmstrip alone', () => {
  const handlers = {};
  const view = {addEventListener: (type, listener) => { handlers[type] = listener; }, focus() {}};
  const state = {view: 'script', sid: 'one'};
  const stage = {};
  let dialog = false, now = 0;
  const keys = {};
  const moves = [];
  const ctx = vm.createContext({
    document: {addEventListener(type, handler) { keys[type] = handler; }},
    setInterval() {}, matchMedia: () => ({matches:true}), performance:{now:()=>now},
    L: {$: () => view, S: state, project: () => ({}), pagingBlocked: () => dialog,
      shots: () => [{id:'one'}, {id:'two'}], showShot: (id, direction, axis) => { state.sid = id; moves.push([direction,axis]); },
      remember() {}, sfx() {}, swap: (_, direction, change, {axis}) => { moves.push([direction,axis]); change(); },
      refresh: () => new Promise(() => {})},
  });
  run(ctx, 'gesture.js');
  run(ctx, 'app.js');
  ctx.L.render = () => {};
  ctx.L.canScrollWithin = () => true;
  function event(type, x, y, zone, count=1) {
    let cancelled = false;
    handlers[type]({
      touches: Array.from({length:count}, () => ({clientX:x,clientY:y})),
      target: {closest: selector => zone==='stage'&&selector==='#stage'?stage:zone==='strip'&&selector.includes('.strip')?{}:null},
      cancelable:true, preventDefault() { cancelled = true; },
    });
    return cancelled;
  }
  event('touchstart',100,100);
  assert.equal(event('touchmove',98,80), false);
  assert.equal(event('touchmove',30,75), false);
  assert.equal(state.view, 'script');
  event('touchend',30,75);
  event('touchstart',100,100);
  event('touchmove',89,100);
  assert.equal(state.view, 'script');
  assert.equal(event('touchmove',88,100), true);
  event('touchmove',30,100);
  assert.equal(state.view, 'cast');
  event('touchend',30,100);
  event('touchstart',100,100);
  event('touchmove',112,100);
  assert.equal(state.view, 'script');
  event('touchend',112,100);
  state.view = 'shots';
  event('touchstart',100,100,'stage');
  event('touchmove',88,100,'stage');
  assert.equal(state.sid, 'two');
  event('touchend',88,100);
  event('touchstart',100,100,'strip');
  assert.equal(event('touchmove',60,100,'strip'), false);
  event('touchstart',100,100);
  assert.equal(event('touchmove',70,100,undefined,2), false);
  dialog = true;
  event('touchstart',100,100);
  assert.equal(event('touchmove',70,100), false);
  assert.equal(state.view, 'shots');
  assert.deepEqual(moves, [[1,'x'],[-1,'x'],[1,'x']]);
  dialog = false;
  state.view = 'script';
  function wheel(dx,dy,strip=false){
    let cancelled = false;
    handlers.wheel({deltaX:dx,deltaY:dy,deltaMode:0,currentTarget:view,
      target:{closest:selector=>strip&&selector.includes('.strip')?{}:null},
      preventDefault(){cancelled=true}});
    return cancelled;
  }
  assert.equal(wheel(0,90), false);
  assert.equal(state.view, 'script');
  assert.equal(wheel(90,0,true), false);
  now = 200;
  assert.equal(wheel(90,0), true);
  assert.equal(state.view, 'cast');
  function key(value){
    let cancelled=false;
    keys.keydown({key:value,target:{closest:()=>null},preventDefault(){cancelled=true}});
    return cancelled;
  }
  assert.equal(key('ArrowDown'),false);
  assert.equal(key('ArrowLeft'),true);
  assert.equal(state.view,'script');
});

test('page animation uses fixed offsets, cancels on reversal, and skips reduced motion', () => {
  const animations = [];
  function element() {
    return {
      children: [], style: {}, tagName: 'div', className: 'view', scrollTop: 0,
      getBoundingClientRect: () => ({left:0, top:0, width:300, height:400}),
      setAttribute() {}, querySelectorAll: () => [],
      cloneNode: () => element(),
      appendChild(child) { this.children.push(child); child.parent = this; },
      remove() { if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this); },
      animate(frames, options) {
        const animation = {frames, options, cancelled:false, finished:new Promise(() => {}), cancel() { this.cancelled=true; }};
        animations.push(animation);
        return animation;
      },
    };
  }
  let reduced = false;
  const body = element();
  const ctx = vm.createContext({
    document: {createElement: element, body, addEventListener() {}},
    localStorage: {getItem: () => null},
    matchMedia: () => ({matches:reduced}),
  });
  ctx.window=ctx;
  run(ctx,'core.js');
  const view = element();
  view.appendChild(element());
  const render = () => { view.children=[element()]; };
  ctx.L.swap(view,1,render);
  assert.deepEqual(animations.map(a=>a.options.duration),[290,260,290,260]);
  assert.equal(animations[0].frames[1].translate,'0 -20px');
  assert.equal(animations[2].frames[0].translate,'0 20px');
  assert.equal(animations[0].options.easing,'cubic-bezier(.2,.75,.25,1)');
  ctx.L.swap(view,-1,render);
  assert.ok(animations.slice(0,4).every(animation=>animation.cancelled));
  assert.equal(body.children.length,1);
  assert.equal(animations[4].frames[1].translate,'0 20px');
  reduced=true;
  ctx.L.swap(view,1,render);
  assert.ok(animations.every(animation=>animation.cancelled));
  assert.equal(body.children.length,0);
  assert.equal(animations.length,8);
  reduced=false;
  ctx.L.swap(view,1,render,{axis:'x'});
  assert.equal(animations[8].frames[1].translate,'-20px 0');
  assert.equal(animations[10].frames[0].translate,'20px 0');
});

test('equal pixel-mode mouse detents are independent, but equal decayed samples are not', () => {
  const context = vm.createContext({});
  run(context, 'gesture.js');
  const mouse = context.L.wheelGesture();
  assert.equal(mouse(10.61, 0), 1);
  assert.equal(mouse(10.61, 50), 1);
  assert.equal(mouse(10.61, 100), 1);
  const momentum = context.L.wheelGesture();
  assert.equal(momentum(14, 0), 1);
  assert.equal(momentum(14, 12), 0);
  assert.equal(momentum(6, 24), 0);
  assert.equal(momentum(6, 74), 0);
  assert.equal(momentum(6, 124), 0);
  assert.equal(momentum(1, 137), 0);
  assert.equal(momentum(9, 149), 1);
});

test('moving the mouse from a scrolling list to the header accepts the next light wheel', () => {
  const context = vm.createContext({});
  run(context, 'gesture.js');
  const wheel = context.L.wheelGesture();
  assert.equal(wheel(240, 0, {scrolling:true, pointer:{x:300,y:440}}), 0);
  assert.equal(wheel(12, 35, {pointer:{x:300,y:440}}), 0);
  assert.equal(wheel(8, 70, {pointer:{x:300,y:140}}), 1);
});

test('a trusted interaction unlocks swipe audio, and reversal replaces the previous sound', async () => {
  const listeners = {};
  const starts = [];
  const stops = [];
  const activation = {isActive:false,hasBeenActive:false};
  const hints = [];
  let audio;
  const parameter = () => ({
    setValueAtTime() {}, exponentialRampToValueAtTime() {}, cancelScheduledValues() {}, setTargetAtTime() {},
  });
  const node = () => ({connect(next) { return next; }});
  class Audio {
    state='suspended';
    sampleRate=1000;
    currentTime=1;
    destination=node();
    constructor(){audio=this}
    resume(){ this.state='running'; return Promise.resolve(); }
    createBuffer(_, size){ return {getChannelData:()=>new Float32Array(size)}; }
    createBufferSource(){
      return {...node(), start:time=>starts.push(time), stop:time=>stops.push(time)};
    }
    createBiquadFilter(){ return {...node(), Q:{}, frequency:parameter()}; }
    createGain(){ return {...node(), gain:parameter()}; }
  }
  const ctx=vm.createContext({
    document:{addEventListener(type,fn){(listeners[type]??=[]).push(fn);}},
    localStorage:{getItem:()=>null},
    AudioContext:Audio,
    navigator:{userActivation:activation},
  });
  ctx.window=ctx;
  run(ctx,'core.js');
  ctx.L.toast=message=>hints.push(message);
  ctx.L.sfx('swipe',1);
  ctx.L.sfx('swipe',-1);
  assert.equal(starts.length,0);
  assert.equal(hints.length,1);
  activation.isActive=true;
  activation.hasBeenActive=true;
  listeners.pointerdown[0]({isTrusted:true});
  activation.isActive=false;
  ctx.L.sfx('swipe',1);
  ctx.L.sfx('swipe',-1);
  assert.deepEqual(starts,[1,1]);
  assert.deepEqual(stops,[1.03]);
  audio.state='suspended';
  ctx.L.sfx('swipe',1);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(starts.length,3);
  ctx.L.sound.on=false;
  ctx.L.sfx('swipe',1);
  assert.equal(starts.length,3);
});
