/* SkellyMotion autonomous tools: Autopilot, song Shorts and the long-video Clip Studio.
 * Self-contained so the lyric editor (app.js) stays untouched apart from window.SkellyBridge.
 * All user/transcript/AI text is inserted with textContent, never innerHTML. */
(() => {
'use strict';
const $ = (id) => document.getElementById(id);
const bridge = () => window.SkellyBridge || null;
const toast = (message, error = false) => { const b = bridge(); if (b && b.toast) b.toast(message, error); };

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let reason; try { reason = (await response.json()).detail; } catch (e) { /* not JSON */ }
    throw new Error(typeof reason === 'string' ? reason : 'Request failed (' + response.status + ')');
  }
  return response.json();
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? '' : value);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined) node.append(kid);
  return node;
}
const clock = (s) => { s = Math.max(0, Number(s) || 0); return Math.floor(s / 60) + ':' + (s % 60).toFixed(1).padStart(4, '0'); };
const STAGES = {
  preparing: 'Getting ready', autopilot_prepare: 'Preparing lyrics', autopilot_full_render: 'Rendering the full video',
  autopilot_shorts: 'Picking and rendering Shorts', encoding: 'Encoding', checking_encoder: 'Checking encoder',
  cpu_fallback: 'Switching to CPU encoder', cached: 'Reusing an identical earlier render', analyzing_video: 'Analyzing video',
  complete: 'Done', error: 'Failed'
};
const stageText = (job) => STAGES[job.stage] || String(job.stage || '').replace(/_/g, ' ').replace(/^short (\d+) of (\d+)$/, 'Short $1 of $2')
  .replace(/^clip (\d+) of (\d+)$/, 'Clip $1 of $2');

