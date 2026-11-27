/**
 * Browser-logic smoke test for static/autoclip.js (no browser or npm packages needed).
 * Drives Clip Studio, Autopilot and the Shorts cards against a fake DOM and canned API replies.
 */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const html = fs.readFileSync('static/index.html', 'utf8');
const script = fs.readFileSync('static/autoclip.js', 'utf8');
const makeScript = fs.readFileSync('static/make.js', 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
assert.equal(new Set(ids).size, ids.length, 'duplicate IDs in index.html');
for (const needed of ['autoRunBtn', 'autopilotFromReview', 'openClipStudio', 'clipStudio', 'clipCards', 'autoShortList', 'openMake', 'makeOverlay', 'makeForm',
  'aePreset', 'aeVoice', 'aeFillers', 'aeZoomMode', 'aeBroll', 'proofModal', 'clipLangs', 'clipKeepFillers', 'brBrollList', 'autoVizBtn'])
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
  text: 'transcript ' + n, title: n === 0 ? '<img src=x onerror=alert(1)>' : 'Title ' + n, description: 'Desc ' + n, tags: ['mixing', 'tips'], reasons: ['opens with a question'] });
let projectPolls = 0;
const BRAND = { name: 'Skelly', font: 'Arial', accent: '#7CE86E', bg: '#0E1410', text: '#FFFFFF', has_logo: false, has_music: false, has_intro: false, has_outro: false,
  audio: { music_volume: 0.2, sfx_volume: 0.6 },
  watermark: { enabled: true, position: 'top-right', opacity: 0.85, size: 10 }, endcard: { enabled: true, title: 'Thanks', subtitle: '', url: '', seconds: 4 } };
const WATCH = { enabled: true, running: false, events: [], busy: null };
const PRESETS = [{ name: 'Tutorial', builtin: true, options: { trim_silence: true, voice_cleanup: 'medium', fillers: 'basic', zoom: 'subtle', shorts: 3 } }];
let etaStep = 0;
const MAKES = [{ id: 'q'.repeat(32), kind: 'mv', label: 'Music video', title: 'Night Drive', created: Math.round(Date.now() / 1000) - 7200, busy: false, files: [{ name: 'music_video.mp4', url: '/api/projects/q/files/music_video.mp4', type: 'video' }] },
  { id: 'r'.repeat(32), kind: 'stream', label: 'Livestream pack', title: '', created: Math.round(Date.now() / 1000) - 10, busy: true, files: [] }];
