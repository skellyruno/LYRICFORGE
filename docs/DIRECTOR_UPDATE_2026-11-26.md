# Local Scene Director and close/zoom polish
- Offline scene planning inspired by the supplied autoedit.py and director prompt. Shot selection uses transcript boundaries and user-supplied filenames/descriptions, not image recognition.
- Plugin / documentary styles, image and video assets, contained UI/document shots, captions, animated stills, optional ducked Brand Kit music, 15-second proof and cached scene rendering.
- Existing lyric editor and project data remain intact. No untrusted inline SVG, no fabricated redactions, no cloud key or external uploads.
- Empty timeline can be preserved during review; Keep recovery & close never deletes a project. Explicit discard continues to reject active transcription to protect its source. Native close requests are deduplicated, with recovery-only fallback if the bridge cannot open the dialog.
- Adaptive shared viewport scales editor and modal overlays together. Skull favicon/header and generated Windows multi-resolution ICO.
- WIP-only tools preserved in separate larger source archive; this is selective integration on the release branch. Verify exact CI and real screenshots before merging. Active inference may take time to finish after closing the window.
