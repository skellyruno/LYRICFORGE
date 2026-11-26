# Consolidation audit — 2026-11-23

Baseline: draft PR #10, commit `0ff7725`, with successful Linux and Windows
CI, 250 tests on Windows, verified portable archive and native WebView2 image.
The separately supplied autonomous WIP ZIP contains additional modules and
routes not present on this branch. Do not replace either tree with the other.

## Implemented in this branch
- Shared atomic JSON publisher for project/recovery manifests, caches, presets,
  Brand Kit, B-roll indexes and render/post manifests. Unique staging names
  eliminate collisions; failures preserve the previous file.
- Staged uploads close the file before cleanup, preserve prior bytes on empty,
  oversized or interrupted input, and publish only successful transfers.
- Unique draft background filenames; failed imports cannot erase the old
  background. Locked old backgrounds cannot invalidate an already-published
  replacement. Legacy background references remain readable.
- Brand Kit asset replacement publishes before retiring older media. Read-only
  library endpoints do not create storage. Malformed B-roll index paths and
  invalid metadata are excluded from use.
- Full/preview/Shorts share dimension, background, cache and encoder helpers.
  Pending backgrounds are consistently selected; missing assets fall back to
  the default generated background. Parent failures terminate stale child
  status entries so projects can be rendered again.
- Superseded Linux PR-only CI runs are cancelled; production, main, manual
  and tagged runs remain independent.

## Verification and open risks
Equivalent changes were locally exercised against the larger WIP source
with 81 targeted tests and both Node smoke suites passing (includes a real
WAV-to-MP4 integration test with simulated ASR). Exact branch CI is required.
There is no new Windows binary or UI screenshot until the new candidate
completes those checks. Previously verified Windows 0ff7725 remains intact.
Atomic publication is not a multi-process transaction: concurrent independent
read-modify-write operations may still need transaction coordination. Do not
claim real Whisper inference, real-user acceptance, or measured speed gains.
Keep this PR draft; no production release or WIP wholesale merge.