const BROLL = [{ name: 'eq', keywords: ['eq', 'equalizer'], duration: 4.2 }];
async function fakeFetch(path, options = {}) {
  const body = options.body && typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
  calls.push({ path, method: options.method || 'GET', body });
  const ok = (data) => ({ ok: true, status: 200, json: async () => data });
  if (path === '/api/creator/video-edit-instruction') return ok({settings:{...body.current,music:false},changes:[{setting:'music',before:body.current.music,after:false}]});
  if (path === '/api/clips/capabilities') return ok({ ai_rerank: false, ai_text: true, watch: true, languages: { es: 'Spanish', fr: 'French' }, max_source_mb: 2048, max_source_minutes: 180 });
  if (path === '/api/clip-sources') return ok({ id: 'b'.repeat(32), status: 'transcribing' });
  if (path === '/api/projects/' + 'b'.repeat(32)) {
    projectPolls++;
    return ok(projectPolls < 2 ? { status: 'transcribing', transcription_progress: 40, title: 'Demo' }
      : { status: 'ready', title: 'Demo', clip_suggestions: [clip(0), clip(1), clip(2), clip(3)] });
  }
  if (path === '/api/brand' && !options.method) return ok({ brand: BRAND });
  if (path === '/api/brand' && options.method === 'PUT') { Object.assign(BRAND, body.brand); return ok({ brand: BRAND }); }
  if (path === '/api/brand/logo' && options.method === 'POST') { BRAND.has_logo = true; return ok({ brand: BRAND }); }
  if (path.startsWith('/api/brand/asset/') && options.method === 'POST') { BRAND['has_' + path.split('/').pop()] = true; return ok({ brand: BRAND }); }
  if (path.startsWith('/api/brand/asset/') && options.method === 'DELETE') { BRAND['has_' + path.split('/').pop()] = false; return ok({ brand: BRAND }); }
  if (path.endsWith('/autoedit')) return ok({ job_id: 'job4' });
  if (path.endsWith('/translate')) return ok({ job_id: 'job5' });
  if (path.endsWith('/clips/variants')) return ok({ variants: [{ hook: 'Stop mixing blind', title: 'Mix better' }, { hook: 'The 3 knobs that matter', title: 'Three knobs' }] });
  if (path === '/api/watch/status') return ok(WATCH);
  if (path === '/api/watch/start') { WATCH.running = true; WATCH.events = [{ time: 1700000000, message: 'Watching ' + body.folder }]; return ok(WATCH); }
  if (path === '/api/watch/stop') { WATCH.running = false; return ok(WATCH); }
  if (path === '/api/jobs/job4') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: {
    video: '/api/projects/x/files/autoedit.mp4', thumbnail: '/api/projects/x/files/thumbnail.jpg', seconds: 95.2, removed_seconds: 12.5, cues: 40,
    captions: { srt: '/api/projects/x/files/captions.srt', vtt: '/api/projects/x/files/captions.vtt' },
    extras: { callouts: 2, lower_thirds: 3, sfx: 7, music: true, intro_clip: true, outro_clip: false, intro_card: false },
    youtube: { title: '<b>Big</b> title', description: 'Desc line', tags: ['mixing', 'eq'], file: '/api/projects/x/files/youtube.txt',
      chapters: [{ start: 0, title: 'Intro' }, { start: 75, title: 'Main part' }, { start: 160, title: 'Wrap up' }] },
    posts: { youtube_shorts: { text: 'YT text', chars: 7, limit: 100 }, x: { text: '<i>x</i> text', chars: 13, limit: 280 } },
    shorts: [{ n: 1, start: 1, end: 20, title: 'S1', description: 'd', tags: [], url: '/api/projects/x/clips/1' }] } });
  if (path === '/api/jobs/job5') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ lang: 'es', language: 'Spanish', srt: '/api/projects/x/files/captions.es.srt', vtt: '/api/projects/x/files/captions.es.vtt' }] } });
  if (path.endsWith('/clips/render')) return ok({ job_id: 'job1' });
  if (path.endsWith('/autopilot')) return ok({ job_id: 'job2' });
  if (path.endsWith('/shorts/suggestions')) return ok({ suggestions: [{ start: 5, end: 25, score: 0.7, reasons: ['likely chorus'], hook: 'Chorus line' }] });
  if (path.endsWith('/shorts/render')) return ok({ job_id: 'job3' });
  if (path === '/api/jobs/job1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { clips: [
    { n: 1, start: 0, end: 30, title: 'Rendered', description: 'd', tags: ['a b'], url: '/api/projects/x/clips/1' }] } });
  if (path === '/api/jobs/job2') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { full: '/api/projects/' + 'a'.repeat(32) + '/export',
    auto_confirmed: true, shorts: [{ n: 1, start: 1, end: 20, title: 'S1', description: 'd', tags: [], url: '/api/projects/x/shorts/1' }] } });
  if (path === '/api/jobs/job3') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { shorts: [{ n: 1, start: 5, end: 25, title: 'S', description: '', tags: [], url: '/u' }] } });

  if (path === '/api/presets' && !options.method) return ok({ presets: PRESETS });
  if (path.startsWith('/api/presets/') && options.method === 'PUT') {
    const name = decodeURIComponent(path.split('/').pop()); PRESETS.push({ name, builtin: false, options: body.options }); return ok({ presets: PRESETS });
  }
  if (path.startsWith('/api/presets/') && options.method === 'DELETE') {
    const name = decodeURIComponent(path.split('/').pop()); PRESETS.splice(PRESETS.findIndex((p) => p.name === name), 1); return ok({ presets: PRESETS });
  }
  if (path.endsWith('/transcript') && !options.method) return ok({ words: 300, uncertain: [{ i: 7, text: 'scaly', prob: 0.31, start: 12.4, before: 'meet the', after: 'tune plugin' }] });
  if (path.endsWith('/transcript') && options.method === 'POST') return ok({ changed: 2, uncertain: [], suggestions: [clip(0)] });
  if (path === '/api/brand/broll' && !options.method) return ok({ clips: BROLL, max: 40 });
  if (path === '/api/brand/broll' && options.method === 'POST') { BROLL.push({ name: 'knob', keywords: ['knob'], duration: 3 }); return ok({ clips: BROLL }); }
  if (path.startsWith('/api/brand/broll/') && options.method === 'PUT') return ok({ clips: BROLL });
  if (path.startsWith('/api/brand/broll/') && options.method === 'DELETE') { BROLL.length = 0; return ok({ clips: BROLL }); }
  if (path.endsWith('/posts')) return ok({ ai: true, posts: { x: { text: 'AI wrote this', chars: 12, limit: 280 } } });
  if (path === '/api/makes' && !options.method) return ok({ makes: MAKES });
  if (path.startsWith('/api/makes/') && options.method === 'DELETE') { MAKES.shift(); return ok({ deleted: true }); }
  if (path.endsWith('/cancel')) return ok({ cancelled: true, status: 'rendering' });
  if (path.endsWith('/visualizer')) return ok({ job_id: 'job6' });
  if (path === '/api/jobs/job6') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { video: '/api/projects/x/export', lyrics: true } });
  if (path === '/api/music-video') return ok({ job_id: 'mv1', id: 'm'.repeat(32) });
  if (path === '/api/jobs/mv1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { video: '/api/projects/m/files/music_video.mp4', bpm: 120.4, cuts: 24, clips: 2, seconds: 30 } });
  if (path === '/api/animation') return ok({ job_id: 'an1', id: 'n'.repeat(32) });
  if (path === '/api/jobs/an1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { video: '/api/projects/n/files/animation.mp4', seconds: 6.5 } });
  if (path === '/api/livestream') return ok({ job_id: 'ls1', id: 'l'.repeat(32) });
  if (path === '/api/jobs/ls1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { scenes: [
    { scene: 'intro', video: '/api/projects/l/files/stream_intro.mp4', seconds: 5, loop: false }, { scene: 'brb', video: '/api/projects/l/files/stream_brb.mp4', seconds: 8, loop: true }] } });
  if (path === '/api/gif') return ok({ job_id: 'gif1', id: 'g'.repeat(32) });
  if (path === '/api/jobs/gif1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'GIF, 1.2 MB', name: 'preview.gif', url: '/api/projects/g/files/preview.gif', kind: 'image' }], seconds: 3, bytes: 1200000, warning: 'This GIF is still large.' } });
  if (path === '/api/enhance') return ok({ job_id: 'en1', id: 'e'.repeat(32) });
  if (path === '/api/jobs/en1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Enhanced audio', name: 'enhanced.m4a', url: '/api/projects/e/files/enhanced.m4a', kind: 'audio' }] } });
  if (path === '/api/capabilities') return ok({ ffmpeg: true, tools: { speed: { ok: false, missing: ['atempo'] }, gif: { ok: true, missing: [] } } });
  if (path === '/api/makes' && options.method === 'DELETE') { const n = MAKES.length; MAKES.length = 0; return ok({ deleted: n, skipped: 1 }); }
  if (['/api/trim', '/api/shrink', '/api/contact-sheet', '/api/quote-card'].includes(path)) return ok({ job_id: 'x_' + path.slice(5), id: 'k'.repeat(32) });
  if (path === '/api/jobs/x_trim') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Trimmed video', name: 'trimmed.mp4', url: '/api/projects/k/files/trimmed.mp4', kind: 'video' }], seconds: 3 } });
  if (path === '/api/jobs/x_shrink') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Shrunk video, 7.4 MB', name: 'shrunk.mp4', url: '/api/projects/k/files/shrunk.mp4', kind: 'video' }], warning: 'The result is a little over 8 MB.' } });
  if (path === '/api/jobs/x_contact-sheet') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Contact sheet', name: 'contact_sheet.jpg', url: '/api/projects/k/files/contact_sheet.jpg', kind: 'image' }] } });
  if (path === '/api/jobs/x_quote-card') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Square 1:1', name: 'quote_card.png', url: '/api/projects/k/files/quote_card.png', kind: 'image' }] } });
  if (path === '/api/jobs/eta1') { etaStep += 1; return ok({ id: 'eta1', status: etaStep > 3 ? 'done' : 'rendering', stage: 'mv_render', progress: [0, 5, 30, 60, 100][etaStep] ?? 100, outputs: {} }); }
  if (['/api/fade', '/api/loop', '/api/extract-audio', '/api/frame', '/api/swap-audio'].includes(path)) return ok({ job_id: 'y_' + path.slice(5), id: 'k'.repeat(32) });
  if (path === '/api/jobs/y_swap-audio') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Video with new audio', name: 'swapped.mp4', url: '/api/projects/k/files/swapped.mp4', kind: 'video' }] } });
  if (path === '/api/jobs/y_extract-audio') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Audio (.m4a)', name: 'audio.m4a', url: '/api/projects/k/files/audio.m4a', kind: 'audio' }] } });
  if (path.startsWith('/api/jobs/y_')) return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Result', name: 'faded.mp4', url: '/api/projects/k/files/faded.mp4', kind: 'video' }] } });
  if (path.startsWith('/api/quick/')) return ok({ job_id: 'q_' + path.slice(11), id: 'k'.repeat(32) });
  if (path.startsWith('/api/jobs/q_')) return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Result ' + path.slice(12), name: 'joined.mp4', url: '/api/projects/k/files/joined.mp4', kind: 'video' }], seconds: 5 } });
  if (path === '/api/lower-third') return ok({ job_id: 'lt1', id: 'h'.repeat(32) });
  if (path === '/api/jobs/lt1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [{ label: 'Video with lower third', name: 'lowerthird.mp4', url: '/api/projects/h/files/lowerthird.mp4', kind: 'video' }], appearances: 1 } });
  if (path.endsWith('/repurpose')) return ok({ job_id: 'rp1', id: 'a'.repeat(32) });
  if (path === '/api/jobs/rp1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: [
    { label: 'Vertical 9:16', name: 'autoedit_9x16.mp4', url: '/api/projects/a/files/autoedit_9x16.mp4', kind: 'video' }, { label: 'Square 1:1', name: 'autoedit_1x1.mp4', url: '/api/projects/a/files/autoedit_1x1.mp4', kind: 'video' }] } });
  if (path.endsWith('/thumbnails')) return ok({ job_id: 'th1', id: 'a'.repeat(32) });
  if (path === '/api/jobs/th1') return ok({ status: 'done', stage: 'complete', progress: 100, outputs: { files: ['a', 'b', 'c'].map((x) => ({ label: 'Layout ' + x, name: 'thumbnail_' + x + '.jpg', url: '/api/projects/a/files/thumbnail_' + x + '.jpg', kind: 'image' })) } });
  return { ok: false, status: 404, json: async () => ({ detail: 'unexpected ' + path }) };
}
const toasts = []; let reloaded = null; const panels = [];
const editorState = { id: 'a'.repeat(32), lines: [{ id: 'l1', text: 'hi there', start: 1, end: 3, words: [] }], settings: { font: 'Arial' } };
const bridge = { state: () => editorState, toast: (m, e) => toasts.push([m, e]), panel: (n) => panels.push(n),
  audio: () => null, reloadProject: async (id) => { reloaded = id; } };
