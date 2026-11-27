"""Finite independent Hold streams; patch only the exact staged Creator candidate."""
from pathlib import Path
import sys

def once(s,a,b):
    if s.count(a)!=1:raise ValueError('Unexpected source anchor '+a[:80])
    return s.replace(a,b,1)

def apply(root):
    root=Path(root)
    p=root/'studio_quick2.py';s=p.read_text(encoding='utf-8');a=s.index('def hold_build(');b=s.index('# ---- cut out a section',a)
    s=s[:a]+'''def hold_build(p, o, out, safe):
    """Encode only picture: FFmpeg 8+ can deadlock when leading tpad and adelay share a scheduler."""
    fps = o.get("fps", 30.0)
    first, last = _hold_frames(o['start'],fps), _hold_frames(o['end'],fps)
    vf=(f"setpts=PTS-STARTPTS,fps={fps:g},"
        f"tpad=start_mode=clone:start={first}:stop_mode=clone:stop={last},"
        f"trim=end_frame={o['frames']},setpts=N/({fps:g}*TB)")
    return [*QUIET,"-y","-filter_threads","1","-threads","2","-i",str(p['video']),
            "-vf",vf,"-map","0:v:0","-an","-r",str(fps),"-fps_mode","cfr",
            *X264,"-threads","2",*FAST,"-frames:v",str(o['frames']),str(out)]


def hold_audio_build(p, o, out):
    fps=o['fps'];first=_hold_frames(o['start'],fps)
    samples=round(o['seconds']*48000)
    af="aresample=48000,"+(f"adelay={round(first/fps*48000)}S:all=1," if first else "")+f"apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB"
    return [*QUIET,"-y","-filter_threads","1","-threads","2","-i",str(p['video']),
            "-vn","-map","0:a:0","-af",af,"-c:a","aac","-b:a","192k",str(out)]


def hold_mux_build(picture, audio, out):
    # Independent finite streams: no filter graph, no second encode, no shortest/truncation.
    return [*QUIET,"-y","-i",str(picture),"-i",str(audio),"-map","0:v:0","-map","1:a:0","-c","copy",*FAST,str(out)]


'''+s[b:];s=once(s,'("fps", "setpts", "loop", "tpad", "trim", "aresample", "adelay", "apad", "atrim", "asetpts")','("fps", "setpts", "tpad", "trim", "aresample", "adelay", "apad", "atrim", "asetpts")');compile(s,str(p),'exec');p.write_text(s,encoding='utf-8')
    p=root/'server.py';s=p.read_text(encoding='utf-8');anchor='''        try:
            run_one_ffmpeg(project_id, job_id, "quick_render", tool.build(paths, opts, out, False), out, opts["seconds"])'''
    s=once(s,anchor,'''        if tool.id == "hold":
            # Each encoder handles just one stream. Mux packet copies only after
            # both have completed. Cancellation/failure cleans private scratch;
            # the previous published output remains intact until atomic replace.
            with tempfile.TemporaryDirectory(prefix="hold-", dir=p) as scratch:
                scratch=Path(scratch);picture=scratch/"picture.mp4"
                run_one_ffmpeg(project_id, job_id, "hold_picture", quick2_lib.hold_build(paths,opts,picture,False),picture,opts["seconds"])
                check_cancel(job_id)
                final=picture
                if opts["has_audio"]:
                    audio=scratch/"audio.m4a";final=scratch/"muxed.mp4"
                    run_one_ffmpeg(project_id,job_id,"hold_audio",quick2_lib.hold_audio_build(paths,opts,audio),audio,opts["seconds"])
                    check_cancel(job_id)
                    run_one_ffmpeg(project_id,job_id,"hold_mux",quick2_lib.hold_mux_build(picture,audio,final),final,opts["seconds"])
                check_cancel(job_id)
                if not final.is_file() or not final.stat().st_size:
                    raise RuntimeError("Hold encoder produced no output")
                perf.publish_staged_file(final,out)
            finish_tool_job(job_id,started,[tool_file(tool.label(opts),project_id,tool.out,tool.kind)],seconds=round(opts["seconds"],2))
            return
        try:
            run_one_ffmpeg(project_id, job_id, "quick_render", tool.build(paths, opts, out, False), out, opts["seconds"])''');compile(s,str(p),'exec');p.write_text(s,encoding='utf-8')

if __name__=='__main__':apply(sys.argv[1])
