(() => {
'use strict';
const $ = (id) => document.getElementById(id);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const defaultSettings = () => ({aspect:'portrait',resolution:'720p',renderSpeed:'balanced',fps:30,performanceMode:'balanced',encoder:'auto',mode:'line',animation:'pop',font:'Arial',fontSize:60,textColor:'#FFFFFF',accentColor:'#81FF71',outline:2.5,position:55,background:'midnight',dim:.15,upper:false});
const backgrounds = {midnight:['#101418','#020605','#6fff87'],acid:['#15372b','#07120f','#72ff68'],violet:['#35244a','#0e0c1c','#bb8cfa'],crimson:['#4b1d2d','#130911','#fb5d88'],ocean:['#16445d','#06121f','#6be4ff'],noir:['#282b31','#050505','#b3b8bc']};
const state = {id:null, title:'Untitled project', duration:0, lines:[], settings:defaultSettings(), time:0, playing:false, selected:0, demo:false, zoom:1, snap:false, sourceObjectUrl:null, backgroundUrl:null, pendingSave:null, backgroundIsVideo:false, waveform:[],persisted:false,dirty:false};
const audio=$('songAudio'), canvas=$('previewCanvas'), ctx=canvas.getContext('2d'), bgImg=$('backgroundImage'),bgVid=$('backgroundVideo');
let lastFrame=performance.now(), lastPreviewPaint=0, pollTimer=null, backgroundVersion=0;
let resizeTimer=null;
let saveSerial=Promise.resolve(), recoverySerial=Promise.resolve(), editRevision=0;
let transitionBusy=false,downloadBusy=false;
const undoHistory=[],redoHistory=[];
let lastEditKind='',lastEditAt=0;

const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const shortTime=(seconds)=>`${Math.floor(Math.max(0,seconds)/60).toString().padStart(2,'0')}:${Math.floor(Math.max(0,seconds)%60).toString().padStart(2,'0')}`;
const prettyTime=(x)=>Number(x||0).toFixed(2);
const safe=(s)=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const trimLine=(s)=>s.length>95?s.slice(0,92)+'…':s;
const toast=(msg,error=false)=>{const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=msg;$('toasts').appendChild(el);setTimeout(()=>el.remove(),4700);};
function api(path,options={}){return fetch(path,options).then(async response=>{if(!response.ok){let reason;try{reason=(await response.json()).detail;}catch{}throw Error(typeof reason==='string'?reason:`Request failed (${response.status})`);}return response.json();});}
function renderTitle(){updateEditButtons();syncClipInspector();$('projectTitle').textContent=state.title;$('trackName').textContent=state.id||state.demo?state.title:'No audio loaded';$('totalTime').textContent=shortTime(state.duration);$('exportDuration').textContent=shortTime(state.duration);$('clipCount').textContent=`${state.lines.length} clip${state.lines.length===1?'':'s'}`;const enabled=!!state.id;['topExport','saveBtn','renderBtn','renderPreviewBtn'].forEach(x=>$(x).disabled=!enabled);$('addLineBtn').disabled=!state.id&&!state.demo;$('projectStatus').textContent=state.demo?'Demo · upload to export':!state.id?'Ready to create':
 state.dirty?'Unsaved · crash recovery on':state.persisted?'Saved project':'Draft · not saved';}
function panel(name){if(name==='storage')loadStorage();if(name==='library')loadLibrary();if(name==='performance')loadPerformance(false);$$('.rail-item').forEach(b=>b.classList.toggle('active',b.dataset.panel===name));$$('.panel').forEach(p=>p.classList.toggle('hidden',p.id!==`panel-${name}`));}

function snapshotEdit(){return JSON.stringify({lines:state.lines,settings:state.settings,selected:state.selected});}
function updateEditButtons(){
 $('undoBtn').disabled=!undoHistory.length;
 $('redoBtn').disabled=!redoHistory.length;
 ['splitLineBtn','duplicateLineBtn','deleteLineBtn'].forEach(id=>$(id).disabled=!state.lines.length);
 $('exportSrtBtn').disabled=!state.lines.length;
}
function resetEditHistory(){
 undoHistory.length=0;redoHistory.length=0;lastEditKind='';lastEditAt=0;
 updateEditButtons();
}
function recordEdit(kind='edit'){
 if(!state.lines.length&&!state.demo&&!state.id)return;
 const now=Date.now();
 if(kind!==lastEditKind||now-lastEditAt>700){
   undoHistory.push(snapshotEdit());
   if(undoHistory.length>60)undoHistory.shift();
 }
 lastEditKind=kind;lastEditAt=now;
 redoHistory.length=0;updateEditButtons();
}
function restoreEdit(value){
 const previous=JSON.parse(value);
 state.lines=previous.lines;
 state.settings=previous.settings;
 state.selected=clamp(previous.selected,0,Math.max(0,state.lines.length-1));
 syncSettingUI();resizePreview();renderLines();renderTimeline();queueSave();syncClipInspector();
 updateEditButtons();
}
function undoEdit(){
 if(!undoHistory.length)return;
 redoHistory.push(snapshotEdit());
 const snapshot=undoHistory.pop();lastEditKind='';lastEditAt=0;
 restoreEdit(snapshot);toast('Undid last change');
}
function redoEdit(){
 if(!redoHistory.length)return;
 undoHistory.push(snapshotEdit());
 const snapshot=redoHistory.pop();lastEditKind='';lastEditAt=0;
 restoreEdit(snapshot);toast('Redid change');
}

function setSetting(name,value){
 if(state.settings[name]===value)return;
 recordEdit('setting:'+name);
 state.settings[name]=value;
 // Do not reset every input and recalculate preview geometry on each slider
 // tick. This avoids snapping sliders and expensive layout during dragging.
 const labels={fontSize:['fontSizeVal',value+'px'],position:['positionVal',value+'%'],
   outline:['outlineVal',String(value)],dim:['dimVal',Math.round(value*100)+'%'],
   textColor:['textColorVal',String(value).toUpperCase()],
   accentColor:['accentColorVal',String(value).toUpperCase()]};
 if(labels[name])$(labels[name][0]).textContent=labels[name][1];
 if(['mode','animation','background','aspect'].includes(name)){
   $$('[data-'+name+']').forEach(button=>button.classList.toggle('selected',button.dataset[name]===value));
 }
 if(name==='aspect'){
   const labels={portrait:'9:16 · VERTICAL',landscape:'16:9 · HORIZONTAL',square:'1:1 · SQUARE'};
   $('canvasFormat').textContent=labels[value];resizePreview();
 }
 if(name==='animation')renderTimeline();
 if(name==='fps')$('exportFpsLabel').textContent=value+' FPS';
 if(name==='performanceMode'){$('startupPerformance').value=value;try{localStorage.setItem('skellymotion-perf-mode',value)}catch{}}
 queueSave();
}

const looks={
 neon:{mode:'karaoke',animation:'pop',font:'Impact',fontSize:65,textColor:'#FFFFFF',accentColor:'#81FF71',outline:3,background:'acid',dim:.15,upper:true},
 minimal:{mode:'line',animation:'fade',font:'Arial',fontSize:53,textColor:'#FFFFFF',accentColor:'#FFFFFF',outline:1,background:'noir',dim:.05,upper:false},
 dream:{mode:'line',animation:'blur',font:'Georgia',fontSize:57,textColor:'#FFFFFF',accentColor:'#BB8CFA',outline:2,background:'violet',dim:.16,upper:false},
 bold:{mode:'line',animation:'bounce',font:'Impact',fontSize:78,textColor:'#FFFFFF',accentColor:'#FB5D88',outline:4,background:'crimson',dim:.23,upper:true}
};
function applyLook(name){if(!looks[name])return;recordEdit('look');state.settings={...state.settings,...looks[name]};syncSettingUI();resizePreview();queueSave();toast('Applied '+name+' look to all lyrics');}

const savedStyleKey='skellymotion-my-look-v1';
const styleFields=['mode','animation','font','fontSize','textColor','accentColor','outline','position','background','dim','upper'];
function saveCurrentLook(){
 try{
   const selected={};
   styleFields.forEach(k=>{selected[k]=state.settings[k]});
   if(selected.background==='custom')selected.background='midnight';
   localStorage.setItem(savedStyleKey,JSON.stringify(selected));
   toast('Your look was saved on this device.');
 }catch{toast('Could not save look in this browser.',true);}
}
function loadSavedLook(){
 try{
   const raw=localStorage.getItem(savedStyleKey);
   if(!raw){toast('Save a look first using ☆ Save my look.');return;}
   const stored=JSON.parse(raw);
   const sanitized={...defaultSettings(),...stored};
   // Only use keys we support, never a raw prototype or unrelated app setting.
   const next={...state.settings};
   styleFields.forEach(k=>{if(Object.prototype.hasOwnProperty.call(stored,k)&&
     Object.prototype.hasOwnProperty.call(sanitized,k))next[k]=sanitized[k]});
   recordEdit('look');
   state.settings=next;syncSettingUI();resizePreview();queueSave();
   toast('Applied your saved look.');
 }catch{toast('Saved look could not be read.',true);}
}
function resetCurrentLook(){
 recordEdit('look');
 state.settings={...defaultSettings(),aspect:state.settings.aspect,resolution:state.settings.resolution,
  performanceMode:state.settings.performanceMode,encoder:state.settings.encoder,fps:state.settings.fps};
 syncSettingUI();resizePreview();queueSave();toast('Reset visual styling.');
}

function shiftSelected(delta){const line=state.lines[state.selected];if(!line)return;recordEdit('nudge');const originalStart=line.start,originalEnd=line.end;const duration=originalEnd-originalStart;const moved=clamp(originalStart+delta,0,Math.max(0,state.duration-duration));line.start=moved;line.end=moved+duration;retimeWords(line,originalStart,originalEnd);renderLines();renderTimeline();queueSave();}

function clipId(){return typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID().slice(0,18):Math.random().toString(16).slice(2,15);}
function snapTime(t){return state.snap?Math.round(t*10)/10:t;}
function toggleSnap(){
 state.snap=!state.snap;
 const b=$('snapBtn');b.textContent=state.snap?'Snap 0.1s':'Snap OFF';
 b.setAttribute('aria-pressed',String(state.snap));b.classList.toggle('is-active',state.snap);
 toast(state.snap?'Snap enabled (0.1s)':'Snap disabled');
}
function deleteAt(i){
 if(!state.lines[i])return;
 if(state.lines.length===1){toast('Keep at least one lyric; you can edit its words instead.');return;}
 recordEdit('delete');state.lines.splice(i,1);state.selected=clamp(i,0,state.lines.length-1);
 renderTitle();renderLines();renderTimeline();queueSave();
}
function duplicateSelected(){
 const source=state.lines[state.selected];if(!source)return;
 const len=source.end-source.start;
 if(len<.1)return;
 let start=source.end+.05;
 if(start+len>state.duration)start=source.start-len-.05;
 if(start<0)start=Math.max(0,state.duration-len);
 const copy=JSON.parse(JSON.stringify(source));copy.id=clipId();
 copy.start=Math.max(0,start);copy.end=Math.min(state.duration,copy.start+len);
 if(copy.end-copy.start<.1){toast('Not enough room for another clip.',true);return;}
 recordEdit('duplicate');retimeWords(copy,source.start,source.end,source.words);
 state.lines.push(copy);state.lines.sort((a,b)=>a.start-b.start);
 state.selected=state.lines.indexOf(copy);renderTitle();renderLines();renderTimeline();
 seek(copy.start);queueSave();toast('Lyric duplicated');
}
function splitSelected(){
 const source=state.lines[state.selected];if(!source)return;
 const words=source.text.trim().split(/\s+/).filter(Boolean);
 if(words.length<2){toast('Split needs at least two words.');return;}
 if(source.end-source.start<.4){toast('Clip is too short to split.');return;}
 const mid=state.time>source.start+.2&&state.time<source.end-.2?state.time:(source.start+source.end)/2;
 const cut=clamp(mid,source.start+.2,source.end-.2);
 const count=clamp(Math.round((cut-source.start)/(source.end-source.start)*words.length),1,words.length-1);
 const left={...source,end:cut,text:words.slice(0,count).join(' '),words:[]};
 const right={...source,id:clipId(),start:cut,text:words.slice(count).join(' '),words:[]};
 reflowWords(left);reflowWords(right);recordEdit('split');
 state.lines.splice(state.selected,1,left,right);state.selected++;
 renderTitle();renderLines();renderTimeline();seek(cut);queueSave();toast('Lyric split');
}
function jumpClip(direction){
 if(!state.lines.length)return;
 state.selected=(state.selected+direction+state.lines.length)%state.lines.length;
 selectLine(state.selected,true);
}
function fitTimeline(){state.zoom=1;$('zoomDisplay').textContent='100%';$('timelineScroll').scrollLeft=0;renderTimeline();}
function exportSrt(){
 if(!state.lines.length)return;
 const lines=[...state.lines].sort((a,b)=>a.start-b.start);
 const time=t=>{const ms=Math.round(Math.max(0,t)*1000);
  return [Math.floor(ms/3600000),Math.floor(ms/60000)%60,Math.floor(ms/1000)%60].map(n=>String(n).padStart(2,'0')).join(':')+','+String(ms%1000).padStart(3,'0');};
 const blocks=[];
 lines.forEach((l,i)=>{const end=i+1<lines.length?Math.min(l.end,lines[i+1].start):l.end;
  if(end-l.start>=.1)blocks.push((blocks.length+1)+'\n'+time(l.start)+' --> '+time(end)+'\n'+l.text.trim());});
 if(!blocks.length){toast('No valid timed lyrics to export.',true);return;}
 const blob=new Blob([blocks.join('\n\n')+'\n'],{type:'text/plain;charset=utf-8'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;
 a.download=(state.title||'SkellyMotion').replace(/[^\w -]/g,'_').slice(0,70)+'.srt';
 document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);toast('SRT subtitles downloaded');
}
function showShortcuts(show){
 $('shortcutsOverlay').classList.toggle('hidden',!show);
 if(show)$('closeShortcuts').focus();
}

const layoutKey='skellymotion-layout-v1';
function saveLayout(){
 try{
  const app=$('app'),css=getComputedStyle(app);
  localStorage.setItem(layoutKey,JSON.stringify({
   panel:parseFloat(css.getPropertyValue('--panel-width'))||312,
   timeline:parseFloat(css.getPropertyValue('--timeline-height'))||210
  }));
 }catch{}
}
function restoreLayout(){
 try{
  const options=JSON.parse(localStorage.getItem(layoutKey)||'null');
  if(!options)return;
  const app=$('app');
  if(Number.isFinite(options.panel))app.style.setProperty('--panel-width',clamp(options.panel,240,470)+'px');
  if(Number.isFinite(options.timeline))app.style.setProperty('--timeline-height',clamp(options.timeline,145,400)+'px');
 }catch{}
}

function initResizer(id,axis,variable,initial,minValue,maxValue){
 const el=$(id),app=$('app');let down=null;
 const update=value=>{
  const max=axis==='x'?Math.min(maxValue,Math.max(minValue,app.offsetWidth-570)):Math.min(maxValue,Math.max(minValue,app.offsetHeight-310));
  app.style.setProperty(variable,clamp(value,minValue,max)+'px');
 };
 el.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;e.preventDefault();
  const scale=app.getBoundingClientRect().width/app.offsetWidth||1;
  down={coordinate:axis==='x'?e.clientX:e.clientY,
    value:parseFloat(getComputedStyle(app).getPropertyValue(variable))||initial,scale};
  el.setPointerCapture(e.pointerId);document.body.classList.add('resizing-studio');
 });
 el.addEventListener('pointermove',e=>{
  if(!down)return;
  const diff=((axis==='x'?e.clientX:e.clientY)-down.coordinate)/down.scale;
  update(down.value+(axis==='x'?diff:-diff));
 });
 const finish=()=>{if(!down)return;down=null;document.body.classList.remove('resizing-studio');resizePreview();drawWaveform();saveLayout()};
 ['pointerup','pointercancel','lostpointercapture'].forEach(event=>el.addEventListener(event,finish));
 el.addEventListener('dblclick',()=>{update(initial);resizePreview();drawWaveform();saveLayout()});
 el.addEventListener('keydown',e=>{
  const keys=axis==='x'?['ArrowLeft','ArrowRight']:['ArrowDown','ArrowUp'];
  if(!keys.includes(e.key))return;e.preventDefault();
  const sign=e.key===keys[0]?-1:1;
  update((parseFloat(getComputedStyle(app).getPropertyValue(variable))||initial)+20*sign);saveLayout();
 });
}


const selectedProjects=new Set();
let visibleProjects=[];
function updateDeleteSelection(){
 const count=selectedProjects.size,button=$('deleteSelectedProjects');
 button.disabled=count===0;button.textContent='Delete selected ('+count+')';
 const all=$('selectAllProjects');
 all.checked=visibleProjects.length>0&&visibleProjects.every(x=>selectedProjects.has(x.id));
 all.indeterminate=visibleProjects.some(x=>selectedProjects.has(x.id))&&!all.checked;
}
async function loadLibrary(){
 const saved=$('savedProjectsList'),drafts=$('draftProjectsList');
 saved.innerHTML='<p class="library-empty">Loading saved projects…</p>';
 drafts.innerHTML='<p class="library-empty">Loading crash-recovery drafts…</p>';
 try{
  const result=await api('/api/projects');
  const projects=result.projects||[],unsaved=result.drafts||[];
  visibleProjects=[...projects,...unsaved];
  const visibleIds=new Set(visibleProjects.map(item=>item.id));
  for(const id of [...selectedProjects])if(!visibleIds.has(id))selectedProjects.delete(id);
  const cards=(list)=>list.map(item=>{
   const date=Number.isFinite(item.updated_at)?new Date(item.updated_at*1000).toLocaleDateString():'';
   const status=item.save_state==='draft'?'Unsaved draft':
    item.status==='editor'?'Ready':item.status==='review'?'Review lyrics':
    item.status==='transcribing'?'Finding lyrics':'Saved';
   return '<div class="library-item"><input class="library-check" type="checkbox" '+
     'aria-label="Select '+safe(item.title)+'" data-select-project="'+safe(item.id)+'" '+
     (selectedProjects.has(item.id)?'checked':'')+' />'+
     '<div class="library-details"><strong title="'+safe(item.title)+'">'+safe(item.title)+'</strong>'+
     '<span>'+shortTime(item.duration||0)+' · '+status+' · '+date+
     (item.has_recovery?' · Recovery available':'')+'</span></div>'+
     '<button type="button" data-open-project="'+safe(item.id)+'">'+
     (item.save_state==='draft'?'Recover':'Open')+'</button></div>';
  }).join('');
  saved.innerHTML=projects.length?cards(projects):
   '<p class="library-empty">No permanently saved projects. Click Save while editing to keep one.</p>';
  drafts.innerHTML=unsaved.length?cards(unsaved):
   '<p class="library-empty">No unsaved drafts. Crash-recovery drafts will appear here.</p>';
  [saved,drafts].forEach(parent=>{
   parent.querySelectorAll('[data-open-project]').forEach(button=>
     button.addEventListener('click',()=>openSavedProject(button.dataset.openProject)));
   parent.querySelectorAll('[data-select-project]').forEach(box=>
     box.addEventListener('change',()=>{
      if(box.checked)selectedProjects.add(box.dataset.selectProject);
      else selectedProjects.delete(box.dataset.selectProject);
      updateDeleteSelection();
     }));
  });
  updateDeleteSelection();
 }catch(e){
  saved.innerHTML='<p class="library-empty">Could not load the project library.</p>';
  drafts.innerHTML='';toast(e.message,true);
 }
}
async function deleteSelectedProjects(){
 const ids=[...selectedProjects];
 if(!ids.length)return;
 const names=visibleProjects.filter(p=>ids.includes(p.id)).map(p=>p.title);
 if(!confirm('Permanently DELETE '+ids.length+' selected project(s)?\n\n'+
   names.slice(0,8).join('\n')+(names.length>8?'\n…and more':'')+
   '\n\nThis deletes their source copies, embedded renders and recovery files. '+
   'Your downloaded MP4s and Whisper model remain untouched.'))return;
 const button=$('deleteSelectedProjects');button.disabled=true;
 try{
  const result=await api('/api/projects/bulk-delete',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({project_ids:ids,confirm:true})
  });
  if(result.deleted_ids.includes(state.id))resetWorkspace();
  result.deleted_ids.forEach(id=>selectedProjects.delete(id));
  toast('Deleted '+result.count+' selected project(s).');await loadLibrary();
 }catch(e){toast('Could not delete selected projects: '+e.message,true);}
 finally{updateDeleteSelection();}
}
async function openSavedProject(id){
 if(!/^[0-9a-f]{32}$/.test(id))return;
 if(id===state.id){panel('lyrics');return;}
 try{
  const project=await api('/api/projects/'+id);
  if(!await mayLeaveProject())return;
  let recovered=null;
  if(project.has_recovery){
   if(confirm('A crash-recovery draft was found for "'+project.title+
      '".\n\nRecover the unsaved edits?')){
    recovered=await api('/api/projects/'+id+'/recovery');
   }
  }
  if(project.status==='editor'||(project.lines&&project.lines.length)){
   loadProjectData(project);
   if(recovered){
    state.lines=recovered.lines||[];
    state.settings={...defaultSettings(),...(recovered.settings||{})};
    state.dirty=true;syncSettingUI();resizePreview();renderLines();renderTimeline();
    $('projectStatus').textContent='Recovered · not yet saved';
   }
   panel('lyrics');localStorage.setItem('lyricforge-last',id);return;
  }
  resetEditHistory();
  state.id=project.id;state.title=project.title||'Untitled project';
  state.duration=project.duration||0;state.demo=false;state.lines=[];
  state.persisted=project.save_state!=='draft';state.dirty=!!recovered;
  state.selected=0;state.waveform=[];state.time=0;state.playing=false;
  state.settings={...defaultSettings(),...(recovered?.settings||project.settings||{})};
  state.backgroundUrl=project.background_file?'/api/projects/'+id+'/background?v='+Date.now():null;
  state.backgroundIsVideo=!!project.background_file&&/\.(mp4|mov|webm)$/i.test(project.background_file);
  refreshBackgroundMedia();syncSettingUI();resizePreview();configureMedia();renderTitle();renderTimeline();renderLines();
  $('welcome').classList.add('hidden');$('reviewOverlay').classList.remove('hidden');
  $('transcribeProgress').classList.remove('hidden');$('lyricsText').classList.add('hidden');
  $('confirmLyrics').disabled=true;
  if(recovered&&recovered.draft_lyrics)$('lyricsText').value=recovered.draft_lyrics;
  localStorage.setItem('lyricforge-last',id);notifyNativeSession();
  await waitForTranscript(id);
  if(recovered&&recovered.draft_lyrics){
   $('lyricsText').value=recovered.draft_lyrics;
   $('confirmLyrics').disabled=!$('lyricsText').value.trim();
   $('projectStatus').textContent='Recovered · not yet saved';
  }
 }catch(e){toast('Could not reopen project: '+e.message,true);}
}

