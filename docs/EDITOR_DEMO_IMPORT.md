# Offline JUCE editor demonstration importer

The new CLI validates the SkellCore Quickstart gain adapter's editor-capture manifest, ordered PNGs, sample-clocked parameter readback, and measured PCM. Seal, verify, then render:

    python studio_cli.py editor-demo seal CAPTURE
    python studio_cli.py editor-demo verify CAPTURE
    python studio_cli.py editor-demo render CAPTURE --out NEW_OUTPUT

The generated MP4 can be supplied as real recorded footage in Creator. This is an isolated programmatically operated JUCE instance, not physical mouse capture, SkellyTune capture, or a DAW automation server. The first adapter is gain-only; integrity sealing does not independently establish origin. Local importer fixtures were synthetic; three tests passed, including a real FFmpeg export, plus eight existing measurement bridge tests. Actual producer compile and capture require SkellCore PR #50 CI. No runtime execution of arbitrary plugin binaries.
