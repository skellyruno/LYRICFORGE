# SkellyMotion V12 — reference-driven cinema

Local continuation of the preserved V11 source candidate; not a replacement of the remote LYRICFORGE development branch. No private narration, source video, SoundFont bank, model weights, user captures or rendered media are bundled in this source archive.

## Implementation

- `studio_material`: bounded Cook–Torrance/GGX rough-metal BRDF, two colored analytic light sources, linear-space shading and tone mapping for the virtual housing. Existing screenshot texture remains ungraded. Stronger orbital movement and focus separation; depth of field remains a compositing approximation, and the product is an extruded captured display, not a fully modeled physical device. No ray tracing or physically accurate shadows.
- `studio_graphics`: authored networks with actual edges, sequential versus radial layouts and animated connection paths; geographic-coordinate route schematics with local longitude unwrapping and explicit not-a-road-map annotation. No geographic boundaries, coordinates or relationships inferred. New data types validated in the existing Creator chapter schema. Portrait and landscape rendered.
- Reverse editorial handoff: extract the exact decoded final frame of the preceding encoded B-roll shot, project it out over the incoming animated graphic/spatial scene. Preserve source trim, scene frame count and caption clock. Only explicitly tagged B-roll; never recorded plugin demonstrations. Previous clip cache key included only for this transition.
- Reference analysis: bounded 2 FPS, 80×45, max 600 seconds. Approximate large image changes, median intervals, brightness/contrast and intra-shot motion proxy. Conservative pacing prior, explicit chapter/graphic cuts still take priority. Does not identify semantics, classify edits perfectly or copy reference frames into a project. `python studio_reference.py reference.mp4` outputs a profile. A trusted local Creator CLI JSON manifest can use `"reference": "relative/path.mp4"` to measure a local reference; only the resulting metrics enter the project/API. No new mandatory UI controls. The HTTP API accepts metadata only, not filesystem paths.
- Correct graphic replacement clears all stale source-role, timing, focus and media-feature metadata and removes replaced assets from the usage counter. This fixes needless duplicate-composition boundaries.
- Original synthesized documentary music adds a bowed harmonic line, resonance, dynamic phrasing and a breath before the final cadence. Optional local sampled-instrument music uses a newly composed MIDI event arrangement of piano, strings, finger bass, cello and celesta with a gradual build and release. The same 88 BPM visual-edit clock is retained. The existing energetic/plugin branch is sample-identical at checked intervals.

## Optional sampled score setup

Set `LYRICFORGE_SOUNDFONT` to a licensed local GM-compatible `.sf2` or `.sf3` bank and install a compatible local FluidSynth shared library. `LYRICFORGE_FLUIDSYNTH_LIB` can explicitly name that trusted local runtime. No automatic downloads. If no bank is configured, the existing synthesized score remains available. If a configured bank or runtime fails, fail explicitly rather than silently downgrade. No instrument bank or shared library included here. For the local audition only, the installed Debian TimGM6mb bank and libfluidsynth3 were used; consult the bank's license and provenance before distribution or bundling. Windows runtime/install integration has not been verified.

## Reference measurements

From the three supplied examples, with a bounded 600-second prefix of the longer documentary: large-change proxy 129 / 11 / 1; median detected intervals 4 / 15 / 11.5 seconds; normalized median brightness .326 / .108 / .117. These are not exact cut counts and fast/dark shots can be missed. The reference pacing was used in the benchmark plan; no original reference media included.

## Validation

Final local targeted suite: 104 passed, including the real sampled-score runtime, malformed graphic coordinates/links, perspective pose, frame timing, real reverse B-roll handoff, Creator and autonomous API tests. Both existing Node frontend smoke suites passed. Initial perspective test failed because camera angle flattened the top edge; corrected and re-tested. Inspected a network connector crossing an unrelated node, changed layout and trimmed connectors; corrected portrait route label backing and safe-area placement. Local plugin score sample equality verified against V11 over three one-second intervals. Verified local offline JUCE kit already available; this Python/FFmpeg work does not require a JUCE build. No Windows installer, native UI screenshot, fresh voice inference, or GitHub push/merge claimed.
