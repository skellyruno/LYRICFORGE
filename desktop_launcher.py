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
        child_flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=0.3",
            "-vf", "ass=check.ass", "-frames:v", "3", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "check.mp4"], cwd=root,
            capture_output=True, text=True, timeout=45, **child_flags)
        if result.returncode or not (root / "check.mp4").exists():
            raise RuntimeError("FFmpeg cannot render lyrics: " + result.stderr[-500:])


def self_test() -> int:
    import server
    assert server.STATIC.joinpath("index.html").is_file(), "Missing editor assets"
    check_subtitle_renderer()
    print("SkellyMotion portable self-test passed")
    return 0


def bundled_python_runtime() -> Path:
    """Exact bundled .NET assembly used by pythonnet's Windows desktop bridge."""
    return runtime_dir() / "pythonnet" / "runtime" / "Python.Runtime.dll"


def native_runtime_self_test() -> int:
    """Actually initialize Python.NET, which the FFmpeg-only smoke test skipped."""
    assembly = bundled_python_runtime()
    if getattr(sys, "frozen", False) and not assembly.is_file():
        raise RuntimeError("Missing packaged Python.NET runtime DLL: " + str(assembly))
    import clr  # noqa: F401  # Deliberately initialize the WinForms .NET bridge.
    from System import Environment
    if not Environment.Version:
        raise RuntimeError("The .NET bridge did not initialize correctly")
    print("SkellyMotion native Python.NET self-test passed")
    return 0


