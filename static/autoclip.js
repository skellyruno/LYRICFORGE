/* SkellyMotion autonomous tools: Autopilot, song Shorts and the long-video Clip Studio.
 * Self-contained so the lyric editor (app.js) stays untouched apart from window.SkellyBridge.
 * All user/transcript/AI text is inserted with textContent, never innerHTML. */
(() => {
'use strict';
const $ = (id) => document.getElementById(id);
const bridge = () => window.SkellyBridge || null;
const toast = (message, error = false) => { const b = bridge(); if (b && b.toast) b.toast(message, error); };

async function api(path, options = {}) {
  let mode = 'balanced';
  try { mode = localStorage.getItem('skellymotion-perf-mode') || 'balanced'; } catch { /* storage can be blocked */ }
  const response = await fetch(path, { ...options, headers: { 'X-Perf-Mode': mode, ...(options && options.headers) } });
  if (!response.ok) {
    let reason; try { reason = (await response.json()).detail; } catch (e) { /* not JSON */ }
    throw new Error(typeof reason === 'string' ? reason : 'Request failed (' + response.status + ')');
  }
  return response.json();
}
const send = (method, path, body) => api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
const post = (path, body) => send('POST', path, body);

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
const clock = (s) => { s = Math.round(Math.max(0, Number(s) || 0)*10)/10; return Math.floor(s / 60) + ':' + (s % 60).toFixed(1).padStart(4, '0'); };
const STAGES = {
  preparing: 'Getting ready', finding_visuals: 'Finding pictures', autopilot_prepare: 'Preparing lyrics', autopilot_full_render: 'Rendering the full video',
  autopilot_shorts: 'Picking and rendering Shorts', encoding: 'Encoding', checking_encoder: 'Checking encoder',
  cpu_fallback: 'Switching to CPU encoder', cached: 'Reusing an identical earlier render', analyzing_video: 'Analyzing video',
  complete: 'Done', error: 'Failed', mv_analyze: 'Finding the beat', mv_footage: 'Scanning your footage', mv_render: 'Cutting to the beat',
  anim_render: 'Rendering the animation', viz_render: 'Rendering the visualizer', viz_lyrics: 'Adding the lyrics', ab_analyze: 'Matching loudness',
  stream_intro: 'Rendering the intro', stream_starting: 'Rendering Starting Soon', stream_brb: 'Rendering Be Right Back', stream_ending: 'Rendering the ending',
  speed_render: 'Changing the speed', trim_render: 'Cutting the video', shrink_render: 'Shrinking the video', sheet_frames: 'Grabbing frames',
  gif_render: 'Making the GIF', enhance_render: 'Cleaning up the audio', lower_render: 'Adding the lower third',
  repurpose_portrait: 'Making the vertical version', repurpose_square: 'Making the square version',
  thumbs_pick: 'Finding the best frame', thumbs_render: 'Designing thumbnails'
};
const stageText = (job) => STAGES[job.stage] || String(job.stage || '').replace(/_/g, ' ').replace(/^short (\d+) of (\d+)$/, 'Short $1 of $2')
  .replace(/^clip (\d+) of (\d+)$/, 'Clip $1 of $2');

async function runJob(jobId, onUpdate) {
  for (let i = 0; i < 7200; i++) {
    const job = await api('/api/jobs/' + encodeURIComponent(jobId));
    onUpdate(job);
    if (job.status === 'done' || job.status === 'error' || job.status==='cancelled'){cancelling.delete(jobId);etaClock.delete(jobId);if(job.status==='done')return job;throw new Error(job.error || (job.status==='cancelled'?'Job cancelled':'The job failed'));}
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error('Timed out waiting for the job');
}
const cancelling = new Set();
/* "about 2 min left", from how fast this job has moved so far. Only shown once there is enough to go on. */
const etaClock = new Map();
function etaText(job) {
  const now = Date.now(), p = job.progress || 0;
  if (!job.id || job.status !== 'rendering') { if (job.id) etaClock.delete(job.id); return ''; }
  if (!etaClock.has(job.id)) etaClock.set(job.id, { t0: now, p0: p });
  const { t0, p0 } = etaClock.get(job.id), seconds = (now - t0) / 1000;
  if (p - p0 < 8 || p >= 97 || seconds < 5) return '';
  const left = Math.round(seconds * (100 - p) / (p - p0));
  return ' · about ' + (left < 90 ? Math.max(5, Math.round(left / 5) * 5) + ' s' : Math.round(left / 60) + ' min') + ' left';
}
function showStatus(node, job) {
  node.classList.remove('hidden');
  node.textContent = stageText(job) + ' · ' + (job.progress || 0) + '%' + etaText(job) + (job.encoder_used ? ' · ' + job.encoder_used : '');
  if (!job.id || job.status !== 'rendering') return;
  const asked = cancelling.has(job.id);
  node.append(' ', el('button', { type: 'button', class: 'tiny-btn cancel-job', text: asked ? 'Cancelling…' : 'Cancel', disabled: asked, onclick: async () => {
    cancelling.add(job.id);
    try { await post('/api/jobs/' + encodeURIComponent(job.id) + '/cancel', {}); } catch (e) { cancelling.delete(job.id); toast(e.message, true); }
  } }));
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
        copyButton('Copy description + tags', () => (item.description || '') + '\n\n' + tags)),
      (item.translations || []).length || (item.translation_errors || []).length ? el('div', { class: 'auto-actions' },
        ...(item.translations || []).map((t) => el('a', { class: 'tiny-btn', href: t.url, download: '', text: t.language })),
        ...(item.translation_errors || []).map((t) => el('small', { class: 'auto-reasons', text: t.lang + ' failed: ' + t.error }))) : null));
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

// Offline Director: semantic asset matching, transcript cuts, scene cache and final mux.
let directorBusy=false, directorProject=null, directorRecording=null;
const currentDirector=id=>bridge()?.state().id===id;
const numberSetting=(id,fallback)=>{const v=$(id)?.value;return v!==''&&v!=null&&Number.isFinite(Number(v))?Number(v):fallback;};
function compressorDemoSettings(){try{return $('directorCompressorLab')?.contentWindow?.demoSettings?.()||{};}catch{return {};}}
function directorPayload(){const b=bridge();return {title_style:$('directorTitleStyle')?.value||'slide',title_motion:!!$('directorTitleMotion')?.checked,guided_replay:!!$('directorGuidedReplay')?.checked,transition_style:$('directorTransitionStyle')?.value||'dissolve',transition_seconds:numberSetting('directorTransitionSeconds',.32),caption_style:$('directorCaptionStyle')?.value||'karaoke',caption_scale:numberSetting('directorCaptionScale',1),voice_style:$('directorVoiceStyle')?.value||'natural',music_gain:numberSetting('directorMusicGain',1),cue_gain:numberSetting('directorCueGain',1),compressor_demo:compressorDemoSettings(),cinematic_finish:$('directorCinematic').checked,sound_design:$('directorSoundDesign').checked,preset:$('directorPreset').value,brand:$('directorBrand').value,preview:$('directorPreview').checked,music:$('directorMusic').checked,auto_pictures:$('directorAutoPictures').checked,output_format:$('directorFormat').value,start_seconds:Number($('directorStart').value)||0,intensity:$('directorIntensity').value,motion:$('directorMotion').value,transitions:$('directorTransitions').checked,diagrams:$('directorDiagrams').checked,local_ai:$('directorLocalAI').checked,semantic_vision:$('directorSemantic').checked,lines:projectLines(),settings:b.state().settings};}
function directorStatus(message,error=false){const node=$('directorStatus');node.classList.remove('hidden');node.textContent=message;if(error)toast(message,true);}
function directorSceneList(plan){const review=plan.review||{}; $('directorReview').replaceChildren(el('div',{class:'director-scene'},el('b',{text:'Review · '+(review.errors||0)+' errors · '+(review.warnings||0)+' warnings'}),el('small',{text:plan.beat_aligned?'Beat grid · '+plan.bpm+' BPM':'Phrase / timed cuts'}),...(review.issues||[]).slice(0,8).map(i=>el('small',{text:i.message}))));const node=$('directorScenes');node.replaceChildren(...(plan.scenes||[]).map((s,i)=>el('div',{class:'director-scene'},el('span',{text:clock(s.start)+'–'+clock(s.end)}),el('b',{text:(i+1)+'. '+s.type.replace('_',' ')}),el('small',{text:s.asset_name||s.text||''}),s.recorded_demo?el('small',{text:'Actual recording · '+clock(s.asset_start||0)}):s.guided_replay?el('small',{text:'Guided captured-state replay'}):null,s.source?el('small',{text:(s.source.provider==='Local AI'?'AI illustration · ':'Illustrative · ')+s.source.license+' · '+s.source.creator}):null,s.asset&&!s.recorded_demo&&(/\.(png|jpg|jpeg|webp)$/i.test(s.asset))?el('img',{class:'director-thumb',src:'/api/projects/'+bridge().state().id+'/director/assets/'+encodeURIComponent(s.asset),alt:s.asset_name||'Illustrative image',loading:'lazy'}):null)));}
function directorAssetCard(a,id){
 const route='/api/projects/'+id+'/director/assets/'+encodeURIComponent(a.id);let point=[...(a.focus_point||[null,null])];
 const desc=el('input',{type:'text',maxlength:300,value:a.description||'', 'aria-label':'Asset description'});
 const role=el('select',{'aria-label':'Asset role'},...['auto','plugin_recording','plugin_state','broll','document'].map(r=>el('option',{value:r,text:r.replaceAll('_',' '),selected:r===(a.role||'auto')})));
 const group=el('input',{maxlength:64,value:a.group||'',placeholder:'State group','aria-label':'State group'}),order=el('input',{type:'number',min:0,max:999,value:a.order||0,'aria-label':'State number'});
 const start=el('input',{type:'number',min:0,step:.1,value:a.trim_start||0,'aria-label':'Trim start seconds'}),end=el('input',{type:'number',min:0,step:.1,value:a.trim_end||0,'aria-label':'Trim end seconds (0 = end)'});
 const focusText=el('small',{text:point[0]==null?'Focus: auto':'Focus: '+point.map(x=>Number(x).toFixed(2)).join(', ')});
 const thumb=a.kind==='image'?el('img',{class:'director-edit-thumb',src:route,alt:a.name,loading:'lazy',onclick:e=>{const rect=e.target.getBoundingClientRect();if(rect.width&&rect.height){point=[Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(e.clientY-rect.top)/rect.height))];focusText.textContent='Focus: '+point.map(x=>x.toFixed(2)).join(', ');}}}):el('video',{class:'director-proof',src:route,controls:true,preload:'none'});
 const update=async disabled=>{if(directorBusy||!currentDirector(id))return;directorBusy=true;try{await send('PUT',route,{description:desc.value,role:role.value||a.role||'auto',group:group.value,order:Number(order.value)||0,focus_x:point[0],focus_y:point[1],trim_start:Number(start.value)||0,trim_end:Number(end.value)||0,disabled});await refreshDirectorAssets(id);if(currentDirector(id))directorStatus('Visual library updated.');}catch(e){if(currentDirector(id))directorStatus(e.message,true);}finally{directorBusy=false;}};
 return el('details',{class:'director-asset-card'},el('summary',{text:(a.disabled?'Disabled · ':'')+a.name}),thumb,el('small',{text:(a.source?'Illustration · ':'')+a.kind+(a.features?.duration?' · '+clock(a.features.duration):'')}),desc,role,el('div',{class:'director-asset-pair'},group,order),a.kind==='video'?el('div',{class:'director-asset-pair'},start,end):null,a.kind==='image'?el('div',{class:'director-asset-pair'},focusText,el('button',{type:'button',class:'tiny-btn',text:'Auto focus',onclick:()=>{point=[null,null];focusText.textContent='Focus: auto';}})):null,el('div',{class:'director-asset-pair'},el('button',{type:'button',class:'tiny-btn',text:'Save metadata',onclick:()=>update(!!a.disabled)}),el('button',{type:'button',class:'tiny-btn',text:a.disabled?'Restore':'Disable (keep file)',onclick:()=>update(!a.disabled)})));
}
async function refreshDirectorAssets(id){const data=await api('/api/projects/'+id+'/director/assets');if(!currentDirector(id))return;directorProject=id;$('directorAssetsList').replaceChildren(...data.assets.map(a=>directorAssetCard(a,id)));}
async function refreshCurrentDirector(){const id=bridge()?.state().id;if(!id){toast('Open a project first.',true);return;}try{await refreshDirectorAssets(id);}catch(e){directorStatus(e.message,true);}}
async function sendDirectorFile(id,file,role,group,order,description){const form=new FormData();form.append('file',file);form.append('description',description);form.append('role',role);form.append('group',group);form.append('order',String(order));return api('/api/projects/'+id+'/director/assets',{method:'POST',body:form});}
async function uploadDirectorAssets(){const id=bridge()?.state().id;if(!id){toast('Open a song or voiceover first.',true);$('directorAssets').value='';return;}if(directorBusy)return;directorBusy=true;try{const files=Array.from($('directorAssets').files||[]),role=$('directorAssetRole').value||'auto',group=$('directorStateGroup').value||'',order=numberSetting('directorStateOrder',0),description=$('directorAssetDescription').value||'';for(let i=0;i<files.length;i++){if(!currentDirector(id))break;directorStatus('Importing visual '+(i+1)+' / '+files.length);await sendDirectorFile(id,files[i],role,group,Math.min(999,order+i),description);}await refreshDirectorAssets(id);if(currentDirector(id))directorStatus('Assets ready.');}catch(e){if(currentDirector(id))directorStatus(e.message,true);}finally{directorBusy=false;$('directorAssets').value='';}}
async function captureDirector(){
 const id=bridge()?.state().id;if(!id||directorBusy||directorRecording){toast('Open an idle project first.',true);return;}
 if(!navigator.mediaDevices?.getDisplayMedia||typeof MediaRecorder==='undefined'){directorStatus('Screen capture is unavailable here. Import a recording from your DAW or OBS.',true);return;}
 const description=$('directorAssetDescription').value||'Plugin control demonstration';directorBusy=true;let stream;
 try{
  stream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:{ideal:30,max:30}},audio:false});
  if(!currentDirector(id)){stream.getTracks().forEach(t=>t.stop());directorBusy=false;return;}
  const type=['video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
  if(!type)throw new Error('WebM screen recording is unavailable. Import an external recording.');
  const recorder=new MediaRecorder(stream,{mimeType:type,videoBitsPerSecond:2500000});let chunks=[],bytes=0,failed=false,timer;
  const stop=()=>{if(recorder.state!=='inactive')recorder.stop();};
  directorRecording={stop};$('directorCapture').disabled=true;$('directorCaptureStop').classList.remove('hidden');
  recorder.addEventListener('dataavailable',e=>{if(e.data.size){bytes+=e.data.size;if(bytes<=70*1024*1024)chunks.push(e.data);else{failed=true;stop();}}});
  recorder.addEventListener('error',()=>{failed=true;stop();});
  recorder.addEventListener('stop',async()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());directorRecording=null;$('directorCapture').disabled=false;$('directorCaptureStop').classList.add('hidden');try{if(failed||!chunks.length)throw new Error('Recording was empty or exceeded the size limit.');if(!currentDirector(id)){toast('Recording not imported because the project changed.',true);return;}const file=new File(chunks,'plugin-recording-'+Date.now()+'.webm',{type:'video/webm'});await sendDirectorFile(id,file,'plugin_recording','',0,description);await refreshDirectorAssets(id);if(currentDirector(id))directorStatus('Actual plugin recording imported.');}catch(e){if(currentDirector(id))directorStatus(e.message,true);}finally{directorBusy=false;chunks=[];}});
  stream.getVideoTracks().forEach(t=>t.addEventListener('ended',stop,{once:true}));recorder.start(1000);timer=setTimeout(stop,60000);directorStatus('Recording selected window · stop when finished.');
 }catch(e){stream?.getTracks().forEach(t=>t.stop());directorRecording=null;directorBusy=false;$('directorCapture').disabled=false;$('directorCaptureStop').classList.add('hidden');if(currentDirector(id))directorStatus('Capture unavailable: '+e.message,true);}
}
async function runDirector(render){const id=bridge()?.state().id;if(!id){toast('Open a song or voiceover first.',true);return;}if(directorBusy||song.busy)return;const payload=directorPayload();directorBusy=true;for(const k of ['directorPlan','directorRun'])$(k).disabled=true;try{await refreshDirectorAssets(id);if(bridge()?.state().id!==id)return;directorStatus('Planning with the local director…');const result=await post('/api/projects/'+id+'/director/'+(render?'render':'plan'),payload);if(bridge()?.state().id!==id)return;directorSceneList(result.plan||result);if(!render){directorStatus(result.scenes.length+' scenes planned. '+(result.warnings||[]).join(' '));return;}const job=await runJob(result.job_id,j=>{if(bridge()?.state().id===id)showStatus($('directorStatus'),j);});if(bridge()?.state().id!==id)return;const out=job.outputs;const finalPlan=await api(out.plan);if(bridge()?.state().id!==id)return;directorSceneList(finalPlan);await refreshDirectorAssets(id);if(!currentDirector(id))return;const sources=finalPlan.visual_sources||{};directorStatus('Done · '+out.scenes+' scenes · '+out.cached+' reused · '+(sources.downloaded||0)+' pictures found · '+(out.recorded_scenes||0)+' recordings · '+(out.guided_replays||0)+' guided shots. '+(finalPlan.warnings||[]).join(' '));$('directorResult').replaceChildren(el('video',{controls:true,preload:'metadata',src:out.video,class:'director-proof'}),el('a',{class:'download-btn',href:out.video,download:'',text:'Download directed MP4'}),el('a',{class:'wide-ghost',href:out.plan,download:'',text:'Download scene plan JSON'}),out.captions?el('a',{class:'wide-ghost',href:out.captions,download:'',text:'Download WebVTT captions'}):null);}catch(e){if(currentDirector(id))directorStatus('Director stopped: '+e.message,true);}finally{directorBusy=false;for(const k of ['directorPlan','directorRun'])$(k).disabled=false;}}

