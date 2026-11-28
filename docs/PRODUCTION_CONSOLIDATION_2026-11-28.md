# Consolidated production candidate — 2026-11-28

Based on the previously verified 67.41 MB semantic build, plus the separately verified visual review and temporal scouting. Chatterbox is optional; Kokoro stays the default. The earlier expression workflow accidentally folded its second shell command into the first; corrected in a3ae0d5, requiring actual Creator report and WAV digests. Do not treat the earlier native model audition as an end-to-end Creator pass.

New opt-in deep review fully decodes both streams and checks actual decoded frame count; measures integrated LUFS, true peak and loudness range, and warns about a broad promotional loudness range. It does not normalize or rewrite output. Tested with real Skelliere continuous interaction, V4 showcase and cue-aligned montage; quiet montage flagged. Normal export path unchanged. Model/weight packages remain external. No merge to production or release tag.
