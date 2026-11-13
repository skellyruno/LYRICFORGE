/**
 * Browser-logic smoke test for static/autoclip.js (no browser or npm packages needed).
 * Drives Clip Studio, Autopilot and the Shorts cards against a fake DOM and canned API replies.
 */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const html = fs.readFileSync('static/index.html', 'utf8');
const script = fs.readFileSync('static/autoclip.js', 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
assert.equal(new Set(ids).size, ids.length, 'duplicate IDs in index.html');
for (const needed of ['autoRunBtn', 'autopilotFromReview', 'openClipStudio', 'clipStudio', 'clipCards', 'autoShortList'])
  assert.ok(ids.includes(needed), 'missing #' + needed);

function makeNode(tag = 'div') {
  const classes = new Set(); const listeners = {};
  const node = {
    tagName: tag.toUpperCase(), children: [], attrs: {}, style: {}, _text: '', value: '', checked: false, disabled: false, files: [],
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c),
      toggle: (c, on = !classes.has(c)) => { on ? classes.add(c) : classes.delete(c); return on; } },
    addEventListener(t, fn) { (listeners[t] ??= []).push(fn); }, removeEventListener() {},
    setAttribute(k, v) { node.attrs[k] = v; if (k === 'value') node.value = v; if (k === 'checked') node.checked = true; },
    append(...kids) { for (const k of kids) node.children.push(typeof k === 'string' ? { _text: k, children: [] } : k); },
    replaceChildren(...kids) { node.children = []; node.append(...kids); },
    click() { for (const fn of listeners.click ?? []) fn({ target: node }); },
    fire(type, extra = {}) { for (const fn of listeners[type] ?? []) fn({ target: node, ...extra }); },
    scrollIntoView() {},
    get textContent() { return node._text + node.children.map((c) => c.textContent ?? c._text ?? '').join(''); },
    set textContent(v) { node._text = String(v); node.children = []; },
    get className() { return [...classes].join(' '); }, set className(v) { String(v).split(' ').forEach((c) => c && classes.add(c)); },
  };
  return node;
}
const byId = new Map(ids.map((id) => [id, makeNode()]));
const all = (n, out = []) => { out.push(n); (n.children || []).forEach((c) => all(c, out)); return out; };
const find = (root, pred) => all(root).filter(pred);

// ---- canned server -----------------------------------------------------------------
const calls = [];
const clip = (n) => ({ id: 'c' + n, start: n * 40, end: n * 40 + 30, score: 0.9 - n / 10, hook: 'Hook ' + n,
  title: n === 0 ? '<img src=x onerror=alert(1)>' : 'Title ' + n, description: 'Desc ' + n, tags: ['mixing', 'tips'], reasons: ['opens with a question'] });
let projectPolls = 0;
async function fakeFetch(path, options = {}) {
  const body = options.body && typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
  calls.push({ path, method: options.method || 'GET', body });
  const ok = (data) => ({ ok: true, status: 200, json: async () => data });
  if (path === '/api/clips/capabilities') return ok({ ai_rerank: false, max_source_mb: 2048, max_source_minutes: 180 });
  if (path === '/api/clip-sources') return ok({ id: 'b'.repeat(32), status: 'transcribing' });
  if (path === '/api/projects/' + 'b'.repeat(32)) {
    projectPolls++;
    return ok(projectPolls < 2 ? { status: 'transcribing', transcription_progress: 40, title: 'Demo' }
      : { status: 'ready', title: 'Demo', clip_suggestions: [clip(0), clip(1), clip(2), clip(3)] });
  }
  if (path.endsWith('/clips/render')) return ok({ job_id: 'job1' });
  if (path.endsWith('/autopilot')) return ok({ job_id: 'job2' });
  if (path.endsWith('/shorts/suggestions')) return ok({ suggestions: [{ start: 5, end: 25, score: 0.7, reasons: ['likely chorus'], hook: 'Chorus line' }] });
  if (path.endsWith('/shorts/render')) return ok({ job_id: 'job3' });
  if (path === '/api/jobs/job1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { clips: [
    { n: 1, start: 0, end: 30, title: 'Rendered', description: 'd', tags: ['a b'], url: '/api/projects/x/clips/1' }] } });
  if (path === '/api/jobs/job2') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { full: '/api/projects/' + 'a'.repeat(32) + '/export',
    auto_confirmed: true, shorts: [{ n: 1, start: 1, end: 20, title: 'S1', description: 'd', tags: [], url: '/api/projects/x/shorts/1' }] } });
  if (path === '/api/jobs/job3') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { shorts: [{ n: 1, start: 5, end: 25, title: 'S', description: '', tags: [], url: '/u' }] } });
  return { ok: false, status: 404, json: async () => ({ detail: 'unexpected ' + path }) };
}
const toasts = []; let reloaded = null; const panels = [];
const editorState = { id: 'a'.repeat(32), lines: [{ id: 'l1', text: 'hi there', start: 1, end: 3, words: [] }], settings: { font: 'Arial' } };
const bridge = { state: () => editorState, toast: (m, e) => toasts.push([m, e]), panel: (n) => panels.push(n),
  audio: () => null, reloadProject: async (id) => { reloaded = id; } };
