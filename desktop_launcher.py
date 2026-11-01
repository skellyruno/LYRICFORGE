"""SkellyMotion desktop host: a native Windows window, no cmd or browser tab."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing import freeze_support


def runtime_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def configure() -> Path:
    root = runtime_dir()
    tools = root / "tools"
    if tools.exists():
        os.environ["PATH"] = str(tools) + os.pathsep + os.environ.get("PATH", "")
    home = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LyricForge"
    # Keep existing paths so older songs, corrected lyrics and the Whisper
    # model cache can be used with new builds without another download.
    os.environ.setdefault("LYRICFORGE_DATA", str(home / "workspace"))
    os.environ.setdefault("HF_HOME", str(home / "models"))
    os.environ.pop("LYRICFORGE_REQUIRE_AUTH", None)  # Local-only mode
    home.mkdir(parents=True, exist_ok=True)
    # --windowed builds have no console streams; log errors instead of hiding them.
    if sys.stdout is None or sys.stderr is None:
        log_dir = home / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = open(log_dir / "desktop.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = log
        sys.stderr = log
    return home


def native_error(message: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "SkellyMotion", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def check_subtitle_renderer() -> None:
    """Actually render ASS into H.264; do not parse ffmpeg's filters listing."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe were not included in the app.")
    with tempfile.TemporaryDirectory(prefix="lyricforge-check-") as temp:
        root = Path(temp)
        ass = """[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 180
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,30,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,5,10,10,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:00.40,Main,,0,0,0,,SkellyMotion
"""
        (root / "check.ass").write_text(ass, encoding="utf-8-sig")
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=0.3",
            "-vf", "ass=check.ass", "-frames:v", "3", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "check.mp4"], cwd=root,
            capture_output=True, text=True, timeout=45)
        if result.returncode or not (root / "check.mp4").exists():
            raise RuntimeError("FFmpeg cannot render lyrics: " + result.stderr[-500:])


def self_test() -> int:
    import server
    assert server.STATIC.joinpath("index.html").is_file(), "Missing editor assets"
    check_subtitle_renderer()
    print("SkellyMotion portable self-test passed")
    return 0


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(port: int, server_thread: threading.Thread, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not server_thread.is_alive():
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.12)
    return False


def run_desktop(home: Path) -> int:
    import uvicorn
    import server
    import webview

    port = available_port()
    config = uvicorn.Config(server.app, host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    api_server = uvicorn.Server(config)
    worker = threading.Thread(target=api_server.run, name="LyricForgeAPI", daemon=True)
    worker.start()
    if not wait_until_ready(port, worker):
        raise RuntimeError("The local editor server did not start. See desktop.log in " + str(home / "logs"))

    try:
        webview.create_window("SkellyMotion | Lyric video studio",
                              "http://127.0.0.1:" + str(port),
                              width=1280, height=830, min_size=(980, 650),
                              resizable=True, background_color="#090c0c")
        webview.start(gui="edgechromium", debug=False, private_mode=False,
                      storage_path=str(home / "webview"))
    finally:
        api_server.should_exit = True
        worker.join(timeout=5)
    return 0


def main() -> int:
    freeze_support()
    home = configure()
    if "--version" in sys.argv:
        print("SkellyMotion 0.3.0")
        return 0
    if "--self-test" in sys.argv:
        return self_test()
    try:
        return run_desktop(home)
    except Exception as exc:
        print("Desktop startup error:", repr(exc), file=sys.stderr)
        native_error(
            "LYRICFORGE couldn't open its desktop window.\n\n"
            + str(exc) + "\n\n"
            "Install Microsoft Edge WebView2 Runtime if needed.\n"
            "For details see: " + str(home / "logs" / "desktop.log")
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
