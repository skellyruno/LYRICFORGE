#!/bin/sh
set -eu
# Railway attaches persistent volumes with root ownership. Fix ownership, then
# drop privileges for ALL user uploads, ASR inference and FFmpeg processing.
mkdir -p /data/workspace /data/model-cache
chown -R appuser:appuser /data
exec gosu appuser uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
