# Live DSP Director / narrated SkellyTune test — 2026-11-26

Continues the Intelligent Director WIP without replacing its existing app, workflows or original files. This is a source-only update; GitHub release branch 9b0b7d7 and its existing Windows binary have not changed.

## New implementation
- Signal-driven 1 kHz numerical level/transfer simulation with attack/release smoothing, live gain reduction and moving input/output traces. Adjustable threshold, ratio, attack and release are validated by the Director request schema and included in scene/cache keys. This is an educational envelope model, not a measured compressor plugin.
- Interactive compressor lab (standalone HTML and expandable within the Director) runs locally without network. Its controls are read into the next render request. Pause/reset and numeric readouts work in the JS behavior harness; browser/WebView2 layout has not been verified. Controls currently reset on page reload.
- Animated conceptual pitch correction: 70 ms and 0 ms cents-domain correction smoothing, not actual SkellyTune audio processing. Animated C-major target-note selection. Scene planner separates changes in topic, ignores tiny frame-rounded sentence overlaps, and avoids selecting unrelated screenshots over a relevant technical diagram. Actual relevant screenshots remain prioritized.
- Video frame sequences are rendered at 15 fps and resampled to the selected output FPS, one bounded 960x540 JPEG at a time; cancellation checked at each frame. No new required model dependency. Captions are placed below diagram panels; screenshot inspection caught and corrected an overlap.

## Evidence
- Narrated SkellyTune Mini explainer: 40.63s, 1920x1080, 24fps, audio/video present, five scenes, zero timing QA errors/warnings. Narration generated with eSpeak from documented product behavior (see https://github.com/skellyruno/skelltune-playground/blob/main/README.md); phrase timing derived from generated WAV duration, word timing interpolated, not a Whisper transcription or real singer test. No fabricated plugin GUI or plugin measurements.
- Moving Compression proof: 13.40s, 960x540, 30fps, audio/video present, two animated compression scenes, zero timing QA errors/warnings. Actual rendered frames inspected and captions corrected/re-rendered. These are not screenshots of the LyricForge desktop app.
- Broader targeted suite: 95 tests passed in 26.66s before the final unrelated-screenshot selection change; the final seven live-diagram tests passed, including that change. Existing editor/autonomous JavaScript smoke tests and new compressor-lab JS smoke test passed. Python syntax and JS syntax checked. Existing variable-tempo drift confidence fallback tested in beat regression suite; general variable-tempo tracking remains unverified.

## Remaining release gates
No compatible local diffusion/CLIP models or transformers/diffusers installed; real inference not verified. Full overlap crossfades, real-song tempo tracking, actual Windows UI capture and new Windows packaging remain open. No GitHub release branch changes or unverified merges. Preserve previous source and binary.
