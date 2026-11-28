# Release blocker: Creator uploaded layer binding

Local expanded editorial tests exposed a genuine failure that the previous hosted Linux run skipped because eSpeak was absent. Creator validated media composition layers before replacing upload_index with safe preflight asset identifiers. It also discarded graphic cues when rebuilding the Director plan.

The fix binds references first against bounded uploaded extensions, persists only the actual imported asset IDs (including duplicate responses), cleans up unpublished project files on failure, and restores graphic cues only for unchanged matching text. Existing asset-upload response fields remain backward compatible. The original draft-voice integration test and three new recorded/invalid/duplicate upload tests passed locally (4/4). CI installs eSpeak on Linux and runs real recorded-voice upload tests on Windows, so the feature cannot disappear behind that optional voice skip.

This supersedes 282c40c as the only current release candidate; do not distribute or promote the older package even if its build completes. Historical evidence and source remain preserved. Existing source-promotion lease for cbb68d0 must fail after this commit; update it to the replacement exact source only after the new producer and archive checksum are known. No merge to main.
