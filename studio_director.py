"""Local-first scene director adapted from the supplied autoedit.py and prompt.

No network, external AI, invented facts, inline SVG execution or arbitrary paths.
Plan at transcript boundaries, select supplied media, cache individual scenes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont, ImageOps

import studio_performance as perf

VERSION = 2
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.m4v', '.webm'}
PRESETS = {
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


def assets_for(folder: Path) -> list[dict]:
    if not folder.is_dir() or folder.is_symlink():
        return []
    index = perf.read_cache(folder / 'index.json')
    items = []
    for key, value in sorted(index.items()):
        path = asset_path(folder, key)
        if path is None or not isinstance(value, dict):
            continue
        label = str(value.get('name', key))[:120]
        items.append({'id': key, 'name': label, 'kind': 'video' if path.suffix in VIDEO_EXT else 'image',
                      'description': str(value.get('description', ''))[:300]})
    return items[:40]


def make_plan(lines: list[dict], duration: float, assets: list[dict], preset: str,
              brand: str = 'SKELLYMOTION', *, fps: int = 30, preview: bool = False) -> dict:
    """Deterministic, frame-contiguous scene planning from real transcript and assets."""
    if preset not in PRESETS or fps not in (24, 30) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid director timing or style')
    duration = min(duration, 15.0) if preview else duration
    if duration > 1800:
        raise ValueError('Director currently supports up to 30 minutes of audio')
    total = max(1, round(duration * fps))
    look = PRESETS[preset]
    lines = [line for line in lines if float(line['start']) < duration and float(line['end']) > 0]
    boundaries = sorted({round(float(line['end']) * fps) for line in lines if 0 < float(line['end']) < duration})
    scenes, cursor, used = [], 0, []
    while cursor < total:
        ideal = cursor + round(look['pace'] * fps)
        maximum = min(total, cursor + round(look['maximum'] * fps))
        lower = cursor + round(1.0 * fps)
        candidates = [b for b in boundaries if lower <= b <= maximum and abs(b - ideal) <= round(2.0 * fps)]
        end = total if total - cursor <= round(look['pace'] * fps * 1.2) else min(maximum, min(candidates, key=lambda b: abs(b - ideal)) if candidates else ideal)
        if total - end < fps:
            end = total
        end = max(cursor + 1, min(end, total))
        start_sec, end_sec = cursor / fps, end / fps
        active = [line for line in lines if float(line['end']) > start_sec and float(line['start']) < end_sec]
        text = ' '.join(str(row['text']) for row in active)
        title = ' '.join((str(active[0]['text']) if active else '').split()[:4])[:64] or brand
        scene = {'start': start_sec, 'end': end_sec, 'frames': end-cursor, 'type': 'big_text', 'text': title,
                 'captions': [{'text': str(row['text'])[:300], 'start': max(start_sec, float(row['start'])) - start_sec,
                               'end': min(end_sec, float(row['end'])) - start_sec,
                               'words': []} for row in active], 'camera': 'still'}
        if assets:
            pool = [a for a in assets if not (len(used) >= 2 and used[-1] == used[-2] == a['id'])] or assets
            def score(a):
                overlap = len(terms(text) & terms(a['name'] + ' ' + a.get('description', '')))
                return (overlap, int(preset == 'plugin' and a['kind'] == 'image'), -used.count(a['id']))
            chosen = max(pool, key=score)
            kind = 'ui_demo' if preset == 'plugin' else 'document' if chosen['kind'] == 'image' and terms(chosen['name']+' '+chosen.get('description','')) & {'article','document','source','comment','forum'} else 'broll'
            scene.update(type=kind, asset=chosen['id'], asset_name=chosen['name'],
                         camera='still' if kind in ('ui_demo','document') else ('push' if len(scenes) % 2 == 0 else 'pull'),
                         text=title if preset == 'plugin' else '')
            used.append(chosen['id'])
        if end == total and not active:
            scene.update(type='outro', text=brand, camera='still')
            scene.pop('asset', None); scene.pop('asset_name', None)
        scenes.append(scene)
        cursor = end
    return {'version': VERSION, 'preset': preset, 'fps': fps, 'duration': duration, 'frames': total,
            'scenes': scenes, 'director': 'local', 'warnings': ([] if assets else ['No visual assets supplied: transcript-based text cards will be used.'])}


def font(size: int, bold: bool = False):
    for candidate in ([r'C:\Windows\Fonts\arialbd.ttf', 'DejaVuSans-Bold.ttf'] if bold else [r'C:\Windows\Fonts\arial.ttf', 'DejaVuSans.ttf']):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def centered_text(draw: ImageDraw.ImageDraw, text: str, w: int, y: int, size: int, color: str, bold=True):
    f = font(size, bold)
    words = text.split()[:12]
    while words and draw.textlength(' '.join(words), font=f) > w * .84 and size > 15:
        size -= 2
        f = font(size, bold)
    draw.text((w // 2, y), ' '.join(words), font=f, fill=color, anchor='mm')


def artwork(scene: dict, preset: str, w: int, h: int, asset: Path | None, base: Path, overlay: Path) -> None:
    look = PRESETS[preset]
    bg = Image.new('RGB', (w, h), look['background'])
    if asset and asset.suffix in IMAGE_EXT:
        with Image.open(asset) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
            if scene['type'] in ('ui_demo','document'):
                tile = ImageOps.contain(image, (round(w*.92), round(h*.60)))
                bg.paste(tile, ((w-tile.width)//2, int(h*.46)-tile.height//2))
            else:
                bg.paste(ImageOps.fit(image, (w,h)), (0,0))
    elif not asset:
        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((round(w*.08), round(h*.14), round(w*.92), round(h*.80)), radius=max(8,h//30), outline='#34463d', width=max(1,h//400))
        centered_text(draw, scene['text'], w, int(h*.46), max(24,h//13), '#f4f8f2')
        draw.rectangle((int(w*.43),int(h*.60),int(w*.57),int(h*.605)), fill=look['accent'])
    bg.save(base)
    layer = Image.new('RGBA',(w,h),(0,0,0,0)); d = ImageDraw.Draw(layer)
    if scene['type'] == 'ui_demo':
        d.rectangle((0,0,w,int(h*.13)), fill=(10,14,12,230))
        centered_text(d, scene['text'].upper(), w, int(h*.068), max(18,h//20), look['accent'])
    if scene['captions']:
        for y in range(int(h*.75),h):
            alpha = round(175 * ((y-h*.75)/(h*.25)))
            d.line((0,y,w,y),fill=(0,0,0,alpha))
    layer.save(overlay)


def scene_key(scene: dict, asset: Path | None, settings: dict, size: tuple[int,int], preset: str) -> str:
    stamp = [asset.name,asset.stat().st_size,asset.stat().st_mtime_ns] if asset else None
    return hashlib.sha256(json.dumps([VERSION,scene,stamp,settings,size,preset],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def render(plan: dict, audio: Path, assets_folder: Path, work: Path, output: Path, settings: dict,
           size: tuple[int,int], make_ass: Callable, encode: Callable, check_cancel: Callable,
           progress: Callable, music: Path | None = None) -> dict:
    """Render one scene at a time, cache complete clips, then mux audio."""
    w,h = size; fps=plan['fps']; duration=plan['duration']; work.mkdir(parents=True,exist_ok=True)
    cache=work/'scenes'; cache.mkdir(exist_ok=True); made=reused=0; clips=[]
    scratch=work/('job-'+uuid4().hex); scratch.mkdir()
    import shutil
    try:
        for index, scene in enumerate(plan['scenes']):
            check_cancel()
            asset=asset_path(assets_folder,scene.get('asset')) if scene.get('asset') else None
            if scene.get('asset') and asset is None:
                raise ValueError('An asset disappeared; refresh the scene plan')
            key=scene_key(scene,asset,settings,size,plan['preset']); clip=cache/(key+'.mp4')
            seconds=scene['frames']/fps
            if clip.is_file() and clip.stat().st_size>1024:
                reused+=1
            else:
                base=scratch/'base.png'; overlay=scratch/'overlay.png'; ass=scratch/'captions.ass'
                artwork(scene,plan['preset'],w,h,asset,base,overlay)
                captions=scene['captions']; make_ass(captions,ass)
                cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-filter_complex_threads','1']
                if asset and asset.suffix in VIDEO_EXT:
                    cmd+=['-stream_loop','-1','-i',str(asset)]
                    if scene['type']=='ui_demo':
                        vf=f"fps={fps},scale={int(w*.92)//2*2}:{int(h*.60)//2*2}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:{int(h*.46)}-ih/2:color=0x101216,setsar=1"
                    else:
                        vf=f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1'
                else:
                    cmd+=['-loop','1','-framerate',str(fps),'-i',str(base)]
                    if scene['camera'] in ('push','pull'):
                        expr=f'0.10*on/{max(1,scene["frames"]-1)}'
                        z='1+'+expr if scene['camera']=='push' else '1.10-'+expr
                        vf=f"scale={w*2}:{h*2},zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps},setsar=1"
                    else: vf='setsar=1'
                cmd+=['-loop','1','-framerate',str(fps),'-i',str(overlay)]
                graph=f'[0:v]{vf}[base];[base][1:v]overlay=0:0,format=yuv420p'
                if captions: graph+=',ass=captions.ass'
                graph+='[out]'
                tmp=scratch/'clip.mp4'
                cmd+=['-filter_complex',graph,'-map','[out]','-frames:v',str(scene['frames']),'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(tmp)]
                encode(cmd,scratch,seconds,f'director_scene_{index+1}',int(5+80*index/len(plan['scenes'])),max(1,int(80/len(plan['scenes']))))
                check_cancel()
                if not tmp.is_file() or tmp.stat().st_size<1024: raise RuntimeError('Scene encoder did not produce a video')
                perf.publish_staged_file(tmp,clip); made+=1
            clips.append(clip)
            progress(index+1,len(plan['scenes']),made,reused)
        check_cancel()
        listing=work/('concat-'+uuid4().hex+'.txt'); listing.write_text(''.join(f"file 'scenes/{p.name}'\n" for p in clips),encoding='utf-8')
        temporary=scratch/'final.mp4'
        try:
            cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-f','concat','-safe','1','-i',str(listing),'-i',str(audio)]
            if music:
                cmd+=['-stream_loop','-1','-i',str(music),'-filter_complex','[1:a]aresample=48000,asplit=2[voice][key];[2:a]aresample=48000,volume=0.1[bed];[bed][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=450[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]','-map','0:v','-map','[a]']
            else: cmd+=['-map','0:v','-map','1:a:0']
            cmd+=['-c:v','copy','-c:a','aac','-b:a','192k','-t',f'{duration:.6f}','-movflags','+faststart',str(temporary)]
            encode(cmd,work,duration,'director_mux',85,14)
            check_cancel()
            if not temporary.is_file() or temporary.stat().st_size<1024: raise RuntimeError('Director output missing')
            perf.publish_staged_file(temporary,output)
        finally: listing.unlink(missing_ok=True)
        return {'scenes':len(clips),'rendered':made,'cached':reused,'duration':duration}
    finally:
        shutil.rmtree(scratch,ignore_errors=True)
