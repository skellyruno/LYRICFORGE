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



## SkellyMotion 0.5 — editing workspace upgrade

This version builds on the working v0.4 desktop app. **It does not change the Whisper model, song data, saved projects, or AI cache paths.** The current Windows executable still needs to be rebuilt from GitHub Actions.

### Easier editing

- **Undo/redo** for lyric text, clip timings, splitting, deleting, duplicating, nudging, and style settings, with bounded 60-step history. Native text-field undo still works while typing.
- **Clip tools** for splitting a selected lyric at the playhead (or its midpoint), duplicating it, deleting it, and moving it ±0.05 seconds.
- **Timeline controls** for 0.1-second snap-to-grid, previous/next clip navigation, zoom in/out, and Fit.
- **Adjustable workspace**: drag the vertical divider to resize the settings panel or the horizontal divider above the timeline to give the waveform more space. Double-click either divider to reset. Panel dimensions are remembered locally.
- **Keyboard shortcuts**: Space play, Ctrl+Z undo, Ctrl+Y/Ctrl+Shift+Z redo, Ctrl+D duplicate, S split, Delete remove, N snap, ↑/↓ move between clips, Alt+←/→ nudge, Ctrl+S save and ? help.
- **Style memory**: save your current typography/motion as a personal look, apply it to another song or reset to default. Personal looks are stored in that computer's webview/browser profile (they do not replace project settings).
- **SRT subtitle export** without needing to render an MP4.
- **Projects library**: revisit previously saved songs, with duration, status and most recent modification date. This is read-only listing; it does not delete files. When switching, the editor attempts to save your current work first.
- **Safer autosave**: serialized project writes, with Unsaved changes → Saving → Saved/Save failed feedback. The program avoids repeated waveform redraws while adjusting clips and records drag operations as one undoable action.

### Compatibility and verification