let fakeNow = null; // null: the real clock
const FakeDate = class extends Date { static now() { return fakeNow ?? Date.now(); } };
const keyListeners = []; const parkedTimers = [];
const context = {
  window: {}, console, URL, FormData: class { constructor() { this.d = []; } append(k, v) { this.d.push([k, v]); } },
  // Short waits (job polling) run at once; long ones (the 3 s watch refresh) are parked like a real timer would be.
  setTimeout: (fn, ms) => { if (ms >= 3000) { parkedTimers.push(fn); return 0; } fn(); return 0; }, clearTimeout() {},
  navigator: { clipboard: { writeText: async () => {} } }, fetch: fakeFetch,
  localStorage: { _m: new Map(), getItem(k) { return this._m.has(k) ? this._m.get(k) : null; }, setItem(k, v) { this._m.set(k, String(v)); } },
  Object, Array, String, Number, Date: FakeDate,
  document: { getElementById: (id) => byId.get(id) ?? null, createElement: makeNode, addEventListener: (t, fn) => keyListeners.push([t, fn]) },
};
context.window = context;
context.window.SkellyBridge = bridge;
vm.runInNewContext(script, context, { filename: 'static/autoclip.js' });
vm.runInNewContext(makeScript, context, { filename: 'static/make.js' });
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


// ---- polish options travel with clip renders --------------------------------------------------
byId.get('clipLoud').checked = true; byId.get('clipTrim').checked = true; byId.get('clipWatermark').checked = false;
byId.get('clipRender').click(); await settle();
const polished = calls.filter((c) => c.path.endsWith('/clips/render')).pop();
assert.deepEqual(polished.body.polish, { loudness: true, trim_silence: true, watermark: false });

// ---- hook ideas fill the hook and title boxes ---------------------------------------------------
const firstCard = byId.get('clipCards').children[0];
const ideaButton = find(firstCard, (n) => n.tagName === 'BUTTON' && n.textContent === 'Hook ideas')[0];
assert.ok(ideaButton, 'hook ideas button exists when the server has an AI key');
ideaButton.click(); await settle();
assert.equal(calls.filter((c) => c.path.endsWith('/clips/variants')).pop().body.text, 'transcript 0');
const chip = find(firstCard, (n) => n.className === 'idea-chip')[0];
chip.click();
assert.equal(find(firstCard, (n) => n.attrs?.['aria-label'] === 'Hook text')[0].value, 'Stop mixing blind');
assert.equal(find(firstCard, (n) => n.attrs?.['aria-label'] === 'Title')[0].value, 'Mix better');

// ---- brand kit: load, edit, upload a logo, save ----------------------------------------------------
byId.get('brandOpen').click(); await settle();
assert.ok(!byId.get('brandModal').classList.contains('hidden'), 'brand dialog opens');
assert.equal(byId.get('brName').value, 'Skelly');
byId.get('brName').value = 'Skelly Audio'; byId.get('brEcUrl').value = 'skelly.example'; byId.get('brWmPos').value = 'bottom-left';
byId.get('brLogoFile').fire('change', { target: { files: [{ name: 'logo.png' }], value: '' } }); await settle();
assert.ok(calls.some((c) => c.path === '/api/brand/logo' && c.method === 'POST'), 'logo uploaded');
assert.equal(byId.get('brName').value, 'Skelly Audio', 'unsaved edits survive a logo upload');
// music + intro clip are uploaded to their own endpoints; typed edits and slider values survive each upload
byId.get('brMusicVol').value = '0.35';
byId.get('brMusicFile').fire('change', { target: { files: [{ name: 'bed.mp3' }], value: '' } }); await settle();
byId.get('brIntroFile').fire('change', { target: { files: [{ name: 'intro.mp4' }], value: '' } }); await settle();
assert.ok(calls.some((c) => c.path === '/api/brand/asset/music' && c.method === 'POST'), 'music uploaded');
assert.ok(calls.some((c) => c.path === '/api/brand/asset/intro' && c.method === 'POST'), 'intro uploaded');
assert.equal(byId.get('brMusicName').textContent, 'Added'); assert.equal(byId.get('brIntroName').textContent, 'Added');
assert.equal(byId.get('brOutroName').textContent, 'None');
assert.ok(!byId.get('brMusicClear').classList.contains('hidden') && byId.get('brOutroClear').classList.contains('hidden'));
assert.equal(byId.get('brName').value, 'Skelly Audio'); assert.equal(Number(byId.get('brMusicVol').value), 0.35);
byId.get('brIntroClear').click(); await settle();
assert.ok(calls.some((c) => c.path === '/api/brand/asset/intro' && c.method === 'DELETE'), 'intro removed');
assert.equal(byId.get('brIntroName').textContent, 'None');
byId.get('brandSave').click(); await settle();
const saved = calls.filter((c) => c.path === '/api/brand' && c.method === 'PUT').pop().body.brand;
assert.equal(saved.name, 'Skelly Audio'); assert.equal(saved.audio.music_volume, 0.35); assert.equal(saved.watermark.position, 'bottom-left'); assert.equal(saved.endcard.url, 'skelly.example');
assert.ok(byId.get('brandModal').classList.contains('hidden'), 'dialog closes after save');

