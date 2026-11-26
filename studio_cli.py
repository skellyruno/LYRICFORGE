#!/usr/bin/env python3
"""Headless SkellyMotion: edit a video or watch a folder, no window needed.

  python studio_cli.py edit  "my recording.mp4" --out finished/ --preset Tutorial --shorts 3
  python studio_cli.py watch inbox/ --out finished/ --preset "Plugin showcase"   (leave running; drop videos into inbox/)

Each video becomes finished/<name>/ with video.mp4, thumbnail.jpg, youtube.txt (title, description with
chapters, tags), posts.txt, captions.srt/.vtt and an optional shorts/ folder. Your brand kit (logo, end card, music,
intro/outro, B-roll) from the app is used automatically. Presets are the ones saved in the app plus the built-ins.
Explicit flags always win over the preset.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULTS = {"trim_silence": True, "min_gap": .8, "zoom": "off", "loudness": True, "captions": False, "watermark": True,
            "endcard": True, "resolution": "1080p", "shorts": 0, "sfx": True, "callouts": True, "chapter_titles": True,
            "music": True, "intro_outro": True, "intro_card": False, "voice_cleanup": "off", "fillers": "off",
            "zoom_mode": "motion", "broll": True}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio_cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (("edit", "edit one video"), ("watch", "edit every video that lands in a folder")):
        cmd = sub.add_parser(name, help=helptext)
        cmd.add_argument("source", help="a video file" if name == "edit" else "the folder to watch")
        cmd.add_argument("--out", required=True, help="folder for the finished packages")
        cmd.add_argument("--preset", help="start from a saved or built-in preset (Tutorial, Plugin showcase, ...)")
        cmd.add_argument("--no-trim", action="store_true", help="keep dead air")
        cmd.add_argument("--min-gap", type=float, default=None, help="silence longer than this many seconds is cut")
        cmd.add_argument("--zoom", choices=["off", "subtle", "medium", "strong"], default=None)
        cmd.add_argument("--zoom-mode", choices=["motion", "ui"], default=None,
                         help="motion: follow what moves; ui: zoom to small sudden changes and ring them")
        cmd.add_argument("--voice-cleanup", choices=["off", "light", "medium", "strong"], default=None)
        cmd.add_argument("--remove-fillers", dest="fillers", choices=["off", "basic", "more"], default=None,
                         help="cut um/uh (basic), or also 'you know', 'I mean', 'sort of', 'kind of' (more)")
        cmd.add_argument("--captions", action="store_true", help="burn captions into the picture")
        cmd.add_argument("--no-loudness", action="store_true")
        cmd.add_argument("--no-watermark", action="store_true")
        cmd.add_argument("--no-endcard", action="store_true")
        cmd.add_argument("--no-sfx", action="store_true", help="no generated sound effects")
        cmd.add_argument("--no-callouts", action="store_true", help="no animated callout boxes")
        cmd.add_argument("--no-chapter-titles", action="store_true", help="no sliding chapter titles")
        cmd.add_argument("--no-music", action="store_true", help="ignore the brand kit's background music")
        cmd.add_argument("--no-intro-outro", action="store_true", help="ignore the brand kit's intro/outro clips")
        cmd.add_argument("--no-broll", action="store_true", help="ignore the brand kit's B-roll library")
        cmd.add_argument("--intro-card", action="store_true", help="add an animated title card at the start")
        cmd.add_argument("--resolution", choices=["720p", "1080p"], default=None)
        cmd.add_argument("--shorts", type=int, default=None, help="also render this many vertical Shorts (0-6)")
        cmd.add_argument("--language", default="auto", help="spoken language code, or auto")
        cmd.add_argument("--recognition", choices=["fast", "balanced", "accurate"], default="balanced")
        if name == "edit":
            cmd.add_argument("--keep-project", action="store_true", help="keep the working copy so it opens in Clip Studio")
    create=sub.add_parser('create',help='create a narrated video from an agent/owner JSON job')
    create.add_argument('manifest',help='JSON brief, approved script and local assets')
    create.add_argument('--out',required=True,help='new output folder (never overwrite existing output)')
    create.add_argument('--draft-only',action='store_true',help='synthesize and save an editable project without rendering')
    return parser


def build_options(args: argparse.Namespace, preset: dict | None = None) -> dict:
    """Defaults, then the preset, then anything given explicitly on the command line."""
    opts = dict(DEFAULTS)
    opts.update({k: v for k, v in (preset or {}).items() if k in DEFAULTS})
    for flag, key in (("no_trim", "trim_silence"), ("no_loudness", "loudness"), ("no_watermark", "watermark"),
                      ("no_endcard", "endcard"), ("no_sfx", "sfx"), ("no_callouts", "callouts"),
                      ("no_chapter_titles", "chapter_titles"), ("no_music", "music"), ("no_intro_outro", "intro_outro"),
                      ("no_broll", "broll")):
        if getattr(args, flag):
            opts[key] = False
    for flag in ("captions", "intro_card"):
        if getattr(args, flag):
            opts[flag] = True
    for key in ("min_gap", "zoom", "zoom_mode", "voice_cleanup", "fillers", "resolution"):
        if getattr(args, key) is not None:
            opts[key] = getattr(args, key)
    if args.shorts is not None:
        opts["shorts"] = args.shorts
    opts["shorts"] = max(0, min(6, int(opts["shorts"])))
    return opts


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command=='create':
        try:return create_from_manifest(Path(args.manifest).expanduser(),Path(args.out).expanduser(),args.draft_only)
        except (ValueError,RuntimeError,OSError) as exc:
            print(f'Error: {exc}',file=sys.stderr);return 1
    import server  # imported late so --help is instant

    preset = None
    if args.preset:
        preset = server.posts_lib.with_preset(server.load_user_presets(), args.preset)
        if preset is None:
            names = ", ".join(r["name"] for r in server.posts_lib.list_presets(server.load_user_presets()))
            print(f"Error: no preset named {args.preset!r}. Available: {names}", file=sys.stderr)
            return 2
    options = build_options(args, preset)
    out = Path(args.out).expanduser()
    if args.command == "edit":
        try:
            result = server.process_video_file(Path(args.source).expanduser(), out, options, language=args.language,
                                               recognition=args.recognition, keep_project=args.keep_project, log=print)
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(result)
        return 0

    os.environ["SKELLYMOTION_WATCH"] = "1"
    try:
        server.watch_start(server.WatchRequest(folder=args.source, out=str(out), options=server.AutoEditRequest(**options),
                                               language=args.language, recognition=args.recognition))
    except server.HTTPException as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    print(f"Watching {args.source}. Press Ctrl+C to stop.")
    shown = 0.0
    try:
        while True:
            time.sleep(2)
            for event in server.watch_status()["events"]:
                if event["time"] > shown:
                    print(event["message"])
                    shown = event["time"]
    except KeyboardInterrupt:
        server.watch_stop()
        print("Stopped.")
        return 0


def create_from_manifest(manifest: Path, out: Path, draft_only=False):
    """Trusted local CLI: reads explicit paths from the agent's manifest. The HTTP API never does."""
    import asyncio,json,shutil
    from contextlib import ExitStack
    from fastapi import UploadFile,HTTPException
    import server
    if manifest.stat().st_size>256*1024:raise ValueError('Job manifest exceeds 256 KiB')
    raw=json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(raw,dict):raise ValueError('Manifest must be a JSON object')
    assets=raw.pop('assets',[])
    if not isinstance(assets,list) or len(assets)>40:raise ValueError('Manifest supports up to 40 assets')
    if out.exists():raise ValueError('Output folder already exists; choose a fresh output path')
    payload=dict(raw);payload['visual_roles']=[]
    if draft_only:payload['auto_render']=False
    with ExitStack() as stack:
        files=[]
        for item in assets:
            if not isinstance(item,dict) or not isinstance(item.get('path'),str):raise ValueError('Each asset needs a local path')
            source=(manifest.parent/item['path']).resolve()
            if not source.is_file():raise ValueError('Asset file not found: '+str(source))
            size=source.stat().st_size
            if size>80*1024*1024:raise ValueError('Asset exceeds 80 MiB: '+source.name)
            files.append(UploadFile(stack.enter_context(source.open('rb')),filename=source.name,size=size))
            payload['visual_roles'].append({k:v for k,v in item.items() if k in ('role','group','order','description','focus_x','focus_y','trim_start','trim_end')})
        try:result=asyncio.run(server.create_video_request(payload=json.dumps(payload),files=files))
        except HTTPException as exc:raise ValueError(str(exc.detail)) from exc
    pid=result['project_id'];job_id=result['job_id'];p=server.project_dir(pid);print('PROJECT',pid,'VOICE',result['voice_provider'],flush=True)
    last=None
    try:
        while True:
            job=server.get_job(job_id);state=(job.get('stage'),job.get('progress'))
            if state!=last:print(*state,flush=True);last=state
            if job['status']!='rendering':break
            time.sleep(.5)
    except KeyboardInterrupt:
        server.cancel_job(job_id);print('Cancellation requested; project retained:',pid,file=sys.stderr);return 130
    if job['status']!='done':raise RuntimeError(f"{job.get('error',job['status'])}; retained project {pid}")
    out.mkdir(parents=True,exist_ok=False)
    for name in ('voice.wav','project.json','director.mp4','director_plan.json','director.vtt','director_preview.mp4','director_preview_plan.json','director_preview.vtt'):
        src=p/name
        if src.is_file():shutil.copy2(src,out/name)
    (out/'script.json').write_text(json.dumps(server.read_project(pid).get('creator_script',[]),indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'job-result.json').write_text(json.dumps(job,indent=2,ensure_ascii=False),encoding='utf-8')
    print('OUTPUT',out,flush=True);return 0


if __name__ == "__main__":
    sys.exit(main())
