# SkellyMotion — AI lyric video studio

**Upload a song → AI transcript → review & confirm lyrics → adjust timing → style, animate and change backgrounds → export a synced MP4.**

## SkellyMotion — native startup and waveform hardening

Windows build logs previously showed pywebview recursively walking the public `DesktopFilePicker.window.native` object until Python's recursion limit was reached. The WinForms window is now stored privately as `_window`; all intended JavaScript bridge methods, Save As, and close actions remain available. The Windows smoke test rejects any recurrence of that exception.

Editor preview now uses the correct global/default lyric placement and 230 ms animation duration. Word-only captions disappear in intentional gaps instead of flashing earlier words. The waveform display rejects NaN/Inf/denormal samples, processes every decoded sample including song tails, and atomically refreshes invalid/contended caches. A real WAV-to-AAC MP4 test verifies finite audio, duration and RMS preservation; it does not modify the source audio or master it.

## SkellyMotion 0.9 — precision editor and reliability update

This update preserves the existing Whisper model, project manifests, WebView2 desktop launcher, saved-project workflows and H.264 export pipeline.

- **Precise lyric timing:** select a clip in Lyrics, edit each word's IN/OUT time in the Word Timing strip, or press its ▶ control to audition the song at that word. Times are retained in saved project data and honored in karaoke/word exports.
- **Word Pulse:** select the Pulse animation globally or per clip. Pulse follows the existing/transcript or manually adjusted **word boundaries** in the live preview and exported ASS subtitles. It does **not** detect musical beats and is **not** a new acoustic forced aligner.
- **Design:** two new backgrounds (Sunset and Arctic), Cinema and Ice style presets, three platform aspect/quality templates, compact timing controls, and right-click clip actions.
- **Reliability:** one import and one render at a time in the desktop editor; stale render polls cannot overwrite a newly opened project; bounded GET status requests and additional crash-recovery writes when a browser tab is hidden. Previously saved projects remain protected by Save / Don't Save / Cancel.
- **Resource control:** completed in-memory render jobs are pruned after long sessions. Existing waveform caching, GPU detection/fallback, and adaptive preview quality remain enabled.
- **Verification:** GitHub's Test app workflow runs JavaScript syntax and interaction smoke tests plus Python/API and actual MP4 tests. A separate Windows workflow packages and smoke-tests the native executable.

**Scope note:** The update adds manual word-level correction, not a licensed vocal-only acoustic aligner. Preview and subtitle-export pulses should be checked against real vocal material before publishing. No new claims are made about CPU reduction or an additional portable bundle-size reduction without Windows measurements.

## Windows startup freeze recovery

Some Windows machines can display the welcome screen but then show **(Not Responding)** before a song is imported. This is a native WinForms/WebView2 message-pump stall, not evidence that transcription or export is running.

- The native app now performs **bounded, repeated UI-thread responsiveness probes** during initial startup, not just a one-time check after the page loads. If it detects three consecutive failures **and there is no active project**, it offers to restart in Safe Mode, or Browser Mode when already in Safe Mode. It does not force-restart an active editing session.
- **Safe Mode:** `SkellyMotion-SafeMode.cmd` next to the EXE starts an isolated WebView2 profile with graphics acceleration disabled for the embedded UI.
- **Browser Mode:** `SkellyMotion-BrowserMode.cmd` bypasses native WebView2 hosting while keeping the editor, source songs and AI model stored locally. Close the browser tab and acknowledge its exit dialog when finished.
- Diagnostics: `%LOCALAPPDATA%\\LyricForge\\logs\\desktop.log`. Look for `[startup] HANG DETECTED`, `native window shown` and `editor document loaded`. Share that log with the developer if both modes freeze. It may contain local paths; review before sharing.
- CI's Windows window smoke test now performs repeated native-message probes **and** checks that the embedded JavaScript renderer responds. CI passing does not guarantee the same WebView2 runtime, GPU driver or security configuration on every user's PC.

No Windows security protection is disabled, no user WebView2 cache is deleted, and saved work is not migrated.

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



## Compact + smoother SkellyMotion — November 2026

This iteration reduces idle rendering work, simplifies the editor hierarchy, and removes an unused runtime from the portable app without changing the Whisper small model, project formats, lyric animations, or H.264 export.