- Windows portable remains a native WebView2 GUI named \`SkellyMotion.exe\`.
- Default window remains **960 × 623** with adjustable window and editor panel sizes.
- The actual AI model remains **Whisper \`small\`** with \`SKELLYMOTION_BEAM_SIZE=3\` (or set 5 for more thorough decoding).
- The project folder is still \`%LOCALAPPDATA%\LyricForge\workspace\`, and model cache is still \`%LOCALAPPDATA%\LyricForge\models\`. **Do not delete or rename these folders.**
- The Windows and Linux CI test workflows now run \`node tests/editor_smoke.mjs\`, a zero-dependency runtime smoke test for editing controls and layout, along with existing Python backend tests. Real Windows native-window and MP4 testing must be confirmed on the newly built executable.

To download: GitHub **Actions → Build SkellyMotion Windows app → Run workflow** on \`main\`, then download and extract \`SkellyMotion-Windows-x64\` from the completed run's **Artifacts**. Keep your previous working folder until the new build has been tested.

## SkellyMotion 0.4 — compact, smoother studio

- Windows starts at **960 × 623** pixels (25% smaller in each dimension than the old 1280 × 830 default), can resize down to 800 × 520, and retains its native WebView2 window.
- The desktop UI retains its existing 65%-of-original visual size. A viewport-anchored scale and flexible panels replace the old CSS zoom technique for reliable resize, scrolling, and preview layout.
- Transcription **still uses the exact same Whisper `small` model and existing model cache**. The CPU default now uses beam size 3 (previously 5), one temperature pass, and leaves some CPU headroom for the interface. This reduces decoding work but could affect recognition of difficult singing.
- If you prefer the prior more thorough decoding, set environment variable `SKELLYMOTION_BEAM_SIZE=5` before starting the app. This changes **decoding effort only**, not the model or saved lyrics.
- The review screen reports real audio-position analysis progress; it does not estimate remaining minutes.
- Waveform generation starts after lyric confirmation rather than competing with transcription. The preview paints at up to 30 FPS while playing, about 12 FPS while idle, and about 4 FPS when covered by dialogs. Timeline clips are updated directly while dragging; font and position sliders avoid unnecessary full-panel resets.
- Projects, audio files and Whisper cache still use the original `%LOCALAPPDATA%\LyricForge` paths.

To test the new Windows build, visit **Actions → Build SkellyMotion Windows app → Run workflow** on `main`, download the new `SkellyMotion-Windows-x64` artifact, and extract the whole folder. Keep the old working version until import, editing, and MP4 export pass on your computer.

## SkellyMotion Windows desktop studio (v0.3)

The latest **SkellyMotion.exe** portable build opens **its own Windows application window** with no Command Prompt and no external browser tab. It uses the system's Microsoft Edge WebView2 runtime and keeps the backend on a random loopback-only port. If WebView2 is unavailable, install the [Microsoft WebView2 Evergreen Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/).

**Existing projects and model files are retained:** `%LOCALAPPDATA%\LyricForge\workspace` and `%LOCALAPPDATA%\LyricForge\models`. The Whisper model default is still **small**; it is not re-downloaded just because the desktop interface changed.

New features: one-click Neon, Minimal, Dream and Bold looks; Zoom, Bounce and Blur Reveal lyric animations; ±0.05-second timing nudge and Alt+Left/Right shortcuts; Ctrl+S save; an optional Storage panel that removes only explicitly confirmed *old* render intermediates and MP4 exports. Songs, lyric edits, backgrounds, the open project's export and model cache are never selected for cleanup.

Exports now trim overlapping caption events and omit accidental caption flashes shorter than 0.1 seconds. This reduces artifacts from ASR timings while leaving the project's editable original timing data untouched. In rare cases very short deliberate lyrics may need manual retiming.

To get the upgraded application, open the **Build Windows portable app** workflow in GitHub Actions, run it on `main`, download the **SkellyMotion-Windows-x64** artifact and extract the entire folder. You can keep your old executable as a fallback while testing. Windows builds must still be verified on GitHub's runner.

## Rebrand compatibility

The product is now named **SkellyMotion**. The GitHub repository remains `skellyruno/LYRICFORGE` to avoid breaking existing links, GitHub integrations and deployments. The on-disk folders `%LOCALAPPDATA%\\LyricForge\\workspace` and `%LOCALAPPDATA%\\LyricForge\\models`, existing `LYRICFORGE_*` environment variables and browser project key `lyricforge-last` intentionally retain their names for backwards compatibility. **Do not rename or delete these folders** to apply the new branding.

The existing architecture already supports a hosted browser editor and a self-contained Windows window sharing the same backend. A mobile app is a future option, not part of this release.


## Windows UI and file picker repair

The SkellyMotion Windows editor now starts in **compact desktop mode**, approximately 35% smaller than the previous Windows layout. High-DPI window sizing is handled together for the header, side panels, video preview, timeline and welcome screen rather than only scaling fonts. The hosted browser editor keeps its independent responsive styling.

The Windows **Upload song** and **Upload background** buttons use a native file dialog through the pywebview bridge. The website retains normal browser file inputs and drag/drop. No HTTP endpoint accepting arbitrary local paths was added. A JavaScript selector bug that prevented the editor from attaching click handlers has been fixed, with tests that check the initialization wiring.

This is a source-code fix: **rebuild from GitHub Actions** to use it. Your old `SkellyMotion.exe` will not update itself. Back up any exported videos before deleting old ZIPs, and keep your existing `%LOCALAPPDATA%\LyricForge\workspace` and `models` folders. The original Whisper `small` model is unchanged.

## Local development

Install Python 3.11 or 3.12 and FFmpeg (including libass), then:

```bash
python -m pip install -r requirements.txt pytest httpx
python -m pytest tests -q
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Visit `http://127.0.0.1:8000`. On Windows you can also run `RUN-WINDOWS.bat` (requires preinstalled Python and FFmpeg).

> Never put your own song files, API keys or passwords into the GitHub repository. The `.gitignore` omits private media, local project storage, the AI model cache and `.env` files.
