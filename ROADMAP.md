# AudioMass AEGIS — Development Roadmap

## Current State (v0.1.0 — July 2026)

### What We Have
- Forked from pkalogiros/AudioMass (MIT, commit 8d36300, May 13 2026)
- 13 major feature additions over upstream
- Vanilla JS frontend, Python FastAPI backend
- No build step — edit src/*.js and reload

### Features Already Built
1. Marker system (M key, MK panel, ruler overlays, undo/redo)
2. Loop table (LP panel, 4/8/16 bar quick loops)
3. Slice to sampler (SL panel, context menu slicing)
4. Eraser mode (toggle, click-to-delete, crosshair cursor)
5. Silence clip (right-click → zero buffer)
6. Multi-clip selection + group drag (Shift+select, snap-aware)
7. BPM auto-detect → beat grid (tempo estimator, >15% confidence)
8. Brighter beat grid (3x visibility)
9. Project save/load (FastAPI backend, WAV encoding, FormData upload)
10. Download all stems (one-click export)
11. In-browser WAV encoder (_audioBufferToWavBlob)
12. stems.js module (AI stem separation integration)
13. embed.js module

### Ecosystem Position
- Only fork focused on DAW feature enhancement
- leather147: enterprise/SaaS rewrite (NestJS/Next.js) — different direction
- ComfyUI-AudioMass: integration wrapper, Vite build, i18n — patterns to borrow
- a83986475: Chinese localization — i18n reference
- Dance Station: embedding integration, file loading fixes — patterns to borrow
- 322 other forks: dead copies

---

## Phase 1 — Foundation (Next Priority)

### 1.1 Docker Deployment
- Containerize the full stack (frontend + FastAPI backend)
- Single Dockerfile, docker-compose for dev/prod
- Volume mounts for /exports and /samples
- Borrow patterns from leather147's Docker setup

### 1.2 CI/CD Pipeline
- GitHub Actions workflow: lint + test on PR
- Auto-deploy on push to production branch
- Borrow patterns from leather147's CI config

### 1.3 Vite Build System (Optional)
- Migrate from raw script tags to Vite
- Benefits: ES modules, hot reload, minification, tree-shaking
- Risk: breaking existing inline script dependencies
- Study ComfyUI-AudioMass's Vite config first

### 1.4 Fix Upstream Bugs
- Cherry-pick zero-crossing selection from upstream (May 25)
- Cherry-pick z-index fix for dockable elements
- Cherry-pick paragraphic EQ multitrack bug fix
- Cherry-pick auto-scroll on new channel

---

## Phase 2 — Audio Production Features

### 2.1 Keyboard Shortcuts Panel
- Visual overlay showing all shortcuts
- Customizable key bindings
- Save/load shortcut presets

### 2.2 Automation Lanes
- Volume automation per track
- Pan automation per track
- Draw curves directly on timeline
- Borrow concept from REAPER/Logic automation lanes

### 2.3 Better Mixer
- Channel strips with EQ, compressor, reverb sends
- Solo/mute automation
- Master bus with limiter
- VU meters per channel (peak + RMS)

### 2.4 Clip Gain Envelopes
- Per-clip volume control
- Fade in/out handles directly on clip
- Drag envelope points on waveform

### 2.5 Time Stretching
- Change clip speed without changing pitch
- WSOLA or phase vocoder algorithm
- Right-click clip → "Stretch to tempo"

### 2.6 Pitch Shifting
- Change pitch without changing speed
- Per-clip or per-track
- Semitone + cents control

---

## Phase 3 — AI Integration

### 3.1 Demucs Stem Separation (In-App)
- Upload audio → click "Separate Stems" → get 4 tracks
- Vocal, drums, bass, other
- Progress bar during separation
- Auto-load stems into multitrack
- Backend already has demucs_adapter.py — wire up frontend

### 3.2 AI Mastering
- One-click mastering pipeline
- LUFS normalization to target (-14 LUFS for streaming)
- Multiband compression
- Stereo widening
- Loudness matching

### 3.3 BPM Detection Improvement
- Improve tempo estimator accuracy
- Support half-time/double-time detection
- Confidence threshold adjustment
- Tap tempo fallback

### 3.4 Key Detection
- Detect musical key of audio clip
- Camelot wheel notation for DJs
- Display key on track header

### 3.5 Smart Beat Matching
- Auto-align clips to nearest beat
- Detect downbeat (beat 1)
- Auto-sync tempo between clips

---

## Phase 4 — UX Polish

### 4.1 Dark/Light Theme Toggle
- Current UI is dark-only
- Add CSS variables for theming
- Save preference in localStorage

### 4.2 i18n / Multi-Language
- Extract all UI strings to JSON locale files
- Study ComfyUI-AudioMass and a83986475's approaches
- Start with EN + ZH (Chinese) — Henry's audience

### 4.3 Undo History Panel
- Visual history stack
- Click any state to jump back
- Named checkpoints ("before vocal cut", "after EQ")

### 4.4 Waveform Color Coding
- Different color per track
- Stereo channels in different shades
- Frequency-colored waveform (spectrogram overlay)

### 4.5 Mobile Responsiveness
- Touch gestures: pinch zoom, swipe scroll
- Collapsible panels
- Portrait/landscape layouts

---

## Phase 5 — Collaboration & Cloud

### 5.1 Cloud Project Sync
- Save projects to cloud storage (S3, R2, or local)
- Share project links
- Version history

### 5.2 Real-time Collaboration
- WebSocket-based multi-user editing
- See other users' cursors
- Track-level permissions

### 5.3 Plugin System
- Study leather147's plugin SDK concept
- Allow third-party audio effects
- JS audio worklet plugins
- Plugin marketplace concept

### 5.4 Export Formats
- Multi-track export (each track as separate file)
- Stem export with metadata (BPM, key, time signature)
- Project archive (.zip with all files + project.json)
- Export to DaVinci Resolve timeline XML
- Export to REAPER RPP format

---

## Phase 6 — Advanced DAW Features

### 6.1 MIDI Support
- Import MIDI files
- Display MIDI as piano roll
- Route MIDI to synths (Web Audio API)
- Export multitrack as MIDI

### 6.2 Sampler Instrument
- Map slices to MIDI notes
- Play slices via keyboard
- Save as instrument preset
- Integration with Aether synth

### 6.3 Effects Chain
- Per-track effects rack
- Drag to reorder effects
- Bypass individual effects
- Save effect chains as presets

### 6.4 Sidechain Compression
- Duck one track based on another
- Classic EDM pumping effect
- Visual threshold display

### 6.5 Spectral Editing
- Frequency-domain editing
- Remove specific frequencies (noise reduction)
- Spectral repair
- Brush tool for spectral painting

---

## Borrowing From Ecosystem

### From leather147
- Docker containerization patterns
- CI/CD GitHub Actions workflow
- Python processing service structure
- Cloud storage abstraction

### From ComfyUI-AudioMass
- Vite build configuration
- i18n/localization framework
- Embedding patterns (AudioMass as component)

### From a83986475
- Chinese translation strings (ready to import)
- i18n string extraction methodology

### From Dance Station
- File loading via blob paths (bug fix)
- WaveSurfer asset path handling
- Overlay file picker integration

### From upstream (pkalogiros)
- Zero-crossing selection (cherry-pick)
- z-index fix for dockable elements
- Paragraphic EQ multitrack fix
- Auto-scroll on new channel

---

## Versioning

- v0.1.0 (current) — Fork with 13 feature additions
- v0.2.0 — Phase 1 (Docker, CI/CD, upstream fixes)
- v0.3.0 — Phase 2 (automation, mixer, time stretch)
- v0.4.0 — Phase 3 (Demucs in-app, AI mastering)
- v0.5.0 — Phase 4 (themes, i18n, mobile)
- v1.0.0 — Phase 5 complete (cloud sync, plugin system)

---

## Notes

- Henry is not a coder — all implementation by AEGIS + workers
- Quality > speed — build carefully, test thoroughly
- Music pipeline: AudioMass → Remix Engine → DaVinci Resolve
- Aether synth integration is a long-term goal
- Always maintain MIT license and credit pkalogiros
