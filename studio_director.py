"""Local-first scene director adapted from the supplied autoedit.py/director prompt.

No network, external AI, generated claims, inline SVG execution or arbitrary paths.
Plan at transcript boundaries, select supplied media, render and cache individual scenes.
"""
from __future__ import annotations

import hashlib
from collections import Counter
import json
import math
import re
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont, ImageOps

import studio_performance as perf
import studio_theme as theme
import studio_shot_motion as shot_motion
import studio_director_intelligence as intel
import studio_live_diagrams as live
from studio_effect_visuals import KINDS as EFFECT_VISUALS
import studio_cinematic as cinema
import studio_walkthrough as walk
from studio_clips import probe_media

VERSION = 19
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
              brand: str = 'SKELLYMOTION', *, fps: int = 30, preview: bool = False, analysis: dict | None = None, intensity: str = "medium", diagrams: bool = False, motion: str = "dynamic", transitions: bool = False, audio_start: float = 0., silent: bool = False, cinematic: bool = False, guided_replay: bool = False, title_motion: bool = False, editorial_style: str = 'standard', visual_theme: str = 'legacy', skell_terminology: bool = False) -> dict:
    """Deterministic shot selection from real transcript and asset descriptions.

    Timing is represented in frames to avoid gaps/drift. No invented facts,
    quotations, coordinates, or filenames; cards use only transcript text.
    """
    if preset not in PRESETS or fps not in (24, 30) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid director timing or style')
    duration = min(duration, 15.0) if preview else duration
    if duration > 1800:
        raise ValueError('Director currently supports up to 30 minutes of audio')
    total = max(1, round(duration * fps))
    if editorial_style not in ('standard','reference'):raise ValueError('Unknown editorial style')
    theme.validate(visual_theme)
    look = dict(PRESETS[preset])
    reference=editorial_style=='reference'
    if reference and preset=='doc':look.update(pace=4.,maximum=8.)
    if reference and preset=='plugin':look.update(pace=11.,maximum=18.)
    lines = [line for line in lines if float(line['start']) < duration and float(line['end']) > 0]
    # The reference director cuts near sentence boundaries. Confirmed lyric
    # clip boundaries are the local equivalent, including pauses in speech.
    boundaries = sorted({round(float(line['end']) * fps) for line in lines if 0 < float(line['end']) < duration})
    # Split plugin diagrams at changes in technical topic (including retune mode).
    topic_cuts = []
    if (preset == 'plugin' and (diagrams or cinematic)) or (reference and preset=='doc'):
        for a,b in zip(lines,lines[1:]):
            explicit_chapters=bool(a.get('chapter_title') and b.get('chapter_title'))
            chapter_change=explicit_chapters and a['chapter_title']!=b['chapter_title']
            if chapter_change or (preset=='plugin' and not explicit_chapters and ((cinematic and float(a['end'])-float(a['start'])>=2) or intel.technical_topic(a['text']) != intel.technical_topic(b['text']))):
                point = round(float(b['start'])*fps)
                if 0 < point < total: topic_cuts.append(point)
    # Web photos must not masquerade as a plugin UI or a source document.
    assets = [a for a in assets if not a.get("source") and not a.get("disabled")]
    if preset == "plugin": assets = [a for a in assets if walk.is_plugin_asset(a)]
    rhythm = intel.cut_boundaries(analysis or {}, duration, fps, lines, intensity) if preset == "music" else []
    scenes, cursor, used, repairs = [], 0, [], 0
    asset_terms={a['id']:terms(a['name']+' '+a.get('description','')) for a in assets}
    asset_features={a['id']:a.get('features') or {} for a in assets}
    usage=Counter()
    proof_intervals=[(max(0,round(row['start']*fps)),min(total,round(row['end']*fps)),row['proof_label']) for row in lines if row.get('proof_label')]
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
        current_proof=next((p for p in proof_intervals if p[0]<=cursor<p[1]),None)
        if current_proof:end=current_proof[1]
        else:
            upcoming=[p[0] for p in proof_intervals if cursor<p[0]<end]
            if upcoming:end=min(upcoming)
        end = max(cursor + 1, min(end, total))
        if current_proof:
            scenes.append({'start':cursor/fps,'end':end/fps,'frames':end-cursor,'type':'proof','text':current_proof[2],'proof_label':current_proof[2],'captions':[],'camera':'still'})
            cursor=end
            continue
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
        source_links=list(dict.fromkeys(str(row['source_url']) for row in meaningful if row.get('source_url')))
        if preset=='doc' and source_links:
            scene['claim_sources']=source_links
        if cinematic:
            scene.update(cinematic_finish=True,chapter=len(scenes)+1,brand=brand)
            if chapter_title:scene['hero_title']=chapter_title
            if title_motion:scene['title_motion']=True
            if not chapter_title and re.search(r'\bretune speed knob\b',text.lower()):
                scene['hero_title']='100 ms / Slow response' if re.search(r'\b(?:100|one hundred)\b',text.lower()) else '0 ms / Hard response' if re.search(r'\b(?:zero|0)\b',text.lower()) else 'Retune speed'
        # Asset matching prefers a semantic filename/description and diversity.
        if assets:
            spoken_terms, hint_terms=terms(text),terms(hint)
            previous=asset_features.get(used[-1],{}) if used else {}
            def score(a):
                key=a['id']; features=asset_features[key]; tags=asset_terms[key]
                overlap=len(spoken_terms & tags)+2*len(hint_terms & tags)
                distance=intel.diversity(features,previous)
                visual=float(features.get('quality',.5))+.4*distance
                if preset=='music': visual+=float(features.get('motion',0))
                # Keep factual/technical relevance first. Among equally relevant
                # visuals, avoid repeating identical shots or perceptual duplicates.
                recent=used[-3:]
                penalty=.22*usage[key]+.45*int(key in recent)
                if previous.get('hash') and features.get('hash') and distance<.08:penalty+=.7
                return (overlap,visual-penalty,int(preset=='plugin' and a['kind']=='image'))
            pool=assets
            chosen=max(pool,key=score)
            if preset=="plugin":
                recording=walk.choose_recording(assets,text+' '+hint,terms,used)
                if recording is not None: chosen=recording
            # Documentary footage needs an actual metadata match. Otherwise use a card.
            if score(chosen)[0] == 0 and (preset == "doc" or (preset == "plugin" and diagrams and intel.diagram_kind(text))):
                pool = []
            if cinematic and preset=='plugin' and diagrams and re.search(r'\b(?:conceptually|illustration|conceptual|simulation)\b',(text+' '+hint).lower()) and intel.diagram_kind(text+' '+hint): pool=[]
            if reference and preset=='plugin' and diagrams and chosen.get('role')!='plugin_recording' and shot_motion.prefer_diagram(text,hint,intel.diagram_kind(text+' '+hint)):
                pool=[]
            if pool:
                kind = 'ui_demo' if preset == 'plugin' else 'document' if chosen['kind'] == 'image' and terms(chosen['name']+' '+chosen.get('description','')) & {'article','document','source','comment','forum'} else 'broll'
                scene.update(type=kind, asset=chosen['id'], asset_name=chosen['name'],
                             camera='still' if kind in ('ui_demo','document') else ('push' if len(scenes) % 2 == 0 else 'pull'),
                             text=title if preset == 'plugin' else '')
                scene['features']=chosen.get('features',{})
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
                if preset=='music':
                    variant = ('clean' if motion=='clean' else ('clean','reverse')[len(scenes)%2] if motion=='pingpong' else intel.VARIATIONS[len(scenes)%len(intel.VARIATIONS)])
                    if variant in ('reverse','mirror_reverse') and (end-cursor)/fps>3.: variant='mirror'
                    scene['variation']=variant
                    clip_duration=float(scene['features'].get('duration',0) or 0)
                    if clip_duration>0: scene['asset_start']=round((used.count(chosen['id'])*((end-cursor)/fps))%clip_duration,3)
                used.append(chosen['id']);usage[chosen['id']]+=1
        if not scene.get('asset') and diagrams and preset=='plugin' and intel.diagram_kind(text+' '+hint):
            scene.update(type='diagram',text=intel.diagram_kind(text+' '+hint),camera='still')
            if scene['text']=='Pitch processing':
                scene['retune_demo_ms']=0. if re.search(r'\b(?:zero|fast|hard)\b', text.lower()) else 100. if re.search(r'\b(?:100|one hundred)\s*(?:ms|milliseconds)\b',(text+' '+hint).lower()) else 70.
        if reference and preset=='plugin' and scene['type']=='ui_demo' and not scene.get('guided_replay'):
            scene['layout']='full_ui'
        if reference and preset=='doc' and scene.get('claim_sources') and not scene.get('asset'):
            # Author-supplied claim, not an invented quotation or source screenshot.
            scene.update(type='evidence',layout='paper',evidence_text=text[:420],camera='still')
        if not scene.get('asset') and preset=='music':
            scene.update(type='visualizer',text='',camera='still')
        if transitions and not cinematic and preset=='music' and len(scenes) and not (scene['type']=='visualizer' and scenes[-1]['type']=='visualizer'):
            scene['transition']='dip';scenes[-1]['dip_out']=True
        # Keep speech as the primary reference; no extra branded tail is added.
        # When the last short region is silent, use it as a natural outro.
        if end == total and not active and preset != "music":
            scene.update(type='outro', text=brand, camera='still')
            scene.pop('asset', None); scene.pop('asset_name', None); scene.pop('before_asset',None); scene.pop('guided_replay',None)
        scenes.append(scene)
        cursor = end
    for scene in scenes:
        scene.update(visual_theme=visual_theme,skell_terminology=bool(skell_terminology))
        if reference and scene.get('camera') in ('push','pull') and scene['type']=='broll':
            scene['motion_curve']='eased'
    plan={'version': VERSION, 'preset': preset, 'visual_theme':visual_theme,'skell_terminology':bool(skell_terminology),'fps': fps, 'duration': duration, 'frames': total,
            'scenes': scenes, 'director': 'local', 'editorial_style':editorial_style, 'audio_start':audio_start, 'silent':silent,
            'cinematic_finish':cinematic,'title_motion':bool(cinematic and title_motion),'crossfades':bool(cinematic and transitions),'caption_repairs':repairs, 'warnings': ([] if assets or preset=='music' else ['No visual assets supplied: transcript-based text cards will be used.'])}
    if preset=='music':
        plan.update(beat_confidence=(analysis or {}).get('confidence',0), bpm=(analysis or {}).get('bpm',0), beat_aligned=bool(rhythm))
    plan['review']=intel.review(plan)
    return plan


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
    look = dict(PRESETS[preset])
    colors=theme.palette(scene.get('visual_theme','legacy'))
    if colors:look.update(background=colors['background'],accent=colors['accent'])
    bg = Image.new('RGB', (w, h), look['background'])
    if asset and asset.suffix in IMAGE_EXT:
        with Image.open(asset) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
            if scene.get('layout')=='full_ui':
                tile=image.copy();tile.thumbnail((round(w*.96),round(h*.76)),Image.Resampling.LANCZOS)
                # Upscale only if needed to fill the allocated safe region.
                factor=min(w*.96/image.width,h*.76/image.height)
                if factor>1:tile=image.resize((round(image.width*factor),round(image.height*factor)),Image.Resampling.LANCZOS)
                bg.paste(tile,((w-tile.width)//2,round(h*.49)-tile.height//2))
            elif scene['type']=='ui_demo' and scene.get('cinematic_finish') and w/h>=1.5:
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
                fsize=round(h*.075);f=font(fsize,True)
                while any(draw.textlength(word,font=f)>label_w for word in phrase.split()) and fsize>18:
                    fsize-=2;f=font(fsize,True)
                lines=[];line=''
                for word in phrase.split():
                    candidate=(line+' '+word).strip()
                    if line and draw.textlength(candidate,font=f)>label_w:lines.append(line);line=word
                    else:line=candidate
                if line:lines.append(line)
                for j,line in enumerate([] if scene.get('title_motion') else lines[:4]):draw.text((left,round(h*.28+j*fsize*1.14)),line,font=f,fill='#e7f0e7')
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
    elif scene['type']=='evidence':
        from studio_editorial import evidence_card
        bg=evidence_card(scene,w,h,font)
    elif scene['type']=='proof':
        draw=ImageDraw.Draw(bg)
        centered_text(draw,theme.label(scene,'LISTEN TO THE ACTUAL AUDIO'),w,int(h*.22),max(16,min(h//36,w//27)),look['accent'])
        centered_text(draw,scene['proof_label'],w,int(h*.46),max(24,h//11),'#f4f8f2')
        centered_text(draw,'SAME TIMESTAMPS · UNCHANGED PLAYBACK GAIN',w,int(h*.65),max(14,h//42),'#a8b9ad')
        draw.rectangle((int(w*.13),int(h*.79),int(w*.87),int(h*.797)),fill=look['accent'])
    elif not asset:
        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((round(w*.08), round(h*.14), round(w*.92), round(h*.80)), radius=max(8,h//30), outline='#34463d', width=max(1,h//400))
        if not (scene.get('title_motion') and scene['type'] in ('big_text','outro')): centered_text(draw, scene['text'], w, int(h*.46), max(24,h//13), '#f4f8f2')
        draw.rectangle((int(w*.43),int(h*.60),int(w*.57),int(h*.605)), fill=look['accent'])
    bg.save(base)
    layer = Image.new('RGBA',(w,h),(0,0,0,0)); d = ImageDraw.Draw(layer)
    if scene['type'] == 'ui_demo' and (scene.get('layout')=='full_ui' or not (scene.get('cinematic_finish') and asset and asset.suffix in IMAGE_EXT and w/h>=1.5)):
        d.rectangle((0,0,w,int(h*.13)), fill=(10,14,12,230))
        if not scene.get('title_motion'): centered_text(d, scene['text'].upper(), w, int(h*.068), max(18,h//20), look['accent'])
        if scene.get('recorded_demo'):
            d.text((int(w*.04),int(h*.105)) if scene.get('layout')=='full_ui' else (int(w*.04),int(h*.16)),'ACTUAL SCREEN RECORDING',font=font(max(12,h//50),True),fill='#a0f58c')
    # Caption contrast remains predictable on arbitrary user footage.
    if scene['captions']:
        for y in range(int(h*.75),h):
            alpha = round(175 * ((y-h*.75)/(h*.25)))
            d.line((0,y,w,y),fill=(0,0,0,alpha))
    if scene.get("source"):
        # Always distinguish external photos from actual product screenshots.
        label = "AI-GENERATED ILLUSTRATION" if scene["source"].get("provider")=="Local AI" else "ILLUSTRATIVE · WIKIMEDIA COMMONS"
        f = font(max(12,h//44),True)
        x,y = int(w*.025),int(h*.025)
        padding = max(6,h//65)
        width = min(w-x,int(d.textlength(label,font=f))+2*padding)
        d.rounded_rectangle((x,y,x+width,y+int(h*.06)),radius=max(3,h//100),fill=(10,14,12,220))
        d.text((x+padding,y+int(h*.03)), label, font=f, fill="#e8f5e8",anchor="lm")
    if scene.get('claim_sources') and scene['type']!='evidence':
        from urllib.parse import urlsplit
        hosts=list(dict.fromkeys(urlsplit(url).hostname or '' for url in scene['claim_sources']))
        label='SOURCE PROVIDED: '+', '.join(hosts)
        label=label[:110]
        f=font(max(12,h//45),True)
        x,y=int(w*.035),int(h*.68)
        # Distinct source strip, clear of title and karaoke caption bands.
        while len(label)>16 and d.textlength(label,font=f)>w*.9:label=label[:-5]+'…'
        d.rounded_rectangle((x,y,x+int(d.textlength(label,font=f))+20,y+int(h*.05)),radius=5,fill=(10,14,12,225))
        d.text((x+10,y+int(h*.025)),label,font=f,fill='#d6e2dc',anchor='lm')
    # Small, bounded editorial label in the title safe region; never paint
    # over source pixels or the actual plugin control area.
    if scene.get('skell_terminology') and scene['type'] in ('ui_demo','diagram','big_text','outro'):
        label=theme.label(scene,'')
        f=font(max(11,min(h//50,w//36)),True)
        x,y=round(w*.035),round(h*.022)
        if scene['type']=='ui_demo':y=round(h*.014)
        d.text((x,y),label,font=f,fill=look['accent'])
    layer.save(overlay)


def scene_key(scene: dict, asset: Path | None, settings: dict, size: tuple[int,int], preset: str) -> str:
    stamp = [asset.name,asset.stat().st_size,asset.stat().st_mtime_ns] if asset else None
    return hashlib.sha256(json.dumps([VERSION,scene,stamp,settings,size,preset],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def render(plan: dict, audio: Path, assets_folder: Path, work: Path, output: Path, settings: dict,
           size: tuple[int,int], make_ass: Callable, encode: Callable, check_cancel: Callable,
           progress: Callable, music: Path | None = None) -> dict:
    """Render one scene at a time, cache validated complete clips, then mux audio.

    encode(args, duration, stage, base, span) integrates the app's cancellation
    and progress reporting. All inputs are server-generated paths.
    """
    started=time.monotonic();w,h = size; fps=plan['fps']; duration=plan['duration']; cinematic=plan.get('cinematic_finish',False); audio_start=float(plan.get('audio_start',0)); work.mkdir(parents=True,exist_ok=True)
    cache=work/'scenes'; cache.mkdir(exist_ok=True); made=reused=0; clips=[]
    mode=settings.get('performanceMode','balanced')
    # All Director encode phases share the selected memory policy.
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
            key=scene_key(scene,asset,{**settings,'cinematic_finish':cinematic,'before_stamp':previous_stamp},size,plan['preset']); clip=cache/(key+'.mp4')
            seconds=scene['frames']/fps
            if walk.valid_scene_clip(clip,seconds,fps,probe_media):
                reused+=1
            else:
                base=scratch/'base.png'; overlay=scratch/'overlay.png'; ass=scratch/'captions.ass'
                artwork(scene,plan['preset'],w,h,asset,base,overlay)
                captions=[] if cinematic else scene['captions']; make_ass([{**row, 'y': 89} for row in captions] if scene['type']=='diagram' else captions,ass)
                cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-filter_complex_threads','1']
                live_diagram=scene['type']=='diagram' and scene['text'] in ({'Compression','Pitch processing','Note selection'} | EFFECT_VISUALS)
                replay_rate=None
                static_still=False
                if scene.get('guided_replay') and asset and asset.suffix in IMAGE_EXT:
                    frames=scratch/'replay_frames';shutil.rmtree(frames,ignore_errors=True)
                    with Image.open(base) as backdrop:
                        replay_rate=walk.replay_frames(scene,before,asset,backdrop.convert('RGB'),frames,fps,check_cancel)
                    if not replay_rate: scene['replay_fallback']='No localized control change found; static capture used'
                if replay_rate:
                    cmd+=['-threads','1','-framerate',str(replay_rate),'-i',str(frames/'%05d.jpg')]
                    vf=f'fps={fps},tpad=stop_mode=clone:stop_duration=0.2,setsar=1'
                elif live_diagram:
                    frames=scratch/'live_frames'
                    shutil.rmtree(frames,ignore_errors=True)
                    source_fps=live.write_frames(scene['text'],seconds,frames,fps,check_cancel,retune_ms=scene.get('retune_demo_ms',70.),compressor=scene.get('compressor_demo'),theme=scene.get('visual_theme','legacy'))
                    cmd+=['-threads','1','-framerate',str(source_fps),'-i',str(frames/'%05d.jpg')]
                    vf=f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x101615,tpad=stop_mode=clone:stop_duration=0.2,setsar=1'
                elif scene['type']=='visualizer':
                    cmd+=['-ss',f'{audio_start+scene["start"]:.6f}','-t',f'{seconds:.6f}','-i',str(audio)]
                    wave_h=max(2,int(h*.35)//2*2);wave_w=max(2,int(w*.84)//2*2)
                    vf=f"[0:a]aformat=channel_layouts=mono,showwaves=s={wave_w}x{wave_h}:mode=cline:colors=0x94f58c:rate={fps}:scale=sqrt:draw=full,format=rgba,colorkey=0x000000:0.02:0.04[wave];[2:v][wave]overlay=x=(W-w)/2:y={int(h*.46)-wave_h//2}:shortest=1,fps={fps},tpad=stop_mode=clone:stop_duration=0.2,setsar=1"
                elif asset and asset.suffix in VIDEO_EXT:
                    if scene.get('recorded_demo'):
                        cmd+=['-threads','2','-ss',str(scene.get('asset_start',0)),'-i',str(asset)]
                    else:
                        cmd+=['-threads','2','-stream_loop','-1','-ss',str(scene.get('asset_start',0)),'-i',str(asset)]
                    if scene['type']=='ui_demo':
                        bg_color=(theme.palette(scene.get('visual_theme','legacy')) or {'background':'#101216'})['background'].replace('#','0x')
                        ratio_w,ratio_h,center=(.96,.76,.49) if scene.get('layout')=='full_ui' else (.92,.65,.46)
                        vf=f"fps={fps},scale={int(w*ratio_w)//2*2}:{int(h*ratio_h)//2*2}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:{int(h*center)}-ih/2:color={bg_color},setsar=1"
                        if scene.get('recorded_demo'): vf+=f',trim=duration={scene["recorded_seconds"]:.6f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={seconds:.6f}'
                    else:
                        focus=scene.get('features',{}).get('focus',[.5,.5]);fx,fy=(max(0.,min(1.,float(v))) for v in focus)
                        vf=f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-ow)*{fx}:(ih-oh)*{fy},setsar=1'
                        if scene.get('variation') in ('reverse','mirror_reverse'):
                            vf+=f',trim=end_frame={scene["frames"]},reverse,setpts=PTS-STARTPTS'
                else:
                    # Decode the still exactly once, instead of re-decoding PNG
                    # for every output frame. A bounded one-frame loop supplies
                    # the same input timeline to camera motion and captions.
                    cmd+=['-threads','1','-framerate',str(fps),'-i',str(base)]
                    # Smooth bounded camera motion derived from the reference
                    # engine's push/pull camera; UI shots remain uncropped.
                    if scene['camera'] in ('push','pull'):
                        if scene.get('motion_curve')=='eased':
                            vf=shot_motion.camera_filter(w,h,fps,scene['frames'],scene['camera'],scene.get('features',{}).get('focus',[.5,.5]))
                        else:
                            expr=f'0.10*on/{max(1,scene["frames"]-1)}'
                            z='1+'+expr if scene['camera']=='push' else '1.10-'+expr
                            vf=f"scale={w*2}:{h*2},zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={scene['frames']}:s={w}x{h}:fps={fps},setsar=1"
                    else:
                        # Blend a static image/overlay once, then repeat that
                        # composite. Time-dependent captions and fades follow.
                        static_still=not scene.get('variation')
                        vf='setsar=1' if static_still else f'setsar=1,loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)'
                variation=scene.get('variation')
                if variation in ('mirror','mirror_reverse'): vf+=',hflip'
                if variation=='grade': vf+=',eq=contrast=1.06:saturation=1.10'
                if variation=='vignette': vf+=',vignette=PI/6'
                # overlay repeats its last decoded frame by default, so a
                # single input image suffices even on moving footage.
                cmd+=['-threads','1','-framerate',str(fps),'-i',str(overlay)]
                if scene['type']=='visualizer': cmd+=['-threads','1','-loop','1','-framerate',str(fps),'-i',str(base)]
                # Relative ASS filename avoids Windows drive/path escaping issues.
                # The server runs the scene subprocess in scratch.
                graph=(vf if scene['type']=='visualizer' else '[0:v]'+vf)+'[base];[base][1:v]overlay=0:0,format=yuv420p'
                if static_still:graph+=f',loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)'
                if scene['type']=='diagram' and not live_diagram:
                    graph+='[diagram];'
                    dot=scratch/'dot.png'; ball=Image.new('RGBA',(max(8,h//24),max(8,h//24)),(0,0,0,0));ImageDraw.Draw(ball).ellipse((1,1,ball.width-2,ball.height-2),fill='#94f58c');ball.save(dot)
                    cmd+=['-threads','1','-framerate',str(fps),'-i',str(dot)]
                    graph+=f"[diagram][2:v]overlay=x='{w*.18}+{w*.64}*min(1,t/{max(.1,seconds)} )-overlay_w/2':y='{h*.765}-overlay_h/2',format=yuv420p"
                if scene.get('transition')=='dip':
                    graph+=f',fade=t=in:st=0:d={min(.16,seconds*.2):.4f}'
                if scene.get('dip_out'):
                    d=min(.16,seconds*.2); graph+=f',fade=t=out:st={seconds-d:.4f}:d={d:.4f}'
                if captions: graph+=',ass=captions.ass'
                graph+='[out]'
                tmp=scratch/'clip.mp4'
                cmd+=['-filter_complex',graph,'-map','[out]','-frames:v',str(scene['frames']),'-an',*perf.director_encode_args(mode,20),str(tmp)]
                encode(cmd,scratch,seconds,f'director_scene_{index+1}',int(5+80*index/len(plan['scenes'])),max(1,int(80/len(plan['scenes']))))
                check_cancel()
                if not walk.valid_scene_clip(tmp,seconds,fps,probe_media): raise RuntimeError('Scene encoder produced invalid or mistimed video')
                perf.publish_staged_file(tmp,clip); made+=1
            clips.append(clip)
            progress(index+1,len(plan['scenes']),made,reused)
        check_cancel()
        # Generated relative cache names avoid concat demuxer quoting and path injection.
        count=0
        if cinematic and plan.get('crossfades'):
            clips,count=cinema.crossfade_clips(clips,plan['scenes'],fps,scratch,encode,check_cancel,duration,style=plan.get('transition_style','dissolve'),seconds=plan.get('transition_seconds',.32),performance_mode=mode)
        # Both cache and scratch paths are generated under work.
        listing=work/('concat-'+uuid4().hex+'.txt'); listing.write_text(''.join(f"file '{p.relative_to(work).as_posix()}'\n" for p in clips),encoding='utf-8')
        temporary=scratch/'final.mp4'
        try:
            cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-filter_complex_threads','1','-f','concat','-safe','1','-threads','1','-i',str(listing),'-ss',f'{audio_start:.6f}','-i',str(audio)]
            if cinematic:
                cinema.write_kinetic_ass(plan,w,h,scratch/'cinematic_captions.ass')
            cues=None
            if cinematic and plan.get('sound_design') and not plan.get('silent'):
                bed=scratch/'original_bed.wav';cinema.original_bed(plan,bed,include_music=music is None,check_cancel=check_cancel,music_gain=plan.get('music_gain',1.),cue_gain=plan.get('cue_gain',1.))
                if music is None: music=bed
                else: cues=bed
            if plan.get('silent'):
                cmd+=['-map','0:v','-an']
            elif cinematic and plan['preset']!='music':
                voice=cinema.voice_chain(plan.get('voice_style','natural'))
                if music:
                    level='0.8' if music==scratch/'original_bed.wav' else str(.12*plan.get('music_gain',1.))
                    cmd+=['-stream_loop','-1','-i',str(music)]
                    if cues: cmd+=['-i',str(cues)]
                    graph=voice+',asplit=2[vo][key];[2:a]aresample=48000,aformat=channel_layouts=stereo,volume='+level+'[bed];[bed][key]sidechaincompress=threshold=0.04:ratio=6:attack=20:release=400[duck];'
                    if cues:
                        graph+='[3:a]aresample=48000,aformat=channel_layouts=stereo[cue];[vo][duck][cue]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.75:level=0:latency=1[a]'
                    else:
                        graph+='[vo][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.75:level=0:latency=1[a]'
                    cmd+=['-filter_complex',graph,'-map','0:v','-map','[a]']
                else:cmd+=['-filter_complex',voice+'[a]','-map','0:v','-map','[a]']
            elif music:
                cmd+=['-stream_loop','-1','-i',str(music),'-filter_complex','[1:a]aresample=48000,asplit=2[voice][key];[2:a]aresample=48000,volume=0.1[bed];[bed][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=450[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]','-map','0:v','-map','[a]']
            else: cmd+=['-map','0:v','-map','1:a:0']
            visual_finish=cinematic and (plan.get('caption_style','karaoke')!='off' or plan.get('title_motion'))
            if visual_finish:cmd+=['-filter_threads','1','-vf',f'ass={scratch.name}/cinematic_captions.ass']
            cmd+=(perf.director_encode_args(mode,18) if visual_finish else ['-c:v','copy'])+([] if plan.get('silent') else ['-c:a','aac','-b:a','192k'])+['-t',f'{duration:.6f}','-movflags','+faststart',str(temporary)]
            encode(cmd,work,duration,'director_mux',85,14)
            check_cancel()
            if not temporary.is_file() or temporary.stat().st_size<1024: raise RuntimeError('Director output missing')
            info=probe_media(temporary)
            if not info['has_video'] or bool(info['has_audio'])==bool(plan.get('silent')) or abs(info['duration']-duration)>max(.13,2/fps): raise RuntimeError('Director output failed stream/timing validation')
            perf.publish_staged_file(temporary,output)
        finally: listing.unlink(missing_ok=True)
        return {'scenes':len(clips),'rendered':made,'cached':reused,'duration':duration,'render_elapsed_seconds':round(time.monotonic()-started,3),'performance_mode':mode,'crossfades':count,'guided_replays':sum(bool(s.get('guided_replay')) and not s.get('replay_fallback') for s in plan['scenes']),'recorded_scenes':sum(bool(s.get('recorded_demo')) for s in plan['scenes'])}
    finally:
        shutil.rmtree(scratch,ignore_errors=True)
