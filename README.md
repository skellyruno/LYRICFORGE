# LYRICFORGE — AI lyric video studio

**Upload a song → AI transcript → review & confirm lyrics → adjust timing → style, animate and change backgrounds → export a synced MP4.**

Two distributions are included in this repository:

| | Online studio | Windows portable app |
|---|---|---|
| Code | `server.py`, `static/` | Same app, packaged by PyInstaller |
| Runs on | Railway Docker deployment | Windows x64, localhost only |
| Login | Owner-only password over HTTPS | None, binds to `127.0.0.1` |
| Storage | Persistent `/data` volume | `%LOCALAPPDATA%/LyricForge` |
| Release | Railway deploys commits from GitHub | GitHub Actions ZIP; version tags publish Releases |

## Getting started

**[Complete GitHub + Railway + Windows setup](docs/DEPLOY.md)** — follow this step-by-step guide to publish both versions.

## Editing features

- MP3/WAV/M4A/FLAC etc. imports (max 250 MB, 15 minutes)
- Automatic speech-to-text lyrics using faster-whisper, with approximate word timestamps
- Explicit review and confirm step before video creation
- Editable lyric clips and timing, with waveform timeline
- Full line / per-word / karaoke lyric display
- Pop, fade, slide and typewriter effects
- Fonts, colors, size, outline, text position, backgrounds and portrait/square/landscape
- 720p / 1080p MP4 video output via FFmpeg

**Limitations:** Whisper is not specialized for sung vocals, and corrected words are interpolated rather than audio-forced-aligned; some timing will need manual tweaks. The cloud site is **owner-only**. It has no multi-user accounts, rate limiting, queue persistence, billing or production-grade untrusted-media sandbox. Windows packaging is automated but must be verified on a Windows machine.

## Local development

Install Python 3.11 or 3.12 and FFmpeg (including libass), then:

```bash
python -m pip install -r requirements.txt pytest httpx
python -m pytest tests -q
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Visit `http://127.0.0.1:8000`. On Windows you can also run `RUN-WINDOWS.bat` (requires preinstalled Python and FFmpeg).

> Never put your own song files, API keys or passwords into the GitHub repository. The `.gitignore` omits private media, local project storage, the AI model cache and `.env` files.