// ---- auto-edit: one button, a finished package, safe text, translation -----------------------------------
// The fake DOM does not read HTML defaults, so set what the real page ships pre-selected.
for (const id of ['aeTrim', 'aeLoud', 'aeWatermark', 'aeEndcard']) byId.get(id).checked = true;
byId.get('aeRes').value = '1080p';
for (const id of ['aeSfx', 'aeCallouts', 'aeTitles', 'aeMusic', 'aeIntroOutro']) byId.get(id).checked = true;
byId.get('aeIntroCard').checked = false;
byId.get('aeZoom').value = 'medium'; byId.get('aeShorts').value = '3'; byId.get('aeCaptions').checked = true;
byId.get('aeVoice').value = 'off'; byId.get('aeFillers').value = 'off'; byId.get('aeZoomMode').value = 'motion'; byId.get('aeBroll').checked = true;
byId.get('autoEditRun').click(); await settle();
const edited = calls.find((c) => c.path.endsWith('/autoedit'));
assert.deepEqual(edited.body, { trim_silence: true, loudness: true, watermark: true, endcard: true, captions: true, zoom: 'medium', resolution: '1080p', shorts: 3,
  sfx: true, callouts: true, chapter_titles: true, music: true, intro_outro: true, intro_card: false, voice_cleanup: 'off', fillers: 'off', zoom_mode: 'motion', broll: true });
