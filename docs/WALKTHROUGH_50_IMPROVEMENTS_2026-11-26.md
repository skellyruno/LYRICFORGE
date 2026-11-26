# LyricForge — 50 improvements / Plugin Walkthrough Director

2026-11-26. Continuation of `LYRICFORGE_CINEMATIC_LIVE_VISUAL_ENGINE_WIP_2026-11-26.zip`, not a replacement editor. This is a source candidate; no new Windows binary, main merge or GitHub upload is implied. Existing release draft PR #10 remains at 9b0b7d7. This audit counts individual implemented capabilities and fixes, not 50 unrelated releases. Tests cover groups of changes; native display capture specifically remains unverified.

## 1–16: Real recording pipeline
1. Plugin-agnostic asset classification (recording, captured state, B-roll, document, automatic).
2. Explicit browser window/screen selection using `getDisplayMedia`, never automatic desktop surveillance.
3. Video-only MediaRecorder path; no automatic microphone or system-audio collection.
4. Recording automatically stops after 60 seconds.
5. Manual stop control and browser-track-ended handling.
6. Recording byte cap; discard oversized or empty recordings safely.
7. Capability detection and clear external screen-recording import fallback.
8. Stream-copy repair for MediaRecorder WebM files missing duration metadata, with bounded work.
9. Actual recordings tagged and favored when metadata matches the narrated topic.
10. B-roll/documents and external illustration sources excluded as plugin demonstrations.
11. Validate capture role against image/video format.
12. Editable recording in/out trims with duration and range validation.
13. Advance through recording sections on repeated use rather than always starting at zero.
14. Real demonstrations do not loop/reverse automatically.
15. Hold the final real frame if source footage is shorter than the scene; review warns about this.
16. On-video actual-screen-recording provenance label.

## 17–32: Guided captured-state replay and visual library
17. Assign captured plugin states to named groups.
18. Order before/after captures; automatically select the preceding group state.
19. Set a normalized control-focus point by clicking a genuine screenshot.
20. Automatic focus from localized pixel differences, not filename-only inference.
21. Reject diffuse/ambiguous differences and incompatible image geometry for automatic focus.
22. Switch between original captured states; never synthesize intermediate knob values.
23. Animated editorial guide pointer approaches the selected control.
24. Timed focus pulse at the switch.
25. Before/after and editorial-focus labels distinguish reconstructed walkthroughs from actual recording.
26. Whole-editor panel sizing that preserves the aspect ratio and reserves caption space.
27. Asset descriptions editable after import.
28. Edit group, order, role, focus and trim metadata via API and editor.
29. Reversible disabling/restoration without removing the original media file.
30. Content-digest duplicate suppression for identically tagged uploads.
31. Keep downloaded/generated illustration provenance; reject relabeling as a plugin capture and do not revive disabled cached art.
32. Image thumbnails, video preview and asset duration in the expandable visual library.

## 33–43: Cinematic picture, text and sound finishing
33. Transition style selector: dissolve, slide, wipe, adaptive, hard cut.
34. Adjustable transition duration with frame-based bounds.
35. Adaptive visual transition selection (restrained dissolves on technical scenes, varied B-roll transitions).
36. Hard-cut mode explicitly skips crossfade work.
37. Kinetic phrases, animated individual words, clean captions, or no burned captions.
38. Adjustable caption sizing with bounded range.
39. Export editable WebVTT captions alongside MP4 and scene JSON.
40. Narration processing choices: natural, present/crisp or original.
41. Independent backing music gain, including Brand Kit bed level.
42. Independent original sound-cue level.
43. Original, quiet state-change accent aligned to the guided replay switch.

## 44–50: Reliability throughout LyricForge
44. Validate cached scene streams/duration before reuse; reject corrupt cache files and symlinks.
45. Check output video/audio presence and duration before atomic final publication; scratch-isolate cinematic caption files.
46. Coordinate uploads/index edits with job registration and serialize index updates; protect existing assets during failures.
47. Serialize explicit project save with transcription progress/finalization; preserve saved metadata and retain existing draft lyrics on recognition failure.
48. Serialize recovery/background registration with save; correct draft-to-saved background upload race and constrain discard cleanup to valid pending filenames.
49. Retain ASR/TTS timing through punctuation, case and token boundary changes when normalized text is unchanged, instead of blindly redistributing timing.
50. Preserve dirty/persisted state when native close fails or browser close cannot actually be performed.

## Additional safeguards
- No hidden plugin/DAW automation, simulated control values, or arbitrary executable loading. Capture is user-initiated. A real plugin host recording is needed for continuous knob/meter motion. Guided replay is editorial, not a recording of live plugin interaction.
- Job polling clears stale cancellation/ETA state; project-switch guards stop stale visual results from appearing in another project. Reject generated file symlinks, validate finishing options, export VTT safely, and include compressor lab smoke tests in both CI workflows.
- Default API behavior preserved where practical; new walkthrough mode is opt-in at the API, enabled in the Director UI. Previous files, state IDs and original project paths retained. No private user media added to source archive.

## Evidence and release gates
- 123 targeted Python tests passed, covering walkthrough, image sourcing, media exports, captions, cinematic engine, diagrams, storage, project library, recovery, transcription cache, music tools, native bridge and import. Three JavaScript smoke suites passed. Real FFmpeg fixture tests cover recording playback, WebM remux, exact-frame dissolves and rendering. The fixture recording is synthetic test footage, not a captured DAW session.
- Real SkellyTune screenshot source: previous verified Mini/Lab Windows test artifact 15109387910 at 035f3817508682d51c948bbfbd40f83cd9376751. V3 is an editorial replay of captures, with matching META mode 25/100/0 ms, not live control automation. Actual screenshots have not been repainted or fabricated. Conceptual pitch curves remain labeled simulations.
- Current LyricForge native WebView2 UI and screen recorder permission flow not tested on Windows; Quick4 source and JUCE are present but Linux Xrandr/ALSA dev libraries missing. No new EXE or merged PR. No actual DAW recording/SkellCore telemetry, neural narration model or live AI inference verified. Review final video for subjective voice, music and visual acceptance.
