# SkellyMotion V8 — cinematic finishing pass

Additive continuation of the V7 local source candidate, not a replacement of the newer remote branch. User reference videos remain private and are not included.

## Reference study
- Reference (4), 291.13 s, 640×360, 30 fps: Relic 0.4.8 technical showcase. Dark green-black editorial canvas, serif headlines, restrained transitions, actual plugin close-ups, diagrams, comparison bars, orderly typography and large negative space. Whole soundtrack: -16.6 LUFS, -1.1 dBTP.
- Reference (5), 23.31 s, 640×360, 24 fps: RFA RF-BUS trailer. Dramatic macro views, progressive close-up/full-product views, changing finishes, logo reveal. Whole soundtrack: -9.2 LUFS, +1.4 dBTP; not a target peak level. No original reference visuals or music copied into the study.
- Keep the prior documentary reference, product explainer, cinematic trailer and future music-video techniques composable rather than hard-coded as restrictive modes.

## Changes
- New independent documentary caption track retains words across picture cuts. Fixed positions, opacity entrances/exits, yellow animated marker wipe keyed to word onset; source caption timing is preserved (neural narration word timing is still estimated). WebVTT matches the independent caption track. Added validation of caption timing.
- New midnight editorial composition: serif title, subdued grid/rules, stronger visual hierarchy, dark process/chart/timeline cards. Original paper evidence remains available. Source footer spacing corrected after inspecting real output.
- New bounded eased camera path, oversampled FFmpeg zoom/pan, and safe matte presentation for genuine recorded screen footage. True full frame retained in presentation motion; explicit detail crop available as a primitive, no fabricated control operations. Full documentary Creator renders default to 60 fps, previews retain their existing rate. 60 fps camera/graphics does not imply 60 fps original footage or optical-flow interpolation.
- New deterministic original musical underscore (eight-bar chord progression, piano-like harmonics, sustained pad, bass and understated percussion), lower cue gain, soft contact textures instead of ascending synthetic chirps, gentler speech sidechain and silence guard for loudnorm. Music and foley generated separately in bounded blocks. Creator offers Automatic music or Narration only; advanced title animation collapsed by default. Existing Director Brand Kit music remains available.
- Reused verified Kokoro Michael WAV and prior actual UI recordings for the benchmark. No new neural inference, private reference footage redistribution, or invented performance proof. This is a motion/finishing study, not a new completed documentary.

## Verification
Targeted suite: 79 tests passed; six new tests covering actual marker animation pixels, caption clock, VTT, score isolation, silence guard, camera frame count. Both frontend smoke suites passed. Initial score peak assertion failed (5088 vs 5000 PCM), fixed by reducing the energetic bed gain, then passed the regression suite. Browser navigation for actual updated application screenshot blocked by administrator policy; no new UI screenshot claimed. Windows installer and exact remote integration unverified; do not overwrite newer remote changes or merge unverified source. The offline JUCE/Quick4 kit is already available locally; this is a Python/FFmpeg video project and no JUCE build is required.
