# SkellyHub icon integration — 2026-11-26

Source: user-supplied SkellyHub v0.12 Quick4 Integration Full Package, hub/ui/skelly-skull.png (220×220 RGBA, Git blob 670bb5beff9092e116783c3198dda72e45afee01). The bundled 128×128 transparent PNG is a resampled, palette-optimized derivative of that artwork, not a new skull design. Windows packaging regenerates 16–256px ICO entries from it. Existing legacy skull SVG/ICO are retained for compatibility; the old committed ICO is replaced by the generator at build time. Source-mode launch before running the generator may use that old ICO. The favicon and in-app mark use the new PNG immediately.

Toolbar and rail actions use consistent local stroke icons with the existing labels and button IDs; no external icon dependency, screenshot substitution, feature removal, or palette-wide redesign. Quick4 plugin artwork is not bundled in this upload and no actual native plugin capture is claimed.

Release checks: generate and decode all seven ICO resolutions; native window checks verify the shared logo loads. New visual evidence from the exact candidate is still required.
