# V20: motion stability and script intake

Continues the exact V19 source archive. Original film masters and previous source archives remain separate.

## Implemented
- Stable nominal raster sizes and cached text/paper/spectrum rasterization; premultiplied fractional-pixel affine transforms, bounded 2x output supersampling; stationary projections reused. The text layout reviewer now uses matching stable raster bounds.
- Motion probe: commanded 0.13 pixel/step, 60 steps; V19 integer placement: 52 holds, RMS 0.339951 px; V20: 0 holds, RMS 0.004794 px (probe is not end-to-end subjective jitter evidence). Actual side-by-side four-second V19/V20 composition rendered at 60 FPS. Final line-weight correction inspected separately.
- Creator accepts raw prose (`script_text`); preserves words and explicit chapter metadata. Recording without script uses existing Whisper ASR with measured word timestamps. Manual timestamps and recorded-script behavior unchanged. Audio-only HTTP integration passed with injected recognition; local faster-whisper and model absent. Existing fallback still requires script where model unavailable.
- Multi-object analytic sphere/ground ray tracer: two recursive secondary bounces, scene-object reflections and transmission, tinted area-light occlusion samples, adaptive deterministic edge sampling. Bounded approximation, not arbitrary-mesh path tracer or global illumination.
- Optional fluid solid obstacle, masked dye and velocity, normal-inflow constraint; approximate boundary, not a pressure-converged physical model. Old fluid default preserved.
- Field Notes 06: The Language of Frequency, original five-chapter plan, script and scientific frequency comparison (2 Hz versus 4 Hz, measured FFT example). Music-led until new neural performance is verified. No third-party footage.
- Non-destructive Creator reconciliation proposal tool. V6 snapshot is comparison reference, not a proven Git merge base. Clean text merge proposals require manual review; conflicts and workflow differences retained separately. No promotion or main merge.

## Evidence
- Local broad run: 181 passed / 1 skipped before final adaptive optical sampling and projection cache. Final focused suite: 54 passed; reconciliation unit test passed. Existing Autoclip JS smoke passed. V19 Windows exact-archive gate run 45937412511 passed 656 tests / 7 skipped, portable executable artifact 15171831140, actual welcome screenshot 15171990446 inspected; not a V20 build.
- Fresh local Whisper and CLIP inference unavailable; no claim of inference. Fresh Field Notes 06 neural performance not yet synthesized. Exact V20 Windows build not yet verified.
