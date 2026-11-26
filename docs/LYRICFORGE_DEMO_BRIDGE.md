# SkellCore → LyricForge measured demo (v1)

This is opt-in offline evidence, not a DAW remote-control server. It does not modify installed plugins or presets. The recorder never belongs in the realtime callback: call after each offline processing block, collect actual meter values, and write files on the capture thread. Future JUCE adapters must make host-notified parameter changes on the appropriate thread and capture actual parameter readback and editor frames. No arbitrary commands, plugin loading, mouse automation, network or production state mutation is implemented here.

Portable example, from the SkellCore repository root:

```sh
g++ -std=c++17 -O2 -I SkellCore/include tools/SkellDemoRender.cpp -o SkellDemoRender
./SkellDemoRender new-capture EXACT_40_HEX_SOURCE_REVISION 0 0.5 1
```

The output is mono PCM16 `dry.wav`, `processed.wav`, `sidechain.wav`, `events.csv`, `meters.csv`, `capture.json`. All share a 48 kHz sample clock. The three four-second stages apply real normalized amount commands to `LiveMultibandDucker`; the meter values are actual `copyDisplayBands` snapshots, with float audio RMS and peaks measured after processing. The capture is synthetic and offline, not a benchmark of a shipping plugin, actual DAW or a real song. Intrinsic latency is the engine's declared contract, not measured device/host latency. `events.csv` logs accepted commands, not independently read-back parameters. The source revision must describe the engine actually built. The trace format is specialized to this ten-band adapter; additional effects need explicit metric schemas. No changes to DSP or automation IDs.

In LyricForge:

```sh
python studio_cli.py demo seal new-capture
python studio_cli.py demo verify new-capture
python studio_cli.py demo render new-capture --out new-video
```

The seal is an integrity check, not proof of origin. LyricForge validates sample clocks, CSV fields/ranges, hashes, RMS and peaks against the audio. It will not trust guessed measurements or launch arbitrary executables. It renders the processed audio and actual band meters synchronized to the sample clock. Use the original dry file for an aligned A/B; do not mistake gain reduction for loudness-matched listening.
