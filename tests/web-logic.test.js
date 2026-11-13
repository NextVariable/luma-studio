const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '..', 'web');
function load() {
  const ctx = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(web, 'js', 'logic.js'), 'utf8'), ctx);
  return ctx.L;
}
const L = load();

test('clock shows minutes and seconds, keeping tenths only when needed', () => {
  assert.equal(L.clock(0), '0:00');
  assert.equal(L.clock(9), '0:09');
  assert.equal(L.clock(65.5), '1:05.5');
  assert.equal(L.clock(-3), '0:00');
});

test('shot state follows server readiness, with stale pictures called out first', () => {
  const s = { image: 'a.png', approved: true, needs_review: false };
  assert.equal(L.shotState(s, { ready: true }).key, 'ready');
  assert.equal(L.shotState(s, { ready: false, stale_media: true }).key, 'stale');
  assert.equal(L.shotState({ approved: false }, { ready: false }).key, 'missing');
  assert.equal(L.shotState({ image: 'a.png', needs_review: true }, { ready: false }).key, 'review');
  assert.equal(L.shotState({ ...s, locked: true }, { ready: true }).key, 'locked');
  assert.equal(L.shotState(s, { ready: false, reason: '承接镜头需先复核' }).label, '承接镜头需先复核');
});

test('filters group stale and unreviewed shots under 待处理', () => {
  const shots = [{ id: 'a' }, { id: 'b', image: 'x.png', needs_review: true }, { id: 'c', image: 'y.png' }, { id: 'd', image: 'z.png' }];
  const items = [{ shot_id: 'a' }, { shot_id: 'b' }, { shot_id: 'c', ready: true }, { shot_id: 'd', stale_media: true }];
  assert.deepEqual(L.filterShots(shots, items, 'missing').map(s => s.id), ['a']);
  assert.deepEqual(L.filterShots(shots, items, 'review').map(s => s.id), ['b', 'd']);
  assert.deepEqual(L.filterShots(shots, items, 'ready').map(s => s.id), ['c']);
  assert.equal(L.filterShots(shots, items, 'all').length, 4);
});

test('a film is current only when both review and delivery bases match an exportable episode', () => {
  const status = { can_export: true, review_basis: 'r', delivery_basis: 'd' };
  assert.equal(L.deliveryIsCurrent({ review_basis: 'r', delivery_basis: 'd' }, status), true);
  assert.equal(L.deliveryIsCurrent({ review_basis: 'old', delivery_basis: 'd' }, status), false);
  assert.equal(L.deliveryIsCurrent({ review_basis: 'r', delivery_basis: 'old' }, status), false);
  assert.equal(L.deliveryIsCurrent({ review_basis: 'r', delivery_basis: 'd' }, { ...status, can_export: false }), false);
  assert.equal(L.deliveryIsCurrent({}, status), false);
});

test('generated candidates are flagged when made for an older shot setting; imports are judged by the server', () => {
  assert.equal(L.candidateOutdated({ source: 'dify', basis: 'old' }, 'new'), true);
  assert.equal(L.candidateOutdated({ source: 'dify', basis: 'new' }, 'new'), false);
  assert.equal(L.candidateOutdated({ source: 'import', basis: 'old' }, 'new'), false);
});

test('partial generation segments cannot stand in for the whole shot', () => {
  const s = { duration: 4 };
  assert.equal(L.isPartialTake({ generation_segment: { start: 0, end: 2 } }, s), true);
  assert.equal(L.isPartialTake({ generation_segment: { start: 0, end: 4 } }, s), false);
  assert.equal(L.isPartialTake({}, s), false);
});

test('removing the last line keeps line-by-line mode with an empty list', () => {
  const one = [{ id: 'l', speaker_asset_id: null, text: '旧句' }];
  assert.deepEqual(JSON.parse(JSON.stringify(L.removeLine(one, 0))), []);
  assert.equal(L.addLine([], 'hero')[0].speaker_asset_id, 'hero');
  assert.equal(L.linesFromDialogue('  你来了。 ')[0].text, '你来了。');
  assert.equal(L.linesFromDialogue('').length, 1);
});

test('job actions match server rules', () => {
  const p = { applied: ['done'] };
  assert.equal(L.canAdopt({ id: 'x', state: 'succeeded', kind: 'shots' }, p), true);
  assert.equal(L.canAdopt({ id: 'done', state: 'succeeded', kind: 'shots' }, p), false);
  assert.equal(L.canAdopt({ id: 'y', state: 'succeeded', kind: 'export' }, p), false);
  assert.equal(L.canReconcile({ state: 'interrupted', result: '{"run_id":"r"}' }), true);
  assert.equal(L.canReconcile({ state: 'interrupted', result: '{}' }), false);
  assert.equal(L.canCancel({ state: 'waiting_review' }), true);
  assert.equal(L.canCancel({ state: 'succeeded' }), false);
  assert.equal(L.jobBucket({ state: 'failed' }), 'attention');
  assert.equal(L.jobBucket({ state: 'running' }), 'active');
});

test('review forms are supported only with at most one paragraph field', () => {
  assert.equal(L.reviewSupport({ inputs: [] }), true);
  assert.equal(L.reviewSupport({ inputs: [{ type: 'paragraph', output_variable_name: 'notes' }] }), true);
  assert.equal(L.reviewSupport({ inputs: [{ type: 'select', output_variable_name: 'x' }] }), false);
  assert.equal(L.reviewSupport({ inputs: [{ type: 'paragraph', output_variable_name: 'a' }, { type: 'paragraph', output_variable_name: 'b' }] }), false);
});

test('films list only successful exports of the chosen episode', () => {
  const jobs = [
    { project_id: 'p', kind: 'export', state: 'succeeded', episode_id: 'e1', result: '{"file":"a.mp4"}' },
    { project_id: 'p', kind: 'export', state: 'failed', episode_id: 'e1', result: null },
    { project_id: 'p', kind: 'export', state: 'succeeded', episode_id: 'e2', result: '{"file":"b.mp4"}' },
  ];
  assert.deepEqual(L.films(jobs, 'p', 'e1').map(f => f.result.file), ['a.mp4']);
});

test('every script referenced by the page exists and every view is registered', () => {
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script src="([^"]+)"/g)].map(m => m[1]);
  assert.ok(scripts.length >= 10);
  for (const src of scripts) assert.ok(fs.existsSync(path.join(web, src)), src);
  const all = scripts.map(src => fs.readFileSync(path.join(web, src), 'utf8')).join('\n');
  for (const view of ['library', 'script', 'cast', 'shots', 'delivery']) assert.match(all, new RegExp('L\\.views\\.' + view + '='));
});

test('user content is escaped before it reaches innerHTML', () => {
  const ctx = vm.createContext({ window: {}, localStorage: { getItem: () => null }, document: { addEventListener() {} }, matchMedia: () => ({ matches: false }) });
  ctx.window = ctx;
  vm.runInContext(fs.readFileSync(path.join(web, 'js', 'core.js'), 'utf8'), ctx);
  assert.equal(ctx.L.esc('<img src=x onerror="a">&\''), '&lt;img src=x onerror=&quot;a&quot;&gt;&amp;&#39;');
  assert.equal(ctx.L.media('a b.png'), '/media/a%20b.png');
});
