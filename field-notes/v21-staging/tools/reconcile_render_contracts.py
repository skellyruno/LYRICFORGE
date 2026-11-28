"""Restore the tested editorial engine without replacing the Creator engine.
Only operates on a disposable, previously reconciled candidate.
"""
import argparse
import ast
import hashlib
from pathlib import Path
import re
import zipfile

ARCHIVE_SHA = '4ba17dd5cdca24a040a05453706cda1881934d0d1e8704080e292e398ace6462'

HOLD = '''def _hold_frames(seconds, fps):
    return max(1, round(seconds * fps)) if seconds > 0 else 0


def hold_prepare(f, i):
    a, b = round(_num(f, "start", 0, HOLD_MAX, 0), 2), round(_num(f, "end", 0, HOLD_MAX, 2), 2)
    if a <= 0 and b <= 0:
        raise ValueError("Choose how long to hold the first frame, the last frame, or both")
    v = i["video"]
    fps = _edit_fps(v)
    if fps < 24 and any(abs(_hold_frames(t, fps) / fps - t) > .001 for t in (a, b)):
        fps = 24.0
    frames = max(1, round(v['duration']*fps)) + _hold_frames(a,fps) + _hold_frames(b,fps)
    return {"start": a, "end": b, "seconds": frames/fps, "frames": frames, "has_audio": v["has_audio"], "fps": fps}


def hold_build(p, o, out, safe):
    fps = o.get("fps", 30.0)
    first, last = _hold_frames(o['start'],fps), _hold_frames(o['end'],fps)
    base=f"setpts=PTS-STARTPTS,fps={fps:g}"
    # Single finite decoder; duplicate only the first cached frame, then reset
    # timestamps before the finite trailing pad. Avoid two-input concat stalls.
    if first: base+=f",loop=loop={first}:size=1:start=0,setpts=N/({fps:g}*TB)"
    if last: base+=f",tpad=stop_mode=clone:stop={last}"
    base+=f",trim=end_frame={o['frames']},setpts=N/({fps:g}*TB)"
    args=[*QUIET,"-y","-filter_threads","1","-threads","2","-i",str(p['video']),"-vf",base,"-map","0:v:0"]
    if o['has_audio']:
        samples=round(o['seconds']*48000)
        af="aresample=48000,"+(f"adelay={round(first/fps*48000)}S:all=1," if first else "")+f"apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB"
        args += ["-map","0:a:0","-af",af,"-c:a","aac","-b:a","192k"]
    else: args += ["-an"]
    return [*args,"-r",str(fps),"-fps_mode","cfr",*X264,"-threads","2",*FAST,"-t",str(o['seconds']),str(out)]


'''

DIRECTOR = '''

# Explicit internal routing: Creator's research/theme/proof and music/plugin
# contracts stay on the original engine. Standard cinematic documentaries use
# the independently tested editorial renderer and retain its complete plan.
import studio_editorial_director as _editorial_engine
_creator_make_plan = make_plan
_creator_render = render
configure_spatial = _editorial_engine.configure_spatial
encoded_frames = _editorial_engine.encoded_frames

def make_plan(lines, duration, assets, preset, brand='SKELLYMOTION', *,
              reference_profile=None, editorial_style='standard',
              visual_theme='legacy', skell_terminology=False, **options):
    theme.validate(visual_theme)
    if editorial_style not in ('standard','reference'):
        raise ValueError('Unknown editorial style')
    if (preset=='doc' and options.get('cinematic') and editorial_style=='standard'
            and visual_theme=='legacy' and not skell_terminology
            and not any(row.get('proof_label') or row.get('source_url') for row in lines)):
        result=_editorial_engine.make_plan(lines,duration,assets,preset,brand,
                                         reference_profile=reference_profile,**options)
        result.update(editorial_engine='v20',editorial_style=editorial_style,
                      visual_theme=visual_theme,skell_terminology=False)
        return result
    return _creator_make_plan(lines,duration,assets,preset,brand,
                              editorial_style=editorial_style,visual_theme=visual_theme,
                              skell_terminology=skell_terminology,**options)

def render(plan, audio, assets_folder, work, output, settings, size, make_ass,
           encode, check_cancel, progress, music=None):
    # Old authored documentary plans lack the engine marker; their explicit
    # composition/spatial fields are sufficient evidence of editorial origin.
    editorial = (plan.get('editorial_engine')=='v20' or
        (plan.get('preset')=='doc' and plan.get('cinematic_finish') and
         plan.get('visual_theme','legacy')=='legacy' and
         any(s.get('editorial') or s.get('graphic') or s.get('spatial_motion') or
             s.get('editorial_bridge_scene') for s in plan['scenes'])))
    fn=_editorial_engine.render if editorial else _creator_render
    return fn(plan,audio,assets_folder,work,output,settings,size,make_ass,
              encode,check_cancel,progress,music)
'''