let creatorBusy=false,creatorDraftRows=[],creatorSampleURL=null,creatorVoiceTake=null,creatorVoiceRecorder=null;
function creatorVoiceSettings(){const pronunciation=Object.create(null);for(const line of $('creatorPronunciation').value.split(/\r?\n/)){if(!line.trim())continue;const i=line.indexOf('=');if(i<1||!line.slice(i+1).trim())throw new Error('Use one pronunciation per line: word = spoken text');pronunciation[line.slice(0,i).trim()]=line.slice(i+1).trim();}return {delivery:$('creatorDelivery').value||'neutral',pronunciation};}
function playCreatorTake(file){const audio=$('creatorVoiceAudio');audio.pause();if(creatorSampleURL)URL.revokeObjectURL(creatorSampleURL);creatorSampleURL=URL.createObjectURL(file);audio.src=creatorSampleURL;audio.classList.remove('hidden');$('creatorVoice').value='recorded';refreshCreatorStats();creatorMessage('Narration take ready · review and use the exact recorded script.');}
async function recordCreatorVoice(){if(creatorBusy||creatorVoiceRecorder)return;if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){creatorMessage('Microphone recording unavailable here. Import a recorded WAV instead.',true);return;}let stream;creatorBusy=true;creatorButtons(true);try{
 stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});const type=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg'].find(t=>MediaRecorder.isTypeSupported(t));if(!type)throw new Error('No supported recording format. Import your take instead.');const recorder=new MediaRecorder(stream,{mimeType:type});let parts=[],bytes=0,failed=false,timer;const stop=()=>{if(recorder.state!=='inactive')recorder.stop();};creatorVoiceRecorder={stop};$('creatorRecordVoice').disabled=true;$('creatorStopVoice').classList.remove('hidden');recorder.addEventListener('dataavailable',e=>{if(e.data.size){bytes+=e.data.size;if(bytes<=100*1024*1024)parts.push(e.data);else{failed=true;stop();}}});recorder.addEventListener('error',()=>{failed=true;stop();});recorder.addEventListener('stop',()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());creatorVoiceRecorder=null;creatorBusy=false;creatorButtons(false);$('creatorRecordVoice').disabled=false;$('creatorStopVoice').classList.add('hidden');if(failed||!parts.length){creatorMessage('Recording empty or too large.',true);return;}const ext=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';creatorVoiceTake=new File(parts,'narration-'+Date.now()+'.'+ext,{type});playCreatorTake(creatorVoiceTake);parts=[];});stream.getAudioTracks().forEach(t=>t.addEventListener('ended',stop,{once:true}));recorder.start(1000);timer=setTimeout(stop,600000);creatorMessage('Recording microphone · stop when finished (10 minute take limit).');
 }catch(e){stream?.getTracks().forEach(t=>t.stop());creatorBusy=false;creatorButtons(false);creatorVoiceRecorder=null;$('creatorRecordVoice').disabled=false;$('creatorStopVoice').classList.add('hidden');creatorMessage('Microphone unavailable: '+e.message,true);}}