const results = byId.get('autoEditResults');
assert.match(byId.get('autoEditStatus').textContent, /ready/);
assert.ok(find(results, (n) => n.tagName === 'IMG' && n.attrs.src.endsWith('thumbnail.jpg')).length === 1, 'thumbnail shown');
assert.ok(find(results, (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('autoedit.mp4')).length === 1, 'edited video shown');
assert.equal(find(results, (n) => n.tagName === 'IMG' && n.attrs.src.includes('<')).length, 0);
const titleField = find(results, (n) => n.tagName === 'INPUT' && n.value === '<b>Big</b> title');
assert.equal(titleField.length, 1, 'YouTube title is a plain value, never HTML');
assert.equal(find(results, (n) => n.tagName === 'B' && n._text === 'Big').length, 0, 'no injected <b> element');
assert.match(results.textContent, /removed 12.5 s of dead air/);
assert.match(results.textContent, /Added automatically/);
assert.match(results.textContent, /3 chapter titles · 2 callouts · 7 sound effects · background music/);
assert.ok(results.textContent.includes('your intro clip') && !results.textContent.includes('your outro clip'));
assert.match(results.textContent, /3 chapters found/);
assert.ok(find(results, (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('/clips/1')).length === 1, 'Shorts listed');

const moreBtn = find(results, (n) => n.tagName === 'BUTTON' && n.textContent === 'Make vertical and square versions')[0];
assert.ok(moreBtn, 'Auto-edit offers vertical and square versions');
moreBtn.click(); await settle();
const repCall = calls.find((c) => c.path === '/api/projects/' + 'b'.repeat(32) + '/repurpose');
assert.deepEqual(repCall.body, { formats: ['portrait', 'square'], resolution: '1080p' });
assert.ok(find(results, (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('autoedit_9x16.mp4')).length === 1 && find(results, (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('autoedit_1x1.mp4')).length === 1, 'both versions shown');
assert.ok(!moreBtn.attrs.disabled, 'the button is usable again afterwards');
find(results, (n) => n.tagName === 'BUTTON' && n.textContent === 'Thumbnail variants')[0].click(); await settle();
assert.equal(calls.find((c) => c.path.endsWith('/thumbnails')).body.title, '<b>Big</b> title', 'the YouTube title is the starting text');
assert.equal(find(results, (n) => n.tagName === 'IMG' && /thumbnail_[abc]\.jpg$/.test(n.attrs.src)).length, 3, 'three layouts shown');

find(results, (n) => n.tagName === 'BUTTON' && n.textContent === 'Vertical, cropped to fill')[0].click(); await settle();
assert.deepEqual(calls.filter((c) => c.path.endsWith('/repurpose')).pop().body, { formats: ['portrait'], resolution: '1080p', fit: 'fill' });
// time left: shown once the job has moved enough, never for an unmoved or nearly finished one
{
  const node = makeNode('div'); let t = 1000; fakeNow = t;
  const S = context.window.SkellyUI; S.showStatus(node, { id: 'eta-x', status: 'rendering', stage: 'mv_render', progress: 2 });
  assert.ok(!/left/.test(node.textContent), 'no estimate at the start');
  t += 20000; fakeNow = t; S.showStatus(node, { id: 'eta-x', status: 'rendering', stage: 'mv_render', progress: 42 });
  assert.match(node.textContent, /about (\d+ s|1 min|\d+ min) left/, 'an estimate once it has moved');
  assert.match(node.textContent, /about 30 s left/, '20 s for 40% leaves about 30 s');
  S.showStatus(node, { id: 'eta-x', status: 'rendering', stage: 'mv_render', progress: 98 });
  assert.ok(!/left/.test(node.textContent), 'nothing when nearly done');
  fakeNow = null;
}
const langs = find(results, (n) => n.tagName === 'INPUT' && n.attrs.type === 'checkbox' && ['es', 'fr'].includes(n.attrs.value));
assert.equal(langs.length, 2, 'language choices come from the server');
const translate = find(results, (n) => n.tagName === 'BUTTON' && n.textContent.startsWith('Translate selected'))[0];
translate.click(); await settle();
assert.ok(!calls.some((c) => c.path.endsWith('/translate')), 'nothing sent with no language picked');
langs[0].checked = true; translate.click(); await settle();
assert.deepEqual(calls.find((c) => c.path.endsWith('/translate')).body, { languages: ['es'] });
assert.ok(find(results, (n) => n.tagName === 'A' && n.attrs.href.endsWith('captions.es.srt')).length === 1, 'translated SRT linked');

// ---- watch folder ------------------------------------------------------------------------------------
assert.ok(!byId.get('watchBox').classList.contains('hidden'), 'watch box shown when the server allows it');
byId.get('watchFolder').value = 'C:\\Inbox'; byId.get('watchOut').value = 'C:\\Finished'; byId.get('watchShorts').value = '1';
byId.get('watchStart').click(); await settle();
const started = calls.find((c) => c.path === '/api/watch/start');
assert.equal(started.body.folder, 'C:\\Inbox'); assert.equal(started.body.options.shorts, 1);
assert.match(byId.get('watchLog').textContent, /Watching C:\\Inbox/);
assert.ok(byId.get('watchStart').classList.contains('hidden') && !byId.get('watchStop').classList.contains('hidden'));
byId.get('watchStop').click(); await settle();
assert.ok(!byId.get('watchStart').classList.contains('hidden'), 'start button returns after stopping');


// ---- presets, post tabs ---------------------------------------------------------------------------------
const presetSelect = byId.get('aePreset');
assert.equal(presetSelect.children.length, 2, 'custom plus the built-in preset');
presetSelect.value = 'Tutorial'; presetSelect.fire('change');
assert.equal(byId.get('aeVoice').value, 'medium'); assert.equal(byId.get('aeFillers').value, 'basic'); assert.equal(byId.get('aeZoom').value, 'subtle');
assert.equal(byId.get('aeShorts').value, '3'); assert.ok(byId.get('aePresetDelete').classList.contains('hidden'), 'built-ins cannot be deleted');
byId.get('aeBroll').checked = false;
byId.get('aePresetSave').click(); await settle();
assert.ok(!calls.some((c) => c.method === 'PUT' && c.path.startsWith('/api/presets/')), 'no name, nothing saved');
byId.get('aePresetName').value = 'My weekly'; byId.get('aePresetSave').click(); await settle();
const savedPreset = calls.find((c) => c.method === 'PUT' && c.path === '/api/presets/My%20weekly');
assert.equal(savedPreset.body.options.voice_cleanup, 'medium'); assert.equal(savedPreset.body.options.broll, false);
assert.equal(byId.get('aePreset').value, 'My weekly'); assert.ok(!byId.get('aePresetDelete').classList.contains('hidden'));
byId.get('aePresetDelete').click(); await settle();
assert.ok(calls.some((c) => c.method === 'DELETE' && c.path === '/api/presets/My%20weekly'), 'user preset deleted');
const postTabs = find(results, (n) => (n.className || '').split(' ').includes('make-tab'));
assert.deepEqual(postTabs.map((n) => n.textContent), ['YouTube Shorts', 'X'], 'one tab per platform');
const postArea = find(results, (n) => n.tagName === 'TEXTAREA' && n.value === 'YT text')[0];
assert.ok(postArea, 'first platform shown first');
postTabs[1].click();
assert.equal(postArea.value, '<i>x</i> text', 'post text is a plain value'); assert.equal(find(results, (n) => n.tagName === 'I').length, 0);
assert.match(results.textContent, /13 of 280 characters/);
find(results, (n) => n.tagName === 'BUTTON' && n.textContent === 'Rewrite with AI')[0].click(); await settle();
assert.equal(calls.find((c) => c.path.endsWith('/posts')).body.use_ai, true);
assert.equal(postArea.value, 'AI wrote this');

// ---- proofreading ----------------------------------------------------------------------------------------
byId.get('proofOpen').click(); await settle();
assert.ok(!byId.get('proofModal').classList.contains('hidden'), 'proof dialog opens');
assert.match(byId.get('proofSummary').textContent, /1 word\(s\)/);
const proofInput = find(byId.get('proofList'), (n) => n.tagName === 'INPUT')[0];
assert.equal(proofInput.value, 'scaly'); assert.match(byId.get('proofList').textContent, /meet the \[scaly\] tune plugin/);
byId.get('proofApply').click(); await settle();
assert.ok(!calls.some((c) => c.path.endsWith('/transcript') && c.method === 'POST'), 'nothing sent when nothing changed');
proofInput.value = 'Skelly'; byId.get('proofFind').value = 'scaly tune'; byId.get('proofWith').value = 'SkellyTune';
byId.get('proofApply').click(); await settle();
const proofed = calls.find((c) => c.path.endsWith('/transcript') && c.method === 'POST').body;
assert.deepEqual(proofed.edits, [{ i: 7, text: 'Skelly' }]); assert.deepEqual(proofed.replace, [{ find: 'scaly tune', with: 'SkellyTune', case: false }]);
assert.equal(byId.get('clipCards').children.length, 1, 'clip picks refresh after corrections');
assert.ok(toasts.some(([m]) => /2 word\(s\) corrected/.test(m)));
byId.get('proofClose').click(); assert.ok(byId.get('proofModal').classList.contains('hidden'));

// ---- translated clips and the filler listen switch -------------------------------------------------------------
const clipLangBoxes = find(byId.get('clipLangs'), (n) => n.tagName === 'INPUT' && ['es', 'fr'].includes(n.attrs.value));
assert.equal(clipLangBoxes.length, 2); assert.ok(!byId.get('clipLangs').classList.contains('hidden'));
clipLangBoxes[1].checked = true;
byId.get('clipRender').click(); await settle();
assert.deepEqual(calls.filter((c) => c.path.endsWith('/clips/render')).pop().body.languages, ['fr']);
byId.get('clipKeepFillers').checked = false;
byId.get('clipFile').fire('change', { target: { files: [{ name: 'talk2.mp4' }], value: '' } }); await settle();
const upload = calls.filter((c) => c.path === '/api/clip-sources').pop().body.d;
assert.deepEqual(upload.find(([k]) => k === 'keep_fillers'), ['keep_fillers', 'false']);

// ---- B-roll library --------------------------------------------------------------------------------------------
byId.get('brandOpen').click(); await settle();
assert.match(byId.get('brBrollList').textContent, /eq/); assert.equal(byId.get('brBrollCount').textContent, '1 of 40');
const kw = find(byId.get('brBrollList'), (n) => n.tagName === 'INPUT')[0]; assert.equal(kw.value, 'eq, equalizer');
kw.value = 'eq, curve'; find(byId.get('brBrollList'), (n) => n.tagName === 'BUTTON' && n.textContent === 'Save')[0].click(); await settle();
assert.deepEqual(calls.find((c) => c.method === 'PUT' && c.path === '/api/brand/broll/eq').body, { keywords: ['eq', 'curve'] });
byId.get('brBrollKeywords').value = 'knob';
byId.get('brBrollFile').fire('change', { target: { files: [{ name: 'knob.mp4' }], value: '' } }); await settle();
assert.deepEqual(calls.find((c) => c.path === '/api/brand/broll' && c.method === 'POST').body.d.map(([k]) => k), ['file', 'keywords']);
find(byId.get('brBrollList'), (n) => n.tagName === 'BUTTON' && n.textContent === 'Remove')[0].click(); await settle();
assert.ok(calls.some((c) => c.method === 'DELETE' && c.path === '/api/brand/broll/eq'));
byId.get('brandCancel').click();

// ---- audio-reactive lyric video ---------------------------------------------------------------------------------------
byId.get('autoVizStyle').value = 'wave'; byId.get('autoVizBtn').click(); await settle();
assert.deepEqual(calls.find((c) => c.path.endsWith('/visualizer')).body, { style: 'wave', lyrics: true });
assert.ok(find(byId.get('autoResults'), (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('/export')).length === 1);
assert.match(byId.get('autoStatus').textContent, /audio-reactive video is ready/);

// ---- Make overlay -----------------------------------------------------------------------------------------------------------
const goButton = () => find(byId.get('makeForm'), (n) => n.attrs?.id === 'makeGo')[0];
const named = (name) => find(byId.get('makeForm'), (n) => n.attrs?.name === name)[0];
byId.get('openMake').click(); await settle();
assert.ok(!byId.get('makeOverlay').classList.contains('hidden'), 'Make opens');
assert.match(byId.get('makeRecent').textContent, /Music video · Night Drive · 2 h ago/);
assert.match(byId.get('makeRecent').textContent, /Livestream pack · \d+ min ago|Livestream pack · just now/);
assert.match(byId.get('makeRecent').textContent, /Still rendering/);
assert.equal(find(byId.get('makeRecent'), (n) => n.tagName === 'BUTTON' && n.textContent === 'Delete').length, 1, 'a running render cannot be deleted');
find(byId.get('makeRecent'), (n) => n.tagName === 'BUTTON' && n.textContent === 'Delete')[0].click(); await settle();
assert.ok(calls.some((c) => c.method === 'DELETE' && c.path === '/api/makes/' + 'q'.repeat(32)));
assert.doesNotMatch(byId.get('makeRecent').textContent, /Night Drive/);
assert.deepEqual(byId.get('makeTabs').children.map((n) => n.textContent), ['Music video', 'Animations', 'Livestream pack', 'Before / After', 'Visualizer', 'GIF', 'Audio enhance', 'Lower third', 'Speed', 'Trim', 'Shrink to size', 'Contact sheet', 'Quote card', 'Fades', 'Loop', 'Extract audio', 'Still frame', 'Swap audio', 'Remove audio', 'Rotate / flip', 'Resize', 'Frame rate', 'Reverse', 'Volume', 'Watermark', 'Crop to shape', 'Color', 'Clean up picture', 'Waveform picture', 'Image + audio', 'Background music', 'Join videos', 'Picture in picture', 'Zoom in', 'Add borders', 'Hold first / last frame', 'Cut out a part', 'Looks', 'Side by side', 'Slideshow', 'Text on video', 'Crossfade join', 'Trim audio', 'Audio fades', 'Audio speed', 'Bass and treble', 'Mono / swap sides', 'Join audio', 'Remove silence', 'Loop audio', 'Pitch shift', 'Echo', 'Collage', 'Frame a screenshot', 'Color palette', 'Before / after picture', 'YouTube banner', 'Profile picture', 'Clip around the drop', 'Best part of a song', 'Song analysis']);
goButton().click(); await settle();
assert.ok(toasts.some(([m, e]) => e && /Still needed: Song, Footage/.test(m)), 'missing files are named');
assert.ok(!calls.some((c) => c.path === '/api/music-video'));
const flagged = find(byId.get('makeForm'), (n) => String(n.className || '').includes('make-field') && n.classList.contains('invalid'));
assert.equal(flagged.length, 2, 'the two missing files are marked on the form, not just named in a toast');
assert.ok(find(byId.get('makeForm'), (n) => String(n.className || '').includes('required')).length >= 2, 'required fields are marked');
assert.equal(byId.get('makeToolTitle').textContent, 'Music video', 'the chosen tool is named above its form');

named('song').files = [{ name: 'song.mp3' }]; named('clips').files = [{ name: 'a.mp4' }, { name: 'b.mp4' }];
named('intensity').value = 'hype'; named('title').value = 'Night Drive';
goButton().click(); await settle();
const mvCall = calls.find((c) => c.path === '/api/music-video').body.d;
assert.deepEqual(mvCall.filter(([k]) => k === 'clips').length, 2, 'every footage file is sent');
assert.deepEqual(Object.fromEntries(mvCall.filter(([k]) => !['song', 'clips'].includes(k))),
  { intensity: 'hype', aspect: 'landscape', resolution: '1080p', title: 'Night Drive', artist: '', watermark: 'true', endcard: 'false' });
const mvResults = byId.get('makeResults');
assert.match(mvResults.textContent, /120 BPM · 24 cuts from 2 clips · 30 s/);
assert.ok(find(mvResults, (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('music_video.mp4')).length === 1);
assert.ok(find(mvResults, (n) => n.tagName === 'A' && n.attrs.href.endsWith('music_video.mp4')).length === 1, 'download link');

byId.get('makeTabs').children[1].click();
assert.ok(named('text') && named('style'), 'the text template shows its own fields first');
const tplSelect = named('template'); tplSelect.value = 'countdown'; tplSelect.fire('change');
const countField = find(byId.get('makeForm'), (n) => n.ctl === named('count'))[0];
const textField = find(byId.get('makeForm'), (n) => n.ctl === named('text'))[0];
assert.ok(textField.classList.contains('hidden') && !countField.classList.contains('hidden'), 'fields follow the template');
named('count').value = '4'; goButton().click(); await settle();
const animBody = Object.fromEntries(calls.find((c) => c.path === '/api/animation').body.d);
assert.equal(animBody.template, 'countdown'); assert.equal(animBody.count, '4'); assert.ok(!('text' in animBody) && !('style' in animBody), 'hidden fields are not sent');
assert.equal(animBody.sfx, 'true'); assert.match(byId.get('makeResults').textContent, /7 s/);
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('animation.mp4')).length === 1);

byId.get('makeTabs').children[2].click();
const sceneBoxes = find(byId.get('makeForm'), (n) => n.tagName === 'INPUT' && ['intro', 'starting', 'brb', 'ending'].includes(n.attrs.value));
assert.equal(sceneBoxes.length, 4); sceneBoxes[1].checked = false;
goButton().click(); await settle();
assert.equal(Object.fromEntries(calls.find((c) => c.path === '/api/livestream').body.d).scenes, 'intro,brb,ending');
assert.match(byId.get('makeResults').textContent, /Intro/); assert.match(byId.get('makeResults').textContent, /Be right back \(loops\)/);
sceneBoxes.forEach((b) => { b.checked = false; });
const before = calls.length; goButton().click(); await settle();
assert.equal(calls.length, before, 'no request with no scene chosen');
assert.ok(toasts.some(([m, e]) => e && /Scenes to make/.test(m)));
byId.get('makeTabs').children[5].click();
named('file').files = [{ name: 'talk.mp4' }]; named('start').value = '2'; named('seconds').value = '3'; named('width').value = '320';
goButton().click(); await settle();
assert.deepEqual(Object.fromEntries(calls.find((c) => c.path === '/api/gif').body.d.filter(([k]) => k !== 'file')), { start: '2', seconds: '3', width: '320', fps: '12' });
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'IMG' && n.attrs.src.endsWith('preview.gif')).length === 1, 'GIF shown as a picture');
assert.match(byId.get('makeResults').textContent, /3 s/); assert.match(byId.get('makeResults').textContent, /still large/);
byId.get('makeTabs').children[6].click();
named('file').files = [{ name: 'voice.wav' }]; named('level').value = 'strong'; named('loudness').value = '-16';
goButton().click(); await settle();
assert.deepEqual(Object.fromEntries(calls.find((c) => c.path === '/api/enhance').body.d.filter(([k]) => k !== 'file')), { level: 'strong', loudness: '-16' });
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'AUDIO' && n.attrs.src.endsWith('enhanced.m4a')).length === 1, 'audio gets an audio player');
byId.get('makeTabs').children[7].click();
named('file').files = [{ name: 'talk.mp4' }];
goButton().click(); await settle();
assert.ok(!calls.some((c) => c.path === '/api/lower-third'), 'the name is required before anything is sent');
assert.ok(toasts.some(([m, e]) => e && /Still needed: Name/.test(m)));
named('name').value = 'Skelly Dev'; named('role').value = 'Plugin author'; named('every').value = '60';
goButton().click(); await settle();
assert.deepEqual(Object.fromEntries(calls.find((c) => c.path === '/api/lower-third').body.d.filter(([k]) => k !== 'file')),
  { name: 'Skelly Dev', role: 'Plugin author', start: '1', duration: '5', every: '60' });
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('lowerthird.mp4')).length === 1);

