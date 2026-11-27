# Consolidation audit — 2026-11-27

## Branch ancestry verified
- main 640f39b -> draft #10 9b0b7d7 -> draft #11 b37a857 -> draft #12 68c3370. #11 contains all #10 commits (23 ahead, 0 behind); #12 contains all #11 commits (18 ahead, 0 behind). #12 was 52 ahead of main and zero behind before this audit. No cherry-picks or redundant inter-branch merges needed.
- Keep #12 the single active development lane, #10 a verified historical fallback, #11 its Creator base. Do not close fallback drafts or merge main until complete gates pass.
- Important: the exact candidate is assembled by the staging workflow. A root checkout of #12 alone is not equivalent to the staged executable source. Promote the tested staged source to root with a complete file-diff review before a production merge; retain original archives and historical workflow evidence.

## Exact candidate local recheck
Downloaded CI artifact 15211239868 from run 46028083402; verified producer 68c3370de0854d633c8d75bd6fd7f713f737b51f and inner ZIP SHA256 6d3e6e8ce13a7b423603fa07ff0deb5466e5f5691b1bf9b4f09c02f4687ea7d2. Actual local FFmpeg 7.1.5:
- 21 passed: renderer routing, recovery and packaging contracts.
- 15 passed: Hold/Cut, 22 deselected.
- 64 passed, 1 skipped: V21 components, Creator, Voice Studio, presenter, visual sources, intelligence.
- 5 JavaScript syntax checks and all 3 JS smoke suites passed.
These are 100 passing selected pytest cases, not a complete suite. PyAV and real model dependencies unavailable locally. Existing approved welcome artwork/preferences unchanged.

## Root cause and repair
Run 46028083402 inference failed at model acquisition: selected OpenAI CLIP revision did not provide the required model.safetensors file; no actual inference ran. Use pinned LAION CLIP transformers safetensors with published SHA256, and pinned Whisper CTranslate2 weights with published SHA256. The targeted recovery workflow verifies exact same candidate source and neural take, splits speech and vision into independent jobs, checks all five actual speech chapters and both axes of vision rankings, records model provenance even on inference failure, and does not rerun Windows or cancel the currently running narrated film/integration. The retry is intentionally temporary; fold it into the canonical integration workflow once the existing jobs finish. No new model shipped. No claims of real inference success before evidence.

## Merge sequence
1. Wait for exact staged Linux/Windows evidence; finish native screenshot inspection, real inference and narrated-film artifact review.
2. Resolve all remaining source/workflow conflicts by comparing the exact candidate against root; preserve packaging and recovery contracts.
3. Promote verified staged source on draft #12, rerun full release gate on that tree and inspect exact Windows UI.
4. Consolidate the historical PR references, then merge only verified changes. No production release or main merge in this audit.

## Hosted Hold/Cut discrepancy
The exact 68c3370 hosted Linux step again timed out after eight minutes; Windows was skipped. Local exact-source 15/15 Hold/Cut passed on FFmpeg 7.1.5. A disposable single-tpad alternative, without a cached loop, also passed all 15 on the same local runtime (9.75 s). It is not promoted. The targeted diagnostic workflow compares original loop vs single-tpad on Ubuntu 24.04 and the newer runner, captures the exact FFmpeg version/commands/progress, bounds each actual encode to 20 s, validates frame counts and audio/video timing, then runs real API tests with visible progress. No replacement of the production Hold algorithm until the newer runner proves it. The original long film job is not cancelled. No false claim that the hosted regression is resolved.


## Completed evidence — exact staged 68c3370
- Narrated render job succeeded in run 46028083402; artifact 15214236362 downloaded and independently checked. SHA256 195487bdfff9e2d32a865f9790e1bb6ec57210eae6cf721f0867ce3a92824d07, 3927 H.264 frames at exact 60 fps, 960x540, both picture and AAC streams start at zero and last exactly 65.45 s. -16.6 LUFS, -2.0 dBTP encoded mix; five scenes rendered, no cache, 131 decoded-frame samples and 64 layout text samples, zero heuristic warnings. All five actual chapter captures visually inspected; small source labels could benefit from larger delivery resolution. No subjective listening or all-frame visual approval claim. Original shorter master retained.
- Recovery run 46029545195: real vision job passed; artifact 15212904016 inspected. LAION CLIP ViT-B/32 revision 1a25a446712ba5ee05982a381eed697ef9b435cf, verified weights 74813fbcdc750f235c9784c367ca1394d2a5c25eb0aac92761752ac239db7cff. Red vs blue control scores [30.8011,23.8346] for red prompt, [25.3369,32.0310] for blue prompt. The real technical diagram ranked highest for graph prompt (25.5897), but that diagnostic is review-only; not broad scene-understanding validation. Actual worker inference ran locally on the hosted CI runner after explicit model acquisition. No installed-user model or UI claim.
- Same recovery run: Whisper actually transcribed all five Kokoro phrases; quality gate failed, artifact 15212839046 inspected. Systran tiny.en revision 0d3d19a32d3338f10357c0889762bd8d64bbdeba, verified model hash 1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a. Raw aggregate 11 edits / 119 reference words (9.24% WER). Chapter raw WER: 0%, 0%, 38.46%, 4.55%, 0%. Chapter 2 contained two zero-length word intervals ("Double" at 4.74s and "frequency" at 5.50s). Chapter 3 raw WER partly reflects equivalent number spelling (440/880/1320) and a genuine "successively"/"successfully" substitution. Chapter 4 dye/die substitution. Preserve raw timestamps and score, add separately labeled numeric normalization and bounded estimated timing repair in a future candidate; don't count repaired timing as measured alignment. Real inference verified, ASR quality gate not passed.
- Hosted Linux integration remained failed on Hold/Cut timeout; Windows skipped. New Hold diagnostic run 46029714215 still in progress when inspected. No promotion or merge. Quick4 offline kit not found in Library. No change to approved welcome appearance.