function creatorBrief(){return {product:$('creatorProduct').value.trim(),brief:$('creatorBrief').value,facts:$('creatorFacts').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),target_seconds:Number($('creatorSeconds').value)||90,story:$('creatorStory').value||'tutorial',production_mode:$('creatorProductionMode').value||'plugin'};}
function refreshCreatorStats(){const node=$('creatorScriptStats');if(!node)return;const chapters=$('creatorScript').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);const words=chapters.reduce((n,s)=>n+($('creatorProductionMode').value==='research'?s.split(' | ')[0]:s).split(/\s+/).length,0);const pace=Math.max(.8,Math.min(1.2,Number($('creatorSpeed').value)||1));const factor=({neutral:1,tutorial:.96,energetic:1.07,documentary:.91})[$('creatorDelivery').value]||1;const seconds=Math.round(words/(2.35*pace*factor)+chapters.length*.25);node.textContent=words?words+' words · '+chapters.length+' chapters · '+($('creatorVoice').value==='recorded'?'timing from your take':'~'+seconds+'s estimate'):'0 words · Add your script';}
function creatorMessage(message,error=false){const node=$('creatorStatus');node.classList.remove('hidden');node.textContent=message;if(error)toast(message,true);}
function creatorButtons(disabled){for(const id of ['creatorDraft','creatorPrepare','creatorRender'])$(id).disabled=disabled;}
async function draftCreator(){if(creatorBusy)return;creatorBusy=true;creatorButtons(true);try{const result=await post('/api/creator/script',creatorBrief());creatorDraftRows=result.chapters;$('creatorScript').value=result.chapters.map(c=>c.narration+(c.source_url?' | '+c.source_url:'')).join('\n');refreshCreatorStats();creatorMessage('Estimated '+result.estimated_seconds+' seconds · '+(result.warnings||[]).join(' '));}catch(e){creatorMessage(e.message,true);}finally{creatorBusy=false;creatorButtons(false);}}
async function auditionCreator(){if(creatorBusy)return;creatorBusy=true;creatorButtons(true);$('creatorAudition').disabled=true;try{
 if($('creatorVoice').value==='recorded'){if(!creatorVoiceTake)throw new Error('Record or import your voice first.');playCreatorTake(creatorVoiceTake);await $('creatorVoiceAudio').play().catch(()=>{});return;}
 const first=$('creatorScript').value.trim().split(/\r?\n/)[0];const text=(($('creatorProductionMode').value==='research'?first.split(' | ')[0]:first)||'Here is a closer look at '+($('creatorProduct').value.trim()||'your plugin')+'.').slice(0,200);
 const response=await fetch('/api/creator/voice-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,voice:$('creatorVoice').value,speed:Number($('creatorSpeed').value)||1,...creatorVoiceSettings()})});
 if(!response.ok){let d;try{d=(await response.json()).detail;}catch{}throw new Error(typeof d==='string'?d:'Voice preview failed');}
 const audio=$('creatorVoiceAudio');audio.pause();if(creatorSampleURL)URL.revokeObjectURL(creatorSampleURL);creatorSampleURL=URL.createObjectURL(await response.blob());audio.src=creatorSampleURL;audio.classList.remove('hidden');creatorMessage('Voice sample · '+(response.headers.get('X-Skelly-Voice')||'local'));await audio.play().catch(()=>{});
 }catch(e){creatorMessage(e.message,true);}finally{creatorBusy=false;creatorButtons(false);$('creatorAudition').disabled=false;}}
async function createVideo(render){if(creatorBusy||directorBusy||song.busy)return;creatorBusy=true;creatorButtons(true);try{
 const text=$('creatorScript').value.trim();const research=$('creatorProductionMode').value==='research';
 const chapters=text?text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map(n=>{const cut=research?n.lastIndexOf(' | '):-1;const claim=cut>=0?n.slice(0,cut).trim():n;const url=cut>=0?n.slice(cut+3).trim():'';if(research&&!url)throw new Error('Research chapters need a confirmed claim | https://source');return {...(creatorDraftRows.find(c=>c.narration===claim&&(!research||c.source_url===url))||{title:claim.split(/\s+/).slice(0,5).join(' '),narration:claim,visual_hint:claim.slice(0,200)}),...(research?{source_url:url}:{})};}):[];
 const files=Array.from($('creatorFiles').files||[]);if(files.length>40)throw new Error('Use up to 40 visuals.');
 const caps=await api('/api/creator/voices');const requested=$('creatorVoice').value;const selected=requested==='auto'?['kokoro','piper','system','draft'].find(x=>caps[x]):requested;
 if(selected==='recorded'){if(!creatorVoiceTake)throw new Error('Record or import your narration first.');if(!chapters.length)throw new Error('Paste the exact recorded script.');}else if(!selected||!caps[selected])throw new Error('That voice is not installed. Choose an available local narrator.');
 const markerText=$('creatorChapterTimes').value.trim();const chapter_starts=markerText?markerText.split(',').map(v=>Number(v.trim())):[];if(chapter_starts.some(v=>!Number.isFinite(v)))throw new Error('Invalid chapter timestamps');
 const payload={...creatorBrief(),...creatorVoiceSettings(),chapter_starts,chapters,voice:selected,speed:Number($('creatorSpeed').value)||1,auto_render:render,preview:false,format:$('creatorFormat').value,visual_roles:files.map(f=>({description:f.name,role:$('creatorRecording').checked&&/\.(mp4|mov|mkv|webm|m4v)$/i.test(f.name)?'plugin_recording':'auto'})),sound_design:true,title_motion:true,title_style:$('creatorTitleStyle').value||'adaptive'};
 const form=new FormData();form.append('payload',JSON.stringify(payload));for(const f of files)form.append('files',f);if(selected==='recorded')form.append('recording',creatorVoiceTake);
 const dry=$('creatorProofBefore').files?.[0],wet=$('creatorProofAfter').files?.[0];
 if(Boolean(dry)!==Boolean(wet))throw new Error('Attach both dry and processed files.');
 if(dry&&wet){payload.proof_start=Number($('creatorProofStart').value);payload.proof_seconds=Number($('creatorProofSeconds').value);form.set('payload',JSON.stringify(payload));form.append('proof_before',dry);form.append('proof_after',wet);}
 creatorMessage('Preparing project with '+selected+' narration…');const result=await api('/api/creator/create',{method:'POST',body:form});
 $('creatorResult').replaceChildren();
 const job=await runJob(result.job_id,j=>showStatus($('creatorStatus'),j));const out=job.outputs||{};
 creatorMessage('Ready · '+selected+' voice'+(selected==='draft'?' (basic synthetic draft)':'')+'. Edit narration and timing before publishing.');
 $('creatorResult').replaceChildren(el('button',{type:'button',class:'wide-ghost',text:'Open editable project',onclick:()=>bridge()?.openSavedProject(result.project_id)}),out.video?el('video',{class:'director-proof',controls:true,src:out.video,preload:'metadata'}):null,out.video?el('a',{class:'download-btn',href:out.video,download:'',text:'Download video'}):null,out.plan?el('a',{class:'wide-ghost',href:out.plan,download:'',text:'Download scene plan'}):null);
 }catch(e){creatorMessage(e.message,true);}finally{creatorBusy=false;creatorButtons(false);}}

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
  paintClipLangs();
  if (studio.caps.max_source_mb) $('clipLimitNote').textContent = 'MP4, MOV, MKV, WebM · up to ' + studio.caps.max_source_mb + ' MB / ' + studio.caps.max_source_minutes + ' min';
  return studio.caps;
}
const clipLangInputs = [];
function paintClipLangs() {
  const box = $('clipLangs'); if (!box) return;
  clipLangInputs.length = 0;
  const on = !!(studio.caps && studio.caps.ai_text);
  box.classList.toggle('hidden', !on);
  if (!on) { box.replaceChildren(); return; }
  box.replaceChildren(el('b', { text: 'Also make translated copies (up to 3)' }), el('div', { class: 'lang-grid' },
    ...Object.entries(studio.caps.languages || {}).map(([code, name]) => {
      const input = el('input', { type: 'checkbox', value: code }); clipLangInputs.push(input);
      return el('label', { class: 'lang-chip' }, input, name);
    })));
}
async function openStudio(id) {
  $('clipStudio').classList.remove('hidden');
  await loadCaps();
  if (studio.caps.watch) refreshWatch();
  refreshPresets();
  if (id) { studio.id = id; attach(); } else { studio.id = null; setStep('clipUploadStep'); }
}
async function uploadSource(file) {
  if (!file) return;
  setStep('clipProgressStep'); $('clipProgressTitle').textContent = 'Uploading ' + file.name; $('clipMeter').style.width = '4%';
  const form = new FormData();
  form.append('file', file); form.append('language', $('clipLanguage').value);
  form.append('keep_fillers', $('clipKeepFillers') && $('clipKeepFillers').checked ? 'true' : 'false');
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
      polish: { loudness: $('clipLoud').checked, trim_silence: $('clipTrim').checked, watermark: $('clipWatermark').checked },
      languages: clipLangInputs.filter((i) => i.checked).map((i) => i.value).slice(0, 3) });
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
  try { const { brand } = await api('/api/brand'); fillBrand(brand); $('brandModal').classList.remove('hidden'); refreshBroll(); }
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
const AE_FIELDS = [ // [option name, element id, kind]
  ['trim_silence', 'aeTrim', 'check'], ['loudness', 'aeLoud', 'check'], ['watermark', 'aeWatermark', 'check'], ['endcard', 'aeEndcard', 'check'],
  ['captions', 'aeCaptions', 'check'], ['zoom', 'aeZoom', 'text'], ['resolution', 'aeRes', 'text'], ['shorts', 'aeShorts', 'number'],
  ['sfx', 'aeSfx', 'check'], ['callouts', 'aeCallouts', 'check'], ['chapter_titles', 'aeTitles', 'check'], ['music', 'aeMusic', 'check'],
  ['intro_outro', 'aeIntroOutro', 'check'], ['intro_card', 'aeIntroCard', 'check'], ['voice_cleanup', 'aeVoice', 'text'],
  ['fillers', 'aeFillers', 'text'], ['zoom_mode', 'aeZoomMode', 'text'], ['broll', 'aeBroll', 'check']];