def offer_download_marker_repair() -> bool:
    """Ask before unblocking exactly the bundled pythonnet DLL, never a folder.

    Windows Explorer may propagate the ZIP's Mark-of-the-Web to extracted
    assemblies. Python.NET cannot initialize a .NET assembly with that marker
    on some Windows configurations. Do not remove download markers silently.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    dll = bundled_python_runtime()
    if not dll.is_file():
        return False
    marker = str(dll) + ":Zone.Identifier"
    try:
        with open(marker, "r", encoding="utf-8", errors="replace") as stream:
            zone = stream.read(1024)
    except OSError:
        return False
    if "ZoneId=3" not in zone and "ZoneId=4" not in zone:
        return False
    import ctypes
    response = ctypes.windll.user32.MessageBoxW(
        None,
        "Windows marked SkellyMotion's bundled Python.Runtime.dll as a "
        "downloaded file. This may prevent the native window from opening.\n\n"
        "Only continue if you downloaded SkellyMotion from your trusted "
        "GitHub repository.\n\n"
        "Remove the download block from this ONE DLL and continue?",
        "SkellyMotion - Windows DLL download block",
        0x04 | 0x30,  # MB_YESNO | MB_ICONWARNING
    )
    if response != 6:  # IDYES
        return False
    try:
        os.remove(marker)
        print("Removed the user-approved download marker on bundled Python.Runtime.dll",
              file=sys.stderr)
        return True
    except OSError as exc:
        print("Could not unblock bundled Python.Runtime.dll:", exc, file=sys.stderr)
        return False


def desktop_runtime_error(exc: Exception) -> str:
    details = str(exc)
    if "Python.Runtime.Loader.Initialize" not in details and "Python.Runtime.dll" not in details:
        return (
            "SkellyMotion couldn't open its desktop window.\n\n" + details +
            "\n\nIf necessary, install Microsoft Edge WebView2 Runtime.\n"
        )

    assembly = bundled_python_runtime()
    location = str(assembly)
    if assembly.is_file():
        presence = "The packaged Python.Runtime.dll exists but did not load."
    else:
        presence = "The packaged Python.Runtime.dll is MISSING; download a fresh complete build."
    return (
        "SkellyMotion's Windows Python.NET bridge could not start.\n\n"
        + presence + "\n\n"
        "If you trust this GitHub download, find Python.Runtime.dll in:\n"
        + location + "\n"
        "Right-click it > Properties > Unblock (if shown).\n"
        "Or run Repair-SkellyMotion.cmd beside SkellyMotion.exe.\n\n"
        "If the DLL is not blocked, check .NET Framework 4.6.2+ and the app log.\n"
    )


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



class DesktopFilePicker:
    """Native dialogs for the desktop only. The web site never receives file paths."""

    def __init__(self):
        self.window = None

    def _open_file(self, formats):
        import webview
        if self.window is None:
            raise RuntimeError("The SkellyMotion desktop window is not ready")
        # pywebview v5/v6 use FileDialog.OPEN; support older OPEN_DIALOG too.
        dialog = getattr(getattr(webview, "FileDialog", None), "OPEN",
                         getattr(webview, "OPEN_DIALOG", 10))
        picked = self.window.create_file_dialog(
            dialog_type=dialog, allow_multiple=False, file_types=(formats,))
        return Path(picked[0]) if picked else None

    def choose_audio(self, recognition="balanced", language="auto",
                     vocabulary="", performance_mode="balanced"):
        source = self._open_file(
            "Music files (*.mp3;*.wav;*.flac;*.m4a;*.aac;*.ogg;*.opus;*.mp4;*.webm)")
        if source is None:
            return None
        import server
        return server.import_desktop_audio_file(source, recognition, language,
                                                vocabulary, performance_mode)

    def choose_background(self, project_id):
        if not isinstance(project_id, str):
            raise ValueError("Choose a song before importing a background")
        source = self._open_file(
            "Images and video (*.jpg;*.jpeg;*.png;*.webp;*.mp4;*.mov;*.webm)")
        if source is None:
            return None
        import server
        return server.import_desktop_background_file(project_id, source)


def run_desktop(home: Path) -> int:
    started = time.monotonic()

    def log_stage(stage: str) -> None:
        # Startup diagnostics let us distinguish Python import delay from
        # WebView2 initialization or project-level media loading.
        print(f"[startup] {stage}: {time.monotonic() - started:.2f}s",
              file=sys.stderr, flush=True)

    log_stage("begin")
    if offer_download_marker_repair():
        log_stage("user approved bundled CLR DLL download-marker repair")
    import uvicorn
    log_stage("uvicorn imported")
    import server
    log_stage("local API loaded (Whisper model remains lazy)")
    import webview
    log_stage("native WebView module imported")

    port = available_port()
    config = uvicorn.Config(server.app, host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    api_server = uvicorn.Server(config)
    worker = threading.Thread(target=api_server.run, name="SkellyMotionAPI", daemon=True)
    worker.start()
    if not wait_until_ready(port, worker):
        raise RuntimeError("The local editor server did not start. See desktop.log in " + str(home / "logs"))
    log_stage("API accepting connections")

    try:
        picker = DesktopFilePicker()
        window = webview.create_window("SkellyMotion | Lyric video studio",
                              "http://127.0.0.1:" + str(port) + "/?desktop=1",
                              # 25% smaller default window; user can resize/maximize freely.
                              width=960, height=623, min_size=(800, 520),
                              resizable=True, background_color="#090c0c",
                              js_api=picker)
        picker.window = window
        log_stage("native window created; initializing WebView2")
        webview.start(gui="edgechromium", debug=False, private_mode=False,
                      storage_path=str(home / "webview"))
    finally:
        log_stage("native window closed or initialization ended")
        api_server.should_exit = True
        worker.join(timeout=5)
    return 0


def main() -> int:
    freeze_support()
    home = configure()
    if "--version" in sys.argv:
        print("SkellyMotion 0.8.2")
        return 0
    if "--self-test" in sys.argv:
        return self_test()
    if "--native-self-test" in sys.argv:
        try:
            return native_runtime_self_test()
        except Exception as exc:
            print("Native Python.NET smoke test failed: " + repr(exc), file=sys.stderr)
            return 2
    try:
        return run_desktop(home)
    except Exception as exc:
        print("Desktop startup error:", repr(exc), file=sys.stderr)
        native_error(
            desktop_runtime_error(exc)
            + "\nFor details see: " + str(home / "logs" / "desktop.log")
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