const keyListeners = [];
const context = {
  window: {}, console, URL, FormData: class { constructor() { this.d = []; } append(k, v) { this.d.push([k, v]); } },
  setTimeout: (fn) => { fn(); return 0; }, clearTimeout() {},
  navigator: { clipboard: { writeText: async () => {} } }, fetch: fakeFetch,
  document: { getElementById: (id) => byId.get(id) ?? null, createElement: makeNode, addEventListener: (t, fn) => keyListeners.push([t, fn]) },
};
context.window = context;
context.window.SkellyBridge = bridge;
vm.runInNewContext(script, context, { filename: 'static/autoclip.js' });
const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };

// ---- Clip Studio: open, upload, wait, pick, render --------------------------------------
byId.get('openClipStudio').click(); await settle();
assert.ok(!byId.get('clipStudio').classList.contains('hidden'), 'studio opens');
assert.ok(!byId.get('clipUploadStep').classList.contains('hidden'), 'upload step visible');
assert.ok(byId.get('clipUseAi').disabled, 'AI ranking disabled without a server key');
assert.match(byId.get('clipLimitNote').textContent, /2048 MB/);

byId.get('clipFile').fire('change', { target: { files: [{ name: 'talk.mp4' }], value: '' } }); await settle();
assert.ok(calls.some((c) => c.path === '/api/clip-sources' && c.method === 'POST'), 'uploaded');
assert.ok(!byId.get('clipReadyStep').classList.contains('hidden'), 'reached ready step');
const cards = byId.get('clipCards').children;
assert.equal(cards.length, 4, 'one card per suggestion');
const titles = find(byId.get('clipCards'), (n) => n.attrs?.['aria-label'] === 'Title').map((n) => n.value);
assert.equal(titles[0], '<img src=x onerror=alert(1)>', 'titles are plain text values, never HTML');
assert.equal(find(byId.get('clipCards'), (n) => n.tagName === 'IMG').length, 0, 'no injected <img> element');
assert.equal(byId.get('clipRender').textContent, 'Render selected (3)', 'top three preselected');

byId.get('clipReframe').value = 'follow';
byId.get('clipRender').click(); await settle();
const render = calls.find((c) => c.path.endsWith('/clips/render'));
assert.equal(render.body.reframe, 'follow');
assert.equal(render.body.clips.length, 3);
assert.equal(render.body.clips[0].tags.join(','), 'mixing,tips');
assert.ok(find(byId.get('clipResults'), (n) => n.attrs?.href?.endsWith('/bundle.zip')).length === 1, 'zip link shown');
assert.match(byId.get('clipStatus').textContent, /1 clip\(s\) rendered/);

// ---- Autopilot from the editor ------------------------------------------------------
byId.get('autoPreset').value = 'bold'; byId.get('autoAspect').value = 'landscape'; byId.get('autoShortCount').value = '2';
byId.get('autoHooks').checked = true;
byId.get('autoRunBtn').click(); await settle();
const auto = calls.find((c) => c.path.endsWith('/autopilot'));
assert.deepEqual({ ...auto.body, lines: undefined }, { preset: 'bold', aspect: 'landscape', shorts: 2, hooks: true, lines: undefined });
assert.equal(auto.body.lines.length, 1, 'editor lines are sent so unsaved edits are used');
assert.equal(reloaded, 'a'.repeat(32), 'editor reloads the finished project');
assert.match(byId.get('autoStatus').textContent, /skim them in the editor/, 'auto-confirmed lyrics are flagged');
assert.ok(!byId.get('autoRunBtn').disabled, 'buttons re-enabled afterwards');

// ---- Shorts suggestions and render -----------------------------------------------------
byId.get('autoFindShorts').click(); await settle();
assert.equal(byId.get('autoShortList').children.length, 1);
byId.get('autoRenderShorts').click(); await settle();
const shorts = calls.find((c) => c.path.endsWith('/shorts/render'));
assert.equal(shorts.body.segments[0].hook, 'Chorus line');
assert.equal(shorts.body.segments[0].start, 5);

// ---- errors surface instead of hanging --------------------------------------------------
byId.get('clipRegen').click(); await settle();
assert.ok(toasts.some(([m, e]) => e && /unexpected/.test(m)), 'API errors become toasts');
console.log('SkellyMotion autonomous UI smoke tests passed: Clip Studio, Autopilot, Shorts, safe text, errors.');
