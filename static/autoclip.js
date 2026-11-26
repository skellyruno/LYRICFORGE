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

// Local Director: transcript cuts, semantic filename matching, cached scene renders.
let directorBusy=false;
function directorPayload(){const b=bridge();return {preset:$('directorPreset').value,brand:$('directorBrand').value,preview:$('directorPreview').checked,music:$('directorMusic').checked,lines:projectLines(),settings:b.state().settings};}
function directorStatus(message,error=false){const node=$('directorStatus');node.classList.remove('hidden');node.textContent=message;if(error)toast(message,true);}
function directorSceneList(plan){const node=$('directorScenes');node.replaceChildren(...(plan.scenes||[]).map((s,i)=>el('div',{class:'director-scene'},el('span',{text:clock(s.start)+'–'+clock(s.end)}),el('b',{text:(i+1)+'. '+s.type.replace('_',' ')}),el('small',{text:s.asset_name||s.text||''}))));}
async function refreshDirectorAssets(id){const data=await api('/api/projects/'+id+'/director/assets');if(bridge()?.state().id!==id)return;$('directorAssetsList').replaceChildren(...data.assets.map(a=>el('div',{class:'director-scene'},el('b',{text:a.name}),el('small',{text:a.kind}))));}
async function uploadDirectorAssets(){const id=bridge()?.state().id;if(!id){toast('Open a song or voiceover first.',true);$('directorAssets').value='';return;}if(directorBusy)return;directorBusy=true;try{const files=Array.from($('directorAssets').files||[]);for(let i=0;i<files.length;i++){directorStatus('Importing visual '+(i+1)+' / '+files.length);const form=new FormData();form.append('file',files[i]);form.append('description',$('directorAssetDescription').value||'');await api('/api/projects/'+id+'/director/assets',{method:'POST',body:form});}await refreshDirectorAssets(id);directorStatus('Assets ready.');}catch(e){directorStatus(e.message,true);}finally{directorBusy=false;$('directorAssets').value='';}}
async function runDirector(render){const id=bridge()?.state().id;if(!id){toast('Open a song or voiceover first.',true);return;}if(directorBusy||song.busy)return;directorBusy=true;for(const k of ['directorPlan','directorRun'])$(k).disabled=true;try{await refreshDirectorAssets(id);directorStatus('Planning with the local director…');const result=await post('/api/projects/'+id+'/director/'+(render?'render':'plan'),directorPayload());directorSceneList(result.plan||result);if(!render){directorStatus(result.scenes.length+' scenes planned. '+(result.warnings||[]).join(' '));return;}const job=await runJob(result.job_id,j=>{showStatus($('directorStatus'),j);if(j.status==='rendering')$('directorStatus').append(' ',el('button',{type:'button',class:'tiny-btn',text:'Cancel',onclick:async()=>{try{await post('/api/jobs/'+encodeURIComponent(result.job_id)+'/cancel',{});directorStatus('Cancellation requested…');}catch(e){directorStatus(e.message,true);}}}));});if(bridge()?.state().id!==id)return;const out=job.outputs;directorStatus('Done · '+out.scenes+' scenes · '+out.cached+' reused');$('directorResult').replaceChildren(el('a',{class:'download-btn',href:out.video,download:'',text:'Download directed MP4'}),el('a',{class:'wide-ghost',href:out.plan,download:'',text:'Download scene plan JSON'}));}catch(e){directorStatus('Director stopped: '+e.message,true);}finally{directorBusy=false;for(const k of ['directorPlan','directorRun'])$(k).disabled=false;}}

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
function closeStudio() { clearTimeout(watch.timer); clearTimeout(studio.timer); studio.timer = null; $('clipStudio').classList.add('hidden'); }
async function loadCaps() {
  if (studio.caps) return studio.caps;
  try { studio.caps = await api('/api/clips/capabilities'); } catch (e) { studio.caps = {}; }
  const ai = $('clipUseAi'); ai.disabled = !studio.caps.ai_rerank;
  if (!studio.caps.ai_rerank) ai.checked = false;
  const watchBox = $('watchBox'); if (watchBox) watchBox.classList.toggle('hidden', !studio.caps.watch);
  if (studio.caps.max_source_mb) $('clipLimitNote').textContent = 'MP4, MOV, MKV, WebM · up to ' + studio.caps.max_source_mb + ' MB / ' + studio.caps.max_source_minutes + ' min';
  return studio.caps;
}
async function openStudio(id) {
  $('clipStudio').classList.remove('hidden');
  await loadCaps();
  if (studio.caps.watch) refreshWatch();
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
    el('label', { class: 'clip-field' }, 'Hook (first 1.5 s)', hook), ideaRow(clip, hook, title),
    el('label', { class: 'clip-field' }, 'Title', title),
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
    const { job_id } = await post('/api/projects/' + studio.id + '/clips/render', { clips: chosen, reframe: $('clipReframe').value,
      polish: { loudness: $('clipLoud').checked, trim_silence: $('clipTrim').checked, watermark: $('clipWatermark').checked } });
    const job = await runJob(job_id, (j) => showStatus(status, j));
    status.textContent = 'Done. ' + job.outputs.clips.length + ' clip(s) rendered.';
    renderOutputs($('clipResults'), job.outputs.clips, 'Clip', studio.id, null);
    $('clipResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Render stopped: ' + e.message; toast(e.message, true); }
  finally { studio.busy = false; updateRenderCount(); }
}


