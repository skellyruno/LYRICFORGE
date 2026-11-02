(() => {
'use strict';
const $ = (id) => document.getElementById(id);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const defaultSettings = () => ({aspect:'portrait',resolution:'720p',mode:'line',animation:'pop',font:'Arial',fontSize:60,textColor:'#FFFFFF',accentColor:'#81FF71',outline:2.5,position:55,background:'midnight',dim:.15,upper:false});
const backgrounds = {midnight:['#101418','#020605','#6fff87'],acid:['#15372b','#07120f','#72ff68'],violet:['#35244a','#0e0c1c','#bb8cfa'],crimson:['#4b1d2d','#130911','#fb5d88'],ocean:['#16445d','#06121f','#6be4ff'],noir:['#282b31','#050505','#b3b8bc']};
const state = {id:null, title:'Untitled project', duration:0, lines:[], settings:defaultSettings(), time:0, playing:false, selected:0, demo:false, zoom:1, sourceObjectUrl:null, backgroundUrl:null, pendingSave:null, backgroundIsVideo:false, waveform:[]};
const audio=$('songAudio'), canvas=$('previewCanvas'), ctx=canvas.getContext('2d'), bgImg=$('backgroundImage'),bgVid=$('backgroundVideo');
let lastFrame=performance.now(), lastPreviewPaint=0, pollTimer=null, backgroundVersion=0;
let resizeTimer=null;
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const shortTime=(seconds)=>`${Math.floor(Math.max(0,seconds)/60).toString().padStart(2,'0')}:${Math.floor(Math.max(0,seconds)%60).toString().padStart(2,'0')}`;
const prettyTime=(x)=>Number(x||0).toFixed(2);
const safe=(s)=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const trimLine=(s)=>s.length>95?s.slice(0,92)+'…':s;
const toast=(msg,error=false)=>{const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=msg;$('toasts').appendChild(el);setTimeout(()=>el.remove(),4700);};
function api(path,options={}){return fetch(path,options).then(async response=>{if(!response.ok){let reason;try{reason=(await response.json()).detail;}catch{}throw Error(typeof reason==='string'?reason:`Request failed (${response.status})`);}return response.json();});}
function renderTitle(){$('projectTitle').textContent=state.title;$('trackName').textContent=state.id||state.demo?state.title:'No audio loaded';$('totalTime').textContent=shortTime(state.duration);$('exportDuration').textContent=shortTime(state.duration);$('clipCount').textContent=`${state.lines.length} clip${state.lines.length===1?'':'s'}`;const enabled=!!state.id;['topExport','saveBtn','renderBtn'].forEach(x=>$(x).disabled=!enabled);$('addLineBtn').disabled=!state.id&&!state.demo;$('projectStatus').textContent=state.demo?'Demo · upload to export':state.id?'Editing':'Ready to create';}
function panel(name){if(name==='storage')loadStorage();$$('.rail-item').forEach(b=>b.classList.toggle('active',b.dataset.panel===name));$$('.panel').forEach(p=>p.classList.toggle('hidden',p.id!==`panel-${name}`));}
function setSetting(name,value){
 if(state.settings[name]===value)return;
 state.settings[name]=value;
 // Do not reset every input and recalculate preview geometry on each slider
 // tick. This avoids snapping sliders and expensive layout during dragging.
 const labels={fontSize:['fontSizeVal',value+'px'],position:['positionVal',value+'%'],
   outline:['outlineVal',String(value)],dim:['dimVal',Math.round(value*100)+'%'],
   textColor:['textColorVal',String(value).toUpperCase()],
   accentColor:['accentColorVal',String(value).toUpperCase()]};
 if(labels[name])$(labels[name][0]).textContent=labels[name][1];
 if(['mode','animation','background','aspect'].includes(name)){
   $('[data-'+name+']').forEach(button=>button.classList.toggle('selected',button.dataset[name]===value));
 }
 if(name==='aspect'){
   const labels={portrait:'9:16 · VERTICAL',landscape:'16:9 · HORIZONTAL',square:'1:1 · SQUARE'};
   $('canvasFormat').textContent=labels[value];resizePreview();
 }
 queueSave();
}

const looks={
 neon:{mode:'karaoke',animation:'pop',font:'Impact',fontSize:65,textColor:'#FFFFFF',accentColor:'#81FF71',outline:3,background:'acid',dim:.15,upper:true},
 minimal:{mode:'line',animation:'fade',font:'Arial',fontSize:53,textColor:'#FFFFFF',accentColor:'#FFFFFF',outline:1,background:'noir',dim:.05,upper:false},
 dream:{mode:'line',animation:'blur',font:'Georgia',fontSize:57,textColor:'#FFFFFF',accentColor:'#BB8CFA',outline:2,background:'violet',dim:.16,upper:false},
 bold:{mode:'line',animation:'bounce',font:'Impact',fontSize:78,textColor:'#FFFFFF',accentColor:'#FB5D88',outline:4,background:'crimson',dim:.23,upper:true}
};
function applyLook(name){if(!looks[name])return;state.settings={...state.settings,...looks[name]};syncSettingUI();resizePreview();queueSave();toast('Applied '+name+' look to all lyrics');}
function shiftSelected(delta){const line=state.lines[state.selected];if(!line)return;const originalStart=line.start,originalEnd=line.end;const duration=originalEnd-originalStart;const moved=clamp(originalStart+delta,0,Math.max(0,state.duration-duration));line.start=moved;line.end=moved+duration;retimeWords(line,originalStart,originalEnd);renderLines();renderTimeline();queueSave();}
const fileSize=bytes=>bytes>=1024**3?(bytes/1024**3).toFixed(2)+' GB':bytes>=1024**2?(bytes/1024**2).toFixed(1)+' MB':bytes>=1024?(bytes/1024).toFixed(1)+' KB':bytes+' B';
async function loadStorage(){try{const params=state.id?'?keep_project_id='+encodeURIComponent(state.id):'';const d=await api('/api/storage'+params);$('storageUsed').textContent=fileSize(d.workspace_bytes);$('storageExports').textContent=fileSize(d.exports_bytes);$('storageReclaim').textContent=fileSize(d.cleanup_bytes)+' · '+d.cleanup_files+' files';$('storageProjects').textContent=d.projects;}catch(e){toast('Storage info unavailable: '+e.message,true);}}
async function cleanupStorage(){try{const params=state.id?'?keep_project_id='+encodeURIComponent(state.id):'';const data=await api('/api/storage'+params);if(!data.cleanup_files){toast('No old render files to clean.');return;}if(!confirm('Delete '+data.cleanup_files+' generated files from OTHER projects and free about '+fileSize(data.cleanup_bytes)+'? Original songs, edits, backgrounds, the current video, and AI models are kept.'))return;const result=await api('/api/storage/cleanup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keep_project_id:state.id,confirm:true})});toast('Cleaned '+result.removed_files+' files · Freed '+fileSize(result.freed_bytes));loadStorage();}catch(e){toast('Cleanup failed: '+e.message,true);}}
function syncSettingUI(){const s=state.settings;
 ['font','fontSize','position','textColor','accentColor','outline','dim','upper','resolution'].forEach(k=>{if($(k))$(k).type==='checkbox'?$(k).checked=!!s[k]:$(k).value=s[k]});
 $('fontSizeVal').textContent=`${s.fontSize}px`;$('positionVal').textContent=`${s.position}%`;$('outlineVal').textContent=s.outline;
 $('dimVal').textContent=`${Math.round(s.dim*100)}%`;$('textColorVal').textContent=s.textColor.toUpperCase();$('accentColorVal').textContent=s.accentColor.toUpperCase();
 $$('[data-mode]').forEach(x=>x.classList.toggle('selected',x.dataset.mode===s.mode));
 $$('[data-animation]').forEach(x=>x.classList.toggle('selected',x.dataset.animation===s.animation));
 $$('[data-background]').forEach(x=>x.classList.toggle('selected',x.dataset.background===s.background));
 $$('[data-aspect]').forEach(x=>x.classList.toggle('selected',x.dataset.aspect===s.aspect));
 const labels={portrait:'9:16 · VERTICAL',landscape:'16:9 · HORIZONTAL',square:'1:1 · SQUARE'};$('canvasFormat').textContent=labels[s.aspect];
}
function resizePreview(){const shapes={portrait:[450,800],landscape:[800,450],square:[650,650]};const [w,h]=shapes[state.settings.aspect];if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}const stage=$('stage');stage.style.aspectRatio=`${w}/${h}`;stage.style.height='min(100%, 660px)';}
function drawBackground(w,h,t){const s=state.settings;ctx.fillStyle='#060b07';ctx.fillRect(0,0,w,h);
 if(s.background==='custom'&&state.backgroundUrl){const media=state.backgroundIsVideo?bgVid:bgImg;const ready=state.backgroundIsVideo?media.readyState>=2:media.complete&&media.naturalWidth;if(ready){const mw=state.backgroundIsVideo?media.videoWidth:media.naturalWidth,mh=state.backgroundIsVideo?media.videoHeight:media.naturalHeight;const scale=Math.max(w/mw,h/mh);const W=mw*scale,H=mh*scale;try{ctx.drawImage(media,(w-W)/2,(h-H)/2,W,H);}catch{}}}
 else {const colors=backgrounds[s.background]||backgrounds.midnight;const g=ctx.createLinearGradient(0,0,w*.8,h);g.addColorStop(0,colors[0]);g.addColorStop(1,colors[1]);ctx.fillStyle=g;ctx.fillRect(0,0,w,h);const radial=ctx.createRadialGradient(w*.48,h*.32,0,w*.48,h*.32,h*.66);radial.addColorStop(0,colors[2]+'45');radial.addColorStop(1,'#00000000');ctx.fillStyle=radial;ctx.fillRect(0,0,w,h);}
 ctx.fillStyle=`rgba(0,0,0,${clamp(s.dim*.7,0,.6)})`;ctx.fillRect(0,0,w,h);
 const vignette=ctx.createRadialGradient(w/2,h*.45,h*.03,w/2,h*.45,Math.max(w,h)*.78);vignette.addColorStop(0,'#00000000');vignette.addColorStop(1,'#00000066');ctx.fillStyle=vignette;ctx.fillRect(0,0,w,h);
}
function wrapWords(words,maxWidth,makeFont){let rows=[[]];for(const word of words){const current=rows[rows.length-1];const probe=[...current,word].join(' ');if(current.length&&ctx.measureText(probe).width>maxWidth){rows.push([word]);}else current.push(word);}return rows;}
function activeLyric(t){const sorted=[...state.lines].sort((a,b)=>a.start-b.start);let current=null;for(let i=0;i<sorted.length;i++){const l=sorted[i],next=sorted[i+1];const end=next?Math.min(l.end,next.start):l.end;if(end-l.start<.10)continue;if(t>=l.start&&t<end)current={...l,end};}return current;}
function easing(t){return 1-Math.pow(1-clamp(t,0,1),3);}
function showText(t){const w=canvas.width,h=canvas.height,s=state.settings,ln=activeLyric(t);if(!ln)return;
 let text=s.upper?ln.text.toUpperCase():ln.text;const progress=clamp((t-ln.start)/Math.max(.03,ln.end-ln.start),0,1);
 const entry=clamp((t-ln.start)/.23,0,1),outro=clamp((ln.end-t)/.16,0,1);
 let alpha=1,scale=1,shift=0;
 if(s.animation==='fade')alpha=Math.min(entry,outro);
 if(s.animation==='pop'){scale=.8+.2*easing(entry);alpha=Math.min(1,entry*4,outro*4);}
 if(s.animation==='slide'){shift=(1-easing(entry))*h*.07;alpha=Math.min(1,entry*4,outro*4);}
 if(s.animation==='zoom'){scale=1.25-.25*easing(clamp((t-ln.start)/.30,0,1));alpha=Math.min(1,entry*5,outro*5);}
 if(s.animation==='bounce'){const x=clamp((t-ln.start)/.26,0,1);scale=x<.42?.65+(.5*x/.42):1.15-.15*easing((x-.42)/.58);alpha=Math.min(1,entry*6,outro*6);}
 if(s.animation==='blur'){alpha=Math.min(entry,outro);}
 let words=(ln.words||[]).length?ln.words.map(x=>({...x,text:s.upper?x.text.toUpperCase():x.text})):text.split(/\s+/).map(x=>({text:x,start:ln.start,end:ln.end}));
 if(s.mode==='word') {let active=words.find(x=>x.start<=t&&x.end>t)||words.find(x=>x.start<=t)||words[0];if(!active)return;text=active.text;words=[active];}
 if(s.animation==='typewriter'&&s.mode==='line')text=text.split(/\s+/).slice(0,Math.max(1,Math.ceil(progress*text.split(/\s+/).length))).join(' ');
 const nominal=Math.round(s.fontSize*w/720);let fs=nominal;const margin=w*.09;
 ctx.save();ctx.font=`800 ${fs}px "${s.font}",Arial,sans-serif`;
 const rawWords=s.mode==='karaoke'?words.map(x=>x.text):text.split(/\s+/);
 for(;fs>Math.max(15,nominal*.66);fs-=2){ctx.font=`800 ${fs}px "${s.font}",Arial,sans-serif`;if(wrapWords(rawWords,w-margin*2).length<=2)break;}
 const rows=wrapWords(rawWords,w-margin*2);
 let maxRow=rows.reduce((m,row)=>Math.max(m,ctx.measureText(row.join(' ')).width),0);
 if(maxRow>w-margin*2){fs*= (w-margin*2)/maxRow;ctx.font=`800 ${fs}px "${s.font}",Arial,sans-serif`;}
 ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineJoin='round';ctx.lineWidth=Math.max(0,s.outline*w/720*2);ctx.strokeStyle='rgba(5,10,8,.94)';ctx.shadowColor='rgba(0,0,0,.58)';ctx.shadowBlur=fs*.22;
 ctx.globalAlpha=alpha;
 if(s.animation==='blur')ctx.filter='blur('+((1-easing(clamp((t-ln.start)/.28,0,1)))*Math.max(2,fs*.09))+'px)';
 const lineHeight=fs*1.24,cy=h*(s.position/100)+shift;ctx.translate(w/2,cy);ctx.scale(scale,scale);
 if(s.mode==='karaoke'){
 let cursor=0;
 rows.forEach((row,i)=>{const y=(i-(rows.length-1)/2)*lineHeight;const total=ctx.measureText(row.join(' ')).width;let x=-total/2;row.forEach((str,j)=>{const wd=ctx.measureText(str).width;const word=words[cursor++];const active=word&&t>=word.start;ctx.textAlign='left';ctx.strokeText(str,x,y);ctx.fillStyle=active?s.accentColor:s.textColor;ctx.fillText(str,x,y);x+=wd+ctx.measureText(' ').width;});});
 }else{
 rows.forEach((row,i)=>{const str=row.join(' '),y=(i-(rows.length-1)/2)*lineHeight;ctx.strokeText(str,0,y);ctx.fillStyle=s.textColor;ctx.fillText(str,0,y);});
 }
 ctx.restore();
}
function drawFrame(now){
 requestAnimationFrame(drawFrame);
 // Prefer 30 fps while playing, 12 fps while editing and 4 fps during
 // modal/welcome screens. Keeps WebView responsive while Whisper uses the CPU.
 const covered=!$('welcome').classList.contains('hidden')||!$('reviewOverlay').classList.contains('hidden');
 const interval=document.hidden?250:covered?250:state.playing?33:80;
 if(now-lastPreviewPaint<interval)return;
 const elapsed=Math.min(.15,(now-lastFrame)/1000);lastFrame=now;lastPreviewPaint=now;
 if(state.demo&&state.playing){state.time+=elapsed;if(state.time>state.duration){state.time=0;state.playing=false;}}
 if(state.id&&state.playing&&isFinite(audio.currentTime))state.time=audio.currentTime;
 const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);drawBackground(w,h,state.time);showText(state.time);
 $('currentTime').textContent=shortTime(state.time);$('playButton').textContent=state.playing?'Ⅱ':'▶';
 const duration=state.duration||1;const timelineWidth=Math.max(0,$('timelineInner').clientWidth-110);$('playhead').style.left=`${110+timelineWidth*clamp(state.time/duration,0,1)}px`;
 if(state.backgroundIsVideo&&state.playing&&bgVid.paused)bgVid.play().catch(()=>{});
 if(state.backgroundIsVideo&&!state.playing&&!bgVid.paused)bgVid.pause();
}
function seek(seconds){state.time=clamp(seconds,0,state.duration);if(state.id&&audio.readyState)audio.currentTime=state.time;if(state.backgroundIsVideo&&Number.isFinite(bgVid.duration)&&bgVid.duration>0)bgVid.currentTime=state.time%bgVid.duration;}
function play(){if(!state.duration){toast('Upload a song to preview lyrics.');return;}state.playing=!state.playing;if(state.id){if(state.playing)audio.play().catch(e=>{state.playing=false;toast(e.message,true);});else audio.pause();}}
function selectLine(index,jump=false){state.selected=clamp(index,0,Math.max(0,state.lines.length-1));if(jump&&state.lines[state.selected])seek(state.lines[state.selected].start);renderLines();renderTimeline();}
function reflowWords(line){
 const parts=line.text.trim().split(/\s+/).filter(Boolean);
 if(line.words&&line.words.length===parts.length){line.words=line.words.map((w,i)=>({...w,text:parts[i]}));return;}
 line.words=parts.map((text,i)=>({text,start:line.start+(line.end-line.start)*i/parts.length,end:line.start+(line.end-line.start)*(i+1)/parts.length}));
}
function retimeWords(line,oldStart,oldEnd,sourceWords){
 const span=Math.max(.01,oldEnd-oldStart),newSpan=line.end-line.start;
 line.words=(sourceWords||line.words||[]).map(w=>({text:w.text,start:line.start+(w.start-oldStart)*newSpan/span,end:line.start+(w.end-oldStart)*newSpan/span}));
}
function renderLines(){const holder=$('lyricsEditor');if(!state.lines.length){holder.innerHTML='<div class="empty-caption"><div class="empty-caption-icon">♫</div><strong>No lyrics yet</strong><span>Upload a song to detect lyrics automatically.</span></div>';return;}
 holder.innerHTML=state.lines.map((l,i)=>`<div class="lyric-row ${i===state.selected?'selected':''}" data-line="${i}"><div class="lyric-row-top"><span class="lyric-n">LINE ${String(i+1).padStart(2,'0')}</span><div class="lyric-row-actions"><button data-action="jump" data-i="${i}" class="tiny-btn" title="Seek to lyric">▶</button><button data-action="delete" data-i="${i}" class="tiny-btn danger" title="Delete line">×</button></div></div><input class="lyric-input" data-text="${i}" value="${safe(l.text)}" aria-label="Line ${i+1} text"/><div class="timing-row"><label>IN<input type="number" data-start="${i}" step="0.01" min="0" max="${state.duration}" value="${prettyTime(l.start)}" /></label><span class="timing-arrow">→</span><label>OUT<input type="number" data-end="${i}" step="0.01" min="0" max="${state.duration}" value="${prettyTime(l.end)}" /></label></div></div>`).join('');
 holder.querySelectorAll('.lyric-row').forEach(el=>el.addEventListener('click',e=>{if(e.target.closest('input,button'))return;selectLine(+el.dataset.line,true)}));
 holder.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{const i=+b.dataset.i;if(b.dataset.action==='jump'){selectLine(i,true);return;}state.lines.splice(i,1);selectLine(Math.min(i,state.lines.length-1));queueSave();}));
 holder.querySelectorAll('.lyric-input').forEach(el=>el.addEventListener('input',()=>{const ln=state.lines[+el.dataset.text];ln.text=el.value;reflowWords(ln);renderTimeline();queueSave();}));
 holder.querySelectorAll('input[data-start],input[data-end]').forEach(el=>el.addEventListener('change',()=>{const i=+(el.dataset.start??el.dataset.end),ln=state.lines[i];const start=el.hasAttribute('data-start');const oldStart=ln.start,oldEnd=ln.end;const val=Number(el.value);if(!Number.isFinite(val))return;if(start)ln.start=clamp(val,0,Math.max(0,ln.end-.06));else ln.end=clamp(val,ln.start+.06,state.duration);retimeWords(ln,oldStart,oldEnd);renderLines();renderTimeline();queueSave();}));
}
function renderTimeline(){const d=state.duration||1;const clips=$('lyricTrack');clips.innerHTML=state.lines.map((l,i)=>`<div class="lyric-clip ${i===state.selected?'selected':''}" data-index="${i}" style="left:${clamp(100*l.start/d,0,100)}%;width:${clamp(100*(l.end-l.start)/d,.3,100)}%;"><span class="clip-grab"></span>${safe(trimLine(l.text))}</div>`).join('');
 $('clipCount').textContent=`${state.lines.length} clips`;$('timelineInner').style.width=`${Math.max(100,state.zoom*100)}%`;
 const ruler=$('ruler');ruler.innerHTML='';const interval=d<45?5:d<150?15:d<360?30:60;for(let s=0;s<d;s+=interval){const tick=document.createElement('span');tick.className='tick';tick.style.left=`${s/d*100}%`;tick.textContent=shortTime(s);ruler.appendChild(tick);}
 drawWaveform();
 clips.querySelectorAll('.lyric-clip').forEach(el=>el.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();const i=+el.dataset.index;const line=state.lines[i];state.selected=i;const trackRect=clips.getBoundingClientRect(),startX=e.clientX;const originalStart=line.start,originalEnd=line.end,originalWords=line.words.map(w=>({...w}));const resize=e.target.classList.contains('clip-grab');selectLine(i,false);const move=evt=>{const diff=(evt.clientX-startX)/trackRect.width*d;if(resize){line.start=clamp(originalStart+diff,0,line.end-.1)}else{const len=originalEnd-originalStart;line.start=clamp(originalStart+diff,0,Math.max(0,d-len));line.end=line.start+len;}retimeWords(line,originalStart,originalEnd,originalWords);
 // Update just the dragged clip; rebuilding hundreds of clips each pointer
 // event causes the editor to stutter and invalidates drag targets.
 const live=clips.querySelector('.lyric-clip[data-index="'+i+'"]');
 if(live){live.style.left=clamp(100*line.start/d,0,100)+'%';live.style.width=clamp(100*(line.end-line.start)/d,.3,100)+'%';}
};const up=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);renderLines();renderTimeline();queueSave();};window.addEventListener('pointermove',move);window.addEventListener('pointerup',up,{once:true});}));
}
function drawWaveform(){
 const holder=$('audioWave');holder.style.backgroundImage='none';
 let wave=holder.querySelector('canvas');if(!wave){wave=document.createElement('canvas');holder.appendChild(wave);}
 const W=Math.max(1,Math.floor(holder.clientWidth||1000)),H=62,dpr=1;
 wave.width=W*dpr;wave.height=H*dpr;wave.style.width='100%';wave.style.height='62px';
 const c=wave.getContext('2d');c.clearRect(0,0,W,H);
 const peaks=state.waveform||[];if(!peaks.length)return;
 c.fillStyle='rgba(15,44,24,.65)';c.fillRect(0,0,W,H);
 const n=peaks.length, step=W/n;
 for(let i=0;i<n;i++){
   const amp=clamp(peaks[i],.025,1);const height=Math.max(2,amp*26);
   c.fillStyle=i%2?'#6fbb69':'#89e17f';c.globalAlpha=.7;
   c.fillRect(Math.floor(i*step),H/2-height,Math.max(1.2,step*.67),height*2);
 }
 c.globalAlpha=1;
}
async function loadWaveform(){if(!state.id)return;const id=state.id;try{const result=await api(`/api/projects/${id}/waveform`);if(state.id===id){state.waveform=result.peaks||[];drawWaveform();}}catch{}}
function queueSave(){if(!state.id)return;clearTimeout(state.pendingSave);state.pendingSave=setTimeout(()=>save(),950);}
async function save(){if(!state.id||!state.lines.length)return;clearTimeout(state.pendingSave);try{await api(`/api/projects/${state.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:state.settings,lines:state.lines})});$('projectStatus').textContent='Changes saved';}catch(e){toast(`Save failed: ${e.message}`,true);}}
function configureMedia(){if(state.id){audio.src=`/api/projects/${state.id}/audio`;audio.load();}else{audio.removeAttribute('src');audio.load();}
 $('totalTime').textContent=shortTime(state.duration);$('exportDuration').textContent=shortTime(state.duration);}
function prepareNewSongUI(){
 state.playing=false;audio.pause();$('welcome').classList.add('hidden');$('reviewOverlay').classList.remove('hidden');
 $('transcribeProgress').classList.remove('hidden');$('lyricsText').classList.add('hidden');
 $('lyricsText').value='';$('reviewTitle').textContent='Finding your lyrics…';
 $('reviewDescription').textContent='Analyzing the vocal and mapping words to timestamps.';
 $('confirmLyrics').disabled=true;$('reviewWarning').classList.add('hidden');
 updateTranscriptProgress({transcription_stage:'queued',transcription_progress:0});
}
async function finishNewSong(data,title){
 state.id=data.id;state.title=title;state.duration=data.duration;state.demo=false;state.lines=[];
 state.waveform=[];state.time=0;state.settings=defaultSettings();state.backgroundUrl=null;
 state.backgroundIsVideo=false;syncSettingUI();resizePreview();configureMedia();renderTitle();
 renderTimeline();renderLines();localStorage.setItem('lyricforge-last',state.id);
 await waitForTranscript(state.id);
}
async function startUpload(file){
 if(!file)return;
 if(!/\.(mp3|wav|flac|m4a|aac|ogg|opus|mp4|webm)$/i.test(file.name)){
   toast('Please upload an audio file (MP3, WAV, M4A, FLAC, etc.)',true);return;
 }
 prepareNewSongUI();
 let data;
 try{const fd=new FormData();fd.append('file',file);data=await api('/api/projects',{method:'POST',body:fd});}
 catch(e){toast('Song import failed: '+e.message,true);$('reviewOverlay').classList.add('hidden');$('welcome').classList.remove('hidden');return;}
 await finishNewSong(data,file.name.replace(/\.[^.]+$/,''));
}
async function chooseSong(){
 const bridge=window.pywebview?.api;
 if(document.documentElement.classList.contains('desktop-mode')&&bridge?.choose_audio){
   try{
     const data=await bridge.choose_audio(); // Native file dialog and safe Python-side copy
     if(!data)return; // The user cancelled
     prepareNewSongUI();
     await finishNewSong(data,data.title||'My song');
   }catch(e){toast('Unable to import song: '+(e.message||String(e)),true);
     $('reviewOverlay').classList.add('hidden');if(!state.id)$('welcome').classList.remove('hidden');}
   return;
 }
 // Normal browser and fallback if pywebview is not initialized yet.
 $('audioFile').click();
}
function updateTranscriptProgress(project){
 const stage=project.transcription_stage||'queued';
 const done=Number.isFinite(project.transcription_progress)?Math.max(0,Math.min(99,project.transcription_progress)):0;
 const label=$('transcribeProgress').querySelector('strong');
 const detail=$('transcribeProgress').querySelector('span');
 if(stage==='loading_model'){
   label.textContent='Preparing your AI lyric engine…';
   detail.textContent='Using the same Whisper model already saved on your computer.';
 }else if(stage==='recognizing'){
   label.textContent='Finding lyrics · '+done+'% of audio analyzed';
   detail.textContent='Syncing words as they are recognized. Longer songs take more time.';
 }else{
   label.textContent='Preparing your song…';
   detail.textContent='Your original song is safe. Transcription starts automatically.';
 }
 const bar=$('transcribeMeter');if(bar)bar.style.width=done+'%';
 const progress=$('transcribeMeterTrack');if(progress)progress.setAttribute('aria-valuenow',String(done));
}
async function waitForTranscript(projectId){for(let attempts=0;attempts<300;attempts++){if(state.id!==projectId)return;try{const project=await api(`/api/projects/${projectId}`);if(project.status==='transcribing')updateTranscriptProgress(project);if(project.status==='review'||project.status==='editor'){if(project.status==='editor'){loadProjectData(project);$('reviewOverlay').classList.add('hidden');return;}$('transcribeProgress').classList.add('hidden');$('lyricsText').classList.remove('hidden');$('lyricsText').value=project.draft_lyrics||'';$('reviewTitle').textContent='Review your lyrics.';$('reviewDescription').textContent='Correct any misheard words and put each lyric line on a new line. Your edits are applied before syncing.';$('confirmLyrics').disabled=!$('lyricsText').value.trim();if(project.transcription_error){const warning=$('reviewWarning');warning.textContent='Automatic transcription was unavailable: '+project.transcription_error+'. You can still paste your lyrics and create a video, but manual timing adjustments may be needed.';warning.classList.remove('hidden');}else if(!project.draft_lyrics){const warning=$('reviewWarning');warning.textContent='No clear vocals were detected. You can paste lyrics manually, though the timing will only be an estimate.';warning.classList.remove('hidden');}return;}}catch(e){toast(e.message,true);return;}await new Promise(r=>setTimeout(r,1400));}
 $('transcribeProgress').classList.add('hidden');$('lyricsText').classList.remove('hidden');$('reviewTitle').textContent='Enter your lyrics.';$('confirmLyrics').disabled=false;toast('Transcription timed out. You can paste the lyrics manually.',true);
}
function loadProjectData(project){state.id=project.id;state.title=project.title;state.duration=project.duration;state.lines=project.lines||[];state.settings={...defaultSettings(),...(project.settings||{})};state.demo=false;state.time=0;state.selected=0;state.playing=false;state.waveform=[];state.backgroundUrl=project.background_file?`/api/projects/${state.id}/background?v=${Date.now()}`:null;state.backgroundIsVideo=!!project.background_file&&/\.(mp4|mov|webm)$/i.test(project.background_file);refreshBackgroundMedia();
 $('welcome').classList.add('hidden');$('reviewOverlay').classList.add('hidden');syncSettingUI();resizePreview();configureMedia();renderTitle();renderTimeline();renderLines();loadWaveform();}
async function confirmLyrics(){const lyrics=$('lyricsText').value.trim();if(!lyrics){toast('Add or correct your lyrics first.',true);return;}$('confirmLyrics').disabled=true;try{const result=await api(`/api/projects/${state.id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lyrics})});state.lines=result.lines;state.selected=0;$('reviewOverlay').classList.add('hidden');renderTitle();renderLines();renderTimeline();loadWaveform();queueSave();toast('Lyrics confirmed! You can edit text and timing below.');}catch(e){toast(e.message,true);}finally{$('confirmLyrics').disabled=false;}}
function refreshBackgroundMedia(){if(!state.backgroundUrl)return;if(state.backgroundIsVideo){bgVid.src=state.backgroundUrl;bgVid.load();bgVid.currentTime=state.time;bgImg.src='';}else{bgImg.src=state.backgroundUrl;bgVid.pause();bgVid.removeAttribute('src');}}
function applyImportedBackground(response,name){
 state.backgroundUrl=response.background_url+'?v='+Date.now();
 state.backgroundIsVideo=/\.(mp4|mov|webm)$/i.test(response.name);
 $('backgroundFileInfo').classList.remove('hidden');
 $('backgroundFileInfo').textContent='✓ '+name;
 refreshBackgroundMedia();setSetting('background','custom');toast('Background added.');
}
async function uploadBackground(file){
 if(!file)return;
 if(!state.id){toast('Upload a song before adding a custom background.',true);return;}
 const form=new FormData();form.append('file',file);
 try{
   const response=await api('/api/projects/'+state.id+'/background',{method:'POST',body:form});
   applyImportedBackground(response,file.name);
 }catch(e){toast('Background import failed: '+e.message,true);}
}
async function chooseBackground(){
 if(!state.id){toast('Upload a song before adding a background.',true);return;}
 const bridge=window.pywebview?.api;
 if(document.documentElement.classList.contains('desktop-mode')&&bridge?.choose_background){
   try{const result=await bridge.choose_background(state.id);if(result)applyImportedBackground(result,result.name);}
   catch(e){toast('Background import failed: '+(e.message||String(e)),true);}
   return;
 }
 $('backgroundFile').click();
}
function loadDemo(){const texts=['I WAS LOST INSIDE THE STATIC','NOW THE CITY KNOWS MY NAME','EVERY SHADOW HAS A STORY','WATCH ME TURN IT INTO FLAMES','I CAME BACK FROM THE DARK','AND I BROUGHT THE LIGHT WITH ME'];state.id=null;state.demo=true;state.title='DEMO / AFTER DARK';state.duration=24;state.time=2;state.waveform=Array.from({length:120},(_,i)=>.14+.42*Math.abs(Math.sin(i*7.1)*Math.cos(i*.9)));state.lines=texts.map((text,i)=>{const start=i*4;const line={id:String(i),start,end:start+3.7,text,words:[]};reflowWords(line);return line;});state.settings=defaultSettings();state.selected=0;$('welcome').classList.add('hidden');syncSettingUI();resizePreview();renderTitle();renderTimeline();renderLines();toast('Demo mode — upload your own song to enable MP4 export.');}
async function exportVideo(){if(!state.id){toast('Upload your song to export a lyric video.',true);return;}if(!state.lines.length){toast('Add some lyric lines before exporting.',true);return;}panel('export');$('renderBtn').disabled=true;$('downloadBtn').classList.add('hidden');$('renderStatus').classList.remove('hidden');$('renderStatus').textContent='Preparing video render…';
 try{const {job_id}=await api(`/api/projects/${state.id}/render`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:state.lines,settings:state.settings})});for(let i=0;i<900;i++){await new Promise(r=>setTimeout(r,1200));const job=await api(`/api/jobs/${job_id}`);if(job.status==='done'){$('renderStatus').textContent='✓ Render complete. Your MP4 is ready.';const dl=$('downloadBtn');dl.href=job.download;dl.classList.remove('hidden');toast('Video export finished!');return;}if(job.status==='error')throw Error(job.error||'Rendering failed');$('renderStatus').textContent=`Rendering your video… ${Math.floor((i+1)*1.2)}s elapsed`; }throw Error('Render timed out after 18 minutes.');}catch(e){$('renderStatus').textContent='Render failed: '+e.message;toast(e.message,true);}finally{$('renderBtn').disabled=false;}}
