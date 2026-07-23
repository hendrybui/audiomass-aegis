# Backend

FastAPI-based API and job orchestration layer for Splinter-x.

## Current Phase 1 capability
- disk-backed job lifecycle
- request persistence
- threaded pipeline progression
- multipart upload intake endpoint
- cancellable subprocess tracking
- placeholder-friendly separation flow with real adapter wiring paths
- manifest and snapshot persistence

## Important note
Real external tool execution depends on local availability of:
- yt-dlp
- ffmpeg
- demucs

When tools are unavailable, the current pipeline can still fall back in selected places for development continuity, but final product behavior will require these binaries.

## Run target
```bash
uvicorn app:app --reload --app-dir backend
```