const fileSize=bytes=>bytes>=1024**3?(bytes/1024**3).toFixed(2)+' GB':bytes>=1024**2?(bytes/1024**2).toFixed(1)+' MB':bytes>=1024?(bytes/1024).toFixed(1)+' KB':bytes+' B';
async function loadStorage(){try{const params=state.id?'?keep_project_id='+encodeURIComponent(state.id):'';const d=await api('/api/storage'+params);$('storageUsed').textContent=fileSize(d.workspace_bytes);$('storageExports').textContent=fileSize(d.exports_bytes);$('storageReclaim').textContent=fileSize(d.cleanup_bytes)+' · '+d.cleanup_files+' files';$('storageProjects').textContent=d.projects;}catch(e){toast('Storage info unavailable: '+e.message,true);}}
async function cleanupStorage(){try{const params=state.id?'?keep_project_id='+encodeURIComponent(state.id):'';const data=await api('/api/storage'+params);if(!data.cleanup_files){toast('No old render files to clean.');return;}if(!confirm('Delete '+data.cleanup_files+' generated files from OTHER projects and free about '+fileSize(data.cleanup_bytes)+'? Original songs, edits, backgrounds, the current video, and AI models are kept.'))return;const result=await api('/api/storage/cleanup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keep_project_id:state.id,confirm:true})});toast('Cleaned '+result.removed_files+' files · Freed '+fileSize(result.freed_bytes));loadStorage();}catch(e){toast('Cleanup failed: '+e.message,true);}}
function syncSettingUI(){const s=state.settings;
 ['font','fontSize','position','textColor','accentColor','outline','dim','upper','resolution','renderSpeed','fps','performanceMode','encoder'].forEach(k=>{if($(k))$(k).type==='checkbox'?$(k).checked=!!s[k]:$(k).value=s[k]});
 $('exportFpsLabel').textContent=(s.fps||30)+' FPS';
 $('fontSizeVal').textContent=`${s.fontSize}px`;$('positionVal').textContent=`${s.position}%`;$('outlineVal').textContent=s.outline;
 $('dimVal').textContent=`${Math.round(s.dim*100)}%`;$('textColorVal').textContent=s.textColor.toUpperCase();$('accentColorVal').textContent=s.accentColor.toUpperCase();
 $$('[data-mode]').forEach(x=>x.classList.toggle('selected',x.dataset.mode===s.mode));
 $$('[data-animation]').forEach(x=>x.classList.toggle('selected',x.dataset.animation===s.animation));
 $$('[data-background]').forEach(x=>x.classList.toggle('selected',x.dataset.background===s.background));
 $$('[data-aspect]').forEach(x=>x.classList.toggle('selected',x.dataset.aspect===s.aspect));
 const labels={portrait:'9:16 · VERTICAL',landscape:'16:9 · HORIZONTAL',square:'1:1 · SQUARE'};$('canvasFormat').textContent=labels[s.aspect];
}
function resizePreview(){const shapes={portrait:[450,800],landscape:[800,450],square:[650,650]};const [w,h]=shapes[state.settings.aspect];if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}const stage=$('stage');stage.style.aspectRatio=`${w}/${h}`;stage.style.height='min(100%, 660px)';}
let cachedBackgroundKey='', cachedBackgroundCanvas=null;
let cachedPhotoKey='', cachedPhotoCanvas=null;
function presetBackgroundSurface(w,h,s){
 const key=[w,h,s.background,s.dim].join('|');
 if(cachedBackgroundCanvas&&cachedBackgroundKey===key)return cachedBackgroundCanvas;
 const surface=document.createElement('canvas');surface.width=w;surface.height=h;
 const paint=surface.getContext('2d');
 const colors=backgrounds[s.background]||backgrounds.midnight;
 const linear=paint.createLinearGradient(0,0,w*.8,h);
 linear.addColorStop(0,colors[0]);linear.addColorStop(1,colors[1]);
 paint.fillStyle=linear;paint.fillRect(0,0,w,h);
 const glow=paint.createRadialGradient(w*.48,h*.32,0,w*.48,h*.32,h*.66);
 glow.addColorStop(0,colors[2]+'45');glow.addColorStop(1,'#00000000');
 paint.fillStyle=glow;paint.fillRect(0,0,w,h);
 paint.fillStyle='rgba(0,0,0,'+clamp(s.dim*.7,0,.6)+')';paint.fillRect(0,0,w,h);
 const vignette=paint.createRadialGradient(w/2,h*.45,h*.03,w/2,h*.45,Math.max(w,h)*.78);
 vignette.addColorStop(0,'#00000000');vignette.addColorStop(1,'#00000066');
 paint.fillStyle=vignette;paint.fillRect(0,0,w,h);
 cachedBackgroundKey=key;cachedBackgroundCanvas=surface;
 return surface;
}
function drawBackground(w,h,t){
 const s=state.settings;
 if(s.background!=='custom'||!state.backgroundUrl){
   ctx.drawImage(presetBackgroundSurface(w,h,s),0,0,w,h);
   return;
 }
 // Static photo: composite once, not once per animation frame.
 if(!state.backgroundIsVideo&&bgImg.complete&&bgImg.naturalWidth>0){
  const key=[w,h,state.backgroundUrl,s.dim].join('|');
  if(!cachedPhotoCanvas||cachedPhotoKey!==key){
   const surface=document.createElement('canvas');surface.width=w;surface.height=h;
   const p=surface.getContext('2d');
   p.fillStyle='#060b07';p.fillRect(0,0,w,h);
   const scale=Math.max(w/bgImg.naturalWidth,h/bgImg.naturalHeight);
   const W=bgImg.naturalWidth*scale,H=bgImg.naturalHeight*scale;
   p.drawImage(bgImg,(w-W)/2,(h-H)/2,W,H);
   p.fillStyle='rgba(0,0,0,'+clamp(s.dim*.7,0,.6)+')';p.fillRect(0,0,w,h);
   const vignette=p.createRadialGradient(w/2,h*.45,h*.03,w/2,h*.45,Math.max(w,h)*.78);
   vignette.addColorStop(0,'#00000000');vignette.addColorStop(1,'#00000066');
   p.fillStyle=vignette;p.fillRect(0,0,w,h);
   cachedPhotoKey=key;cachedPhotoCanvas=surface;
  }
  ctx.drawImage(cachedPhotoCanvas,0,0,w,h);return;
 }
 ctx.fillStyle='#060b07';ctx.fillRect(0,0,w,h);
 const media=state.backgroundIsVideo?bgVid:bgImg;
 const ready=state.backgroundIsVideo?media.readyState>=2:media.complete&&media.naturalWidth;
 if(ready){
  const mw=state.backgroundIsVideo?media.videoWidth:media.naturalWidth;
  const mh=state.backgroundIsVideo?media.videoHeight:media.naturalHeight;
  if(mw>0&&mh>0){
   const scale=Math.max(w/mw,h/mh),W=mw*scale,H=mh*scale;
   try{ctx.drawImage(media,(w-W)/2,(h-H)/2,W,H)}catch{}
  }
 }
 ctx.fillStyle='rgba(0,0,0,'+clamp(s.dim*.7,0,.6)+')';ctx.fillRect(0,0,w,h);
 const vignette=ctx.createRadialGradient(w/2,h*.45,h*.03,w/2,h*.45,Math.max(w,h)*.78);
 vignette.addColorStop(0,'#00000000');vignette.addColorStop(1,'#00000066');
 ctx.fillStyle=vignette;ctx.fillRect(0,0,w,h);
}
function wrapWords(words,maxWidth,makeFont){let rows=[[]];for(const word of words){const current=rows[rows.length-1];const probe=[...current,word].join(' ');if(current.length&&ctx.measureText(probe).width>maxWidth){rows.push([word]);}else current.push(word);}return rows;}

const lyricLayoutCache=new Map();
function measureLyricLayout(words,nominal,maxWidth,font){
 const key=font+'|'+nominal+'|'+maxWidth+'|'+words.join('\u001f');
 const old=lyricLayoutCache.get(key);if(old)return old;
 let fs=nominal,rows=[];
 for(;fs>Math.max(15,nominal*.66);fs-=2){
  ctx.font='800 '+fs+'px "'+font+'",Arial,sans-serif';
  rows=wrapWords(words,maxWidth);
  if(rows.length<=2)break;
 }
 if(!rows.length)rows=wrapWords(words,maxWidth);
 const maxRow=rows.reduce((m,row)=>Math.max(m,ctx.measureText(row.join(' ')).width),0);
 if(maxRow>maxWidth)fs*=maxWidth/maxRow;
 const item={fontSize:fs,rows};
 lyricLayoutCache.set(key,item);
 if(lyricLayoutCache.size>160)lyricLayoutCache.delete(lyricLayoutCache.keys().next().value);
 return item;
}
function activeLyric(t){
 // One linear pass avoids allocating and sorting the entire lyric list every frame.
 let current=null;
 for(const line of state.lines){
  if(line.end-line.start<.10||t<line.start||t>=line.end)continue;
  if(!current||line.start>current.start)current=line;
 }
 if(!current)return null;
 let end=current.end;
 for(const line of state.lines){
  if(line.start>current.start&&line.start<end)end=line.start;
 }
 return end-current.start>=.10?{...current,end}:null;
}
function easing(t){return 1-Math.pow(1-clamp(t,0,1),3);}

const clipAnimations=['pop','fade','slide','typewriter','zoom','bounce','blur','none'];
const clipAnimationName=name=>({pop:'Pop',fade:'Fade',slide:'Slide',typewriter:'Type-on',zoom:'Zoom',bounce:'Bounce',blur:'Blur',none:'None'})[name]||'Global';
function selectedClip(){return state.lines[state.selected]||null;}
function clipMotionName(clip){return clipAnimations.includes(clip?.animation)?clip.animation:state.settings.animation;}
function clipMotionMs(clip){return Number.isFinite(Number(clip?.effectMs))?clamp(Number(clip.effectMs),120,650):230;}
function clipLocation(clip){return {x:Number.isFinite(Number(clip?.x))?clamp(Number(clip.x),8,92):50,
 y:Number.isFinite(Number(clip?.y))?clamp(Number(clip.y),8,92):state.settings.position};}
function syncClipInspector(){
 const clip=selectedClip(),has=!!clip;
 const ids=['clipAnimation','clipEffectMs','clipPosX','clipPosY',
            'resetClipMotion','applyClipMotionAll','previewClipMotion'];
 ids.forEach(id=>{$(id).disabled=!has});
 $('clipMotionName').textContent=has?clip.text:'Select a lyric from the timeline';
 $('clipAnimation').value=has&&clipAnimations.includes(clip.animation)?clip.animation:'';
 $('clipEffectMs').value=has?clipMotionMs(clip):230;
 $('clipEffectMsVal').textContent=(has?clipMotionMs(clip):230)+' ms';
 const pos=clipLocation(clip);
 $('clipPosX').value=pos.x;
 $('clipPosY').value=pos.y;
 $('clipPosXVal').textContent=Math.round(pos.x)+'%';
 $('clipPosYVal').textContent=Math.round(pos.y)+'%';
}
function setClipMotion(property,value){
 const line=selectedClip();if(!line)return;
 const next=property==='animation'?(clipAnimations.includes(value)?value:undefined):
 property==='effectMs'?clamp(Number(value),120,650):
 clamp(Number(value),8,92);
 if(line[property]===next||(line[property]==null&&next===undefined))return;
 recordEdit('clipfx:'+property+':'+state.selected);
 if(next===undefined)delete line[property];else line[property]=next;
 syncClipInspector();renderEffects();queueSave();
}
function resetClipMotion(){
 const clip=selectedClip();if(!clip)return;
 if(!['animation','effectMs','x','y'].some(k=>clip[k]!=null))return;
 recordEdit('clipfx:reset');['animation','effectMs','x','y'].forEach(k=>delete clip[k]);
 syncClipInspector();renderEffects();queueSave();toast('Clip now follows global motion and placement');
}
function applyClipMotionAll(){
 const clip=selectedClip();if(!clip||!state.lines.length)return;
 recordEdit('clipfx:all');
 for(const target of state.lines){
   for(const key of ['animation','effectMs','x','y']){
     if(clip[key]==null)delete target[key];
     else target[key]=clip[key];
   }
 }
 syncClipInspector();renderEffects();queueSave();toast('Applied selected clip motion and position to every lyric');
}
function previewSelectedMotion(){
 const clip=selectedClip();if(!clip)return;
 seek(clip.start);
 if(!state.playing)play();
}
function bindPreviewPositionDragging(){
 const el=canvas;let drag=null;
 function point(e){
  const rect=canvas.getBoundingClientRect();
  return {x:(e.clientX-rect.left)/Math.max(1,rect.width)*100,
          y:(e.clientY-rect.top)/Math.max(1,rect.height)*100};
 }
 el.addEventListener('pointerdown',e=>{
  if(e.button!==0||!state.lines.length)return;
  const active=activeLyric(state.time);
  if(!active)return;
  const index=state.lines.findIndex(line=>line.id===active.id);
  if(index<0)return;
  const p=point(e),loc=clipLocation(active);
  if(Math.abs(p.x-loc.x)>37||Math.abs(p.y-loc.y)>14)return;
  e.preventDefault();state.selected=index;syncClipInspector();renderLines();renderTimeline();
  drag={index,x:p.x,y:p.y,from:loc,moved:false};
  el.setPointerCapture(e.pointerId);el.classList.add('is-dragging-lyric');
 });
 el.addEventListener('pointermove',e=>{
  if(!drag)return;
  const p=point(e),clip=state.lines[drag.index];if(!clip)return;
  const x=clamp(drag.from.x+(p.x-drag.x),8,92);
  const y=clamp(drag.from.y+(p.y-drag.y),8,92);
  if(Math.abs(x-clipLocation(clip).x)<.01&&Math.abs(y-clipLocation(clip).y)<.01)return;
  if(!drag.moved){recordEdit('clipfx:drag');drag.moved=true;}
  clip.x=Math.round(x*10)/10;clip.y=Math.round(y*10)/10;
  syncClipInspector();
 });
 const finish=()=>{
  if(!drag)return;
  if(drag.moved){renderEffects();queueSave();toast('Lyric position updated');}
  drag=null;el.classList.remove('is-dragging-lyric');
 };
 ['pointerup','pointercancel','lostpointercapture'].forEach(name=>el.addEventListener(name,finish));
}
function drawPositionGuide(){
 if(state.playing||!$('welcome').classList.contains('hidden')||!$('reviewOverlay').classList.contains('hidden'))return;
 const line=activeLyric(state.time);
 if(!line||line.id!==selectedClip()?.id)return;
 const {x,y}=clipLocation(line),w=canvas.width,h=canvas.height;
 const px=w*x/100,py=h*y/100,bw=w*.74,bh=h*.105;
 ctx.save();ctx.lineWidth=Math.max(1,w/450);
 ctx.strokeStyle='rgba(146,255,127,0.7)';
 ctx.setLineDash([7,5]);ctx.strokeRect(px-bw/2,py-bh/2,bw,bh);
 ctx.setLineDash([]);ctx.fillStyle='#9aff8a';
 ctx.fillRect(px-4,py-4,8,8);ctx.restore();
}

function showText(t){const w=canvas.width,h=canvas.height,s=state.settings,ln=activeLyric(t);if(!ln)return;
 const anim=clipMotionName(ln),duration=clipMotionMs(ln)/1000,pos=clipLocation(ln);
 let text=s.upper?ln.text.toUpperCase():ln.text;const progress=clamp((t-ln.start)/Math.max(.03,ln.end-ln.start),0,1);
 const entry=clamp((t-ln.start)/duration,0,1),outro=clamp((ln.end-t)/.16,0,1);
 let alpha=1,scale=1,shift=0;
 if(anim==='fade')alpha=Math.min(entry,outro);
 if(anim==='pop'){scale=.8+.2*easing(entry);alpha=Math.min(1,entry*4,outro*4);}
 if(anim==='slide'){shift=(1-easing(entry))*h*.07;alpha=Math.min(1,entry*4,outro*4);}
 if(anim==='zoom'){scale=1.25-.25*easing(clamp((t-ln.start)/duration,0,1));alpha=Math.min(1,entry*5,outro*5);}
 if(anim==='bounce'){const x=clamp((t-ln.start)/duration,0,1);scale=x<.42?.65+(.5*x/.42):1.15-.15*easing((x-.42)/.58);alpha=Math.min(1,entry*6,outro*6);}
 if(anim==='blur'){alpha=Math.min(entry,outro);}
 let words=(ln.words||[]).length?ln.words.map(x=>({...x,text:s.upper?x.text.toUpperCase():x.text})):text.split(/\s+/).map(x=>({text:x,start:ln.start,end:ln.end}));
 if(s.mode==='word') {let active=words.find(x=>x.start<=t&&x.end>t)||words.find(x=>x.start<=t)||words[0];if(!active)return;text=active.text;words=[active];}
 if(anim==='typewriter'&&s.mode==='line')text=text.split(/\s+/).slice(0,Math.max(1,Math.ceil(progress*text.split(/\s+/).length))).join(' ');
 const nominal=Math.round(s.fontSize*w/720),margin=w*.09;
 ctx.save();
 const rawWords=s.mode==='karaoke'?words.map(x=>x.text):text.split(/\s+/);
 const layout=measureLyricLayout(rawWords,nominal,w-margin*2,s.font);
 const fs=layout.fontSize,rows=layout.rows;
 ctx.font=`800 ${fs}px "${s.font}",Arial,sans-serif`;
 ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineJoin='round';ctx.lineWidth=Math.max(0,s.outline*w/720*2);ctx.strokeStyle='rgba(5,10,8,.94)';ctx.shadowColor='rgba(0,0,0,.58)';ctx.shadowBlur=fs*.22;
 ctx.globalAlpha=alpha;
 if(anim==='blur')ctx.filter='blur('+((1-easing(clamp((t-ln.start)/duration,0,1)))*Math.max(2,fs*.09))+'px)';
 const lineHeight=fs*1.24,cy=h*(pos.y/100)+shift;ctx.translate(w*pos.x/100,cy);ctx.scale(scale,scale);
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
 // Don't paint or read timeline layout behind the welcome overlay. On Windows,
 // startup competes with WebView2 GPU/process initialization and no media is
 // playing yet. Keep the entire idle welcome view static.
 const covered=!$('welcome').classList.contains('hidden')||!$('reviewOverlay').classList.contains('hidden');
 if(covered&&!state.playing&&!state.lines.length)return;
 // Prefer 30 fps while playing, 12 fps while editing and 4 fps during modal.
 const interval=document.hidden?250:covered?250:state.playing?(state.settings.performanceMode==='eco'?67:33):120;
 if(now-lastPreviewPaint<interval)return;
 const elapsed=Math.min(.15,(now-lastFrame)/1000);lastFrame=now;lastPreviewPaint=now;
 if(state.demo&&state.playing){state.time+=elapsed;if(state.time>state.duration){state.time=0;state.playing=false;}}
 if(state.id&&state.playing&&isFinite(audio.currentTime))state.time=audio.currentTime;
 const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);drawBackground(w,h,state.time);showText(state.time);drawPositionGuide();
 $('currentTime').textContent=shortTime(state.time);$('playButton').textContent=state.playing?'Ⅱ':'▶';
 const duration=state.duration||1;const timelineWidth=Math.max(0,$('timelineInner').clientWidth-110);$('playhead').style.left=`${110+timelineWidth*clamp(state.time/duration,0,1)}px`;
 if(state.backgroundIsVideo&&state.playing&&bgVid.paused)bgVid.play().catch(()=>{});
 if(state.backgroundIsVideo&&!state.playing&&!bgVid.paused)bgVid.pause();
}
function seek(seconds){state.time=clamp(seconds,0,state.duration);if(state.id&&audio.readyState)audio.currentTime=state.time;if(state.backgroundIsVideo&&Number.isFinite(bgVid.duration)&&bgVid.duration>0)bgVid.currentTime=state.time%bgVid.duration;}
function play(){if(!state.duration){toast('Upload a song to preview lyrics.');return;}state.playing=!state.playing;if(state.id){if(state.playing)audio.play().catch(e=>{state.playing=false;toast(e.message,true);});else audio.pause();}}
function selectLine(index,jump=false){state.selected=clamp(index,0,Math.max(0,state.lines.length-1));if(jump&&state.lines[state.selected])seek(state.lines[state.selected].start+.07);syncClipInspector();renderLines();renderTimeline();}
function reflowWords(line){
 const parts=line.text.trim().split(/\s+/).filter(Boolean);
 if(line.words&&line.words.length===parts.length){line.words=line.words.map((w,i)=>({...w,text:parts[i]}));return;}
 line.words=parts.map((text,i)=>({text,start:line.start+(line.end-line.start)*i/parts.length,end:line.start+(line.end-line.start)*(i+1)/parts.length}));
}
function retimeWords(line,oldStart,oldEnd,sourceWords){
 const span=Math.max(.01,oldEnd-oldStart),newSpan=line.end-line.start;
 line.words=(sourceWords||line.words||[]).map(w=>({text:w.text,start:line.start+(w.start-oldStart)*newSpan/span,end:line.start+(w.end-oldStart)*newSpan/span}));
}
function renderLines(){syncClipInspector();const holder=$('lyricsEditor');if(!state.lines.length){holder.innerHTML='<div class="empty-caption"><div class="empty-caption-icon">♫</div><strong>No lyrics yet</strong><span>Upload a song to detect lyrics automatically.</span></div>';return;}
 holder.innerHTML=state.lines.map((l,i)=>`<div class="lyric-row ${i===state.selected?'selected':''}" data-line="${i}"><div class="lyric-row-top"><span class="lyric-n">LINE ${String(i+1).padStart(2,'0')}</span><div class="lyric-row-actions"><button data-action="jump" data-i="${i}" class="tiny-btn" title="Seek to lyric">▶</button><button data-action="delete" data-i="${i}" class="tiny-btn danger" title="Delete line">×</button></div></div><input class="lyric-input" data-text="${i}" value="${safe(l.text)}" aria-label="Line ${i+1} text"/><div class="timing-row"><label>IN<input type="number" data-start="${i}" step="0.01" min="0" max="${state.duration}" value="${prettyTime(l.start)}" /></label><span class="timing-arrow">→</span><label>OUT<input type="number" data-end="${i}" step="0.01" min="0" max="${state.duration}" value="${prettyTime(l.end)}" /></label></div></div>`).join('');
 holder.querySelectorAll('.lyric-row').forEach(el=>el.addEventListener('click',e=>{if(e.target.closest('input,button'))return;selectLine(+el.dataset.line,true)}));
 holder.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{const i=+b.dataset.i;if(b.dataset.action==='jump'){selectLine(i,true);return;}deleteAt(i);}));
 holder.querySelectorAll('.lyric-input').forEach(el=>el.addEventListener('input',()=>{const i=+el.dataset.text,ln=state.lines[i];if(ln.text===el.value)return;recordEdit('text:'+i);ln.text=el.value;reflowWords(ln);renderTimeline();queueSave();}));
 holder.querySelectorAll('input[data-start],input[data-end]').forEach(el=>el.addEventListener('change',()=>{const i=+(el.dataset.start??el.dataset.end),ln=state.lines[i];const start=el.hasAttribute('data-start');const oldStart=ln.start,oldEnd=ln.end;const val=Number(el.value);if(!Number.isFinite(val))return;recordEdit('timing:'+i);if(start)ln.start=clamp(val,0,Math.max(0,ln.end-.06));else ln.end=clamp(val,ln.start+.06,state.duration);retimeWords(ln,oldStart,oldEnd);renderLines();renderTimeline();queueSave();}));
}
function renderEffects(){
 const fx=$('effectsTrack');
 fx.innerHTML=state.lines.map((line,i)=>{
   const custom=clipAnimations.includes(line.animation)||line.effectMs!=null||line.x!=null||line.y!=null;
   const effect=clipMotionName(line),label=(custom?'✧ ':'↳ ')+clipAnimationName(effect);
   const d=state.duration||1;
   return '<button type="button" class="fx-clip '+(custom?'has-override ':'')+
      (i===state.selected?'selected':'')+'" data-fx-index="'+i+'" title="'+
      safe(line.text+' · '+clipAnimationName(effect)+(custom?' (customized)':' (global)'))+
      '" style="left:'+clamp(100*line.start/d,0,100)+'%;width:'+
      clamp(100*(line.end-line.start)/d,.3,100)+'%;">'+safe(label)+'</button>';
 }).join('');
 fx.querySelectorAll('[data-fx-index]').forEach(button=>button.addEventListener('click',e=>{
   e.preventDefault();e.stopPropagation();
   selectLine(Number(button.dataset.fxIndex),true);panel('animation');
 }));
}
function renderTimeline(){const d=state.duration||1;const clips=$('lyricTrack');clips.innerHTML=state.lines.map((l,i)=>`<div class="lyric-clip ${i===state.selected?'selected':''}" data-index="${i}" style="left:${clamp(100*l.start/d,0,100)}%;width:${clamp(100*(l.end-l.start)/d,.3,100)}%;"><span class="clip-grab"></span>${safe(trimLine(l.text))}</div>`).join('');
 renderEffects();
 $('clipCount').textContent=`${state.lines.length} clips`;$('timelineInner').style.width=`${Math.max(100,state.zoom*100)}%`;
 const ruler=$('ruler');ruler.innerHTML='';const interval=d<45?5:d<150?15:d<360?30:60;for(let s=0;s<d;s+=interval){const tick=document.createElement('span');tick.className='tick';tick.style.left=`${s/d*100}%`;tick.textContent=shortTime(s);ruler.appendChild(tick);}
 drawWaveform();
 clips.querySelectorAll('.lyric-clip').forEach(el=>el.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();const i=+el.dataset.index;const line=state.lines[i];state.selected=i;const trackRect=clips.getBoundingClientRect(),startX=e.clientX;const originalStart=line.start,originalEnd=line.end,originalWords=line.words.map(w=>({...w}));const resize=e.target.classList.contains('clip-grab');let moved=false;selectLine(i,false);const move=evt=>{
 const diff=(evt.clientX-startX)/trackRect.width*d;
 if(Math.abs(diff)<.004&&!moved)return;
 if(!moved){recordEdit('drag');moved=true;}
 if(resize){line.start=clamp(snapTime(originalStart+diff),0,line.end-.1)}
 else{const len=originalEnd-originalStart;line.start=clamp(snapTime(originalStart+diff),0,Math.max(0,d-len));line.end=line.start+len;}
 retimeWords(line,originalStart,originalEnd,originalWords);
 // Update just the dragged clip; rebuilding hundreds of clips each pointer
 // event causes the editor to stutter and invalidates drag targets.
 const live=clips.querySelector('.lyric-clip[data-index="'+i+'"]');
 if(live){live.style.left=clamp(100*line.start/d,0,100)+'%';live.style.width=clamp(100*(line.end-line.start)/d,.3,100)+'%';}
};const up=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);if(moved){state.lines.sort((a,b)=>a.start-b.start);state.selected=state.lines.indexOf(line);}renderLines();renderTimeline();if(moved)queueSave();};window.addEventListener('pointermove',move);window.addEventListener('pointerup',up,{once:true});}));
}
function drawWaveform(){
 const holder=$('audioWave');holder.style.backgroundImage='none';
 let wave=holder.querySelector('canvas');if(!wave){wave=document.createElement('canvas');holder.appendChild(wave);}
 const W=Math.max(1,Math.floor(holder.clientWidth||1000)),H=62;
 if(wave.width===W&&wave.height===H&&wave._lastPeaks===state.waveform)return;
 wave.width=W;wave.height=H;wave._lastPeaks=state.waveform;
 wave.style.width='100%';wave.style.height='62px';
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
function notifyNativeSession(){
 try{const bridge=window.pywebview?.api;
  bridge?.session_active?.(!!state.id).catch?.(()=>{});
 }catch{}
}
function queueSave(){
 if(!state.id)return;
 state.dirty=true;editRevision++;
 $('projectStatus').textContent='Unsaved · crash recovery on';
 clearTimeout(state.pendingSave);
 state.pendingSave=setTimeout(()=>writeRecovery(),750);
}
function writeRecovery(){
 if(!state.id)return Promise.resolve();
 const id=state.id;
 const draft=$('reviewOverlay').classList.contains('hidden')?'':$('lyricsText').value;
 const payload=JSON.stringify({lines:state.lines,settings:state.settings,draft_lyrics:draft});
 // Crash-only recovery; never overwrite project.json.
 recoverySerial=recoverySerial.catch(()=>{}).then(()=>api('/api/projects/'+id+'/recovery',{
  method:'PUT',headers:{'Content-Type':'application/json'},body:payload
 }));
 return recoverySerial.catch(e=>{if(state.id===id)toast('Crash recovery failed: '+e.message,true);});
}
async function save(){
 if(!state.id||state.demo)return false;
 clearTimeout(state.pendingSave);
 const id=state.id,revision=editRevision;
 // Complete pending recovery writes before committing and clearing the cache.
 await recoverySerial.catch(()=>{});
 const payload=JSON.stringify({settings:state.settings,lines:state.lines});
 $('projectStatus').textContent='Saving…';
 saveSerial=saveSerial.catch(()=>{}).then(()=>api('/api/projects/'+id,{
  method:'PUT',headers:{'Content-Type':'application/json'},body:payload
 }));
 try{
  await saveSerial;
  if(state.id===id){
   state.persisted=true;
   state.dirty=revision!==editRevision;
   $('projectStatus').textContent=state.dirty?'Unsaved · crash recovery on':'Saved';
   if(state.dirty)queueSave();
  }
  toast('Project saved.');
  return true;
 }catch(e){
  if(state.id===id)$('projectStatus').textContent='Save failed';
  toast('Save failed: '+e.message,true);
  return false;
 }
}
function askSaveDecision(reason='leave'){
 if(!state.id||(!state.dirty&&state.persisted))return Promise.resolve('skip');
 $('saveDecisionText').textContent=state.persisted?
  'Save changes to "'+state.title+'"? Don’t Save keeps the last saved version and clears only the crash recovery.':
  'Save "'+state.title+'"? Don’t Save permanently deletes this unsaved draft and its temporary media.';
 $('saveDecisionOverlay').classList.remove('hidden');
 return new Promise(resolve=>{
  let settled=false;
  const finish=(answer)=>{
   if(settled)return;settled=true;
   $('saveDecisionOverlay').classList.add('hidden');
   ['decisionSave','decisionDiscard','decisionCancel'].forEach(k=>$(k).onclick=null);
   resolve(answer);
  };
  $('decisionSave').onclick=()=>finish('save');
  $('decisionDiscard').onclick=()=>finish('discard');
  $('decisionCancel').onclick=()=>finish('cancel');
 });
}
async function mayLeaveProject(){
 if(transitionBusy)return false;
 if(!state.id)return true;
 transitionBusy=true;
 try{
  const decision=await askSaveDecision();
  if(decision==='cancel')return false;
  if(decision==='save')return await save();
  if(decision==='discard'){
   clearTimeout(state.pendingSave);
   await recoverySerial.catch(()=>{});
   const id=state.id;
   await api('/api/projects/'+id+'/discard',{method:'POST'});
   if(localStorage.getItem('lyricforge-last')===id)
    localStorage.removeItem('lyricforge-last');
   return true;
  }
  return true;
 }catch(e){toast('Cannot leave this project: '+e.message,true);return false;}
 finally{transitionBusy=false;}
}
async function quitStudio(){
 if(!await mayLeaveProject())return;
 if(window.pywebview?.api?.approve_close){
  try{await window.pywebview.api.approve_close();}catch(e){toast('Could not close: '+e.message,true);}
 }else{
  resetWorkspace();
  toast('You can close this browser tab now.');
 }
}
function resetWorkspace(){
 clearTimeout(state.pendingSave);
 state.playing=false;audio.pause();state.id=null;state.persisted=false;state.dirty=false;
 state.demo=false;state.lines=[];resetEditHistory();state.waveform=[];state.duration=0;
 state.time=0;state.title='Untitled project';state.settings=defaultSettings();
 state.backgroundUrl=null;state.selected=0;
 localStorage.removeItem('lyricforge-last');
 $('reviewOverlay').classList.add('hidden');$('welcome').classList.remove('hidden');
 syncSettingUI();resizePreview();configureMedia();renderTitle();renderTimeline();renderLines();
 notifyNativeSession();
}
function configureMedia(){if(state.id){audio.src=`/api/projects/${state.id}/audio`;audio.load();}else{audio.removeAttribute('src');audio.load();}
 $('totalTime').textContent=shortTime(state.duration);$('exportDuration').textContent=shortTime(state.duration);}
function prepareNewSongUI(){
 state.playing=false;audio.pause();$('welcome').classList.add('hidden');$('reviewOverlay').classList.remove('hidden');
 $('transcribeProgress').classList.remove('hidden');$('lyricsText').classList.add('hidden');
 $('lyricsText').value='';$('reviewTitle').textContent='Finding your lyrics…';
 $('reviewDescription').textContent='Analyzing the vocal and mapping words to timestamps.';
 $('confirmLyrics').disabled=true;$('reviewWarning').classList.add('hidden');$('uncertainReview').classList.add('hidden');
 updateTranscriptProgress({transcription_stage:'queued',transcription_progress:0});
}
async function finishNewSong(data,title){resetEditHistory();
 state.id=data.id;state.title=title;state.duration=data.duration;state.demo=false;state.lines=[];
 state.persisted=false;state.dirty=false;notifyNativeSession();
 state.waveform=[];state.time=0;state.settings={...defaultSettings(),performanceMode:$('startupPerformance').value};state.backgroundUrl=null;
 state.backgroundIsVideo=false;syncSettingUI();resizePreview();configureMedia();renderTitle();
 renderTimeline();renderLines();localStorage.setItem('lyricforge-last',state.id);
 await waitForTranscript(state.id);
}
async function startUpload(file){
 if(!file)return;
 if(!await mayLeaveProject())return;
 if(state.id)resetWorkspace();
 if(!/\.(mp3|wav|flac|m4a|aac|ogg|opus|mp4|webm)$/i.test(file.name)){
   toast('Please upload an audio file (MP3, WAV, M4A, FLAC, etc.)',true);return;
 }
 prepareNewSongUI();
 let data;
 try{const fd=new FormData();fd.append('file',file);
   fd.append('recognition',$('recognitionMode').value);
   fd.append('language',$('languageHint').value);
   fd.append('vocabulary',$('vocabularyHint').value);
   fd.append('performance_mode',$('startupPerformance').value);
   data=await api('/api/projects',{method:'POST',body:fd});}
 catch(e){toast('Song import failed: '+e.message,true);$('reviewOverlay').classList.add('hidden');$('welcome').classList.remove('hidden');return;}
 await finishNewSong(data,file.name.replace(/\.[^.]+$/,''));
}
async function chooseSong(){
 const bridge=window.pywebview?.api;
 if(document.documentElement.classList.contains('desktop-mode')&&bridge?.pick_audio_file){
  try{
   const picked=await bridge.pick_audio_file();
   if(!picked)return; // Cancelled native picker; current project stays untouched.
   if(!await mayLeaveProject())return;
   resetWorkspace();prepareNewSongUI();
   const data=await bridge.import_picked_audio(
      $('recognitionMode').value,$('languageHint').value,
      $('vocabularyHint').value,$('startupPerformance').value);
   await finishNewSong(data,data.title||picked.name||'My song');
  }catch(err){
   toast('Unable to import song: '+(err.message||String(err)),true);
   $('reviewOverlay').classList.add('hidden');
   if(!state.id)$('welcome').classList.remove('hidden');
  }
  return;
 }
 // Browser picker: Save/Discard decision occurs only after a file is chosen.
 $('audioFile').click();
}
function showUncertainReview(project){
 const words=Array.isArray(project.review_uncertain)?project.review_uncertain:[];
 const review=$('uncertainReview'),list=$('uncertainWordList');
 $('refineStatus').textContent='';
 $('refineSuggestions').classList.add('hidden');
 $('applyRefineBtn').classList.add('hidden');
 if(!words.length){review.classList.add('hidden');return;}
 review.classList.remove('hidden');
 list.innerHTML=words.slice(0,24).map(w=>{
   const at=Math.max(0,Number(w.start)||0);
   return '<button type="button" data-review-time="'+at.toFixed(3)+'" title="Listen near this word">'+
     '<b>'+safe(w.text)+'</b><span>'+shortTime(at)+' · check pronunciation</span></button>';
 }).join('');
 list.querySelectorAll('[data-review-time]').forEach(button=>button.addEventListener('click',()=>{
  const at=Math.max(0,Number(button.dataset.reviewTime)||0);
  if(!state.id)return;
  audio.currentTime=Math.max(0,at-.7);
  audio.play().catch(()=>{});
 }));
 $('refineLyricsBtn').disabled=false;
}
async function refineUncertainLyrics(){
 if(!state.id)return;
 const id=state.id;
 const button=$('refineLyricsBtn');button.disabled=true;
 $('refineStatus').textContent='Rechecking uncertain sections with the same Whisper model…';
 try{
  const {job_id}=await api('/api/projects/'+id+'/refine',{method:'POST'});
  for(let i=0;i<600;i++){
   await new Promise(resolve=>setTimeout(resolve,1200));
   if(state.id!==id)return;
   const job=await api('/api/jobs/'+job_id);
   if(job.status==='error')throw Error(job.error||'Refinement failed');
   if(job.status==='done'){
    const options=job.suggestions||[];
    $('refineStatus').textContent=options.length?
     options.length+' second-pass suggestion(s) ready. Review before applying.':
     'No clear alternative lyrics were found. Your original draft is unchanged.';
    const holder=$('refineSuggestions');
    holder.innerHTML=options.map((entry,i)=>'<div class="refine-option">'+
      '<b>Section '+(i+1)+' · '+shortTime(entry.start)+'</b>'+
      '<span>Original: '+safe(entry.before)+'</span>'+
      '<strong>Suggested: '+safe(entry.suggested)+'</strong></div>').join('');
    holder.classList.toggle('hidden',!options.length);
    $('applyRefineBtn').classList.toggle('hidden',!options.length);
    return;
   }
   $('refineStatus').textContent='Refining… '+Math.max(0,Math.min(99,job.progress||0))+
    '% · This may take longer than the first pass.';
  }
  throw Error('Refinement took too long');
 }catch(e){$('refineStatus').textContent='Refinement unavailable: '+e.message;}
 finally{button.disabled=false;}
}
async function applyRefinement(){
 if(!state.id)return;
 if(!confirm('Replace the current unconfirmed lyric draft with the reviewed second-pass result? Unsaved edits in this textbox will be replaced.'))return;
 try{
  const response=await api('/api/projects/'+state.id+'/refine/apply',{method:'POST'});
  $('lyricsText').value=response.draft_lyrics||'';
  $('confirmLyrics').disabled=!$('lyricsText').value.trim();
  $('refineStatus').textContent='Suggestions applied. Please review and correct the lyrics before syncing.';
  $('refineSuggestions').classList.add('hidden');$('applyRefineBtn').classList.add('hidden');
  showUncertainReview({review_uncertain:response.review_uncertain||[]});
  $('refineStatus').textContent='Suggestions applied. Please review and correct before confirming.';
 }catch(e){toast('Could not apply suggestions: '+e.message,true);}
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
async function waitForTranscript(projectId){for(let attempts=0;attempts<300;attempts++){if(state.id!==projectId)return;try{const project=await api(`/api/projects/${projectId}`);if(project.status==='transcribing')updateTranscriptProgress(project);if(project.status==='review'||project.status==='editor'){if(project.status==='editor'){loadProjectData(project);$('reviewOverlay').classList.add('hidden');return;}$('transcribeProgress').classList.add('hidden');$('lyricsText').classList.remove('hidden');$('lyricsText').value=project.draft_lyrics||'';$('reviewTitle').textContent='Review your lyrics.';$('reviewDescription').textContent='Correct any misheard words and put each lyric line on a new line. Your edits are applied before syncing.';showUncertainReview(project);$('confirmLyrics').disabled=!$('lyricsText').value.trim();if(project.transcription_error){const warning=$('reviewWarning');warning.textContent='Automatic transcription was unavailable: '+project.transcription_error+'. You can still paste your lyrics and create a video, but manual timing adjustments may be needed.';warning.classList.remove('hidden');}else if(!project.draft_lyrics){const warning=$('reviewWarning');warning.textContent='No clear vocals were detected. You can paste lyrics manually, though the timing will only be an estimate.';warning.classList.remove('hidden');}return;}}catch(e){toast(e.message,true);return;}await new Promise(r=>setTimeout(r,1400));}
 $('transcribeProgress').classList.add('hidden');$('lyricsText').classList.remove('hidden');$('reviewTitle').textContent='Enter your lyrics.';$('confirmLyrics').disabled=false;toast('Transcription timed out. You can paste the lyrics manually.',true);
}
function loadProjectData(project){resetEditHistory();state.id=project.id;state.title=project.title;state.duration=project.duration;state.lines=project.lines||[];
 state.persisted=project.save_state!=='draft';state.dirty=false;notifyNativeSession();state.settings={...defaultSettings(),...(project.settings||{})};state.demo=false;state.time=0;state.selected=0;state.playing=false;state.waveform=[];state.backgroundUrl=project.background_file?`/api/projects/${state.id}/background?v=${Date.now()}`:null;state.backgroundIsVideo=!!project.background_file&&/\.(mp4|mov|webm)$/i.test(project.background_file);refreshBackgroundMedia();
 $('welcome').classList.add('hidden');$('reviewOverlay').classList.add('hidden');syncSettingUI();resizePreview();configureMedia();renderTitle();renderTimeline();renderLines();
 // Allow the window and timeline to paint before asking FFmpeg for waveform data.
 // The request stays asynchronous and cancels naturally when another song opens.
 setTimeout(()=>{if(state.id===project.id)loadWaveform();},450);}
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
function loadDemo(){resetEditHistory();const texts=['I WAS LOST INSIDE THE STATIC','NOW THE CITY KNOWS MY NAME','EVERY SHADOW HAS A STORY','WATCH ME TURN IT INTO FLAMES','I CAME BACK FROM THE DARK','AND I BROUGHT THE LIGHT WITH ME'];state.id=null;state.demo=true;state.title='DEMO / AFTER DARK';state.duration=24;state.time=2;state.waveform=Array.from({length:120},(_,i)=>.14+.42*Math.abs(Math.sin(i*7.1)*Math.cos(i*.9)));state.lines=texts.map((text,i)=>{const start=i*4;const line={id:String(i),start,end:start+3.7,text,words:[]};reflowWords(line);return line;});state.settings=defaultSettings();state.selected=0;$('welcome').classList.add('hidden');syncSettingUI();resizePreview();renderTitle();renderTimeline();renderLines();toast('Demo mode — upload your own song to enable MP4 export.');}
let updateCheckBusy=false;
async function checkForUpdates(manual=false){
 const bridge=window.pywebview?.api;
 if(!bridge?.check_updates){
  if(manual)toast('Automatic updates are available in the Windows desktop app.',true);
  return;
 }
 if(updateCheckBusy)return;
 updateCheckBusy=true;
 const overlay=$('updateOverlay'),install=$('updateInstall');
 if(manual){$('updateTitle').textContent='Checking for updates…';
  $('updateText').textContent='Checking official SkellyMotion releases.';
  $('updateDetails').textContent='No change will be installed without your approval.';
  install.disabled=true;overlay.classList.remove('hidden');}
 try{
  const data=await bridge.check_updates();
  if(data.status==='update'){
   $('updateTitle').textContent='SkellyMotion '+data.version+' is available';
   $('updateText').textContent='You have '+data.current_version+
    '. Download and install the newer version? Your projects and AI models stay in place.';
   $('updateDetails').textContent='Size: '+(data.size_bytes/1048576).toFixed(0)+
    ' MB · Secure SHA-256 verification · Backup of previous app retained';
   overlay.classList.remove('hidden');
   install.disabled=false;install.textContent='Download and install';
   install.onclick=async()=>{
    install.disabled=true;install.textContent='Downloading…';
    $('updateText').textContent='Downloading and verifying the update. Do not close SkellyMotion.';
    try{
     const result=await bridge.prepare_update(data.version);
     if(result.status==='busy')throw Error('Another update is being prepared');
     if(result.status!=='ready')throw Error('Update did not pass verification');
     $('updateText').textContent='Update verified. Save your current project before restarting.';
     if(!await mayLeaveProject()){
      install.disabled=false;install.textContent='Restart and install';return;
     }
     await bridge.install_prepared_update();
     $('updateText').textContent='Installing update and restarting…';
    }catch(err){
     $('updateText').textContent='Update not installed: '+(err.message||String(err));
     install.disabled=false;install.textContent='Try again';
    }
   };
  }else if(manual){
   install.disabled=true;
   $('updateTitle').textContent=data.status==='current'?'You’re up to date':'Updates not available';
   $('updateText').textContent=data.reason||
    (data.status==='current'?'You already have the latest published release.':
     'There is no newer published release yet.');
   $('updateDetails').textContent=data.status==='needs_auth'?
    "Private GitHub repository: install GitHub CLI and sign in once using 'gh auth login'. No token is stored in SkellyMotion.":
    'SkellyMotion only installs official, verified Windows release packages.';
  }
 }catch(err){
  if(manual){
   install.disabled=true;$('updateTitle').textContent='Update check failed';
   $('updateText').textContent=err.message||String(err);
  }
 }finally{updateCheckBusy=false;}
}
async function downloadVideo(e,preview=false){
 const el=preview?$('previewDownloadBtn'):$('downloadBtn');
 if(downloadBusy){e.preventDefault();return;}
 if(!state.id||el.classList.contains('hidden')||!el.getAttribute('href')||
      el.getAttribute('href')==='#'){e.preventDefault();return;}
 const bridge=window.pywebview?.api;
 if(bridge?.save_video){
  // pywebview's embedded Edge does not reliably handle attachment downloads.
  // Use native Save As and stream the file server-side, outside the renderer.
  e.preventDefault();downloadBusy=true;el.classList.add('is-busy');
  el.setAttribute('aria-disabled','true');$('downloadStatus').textContent='Opening Save As…';
  try{
   const result=await bridge.save_video(state.id,preview);
   if(result?.status==='saved'){
    $('downloadStatus').textContent='✓ MP4 saved to '+result.path;
    toast('Video saved successfully.');
   }else if(result?.status==='cancelled'){
    $('downloadStatus').textContent='Save cancelled. Your render remains available.';
   }else{
    $('downloadStatus').textContent='Another download is already running.';
   }
  }catch(err){
   $('downloadStatus').textContent='Could not save MP4: '+(err.message||String(err));
   toast($('downloadStatus').textContent,true);
  }finally{downloadBusy=false;el.classList.remove('is-busy');
   el.removeAttribute('aria-disabled');}
 }else{
  // Normal browsers download the FileResponse as an MP4 attachment.
  // No fetch/blob buffering of large video files in JS memory.
  downloadBusy=true;el.classList.add('is-busy');
  $('downloadStatus').textContent='Your browser is saving the MP4…';
  setTimeout(()=>{downloadBusy=false;el.classList.remove('is-busy');},2200);
 }
}
async function runVideoExport(preview=false){
 if(!state.id){toast('Upload a song to export a video.',true);return;}
 if(!state.lines.length){toast('Add lyric lines before exporting.',true);return;}
 panel('export');
 $('renderBtn').disabled=true;$('renderPreviewBtn').disabled=true;
 if(preview){$('previewDownloadBtn').classList.add('hidden');$('renderPreviewPlayer').classList.add('hidden');}
 else $('downloadBtn').classList.add('hidden');
 const label=$('renderStatus'),track=$('renderProgressTrack'),fill=$('renderProgressFill');
 label.classList.remove('hidden');track.classList.remove('hidden');
 track.setAttribute('aria-valuenow','0');fill.style.width='0%';
 label.textContent=preview?'Preparing a 15-second preview…':'Preparing full video…';
 try{
  const endpoint='/api/projects/'+state.id+(preview?'/preview':'/render');
  const {job_id}=await api(endpoint,{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({lines:state.lines,settings:state.settings})
  });
  for(let i=0;i<900;i++){
   await new Promise(resolve=>setTimeout(resolve,1200));
   const job=await api('/api/jobs/'+job_id);
   if(job.status==='done'){
    fill.style.width='100%';track.setAttribute('aria-valuenow','100');
    const message=job.cached?'Reused an identical completed render.':'Rendered successfully.';
    label.textContent='✓ '+message+
     (job.elapsed_seconds!=null?' '+job.elapsed_seconds+'s.':'')+
     (job.encoder_used?' · '+job.encoder_used:'');
    if(preview){
     const link=$('previewDownloadBtn');link.href=job.download;link.classList.remove('hidden');
     const player=$('renderPreviewPlayer');player.src=job.download+'?v='+Date.now();
     player.classList.remove('hidden');
    }else{
     const link=$('downloadBtn');link.href=job.download;link.classList.remove('hidden');
    }
    toast(preview?'Test render ready for review!':'Full MP4 export complete!');
    return;
   }
   if(job.status==='error')throw Error(job.error||'Rendering failed');
   const percent=Math.max(0,Math.min(99,Number(job.progress)||0));
   fill.style.width=percent+'%';track.setAttribute('aria-valuenow',String(percent));
   const speed=Number.isFinite(job.encode_fps)?' · '+job.encode_fps.toFixed(0)+' encode FPS':'';
   const encoder=job.encoder_used?' · '+job.encoder_used:'';
   const stage=job.stage==='checking_encoder'?'Testing video encoder…':
     job.stage==='cpu_fallback'?'GPU failed, automatically retrying on CPU…':
     job.stage==='encoding'?'Encoding video… '+percent+'%'+speed+encoder:
     'Preparing background and subtitles…';
   label.textContent=stage;
  }
  throw Error('Render exceeded the safety timeout.');
 }catch(e){label.textContent='Export failed: '+e.message;toast(e.message,true);}
 finally{$('renderBtn').disabled=false;$('renderPreviewBtn').disabled=false;}
}
async function exportVideo(){return runVideoExport(false);}
async function previewVideo(){return runVideoExport(true);}

async function loadPerformance(checkGpu=false){
 try{
  $('perfLastRender').textContent='Reading resource usage…';
  const status=await api('/api/performance'+(checkGpu?'?check_gpu=true':''));
  const res=status.resources||{};
  $('perfCPU').textContent=res.cpu_percent==null?'—':res.cpu_percent.toFixed(1)+'%';
  $('perfRAM').textContent=res.ram_mb==null?'—':res.ram_mb.toFixed(1)+' MB';
  $('perfChildRAM').textContent=res.child_ram_mb==null?'—':res.child_ram_mb.toFixed(1)+' MB';
  $('perfCores').textContent=res.logical_cores||'—';
  if(checkGpu){
   const enc=status.gpu_encoders||[];
   $('gpuResult').textContent=enc.length?'Hardware H.264 encoders passed: '+enc.join(', '):
     'No tested hardware encoder available. Software H.264 will be used.';
  }
  const job=status.last_render;
  $('perfLastRender').textContent=job?
    'Last video: '+(job.preview?'15-second preview':'Full MP4')+
    (job.cached?' · From cache':'')+
    (job.encoder_used?' · '+job.encoder_used:'')+
    (job.elapsed_seconds!=null?' · '+job.elapsed_seconds+'s':'')+
    (job.speed_ratio!=null?' · '+job.speed_ratio+'× realtime':''):
    'No completed export measured this session.';
 }catch(e){$('perfLastRender').textContent='Performance information unavailable: '+e.message;}
}
function wireUI(){
 $$('.rail-item').forEach(b=>b.addEventListener('click',()=>panel(b.dataset.panel)));
 $('undoBtn').addEventListener('click',undoEdit);
 $('redoBtn').addEventListener('click',redoEdit);
 $('saveLookBtn').addEventListener('click',saveCurrentLook);
 $('loadLookBtn').addEventListener('click',loadSavedLook);
 $('resetLookBtn').addEventListener('click',resetCurrentLook);
 $$('[data-preset]').forEach(b=>b.addEventListener('click',()=>applyLook(b.dataset.preset)));
 $('splitLineBtn').addEventListener('click',splitSelected);
 $('duplicateLineBtn').addEventListener('click',duplicateSelected);
 $('deleteLineBtn').addEventListener('click',()=>deleteAt(state.selected));
 $('exportSrtBtn').addEventListener('click',exportSrt);
 $('snapBtn').addEventListener('click',toggleSnap);
 $('prevClipBtn').addEventListener('click',()=>jumpClip(-1));
 $('nextClipBtn').addEventListener('click',()=>jumpClip(1));
 $('zoomFit').addEventListener('click',fitTimeline);
 $('clipAnimation').addEventListener('change',e=>setClipMotion('animation',e.target.value));
 $('clipEffectMs').addEventListener('input',e=>setClipMotion('effectMs',Number(e.target.value)));
 $('clipPosX').addEventListener('input',e=>setClipMotion('x',Number(e.target.value)));
 $('clipPosY').addEventListener('input',e=>setClipMotion('y',Number(e.target.value)));
 $('resetClipMotion').addEventListener('click',resetClipMotion);
 $('applyClipMotionAll').addEventListener('click',applyClipMotionAll);
 $('previewClipMotion').addEventListener('click',previewSelectedMotion);
 bindPreviewPositionDragging();
 $('shortcutsBtn').addEventListener('click',()=>showShortcuts(true));
 $('closeShortcuts').addEventListener('click',()=>showShortcuts(false));
 $('shortcutsOverlay').addEventListener('click',e=>{if(e.target===$('shortcutsOverlay'))showShortcuts(false)});
 initResizer('panelResizer','x','--panel-width',312,240,470);
 initResizer('timelineResizer','y','--timeline-height',245,145,400);
 $('nudgeBack').addEventListener('click',()=>shiftSelected(-.05));
 $('nudgeForward').addEventListener('click',()=>shiftSelected(.05));
 $('refreshProjects').addEventListener('click',loadLibrary);
 $('deleteSelectedProjects').addEventListener('click',deleteSelectedProjects);
 $('selectAllProjects').addEventListener('change',e=>{
  if(e.target.checked)visibleProjects.forEach(p=>selectedProjects.add(p.id));
  else visibleProjects.forEach(p=>selectedProjects.delete(p.id));
  $('.library-check').forEach(box=>box.checked=e.target.checked);
  updateDeleteSelection();
 });
 $('refreshStorage').addEventListener('click',loadStorage);
 $('refreshPerformance').addEventListener('click',()=>loadPerformance(false));
 $('checkGPU').addEventListener('click',()=>loadPerformance(true));
 $('refineLyricsBtn').addEventListener('click',refineUncertainLyrics);
 $('applyRefineBtn').addEventListener('click',applyRefinement);
 $('startupPerformance').addEventListener('change',e=>{
  if(['eco','balanced','turbo'].includes(e.target.value)){
   try{localStorage.setItem('skellymotion-perf-mode',e.target.value)}catch{}
  }
 });
 $('renderPreviewBtn').addEventListener('click',previewVideo);
 $('downloadBtn').addEventListener('click',e=>downloadVideo(e,false));
 $('previewDownloadBtn').addEventListener('click',e=>downloadVideo(e,true));
 $('cleanupStorage').addEventListener('click',cleanupStorage);
 ['font','fontSize','position','textColor','accentColor','outline','dim','resolution','renderSpeed','fps','performanceMode','encoder'].forEach(k=>$(k).addEventListener('input',e=>setSetting(k,k==='fontSize'||k==='position'||k==='outline'||k==='dim'||k==='fps'?Number(e.target.value):e.target.value)));
 $('upper').addEventListener('change',e=>setSetting('upper',e.target.checked));
 ['mode','animation','background','aspect'].forEach(key=>$$(`[data-${key}]`).forEach(b=>b.addEventListener('click',()=>setSetting(key,b.dataset[key]))));
 $('heroUpload').addEventListener('click',chooseSong);
 $('exitBtn').addEventListener('click',quitStudio);
 $('checkUpdateBtn').addEventListener('click',()=>checkForUpdates(true));
 $('updateLater').addEventListener('click',()=>$('updateOverlay').classList.add('hidden'));
 window.addEventListener('skellymotion-close-request',()=>{quitStudio();});
 window.addEventListener('beforeunload',e=>{
  // Browser tab closes cannot synchronously run Save/Discard. A regular
  // browser warning and persistent crash recovery are the safe fallback.
  if(!window.pywebview?.api&&state.id&&(state.dirty||!state.persisted)){
   e.preventDefault();e.returnValue='';
  }
 });
 $('backgroundUploadTrigger').addEventListener('click',chooseBackground);
 $('audioFile').addEventListener('change',e=>{startUpload(e.target.files[0]);e.target.value='';});
 $('backgroundFile').addEventListener('change',e=>{uploadBackground(e.target.files[0]);e.target.value='';});
 $('lyricsText').addEventListener('input',()=>{$('confirmLyrics').disabled=!$('lyricsText').value.trim();queueSave();});
 $('confirmLyrics').addEventListener('click',confirmLyrics);
 $('closeReview').addEventListener('click',async()=>{if(await mayLeaveProject())resetWorkspace();});
 $('demoBtn').addEventListener('click',()=>{
  if(!state.id){loadDemo();return;}
  mayLeaveProject().then(ok=>{if(ok){resetWorkspace();loadDemo();}});
 });
 $('openProjectsWelcome').addEventListener('click',()=>{$('welcome').classList.add('hidden');panel('library');});
 $('resumeLastBtn').addEventListener('click',()=>restore(true));
 $('playButton').addEventListener('click',play);$('skipBack').addEventListener('click',()=>seek(state.time-5));$('skipAhead').addEventListener('click',()=>seek(state.time+5));
 $('zoomIn').addEventListener('click',()=>{state.zoom=clamp(state.zoom+.25,1,5);$('zoomDisplay').textContent=`${Math.round(state.zoom*100)}%`;renderTimeline();});
 $('zoomOut').addEventListener('click',()=>{state.zoom=clamp(state.zoom-.25,1,5);$('zoomDisplay').textContent=`${Math.round(state.zoom*100)}%`;renderTimeline();});
 $('timelineInner').addEventListener('click',e=>{if(e.target.closest('.lyric-clip'))return;const rect=$('ruler').getBoundingClientRect();seek(((e.clientX-rect.left)/rect.width)*state.duration);});
 $('saveBtn').addEventListener('click',save);
 $('topExport').addEventListener('click',()=>panel('export'));
 $('renderBtn').addEventListener('click',exportVideo);
 $('addLineBtn').addEventListener('click',()=>{let start=clamp(state.time,0,Math.max(0,state.duration-.5));let line={id:clipId(),text:'New lyric',start,end:Math.min(state.duration,start+2),words:[]};reflowWords(line);recordEdit('add');state.lines.push(line);state.lines.sort((a,b)=>a.start-b.start);selectLine(state.lines.indexOf(line),true);queueSave();});
 $('newBtn').addEventListener('click',async()=>{if(await mayLeaveProject())resetWorkspace();});
 $('previewFull').addEventListener('click',()=>{const stage=$('stage');if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});else stage.requestFullscreen?.().catch(()=>{});});
 window.addEventListener('resize',()=>{
   clearTimeout(resizeTimer);
   resizeTimer=setTimeout(()=>{resizePreview();drawWaveform();},100);
 });
 const hero=$('heroUpload');hero.addEventListener('dragover',e=>{e.preventDefault();hero.classList.add('drag-over');});hero.addEventListener('dragleave',()=>hero.classList.remove('drag-over'));hero.addEventListener('drop',e=>{e.preventDefault();hero.classList.remove('drag-over');if(e.dataTransfer.files.length)startUpload(e.dataTransfer.files[0]);});
 audio.addEventListener('ended',()=>{state.playing=false;});audio.addEventListener('pause',()=>{if(!audio.ended)state.playing=false;});audio.addEventListener('play',()=>{state.playing=true;});
 document.addEventListener('keydown',e=>{
  const ctrl=e.ctrlKey||e.metaKey;
  const typing=!!e.target.closest('input,textarea,select,[contenteditable="true"]');
  if(e.key==='Escape'&&!$('shortcutsOverlay').classList.contains('hidden')){e.preventDefault();showShortcuts(false);return;}
  if(ctrl&&e.code==='KeyS'){e.preventDefault();save();return;}
  if(typing)return; // Preserve OS text editing, selection and accessibility shortcuts.
  if(ctrl&&e.code==='KeyZ'){e.preventDefault();if(e.shiftKey)redoEdit();else undoEdit();return;}
  if(ctrl&&(e.code==='KeyY')){e.preventDefault();redoEdit();return;}
  if(ctrl&&e.code==='KeyD'){e.preventDefault();duplicateSelected();return;}
  if((e.key==='?'||e.code==='Slash')&&!e.altKey){e.preventDefault();showShortcuts(true);return;}
  if(ctrl||e.shiftKey||e.repeat)return;
  if(e.altKey&&['ArrowLeft','ArrowRight'].includes(e.code)){
   e.preventDefault();shiftSelected(e.code==='ArrowLeft'?-.05:.05);return;
  }
  if(e.altKey)return;
  if(e.code==='Space'&&!e.target.closest('button')){e.preventDefault();play();return;}
  if(e.code==='KeyS'){e.preventDefault();splitSelected();return;}
  if(e.code==='KeyN'){e.preventDefault();toggleSnap();return;}
  if(e.code==='Delete'||e.code==='Backspace'){e.preventDefault();deleteAt(state.selected);return;}
  if(e.code==='ArrowUp'){e.preventDefault();jumpClip(-1);return;}
  if(e.code==='ArrowDown'){e.preventDefault();jumpClip(1);return;}
 });
}
async function restore(interactive=false){
 const last=localStorage.getItem('lyricforge-last');
 if(!last||state.id||state.demo)return;
 const button=$('resumeLastBtn');
 button.disabled=true;
 if(interactive)button.textContent='Opening saved project…';
 try{
  const p=await api('/api/projects/'+encodeURIComponent(last));
  // Do not overwrite a new song selected while last-session lookup was in flight.
  if(state.id||state.demo)return;
  if(p.has_recovery){
   // Resume the crash-protected draft only after the user chooses Recover.
   await openSavedProject(p.id);return;
  }
  if(p.status==='editor'&&p.lines?.length){
   loadProjectData(p);
  }else if(p.status==='review'||p.status==='transcribing'){
   state.id=p.id;state.title=p.title;state.duration=p.duration;
   state.persisted=p.save_state!=='draft';state.dirty=false;notifyNativeSession();
   configureMedia();renderTitle();$('welcome').classList.add('hidden');
   $('reviewOverlay').classList.remove('hidden');
   $('transcribeProgress').classList.remove('hidden');$('lyricsText').classList.add('hidden');
   $('confirmLyrics').disabled=true;waitForTranscript(p.id);
  }else if(interactive){
   toast('The previous project could not be restored. Try Projects.',true);
  }
 }catch(e){
  if(localStorage.getItem('lyricforge-last')===last)localStorage.removeItem('lyricforge-last');
  button.classList.add('hidden');
  if(interactive)toast('Could not open the last project: '+e.message,true);
 }finally{
  button.disabled=false;button.textContent='↻ Resume last project →';
 }
}
restoreLayout();
try{const savedMode=localStorage.getItem('skellymotion-perf-mode');
 if(['eco','balanced','turbo'].includes(savedMode)){
  $('startupPerformance').value=savedMode;state.settings.performanceMode=savedMode;
 }}catch{}
wireUI();syncSettingUI();syncClipInspector();resizePreview();renderTimeline();updateEditButtons();
requestAnimationFrame(drawFrame);
if(document.documentElement.classList.contains('desktop-mode'))
 setTimeout(()=>checkForUpdates(false),9000);
let lastSession=null;
try{lastSession=localStorage.getItem('lyricforge-last')}catch{}
$('resumeLastBtn').classList.toggle('hidden',!lastSession);
// Windows startup should display a responsive editor immediately. Restoring a
// large song can decode audio, generate waveforms and populate many lyric clips.
// The user can explicitly resume in one click; browser sessions still restore.
if(lastSession&&!document.documentElement.classList.contains('desktop-mode'))
 setTimeout(()=>restore(false),350);
})();
