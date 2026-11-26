# Autonomous Creator — November 26, 2026

Continue the existing 50-improvement WIP; no prior source paths removed.

## Create a full plugin video
Open the Auto panel → Create a video from a brief. Enter a product name, describe the audience/style, add confirmed product facts one per line, select a target duration, draft the script, edit or paste a longer script, attach genuine screenshots or screen recordings, audition a local voice, then create an editable project or render the full video. The deterministic local writer structures supplied facts; it does not infer undocumented product behavior from a screenshot or interpret arbitrary stylistic requests like a language model. The target duration is advisory; actual duration comes from narration. For creative writing and longer scripts, use an external agent to provide chapters. Do not invent product claims, UI states, test results, or measurement data.

## Voice
Piper is an optional local neural sidecar, not a bundled dependency. From a separate Python environment, install `piper-tts`, download a voice using the official `python -m piper.download_voices` command, and confirm its model license. Point `LYRICFORGE_PIPER_EXE` to the installed `piper.exe` command, and `LYRICFORGE_PIPER_MODEL` to the absolute ONNX file (adjacent `.onnx.json` required). Start LyricForge in that environment. See https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/CLI.md . The Windows system provider uses installed SAPI/System.Speech voices, not necessarily neural. `draft` uses locally installed eSpeak; `auto` prefers Piper, then system, then draft; actual provider is returned in project metadata. Explicit neural selection fails if unavailable rather than silently substituting. Audition previews are temporary. Phrase durations are measured from generated audio; word timing within phrases is estimated. For your own voice, export/read the approved script, record it and import the recording through the existing lyric/voiceover editor; run transcription and review timing before directing it. No real neural model inference or Windows system-voice run has been verified here.

## Agent interface
Run `python studio_cli.py create job.json --out finished/my-video` from source. Paths in `assets` are local to the manifest; specify trusted local files only. The destination must be new; older videos are not overwritten. An agent may use `--draft-only` to stop after narration. It can also use the app's authenticated HTTP interface: POST `/api/creator/script` (JSON), GET `/api/creator/voices`, POST `/api/creator/voice-preview` (JSON, returns WAV), POST `/api/creator/create` (multipart `payload` JSON and repeated `files` uploads), GET `/api/jobs/{id}`, POST `/api/jobs/{id}/cancel`, GET `/api/projects/{id}`. No caller-provided executable paths or commands in the HTTP contract. Use returned project/plan/video/caption IDs, do not invent success or bypass review.

Example job:
```json
{
  "product": "My Plugin",
  "brief": "A two-minute educational demonstration for music producers",
  "target_seconds": 120,
  "voice": "auto",
  "speed": 1.0,
  "auto_render": true,
  "format": "youtube",
  "chapters": [
    {"title": "Introduction", "narration": "Here is a closer look at My Plugin.", "visual_hint": "main editor"},
    {"title": "Hear the difference", "narration": "Listen to the before and after examples.", "visual_hint": "recorded mix control demonstration"}
  ],
  "assets": [
    {"path": "media/editor.png", "role": "plugin_state", "description": "main editor"},
    {"path": "media/mix-control.mp4", "role": "plugin_recording", "description": "recorded mix control demonstration", "trim_start": 0, "trim_end": 5}
  ]
}
```
For guided states use identical mode/window captures, `group` and increasing `order`, optional normalized `focus_x`/`focus_y` in [0,1]. Do not label unrelated B-roll as a plugin recording. If change localization fails, the director keeps the actual screenshot and reports the fallback instead of inventing a knob motion. Current limits: 120 chapters, 3300 words, 500 timed editor clips, 40 assets (80 MiB each, 500 MiB combined), 30 minutes of narration; requested target 15–1200 seconds. Full-length YouTube/square, platform-capped reels. Clip/cache validation retained.

## Release status
Prior verified release branch `fix/source-media-probe-20261123`, draft PR #10, exact commit `9b0b7d7` passed both CI platforms with 288 tests each. This larger WIP is **not that build**. The older WIP branch `feature/skellymotion-wip-studio-suite-2026-11-20` contains a substantially older server and no Scene Director. Git terminal DNS access is blocked. GitHub connector supports text-file/commit operations, not a container source ZIP transfer; do not wholesale replace the release branch with unreviewed files or discard its verified build infrastructure. Import this archive on a separate draft branch using a real git environment, inspect and reconcile the exact changes against both branches, run full Windows/Linux tests, package, capture and inspect real WebView2 screenshots (including Creator controls, closing, resizing and recording), then validate neural inference and actual DAW capture. Keep existing release and draft PR intact until verified.
