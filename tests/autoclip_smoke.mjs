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
for (const needed of ['autoRunBtn', 'autopilotFromReview', 'openClipStudio', 'openClipStudioPanel', 'clipStudio', 'clipCards', 'autoShortList'])
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
async function fakeFetch(path, options = {}) {
  const body = options.body && typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
  calls.push({ path, method: options.method || 'GET', body });
  const ok = (data) => ({ ok: true, status: 200, json: async () => data });
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
  return { ok: false, status: 404, json: async () => ({ detail: 'unexpected ' + path }) };
}
const toasts = []; let reloaded = null; const panels = [];
const editorState = { id: 'a'.repeat(32), lines: [{ id: 'l1', text: 'hi there', start: 1, end: 3, words: [] }], settings: { font: 'Arial' } };
const bridge = { state: () => editorState, toast: (m, e) => toasts.push([m, e]), panel: (n) => panels.push(n),
  audio: () => null, reloadProject: async (id) => { reloaded = id; } };
const keyListeners = []; const parkedTimers = [];
const context = {
  window: {}, console, URL, FormData: class { constructor() { this.d = []; } append(k, v) { this.d.push([k, v]); } },
  // Short waits (job polling) run at once; long ones (the 3 s watch refresh) are parked like a real timer would be.
  setTimeout: (fn, ms) => { if (ms >= 3000) { parkedTimers.push(fn); return 0; } fn(); return 0; }, clearTimeout() {},
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
// Clip Studio must remain reachable after the welcome overlay has been dismissed.
byId.get('clipStudioClose').click();
assert.ok(byId.get('clipStudio').classList.contains('hidden'), 'studio closes');
byId.get('openClipStudioPanel').click(); await settle();
assert.ok(!byId.get('clipStudio').classList.contains('hidden'), 'Autopilot panel reopens Clip Studio');

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
byId.get('autoEditRun').click(); await settle();
const edited = calls.find((c) => c.path.endsWith('/autoedit'));
assert.deepEqual(edited.body, { trim_silence: true, loudness: true, watermark: true, endcard: true, captions: true, zoom: 'medium', resolution: '1080p', shorts: 3,
  sfx: true, callouts: true, chapter_titles: true, music: true, intro_outro: true, intro_card: false });
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

// ---- errors surface instead of hanging --------------------------------------------------
byId.get('clipRegen').click(); await settle();
assert.ok(toasts.some(([m, e]) => e && /unexpected/.test(m)), 'API errors become toasts');
console.log('SkellyMotion autonomous UI smoke tests passed: Clip Studio, Autopilot, Shorts, Auto-edit, brand kit, translation, hook ideas, watch folder, safe text, errors.');
