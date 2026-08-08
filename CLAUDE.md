# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application

```bash
# One-time setup (creates venv, installs ffmpeg, demucs, and Python deps)
./run.sh setup

# Start development server (default port 5055)
./run.sh start

# Start with uvicorn options (e.g., --reload)
./run.sh start --reload

# Or directly with uvicorn
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 5055 --app-dir backend
```

The app serves at `http://localhost:5055/?multitrack=1` for multitrack mode.

### Backend Testing

```bash
cd backend
python -m py_compile app.py          # Syntax check
python -c "import backend.app"        # Import check
```

### Docker

```bash
docker build -t audiomass .
docker run -p 5055:5055 -e AUDIOMASS_PORT=5055 audiomass
```

## Architecture Overview

### Frontend (Vanilla JS, No Build Step)

The frontend (`src/`) loads scripts directly via `<script>` tags in `index.html` — no bundler, no Vite, just edit and reload. Core initialization:

- `app.js` — Main PKAudioEditor singleton, event system, project save/load (`_saveProject`, `_loadProject`)
- `multitrack.js` — Multitrack engine (tracks, clips, timeline, markers, loops, slicing, eraser)
- `engine.js` — Audio engine wrapper around WaveSurfer.js
- `ui.js` — UI components and interaction handling
- `actions.js` — Toolbar actions and menu handlers
- `state.js` — Undo/redo history manager
- `markers.js` — Marker system (M key, MK panel)
- `stems.js` — AI stem separation integration (uploads to backend, SSE progress, loads results)

**Event System**: `fireEvent(eventName, value)` and `listenFor(eventName, callback)` wire modules together. Key events include `Request*` prefixed events that propagate to multitrack.

**State Flow**: Multitrack state → `GetState()` → JSON (minus AudioBuffers) → FormData upload → backend storage. Restoration fetches clip WAVs individually, decodes via AudioContext, then reattaches to state.

### Backend (FastAPI)

`backend/app.py` creates the FastAPI app with:
- `/api/health` — Health check
- `/api/projects` — CRUD for multitrack projects (save/load/delete)
- `/api/jobs` — Job lifecycle for stem separation (upload → SSE progress → results)
- `/` (mount) — Static files from `src/` (catch-all, must be last)

**Services Layer** (`backend/services/`):
- `job_service.py` — Job orchestration, state persistence, cancellation
- `pipeline_service.py` — Threaded audio processing pipeline with adapters
- `project_service.py` — Disk-backed project storage with clip deduplication
- `analysis_service.py` — BPM, key, loudness analysis
- `waveform_service.py` — Waveform peak generation

**Adapters** (`backend/adapters/`): Abstract external tools:
- `demucs_adapter.py`, `optimized_demucs.py` — Stem separation
- `ffmpeg_adapter.py` — Transcoding, format conversion
- `librosa_adapter.py` — BPM/key detection
- `onnx_adapter.py`, `onnx_separator.py` — ONNX model inference

### Project Storage Pattern

Projects are stored as:
- `state.json` — Timeline state (tracks, clips, positions, effects)
- `clips/` directory — Individual WAV files per clip ID
- `meta.json` — Name, timestamps, track/clip counts

This enables clip deduplication across projects and incremental loading.

### Stem Separation Flow

1. Frontend (`stems.js`) encodes current audio to WAV blob
2. Upload to `/api/jobs/upload` with selected stem names
3. Backend creates job, returns `job_id`
4. Frontend opens SSE connection to `/api/jobs/{id}/events`
5. Backend pipeline processes: validate → transcode → separate (Demucs) → post-process
6. SSE events `job_progress` → UI progress bar; `job_done` → load stems into multitrack
7. Stems fetched as individual WAV files via `/api/jobs/{id}/stems/{stem_name}`

## Key File Locations

- `src/index.html` — Frontend entry point, script loading order matters
- `src/app.js` — PKAudioEditor initialization, project save/load logic
- `src/multitrack.js` — Core multitrack engine (2700+ lines)
- `src/stems.js` — Stem separation UI and backend integration
- `backend/app.py` — FastAPI app factory, route mounting
- `backend/services/pipeline_service.py` — Job processing pipeline
- `backend/adapters/optimized_demucs.py` — FP16/compiled Demucs wrapper

## Frontend Module Registration

New frontend modules must register to `PKAE._deps` before `app.js` initializes:

```javascript
(function ( w, d, PKAE ) {
    'use strict';
    function PKMyModule ( app ) { ... }
    PKAE._deps.myModule = PKMyModule;
})( window, document, PKAudioEditor );
```

Then reference in `index.html` script tags.

## Configuration

- `.env.example` — Backend config template (copy to `.env` for local dev)
- `AUDIOMASS_PORT` — Server port (default 5055)
- `DEMUCS_MODEL` — Stem separation model (default `htdemucs`)
- `MAX_CONCURRENT_JOBS` — Prevent OOM (default 2)

## Fork Context

This is the AEGIS fork of [pkalogiros/AudioMass](https://github.com/pkalogiros/AudioMass) with 13+ major DAW-focused additions. See `ROADMAP.md` for planned features and `README.md` for what's new. The codebase maintains MIT license and credits upstream.

## Related Projects (for Pattern Borrowing)

- **leather147/AudioMass** — Enterprise migration with NestJS/Next.js, Docker patterns, CI/CD
- **ComfyUI-AudioMass** — Vite build, i18n localization
- **a83986475/AudioMass** — Chinese translation strings
- **Dance Station** — Embedding integration, file loading fixes

When adding features, check these forks for implementation patterns rather than reinventing.
