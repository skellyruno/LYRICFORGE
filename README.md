# SkellyMotion — AI lyric video studio

**Upload a song → AI transcript → review & confirm lyrics → adjust timing → style, animate and change backgrounds → export a synced MP4.**

Two distributions are included in this repository:

| | Online studio | Windows portable app |
|---|---|---|
| Code | `server.py`, `static/` | Same app, in a native WebView2 window via PyInstaller |
| Runs on | Railway Docker deployment | Windows x64, localhost only |
| Login | Owner-only password over HTTPS | None, binds to `127.0.0.1` |
| Storage | Persistent `/data` volume | `%LOCALAPPDATA%/LyricForge` |
| Release | Railway deploys commits from GitHub | GitHub Actions ZIP; version tags publish Releases |

## Getting started

**[Complete GitHub + Railway + Windows setup](docs/DEPLOY.md)** — follow this step-by-step guide to publish both versions.

## Editing features

- MP3/WAV/M4A/FLAC etc. imports (max 250 MB, 15 minutes)
- Automatic speech-to-text lyrics using faster-whisper, with approximate word timestamps
- Explicit review and confirm step before video creation
- Editable lyric clips and timing, with waveform timeline
- Full line / per-word / karaoke lyric display
- Pop, fade, slide and typewriter effects
- Fonts, colors, size, outline, text position, backgrounds and portrait/square/landscape
- 720p / 1080p MP4 video output via FFmpeg

**Limitations:** Whisper is not specialized for sung vocals, and corrected words are interpolated rather than audio-forced-aligned; some timing will need manual tweaks. The cloud site is **owner-only**. It has no multi-user accounts, rate limiting, queue persistence, billing or production-grade untrusted-media sandbox. Windows packaging is automated but must be verified on a Windows machine.


## SkellyMotion Windows desktop studio (v0.3)

The latest **SkellyMotion.exe** portable build opens **its own Windows application window** with no Command Prompt and no external browser tab. It uses the system's Microsoft Edge WebView2 runtime and keeps the backend on a random loopback-only port. If WebView2 is unavailable, install the [Microsoft WebView2 Evergreen Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/).

**Existing projects and model files are retained:** `%LOCALAPPDATA%\LyricForge\workspace` and `%LOCALAPPDATA%\LyricForge\models`. The Whisper model default is still **small**; it is not re-downloaded just because the desktop interface changed.

New features: one-click Neon, Minimal, Dream and Bold looks; Zoom, Bounce and Blur Reveal lyric animations; ±0.05-second timing nudge and Alt+Left/Right shortcuts; Ctrl+S save; an optional Storage panel that removes only explicitly confirmed *old* render intermediates and MP4 exports. Songs, lyric edits, backgrounds, the open project's export and model cache are never selected for cleanup.

Exports now trim overlapping caption events and omit accidental caption flashes shorter than 0.1 seconds. This reduces artifacts from ASR timings while leaving the project's editable original timing data untouched. In rare cases very short deliberate lyrics may need manual retiming.

To get the upgraded application, open the **Build Windows portable app** workflow in GitHub Actions, run it on `main`, download the **SkellyMotion-Windows-x64** artifact and extract the entire folder. You can keep your old executable as a fallback while testing. Windows builds must still be verified on GitHub's runner.

## Rebrand compatibility

The product is now named **SkellyMotion**. The GitHub repository remains `skellyruno/LYRICFORGE` to avoid breaking existing links, GitHub integrations and deployments. The on-disk folders `%LOCALAPPDATA%\\LyricForge\\workspace` and `%LOCALAPPDATA%\\LyricForge\\models`, existing `LYRICFORGE_*` environment variables and browser project key `lyricforge-last` intentionally retain their names for backwards compatibility. **Do not rename or delete these folders** to apply the new branding.

The existing architecture already supports a hosted browser editor and a self-contained Windows window sharing the same backend. A mobile app is a future option, not part of this release.

## Local development

Install Python 3.11 or 3.12 and FFmpeg (including libass), then:

```bash
python -m pip install -r requirements.txt pytest httpx
python -m pytest tests -q
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Visit `http://127.0.0.1:8000`. On Windows you can also run `RUN-WINDOWS.bat` (requires preinstalled Python and FFmpeg).

> Never put your own song files, API keys or passwords into the GitHub repository. The `.gitignore` omits private media, local project storage, the AI model cache and `.env` files.
