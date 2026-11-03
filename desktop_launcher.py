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
    """The CLR bridge assembly that pythonnet loads."""
    return runtime_dir() / "pythonnet" / "runtime" / "Python.Runtime.dll"


# Narrow allowlist: only the managed assemblies SkellyMotion ships for its
# Python.NET / WebView2 window. Never touch every DLL or an entire folder.
MANAGED_UI_DLL_PATHS = (
    ("pythonnet", "runtime", "Python.Runtime.dll"),
    ("webview", "lib", "Microsoft.Web.WebView2.Core.dll"),
    ("webview", "lib", "Microsoft.Web.WebView2.WinForms.dll"),
    ("webview", "lib", "Microsoft.Web.WebView2.Wpf.dll"),
)


def bundled_managed_assemblies() -> list[Path]:
    root = runtime_dir().resolve()
    result = []
    for pieces in MANAGED_UI_DLL_PATHS:
        dll = root.joinpath(*pieces)
        # Don't follow a symlink to an untrusted location.
        if (dll.is_file() and not dll.is_symlink()
                and dll.resolve().is_relative_to(root)):
            result.append(dll)
    return result


def blocked_managed_assemblies() -> list[Path]:
    """Read Windows Mark-of-the-Web ADS on the exact bundled DLL allowlist."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return []
    marked = []
    for dll in bundled_managed_assemblies():
        try:
            with open(str(dll) + ":Zone.Identifier", "r",
                      encoding="utf-8", errors="replace") as stream:
                marker = stream.read(1024)
        except OSError:
            continue
        if any(token in marker for token in ("ZoneId=3", "ZoneId=4")):
            marked.append(dll)
    return marked


def native_runtime_self_test() -> int:
    """Smoke-test the EXACT .NET assemblies used by the native Windows editor.

    The previous test imported clr alone, allowing a working Python.NET loader
    but a broken/blocked Microsoft.Web.WebView2.Core.dll to slip through.
    """
    python_runtime = bundled_python_runtime()
    if getattr(sys, "frozen", False) and not python_runtime.is_file():
        raise RuntimeError("Missing Python.NET runtime: " + str(python_runtime))
    import clr
    from System import Environment
    if not Environment.Version:
        raise RuntimeError("The .NET bridge did not initialize")
    if getattr(sys, "frozen", False):
        root = runtime_dir()
        for name in ("Microsoft.Web.WebView2.Core.dll",
                     "Microsoft.Web.WebView2.WinForms.dll"):
            path = root / "webview" / "lib" / name
            if not path.is_file():
                raise RuntimeError("Missing bundled WebView2 managed assembly: " + str(path))
            # Load using the same full-path assembly resolution as pywebview.
            clr.AddReference(str(path))
            print("Verified native .NET assembly: " + name, flush=True)
    print("SkellyMotion Python.NET + WebView2 assembly self-test passed")
    return 0


def native_notice(message: str, error: bool = False) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, message, "SkellyMotion - Windows runtime repair",
            0x10 if error else 0x40)
    except Exception:
        print(message, file=sys.stderr)


def offer_download_marker_repair() -> bool:
    """Offer one explicitly approved, narrowly scoped UI-DLL repair.

    Windows Explorer may propagate Mark-of-the-Web from the downloaded ZIP to
    multiple bundled .NET assemblies. Unblocking only Python.Runtime.dll then
    exposes a second 0x80131515 failure in Microsoft.Web.WebView2.Core.dll.
    """
    marked = blocked_managed_assemblies()
    if not marked:
        return False
    import ctypes
    names = "\n".join("  - " + item.name for item in marked)
    response = ctypes.windll.user32.MessageBoxW(
        None,
        "Windows marked these SkellyMotion UI libraries as downloaded:\n\n"
        + names
        + "\n\nOnly continue if this build came from your trusted "
          "SkellyMotion GitHub repository.\n\n"
          "Remove the Windows download markers from these "
          + str(len(marked)) + " files ONLY and continue?",
        "SkellyMotion - Repair blocked UI libraries",
        0x04 | 0x30,  # MB_YESNO | MB_ICONWARNING
    )
    if response != 6:  # IDYES
        print("User declined downloaded-DLL repair", file=sys.stderr)
        return False
    repaired = []
    for dll in marked:
        try:
            # Only deletes the file's Zone.Identifier alternate data stream,
            # NOT the DLL. The rest of Windows attachment protection remains.
            os.remove(str(dll) + ":Zone.Identifier")
            repaired.append(dll.name)
        except OSError as exc:
            print("Could not remove download marker from", dll.name, ":", exc,
                  file=sys.stderr)
    if repaired:
        print("User approved unblocking bundled UI DLLs:", ", ".join(repaired),
              file=sys.stderr)
    return len(repaired) == len(marked)


def desktop_runtime_error(exc: Exception) -> str:
    details = str(exc)
    if (any(token in details for token in
            ("0x80131515", "network location", "Microsoft.Web.WebView2",
             "Python.Runtime.Loader.Initialize", "Python.Runtime.dll"))):
        return (
            "SkellyMotion could not load one of its bundled .NET UI libraries.\n\n"
            "This can happen when Windows marks DLLs extracted from a download "
            "as untrusted, or when the app was not extracted completely.\n\n"
            "If you trust the GitHub build, run Repair-SkellyMotion.cmd "
            "beside SkellyMotion.exe to check the Python.NET and WebView2 "
            "UI DLLs. The repair asks before changing any download markers.\n\n"
            "Alternatively: right-click the downloaded ZIP > Properties > "
            "Unblock (if shown), then extract the ZIP again into a new folder.\n\n"
            "Details: " + details[:900]
        )
    return (
        "SkellyMotion couldn't open its desktop window.\n\n" + details[:900]
        + "\n\nCheck the desktop.log file. Install Microsoft Edge WebView2 "
          "Runtime only if the log indicates that WebView2 itself is missing."
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
        self.active_project = False
        self.allow_close = False
        self._saving_video = threading.Lock()

    def session_active(self, active):
        self.active_project = bool(active)
        return {"active": self.active_project}

    def approve_close(self):
        self.allow_close = True
        if self.window is not None:
            self.window.destroy()
        return True

    def save_video(self, project_id, preview=False):
        """Native Save As copies the MP4; it does not navigate the WebView.

        The no-wait lock prevents double-clicks from launching multiple huge
        simultaneous downloads and makes cancellation a no-op.
        """
        if not self._saving_video.acquire(blocking=False):
            return {"status": "busy"}
        try:
            import webview
            import server
            import re
            project = server.read_project(project_id)
            source = server.project_dir(project_id) / (
                "lyric_preview.mp4" if bool(preview) else "lyric_video.mp4")
            if not source.is_file() or source.stat().st_size < 1024:
                raise RuntimeError("The MP4 has not finished rendering yet.")
            title = re.sub(r"[^\w .()-]", "_", str(project.get("title") or "video"))[:55].strip(" .")
            filename = ("SkellyMotion-" + (title or "video") +
                        ("-preview" if preview else "") + ".mp4")
            dialog = getattr(getattr(webview, "FileDialog", None), "SAVE",
                             getattr(webview, "SAVE_DIALOG", 20))
            picked = self.window.create_file_dialog(
                dialog_type=dialog, save_filename=filename,
                file_types=("MP4 video (*.mp4)",))
            if not picked:
                return {"status": "cancelled"}
            target = Path(picked[0])
            if target.suffix.lower() != ".mp4":
                target = target.with_suffix(".mp4")
            if source.resolve() == target.resolve():
                return {"status": "saved", "path": str(target)}
            # Atomic replacement avoids leaving a partial copy if interrupted.
            temporary = target.with_name(target.name + ".part")
            try:
                with source.open("rb") as inp, temporary.open("wb") as out:
                    shutil.copyfileobj(inp, out, 1024 * 1024)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return {"status": "saved", "path": str(target)}
        finally:
            self._saving_video.release()

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


def run_desktop(home: Path, safe_mode: bool = False,
                smoke_test: bool = False) -> int:
    started = time.monotonic()
    if safe_mode:
        # Opt-in diagnostic only. Normal WebView2 keeps GPU acceleration.
        flags = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            flags + " --disable-gpu --disable-gpu-compositing").strip()
    profile = home / ("webview_safe" if safe_mode else "webview")
    profile.mkdir(parents=True, exist_ok=True)

    def log_stage(stage: str) -> None:
        # Startup diagnostics let us distinguish Python import delay from
        # WebView2 initialization or project-level media loading.
        print(f"[startup] {stage}: {time.monotonic() - started:.2f}s",
              file=sys.stderr, flush=True)

    log_stage("begin" + (" (safe WebView2 profile, software rendering)" if safe_mode else ""))
    log_stage("user data folder: " + str(profile))
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

    smoke_loaded = threading.Event()
    watchdog = None
    if smoke_test:
        # The packaged GUI must open, render and exit cleanly in CI.
        # A blocked native window cannot stall GitHub Actions indefinitely.
        def expired():
            print("[window-smoke] TIMEOUT: editor window did not close",
                  file=sys.stderr, flush=True)
            os._exit(4)
        watchdog = threading.Timer(35, expired)
        watchdog.daemon = True
        watchdog.start()

    try:
        picker = DesktopFilePicker()
        window = webview.create_window("SkellyMotion | Lyric video studio",
                              "http://127.0.0.1:" + str(port) + "/?desktop=1",
                              # 25% smaller default window; user can resize/maximize freely.
                              width=960, height=623, min_size=(800, 520),
                              resizable=True, background_color="#090c0c",
                              js_api=picker)
        picker.window = window
        try:
            def on_closing():
                # Never block the native UI thread waiting for JavaScript.
                if picker.allow_close or smoke_test or not picker.active_project:
                    return True
                def request_decision():
                    try:
                        window.evaluate_js(
                            "window.dispatchEvent(new Event('skellymotion-close-request'))")
                    except Exception as exc:
                        log_stage("Could not show Save / Don't Save / Cancel: " + str(exc))
                threading.Thread(target=request_decision, daemon=True).start()
                return False
            window.events.closing += on_closing
            window.events.shown += lambda: log_stage("native window shown")
            def on_loaded():
                log_stage("editor document loaded")
                if smoke_test and not smoke_loaded.is_set():
                    smoke_loaded.set()
                    def check_window_and_close():
                        # A real Windows UI thread that stops processing OS
                        # messages is marked Not Responding by IsHungAppWindow.
                        import ctypes
                        if os.name == "nt":
                            hwnd = ctypes.windll.user32.FindWindowW(
                                None, "SkellyMotion | Lyric video studio")
                            if hwnd and ctypes.windll.user32.IsHungAppWindow(hwnd):
                                print("[window-smoke] WinForms window is NOT RESPONDING",
                                      file=sys.stderr, flush=True)
                                os._exit(5)
                        log_stage("editor window remained responsive during smoke test")
                        window.destroy()
                    timer = threading.Timer(4, check_window_and_close)
                    timer.daemon = True
                    timer.start()
            window.events.loaded += on_loaded
        except (AttributeError, TypeError) as exc:
            log_stage("window event hooks unavailable: " + str(exc))
        log_stage("native window created; initializing WebView2")
        webview.start(gui="edgechromium", debug=False, private_mode=False,
                      storage_path=str(profile))
    finally:
        if watchdog is not None:
            watchdog.cancel()
        log_stage("native window closed or initialization ended")
        api_server.should_exit = True
        worker.join(timeout=5)
    if smoke_test and not smoke_loaded.is_set():
        raise RuntimeError("Packaged WebView2 editor never finished loading")
    return 0



def run_browser_mode(home: Path) -> int:
    """Use the same local studio without Python.NET/WebView2 window hosting.

    Fallback is intentionally user-initiated. The visible exit dialog keeps
    the local API alive and lets the user shut it down cleanly.
    """
    import uvicorn
    import server
    import webbrowser
    port = available_port()
    config = uvicorn.Config(server.app, host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, name="SkellyMotionBrowserAPI",
                              daemon=True)
    thread.start()
    try:
        if not wait_until_ready(port, thread):
            raise RuntimeError("The local editor server could not start")
        address = "http://127.0.0.1:" + str(port) + "/"
        print("[browser-fallback] local editor at " + address, file=sys.stderr,
              flush=True)
        opened = webbrowser.open(address, new=1)
        if not opened:
            print("[browser-fallback] The default browser did not confirm opening",
                  file=sys.stderr, flush=True)
        native_notice(
            "SkellyMotion is running in your default browser.\n\n"
            "Use the browser tab to edit your lyric videos. Your songs and AI "
            "model are unchanged.\n\n"
            "When you finish, close the browser tab and click OK here to stop "
            "the local SkellyMotion server."
        )
    finally:
        instance.should_exit = True
        thread.join(timeout=5)
    return 0

def main() -> int:
    freeze_support()
    home = configure()
    if "--version" in sys.argv:
        print("SkellyMotion 0.8.3")
        return 0
    if "--self-test" in sys.argv:
        return self_test()
    if "--native-self-test" in sys.argv:
        try:
            return native_runtime_self_test()
        except Exception as exc:
            print("Native Python.NET/WebView2 self-test failed: " + repr(exc), file=sys.stderr)
            return 2
    if "--repair-runtime" in sys.argv:
        if not blocked_managed_assemblies():
            native_notice("No Windows download blocks were found on the bundled UI DLLs.\n"
                          "See desktop.log for other startup errors.")
            return 0
        if offer_download_marker_repair():
            native_notice("The selected SkellyMotion UI DLLs were unblocked.\n"
                          "Please relaunch SkellyMotion.exe.")
            return 0
        native_notice("Runtime repair was declined or could not complete.\n"
                      "No other files were modified.", error=True)
        return 3
    try:
        if "--browser-mode" in sys.argv:
            return run_browser_mode(home)
        return run_desktop(home, safe_mode="--safe-mode" in sys.argv,
                           smoke_test="--window-self-test" in sys.argv)
    except Exception as exc:
        print("Desktop startup error:", repr(exc), file=sys.stderr)
        native_error(
            desktop_runtime_error(exc)
            + "\nFor details see: " + str(home / "logs" / "desktop.log")
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