// ---- second batch of tools, remembered settings, tools the FFmpeg build cannot run ------------------------------------------------
const tabNames = Array.from(byId.get('makeTabs').children).map((b) => b.textContent);
assert.deepEqual(tabNames.slice(8), ['Speed', 'Trim', 'Shrink to size', 'Contact sheet', 'Quote card', 'Fades', 'Loop', 'Extract audio', 'Still frame', 'Swap audio', 'Remove audio', 'Rotate / flip', 'Resize', 'Frame rate', 'Reverse', 'Volume', 'Watermark', 'Crop to shape', 'Color', 'Clean up picture', 'Waveform picture', 'Image + audio', 'Background music', 'Join videos', 'Picture in picture', 'Zoom in', 'Add borders', 'Hold first / last frame', 'Cut out a part', 'Looks', 'Side by side', 'Slideshow', 'Text on video', 'Crossfade join', 'Trim audio', 'Audio fades', 'Audio speed', 'Bass and treble', 'Mono / swap sides', 'Join audio', 'Remove silence', 'Loop audio', 'Pitch shift', 'Echo', 'Collage', 'Frame a screenshot', 'Color palette', 'Before / after picture', 'YouTube banner', 'Profile picture', 'Clip around the drop', 'Best part of a song', 'Song analysis']);
const speedTab = byId.get('makeTabs').children[8];
assert.ok(speedTab.classList.contains('unavailable') && /atempo/.test(speedTab.attrs.title), 'a tool whose filter is missing is greyed out and says why');
speedTab.click();
assert.match(byId.get('makeBlurb').textContent, /missing: atempo/);
assert.ok(goButton().attrs.disabled || goButton().disabled, 'and cannot be started');
const callsBefore = calls.length; named("file").files = [{ name: "a.mp4" }]; goButton().click(); await settle();
assert.equal(calls.length, callsBefore, "nothing is sent for it");
byId.get('makeTabs').children[9].click();
named('file').files = [{ name: 'talk.mp4' }]; named('start').value = '2'; named('end').value = '5';
goButton().click(); await settle();
assert.deepEqual(Object.fromEntries(calls.find((c) => c.path === '/api/trim').body.d.filter(([k]) => k !== 'file')), { start: '2', end: '5' });
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('trimmed.mp4')).length === 1);
byId.get('makeTabs').children[10].click();
named('file').files = [{ name: 'talk.mp4' }]; named('size').value = '8';
goButton().click(); await settle();
assert.equal(calls.find((c) => c.path === '/api/shrink').body.d.find(([k]) => k === 'size')[1], '8');
assert.match(byId.get('makeResults').textContent, /little over 8 MB/);
byId.get('makeTabs').children[11].click();
named('file').files = [{ name: 'talk.mp4' }]; named('cols').value = '4'; named('rows').value = '2';
goButton().click(); await settle();
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'IMG' && n.attrs.src.endsWith('contact_sheet.jpg')).length === 1);
byId.get('makeTabs').children[12].click();
goButton().click(); await settle();
assert.ok(!calls.some((c) => c.path === '/api/quote-card'), 'the quote is required');
named('quote').value = 'Tune less, play more.'; named('author').value = 'Skelly'; named('aspect').value = 'portrait';
goButton().click(); await settle();
assert.deepEqual(Object.fromEntries(calls.find((c) => c.path === '/api/quote-card').body.d), { quote: 'Tune less, play more.', author: 'Skelly', aspect: 'portrait' });
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'IMG' && n.attrs.src.endsWith('quote_card.png')).length === 1);
byId.get('makeTabs').children[17].click();
named('file').files = [{ name: 'talk.mp4' }]; goButton().click(); await settle();
assert.ok(!calls.some((c) => c.path === '/api/swap-audio'), 'both the video and the new track are required');
named('audio').files = [{ name: 'song.wav' }]; goButton().click(); await settle();
assert.deepEqual(calls.find((c) => c.path === '/api/swap-audio').body.d.map(([k]) => k), ['file', 'audio']);
assert.ok(find(byId.get('makeResults'), (n) => n.tagName === 'VIDEO' && n.attrs.src.endsWith('swapped.mp4')).length === 1);
byId.get('makeTabs').children[15].click(); // Extract audio: results as an audio player
named('file').files = [{ name: 'talk.mp4' }]; goButton().click(); await settle();
assert.equal(find(byId.get('makeResults'), (n) => n.tagName === 'AUDIO').length, 1);
byId.get('makeTabs').children[12].click(); goButton().click(); await settle(); // back on the quote card (its settings were remembered)
// the fifteen quick tools all post to /api/quick/<id> with the field names the server expects
const quickTabs = Array.from(byId.get('makeTabs').children).slice(18, 33);
assert.equal(quickTabs.length, 15);
const quickIds = ['mute', 'rotate', 'resize', 'fps', 'reverse', 'volume', 'watermark', 'crop', 'grade', 'cleanup', 'waveform', 'still', 'music', 'join', 'pip'];
for (const [k, id] of quickIds.entries()) {
  const tab = context.window.SkellyMake.TABS.find((x) => x.id === id);
  assert.equal(tab.endpoint, '/api/quick/' + id); assert.ok(tab.fields.length >= 1 && tab.go && tab.blurb.length > 20, id);
}
// the second batch of twenty-five, and the group filter that keeps sixty tabs manageable
const second = context.window.SkellyMake.TABS.slice(33, 58);
assert.equal(second.length, 25);
for (const tab of second) {
  assert.equal(tab.endpoint, '/api/quick/' + tab.id); assert.ok(tab.fields.length >= 1 && tab.go && tab.blurb.length > 20, tab.id);
  assert.ok(tab.fields.some((f) => f.type === 'file') || tab.id === 'banner', tab.id + ' takes a file');
}
assert.equal(new Set(context.window.SkellyMake.TABS.map((t) => t.id)).size, 61, 'no duplicate tab ids');
const groupBar = byId.get('makeGroups');
assert.deepEqual(groupBar.children.map((n) => n.textContent), ['All', 'Create', 'Edit video', 'Audio', 'Pictures']);
const visibleTabs = () => byId.get('makeTabs').children.filter((n) => !n.classList.contains('hidden')).length;
assert.equal(visibleTabs(), 61);
groupBar.children[3].click(); // Audio
assert.ok(visibleTabs() > 10 && visibleTabs() < 61, 'only audio tools stay');
assert.ok(byId.get('makeTabs').children.filter((n) => !n.classList.contains('hidden')).some((n) => n.textContent === 'Pitch shift'));
groupBar.children[0].click();
assert.equal(visibleTabs(), 61);
quickTabs[0].click(); // (back to the Remove audio tab used by the next check)
const slides = byId.get('makeTabs').children[33 + 6]; slides.click();
named('images').files = [{ name: '1.png' }, { name: '2.png' }]; goButton().click(); await settle();
assert.deepEqual(calls.find((c) => c.path === '/api/quick/slides').body.d.map(([k]) => k), ['images', 'images', 'each', 'shape'], 'list field repeats; optional song not sent');
quickTabs[0].click();
quickTabs[13].click(); // Join videos: several files under one field
named('videos').files = [{ name: 'a.mp4' }, { name: 'b.mp4' }, { name: 'c.mp4' }]; goButton().click(); await settle();
assert.deepEqual(calls.find((c) => c.path === '/api/quick/join').body.d.map(([k]) => k), ['videos', 'videos', 'videos']);
quickTabs[6].click(); // Watermark: the logo is optional
named('video').files = [{ name: 'a.mp4' }]; goButton().click(); await settle();
assert.deepEqual(calls.find((c) => c.path === '/api/quick/watermark').body.d.map(([k]) => k), ['video', 'corner', 'size', 'opacity'], 'no logo file sent when none is chosen');
quickTabs[12].click(); // Background music: the check box is sent as true or false
named('video').files = [{ name: 'a.mp4' }]; named('music').files = [{ name: 'm.mp3' }]; goButton().click(); await settle();
assert.equal(calls.find((c) => c.path === '/api/quick/music').body.d.find(([k]) => k === 'duck')[1], 'true');
quickTabs[0].click(); goButton().click(); await settle();
assert.ok(!calls.some((c) => c.path === '/api/quick/mute'), 'a file is required');
byId.get('makeTabs').children[12].click(); goButton().click(); await settle(); // back on the quote card so its settings are the ones remembered
// search, drag and drop, file sizes and handing a result to another tool
const search = byId.get('makeSearch'); search.value = 'pitch'; search.fire('input');
const shownNow = () => byId.get('makeTabs').children.filter((n) => !n.classList.contains('hidden')).map((n) => n.textContent);
assert.ok(shownNow().includes('Pitch shift') && shownNow().length < 8, 'search narrows the tabs: ' + shownNow().join());
search.value = ''; search.fire('input'); assert.equal(shownNow().length, 61);
context.window.SkellyMake.dropFiles([{ name: 'cover.png', type: 'image/png', size: 2048 }]);
const pic = named('image') || named('images');
assert.ok(pic && pic.files[0].name === 'cover.png', 'a dropped picture lands in a picture tool (the one used last)');
assert.ok(find(byId.get('makeForm'), (n) => String(n.className || '').includes('make-picked') && n.textContent.includes('cover.png (2 KB)')).length === 1, 'the chosen file and its size are shown');
context.window.SkellyMake.dropFiles([{ name: 'song.mp3', type: 'audio/mpeg', size: 3 * 1048576 }]);
assert.ok(find(byId.get('makeForm'), (n) => n.files && n.files[0] && n.files[0].name === 'song.mp3').length === 1, 'a dropped song lands in an audio-accepting tool');
const toastsBefore = byId.get('toast') ? byId.get('toast').textContent : '';
context.window.SkellyMake.dropFiles([{ name: 'notes.txt', type: 'text/plain' }]);
assert.ok(context.window.SkellyMake.fitsKind(context.window.SkellyMake.TABS.find((t) => t.id === 'pitch'), 'video'), 'audio tools accept a video too');
assert.ok(!context.window.SkellyMake.fitsKind(context.window.SkellyMake.TABS.find((t) => t.id === 'pitch'), 'image'));
byId.get('makeTabs').children[12].click(); goButton().click(); await settle(); // back on the quote card so its settings are the ones remembered
// the last settings come back when the overlay is reopened, and the tab itself is remembered
byId.get('makeClose').click();
const savedMemory = JSON.parse(context.localStorage.getItem('skellymotion.make.v1'));
assert.equal(savedMemory.tab, 'quote'); assert.equal(savedMemory.values.trim.end, '5'); assert.equal(savedMemory.values.gif.seconds, '3');
assert.ok(!('file' in savedMemory.values.trim), 'files are never stored');
context.window.SkellyMake.open();
assert.equal(named('quote').value, 'Tune less, play more.'); assert.equal(named('aspect').value, 'portrait');
byId.get('makeTabs').children[9].click();
assert.equal(named('start').value, '2'); assert.equal(named('end').value, '5');
// broken storage is ignored, not fatal
context.localStorage.setItem('skellymotion.make.v1', '{nonsense');
byId.get('makeTabs').children[0].click(); byId.get('makeTabs').children[9].click();
assert.equal(named('end').value, '0', 'bad saved data falls back to defaults');
// Clear all in Recent
const clearAll = find(byId.get('makeRecent'), (n) => n.attrs && n.attrs.id === 'makeClearAll')[0];
assert.ok(clearAll, 'Recent offers Clear all');
clearAll.click(); await settle();
assert.ok(calls.some((c) => c.path === '/api/makes' && c.method === 'DELETE'));
assert.ok(toasts.some(([m]) => /removed, 1 still rendering/.test(m)));
assert.equal(byId.get('makeRecent').children.length, 0, 'the list is empty afterwards');
byId.get('makeClose').click(); assert.ok(byId.get('makeOverlay').classList.contains('hidden'));

