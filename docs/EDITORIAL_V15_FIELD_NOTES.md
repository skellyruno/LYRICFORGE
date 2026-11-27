# V15 — Field Notes / Director editions

Additive continuation of V14. Original films, source archives and example scripts remain intact. New optional director editions are authored from the original plans, with matching title hierarchy, continuous keyframe interpolation, a sampled cinematic music arc and native 1280×720, 60 fps output. The two original films are music-led; no neural narration is claimed. Source measurements and UI capture provenance remain explicit.

## Engine additions
- Indexed triangle mesh rasterization with perspective-correct UV/normal interpolation, z buffer, matching-topology morphs, GGX direct light and an analytic softbox environment approximation. Geometry and indices bounded; optional Numba acceleration, NumPy alternative. No arbitrary external mesh paths or code execution. The film demonstrates a six-face textured grid changing into a sphere; UV islands may remain visible. Not a path tracer, not a full arbitrary 3D scene editor or model importer.
- Optional mesh shutter samples blend premultiplied RGBA; continuous monotone cubic per-layer curve option (bounded tangents, not a universal C1 spline at all knots). Existing authored curves remain default unless opted in.
- Independent footage layers follow output clocks of 24, 30 or 60 fps, rather than mandatory 30 fps. This preserves available native cadence, does not invent intermediate frames from lower-rate footage. Temporary frame strips remain bounded per source trim.
- Four comparison-layout candidates scored by source aspect fit and balance. Positive source metadata match required. No claim of semantic or artistic model approval; candidate scoring is landscape-oriented.
- Conservative sampled glyph repair: generated collages are repaired automatically, authored plans opt in. Only accept strictly fewer sampled edge/overlap warnings, preserve content/timing/opacity and media layers. May report unresolved issues; not guaranteed to fix every frame. User approval still needed before publication.
- New cinematic documentary plans use original sampled-instrument arrangement arc if local SoundFont configured; plugin score path unchanged. Existing plans retain their prior arc setting. Original sampled bank/runtime not bundled.
- Cache version bumped to prevent reusing V14 clips under updated render code. Director editions were rendered before the final cache revision bookkeeping update; the expanded repair search was not applied if no layout warnings were present.

## Reproduction
`python examples/polished_films.py sound|image PLAN ASSETS NEW_OUTPUT_DIR --height 720`
Use the previously exported original plan and local assets. Set `LYRICFORGE_SOUNDFONT` to an approved local SF2/SF3 bank if desired. Voice models remain optional and external. Existing V14 scripts and original editions preserved. No model/runtime fetched by this milestone; local Kokoro and CLIP inference not executed. No Windows release or fresh native UI claim. Static Field Notes screening page is a distribution draft only, not deployed.