/* ---------- Hook ideas (AI, opt-in) ---------- */
function ideaRow(clip, hookInput, titleInput) {
  const chips = el('div', { class: 'idea-chips' });
  const button = el('button', { type: 'button', class: 'tiny-btn', text: 'Hook ideas', onclick: async () => {
    button.disabled = true; button.textContent = 'Thinking…';
    try {
      const { variants } = await post('/api/projects/' + studio.id + '/clips/variants', { text: clip.text || clip.hook || '', count: 3 });
      chips.replaceChildren(...variants.map((v) => el('button', { type: 'button', class: 'idea-chip', title: v.title, text: v.hook,
        onclick: () => { hookInput.value = v.hook; titleInput.value = v.title; } })));
    } catch (e) { toast(e.message, true); } finally { button.disabled = false; button.textContent = 'Hook ideas'; }
  } });
  const row = el('div', { class: 'idea-row' }, button, chips);
  if (!(studio.caps && studio.caps.ai_text)) row.classList.add('hidden');
  return row;
}

/* ---------- Brand kit ---------- */
const ASSETS = [['Music', 'has_music'], ['Intro', 'has_intro'], ['Outro', 'has_outro']];
function fillBrand(b) {
  $('brName').value = b.name; $('brFont').value = b.font;
  $('brAccent').value = b.accent.toLowerCase(); $('brBg').value = b.bg.toLowerCase(); $('brText').value = b.text.toLowerCase();
  $('brWmOn').checked = b.watermark.enabled; $('brWmPos').value = b.watermark.position;
  $('brWmOpacity').value = b.watermark.opacity; $('brWmSize').value = b.watermark.size;
  $('brEcOn').checked = b.endcard.enabled; $('brEcSecs').value = b.endcard.seconds;
  $('brEcTitle').value = b.endcard.title; $('brEcSub').value = b.endcard.subtitle; $('brEcUrl').value = b.endcard.url;
  const img = $('brLogoImg');
  if (b.has_logo) img.setAttribute('src', '/api/brand/logo?v=' + Date.now());
  img.classList.toggle('hidden', !b.has_logo); $('brLogoClear').classList.toggle('hidden', !b.has_logo);
  $('brLogoPick').textContent = b.has_logo ? 'Replace logo' : 'Upload logo';
  for (const [kind, key] of ASSETS) {
    $('br' + kind + 'Name').textContent = b[key] ? 'Added' : 'None';
    $('br' + kind + 'Clear').classList.toggle('hidden', !b[key]); $('br' + kind + 'Pick').textContent = b[key] ? 'Replace' : 'Choose';
  }
  $('brMusicVol').value = b.audio.music_volume; $('brSfxVol').value = b.audio.sfx_volume;
}
function readBrand() {
  return { name: $('brName').value, font: $('brFont').value, accent: $('brAccent').value, bg: $('brBg').value, text: $('brText').value,
    watermark: { enabled: $('brWmOn').checked, position: $('brWmPos').value, opacity: Number($('brWmOpacity').value), size: Number($('brWmSize').value) },
    audio: { music_volume: Number($('brMusicVol').value), sfx_volume: Number($('brSfxVol').value) },
    endcard: { enabled: $('brEcOn').checked, seconds: Number($('brEcSecs').value), title: $('brEcTitle').value, subtitle: $('brEcSub').value, url: $('brEcUrl').value } };
}
async function openBrand() {
  try { const { brand } = await api('/api/brand'); fillBrand(brand); $('brandModal').classList.remove('hidden'); }
  catch (e) { toast(e.message, true); }
}
async function saveBrand() {
  try { const { brand } = await api('/api/brand', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brand: readBrand() }) });
    fillBrand(brand); $('brandModal').classList.add('hidden'); toast('Brand kit saved'); }
  catch (e) { toast(e.message, true); }
}
// After a server-side change (logo or clips), show the new file flags but keep whatever the person has typed.
function keepDraft(brand) { fillBrand({ ...brand, ...readBrand(), has_logo: brand.has_logo, has_music: brand.has_music,
  has_intro: brand.has_intro, has_outro: brand.has_outro }); }