function wireUI(){
 $$('.rail-item').forEach(b=>b.addEventListener('click',()=>panel(b.dataset.panel)));
 $$('[data-preset]').forEach(b=>b.addEventListener('click',()=>applyLook(b.dataset.preset)));
 $('nudgeBack').addEventListener('click',()=>shiftSelected(-.05));
 $('nudgeForward').addEventListener('click',()=>shiftSelected(.05));
 $('refreshStorage').addEventListener('click',loadStorage);
 $('cleanupStorage').addEventListener('click',cleanupStorage);
 ['font','fontSize','position','textColor','accentColor','outline','dim','resolution'].forEach(k=>$(k).addEventListener('input',e=>setSetting(k,k==='fontSize'||k==='position'||k==='outline'||k==='dim'?Number(e.target.value):e.target.value)));
 $('upper').addEventListener('change',e=>setSetting('upper',e.target.checked));
 ['mode','animation','background','aspect'].forEach(key=>$$(`[data-${key}]`).forEach(b=>b.addEventListener('click',()=>setSetting(key,b.dataset[key]))));
 $('heroUpload').addEventListener('click',chooseSong);
 $('backgroundUploadTrigger').addEventListener('click',chooseBackground);
 $('audioFile').addEventListener('change',e=>{startUpload(e.target.files[0]);e.target.value='';});
 $('backgroundFile').addEventListener('change',e=>{uploadBackground(e.target.files[0]);e.target.value='';});
 $('lyricsText').addEventListener('input',()=>{$('confirmLyrics').disabled=!$('lyricsText').value.trim();});
 $('confirmLyrics').addEventListener('click',confirmLyrics);
 $('closeReview').addEventListener('click',()=>{$('reviewOverlay').classList.add('hidden');if(!state.lines.length)$('welcome').classList.remove('hidden');});
 $('demoBtn').addEventListener('click',loadDemo);
 $('playButton').addEventListener('click',play);$('skipBack').addEventListener('click',()=>seek(state.time-5));$('skipAhead').addEventListener('click',()=>seek(state.time+5));
 $('zoomIn').addEventListener('click',()=>{state.zoom=clamp(state.zoom+.25,1,5);$('zoomDisplay').textContent=`${Math.round(state.zoom*100)}%`;renderTimeline();});
 $('zoomOut').addEventListener('click',()=>{state.zoom=clamp(state.zoom-.25,1,5);$('zoomDisplay').textContent=`${Math.round(state.zoom*100)}%`;renderTimeline();});
 $('timelineInner').addEventListener('click',e=>{if(e.target.closest('.lyric-clip'))return;const rect=$('ruler').getBoundingClientRect();seek(((e.clientX-rect.left)/rect.width)*state.duration);});
 $('saveBtn').addEventListener('click',()=>{save();toast('Saving project…');});
 $('topExport').addEventListener('click',()=>panel('export'));
 $('renderBtn').addEventListener('click',exportVideo);
 $('addLineBtn').addEventListener('click',()=>{let start=clamp(state.time,0,Math.max(0,state.duration-.5));let line={id:Math.random().toString(16).slice(2,12),text:'New lyric',start,end:Math.min(state.duration,start+2),words:[]};reflowWords(line);state.lines.push(line);state.lines.sort((a,b)=>a.start-b.start);selectLine(state.lines.indexOf(line),true);queueSave();});
 $('newBtn').addEventListener('click',()=>{if(state.id&&state.lines.length&&!confirm('Start a new project? Your current changes are saved locally.'))return;state.playing=false;audio.pause();state.id=null;state.demo=false;state.lines=[];state.waveform=[];state.duration=0;state.time=0;state.title='Untitled project';state.settings=defaultSettings();state.backgroundUrl=null;state.selected=0;localStorage.removeItem('lyricforge-last');$('welcome').classList.remove('hidden');syncSettingUI();resizePreview();renderTitle();renderTimeline();renderLines();});
 $('previewFull').addEventListener('click',()=>{const stage=$('stage');if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});else stage.requestFullscreen?.().catch(()=>{});});
 window.addEventListener('resize',()=>{
   clearTimeout(resizeTimer);
   resizeTimer=setTimeout(()=>{resizePreview();drawWaveform();},100);
 });
 const hero=$('heroUpload');hero.addEventListener('dragover',e=>{e.preventDefault();hero.classList.add('drag-over');});hero.addEventListener('dragleave',()=>hero.classList.remove('drag-over'));hero.addEventListener('drop',e=>{e.preventDefault();hero.classList.remove('drag-over');if(e.dataTransfer.files.length)startUpload(e.dataTransfer.files[0]);});
 audio.addEventListener('ended',()=>{state.playing=false;});audio.addEventListener('pause',()=>{if(!audio.ended)state.playing=false;});audio.addEventListener('play',()=>{state.playing=true;});
 document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.code==='KeyS'){e.preventDefault();if(state.id)save();return;}if(e.altKey&&!e.ctrlKey&&!e.metaKey&&['ArrowLeft','ArrowRight'].includes(e.code)&&!e.target.closest('input,textarea,select')){e.preventDefault();shiftSelected(e.code==='ArrowLeft'?-.05:.05);return;}if(e.code==='Space'&&!e.repeat&&!e.target.closest('input,textarea,select,button')){e.preventDefault();play();}});
}
async function restore(){const last=localStorage.getItem('lyricforge-last');if(!last)return;try{const p=await api(`/api/projects/${last}`);if(p.status==='editor'&&p.lines?.length){loadProjectData(p);}else if(p.status==='review'||p.status==='transcribing'){state.id=p.id;state.title=p.title;state.duration=p.duration;configureMedia();renderTitle();$('welcome').classList.add('hidden');$('reviewOverlay').classList.remove('hidden');$('transcribeProgress').classList.remove('hidden');$('lyricsText').classList.add('hidden');$('confirmLyrics').disabled=true;waitForTranscript(p.id);}}catch{localStorage.removeItem('lyricforge-last');}}
wireUI();syncSettingUI();resizePreview();renderTimeline();requestAnimationFrame(drawFrame);restore();
})();