### Verified portable sizes

| Windows build | GitHub download | Extracted folder |
| --- | ---: | ---: |
| Original | ~197.22 MB | 473.97 MiB |
| First optimization (no FFprobe binary) | 157.66 MB | 373.62 MiB |
| **Current optimization** | **141.17 MB** | **330.81 MiB** |

For the latest verified builds, see [Build SkellyMotion Windows app](https://github.com/skellyruno/LYRICFORGE/actions/workflows/windows-release.yml). The Windows workflow validates bundled Whisper/CTranslate2/PyAV imports, native Python.NET assemblies, a real WebView2 window, and subtitle MP4 export.

**What was removed:** ONNX Runtime's ~42 MB Silero VAD backend. SkellyMotion currently transcribes with vad_filter=False, so that optional engine is unused. If future features enable ONNX speech activity detection, its dependencies must be bundled again. The downloaded Whisper transcription model remains separate in the existing user model cache.

### Editing and CPU improvements

- **Live Preview Detail (Speed panel):** Auto selects a smaller canvas for Balanced and Eco profiles; Light further reduces drawing pixels, while Sharp restores maximum preview detail. Video exports stay at the chosen 540p/720p/1080p and 24/30 FPS regardless of preview setting.
- **Less idle work:** preview schedules low-frequency wakeups while paused or hidden instead of a continuous high-frequency animation-frame loop; playback wakes promptly for play, seek, and style changes.
- **Fewer DOM rebuilds:** selecting lyric clips updates only selected highlights, and typing updates a single clip immediately while batching full timeline updates.
- **Better lyric lookup:** playhead preview uses an indexed, binary-searched lyric timeline rather than two full scans on every playback frame. The index is invalidated after edits, preserving current motion timing.
- **Smoother timeline:** the playhead uses a GPU-friendly CSS transform instead of continuously changing its layout position. Clock labels are only updated when changed.
- **Cleaner UI:** compact controls, more legible tabs, improved focus states, calmer shadows and clearer green selected states. The user-customizable panel/timeline sizes remain intact.

The tests verify preview pixel dimensions and selection/timing edits. The Windows GUI smoke test checks whether the packaged editor opens and stays responsive. These results do not establish a measured CPU percentage reduction on every computer; compare playback and export locally for your hardware.

**Installation:** From GitHub Actions, manually run **Build SkellyMotion Windows app** on `main` to request a Windows ZIP. Download the `SkellyMotion-Windows-x64` artifact from that manual run, extract once, and keep the EXE and `_internal` folder together. Projects and model cache remain under `%LOCALAPPDATA%\LyricForge`.

## Smaller Windows portable package (November 2026)

The Windows portable app now uses the already-bundled **PyAV** library to read song durations and validate image/video backgrounds. This removes the duplicate 100 MB `ffprobe.exe` while retaining the verified FFmpeg `ffmpeg.exe` needed for lyric rendering and H.264 exports. Whisper `small`, native WebView2, supported media imports and existing project/model storage remain unchanged.

Measured GitHub Windows build results (same workflow and compression settings):

| Size | Previous build | Reduced build | Saved |
| --- | ---: | ---: | ---: |
| GitHub artifact ZIP | 197.22 MB | 157.66 MB | 39.56 MB (about 20%) |
| Extracted Windows folder | 473.97 MiB | 373.62 MiB | 100.35 MiB |

The **launcher EXE** itself is approximately 17.21 MiB; most disk usage is its adjacent `_internal` folder. Extract the entire artifact once, keep `SkellyMotion.exe` with `_internal`, and do not delete bundled libraries individually.

Windows CI checks the actual portable EXE by rendering ASS captions with FFmpeg, probing that video via PyAV, initializing the Python.NET/WebView2 DLLs and opening its native window. Source tests also check real WAV/PNG/JPEG metadata parsing.

## SkellyMotion 0.8.3 — fix unresponsive desktop window

A visible editor with **"(Not Responding)" in the title bar** is different from the DLL errors. That means the native Windows host or embedded WebView2 renderer may be stalled; it is not proof that Whisper/FFmpeg is busy. The last-project auto-load is already disabled on native startup.

The latest download includes three ways to launch the same local editor:

- **`SkellyMotion.exe`** — normal native Windows window, GPU acceleration retained.
- **`SkellyMotion-SafeMode.cmd`** — native window using a separate WebView2 profile under `%LOCALAPPDATA%\LyricForge\webview_safe` and temporary software rendering. This bypasses some corrupted-profile/GPU-driver startup issues. Rendering videos still uses the configured FFmpeg encoder, and no original WebView2 profile is deleted.
- **`SkellyMotion-BrowserMode.cmd`** — open the studio in the default web browser, not in the embedded WebView2 window. It runs the same local FastAPI backend on `127.0.0.1`, preserving songs, projects, Whisper `small`, and exports. After editing, close the tab and click OK in SkellyMotion's exit dialog to stop the local server.

The startup path also skips idle canvas compositing behind the welcome overlay, and logs native window **shown** and document **loaded** events to `%LOCALAPPDATA%\LyricForge\logs\desktop.log`.

**Suggested order:** Try normal mode; if the window becomes gray or unresponsive, use Safe Mode. If Safe Mode also freezes, use Browser Mode to edit immediately and send `desktop.log` for deeper debugging. These are recovery options; exact WebView2 hangs vary with the Windows installation, driver, and runtime version. We have not established that every affected computer will respond to Safe Mode.

For a new ZIP, open GitHub Actions → **Build SkellyMotion Windows app** → **Run workflow** on `main`, then download `SkellyMotion-Windows-x64` from that manual run. Automatic pushes compile and test but do not upload an artifact, preventing the old repeated-build storage quota failures. If GitHub still reports a full artifact storage quota, wait for its quota recalculation or remove unused historical artifacts in GitHub.

## Windows runtime fix — blocked Python.NET or WebView2 DLLs

On some Windows machines, Explorer marks DLLs extracted from a downloaded ZIP as Internet-originated. The .NET Framework may then refuse to load `Python.Runtime.dll` or `Microsoft.Web.WebView2.Core.dll` with error **0x80131515**. This is different from a missing WebView2 Runtime installation.

### What to try immediately

1. Close SkellyMotion.
2. Right-click your downloaded `SkellyMotion-Windows-x64.zip` → **Properties** → select **Unblock** if available → Apply.
3. **Extract the unblocked ZIP into a new folder** (don't just overwrite an old partial extraction).
4. Open `SkellyMotion.exe` while keeping the adjacent `_internal` folder intact.

Only unblock a ZIP that came from your own trusted GitHub repository. If a download is unfamiliar, verify its origin and scan it before opening.

### Built-in repair (new Windows build)

- Before opening the native window, SkellyMotion checks a narrow allowlist of its own managed UI assemblies: `_internal/pythonnet/runtime/Python.Runtime.dll`, `_internal/webview/lib/Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll` and optional WebView2 WPF assembly.
- If Windows has blocked any of those files, the app shows a **Yes/No dialog listing the affected DLLs**. On explicit approval it removes only their `Zone.Identifier` download markers. It does not disable global Windows security or touch other binaries, project files, songs or AI models.
- You can manually launch `Repair-SkellyMotion.cmd` beside `SkellyMotion.exe`, which runs the same targeted, consent-only repair path.
- Windows CI now verifies that the packaged `Python.Runtime.dll`, `Microsoft.Web.WebView2.Core.dll` and `Microsoft.Web.WebView2.WinForms.dll` are present, then loads the .NET UI assemblies using the packaged GUI executable's `--native-self-test`. This catches missing or mismatched packaged assemblies. It cannot prevent Windows Explorer from applying download markers **after** GitHub's artifact is downloaded, so the startup repair handles that case.

If the startup dialog continues after repair, read `%LOCALAPPDATA%\LyricForge\logs\desktop.log` and confirm the full artifact was extracted. The existing Whisper `small` model and all project folders are preserved.

## SkellyMotion 0.8.1 — faster opening and ONE extraction on Windows

**Why it seemed to freeze:** The desktop edition previously reopened the last project immediately, which could trigger media loading, waveform generation, and hundreds of timeline controls while the WebView2 window was still starting. The Windows app now opens the welcome screen first; use **Resume last project** to reopen your song when ready. The Projects tab still works and **no songs or AI models are removed**. The browser edition keeps automatic restoration.

- Waveform decoding is deferred until the editor has painted, then FFmpeg uses **one decoding thread** and below-normal Windows process priority. Previously generated waveforms remain cached.
- Video backgrounds now preload metadata rather than the whole video. Saved project files, Whisper `small` and model-cache directories are unchanged.
- Startup stages (Python imports, local API readiness, native window creation) are recorded in `%LOCALAPPDATA%\LyricForge\logs\desktop.log`. If the app still stalls before the welcome screen, check those stages: Windows Defender's first-run scanning, a slow disk, and WebView2 initialization can also delay the first launch.
- **GitHub Actions downloads require just one extraction.** The `SkellyMotion-Windows-x64` artifact now contains `SkellyMotion.exe` and its `_internal` folder directly, rather than an extra ZIP inside another ZIP. Keep them together in one folder.
- Manual Actions builds skip redundant release ZIP compression, saving packaging time. GitHub **Releases** still provides one self-contained ZIP for tagged versions.

Build the updated executable using **GitHub Actions → Build SkellyMotion Windows app → Run workflow** on `main`. Download `SkellyMotion-Windows-x64` from the completed run and **extract only once**. Keep the previous working build until you've tested launch, importing, preview, and exporting.

## SkellyMotion 0.8 — speed, quality and CPU overhaul

**Backwards compatibility:** Uses the same Whisper \`small\` model by default and the same \`%LOCALAPPDATA%\LyricForge\workspace\` and \`%LOCALAPPDATA%\LyricForge\models\` paths. Existing song files, corrected lyrics, and projects aren't migrated or deleted.

### Faster video renders, without compromising previous exports

- **Hardware acceleration (H.264 encoding):** NVIDIA NVENC, Intel Quick Sync and AMD AMF are tested with an actual three-frame encoding probe. A listed-but-unusable encoder is ignored. Auto prefers a successfully tested GPU; if an encoder fails during a real video export, SkellyMotion retries on CPU. libass caption effects and some video filters still use CPU, so speedup depends on hardware.
- **Eco / Balanced / Turbo:** Eco reduces preview FPS and uses lower-priority Windows FFmpeg workers; Balanced is the default; Turbo permits higher CPU thread budgets. CPU-thread preferences for the AI model are selected when it first loads; restart the application to change those after a model has loaded.
- **24 or 30 FPS** per export, alongside 540p, 720p and 1080p and existing Fast/Balanced/Quality encoder choices.
- **15-second test render:** Render just the first fifteen seconds, watch the result inside the editor and download it if desired. Uses the same caption, audio, encoder and styling pipeline as full exports.
- **Render fingerprint cache:** Re-exporting an identical project with unchanged audio, backgrounds, lyrics and settings reuses the completed MP4. Changing any relevant source invalidates the cache. Failed exports never overwrite a successful file.
- **Live profiling:** Performance tab shows process CPU/RAM, FFmpeg child memory, confirmed GPU encoders, export frame rate, elapsed time, processing speed and whether the export was cached.
- **Preview optimization:** Solid gradient backgrounds are cached to an offscreen canvas; lyric text layouts are cached with a bounded LRU; idle playback throttles frame paints and Eco mode uses a lighter frame budget.
- **Faster new project setup:** Gradient creation uses an anti-aliased 360×640 intermediate (upscaled to 720×1280), with palette-aware caching. Repeat uploads of the *exact same audio bytes* with identical Whisper model, recognition mode, language and vocabulary reuse machine-generated transcription/timestamps; manually corrected lyrics are never copied into another project. The cache retains at most 40 transcripts.

### Better sung-lyric review, same model

- A **vocabulary hint** for artist names, slang, and uncommon words is available in the Advanced upload options and in native Windows imports. This is a model hint, not a guarantee.
- Low-probability words are marked **Worth checking** in the review screen (probabilities are *not* calibrated accuracy percentages). Click a word to listen near that timestamp.
- **Refine uncertain sections** performs an optional second Whisper pass using beam size 5, limited to up to four uncertain regions. It retains the existing model and avoids repeated whole-song transcription.
- The second pass generates proposals and comparisons. You must explicitly approve replacements, and applying them warns before replacing current unconfirmed textbox edits.
- Auto-generated timing uses Whisper word timestamps and corrected-word interpolation; **this is not a licensed/acoustic forced-alignment engine**. The app still requires manual review for musical vocals.

### Performance benchmarking

To compare versions, use the **same source song**, lyrics, background, export resolution/FPS/encoder, and computer. Record processing duration, render FPS, CPU, RAM, and file size. A fair quality comparison should also review the actual MP4; faster encoding does not imply equal quality at the same bitrate.

The new Python regression tests exercise encoder selection/fallback, source-aware caching, short previews, opt-in refinement and transcription reuse. The JavaScript smoke test covers the editor's performance and review controls. These source tests are not a substitute for a successful **Windows build** and testing on the user's hardware.

To install: open **GitHub Actions → Build SkellyMotion Windows app → Run workflow** on \`main\`, then extract the whole \`SkellyMotion-Windows-x64\` artifact. Keep the previous working version until importing, editing and MP4 export succeed.

## SkellyMotion 0.6 — clip motion, faster exports and cleaner Windows operation

This upgrade keeps the **same Whisper \`small\` model**, project location, local AI model cache, existing songs and saved lyric edits. Nothing is deleted or renamed in \`%LOCALAPPDATA%\LyricForge\`.

### Motion editor: independent effects on individual lines

- Open **Motion**, select a lyric clip, and set that clip's own animation: Pop, Fade, Slide, Zoom, Bounce, Blur, Type-on or None. Empty/inherited selection uses the project's global effect.
- Set a clip's entrance duration (120–650 ms), horizontal position (8–92%) and vertical position (8–92%).
- **Drag lyrics inside the video preview** to reposition the active line. A green positioning guide appears while paused.
- An **FX lane** in the timeline shows which clips inherit the global effect and which have an override. Click a badge to select and edit its lyric.
- Preview selected motion, reset one clip or apply a selected clip's motion to all. The clip overrides are stored in the original project manifest, so reopening projects retains them.
- The FFmpeg ASS subtitle renderer uses the same per-clip animation and position, including avoiding conflicting \`\\pos\` + \`\\move\` tags for slide effects.
- Older projects without clip overrides still inherit the original global effect. Undo/redo and autosave include clip effects.

### Rendering improvements

- FFmpeg child processes launch without separate command windows on Windows; media duration/background checks now use the already-bundled PyAV library without requiring an FFprobe executable.
- Added **540p Quick proof** alongside 720p and 1080p, plus three H.264 encoder settings: **Fast**, **Balanced** (original default) and **Quality**. Fast trades compression efficiency for speed and can make bigger files; Quality uses a slower preset and typically preserves more detail.
- Export panel reports actual progress from FFmpeg, not just elapsed time.
- Failed renders don't overwrite an earlier successful MP4: output is encoded into a temporary file then swapped in only when complete.
- Video processing still depends on CPU, source format and clip count. Hardware GPU encoding is not yet enabled. A long 1080p burn-in may still take longer than the song.

### Faster versus more accurate lyric detection

- Before uploading, choose **Fast** (beam 1), **Balanced** (beam 3 by default), or **Accurate** (beam 5). They use exactly the same Whisper \`small\` model and word-level timestamps. More beam search can take longer and can sometimes improve transcription, but is not a guarantee for music vocals.
- Optionally select the known song language. Otherwise SkellyMotion auto-detects. Choosing the correct language can avoid wrong detections, especially if the track starts with instrumental audio.
- Whisper recognition still needs human review; automatic sung-lyric timing is approximate. No additional large AI model is downloaded for these choices.
- \`SKELLYMOTION_BEAM_SIZE\` continues to override the default Balanced beam if you configured it previously.

### Testing

Windows and test workflows run the zero-dependency editor smoke test and Python backend tests, including per-clip ASS timing, recognition options and progress parsing. Changes must still be validated on a GitHub Windows runner and in a real MP4/Whisper session on your computer.

To get this release: go to **Actions → Build SkellyMotion Windows app → Run workflow** on \`main\`, then download \`SkellyMotion-Windows-x64\` under Artifacts. Extract the whole folder; don't replace your old working folder until song upload, transcription, preview and export succeed.

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