async function uploadAsset(kind, file) {
  if (!file) return;
  const form = new FormData(); form.append('file', file);
  try { const { brand } = await api('/api/brand/asset/' + kind, { method: 'POST', body: form }); keepDraft(brand); toast('Saved'); }
  catch (e) { toast(e.message, true); }
}
async function clearAsset(kind) {
  try { const { brand } = await api('/api/brand/asset/' + kind, { method: 'DELETE' }); keepDraft(brand); }
  catch (e) { toast(e.message, true); }
}
async function uploadLogo(file) {
  if (!file) return;
  const form = new FormData(); form.append('file', file);
  try { const { brand } = await api('/api/brand/logo', { method: 'POST', body: form }); keepDraft(brand); }
  catch (e) { toast(e.message, true); }
}
async function clearLogo() {
  try { const { brand } = await api('/api/brand/logo', { method: 'DELETE' }); keepDraft(brand); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Auto-edit (the one-button video editor) ---------- */
function labeledText(title, text, multiline) {
  const field = multiline ? el('textarea', { rows: '7', readonly: true }) : el('input', { type: 'text', readonly: true });
  field.value = text;
  return el('div', { class: 'ae-field' }, el('div', { class: 'ae-field-head' }, el('b', { text: title }), copyButton('Copy', () => field.value)), field);
}
function translateBox(id) {
  const box = el('div', { class: 'translate-box' }, el('b', { text: 'Reach more viewers: translate captions' }));
  if (!(studio.caps && studio.caps.ai_text)) {
    box.append(el('small', { text: 'Translated captions need ANTHROPIC_API_KEY on this computer. The original SRT and VTT files above work on YouTube as they are.' }));
    return box;
  }
  const inputs = [];
  const checks = Object.entries(studio.caps.languages || {}).map(([code, name]) => {
    const input = el('input', { type: 'checkbox', value: code }); inputs.push(input);
    return el('label', { class: 'lang-chip' }, input, name);
  });
  const status = el('div', { class: 'render-status hidden', role: 'status' });
  const out = el('div', { class: 'translate-files' });
  const go = el('button', { type: 'button', class: 'ghost-btn', text: 'Translate selected (up to 6)', onclick: async () => {
    const langs = inputs.filter((i) => i.checked).map((i) => i.value);
    if (!langs.length) { toast('Pick at least one language.', true); return; }
    go.disabled = true;
    try {
      const { job_id } = await post('/api/projects/' + id + '/translate', { languages: langs });
      const job = await runJob(job_id, (j) => showStatus(status, j));
      status.textContent = 'Done.';
      out.replaceChildren(...job.outputs.files.map((f) => el('div', { class: 'translate-file' }, el('span', { text: f.language }),
        el('a', { class: 'tiny-btn', href: f.srt, download: '', text: 'SRT' }), el('a', { class: 'tiny-btn', href: f.vtt, download: '', text: 'VTT' }))));
    } catch (e) { status.classList.remove('hidden'); status.textContent = 'Translation stopped: ' + e.message; toast(e.message, true); }
    finally { go.disabled = false; }
  } });
  box.append(el('div', { class: 'lang-grid' }, ...checks), go, status, out);
  return box;
}
function extrasLine(x) {
  if (!x) return null;
  const bits = [];
  if (x.intro_clip) bits.push('your intro clip'); if (x.intro_card) bits.push('a title card');
  if (x.lower_thirds) bits.push(x.lower_thirds + ' chapter title' + (x.lower_thirds === 1 ? '' : 's'));
  if (x.callouts) bits.push(x.callouts + ' callout' + (x.callouts === 1 ? '' : 's'));
  if (x.sfx) bits.push(x.sfx + ' sound effect' + (x.sfx === 1 ? '' : 's'));
  if (x.music) bits.push('background music'); if (x.outro_clip) bits.push('your outro clip');
  return el('div', { class: 'auto-result' }, el('strong', { text: 'Added automatically' }),
    el('small', { class: 'auto-reasons', text: bits.length ? bits.join(' · ') : 'Nothing extra was needed for this video.' }));
}
function renderAutoEdit(out, id) {
  const yt = out.youtube; const box = $('autoEditResults');
  const chapters = (yt.chapters || []).length ? yt.chapters.map((c) => Math.floor(c.start / 60) + ':' + String(Math.round(c.start % 60)).padStart(2, '0') + ' ' + c.title).join('\n') : '';
  box.replaceChildren(
    el('div', { class: 'auto-result' },
      el('strong', { text: 'Finished video · ' + clock(out.seconds) + (out.removed_seconds > 0 ? ' · removed ' + out.removed_seconds + ' s of dead air' : '') }),
      el('video', { controls: true, preload: 'metadata', src: out.video }),
      el('div', { class: 'auto-actions' }, el('a', { class: 'download-btn', href: out.video, download: '', text: 'Download video' }))),
    extrasLine(out.extras),
    el('div', { class: 'auto-result' }, el('strong', { text: 'Thumbnail' }),
      el('img', { class: 'ae-thumb', src: out.thumbnail, alt: 'Generated thumbnail' }),
      el('div', { class: 'auto-actions' }, el('a', { class: 'tiny-btn', href: out.thumbnail, download: '', text: 'Download thumbnail' }))),
    el('div', { class: 'auto-result' }, el('strong', { text: 'YouTube upload text' }),
      labeledText('Title', yt.title, false), labeledText('Description (with chapters)', yt.description, true),
      labeledText('Tags', (yt.tags || []).join(', '), false),
      chapters ? el('small', { class: 'auto-reasons', text: (yt.chapters.length) + ' chapters found.' }) : el('small', { class: 'auto-reasons', text: 'No chapters: the video is too short or has no clear topic changes.' }),
      el('div', { class: 'auto-actions' }, el('a', { class: 'tiny-btn', href: yt.file, download: '', text: 'Download as .txt' }))),
    el('div', { class: 'auto-result' }, el('strong', { text: 'Captions (' + out.cues + ')' }),
      el('div', { class: 'auto-actions' }, el('a', { class: 'tiny-btn', href: out.captions.srt, download: '', text: 'SRT' }), el('a', { class: 'tiny-btn', href: out.captions.vtt, download: '', text: 'VTT' })),
      translateBox(id)));
  if (out.shorts && out.shorts.length) {
    const wrap = el('div', { class: 'auto-results' }); box.append(el('strong', { class: 'ae-shorts-title', text: 'Shorts' }), wrap);
    renderOutputs(wrap, out.shorts, 'Short', id, null);
  } else {
    box.append(el('a', { class: 'download-btn', href: '/api/projects/' + id + '/bundle.zip', text: 'Download everything (.zip)' }));
  }
}
async function runAutoEdit() {
  if (studio.busy || !studio.id) return;
  studio.busy = true; const button = $('autoEditRun'); button.disabled = true;
  const status = $('autoEditStatus');
  try {
    const { job_id } = await post('/api/projects/' + studio.id + '/autoedit', {
      trim_silence: $('aeTrim').checked, loudness: $('aeLoud').checked, watermark: $('aeWatermark').checked,
      endcard: $('aeEndcard').checked, captions: $('aeCaptions').checked, zoom: $('aeZoom').value,
      resolution: $('aeRes').value, shorts: Number($('aeShorts').value),
      sfx: $('aeSfx').checked, callouts: $('aeCallouts').checked, chapter_titles: $('aeTitles').checked,
      music: $('aeMusic').checked, intro_outro: $('aeIntroOutro').checked, intro_card: $('aeIntroCard').checked });
    const job = await runJob(job_id, (j) => showStatus(status, j));
    status.textContent = 'Done. Your video, thumbnail and upload text are ready.';
    renderAutoEdit(job.outputs, studio.id);
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Auto-edit stopped: ' + e.message; toast(e.message, true); }
  finally { studio.busy = false; button.disabled = false; }
}

/* ---------- Watch folder (desktop app only) ---------- */
const watch = { timer: null };
function paintWatch(s) {
  $('watchStart').classList.toggle('hidden', s.running); $('watchStop').classList.toggle('hidden', !s.running);
  const lines = (s.events || []).slice(-8).map((e) => new Date(e.time * 1000).toLocaleTimeString() + '  ' + e.message);
  if (s.busy) lines.push('Working on ' + s.busy + '…');
  $('watchLog').textContent = lines.join('\n');
  clearTimeout(watch.timer);
  if (s.running) watch.timer = setTimeout(refreshWatch, 3000);
}
async function refreshWatch() { try { paintWatch(await api('/api/watch/status')); } catch (e) { /* offline: try again on next open */ } }
async function startWatch() {
  try {
    paintWatch(await post('/api/watch/start', { folder: $('watchFolder').value.trim(), out: $('watchOut').value.trim(),
      options: { shorts: Number($('watchShorts').value) } }));
  } catch (e) { toast(e.message, true); }
}
async function stopWatch() { try { paintWatch(await post('/api/watch/stop', {})); } catch (e) { toast(e.message, true); } }

/* ---------- wiring (every element is optional so a page without them still loads) ---------- */
const on = (id, type, fn) => { const node = $(id); if (node) node.addEventListener(type, fn); };
on('autoRunBtn', 'click', runAutopilot);
on('directorAssets','change',uploadDirectorAssets);
on('directorPlan','click',()=>runDirector(false));
on('directorRun','click',()=>runDirector(true));
on('autopilotFromReview', 'click', runAutopilot);
on('autoFindShorts', 'click', findShorts);
on('autoRenderShorts', 'click', renderPickedShorts);
on('openClipStudio', 'click', () => openStudio(null));
on('openClipStudioPanel', 'click', () => openStudio(null));
on('clipStudioClose', 'click', closeStudio);
on('clipPick', 'click', () => $('clipFile').click());
on('clipFile', 'change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadSource(f); e.target.value = ''; });
on('clipRegen', 'click', regenerate);
on('autoEditRun', 'click', runAutoEdit);
on('brandOpen', 'click', openBrand);
on('brandSave', 'click', saveBrand);
on('brandCancel', 'click', () => $('brandModal').classList.add('hidden'));
on('brLogoPick', 'click', () => $('brLogoFile').click());
on('brLogoFile', 'change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadLogo(f); e.target.value = ''; });
on('brLogoClear', 'click', clearLogo);
for (const [kind] of ASSETS) {
  const slug = kind.toLowerCase();
  on('br' + kind + 'Pick', 'click', () => $('br' + kind + 'File').click());
  on('br' + kind + 'File', 'change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadAsset(slug, f); e.target.value = ''; });
  on('br' + kind + 'Clear', 'click', () => clearAsset(slug));
}
on('watchStart', 'click', startWatch);
on('watchStop', 'click', stopWatch);
on('clipRender', 'click', renderClips);
document.addEventListener('keydown', (e) => { const s = $('clipStudio'); if (e.key === 'Escape' && s && !s.classList.contains('hidden')) closeStudio(); });

window.SkellyClips = { open: openStudio, close: closeStudio };
})();
