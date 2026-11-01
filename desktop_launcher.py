"""Portable Windows entry point; built into LyricForge.exe by GitHub Actions."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from multiprocessing import freeze_support


def runtime_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def configure() -> None:
    root = runtime_dir()
    bundled_tools = root / "tools"
    if bundled_tools.exists():
        os.environ["PATH"] = str(bundled_tools) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("LYRICFORGE_DATA", str(
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LyricForge" / "workspace"
    ))
    os.environ.setdefault("HF_HOME", str(
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LyricForge" / "models"
    ))
    # Do not accidentally inherit owner-only web mode when running offline.
    os.environ.pop("LYRICFORGE_REQUIRE_AUTH", None)


def self_test() -> int:
    import server
    assert server.STATIC.joinpath("index.html").is_file(), "Missing static/index.html"
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        assert path, f"{tool} not included"
        subprocess.run([path, "-version"], check=True, stdout=subprocess.DEVNULL)
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], check=True,
                             capture_output=True, text=True).stdout
    assert " ass " in filters or " ass\n" in filters or " ass        " in filters, "FFmpeg needs the ass subtitle filter"
    print("LYRICFORGE portable self-test passed")
    return 0


def open_when_ready(host: str, port: int) -> None:
    for _ in range(100):
        try:
            with socket.create_connection((host, port), timeout=0.3):
                webbrowser.open(f"http://{host}:{port}")
                return
        except OSError:
            time.sleep(0.2)


def main() -> int:
    freeze_support()
    configure()
    if "--version" in sys.argv:
        print("LYRICFORGE 0.2.0")
        return 0
    if "--self-test" in sys.argv:
        return self_test()
    import server
    import uvicorn
    host, port = "127.0.0.1", 8000
    threading.Thread(target=open_when_ready, args=(host, port), daemon=True).start()
    print(f"LYRICFORGE is running at http://{host}:{port}")
    print("Close this window to shut down the editor.")
    uvicorn.run(server.app, host=host, port=port, log_level="info", workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
