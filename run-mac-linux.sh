#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first'; exit 1; }
command -v ffprobe >/dev/null || { echo 'Install ffprobe first'; exit 1; }
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
printf 'Open http://127.0.0.1:8000 in your browser\n'
exec .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