function readAutoEdit() {
  const out = {};
  for (const [key, id, kind] of AE_FIELDS) { const n = $(id); out[key] = kind === 'check' ? !!n.checked : kind === 'number' ? Number(n.value) : n.value; }
  return out;
}
function applyAutoEdit(options) {
  for (const [key, id, kind] of AE_FIELDS) {
    if (!(key in options)) continue;
    const n = $(id); if (kind === 'check') n.checked = !!options[key]; else n.value = String(options[key]);
  }
}

/* ---------- Presets: one-click bundles of the auto-edit options ---------- */
const presets = { list: [] };
async function refreshPresets(select) {
  const box = $('aePreset'); if (!box) return;
  try { presets.list = (await api('/api/presets')).presets || []; } catch (e) { return; }
  box.replaceChildren(el('option', { value: '', text: 'Custom (my own settings)' }),
    ...presets.list.map((p) => el('option', { value: p.name, text: p.name + (p.builtin ? '' : ' (mine)') })));
  box.value = select || '';
  $('aePresetDelete').classList.toggle('hidden', !presets.list.some((p) => p.name === box.value && !p.builtin));
}
function pickPreset() {
  const name = $('aePreset').value; const found = presets.list.find((p) => p.name === name);
  if (found) applyAutoEdit(found.options);
  $('aePresetDelete').classList.toggle('hidden', !found || found.builtin);
}
async function savePreset() {
  const name = $('aePresetName').value.trim();
  if (!name) { toast('Type a name for this preset first.', true); return; }
  try {
    await send('PUT', '/api/presets/' + encodeURIComponent(name), { options: readAutoEdit() });
    $('aePresetName').value = ''; await refreshPresets(name); toast('Preset saved');
  } catch (e) { toast(e.message, true); }
}
async function deletePreset() {
  const name = $('aePreset').value; if (!name) return;
  try { await send('DELETE', '/api/presets/' + encodeURIComponent(name)); await refreshPresets(''); toast('Preset removed'); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Post text for every platform ---------- */
const PLATFORMS = { youtube_shorts: 'YouTube Shorts', tiktok: 'TikTok', instagram: 'Instagram', x: 'X' };
function postsBox(posts, yt, id) {
  const box = el('div', { class: 'auto-result posts-box' }, el('strong', { text: 'Post text for each platform' }));
  const tabs = el('div', { class: 'make-tabs' }); let buttons = []; const area = el('textarea', { rows: '7', readonly: true }); const count = el('small', { class: 'auto-reasons' });
  let current = posts; let activeKey = null;
  const show = (key) => {
    const p = current[key]; area.value = p.text; count.textContent = p.chars !== undefined ? p.chars + ' of ' + p.limit + ' characters' : '';
    for (const b of buttons) b.node.classList.toggle('active', b.key === key);
    activeKey = key;
  };
  const paint = () => {
    buttons = Object.keys(current).map((key) => ({ key, node: el('button', { type: 'button', class: 'make-tab',
      text: PLATFORMS[key] || key, onclick: () => show(key) }) }));
    tabs.replaceChildren(...buttons.map((b) => b.node));
    show(activeKey && current[activeKey] ? activeKey : Object.keys(current)[0]);
  };
  const actions = el('div', { class: 'auto-actions' }, copyButton('Copy', () => area.value));
  box.append(tabs, area, count, actions);
  if (studio.caps && studio.caps.ai_text) {
    const ai = el('button', { type: 'button', class: 'tiny-btn', text: 'Rewrite with AI', onclick: async () => {
      ai.disabled = true;
      try { current = (await post('/api/projects/' + id + '/posts', { title: yt.title, text: yt.description, tags: yt.tags || [], use_ai: true })).posts; paint(); }
      catch (e) { toast(e.message, true); } finally { ai.disabled = false; }
    } });
    actions.append(ai);
  }
  paint();
  return box;
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
    out.posts && Object.keys(out.posts).length ? postsBox(out.posts, yt, id) : null,
    el('div', { class: 'auto-result' }, el('strong', { text: 'Captions (' + out.cues + ')' }),
      el('div', { class: 'auto-actions' }, el('a', { class: 'tiny-btn', href: out.captions.srt, download: '', text: 'SRT' }), el('a', { class: 'tiny-btn', href: out.captions.vtt, download: '', text: 'VTT' })),
      translateBox(id)));
  if (window.SkellyMake && window.SkellyMake.extras) for (const node of window.SkellyMake.extras(out, id)) box.append(node);
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
    const { job_id } = await post('/api/projects/' + studio.id + '/autoedit', readAutoEdit());
    const job = await runJob(job_id, (j) => showStatus(status, j));
    status.textContent = 'Done. Your video, thumbnail and upload text are ready.';
    renderAutoEdit(job.outputs, studio.id);
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Auto-edit stopped: ' + e.message; toast(e.message, true); }
  finally { studio.busy = false; button.disabled = false; }
}

/* ---------- Transcript proofreading ---------- */
const proof = { rows: [], words: 0 };
async function openProof() {
  if (!studio.id) return;
  try {
    const data = await api('/api/projects/' + studio.id + '/transcript');
    paintProof(data); $('proofModal').classList.remove('hidden');
  } catch (e) { toast(e.message, true); }
}
function paintProof(data) {
  proof.words = data.words;
  $('proofSummary').textContent = data.uncertain.length
    ? data.uncertain.length + ' word(s) the speech recognizer was unsure about. Fix any that are wrong; leave the rest.'
    : 'Nothing looks uncertain. Use find and replace below for names the recognizer keeps getting wrong.';
  proof.rows = data.uncertain.map((u) => {
    const input = el('input', { type: 'text', maxlength: '80', value: u.text, 'aria-label': 'Correction for ' + u.text });
    return { i: u.i, original: u.text, input, node: el('div', { class: 'proof-row' },
      el('small', { class: 'auto-reasons', text: '…' + [u.before, '[' + u.text + ']', u.after].filter(Boolean).join(' ') + '… · ' + clock(u.start) }), input) };
  });
  $('proofList').replaceChildren(...proof.rows.map((r) => r.node));
}
async function applyProof() {
  const edits = proof.rows.filter((r) => r.input.value.trim() !== r.original).map((r) => ({ i: r.i, text: r.input.value.trim() }));
  const find = $('proofFind').value.trim(); const replace = [];
  if (find) replace.push({ find, with: $('proofWith').value.trim(), case: false });
  if (!edits.length && !replace.length) { toast('Nothing to change yet.', true); return; }
  const button = $('proofApply'); button.disabled = true;
  try {
    const res = await post('/api/projects/' + studio.id + '/transcript', { edits, replace });
    paintProof({ words: proof.words, uncertain: res.uncertain });
    $('proofFind').value = ''; $('proofWith').value = '';
    if (res.suggestions) showCards(res.suggestions);
    toast(res.changed ? res.changed + ' word(s) corrected. Clip picks were refreshed.' : 'No matching words were found.');
  } catch (e) { toast(e.message, true); } finally { button.disabled = false; }
}

/* ---------- B-roll library (inside the brand kit) ---------- */
async function refreshBroll() {
  const list = $('brBrollList'); if (!list) return;
  try {
    const { clips: items, max } = await api('/api/brand/broll');
    $('brBrollCount').textContent = items.length + ' of ' + max;
    list.replaceChildren(...items.map((c) => {
      const kw = el('input', { type: 'text', value: c.keywords.join(', '), maxlength: '200', 'aria-label': 'Keywords for ' + c.name });
      return el('div', { class: 'broll-row' }, el('b', { text: c.name }), el('small', { text: c.duration + ' s' }), kw,
        el('button', { type: 'button', class: 'tiny-btn', text: 'Save', onclick: async () => {
          try { await send('PUT', '/api/brand/broll/' + encodeURIComponent(c.name), { keywords: kw.value.split(',').map((x) => x.trim()).filter(Boolean) }); toast('Keywords saved'); }
          catch (e) { toast(e.message, true); } } }),
        el('button', { type: 'button', class: 'tiny-btn', text: 'Remove', onclick: async () => {
          try { await api('/api/brand/broll/' + encodeURIComponent(c.name), { method: 'DELETE' }); refreshBroll(); } catch (e) { toast(e.message, true); } } }));
    }));
  } catch (e) { /* the library is optional */ }
}
async function uploadBroll(file) {
  if (!file) return;
  const form = new FormData(); form.append('file', file); form.append('keywords', $('brBrollKeywords').value);
  try { await api('/api/brand/broll', { method: 'POST', body: form }); $('brBrollKeywords').value = ''; await refreshBroll(); toast('Clip added'); }
  catch (e) { toast(e.message, true); }
}

/* ---------- Audio-reactive lyric video ---------- */
async function runSongVisualizer() {
  const b = bridge(); const id = b && b.state().id;
  if (!id) { toast('Open or upload a song first.', true); return; }
  if (song.busy) return;
  song.busy = true; const button = $('autoVizBtn'); button.disabled = true; const status = $('autoStatus');
  try {
    const { job_id } = await post('/api/projects/' + id + '/visualizer', { style: $('autoVizStyle').value, lyrics: true });
    const job = await runJob(job_id, (j) => showStatus(status, j));
    status.textContent = 'Done. Your audio-reactive video is ready.';
    $('autoResults').replaceChildren(el('div', { class: 'auto-result' }, el('strong', { text: job.outputs.lyrics ? 'Audio-reactive lyric video' : 'Music visualizer' }),
      el('video', { controls: true, preload: 'metadata', src: job.outputs.video }),
      el('a', { class: 'download-btn', href: job.outputs.video, download: '', text: 'Download video' })));
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Visualizer stopped: ' + e.message; toast(e.message, true); }
  finally { song.busy = false; button.disabled = false; }
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
on('directorRefreshAssets','click',refreshCurrentDirector);
on('directorCapture','click',captureDirector);
on('creatorVoiceFile','change',()=>{const f=$('creatorVoiceFile').files?.[0];if(f){creatorVoiceTake=f;playCreatorTake(f);}});
on('creatorRecordVoice','click',recordCreatorVoice);
on('creatorStopVoice','click',()=>creatorVoiceRecorder?.stop());
on('creatorProductionMode','change',()=>{$('creatorModeHint').textContent=$('creatorProductionMode').value==='research'?'Enter one confirmed claim | https://source per line. Sources are supplied by you, not independently verified.':'Use actual captures and confirmed product facts.';});
on('creatorScript','input',refreshCreatorStats);
on('creatorSpeed','input',refreshCreatorStats);
on('creatorDelivery','change',refreshCreatorStats);
on('creatorVoice','change',refreshCreatorStats);
on('creatorDraft','click',draftCreator);
on('creatorAudition','click',auditionCreator);
on('creatorPrepare','click',()=>createVideo(false));
on('creatorRender','click',()=>createVideo(true));
on('directorCaptureStop','click',()=>directorRecording?.stop());
on('directorPlan','click',()=>runDirector(false));
on('directorRun','click',()=>runDirector(true));
on('autopilotFromReview', 'click', runAutopilot);
on('autoFindShorts', 'click', findShorts);
on('autoRenderShorts', 'click', renderPickedShorts);
on('openClipStudio', 'click', () => openStudio(null));
on('clipStudioClose', 'click', closeStudio);
on('clipPick', 'click', () => $('clipFile').click());
on('clipFile', 'change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadSource(f); e.target.value = ''; });
on('clipRegen', 'click', regenerate);
on('autoEditRun', 'click', runAutoEdit);
on('aePreset', 'change', pickPreset);
on('aePresetSave', 'click', savePreset);
on('aePresetDelete', 'click', deletePreset);
on('proofOpen', 'click', openProof);
on('proofApply', 'click', applyProof);
on('proofClose', 'click', () => $('proofModal').classList.add('hidden'));
on('autoVizBtn', 'click', runSongVisualizer);
on('makeBrand', 'click', openBrand);
on('brBrollPick', 'click', () => $('brBrollFile').click());
on('brBrollFile', 'change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadBroll(f); e.target.value = ''; });
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
window.SkellyUI = { api, send, post, el, runJob, showStatus, copyButton, toast, clock, stageText };
})();
