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


if __name__ == "__main__":
    sys.exit(main())
