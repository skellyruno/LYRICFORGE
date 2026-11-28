"""Local-first scene director adapted from the supplied autoedit.py/director prompt.

No network, external AI, generated claims, inline SVG execution or arbitrary paths.
Plan at transcript boundaries, select supplied media, render and cache individual scenes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont, ImageOps

import studio_performance as perf
import studio_director_intelligence as intel
import studio_live_diagrams as live
from studio_effect_visuals import KINDS as EFFECT_VISUALS
import studio_editorial_cinematic as cinema
import studio_walkthrough as walk
import studio_editorial as editorial
import studio_editorial_motion as editorial_motion
import studio_camera as camera
import studio_continuity as continuity
import studio_product_motion as product_motion
import studio_spatial as spatial
import studio_score as score
import studio_musical_edit as musical_edit
from studio_clips import probe_media

VERSION = 25
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.m4v', '.webm'}
PRESETS = {
    'music': {'pace': 2.5, 'maximum': 6, 'accent': '#94f58c', 'background': '#101615'},
    'doc': {'pace': 4.5, 'maximum': 9, 'accent': '#94f58c', 'background': '#101615'},
    'plugin': {'pace': 9, 'maximum': 15, 'accent': '#f5b942', 'background': '#101216'},
}
ASSET_PATTERN = re.compile(r'[a-f0-9]{32}\.(?:png|jpg|jpeg|webp|mp4|mov|mkv|m4v|webm)')


def terms(text: str) -> set[str]:
    return set(re.findall(r'[\w]+', text.casefold())) - {'the', 'this', 'that', 'and', 'with', 'for', 'you', 'your', 'is', 'to', 'a', 'of', 'in', 'it'}


def asset_path(folder: Path, key: str) -> Path | None:
    if not isinstance(key, str) or not ASSET_PATTERN.fullmatch(key):
        return None
    path = folder / key
    return path if path.is_file() and not path.is_symlink() else None


def assets_for(folder: Path, include_disabled=False) -> list[dict]:
    if not folder.is_dir() or folder.is_symlink():
        return []
    index = perf.read_cache(folder / 'index.json')
    items = []
    for key, value in sorted(index.items()):
        path = asset_path(folder, key)
        if path is None or not isinstance(value, dict):
            continue
        if value.get("disabled") and not include_disabled: continue
        label = str(value.get('name', key))[:120]
        items.append({'id': key, 'name': label, 'kind': 'video' if path.suffix in VIDEO_EXT else 'image',
                      'description': str(value.get('description', ''))[:300],
                      'features': value.get('features', {}),
                      **{k:value[k] for k in ('role','group','order','focus_point','trim_start','trim_end','disabled') if k in value},
                      **({'source': value['source']} if isinstance(value.get('source'), dict) else {})})
    return items[:40]


def make_plan(lines: list[dict], duration: float, assets: list[dict], preset: str,
              brand: str = 'SKELLYMOTION', *, fps: int = 30, preview: bool = False, analysis: dict | None = None, intensity: str = "medium", diagrams: bool = False, motion: str = "dynamic", transitions: bool = False, audio_start: float = 0., silent: bool = False, cinematic: bool = False, guided_replay: bool = False, title_motion: bool = False, reference_profile: dict | None = None) -> dict:
    """Deterministic shot selection from real transcript and asset descriptions.

    Timing is represented in frames to avoid gaps/drift. No invented facts,
    quotations, coordinates, or filenames; cards use only transcript text.
    """
    if preset not in PRESETS or fps not in (24, 30, 60) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid director timing or style')
    duration = min(duration, 15.0) if preview else duration
    if duration > 1800:
        raise ValueError('Director currently supports up to 30 minutes of audio')
    total = max(1, round(duration * fps))
    look = dict(PRESETS[preset])
    if cinematic and preset=="doc" and reference_profile:
        from studio_reference import pacing
        look["pace"],look["maximum"]=pacing(reference_profile,look["pace"],look["maximum"])
    lines = [line for line in lines if float(line['start']) < duration and float(line['end']) > 0]
    # The reference director cuts near sentence boundaries. Confirmed lyric
    # clip boundaries are the local equivalent, including pauses in speech.
    boundaries = sorted({round(float(line['end']) * fps) for line in lines if 0 < float(line['end']) < duration})
    # Split plugin diagrams at changes in technical topic (including retune mode).
    topic_cuts = []
    if (preset == 'plugin' and (diagrams or cinematic)) or (preset == 'doc' and cinematic):
        for a,b in zip(lines,lines[1:]):
            explicit_chapters=bool(a.get('chapter_title') and b.get('chapter_title'))
            chapter_change=explicit_chapters and a['chapter_title']!=b['chapter_title']
            if preset=='doc' and a.get('graphic')!=b.get('graphic'):chapter_change=True
            if chapter_change or (preset=='plugin' and not explicit_chapters and ((cinematic and float(a['end'])-float(a['start'])>=2) or intel.technical_topic(a['text']) != intel.technical_topic(b['text']))):
                point = round(float(b['start'])*fps)
                if 0 < point < total: topic_cuts.append(point)
    # Web photos must not masquerade as a plugin UI or a source document.
    assets = [a for a in assets if not a.get("source") and not a.get("disabled")]
    if preset == "plugin": assets = [a for a in assets if walk.is_plugin_asset(a)]
    rhythm = intel.cut_boundaries(analysis or {}, duration, fps, lines, intensity) if preset == "music" else []
    scenes, cursor, used, repairs = [], 0, [], 0
    chapter_no=0; last_chapter=None
    while cursor < total:
        ideal = cursor + round(look['pace'] * fps)
        maximum = min(total, cursor + round(look['maximum'] * fps))
        lower = cursor + round(1.0 * fps)
        candidates = [b for b in boundaries if lower <= b <= maximum and abs(b - ideal) <= round(2.0 * fps)]
        end = total if total - cursor <= round(look['pace'] * fps * 1.2) else min(maximum, min(candidates, key=lambda b: abs(b - ideal)) if candidates else ideal)
        if topic_cuts and not rhythm:
            change = next((p for p in topic_cuts if p >= cursor+fps), None)
            if change is not None and change <= maximum:
                end = change
        if rhythm:
            end = next((b for b in rhythm if b > cursor), total)
        if not rhythm and total - end < fps:
            end = total
        end = max(cursor + 1, min(end, total))
        start_sec, end_sec = cursor / fps, end / fps
        active = [line for line in lines if float(line['end']) > start_sec and float(line['start']) < end_sec]
        # A frame-rounded boundary can overlap a new sentence by a few milliseconds.
        # Choose the dominant sentence, not an almost-zero overlap at either end.
        meaningful=[row for row in active if min(end_sec,float(row['end']))-max(start_sec,float(row['start'])) >= .08]
        text = ' '.join(str(row['text']) for row in meaningful)
        hint=' '.join(str(row.get('visual_hint','')) for row in meaningful)
        chapter_title=next((str(row.get('chapter_title')) for row in meaningful if row.get('chapter_title')), '')
        first = str(meaningful[0]['text']) if meaningful else ''
        title = ' '.join(re.split(r'[.!?]',first,maxsplit=1)[0].split()[:6])[:64] or brand
        if title.split()[-1].lower() in {'a','an','the','on','of','to','and','your'} and len(title.split())>1: title=title.rsplit(' ',1)[0]
        captions, fixed = intel.captions_for(active, start_sec, end_sec)
        repairs += fixed
        scene = {'start': start_sec, 'end': end_sec, 'frames': end-cursor, 'type': 'big_text', 'text': title,
                 'captions': captions, 'camera': 'still'}
        if chapter_title and chapter_title!=last_chapter:
            chapter_no+=1;last_chapter=chapter_title
        if cinematic:
            scene.update(cinematic_finish=True,chapter=chapter_no if preset=='doc' and chapter_no else len(scenes)+1,brand=brand)
            if chapter_title:scene['hero_title']=chapter_title
            if title_motion:scene['title_motion']=True
            if not chapter_title and re.search(r'\bretune speed knob\b',text.lower()):
                scene['hero_title']='100 ms / Slow response' if re.search(r'\b(?:100|one hundred)\b',text.lower()) else '0 ms / Hard response' if re.search(r'\b(?:zero|0)\b',text.lower()) else 'Retune speed'
        if cinematic and preset=='doc' and reference_profile:
            import studio_story
            scene['narrative_role']=studio_story.role_for(text,hint,next((row.get('graphic') for row in meaningful if row.get('graphic')),None))
        # Asset matching prefers a semantic filename/description and diversity.
        if assets:
            pool = [a for a in assets if not (len(used) >= 2 and used[-1] == used[-2] == a['id'])] or assets
            def score(a):
                overlap = len(terms(text) & terms(a['name'] + ' ' + a.get('description', ''))) + 2*len(terms(hint) & terms(a['name']+' '+a.get('description','')))
                features=a.get('features') or {}
                previous=next((v.get('features',{}) for v in assets if used and v['id']==used[-1]),{})
                visual = float(features.get('quality',.5)) + .4*intel.diversity(features,previous)
                if preset=='music': visual += float(features.get('motion',0))
                if preset=='doc' and overlap>0:
                    visual+=.45 if a['kind']=='video' else 0.
                    if reference_profile and scene.get('narrative_role'):
                        visual+=studio_story.bonus(reference_profile,scene['narrative_role'],a)
                    # Explicit shot intent is a tie-break, not permission to select unrelated media.
                    intent=(hint+' '+text).casefold();role=a.get('role')
                    if re.search(r'\b(?:document|article|evidence|excerpt|quotation)\b',intent) and role=='document':visual+=1.2
                    if re.search(r'\b(?:macro|close-up|capture detail|interface|control)\b',hint.casefold()) and role=='plugin_state':visual+=1.2
                    if re.search(r'\b(?:footage|recording|b-roll|moving shot)\b',hint.casefold()) and a['kind']=='video':visual+=1.2
                return (overlap, visual - .45*used.count(a['id']), int(preset == 'plugin' and a['kind'] == 'image'))
            chosen = max(pool, key=score)
            if preset=="plugin":
                recording=walk.choose_recording(assets,text+' '+hint,terms,used)
                if recording is not None: chosen=recording
            # Documentary footage needs an actual metadata match. Otherwise use a card.
            if score(chosen)[0] == 0 and (preset == "doc" or (preset == "plugin" and diagrams and intel.diagram_kind(text))):
                pool = []
            if cinematic and preset=='plugin' and diagrams and re.search(r'\b(?:conceptually|illustration|conceptual|simulation)\b',(text+' '+hint).lower()) and intel.diagram_kind(text+' '+hint): pool=[]
            if pool:
                kind = 'ui_demo' if preset == 'plugin' else 'document' if chosen['kind'] == 'image' and (chosen.get('role')=='document' or terms(chosen['name']+' '+chosen.get('description','')) & {'article','document','source','comment','forum'}) else 'broll'
                scene.update(type=kind, asset=chosen['id'], asset_name=chosen['name'],
                             camera='still' if kind in ('ui_demo','document') else ('push' if len(scenes) % 2 == 0 else 'pull'),
                             text=title if preset == 'plugin' else '')
                scene['features']=chosen.get('features',{})
                if chosen.get('role'):scene['asset_role']=chosen['role']
                if preset=='plugin' and chosen['kind']=='video' and chosen.get('role')=='plugin_recording':
                    scene['recorded_demo']=True
                    scene['asset_start'],scene['recorded_seconds']=walk.recording_window(chosen,(end-cursor)/fps,used.count(chosen['id']))
                if preset=='plugin' and cinematic and guided_replay and chosen['kind']=='image' and chosen.get('role')=='plugin_state':
                    prior=walk.pair_for(chosen,assets)
                    if prior:
                        scene['before_asset']=prior['id']
                        if scene.get('hero_title') and not chapter_title:scene['hero_title']='TO '+scene['hero_title']
                    if chosen.get('focus_point') is not None: scene['focus_point']=chosen['focus_point']
                    if prior or scene.get('focus_point') is not None: scene['guided_replay']=True
                if preset=='doc' and cinematic:
                    if chosen.get('role')=='plugin_state' and chosen.get('focus_point') is not None:scene['focus_point']=chosen['focus_point']
                    if kind=='document':
                        scene.update(editorial='evidence',camera='push',evidence_focus=chosen.get('focus_point'))
                    elif chosen['kind']=='video' and float(scene['features'].get('duration',0) or 0)>0:
                        scene['asset_start'],scene['editorial_seconds']=walk.recording_window(chosen,(end-cursor)/fps,used.count(chosen['id']))
                        if scenes and scenes[-1].get('asset')==chosen['id'] and 'editorial_seconds' in scenes[-1]:
                            prev=scenes[-1];next_start=prev['asset_start']+prev['editorial_seconds'];limit=min(float(chosen.get('trim_end') or scene['features']['duration']),float(scene['features']['duration']))
                            if next_start<limit-.05:
                                scene['asset_start']=next_start;scene['editorial_seconds']=min((end-cursor)/fps,limit-next_start)
                if preset=='music':
                    variant = ('clean' if motion=='clean' else ('clean','reverse')[len(scenes)%2] if motion=='pingpong' else intel.VARIATIONS[len(scenes)%len(intel.VARIATIONS)])
                    if variant in ('reverse','mirror_reverse') and (end-cursor)/fps>3.: variant='mirror'
                    scene['variation']=variant
                    clip_duration=float(scene['features'].get('duration',0) or 0)
                    if clip_duration>0: scene['asset_start']=round((used.count(chosen['id'])*((end-cursor)/fps))%clip_duration,3)
                used.append(chosen['id'])
        if not scene.get('asset') and diagrams and preset=='plugin' and intel.diagram_kind(text+' '+hint):
            scene.update(type='diagram',text=intel.diagram_kind(text+' '+hint),camera='still')
            if scene['text']=='Pitch processing':
                scene['retune_demo_ms']=0. if re.search(r'\b(?:zero|fast|hard)\b', text.lower()) else 100. if re.search(r'\b(?:100|one hundred)\s*(?:ms|milliseconds)\b',(text+' '+hint).lower()) else 70.
        if not scene.get('asset') and preset=='music':
            scene.update(type='visualizer',text='',camera='still')
        if transitions and not cinematic and preset=='music' and len(scenes) and not (scene['type']=='visualizer' and scenes[-1]['type']=='visualizer'):
            scene['transition']='dip';scenes[-1]['dip_out']=True
        # Keep speech as the primary reference; no extra branded tail is added.
        # When the last short region is silent, use it as a natural outro.
        if end == total and not active and preset != "music":
            scene.update(type='outro', text=brand, camera='still')
            scene.pop('asset', None); scene.pop('asset_name', None); scene.pop('before_asset',None); scene.pop('guided_replay',None)
        if preset=='doc' and cinematic and scene['type']=='big_text':
            # Explicit chapter titles only; otherwise use transcript-derived statements.
            scene.update(editorial='chapter' if chapter_title and (not scenes or scenes[-1].get('hero_title')!=chapter_title) else 'statement',camera='push')
            scene.pop('title_motion',None)
        graphic = next((row.get('graphic') for row in meaningful if row.get('graphic')), None)
        if not graphic and cinematic and preset=='doc' and scene.get('asset_role') not in ('plugin_state','plugin_recording') and not scene.get('recorded_demo') and not scene.get('guided_replay'):
            from studio_auto_composition import plan as auto_composition
            graphic=auto_composition(text,hint,chapter_title or title,assets,terms,(end-cursor)/fps)
            if graphic:
                scene['automatic_collage']=True
                if graphic.get('storyboard'):scene['storyboard']=graphic['storyboard']
        if graphic and cinematic and preset!='music':
            scene.update(type='big_text',graphic=editorial_motion.validate_graphic(graphic),editorial='graphic',camera='still')
            if scene.get('asset') and used and used[-1]==scene['asset']:used.pop()
            for k in ('asset','asset_name','asset_role','features','asset_start','editorial_seconds','recorded_seconds','recorded_demo','guided_replay','before_asset','title_motion','focus_point','evidence_focus'):scene.pop(k,None)
        if cinematic and preset=='doc' and scene.get('editorial') in ('chapter','statement','graphic'):
            scene['editorial_look']='midnight'
        if cinematic and preset=='doc' and scene['type']=='broll' and str(scene.get('asset','')).lower().endswith(tuple(VIDEO_EXT)) and scene.get('asset_role')=='broll':
            scene['camera_path']='push' if len(scenes)%2==0 else 'pull'
        if cinematic and preset=='doc' and scene['type']=='broll' and str(scene.get('asset','')).lower().endswith(tuple(VIDEO_EXT)) and scene.get('asset_role')=='plugin_recording':
            scene['camera_path']='present'
        if cinematic and preset=='doc' and scene.get('asset_role')=='plugin_state' and str(scene.get('asset','')).endswith(tuple(IMAGE_EXT)) and scene['type']=='broll':
            scene['product_motion']=True
        scenes.append(scene)
        cursor = end
    if cinematic and preset=='doc':
        scenes=continuity.connect(scenes,fps)
        configure_spatial(scenes,fps)
    plan={'version': VERSION, 'preset': preset, 'fps': fps, 'duration': duration, 'frames': total,
            'scenes': scenes, 'director': 'local', 'audio_start':audio_start, 'silent':silent,
            'cinematic_finish':cinematic,'title_motion':bool(cinematic and title_motion),'crossfades':bool(cinematic and transitions),'caption_repairs':repairs, 'warnings': ([] if assets or preset=='music' else ['No visual assets supplied: transcript-based text cards will be used.'])}
    if cinematic and preset=='doc':
        # New plans receive the cinematic arrangement; old saved plans and plugin
        # exports keep their exact historical score path. Authored layout repair
        # remains opt-in, while generated comparisons are repaired automatically.
        plan['score_arc']='cinematic'
        if reference_profile:plan['reference_pacing']={'pace':look['pace'],'maximum':look['maximum']}
        plan['caption_track'],_=intel.captions_for(lines,0,total/fps)
    if preset=='music':
        plan.update(beat_confidence=(analysis or {}).get('confidence',0), bpm=(analysis or {}).get('bpm',0), beat_aligned=bool(rhythm))
    plan['review']=intel.review(plan)
    return plan


def configure_spatial(scenes,fps):
    """Recompute spatial provenance after optional media replacement."""
    for i,scene in enumerate(scenes):
        for key in ('spatial_motion','spatial_bridge','bridge_scene','bridge_seconds','editorial_bridge_scene','editorial_bridge_asset','editorial_bridge_seconds','footage_bridge_seconds'):scene.pop(key,None)
        if scene.get('product_motion') and scene.get('asset_role')=='plugin_state' and str(scene.get('asset','')).lower().endswith(tuple(IMAGE_EXT)) and not scene.get('graphic'):
            scene['spatial_motion']=True
        if i and (scene.get('spatial_motion') or scene.get('graphic') or scene.get('editorial') in ('chapter','statement','evidence')):
            prev=scenes[i-1]
            if prev.get('asset_role')=='broll' and str(prev.get('asset','')).lower().endswith(tuple(VIDEO_EXT)) and not prev.get('recorded_demo') and not prev.get('guided_replay'):
                scene['footage_bridge_seconds']=min(.85,scene['frames']/fps*.22)
        if i and scenes[i-1].get('spatial_motion') and (scene.get('graphic') or scene.get('editorial') in ('chapter','statement','evidence')):
            prev=scenes[i-1]
            scene['spatial_bridge']=prev['asset']
            scene['bridge_scene']={k:prev[k] for k in ('start','end','focus_point','hero_title','asset_name') if k in prev}
            scene['bridge_seconds']=min(1.05,scene['frames']/fps*.26)
        elif i and (scene.get('spatial_motion') or scene.get('graphic') or scene.get('editorial') in ('chapter','statement','evidence') or (scene.get('asset_role')=='broll' and str(scene.get('asset','')).lower().endswith(tuple(VIDEO_EXT)))):
            prev=scenes[i-1]
            if prev.get('graphic') or prev.get('editorial') in ('chapter','statement','evidence'):
                # Authored graphics/documents only. Never apply to recorded demos.
                if prev.get('asset') and not str(prev['asset']).lower().endswith(tuple(IMAGE_EXT)):continue
                scene['editorial_bridge_scene']={k:prev[k] for k in ('start','end','graphic','editorial','editorial_look','hero_title','text','chapter','asset_name','evidence_focus') if k in prev}
                if prev.get('asset'):scene['editorial_bridge_asset']=prev['asset']
                scene['editorial_bridge_seconds']=min(.90,scene['frames']/fps*.24)


def font(size: int, bold: bool = False):
    for candidate in ([r'C:\Windows\Fonts\arialbd.ttf', 'DejaVuSans-Bold.ttf'] if bold else [r'C:\Windows\Fonts\arial.ttf', 'DejaVuSans.ttf']):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def centered_text(draw: ImageDraw.ImageDraw, text: str, w: int, y: int, size: int, color: str, bold=True):
    """Fit long text and wrap without overflowing the safe frame."""
    f = font(size, bold)
    words = text.split()[:12]
    while words and draw.textlength(' '.join(words), font=f) > w * .84 and size > 15:
        size -= 2
        f = font(size, bold)
    draw.text((w // 2, y), ' '.join(words), font=f, fill=color, anchor='mm')


def artwork(scene: dict, preset: str, w: int, h: int, asset: Path | None, base: Path, overlay: Path) -> None:
    look = PRESETS[preset]
    bg = Image.new('RGB', (w, h), look['background'])
    if scene.get('editorial') in ('chapter','statement','evidence') and (scene['type']=='big_text' or (scene['type']=='document' and asset and asset.suffix in IMAGE_EXT)):
        if asset:
            with Image.open(asset) as original: bg=editorial.artwork(scene,w,h,ImageOps.exif_transpose(original).convert('RGB'),font)
        else: bg=editorial.artwork(scene,w,h,None,font)
    elif asset and asset.suffix in IMAGE_EXT:
        with Image.open(asset) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
            if scene['type']=='ui_demo' and scene.get('cinematic_finish') and w/h>=1.5:
                # Large intact product screenshot in a dedicated image zone; never crop the UI.
                # Scale both ways, including smaller native captures; Pillow contain does not enlarge on all versions.
                ix,iy,tw,th=walk.panel_geometry(w,h,image.width,image.height)
                tile=image.resize((tw,th),Image.Resampling.LANCZOS)
                # A muted radial field and split composition distinguish the hero from captions.
                draw=ImageDraw.Draw(bg);cx=int(w*.73);cy=int(h*.425)
                for i in range(14,0,-1):
                    rx=int(w*.30*i/14);ry=int(h*.43*i/14);shade=15+(14-i)//2
                    draw.ellipse((cx-rx,cy-ry,cx+rx,cy+ry),fill=(shade,shade+6,shade+3))
                draw.rounded_rectangle((ix-12,iy-12,ix+tile.width+12,iy+tile.height+12),radius=max(8,h//45),fill='#0b130f',outline='#30473b',width=max(2,h//400))
                bg.paste(tile,(ix,iy))
                draw=ImageDraw.Draw(bg);left=round(w*.055);label_w=round(w*.34)
                draw.text((left,round(h*.13)),f"{str(scene.get('brand','SKELLYMOTION')).upper()[:35]}  /  {scene.get('chapter',1):02d}",font=font(max(15,h//40),True),fill='#93ab98')
                draw.line((left,round(h*.18),left+round(label_w*.76),round(h*.18)),fill='#30473b',width=max(2,h//300))
                phrase=str(scene.get('hero_title') or scene.get('text') or 'Plugin walkthrough').upper()
                f,lines,fsize=editorial.fit_text(draw,phrase,font,min(h*.075,h*.37/4.8),label_w,4)
                for j,line in enumerate([] if scene.get('title_motion') else lines):draw.text((left,round(h*.28+j*fsize*1.14)),line,font=f,fill='#e7f0e7')
                draw.rectangle((left,round(h*.68),left+round(w*.047),round(h*.687)),fill=look['accent'])
                draw.text((left,round(h*.71)),'PLUGIN WALKTHROUGH',font=font(max(12,h//40),True),fill='#a0f58c')
            elif scene['type'] in ('ui_demo','document'):
                # Reserve distinct top and bottom regions for title/captions.
                if scene.get('guided_replay'):
                    ix,iy,tw,th=walk.panel_geometry(w,h,image.width,image.height)
                    bg.paste(image.resize((tw,th),Image.Resampling.LANCZOS),(ix,iy))
                else:
                    tile = ImageOps.contain(image, (round(w*.92), round(h*.60)))
                    bg.paste(tile, ((w-tile.width)//2, int(h*.46)-tile.height//2))
            else:
                focus=scene.get('features',{}).get('focus',[.5,.5])
                bg.paste(ImageOps.fit(image, (w,h),centering=tuple(focus)), (0,0))
    elif scene['type']=='diagram':
        draw=ImageDraw.Draw(bg)
        centered_text(draw,scene['text'],w,int(h*.12),max(20,h//16),look['accent'])
        centered_text(draw,'CONCEPTUAL SIGNAL FLOW',w,int(h*.24),max(12,h//35),'#acbcae')
        kind=scene['text'];fg=look['accent']; x0,x1=int(w*.14),int(w*.86); y0,y1=int(h*.31),int(h*.66)
        draw.rounded_rectangle((x0-8,y0-8,x1+8,y1+8),radius=max(5,h//50),fill='#18221d',outline='#3c5543',width=2)
        ax,ay=x0+int((x1-x0)*.08),y1-int((y1-y0)*.12);bx,by=x1-int((x1-x0)*.04),y0+int((y1-y0)*.12)
        for i in range(1,5):
            x=ax+(bx-ax)*i/5;y=ay+(by-ay)*i/5
            draw.line((x,by,x,ay),fill='#2c3c32',width=1);draw.line((ax,y,bx,y),fill='#2c3c32',width=1)
        draw.line((ax,by,ax,ay,bx,ay),fill='#6a8170',width=max(1,h//350))
        def xy(x,y):return (ax+x*(bx-ax),ay-y*(ay-by))
        if kind=='Compression':
            points=[xy(0,0),xy(.42,.42),xy(1,.65)];draw.line((xy(0,0),xy(1,1)),fill='#52685a',width=2)
            draw.line(points,fill=fg,width=max(3,h//120));draw.ellipse((points[1][0]-4,points[1][1]-4,points[1][0]+4,points[1][1]+4),fill=fg)
            label='Input level → output level · reduced slope above threshold'
        elif kind=='Equalization':
            points=[xy(i/100,.42+.35*math.exp(-((i/100-.53)/.14)**2)) for i in range(101)];draw.line((xy(0,.42),xy(1,.42)),fill='#52685a',width=2);draw.line(points,fill=fg,width=max(3,h//120));label='Frequency → relative gain · illustrative bell boost'
        elif kind=='Delay':
            for i in range(6):
                x=.08+i*.16;draw.line((xy(x,0),xy(x,.9*(.67**i))),fill=fg,width=max(3,h//85))
            label='Time → repeated signal · decaying feedback'
        elif kind=='Reverb':
            points=[xy(i/100,.92*math.exp(-4*i/100)) for i in range(101)];draw.line(points,fill=fg,width=max(3,h//120));label='Time → relative energy · illustrative decay tail'
        else:
            for rate,color in ((4,'#779486'),(6,fg)):
                draw.line([xy(i/100,.5+.28*math.sin(2*math.pi*rate*i/100)) for i in range(101)],fill=color,width=max(2,h//160))
            label='Time → waveform · illustrative frequency change'
        centered_text(draw,label,w,int(h*.715),max(11,min(h//34,w//33)),'#acbcae',False)
        draw.line((int(w*.18),int(h*.765),int(w*.82),int(h*.765)),fill='#49614b',width=max(2,h//150))
    elif scene['type']=='visualizer':
        draw=ImageDraw.Draw(bg)
        cx,cy=w//2,int(h*.46)
        for i in range(7,0,-1):
            r=int(min(w,h)*(.13+i*.038)); shade=16+i*3
            draw.ellipse((cx-r,cy-r,cx+r,cy+r),outline=(shade,shade+12,shade+5),width=max(1,h//400))
        draw.line((int(w*.08),cy,int(w*.92),cy),fill='#41634a',width=max(1,h//400))
        centered_text(draw,'SKELLYMOTION',w,int(h*.13),max(15,min(w//18,h//30)),'#a0f58c')
        centered_text(draw,'AUDIO REACTIVE',w,int(h*.19),max(10,min(w//30,h//42)),'#91a99b')
    elif not asset:
        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((round(w*.08), round(h*.14), round(w*.92), round(h*.80)), radius=max(8,h//30), outline='#34463d', width=max(1,h//400))
        if not (scene.get('title_motion') and scene['type'] in ('big_text','outro')): centered_text(draw, scene['text'], w, int(h*.46), max(24,h//13), '#f4f8f2')
        draw.rectangle((int(w*.43),int(h*.60),int(w*.57),int(h*.605)), fill=look['accent'])
    bg.save(base)
    layer = Image.new('RGBA',(w,h),(0,0,0,0)); d = ImageDraw.Draw(layer)
    if scene['type'] == 'ui_demo' and not (scene.get('cinematic_finish') and asset and asset.suffix in IMAGE_EXT and w/h>=1.5):
        d.rectangle((0,0,w,int(h*.13)), fill=(10,14,12,230))
        if not scene.get('title_motion'): centered_text(d, scene['text'].upper(), w, int(h*.068), max(18,h//20), look['accent'])
        if scene.get('recorded_demo'):
            d.text((int(w*.04),int(h*.16)),'ACTUAL SCREEN RECORDING',font=font(max(13,h//38),True),fill='#a0f58c')
    # Caption contrast remains predictable on arbitrary user footage.
    if scene['captions'] and scene.get('editorial') not in ('chapter','graphic'):
        for y in range(int(h*.75),h):
            alpha = round(175 * ((y-h*.75)/(h*.25)))
            d.line((0,y,w,y),fill=(0,0,0,alpha))
    if scene.get('editorial_footage_label'):
        label=str(scene['editorial_footage_label'])[:80];f=font(max(12,h//45),True);x,y=round(w*.04),round(h*.045);pad=max(5,h//100);tw=round(d.textlength(label,font=f));d.rounded_rectangle((x,y,x+tw+pad*2,y+round(h*.052)),radius=4,fill=(12,15,18,225));d.text((x+pad,y+round(h*.026)),label,font=f,fill='#e2e3df',anchor='lm')
    if scene.get("source"):
        # Always distinguish external photos from actual product screenshots.
        label = "AI-GENERATED ILLUSTRATION" if scene["source"].get("provider")=="Local AI" else "ILLUSTRATIVE · WIKIMEDIA COMMONS"
        f = font(max(12,h//44),True)
        x,y = int(w*.025),int(h*.025)
        padding = max(6,h//65)
        width = min(w-x,int(d.textlength(label,font=f))+2*padding)
        d.rounded_rectangle((x,y,x+width,y+int(h*.06)),radius=max(3,h//100),fill=(10,14,12,220))
        d.text((x+padding,y+int(h*.03)), label, font=f, fill="#e8f5e8",anchor="lm")
    layer.save(overlay)


def scene_key(scene: dict, asset: Path | None, settings: dict, size: tuple[int,int], preset: str) -> str:
    stamp = [asset.name,asset.stat().st_size,asset.stat().st_mtime_ns] if asset else None
    if scene.get('graphic') or scene.get('editorial') in ('chapter','statement','evidence'):settings={**settings,'editorial_motion_revision':editorial_motion.MOTION_REVISION}
    if scene.get('camera_path'):settings={**settings,'camera_path_revision':2}
    if scene.get('product_motion'):settings={**settings,'product_motion_revision':product_motion.REVISION}
    if scene.get('spatial_motion') or scene.get('spatial_bridge') or scene.get('editorial_bridge_scene') or scene.get('footage_bridge_seconds'):settings={**settings,'spatial_revision':spatial.REVISION}
    return hashlib.sha256(json.dumps([VERSION,scene,stamp,settings,size,preset],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def encoded_frames(path: Path) -> int:
    """Count generated H.264 packets with the bundled FFmpeg, without decoding.
    All Director outputs use one video access unit per muxed packet.
    """
    result=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-i',str(path),'-map','0:v:0','-an','-c:v','copy','-f','null','-','-progress','pipe:1','-nostats'],capture_output=True,text=True,timeout=90,**perf.windows_child_options(low_priority=True))
    values=re.findall(r'^frame=(\d+)\s*$',result.stdout or '',re.M)
    if result.returncode or not values:raise RuntimeError('Could not verify Director video frame count')
    return int(values[-1])


def render(plan: dict, audio: Path, assets_folder: Path, work: Path, output: Path, settings: dict,
           size: tuple[int,int], make_ass: Callable, encode: Callable, check_cancel: Callable,
           progress: Callable, music: Path | None = None) -> dict:
    """Render one scene at a time, cache validated complete clips, then mux audio.

    encode(args, duration, stage, base, span) integrates the app's cancellation
    and progress reporting. All inputs are server-generated paths.
    """
    w,h = size; fps=plan['fps']; duration=plan['duration']; cinematic=plan.get('cinematic_finish',False); audio_start=float(plan.get('audio_start',0)); work.mkdir(parents=True,exist_ok=True)
    if cinematic and plan.get('preset')=='doc':
        from studio_quality import repair_layout
        repair=repair_layout(plan,size,font,check_cancel)
        if repair['corrections'] or 'layout_repair' not in plan:plan['layout_repair']=repair
        configure_spatial(plan['scenes'],fps)
        if plan.get('sound_design') and music is None and not plan.get('silent'):
            plan.update(musical_edit.align_generated_cuts(plan))
        else:
            plan.pop('beat_locked_cuts',None);plan.pop('score_bpm',None)
    cache=work/'scenes'; cache.mkdir(exist_ok=True); made=reused=0; clips=[]; picture_review=None
    scratch=work/('job-'+uuid4().hex); scratch.mkdir()
    import shutil
    try:
        for index, scene in enumerate(plan['scenes']):
            check_cancel()
            asset=asset_path(assets_folder,scene.get('asset')) if scene.get('asset') else None
            if scene.get('asset') and asset is None:
                raise ValueError('An asset disappeared; refresh the scene plan')
            if scene['type']=='visualizer': scene['audio_stamp']=[audio.stat().st_size,audio.stat().st_mtime_ns,audio_start]
            before=asset_path(assets_folder,scene.get('before_asset')) if scene.get('before_asset') else None
            if scene.get('before_asset') and before is None: raise ValueError('A previous captured state disappeared')
            previous_stamp=[before.name,before.stat().st_size,before.stat().st_mtime_ns] if before else None
            if scene.get('guided_replay') and not scene.get('focus_point') and before and asset:
                with Image.open(before) as a, Image.open(asset) as b:scene['focus_point']=walk.state_focus(a,b)
            if scene.get('guided_replay') and not scene.get('focus_point'):
                scene['replay_fallback']='No localized control change found; static capture used';scene['guided_replay']=False
            bridge=asset_path(assets_folder,scene.get('spatial_bridge')) if scene.get('spatial_bridge') else None
            bridge_stamp=[bridge.name,bridge.stat().st_size,bridge.stat().st_mtime_ns] if bridge else None
            editorial_bridge=asset_path(assets_folder,scene.get('editorial_bridge_asset')) if scene.get('editorial_bridge_asset') else None
            if scene.get('editorial_bridge_asset') and editorial_bridge is None:raise ValueError('Previous editorial asset disappeared')
            editorial_stamp=[editorial_bridge.name,editorial_bridge.stat().st_size,editorial_bridge.stat().st_mtime_ns] if editorial_bridge else None
            from studio_media_layers import stamps
            layer_stamps=stamps(scene,assets_folder)
            key=scene_key(scene,asset,{**settings,**({'layer_stamps':layer_stamps} if layer_stamps else {}),'cinematic_finish':cinematic,'before_stamp':previous_stamp,'bridge_stamp':bridge_stamp,'editorial_stamp':editorial_stamp,**({'footage_stamp':clips[-1].name} if scene.get('footage_bridge_seconds') and clips else {})},size,plan['preset']); clip=cache/(key+'.mp4')
            seconds=scene['frames']/fps
            if walk.valid_scene_clip(clip,seconds,fps,probe_media) and (not cinematic or encoded_frames(clip)==scene['frames']):
                reused+=1
            else:
                base=scratch/'base.png'; overlay=scratch/'overlay.png'; ass=scratch/'captions.ass'
                artwork(scene,plan['preset'],w,h,asset,base,overlay)
                captions=[] if cinematic else scene['captions']; make_ass([{**row, 'y': 89} for row in captions] if scene['type']=='diagram' else captions,ass)
                cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-filter_complex_threads','1']
                live_diagram=scene['type']=='diagram' and scene['text'] in ({'Compression','Pitch processing','Note selection'} | EFFECT_VISUALS)
                replay_rate=None
                footage_previous=None
                if scene.get('footage_bridge_seconds') and clips:
                    # Exact final encoded frame from the preceding B-roll, with its
                    # own camera and provenance intact. Do not alter footage timing.
                    footage_previous=spatial.last_encoded_frame(clips[-1],plan['scenes'][index-1]['frames'],check_cancel)
                if scene.get('guided_replay') and asset and asset.suffix in IMAGE_EXT:
                    frames=scratch/'replay_frames';shutil.rmtree(frames,ignore_errors=True)
                    with Image.open(base) as backdrop:
                        replay_rate=walk.replay_frames(scene,before,asset,backdrop.convert('RGB'),frames,fps,check_cancel)
                    if not replay_rate: scene['replay_fallback']='No localized control change found; static capture used'
                if cinematic and scene.get('product_motion') and asset and asset.suffix in IMAGE_EXT:
                    frames=scratch/'product_frames';shutil.rmtree(frames,ignore_errors=True)
                    if scene.get('spatial_motion'):spatial.write_frames(scene,w,h,asset,frames,fps,font,check_cancel,editorial_bridge=editorial_bridge,footage_previous=footage_previous,assets_folder=assets_folder)
                    else:product_motion.write_frames(scene,w,h,asset,frames,fps,font,check_cancel)
                    cmd+=['-framerate',str(fps),'-i',str(frames/'%05d.jpg')];vf='setsar=1'
                elif cinematic and (scene.get('graphic') or scene.get('editorial') in ('chapter','statement','evidence')):
                    frames=scratch/'editorial_frames';shutil.rmtree(frames,ignore_errors=True)
                    editorial_motion.write_frames(scene,w,h,asset,frames,fps,font,check_cancel,bridge=bridge,editorial_bridge=editorial_bridge,footage_previous=footage_previous,assets_folder=assets_folder)
                    cmd+=['-framerate',str(fps),'-i',str(frames/'%05d.jpg')]
                    vf='setsar=1'
                elif replay_rate:
                    cmd+=['-framerate',str(replay_rate),'-i',str(frames/'%05d.jpg')]
                    vf=f'fps={fps},tpad=stop_mode=clone:stop_duration=0.2,setsar=1'
                elif live_diagram:
                    frames=scratch/'live_frames'
                    shutil.rmtree(frames,ignore_errors=True)
                    source_fps=live.write_frames(scene['text'],seconds,frames,fps,check_cancel,retune_ms=scene.get('retune_demo_ms',70.),compressor=scene.get('compressor_demo'))
                    cmd+=['-framerate',str(source_fps),'-i',str(frames/'%05d.jpg')]
                    vf=f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x101615,tpad=stop_mode=clone:stop_duration=0.2,setsar=1'
                elif scene['type']=='visualizer':
                    cmd+=['-ss',f'{audio_start+scene["start"]:.6f}','-t',f'{seconds:.6f}','-i',str(audio)]
                    wave_h=max(2,int(h*.35)//2*2);wave_w=max(2,int(w*.84)//2*2)
                    vf=f"[0:a]aformat=channel_layouts=mono,showwaves=s={wave_w}x{wave_h}:mode=cline:colors=0x94f58c:rate={fps}:scale=sqrt:draw=full,format=rgba,colorkey=0x000000:0.02:0.04[wave];[2:v][wave]overlay=x=(W-w)/2:y={int(h*.46)-wave_h//2}:shortest=1,fps={fps},tpad=stop_mode=clone:stop_duration=0.2,setsar=1"
                elif asset and asset.suffix in VIDEO_EXT:
                    if scene.get('recorded_demo') or plan['preset']=='doc':
                        cmd+=['-ss',str(scene.get('asset_start',0)),'-i',str(asset)]
                    else:
                        cmd+=['-stream_loop','-1','-ss',str(scene.get('asset_start',0)),'-i',str(asset)]
                    if scene['type']=='ui_demo':
                        vf=f"fps={fps},scale={int(w*.92)//2*2}:{int(h*.65)//2*2}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:{int(h*.46)}-ih/2:color=0x101216,setsar=1"
                        if scene.get('recorded_demo'): vf+=f',trim=duration={scene["recorded_seconds"]:.6f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={seconds:.6f}'
                    else:
                        focus=scene.get('features',{}).get('focus',[.5,.5]);fx,fy=(max(0.,min(1.,float(v))) for v in focus)
                        vf=f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-ow)*{fx}:(ih-oh)*{fy},setsar=1'
                        if plan['preset']=='doc':
                            if scene.get('editorial_seconds'):vf+=f',trim=duration={scene["editorial_seconds"]:.6f},setpts=PTS-STARTPTS'
                            vf+=f',tpad=stop_mode=clone:stop_duration={seconds:.6f}'
                        if cinematic and scene.get('camera_path')=='present':
                            iw=round(w*.89/2)*2;ih=round(h*.82/2)*2
                            vf+=f',scale={iw}:{ih}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x101612'
                            vf+=','+camera.camera_filter(w,h,scene['frames'],fps,'push',(.5,.5))
                        elif cinematic and scene.get('camera_path') in ('push','pull','detail'):
                            vf+=','+camera.camera_filter(w,h,scene['frames'],fps,scene['camera_path'],focus)
                        if scene.get('variation') in ('reverse','mirror_reverse'):
                            vf+=f',trim=end_frame={scene["frames"]},reverse,setpts=PTS-STARTPTS'
                else:
                    cmd+=['-loop','1','-framerate',str(fps),'-i',str(base)]
                    # Smooth bounded camera motion derived from the reference
                    # engine's push/pull camera; UI shots remain uncropped.
                    if scene['camera'] in ('push','pull'):
                        n=max(1,scene['frames']-1);u=f'(on/{n})';expr=f'0.10*{u}*{u}*(3-2*{u})'
                        z='1+'+expr if scene['camera']=='push' else '1.10-'+expr
                        vf=f"scale={w*2}:{h*2},zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps},setsar=1"
                    else: vf='setsar=1'
                variation=scene.get('variation')
                if variation in ('mirror','mirror_reverse'): vf+=',hflip'
                if variation=='grade': vf+=',eq=contrast=1.06:saturation=1.10'
                if variation=='vignette': vf+=',vignette=PI/6'
                cmd+=['-loop','1','-framerate',str(fps),'-i',str(overlay)]
                if scene['type']=='visualizer': cmd+=['-loop','1','-framerate',str(fps),'-i',str(base)]
                # Relative ASS filename avoids Windows drive/path escaping issues.
                # The server runs the scene subprocess in scratch.
                graph=(vf if scene['type']=='visualizer' else '[0:v]'+vf)+'[base];[base][1:v]overlay=0:0,format=yuv420p'
                if scene['type']=='diagram' and not live_diagram:
                    graph+='[diagram];'
                    dot=scratch/'dot.png'; ball=Image.new('RGBA',(max(8,h//24),max(8,h//24)),(0,0,0,0));ImageDraw.Draw(ball).ellipse((1,1,ball.width-2,ball.height-2),fill='#94f58c');ball.save(dot)
                    cmd+=['-loop','1','-framerate',str(fps),'-i',str(dot)]
                    graph+=f"[diagram][2:v]overlay=x='{w*.18}+{w*.64}*min(1,t/{max(.1,seconds)} )-overlay_w/2':y='{h*.765}-overlay_h/2',format=yuv420p"
                if scene.get('transition')=='dip':
                    graph+=f',fade=t=in:st=0:d={min(.16,seconds*.2):.4f}'
                if scene.get('dip_out'):
                    d=min(.16,seconds*.2); graph+=f',fade=t=out:st={seconds-d:.4f}:d={d:.4f}'
                if captions: graph+=',ass=captions.ass'
                if cinematic: graph+=f',scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,settb=1/{fps},setpts=N'
                # Authored editorial composition exits over actual moving B-roll.
                # Explicit B-roll role only; a recorded plugin demo never receives this overlay.
                if cinematic and editorial_bridge is not None and not scene.get('editorial_bridge_scene'):
                    raise ValueError('Invalid editorial bridge metadata')
                if (cinematic and scene.get('editorial_bridge_scene') and scene.get('asset_role')=='broll' and asset and asset.suffix in VIDEO_EXT and not scene.get('recorded_demo')):
                    previous=spatial.editorial_previous(scene,w,h,font,editorial_bridge,assets_folder=assets_folder)
                    overlay_frames=scratch/'handoff_frames';shutil.rmtree(overlay_frames,ignore_errors=True)
                    spatial.write_handoff_overlay(previous,overlay_frames,scene['editorial_bridge_seconds'],fps,check_cancel)
                    cmd+=['-framerate',str(fps),'-i',str(overlay_frames/'%05d.png')]
                    graph+='[ready];[ready][2:v]overlay=0:0:eof_action=pass:repeatlast=0,format=yuv420p'
                graph+='[out]'
                tmp=scratch/'clip.mp4'
                cmd+=['-filter_complex',graph,'-map','[out]','-frames:v',str(scene['frames']),'-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','20','-pix_fmt','yuv420p']+(['-bf','0','-r',str(fps),'-fps_mode','cfr','-enc_time_base:v',f'1:{fps}','-video_track_timescale','60000','-use_editlist','0','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-chroma_sample_location','left'] if cinematic else [])+[str(tmp)]
                encode(cmd,scratch,seconds,f'director_scene_{index+1}',int(5+80*index/len(plan['scenes'])),max(1,int(80/len(plan['scenes']))))
                check_cancel()
                if not walk.valid_scene_clip(tmp,seconds,fps,probe_media) or (cinematic and encoded_frames(tmp)!=scene['frames']): raise RuntimeError('Scene encoder produced invalid or mistimed video')
                perf.publish_staged_file(tmp,clip); made+=1
            clips.append(clip)
            progress(index+1,len(plan['scenes']),made,reused)
        check_cancel()
        # Generated relative cache names avoid concat demuxer quoting and path injection.
        count=0
        if cinematic and plan.get('crossfades'):
            clips,count=cinema.crossfade_clips(clips,plan['scenes'],fps,scratch,encode,check_cancel,duration,style=plan.get('transition_style','dissolve'),seconds=plan.get('transition_seconds',.32))
        # Both cache and scratch paths are generated under work.
        listing=work/('concat-'+uuid4().hex+'.txt'); listing.write_text(''.join(f"file '{p.relative_to(work).as_posix()}'\n"+(f"duration {scene['frames']/fps:.9f}\n" if cinematic else '') for p,scene in zip(clips,plan['scenes'])),encoding='utf-8')
        temporary=scratch/'final.mp4'
        try:
            cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-f','concat','-safe','1','-i',str(listing),'-ss',f'{audio_start:.6f}','-i',str(audio)]
            if cinematic:
                cinema.write_kinetic_ass(plan,w,h,scratch/'cinematic_captions.ass')
            cues=None
            if cinematic and plan.get('sound_design') and not plan.get('silent'):
                bed=scratch/'original_bed.wav';cinema.original_bed(plan,bed,include_music=music is None,check_cancel=check_cancel,music_gain=plan.get('music_gain',1.),cue_gain=plan.get('cue_gain',0. if plan['preset']=='doc' else 1.))
                if music is None: music=bed
                else: cues=bed
            if plan.get('silent'):
                cmd+=['-map','0:v','-an']
            elif cinematic and plan['preset']!='music':
                check_cancel()
                voice=cinema.voice_chain(plan.get('voice_style','natural'),silent=cinema.silent_voice(audio,audio_start,duration))
                check_cancel()
                if music:
                    level='1.0' if music==scratch/'original_bed.wav' else str(.20*plan.get('music_gain',1.))
                    cmd+=['-stream_loop','-1','-i',str(music)]
                    if cues: cmd+=['-i',str(cues)]
                    graph=voice+',asplit=2[vo][key];[2:a]aresample=48000,aformat=channel_layouts=stereo,volume='+level+'[bed];[bed][key]sidechaincompress=threshold=0.12:ratio=2.2:attack=50:release=650[duck];'
                    if cues:
                        graph+='[3:a]aresample=48000,aformat=channel_layouts=stereo[cue];[vo][duck][cue]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.75:level=0:latency=1[a]'
                    else:
                        graph+='[vo][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.75:level=0:latency=1[a]'
                    cmd+=['-filter_complex',graph,'-map','0:v','-map','[a]']
                else:cmd+=['-filter_complex',voice+'[a]','-map','0:v','-map','[a]']
            elif music:
                cmd+=['-stream_loop','-1','-i',str(music),'-filter_complex','[1:a]aresample=48000,asplit=2[voice][key];[2:a]aresample=48000,volume=0.1[bed];[bed][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=450[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]','-map','0:v','-map','[a]']
            else: cmd+=['-map','0:v','-map','1:a:0']
            if cinematic:
                # Concat container durations are rounded independently; rebuild
                # the exact presentation clock from the ordered decoded frames.
                vf=f'settb=1/{fps},setpts=N'
                if plan.get('caption_style','karaoke')!='off' or plan.get('title_motion'):vf+=f',ass={scratch.name}/cinematic_captions.ass'
                cmd+=['-vf',vf,'-r',str(fps),'-fps_mode','cfr','-enc_time_base:v',f'1:{fps}','-bf','0','-video_track_timescale','60000','-movie_timescale','240000','-use_editlist','1']
            cmd+=(['-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p'] if cinematic else ['-c:v','copy'])+([] if plan.get('silent') else ['-c:a','aac','-b:a','192k'])+['-t',f'{max(duration,plan["frames"]/fps) if cinematic else duration:.6f}','-movflags','+faststart',str(temporary)]
            encode(cmd,work,duration,'director_mux',85,14)
            check_cancel()
            if not temporary.is_file() or temporary.stat().st_size<1024: raise RuntimeError('Director output missing')
            info=probe_media(temporary)
            if not info['has_video'] or bool(info['has_audio'])==bool(plan.get('silent')) or abs(info['duration']-duration)>max(.13,2/fps): raise RuntimeError('Director output failed stream/timing validation')
            if cinematic and encoded_frames(temporary)!=plan['frames']:raise RuntimeError('Director output frame count does not match plan')
            if cinematic and any((s.get('graphic') or {}).get('kind')=='composition' for s in plan['scenes']):
                from studio_quality import review_video,review_layout
                picture_review=review_video(temporary,duration,check_cancel)
                picture_review["layout"]=review_layout(plan,size,font)
                picture_review["repair"]=plan.get("layout_repair",{})
            perf.publish_staged_file(temporary,output)
        finally: listing.unlink(missing_ok=True)
        return {**({'picture_review':picture_review} if picture_review is not None else {}),'scenes':len(clips),'rendered':made,'cached':reused,'duration':duration,'crossfades':count,'guided_replays':sum(bool(s.get('guided_replay')) and not s.get('replay_fallback') for s in plan['scenes']),'recorded_scenes':sum(bool(s.get('recorded_demo')) for s in plan['scenes']),'beat_locked_cuts':plan.get('beat_locked_cuts',[]),'score_bpm':plan.get('score_bpm'), 'spatial_shots':sum(bool(s.get('spatial_motion')) for s in plan['scenes'])}
    finally:
        shutil.rmtree(scratch,ignore_errors=True)