async function runJob(jobId, onUpdate) {
  for (let i = 0; i < 7200; i++) {
    const job = await api('/api/jobs/' + encodeURIComponent(jobId));
    onUpdate(job);
    if (job.status === 'done') return job;
    if (job.status === 'error') throw new Error(job.error || 'The job failed');
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error('Timed out waiting for the job');
}
function showStatus(node, job) {
  node.classList.remove('hidden');
  node.textContent = stageText(job) + ' · ' + (job.progress || 0) + '%' + (job.encoder_used ? ' · ' + job.encoder_used : '');
}
function copyButton(label, getText) {
  return el('button', { type: 'button', class: 'tiny-btn', text: label, onclick: async (e) => {
    try { await navigator.clipboard.writeText(getText()); e.target.textContent = 'Copied'; setTimeout(() => { e.target.textContent = label; }, 1400); }
    catch (err) { toast('Copy failed. Select the text and copy it manually.', true); }
  } });
}

/* ---------- finished-file list, shared by Shorts and clips ---------- */
function renderOutputs(container, items, kind, projectId, full) {
  container.replaceChildren();
  if (full) container.append(el('div', { class: 'auto-result' },
    el('strong', { text: 'Full video' }), el('video', { controls: true, preload: 'metadata', src: full }),
    el('a', { class: 'download-btn', href: full, text: 'Download full video' })));
  for (const item of items) {
    const tags = (item.tags || []).map((t) => '#' + String(t).replace(/\s+/g, '')).join(' ');
    container.append(el('div', { class: 'auto-result' },
      el('strong', { text: kind + ' ' + item.n + ' · ' + clock(item.start) + ' to ' + clock(item.end) }),
      el('video', { controls: true, preload: 'metadata', src: item.url }),
      el('div', { class: 'auto-meta' }, el('b', { text: item.title || item.hook || '' }), el('small', { text: item.description || '' }), el('small', { text: tags })),
      el('div', { class: 'auto-actions' },
        el('a', { class: 'tiny-btn', href: item.url, download: '', text: 'Download' }),
        copyButton('Copy title', () => item.title || ''),
        copyButton('Copy description + tags', () => (item.description || '') + '\n\n' + tags))));
  }
  container.append(el('a', { class: 'download-btn', href: '/api/projects/' + projectId + '/bundle.zip', text: 'Download everything (.zip)' }));
}

/* ---------- Song mode: Autopilot + Shorts in the editor ---------- */
const song = { picks: [], busy: false, stop: null };
function projectLines() { const b = bridge(); const s = b && b.state(); return s && s.lines && s.lines.length ? s.lines : undefined; }

async function runAutopilot() {
  const b = bridge(); const id = b && b.state().id;
  if (!id) { toast('Open or upload a song first.', true); return; }
  if (song.busy) return;
  song.busy = true;
  const status = $('autoStatus'); const buttons = [$('autoRunBtn'), $('autopilotFromReview')];
  buttons.forEach((x) => { x.disabled = true; });
  b.panel('auto');
  try {
    const { job_id } = await post('/api/projects/' + id + '/autopilot', {
      preset: $('autoPreset').value, aspect: $('autoAspect').value, shorts: Number($('autoShortCount').value),
      hooks: $('autoHooks').checked, lines: projectLines() });
    const job = await runJob(job_id, (j) => showStatus(status, j));
    const out = job.outputs || {};
    status.textContent = 'Done. ' + (out.shorts ? out.shorts.length + ' Short(s) and ' : '') + 'the full video are ready.' +
      (out.auto_confirmed ? ' Lyrics were accepted without review, so skim them in the editor.' : '');
    renderOutputs($('autoResults'), out.shorts || [], 'Short', id, out.full);
    await b.reloadProject(id);
    b.panel('auto');
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Autopilot stopped: ' + e.message; toast(e.message, true); }
  finally { song.busy = false; buttons.forEach((x) => { x.disabled = false; }); }
}

function stopPreview() { if (song.stop) { song.stop(); song.stop = null; } }
function previewSegment(start, end) {
  const b = bridge(); const audio = b && b.audio(); if (!audio) return;
  stopPreview();
  const onTime = () => { if (audio.currentTime >= end) { audio.pause(); stopPreview(); } };
  song.stop = () => audio.removeEventListener('timeupdate', onTime);
  audio.addEventListener('timeupdate', onTime);
  audio.currentTime = start; audio.play().catch(() => stopPreview());
}

function pickCard(pick, index) {
  const start = el('input', { type: 'number', step: '0.1', min: '0', value: pick.start.toFixed(1), 'aria-label': 'Start seconds' });
  const end = el('input', { type: 'number', step: '0.1', min: '0', value: pick.end.toFixed(1), 'aria-label': 'End seconds' });
  const hook = el('input', { type: 'text', maxlength: '80', value: pick.hook || '', placeholder: 'Hook text (optional)', 'aria-label': 'Hook text' });
  const include = el('input', { type: 'checkbox', checked: true, 'aria-label': 'Include this Short' });
  const card = el('div', { class: 'auto-card' },
    el('label', { class: 'auto-card-top' }, include, el('b', { text: 'Short ' + (index + 1) }), el('span', { class: 'auto-score', text: 'score ' + pick.score.toFixed(2) })),
    el('small', { class: 'auto-reasons', text: pick.reasons.join(' · ') }),
    el('div', { class: 'auto-times' }, start, el('span', { text: 'to' }), end,
      el('button', { type: 'button', class: 'tiny-btn', text: '▶', title: 'Listen to this section', onclick: () => previewSegment(Number(start.value), Number(end.value)) })),
    hook);
  card.read = () => ({ include: include.checked, start: Number(start.value), end: Number(end.value), hook: hook.value, score: pick.score, reasons: pick.reasons });
  return card;
}
let pickCards = [];
async function findShorts() {
  const b = bridge(); const id = b && b.state().id; if (!id) { toast('Open or upload a song first.', true); return; }
  const button = $('autoFindShorts'); button.disabled = true; button.textContent = 'Analyzing the song…';
  try {
    const { suggestions } = await post('/api/projects/' + id + '/shorts/suggestions', { lines: projectLines(), count: 4 });
    pickCards = suggestions.map(pickCard);
    $('autoShortList').replaceChildren(...pickCards);
    $('autoRenderShorts').classList.toggle('hidden', !pickCards.length);
    if (!pickCards.length) toast('No good Short-length sections were found.', true);
  } catch (e) { toast(e.message, true); }
  finally { button.disabled = false; button.textContent = 'Find the best Shorts in this song'; }
}
async function renderPickedShorts() {
  const b = bridge(); const id = b && b.state().id; if (!id || song.busy) return;
  const chosen = pickCards.map((c) => c.read()).filter((c) => c.include);
  if (!chosen.length) { toast('Tick at least one Short.', true); return; }
  song.busy = true; const button = $('autoRenderShorts'); button.disabled = true;
  const status = $('autoStatus');
  try {
    const { job_id } = await post('/api/projects/' + id + '/shorts/render', {
      segments: chosen, settings: b.state().settings, lines: projectLines() });
    const job = await runJob(job_id, (j) => showStatus(status, j));
    status.textContent = 'Done. ' + job.outputs.shorts.length + ' Short(s) rendered.';
    renderOutputs($('autoResults'), job.outputs.shorts, 'Short', id, null);
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Render stopped: ' + e.message; toast(e.message, true); }
  finally { song.busy = false; button.disabled = false; }
}

/* ---------- Clip Studio: long video to Shorts ---------- */
const studio = { id: null, timer: null, busy: false, cards: [], caps: null };
function setStep(name) {
  for (const step of ['clipUploadStep', 'clipProgressStep', 'clipReadyStep']) $(step).classList.toggle('hidden', step !== name);
}
function closeStudio() { clearTimeout(studio.timer); studio.timer = null; $('clipStudio').classList.add('hidden'); }
async function loadCaps() {
  if (studio.caps) return studio.caps;
  try { studio.caps = await api('/api/clips/capabilities'); } catch (e) { studio.caps = {}; }
  const ai = $('clipUseAi'); ai.disabled = !studio.caps.ai_rerank;
  if (!studio.caps.ai_rerank) ai.checked = false;
  if (studio.caps.max_source_mb) $('clipLimitNote').textContent = 'MP4, MOV, MKV, WebM · up to ' + studio.caps.max_source_mb + ' MB / ' + studio.caps.max_source_minutes + ' min';
  return studio.caps;
}
async function openStudio(id) {
  $('clipStudio').classList.remove('hidden');
  await loadCaps();
  if (id) { studio.id = id; attach(); } else { studio.id = null; setStep('clipUploadStep'); }
}
async function uploadSource(file) {
  if (!file) return;
  setStep('clipProgressStep'); $('clipProgressTitle').textContent = 'Uploading ' + file.name; $('clipMeter').style.width = '4%';
  const form = new FormData();
  form.append('file', file); form.append('language', $('clipLanguage').value);
  form.append('recognition', $('clipRecognition').value); form.append('use_ai', $('clipUseAi').checked ? 'true' : 'false');
  try { const made = await api('/api/clip-sources', { method: 'POST', body: form }); studio.id = made.id; attach(); }
  catch (e) { toast(e.message, true); setStep('clipUploadStep'); }
}
async function attach() {
  clearTimeout(studio.timer);
  const id = studio.id; if (!id) return;
  try {
    const project = await api('/api/projects/' + id);
    if (studio.id !== id) return;
    $('clipStudioTitle').textContent = project.title || 'Long video to Shorts';
    if (project.status === 'ready') { showReady(project); return; }
    if (project.status === 'failed') { setStep('clipUploadStep'); toast(project.clip_error || 'Could not analyze this video.', true); return; }
    setStep('clipProgressStep');
    const analyzing = project.status === 'analyzing';
    $('clipProgressTitle').textContent = analyzing ? 'Finding the best moments…' : 'Transcribing speech…';
    $('clipMeter').style.width = (analyzing ? 96 : Math.max(4, Number(project.transcription_progress) || 4)) + '%';
    $('clipProgressNote').textContent = analyzing ? 'Scoring transcript, loudness and scene changes.' : 'Progress measures analyzed audio, not time remaining.';
    studio.timer = setTimeout(attach, 1500);
  } catch (e) { toast(e.message, true); studio.timer = setTimeout(attach, 4000); }
}
function clipCard(clip, index) {
  const src = '/api/projects/' + studio.id + '/source';
  const start = el('input', { type: 'number', step: '0.1', min: '0', value: clip.start.toFixed(1), 'aria-label': 'Start seconds' });
  const end = el('input', { type: 'number', step: '0.1', min: '0', value: clip.end.toFixed(1), 'aria-label': 'End seconds' });
  const video = el('video', { controls: true, preload: 'metadata', src: src + '#t=' + clip.start + ',' + clip.end });
  const retarget = () => { video.src = src + '#t=' + Number(start.value) + ',' + Number(end.value); };
  start.addEventListener('change', retarget); end.addEventListener('change', retarget);
  const hook = el('input', { type: 'text', maxlength: '80', value: clip.hook || '', 'aria-label': 'Hook text' });
  const title = el('input', { type: 'text', maxlength: '100', value: clip.title || '', 'aria-label': 'Title' });
  const desc = el('textarea', { rows: '3', maxlength: '500', 'aria-label': 'Description' }); desc.value = clip.description || '';
  const tags = el('input', { type: 'text', value: (clip.tags || []).join(', '), 'aria-label': 'Tags' });
  const include = el('input', { type: 'checkbox', checked: index < 3, 'aria-label': 'Include this clip' });
  include.addEventListener('change', updateRenderCount);
  const card = el('div', { class: 'clip-card' }, video,
    el('label', { class: 'auto-card-top' }, include, el('b', { text: 'Clip ' + (index + 1) }), el('span', { class: 'auto-score', text: 'score ' + clip.score.toFixed(2) })),
    el('small', { class: 'auto-reasons', text: (clip.reasons || []).join(' · ') }),
    el('div', { class: 'auto-times' }, start, el('span', { text: 'to' }), end),
    el('label', { class: 'clip-field' }, 'Hook (first 1.5 s)', hook), el('label', { class: 'clip-field' }, 'Title', title),
    el('label', { class: 'clip-field' }, 'Description', desc), el('label', { class: 'clip-field' }, 'Tags', tags));
  card.read = () => ({ include: include.checked, start: Number(start.value), end: Number(end.value), hook: hook.value, title: title.value,
    description: desc.value, tags: tags.value.split(',').map((t) => t.trim()).filter(Boolean), score: clip.score, reasons: clip.reasons || [] });
  return card;
}
function updateRenderCount() {
  const n = studio.cards.filter((c) => c.read().include).length;
  $('clipRender').textContent = 'Render selected (' + n + ')'; $('clipRender').disabled = !n || studio.busy;
}
function showCards(suggestions) {
  studio.cards = suggestions.map(clipCard);
  $('clipCards').replaceChildren(...studio.cards);
  updateRenderCount();
}
function showReady(project) {
  setStep('clipReadyStep'); showCards(project.clip_suggestions || []);
  if (!(project.clip_suggestions || []).length) toast('No clip-length sections were found. Try a lower minimum.', true);
}
async function regenerate() {
  const button = $('clipRegen'); button.disabled = true;
  try {
    const { suggestions } = await post('/api/projects/' + studio.id + '/clips/suggestions', {
      count: Number($('clipSuggestCount').value), min_seconds: Number($('clipMin').value), max_seconds: Number($('clipMax').value),
      use_ai: $('clipUseAi').checked });
    showCards(suggestions);
  } catch (e) { toast(e.message, true); } finally { button.disabled = false; }
}
async function renderClips() {
  const chosen = studio.cards.map((c) => c.read()).filter((c) => c.include);
  if (!chosen.length || studio.busy) return;
  studio.busy = true; updateRenderCount();
  const status = $('clipStatus');
  try {
    const { job_id } = await post('/api/projects/' + studio.id + '/clips/render', { clips: chosen, reframe: $('clipReframe').value });
    const job = await runJob(job_id, (j) => showStatus(status, j));
    status.textContent = 'Done. ' + job.outputs.clips.length + ' clip(s) rendered.';
    renderOutputs($('clipResults'), job.outputs.clips, 'Clip', studio.id, null);
    $('clipResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Render stopped: ' + e.message; toast(e.message, true); }
  finally { studio.busy = false; updateRenderCount(); }
}

/* ---------- wiring (every element is optional so a page without them still loads) ---------- */
const on = (id, type, fn) => { const node = $(id); if (node) node.addEventListener(type, fn); };
on('autoRunBtn', 'click', runAutopilot);
on('autopilotFromReview', 'click', runAutopilot);
on('autoFindShorts', 'click', findShorts);
on('autoRenderShorts', 'click', renderPickedShorts);
on('openClipStudio', 'click', () => openStudio(null));
on('clipStudioClose', 'click', closeStudio);
on('clipPick', 'click', () => $('clipFile').click());
on('clipFile', 'change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadSource(f); e.target.value = ''; });
on('clipRegen', 'click', regenerate);
on('clipRender', 'click', renderClips);
document.addEventListener('keydown', (e) => { const s = $('clipStudio'); if (e.key === 'Escape' && s && !s.classList.contains('hidden')) closeStudio(); });

window.SkellyClips = { open: openStudio, close: closeStudio };
})();
