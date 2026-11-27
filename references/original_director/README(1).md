# autoedit: autonomous explainer / plugin-demo editor

Keep `autoedit.py` and `director_prompt.md` in the same folder.

    voiceover.wav + assets/  ->  Whisper words  ->  Claude edit plan (plan.json)  ->  ffmpeg render  ->  final.mp4

## Setup

    ffmpeg + ffprobe on PATH
    pip install pillow numpy faster-whisper anthropic
    export ANTHROPIC_API_KEY=...
    optional, for diagram scenes: rsvg-convert (librsvg) or cairosvg or ImageMagick

## Run

    # 1. everything in one go (transcribe -> direct -> render)
    python autoedit.py make --audio vo.wav --assets ./assets --preset plugin \
        --brief "Riverflux Audio. Spatial EQ plugin walkthrough, calm and precise, for mixing engineers." \
        --music bed.mp3 --out final.mp4

    # 2. fast draft (960x540) while you iterate
    python autoedit.py make ... --preview

    # 3. hand-edit work_vo/plan.json, then re-render. Only changed scenes are re-rendered.
    python autoedit.py render --audio vo.wav --assets ./assets --preset plugin --out final.mp4

    # other commands: transcribe, direct, validate (checks a plan without rendering)

Presets: `doc` (documentary essay) and `plugin` (product walkthrough). Both are defined in the `PRESETS`
dict at the top of the script (colours, text sizes, caption position).

## Assets

Put screenshots, plugin UI shots, screen recordings, b-roll and logos in `assets/`.
Give the director better information by adding a `.txt` next to a file with one line describing it
(`plugin_eq.png` + `plugin_eq.txt`: "Spatial EQ main window, band 1 selected, depth at 100%").
Without it, only the file name is used.

If the director wants footage you do not have, the scene renders a labelled placeholder
("[ b-roll wanted ] ...") and you drop the file in and re-render.

## Plan format

See `director_prompt.md` for all scene types and fields (broll, document, quote, big_text, stat,
ui_demo, diagram, outro). It is plain JSON, so you can write or edit scenes by hand.

## What the two reference videos taught the presets

Measured with ffmpeg scene detection (approximate), visuals judged from contact sheets:
- Documentary essay (about 11 min): around 128 cuts, 5 s average shot, nothing over about 14 s. Footage
  with blurred logos, article screenshots with yellow marker highlights, year stamps, quote cards,
  a big stat, chapter cards. Caption-led, sparse white text at the bottom.
- Plugin walkthrough (about 6 min): around 27 cuts, 12 s average shot (median about 9 s). The plugin
  UI is the hero, gold capitals titles with a lower-case sub-line, simple diagrams that show the
  mechanism, redacted user comments, a branded outro.

Edit the numbers in `director_prompt.md` (the "Pace" lines) if you want it faster or slower.

## Known limits

- The director cannot see your images. It places highlight boxes from descriptions only, so check
  `document` scenes. `redact` boxes in particular should be checked before publishing.
- Cuts snap to sentence boundaries from Whisper. If the voiceover has long pauses, trim them first.
- No automatic sound effects or word-by-word animated captions. Captions are short phrases chosen by the director.
- Scene render is cached by content. If you change the code, bump `CACHE_VER`.
