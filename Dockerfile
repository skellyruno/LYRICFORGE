# Single-user, password-protected SkellyMotion website (not a multi-tenant service).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LYRICFORGE_REQUIRE_AUTH=1 \
    LYRICFORGE_DATA=/data/workspace \
    HF_HOME=/data/model-cache \
    WHISPER_MODEL=small
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core fonts-liberation ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY server.py studio_performance.py studio_clips.py ./
COPY static/ ./static/
RUN useradd --uid 10001 --create-home appuser && mkdir -p /data /app && chown -R appuser:appuser /app
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
