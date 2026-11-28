"""Timeline-preserving Director finishing: overlapping visuals, kinetic captions,
optional original backing bed and subtle cut accents. No cloud or media downloads.
"""
from __future__ import annotations
import math
import wave
from pathlib import Path
import numpy as np
from studio_walkthrough import replay_hit
from studio_editorial import marker_layout, marker_font
from studio_score import write_score
import subprocess
import re


TITLE_STYLES={"slide","pop","fade","adaptive"}


def transition_frames(previous, current, fps, seconds=.32):
    if previous['type']==current['type']=='visualizer': return 0
    return min(round(seconds*fps), previous['frames']//5, current['frames']//5)


def ass_time(t):
    cs=max(0,round(t*100));return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'


def escape(text):
    return str(text).replace('\\','／').replace('{','｛').replace('}','｝').replace('\n',' ').replace('\r',' ')


def write_kinetic_ass(plan, width, height, target):
    """Stable phrase positions; per-word progressive highlighting, short entrance.
    Timestamp-based where supplied; estimated timings are not invented ASR results.
    """
    style=plan.get("caption_style","karaoke")
    size=max(18,round(min(width*.045,height*.055)*plan.get("caption_scale",1.)))
    x,y=width//2,round(height*.89)
    rows=[f'''[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Main,Arial,{size},&H008CF5A0,&H00F0F2EF,&H00101712,&H88000000,-1,0,0,0,100,100,0,0,1,{max(2,size//15)},1,5,{width//12},{width//12},0,1\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n''']
    # Independent title layer: transitions never blend duplicated titles or captions.
    if plan.get('title_motion'):
        for index,scene in enumerate(plan['scenes']):
            if scene['type'] not in ('ui_demo','big_text','outro') or scene.get('editorial'):continue
            text=str(scene.get('hero_title') or scene.get('text') or '').strip().upper()
            if not text:continue
            a=float(scene['start']);b=float(scene['end']);ms=round((b-a)*1000)
            if ms<180:continue
            split=scene['type']=='ui_demo' and not scene.get('recorded_demo') and width/height>=1.5
            # Video-backed demos use the top bar, not the screenshot's title column.
            if scene.get('asset','').lower().endswith(('.mp4','.mov','.webm','.mkv','.m4v')):split=False
            if split:
                xx,yy=round(width*.055),round(height*.28);fs=round(height*.068);limit=width*.34;align=7
            elif scene['type']=='ui_demo':
                xx,yy=width//2,round(height*.065);fs=round(min(height*.05,width*.065));limit=width*.88;align=5
            else:
                xx,yy=width//2,round(height*.46);fs=round(min(height*.075,width*.085));limit=width*.78;align=5
            from PIL import ImageFont
            def width_of(value,size):
                for name in ('arialbd.ttf','DejaVuSans-Bold.ttf'):
                    try:return ImageFont.truetype(name,size).getlength(value)
                    except OSError:pass
                return len(value)*size*.7
            if split or scene['type']!='ui_demo':
                while fs>16 and any(width_of(word,fs)>limit for word in text.split()):fs-=2
                chunks=[];line=''
                for word in text.split():
                    trial=(line+' '+word).strip()
                    if line and width_of(trial,fs)>limit:chunks.append(line);line=word
                    else:line=trial
                if line:chunks.append(line)
                if len(chunks)>3:
                    while fs>16 and width_of(text,fs)>limit*2.7:fs-=2
                    chunks=[];line=''
                    for word in text.split():
                        trial=(line+' '+word).strip()
                        if line and width_of(trial,fs)>limit:chunks.append(line);line=word
                        else:line=trial
                    if line:chunks.append(line)
                title=r'\N'.join(escape(c) for c in chunks[:3])
            else:
                while fs>16 and width_of(text,fs)>limit:fs-=2
                title=escape(text)
            enter=min(280,ms//4);exit=min(180,ms//5)
            motion=plan.get('title_style','slide')
            if motion=='adaptive':motion=('slide','fade','pop')[index%3]
            if motion=='pop':entrance=rf'\pos({xx},{yy})\fscx90\fscy90\t(0,{enter},\fscx100\fscy100)'
            elif motion=='fade':entrance=rf'\pos({xx},{yy})'
            else:entrance=rf'\move({xx-max(10,width//45)},{yy},{xx},{yy},0,{enter})'
            tags=rf'{{\an{align}\fs{fs}\bord1\shad0\c&H00E7F0E7&{entrance}\fad({enter},{exit})}}' 
            rows.append(f'Dialogue: 1,{ass_time(a)},{ass_time(b)},Main,,0,0,0,,{tags}{title}\n')
    # Documentary captions are authored on the speech clock, not the shot clock.
    # The same phrase can survive a visual cut without re-entering or losing a word.
    independent = plan.get('caption_track') is not None and style=='marker'
    caption_scenes = [{'start':0.,'captions':plan['caption_track']}] if independent else plan['scenes']
    for scene in ([] if style=='off' else caption_scenes):
        offset=float(scene['start'])
        for cap in scene.get('captions',[]):
            start,end=float(cap['start']),float(cap['end'])
            if end-start<.07: continue
            words=cap.get('words') or []
            if not words:
                text=str(cap['text']).split();n=len(text)
                words=[{'text':w,'start':start+(end-start)*i/max(1,n),'end':start+(end-start)*(i+1)/max(1,n)} for i,w in enumerate(text)]
            if not words: continue
            if style=='marker':
                layout=marker_layout(cap['text'],width,height,plan.get('caption_scale',1.))
                a,b=ass_time(offset+start),ass_time(offset+end)
                ms=round((end-start)*1000);fade=min(105,ms//5);out=min(85,ms//5)
                light=not independent and scene.get('editorial') in ('chapter','graphic')
                for index,(word,hot,xx,yy,fs,ww,hh) in enumerate(layout):
                    face=marker_font(fs).getname()[0]
                    color='&H00191817&' if light else '&H00F7F5F2&'
                    outline='&H00EAF0F1&' if light else '&H00101712&'
                    # Whole phrase has fixed metrics and a single short opacity entrance.
                    tags=rf'{{\an5\pos({xx},{yy})\fn{face}\fs{fs}\b0\bord{1 if light else max(2,fs//12)}\shad0\1c{color}\3c{outline}\fad({fade},{out})}}'
                    rows.append(f'Dialogue: 1,{a},{b},Main,,0,0,0,,{tags}'+escape(word)+'\n')
                    if not hot:continue
                    # Highlight follows the selected word's actual supplied/estimated onset.
                    onset=max(start,min(end-.04,float(words[index]['start']) if index<len(words) else start))
                    at=ass_time(offset+onset);remain=round((end-onset)*1000)
                    if remain<45:continue
                    reveal=min(220,max(35,round(remain*.45)));tail=min(out,remain//4)
                    left,top=xx-ww//2,yy-hh//2;right,bottom=left+ww,top+hh
                    clip=rf'\clip({left},{top},{left+1},{bottom})\t(0,{reveal},0.65,\clip({left},{top},{right},{bottom}))'
                    shape=f'm 0 0 l {ww} 0 {ww} {hh} 0 {hh}'
                    tags=rf'{{\an7\pos({left},{top})\bord0\shad0\1c&H004ED6F5&\fad(0,{tail}){clip}\p1}}'
                    rows.append(f'Dialogue: 2,{at},{b},Main,,0,0,0,,{tags}{shape}{{\\p0}}\n')
                    tags=rf'{{\an5\pos({xx},{yy})\fn{face}\fs{fs}\b0\bord0\shad0\1c&H00191817&\fad(0,{tail}){clip}}}'
                    rows.append(f'Dialogue: 3,{at},{b},Main,,0,0,0,,{tags}'+escape(word)+'\n')
                continue
            if style=='word':
                for word in words:
                    a=max(start,float(word['start']));b=min(end,float(word['end']))
                    if b-a<.025:continue
                    rows.append(f'Dialogue: 0,{ass_time(offset+a)},{ass_time(offset+b)},Main,,0,0,0,,'+rf'{{\an5\pos({x},{y})\fscx92\fscy92\t(0,100,\fscx100\fscy100)}}'+escape(word['text'])+'\n')
                continue
            if style=='clean':
                rows.append(f'Dialogue: 0,{ass_time(offset+start)},{ass_time(offset+end)},Main,,0,0,0,,'+rf'{{\an5\pos({x},{y})\c&H00F0F2EF&}}'+escape(cap['text'])+'\n');continue
            # The phrase enters once; highlights follow original word boundaries.
            cursor=round(start*100);last=round(end*100);spans=[]
            for i,word in enumerate(words):
                a=max(cursor,round(float(word['start'])*100));b=min(last,max(a+1,round(float(word['end'])*100)))
                if b<=a:continue
                if a>cursor:spans.append(r'{\k'+str(a-cursor)+'} ')
                elif spans:spans.append(' ')
                spans.append(r'{\kf'+str(b-a)+'}'+escape(word['text']));cursor=b
            if not spans:continue
            tags=rf'{{\an5\move({x},{y+max(4,height//70)},{x},{y},0,130)\fad(100,80)}}'
            rows.append(f'Dialogue: 0,{ass_time(offset+start)},{ass_time(offset+end)},Main,,0,0,0,,{tags}'+''.join(spans)+'\n')
    target.write_text(''.join(rows),encoding='utf-8-sig')


def crossfade_clips(clips, scenes, fps, scratch, encode, check_cancel, duration, *,style="dissolve",seconds=.32):
    """Bounded two-input crossfades. An outgoing final-frame handle overlaps
    incoming moving footage, preserving exact soundtrack/scene frame counts.
    Captions are composed AFTER the transitions, never blended twice.
    """
    if not clips:return [],0
    result=[clips[0]];count=0
    for i in range(1,len(clips)):
        check_cancel();n=0 if style=='cut' else transition_frames(scenes[i-1],scenes[i],fps,seconds)
        if n<2:result.append(clips[i]);continue
        d=n/fps;length=scenes[i]['frames']/fps;prev=(scenes[i-1]['frames']-1)/fps
        out=scratch/f'crossfade-{i:04d}.mp4'
        mode={'dissolve':'fade','slide':'slideleft','wipe':'wipeleft','auto':('fade' if scenes[i]['type'] in ('ui_demo','diagram') else ('fade','slideleft','wipeleft')[i%3])}.get(style,'fade')
        graph=(f'[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration={d+2/fps:.8f},format=yuv444p,setsar=1,fps={fps},settb=1/{fps}[a];'
               f'[1:v]setpts=PTS-STARTPTS,format=yuv444p,setsar=1,fps={fps},settb=1/{fps}[b];'
               f'[a][b]xfade=transition={mode}:duration={d:.8f}:offset=0,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,settb=1/{fps},setpts=N[out]')
        args=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-progress','pipe:1','-nostats','-filter_complex_threads','1','-ss',f'{prev:.8f}','-i',str(clips[i-1]),'-i',str(clips[i]),'-filter_complex',graph,'-map','[out]','-frames:v',str(scenes[i]['frames']),'-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-bf','0','-r',str(fps),'-fps_mode','cfr','-enc_time_base:v',f'1:{fps}','-video_track_timescale','60000','-use_editlist','0','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-chroma_sample_location','left',str(out)]
        encode(args,scratch,length,f'director_crossfade_{i}',80+int(5*i/len(clips)),1)
        if not out.is_file() or out.stat().st_size<1024:raise RuntimeError('Crossfade produced no video')
        result.append(out);count+=1
    return result,count


def original_bed(plan,path,*,rate=24000,include_music=True,check_cancel=lambda:None,music_gain=1.,cue_gain=1.):
    return write_score(plan,path,rate=rate,include_music=include_music,check_cancel=check_cancel,music_gain=music_gain,cue_gain=cue_gain)


def silent_voice(path,start,duration):
    """Detect digital silence before loudnorm: zero-energy input has undefined gain."""
    cmd=['ffmpeg','-hide_banner','-nostdin','-ss',str(start),'-i',str(path),'-t',str(duration),'-vn','-af','volumedetect','-f','null','-']
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
    if result.returncode:raise RuntimeError('Narration level probe failed')
    peak=re.findall(r'max_volume:\s*([-\d.]+) dB',result.stderr)
    return bool(peak and float(peak[-1])<=-90.)


def voice_chain(style, *, silent=False):
    base='[1:a]aresample=48000,aformat=channel_layouts=stereo'
    if style=='off' or silent:return base
    if style=='present':return base+',highpass=f=95,equalizer=f=280:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1:g=2,lowpass=f=13000,acompressor=threshold=0.09:ratio=2.5:attack=8:release=120,loudnorm=I=-16:TP=-2:LRA=7,aresample=48000'
    return base+',highpass=f=80,lowpass=f=11000,acompressor=threshold=0.10:ratio=2:attack=12:release=120,loudnorm=I=-17:TP=-2:LRA=7,aresample=48000'
