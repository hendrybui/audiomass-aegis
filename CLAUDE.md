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

# Host-side unit tests for EVERY plugin's internals (htdemucs worker-stats
# parsing + pool-stats load/persist; analyze duration/RMS + progress spans;
# waveform bucket math; transcribe note mapping/rounding + error paths), the
# pipeline's phase-to-progress aggregation (each plugin span maps into its
# aggregate window and tiles the checkpoints), the pipeline's cancel + failure
# routing (mid-plugin/boundary cancels land in mark_cancelled; non-cancel
# errors land in mark_failed with the friendly message — neither starts the
# next phase, both run cleanup), and the finally-block teardown (clear +
# log-handler detach run even when the terminal-state write raises) — no
# GPU/docker/server required. Also runs as part of the repo-root `npm test`
# via tests/plugin-units.test.mjs.
PYTHONPATH=. ../.venv/bin/python -m unittest discover -s ../tests -v
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

### Processing Plugins

Processing capabilities (separation, transcription, future effects) register in
`backend/plugins/` as named capabilities behind one uniform contract:

- `base.py` — `AudioPlugin`, `PluginContext` (params, work_dir, progress/log
  callables, `is_cancelled`), `PluginError`, `CancelledError`
- `registry.py` — `plugin_registry` singleton; `require(name)` / `names()`
- `htdemucs_plugin.py`, `transcribe_plugin.py`, `analyze_plugin.py`,
  `waveform_plugin.py` — built-ins, self-register on import

A plugin is a class with `name`/`description` and `run(ctx) -> dict`. The
pipeline drives `htdemucs` via `_separate_stems()` (0.55–0.80 span),
`analyze` via `_analyze_stems()` (0.88–0.92 span, per-step progress:
tempo/key, loudness, duration, per-stem energy) and `waveform` via
`_generate_waveforms()` (0.92–0.95 span, one step per stem); the
`/api/transcribe` endpoint drives `transcribe` directly. Every job phase
now flows through the registry — the pipeline's only direct work left is
ffmpeg transcode/mixdown and the phase orchestration itself. Cancellation is
uniform: plugins poll `ctx.is_cancelled()` and raise `CancelledError`; the
htdemucs plugin additionally registers its worker child process with
`cancellation_service` so cancel SIGTERMs it immediately. Adding a plugin:
drop a module in `plugins/`, register an instance, import it in
`plugins/__init__.py` — the pipeline/endpoints need no changes unless a new
job phase is required.

### ROCm container backend (GPU separation on gfx803 / RX 580)

Host torch has no working backend for this Polaris card, but this box has a
from-source ROCm 6.4 + PyTorch 2.4 container build that does (see
`/mnt/Pandora/Workshop/GFX803_Rocm`). `adapters/docker_runtime.py` runs the
separation worker inside that container when configured, and the plugin falls
back to the local CPU worker automatically otherwise:

- Build the demucs layer once: `docker build -f docker/Dockerfile.demucs-rocm
  -t rocm64_gfx803_demucs:2.4 .`
- Enable it: `AUDIOMASS_DEMUCS_DOCKER_IMAGE=rocm64_gfx803_demucs:2.4`
  (daemon must be running; device nodes `/dev/kfd` + `/dev/dri` and the
  gfx803 env overrides are injected by the adapter)
- Availability is probed per job (cached 30s); when docker/image/daemon is
  missing the worker runs locally on CPU with the exact same job semantics
  (progress JSONL, live logs, cancel). Container mode reports `device=cuda`;
  the CLI fallback is forced to CPU (host has no CUDA).
