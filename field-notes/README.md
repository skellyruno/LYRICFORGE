# Field Notes — The Art of Information

This is SkellyMotion's original film series. Keep the engine general-purpose: Field Notes is a creative production and regression corpus, not another mandatory rendering mode.

## Volume 01
- 01 The Shape of Sound — 2,700 frames, 1280×720, 60 fps.
- 02 The Anatomy of an Image — 3,273 frames, 1280×720, 60 fps.

The Director's Editions are new 720p renders. Preserve the original V13/V14 films and archives. Both films are music-led, not narrated. The source capture and synthetic measurements are explicitly identified.

## Distribution and exact archive import
This branch contains the website source and integrity manifest, not the binary archives. Direct Git access from the production runtime failed DNS; binary transfer through the text-based connector is unavailable. The exact V15 source and screening ZIPs are separately retained in the local production deliverables and recorded in manifest.json. Do not mistake the website source for a playable deployment.

With both archives in a local directory, run:
```sh
python field-notes/verify_package.py /path/to/archives --stage-website /path/to/new-screening-directory
```
This checks both archive hashes, member counts, and the exact website member hashes, then stages a fresh directory. It refuses an existing destination and unsafe members. Serve the staged directory with MP4 byte-range support. Do not publish before creative approval, audio/sample rights review, and playback verification. The TimGM6mb SoundFont provenance is included inside the original screening ZIP; the bank itself is not distributed. No public reference footage or private music should enter the repo.

V15 source is a separately preserved local candidate (140 targeted regressions passed, both frontend smoke suites passed); reconcile changes against the current Creator PR #11 before integrating, preserve newer fixes and build infrastructure, run exact-commit Windows/Linux checks, actual UI capture, and fresh render review. Do not overlay the archive onto a release branch.

## Production slate
| Episode | Subject | Status |
|---|---|---|
| 01 | The Shape of Sound | Polished candidate |
| 02 | The Anatomy of an Image | Polished candidate |
| 03 | The Architecture of Silence | Planned: measured signal/noise, real silent interval, evolving space and musical restraint |
| 04 | The Science of Color | Planned |
| 05 | The Geometry of Time | Planned |
| 06 | The Language of Frequency | Planned |
| 07 | The Illusion of Motion | Planned |
| 08 | The Art of Distortion | Planned |

Every film should have a reviewed script, original or rights-cleared assets, explicit provenance, a reusable editable plan, actual encoded QC, poster and accessible text summary. Continue work on arbitrary textured geometry, smooth object continuity, local vision and neural voice adapters, expressive scoring, and automatic quality repair. Keep the Creator interface simple. Fresh neural inference remains blocked locally by missing runtime/weights. Neither the full V15 integration nor public publication is verified.
