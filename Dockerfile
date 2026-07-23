# AudioMass AEGIS — Dockerfile
# Adapted from leather147/AudioMass enterprise migration pattern
# Slim Python base, non-root user, layer caching for deps

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/audiomass/.cache/huggingface

# System deps: ffmpeg for audio processing, libsndfile1 for soundfile
RUN apt-get update && \
    apt-get install --no-install-recommends --yes ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 audiomass

WORKDIR /srv/audiomass

# Layer cache: install deps before code
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --requirement requirements.txt

# Copy app code
COPY backend/ ./backend/
COPY src/ ./src/

# Static files served by FastAPI
USER audiomass
EXPOSE 5055

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "5055", "--app-dir", "/srv/audiomass"]