- The container is bind-mounted at host paths (no path translation), named
  `audiomass-demucs-<job_id>`, and killed by name on cancel (killing the
  `docker run` CLI alone would leave it running). The worker runs as the
  **host user** (`--user`) with numeric `video`/`render` GIDs resolved from
  the host (name-based `--group-add` grants the image's GIDs, which can
  differ — this box: render=992 host vs 109 image — and GPU init then fails
  with "CUDA not available"). Three host caches are mounted at
  `/opt/cache/*` (pinned via `TORCH_HOME`/`HF_HOME`/`MIOPEN_USER_DB_PATH`,
  since the unprivileged user can't write under the 0700 `/root`) so
  per-job fixed costs stay low: HuggingFace hub + torch hub (model weights),
  and the MIOpen kernel cache — without it every ephemeral container
  recompiles kernels for this card, ~40s/job. Once weights are cached the
  worker runs with `HF_HUB_OFFLINE=1` to skip the per-job hub ping.
- Measured on this box (60s track, `rocm64_gfx803_demucs:2.4`): CPU
  separation ~55s; GPU compute ~7s (0.12x realtime) after a ~35-40s fixed
  per-container startup (python+torch+HIP init+warmup). Long tracks get
  the win — a 20-min track goes from ~18 CPU minutes to ~3 GPU minutes;
  very short tracks are dominated by the fixed startup.
- **Warm pool**: instead of a fresh container per job, the plugin can start
  `demucs_pool_server.py` inside a persistent container
  (`audiomass-demucs-pool`) that keeps the loaded separator alive and
  serves jobs over a file protocol under `<JOBS_DIR>/_pool`
  (`request.json` in; the same JSONL progress out; `cancel_<job_id>`
  markers; heartbeat/shutdown liveness). The ~35s startup is paid once per
  container generation: measured on this box, back-to-back 12-30s tracks
  go ~35-60s (cold) -> ~3-5s (warm), with the model loaded exactly once.
  The supervisor exits on a stale heartbeat (server gone), the shutdown
  marker, or **idle eviction** — after `AUDIOMASS_POOL_IDLE_TIMEOUT`
  (default 600s) with no job it exits and the `--rm` container is removed,
  so the GPU is released when nobody is bouncing. The exit reason is
  recorded in `<JOBS_DIR>/_pool/evicted` (`idle` / `stale_heartbeat` /
  `shutdown`) for diagnostics until the next generation. One caveat: the
  pool container name is fixed, so a live pool belongs to whichever
  AudioMass started it.
- **One-command GPU check**: `../check-demucs-gpu.sh` (project root) starts
  docker if needed, ensures the demucs image (building the layer from
  `docker/Dockerfile.demucs-rocm` if only the base exists), then runs two
  real back-to-back separations through the warm pool on a short generated
  track and verifies both jobs finished with all 6 stems, the model loaded
  exactly once, and the pool still up. Exits non-zero with a message on
  failure; refuses to run if a pool container is already live (it would
  dispatch into the wrong instance's mounts). `--nightly` (used by the
  scheduled check below) turns environment-not-ready states — docker daemon
  down, a live pool from another instance — into logged skips (exit 0)
  instead of false alarms, and its cleanup never kills a pool it didn't
  start.
- **Nightly regression check**: `systemd/demucs-gpu-check.{service,timer}`
  (project root) run `check-demucs-gpu.sh --nightly` at 03:30 daily as a
  user timer (`Persistent=true` catches up after suspend/off; linger is
  enabled so it runs without a login session). Real failures exit non-zero
  into the user journal. Install: `cp systemd/*.service systemd/*.timer
  ~/.config/systemd/user/ && systemctl --user enable --now
  demucs-gpu-check.timer`. `docker.service` is enabled at boot on this box,
  so the daemon is up at 03:30 and the full regression runs; a SKIP only
  appears if the daemon crashed overnight or a pool from another instance
  is live.
- `GET /api/diagnostics` (both the FastAPI and the stdlib entry points)
  reports `separation`: which engine the next job uses (`rocm_container`
  vs `cpu_worker`), the image, container availability + reason, and
  `last_job` — measured wall/ready/compute/overhead/audio/realtime from
  the most recent container run (recorded by the htdemucs plugin after
  each successful container job). It also reports `warm_pool` — live state
  of the persistent pool container: `up` (probed per call), `busy`,
  `jobs_served` (CUMULATIVE across server restarts — persisted in
  `<JOBS_DIR>/_pool/stats.json` after each pool job), the one-time
  `ready_sec` startup the current generation paid, `idle_timeout_sec` (the
  configured eviction window), `first_seen_at`/`last_activity_at` (history
  anchors), `eviction` + `evicted_at` (why the last container generation
  ended), and `last_job` (whose `overhead_sec` is near-zero, proving
  startup is not re-paid). The Aether bridge renders all of this as the
  engine indicator in the AudioMass panel.

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
- `AUDIOMASS_DEMUCS_DOCKER_IMAGE` — ROCm container for GPU separation
  (optional; unset = local CPU worker). Related: `AUDIOMASS_DEMUCS_DOCKER_DEVICES`
  (default `/dev/kfd,/dev/dri`), `AUDIOMASS_DEMUCS_DOCKER_ENV` (extra `K=V`
  pairs, space-separated). See the container backend section above.

## Fork Context

This is the AEGIS fork of [pkalogiros/AudioMass](https://github.com/pkalogiros/AudioMass) with 13+ major DAW-focused additions. See `ROADMAP.md` for planned features and `README.md` for what's new. The codebase maintains MIT license and credits upstream.

## Related Projects (for Pattern Borrowing)

- **leather147/AudioMass** — Enterprise migration with NestJS/Next.js, Docker patterns, CI/CD
- **ComfyUI-AudioMass** — Vite build, i18n localization
- **a83986475/AudioMass** — Chinese translation strings
- **Dance Station** — Embedding integration, file loading fixes

When adding features, check these forks for implementation patterns rather than reinventing.