CINEMATIC = '''

# Preserve the Creator caption/transition path for existing plans. Explicit
# documentary marker/auto captions use the exact editorial implementation.
import studio_editorial_cinematic as _editorial_cinema
_creator_write_kinetic_ass = write_kinetic_ass
_creator_voice_chain = voice_chain
silent_voice = _editorial_cinema.silent_voice

def write_kinetic_ass(plan,width,height,target):
    if (plan.get('editorial_engine')=='v20' or plan.get('caption_style') in ('marker','auto')
            or (plan.get('preset')=='doc' and plan.get('caption_track') is not None)):
        return _editorial_cinema.write_kinetic_ass(plan,width,height,target)
    return _creator_write_kinetic_ass(plan,width,height,target)

def voice_chain(style, *, silent=False):
    return _editorial_cinema.voice_chain(style,silent=True) if silent else _creator_voice_chain(style)
'''

def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Unexpected reconciliation anchor: '+old[:100])
    return text.replace(old,new,1)

def apply(root, archive):
    root=Path(root)
    archive=Path(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=ARCHIVE_SHA:raise ValueError('Wrong V20 archive')
    if not (root/'studio_theme.py').is_file():raise ValueError('Requires the full Creator candidate')
    changes={}
    def read(name):return (root/name).read_text(encoding='utf-8')
    def add(name,value):
        if name.endswith('.py'):ast.parse(value,filename=name)
        changes[name]=value
    with zipfile.ZipFile(archive) as z:
        def archived(name):return z.read('LYRICFORGE-main/'+name).decode('utf-8')
        for name,target in [('studio_editorial.py','studio_editorial_primitives.py'),
                            ('studio_cinematic.py','studio_editorial_cinematic.py'),
                            ('studio_director.py','studio_editorial_director.py')]:
            if (root/target).exists():raise ValueError('Refusing to overwrite '+target)
            src=archived(name)
            if name=='studio_director.py':
                src=once(src,'import studio_cinematic as cinema','import studio_editorial_cinematic as cinema')
            add(target,src)
    add('studio_editorial.py',read('studio_editorial.py')+
        '\n# Missing V20 primitives; preserve Creator evidence_card and technical_frame.\n'
        'from studio_editorial_primitives import ACCENT, STOP, emphasis, marker_font, marker_layout, fit_text, artwork\n')
    add('studio_cinematic.py',read('studio_cinematic.py')+CINEMATIC)
    add('studio_director.py',read('studio_director.py')+DIRECTOR)
    walk=read('studio_walkthrough.py')
    add('studio_walkthrough.py',walk+"\nCAPTIONS.update({'marker','auto'})\n")
    voice=read('studio_creator.py')
    voice=once(voice,'def resolve_voice(voice):','def resolve_voice(voice, *, allow_draft=True):')
    voice=once(voice,"if options.get(name)),''", "if options.get(name) and (allow_draft or name!='draft')),''")
    voice=once(voice,'        with wave.open(str(staged),', '''            neural=list(neural)
            if len(neural)!=len(phrases):raise RuntimeError('Incomplete neural narration output')
        with wave.open(str(staged),''')
    add('studio_creator.py',voice)
    quick=read('studio_quick2.py')
    begin=quick.index('def _hold_frames(');end=quick.index('# ---- cut out a section',begin)
    quick=quick[:begin]+HOLD+quick[end:]
    quick=once(quick,'("fps", "setpts", "tpad", "adelay", "apad", "atrim")',
               '("fps", "setpts", "loop", "tpad", "trim", "aresample", "adelay", "apad", "atrim", "asetpts")')
    add('studio_quick2.py',quick)
    # Check the new page script in both existing workflow contracts. This does
    # not replace the release workflow or promote the candidate.
    for name in ('.github/workflows/test.yml','.github/workflows/windows-release.yml'):
        value=read(name)
        value=re.sub(r'(?m)^([ \t]*)node --check static/make\.js[ \t]*$',
                     r'\g<0>\n\1node --check static/welcome-preferences.js',value)
        if 'node --check static/welcome-preferences.js' not in value:raise ValueError('Missing syntax check anchor')
        add(name,value)
    # Update the old implementation-specific assertion to check the newer
    # idle-work guard and execute the actual cadence helper in Node.
    name='tests/test_recovery_modes.py'
    test=read(name)
    old='    assert "if((document.hidden||covered)&&!state.playing){" in script'
    new='''    assert "if(covered&&!state.playing&&!state.lines.length)return;" in script
    import re, shutil, subprocess
    match = re.search(r"function previewInterval\\([^\\n]+\\)\\{[^}]+\\}", script)
    assert match, "Missing idle preview cadence helper"
    if shutil.which("node"):
        result = subprocess.run(["node", "-e", match.group(0) + ";if(previewInterval(true,false,false,'turbo')<200||previewInterval(false,true,false,'turbo')<200||previewInterval(false,false,true,'turbo')>20)process.exit(1)"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr'''
    if old in test:test=once(test,old,new)
    else:raise ValueError('Unexpected recovery test baseline')
    test=once(test,'if(state.backgroundIsVideo&&!bgVid.paused)bgVid.pause();','if(state.backgroundIsVideo&&!state.playing&&!bgVid.paused)bgVid.pause();')
    add(name,test)
    # Preserve legacy documentary defaults without changing explicit themes,
    # newer research production or the source/proof ledger.
    server=read('server.py')
    server=once(server,'        body=CreatorRequest.model_validate_json(payload)\n        import studio_theme', '''        body=CreatorRequest.model_validate_json(payload)
        if body.story=='documentary' and body.production_mode!='research' and 'visual_theme' not in body.model_fields_set:
            body=body.model_copy(update={'visual_theme':'legacy'})
        import studio_theme''')
    server=once(server,'        if body.auto_render:\n            _,settings,plan=prepare_director(project_id,DirectorRequest(', '''        if body.auto_render:
            legacy_documentary=body.story=='documentary' and body.production_mode!='research'
            _,settings,plan=prepare_director(project_id,DirectorRequest(''')
    server=once(server,"editorial_style='reference',visual_theme=body.visual_theme,skell_terminology=body.skell_terminology,caption_style='clean',caption_scale=.85,transition_style='auto'","editorial_style='standard' if legacy_documentary else 'reference',visual_theme=body.visual_theme,skell_terminology=body.skell_terminology,caption_style='marker' if legacy_documentary else 'clean',caption_scale=.85,transition_style='cut' if legacy_documentary else 'auto'")
    server=once(server,'caption_style=body.caption_style,caption_scale=body.caption_scale',"caption_style=('marker' if plan.get('editorial_engine')=='v20' else 'clean') if body.caption_style=='auto' else body.caption_style,caption_scale=body.caption_scale")
    add('server.py',server)
    # All source is validated before writing; the original archive and Creator
    # checkout are never edited. Record exactly which files changed.
    for name,value in changes.items():
        (root/name).write_text(value,encoding='utf-8')
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in changes}

if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path);p.add_argument('archive',type=Path);p.add_argument('report',type=Path);a=p.parse_args()
    a.report.write_text(json.dumps(apply(a.candidate,a.archive),indent=2),encoding='utf-8')
