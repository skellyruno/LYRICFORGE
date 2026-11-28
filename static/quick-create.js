/* One-click research and video-edit entry points. Use the existing real job API. */
(() => {
'use strict';
const $=id=>document.getElementById(id), ui=window.SkellyUI;
const q={busy:false,draft:null,project:null,topic:'',focus:'',seconds:60,delivery:'documentary',format:'youtube',sound_design:true,title_motion:true,history:[],modelCheck:0};
async function detectModels(){
 const ticket=++q.modelCheck,selected=$('researchModel').value;
 $('researchModelStatus').textContent='Checking local model server…';
 try{
 const info=await ui.api('/api/creator/writing-models');
 if(ticket!==q.modelCheck)return;
 const options=[ui.el('option',{value:'',text:'Source-based writing (no model)'})];
 for(const m of info.models||[])options.push(ui.el('option',{value:m.name,text:m.name}));
 $('researchModel').replaceChildren(...options);
 if((info.models||[]).some(m=>m.name===selected))$('researchModel').value=selected;
 else if(selected){$('researchModelStatus').textContent='Previously selected model is unavailable. Choose a writing mode.';return;}
 $('researchModelStatus').textContent=info.connected?(info.models.length?'Local models detected. Select one to enable AI writing.':'Ollama is running; install a model in Ollama first.'):'Ollama not connected. Source-based writing remains available.';
 }catch(e){if(ticket===q.modelCheck)$('researchModelStatus').textContent='Model detection unavailable. Source-based writing remains available.';}
}
function open(){ $('researchStudio').classList.remove('hidden'); $('researchTopic').focus();detectModels(); }
function rememberDraft(){
 if(!q.draft)return;
 q.history.push({draft:JSON.parse(JSON.stringify({...q.draft,chapters:readScript()})),delivery:q.delivery,format:q.format,sound_design:q.sound_design,title_motion:q.title_motion,visuals:$('researchVisuals').checked,seconds:q.seconds,focus:q.focus});
 if(q.history.length>10)q.history.shift();
}
function undoDraft(){
 if(q.busy||!q.history.length)return;
 const previous=q.history.pop();const {draft,visuals,...options}=previous;
 Object.assign(q,options);$('researchVisuals').checked=visuals;$('researchLength').value=String(q.seconds);
 paint({...draft,options:{}});$('researchUndoDraft').disabled=!q.history.length;
 status('Previous draft restored. Render it to create a new video; existing exports are unchanged.');
}
function home(){if(q.busy)return; $('researchStudio').classList.add('hidden');window.SkellyBridge.home();}
function status(text){$('researchStatus').classList.remove('hidden');$('researchStatus').textContent=text;}
function busy(value){q.busy=value;for(const id of ['researchRun','researchRevise','researchRenderScript','researchHome','researchTopic','researchLength','researchInstruction','researchScript','researchModel','researchVisuals','researchRefreshModels']) $(id).disabled=value;$('researchUndoDraft').disabled=value||!q.history.length;}
function paint(d){q.draft=d;$('researchScript').value=d.chapters.map(c=>c.narration+' | '+c.source_url).join('\n');$('researchReview').classList.remove('hidden');$('researchSource').replaceChildren(...(d.sources||[d.source]).map(r=>ui.el('a',{class:'research-source-link',href:r.url,target:'_blank',rel:'noopener noreferrer',text:(r.kind==='bibliography'?'Related reading: ':'Source: ')+r.title})),ui.el('a',{href:d.license_url,target:'_blank',rel:'noopener noreferrer',text:'CC BY-SA 4.0'}));$('researchEstimate').textContent='~'+d.estimated_seconds+'s narration · '+d.warnings.join(' ');Object.assign(q,d.options||{});if(typeof d.options?.auto_pictures==='boolean')$('researchVisuals').checked=d.options.auto_pictures;}
function applyInstruction(){const s=$('researchInstruction').value.trim();if(!s)throw new Error('Tell us what to change.');let recognized=false;
 const focus=s.match(/\bfocus (?:more )?on\s+(.+?)(?:[,.;]|$)/i);if(focus){q.focus=focus[1].slice(0,160);recognized=true;}
 const length=s.match(/\b(\d{1,3})\s*(?:seconds?|secs?|s)\b/i);if(length){q.seconds=Math.max(15,Math.min(180,Number(length[1])));recognized=true;}
 else if(/\b(shorter|shorten|less detail)\b/i.test(s)){q.seconds=Math.max(15,Math.round(q.seconds*.65));recognized=true;}
 else if(/\b(longer|more detail|expand)\b/i.test(s)){q.seconds=Math.min(180,Math.round(q.seconds*1.5));recognized=true;}
 if(/\b(calm|slower|documentary)\b/i.test(s)){q.delivery='documentary';recognized=true;}else if(/\b(energetic|faster|brisk)\b/i.test(s)){q.delivery='energetic';recognized=true;}
 if(/\b(square)\b/i.test(s)){q.format='square';recognized=true;}else if(/\b(landscape|youtube)\b/i.test(s)){q.format='youtube';recognized=true;}else if(/\b(vertical|shorts|reel)\b/i.test(s)){q.format='reel30';recognized=true;}
 if(!recognized)throw new Error('This source-based mode supports focus, length, narration pace and format changes. For other wording, edit the script below.');
 $('researchLength').value=String(q.seconds);
}
function readScript(){
 return $('researchScript').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map(s=>{const i=s.lastIndexOf(' | ');if(i<1)throw new Error('Keep a source URL on every script line.');const narration=s.slice(0,i).trim(),source_url=s.slice(i+3).trim();return q.draft.chapters.find(c=>c.narration===narration&&c.source_url===source_url)||{title:narration.split(/\s+/).slice(0,5).join(' '),narration,source_url,visual_hint:narration.slice(0,160)};});
}
async function render(mode){if(q.busy)return;busy(true);try{
 if(mode==='new'){q.history=[];q.topic=$('researchTopic').value.trim();q.focus='';q.seconds=Number($('researchLength').value);q.delivery='documentary';q.format='youtube';q.sound_design=true;q.title_motion=true;}
 if(!q.topic)throw new Error('Enter a topic first.');
 if(!Number.isInteger(q.seconds)||q.seconds<15||q.seconds>180)throw new Error('Choose a length between 15 and 180 seconds.');
 const model=$('researchModel').value.trim();
 let direct=false;
 if(mode==='revise'){
   rememberDraft();
   const instruction=$('researchInstruction').value.trim();
   if(!instruction)throw new Error('Tell us what to change.');
   if(!model&&/^(?:remove|delete|move|(?:set|change) (?:scene|chapter)|(?:set |change )?(?:format|aspect ratio|delivery|narration pace)|(?:turn |set )?(?:sound design|title motion|automatic footage))\b/i.test(instruction)){
     status('Applying scene and production edits…');
     const edit=await ui.post('/api/creator/research-edit',{chapters:readScript(),instruction});
     paint({...q.draft,chapters:edit.chapters,options:edit.options,warnings:edit.warnings,estimated_seconds:Math.round(edit.chapters.reduce((n,c)=>n+c.narration.split(/\s+/).length,0)/2.35)});
     direct=true;
   }else if(!model)applyInstruction();
 }
 if(mode==='revise'&&model&&!$('researchInstruction').value.trim())throw new Error('Tell us what to change.');
 if(mode==='revise'&&model)q.seconds=Number($('researchLength').value);
 if(mode!=='script'&&!direct){status('Collecting sources and composing the narration…');paint(await ui.post('/api/creator/research-compose',{topic:q.topic,target_seconds:q.seconds,focus:q.focus,model,instruction:mode==='revise'?$('researchInstruction').value.trim():'',prior:mode==='revise'&&q.draft?readScript():[]}));}
 if(!q.draft)throw new Error('Create a research draft first.');
 const rows=readScript();
 status('Creating narration, captions and motion graphics…');const form=new FormData();form.append('payload',JSON.stringify({product:q.draft.product,brief:q.focus,production_mode:'research',story:'documentary',chapters:rows,voice:'auto',delivery:q.delivery,format:q.format,output_fps:24,visual_theme:'clean',auto_render:true,preview:false,sound_design:q.sound_design,title_motion:q.title_motion,auto_pictures:$('researchVisuals').checked,research_sources:q.draft.sources||[q.draft.source]}));
 const result=await ui.api('/api/creator/create',{method:'POST',body:form});
 const job=await ui.runJob(result.job_id,j=>ui.showStatus($('researchStatus'),j));const out=job.outputs||{};q.project=result.project_id;q.draft.chapters=rows;status('Video ready. Review the source and narration before publishing.');
 $('researchResults').replaceChildren(...[out.video?ui.el('video',{class:'director-proof',src:out.video,controls:true,preload:'metadata'}):null,out.video?ui.el('a',{class:'download-btn',href:out.video,download:'',text:'Download video'}):null,out.plan?ui.el('a',{class:'wide-ghost',href:out.plan,download:'',text:'Download scene plan & sources'}):null,ui.el('button',{class:'wide-ghost',type:'button',text:'Open editable project',onclick:async()=>{await window.SkellyBridge.openSavedProject(result.project_id);if(window.SkellyBridge.state().id===result.project_id)$('researchStudio').classList.add('hidden');}})].filter(Boolean));
 }catch(e){status(e.message);ui.toast(e.message,true);}finally{busy(false);}}
$('researchRefreshModels').addEventListener('click',detectModels);$('researchUndoDraft').addEventListener('click',undoDraft);
$('openResearchWelcome').addEventListener('click',open);$('researchHome').addEventListener('click',home);$('researchRun').addEventListener('click',()=>render('new'));$('researchRevise').addEventListener('click',()=>render('revise'));$('researchRenderScript').addEventListener('click',()=>render('script'));
})();