// ---- Conversational settings preview: no automatic render ----------------
byId.get('aeMusic').checked=true;
byId.get('aeInstruction').value='music off';
const beforeInstructionJobs=calls.filter(c=>c.path.endsWith('/autoedit')).length;
byId.get('aeSuggest').click(); await settle();
assert.match(byId.get('aeSuggested').textContent,/music/);
assert.equal(byId.get('aeMusic').checked,true);
byId.get('aeApplySuggestion').click();
assert.equal(byId.get('aeMusic').checked,false);
assert.equal(calls.filter(c=>c.path.endsWith('/autoedit')).length,beforeInstructionJobs);

// ---- cancelling a running job from the shared status line ----------------------------------------------------------------------
const statusNode = byId.get('makeStatus');
context.window.SkellyUI.showStatus(statusNode, { id: 'abc123', status: 'rendering', stage: 'mv_render', progress: 40 });
assert.match(statusNode.textContent, /Cutting to the beat · 40%/);
const cancelButton = find(statusNode, (n) => n.tagName === 'BUTTON')[0];
assert.equal(cancelButton.textContent, 'Cancel'); cancelButton.click(); await settle();
assert.ok(calls.some((c) => c.method === 'POST' && c.path === '/api/jobs/abc123/cancel'), 'cancel request sent');
context.window.SkellyUI.showStatus(statusNode, { id: 'abc123', status: 'rendering', stage: 'mv_render', progress: 55 });
const again = find(statusNode, (n) => n.tagName === 'BUTTON')[0];
assert.equal(again.textContent, 'Cancelling…'); assert.ok('disabled' in again.attrs, 'no second cancel while it is stopping');
context.window.SkellyUI.showStatus(statusNode, { id: 'abc123', status: 'done', stage: 'complete', progress: 100 });
assert.equal(find(statusNode, (n) => n.tagName === 'BUTTON').length, 0, 'no cancel button on a finished job');

// ---- errors surface instead of hanging --------------------------------------------------
byId.get('clipRegen').click(); await settle();
assert.ok(toasts.some(([m, e]) => e && /unexpected/.test(m)), 'API errors become toasts');
console.log('SkellyMotion autonomous UI smoke tests passed: Clip Studio, Autopilot, Shorts, Auto-edit, presets, post text, proofreading, translated clips, B-roll, brand kit, Make overlay, watch folder, safe text, errors.');
