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
