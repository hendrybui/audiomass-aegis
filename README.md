# AudioMass — AEGIS Fork

Forked from [pkalogiros/AudioMass](https://github.com/pkalogiros/AudioMass) (MIT License).

A web-based multitrack audio editor with significant enhancements for music production workflows.

## What's New in This Fork

### Multitrack Enhancements

- **Marker System** — Press `M` to drop a marker at the cursor. MK panel for list, rename, goto, delete. Yellow overlays on ruler.
- **Loop Table** — Save regions as loops. Quick-loop buttons for 4/8/16 bars. Play, rename, delete.
- **Slice to Sampler** — Right-click any clip → slice into 4/8/16/beat/bar pieces. Each slice becomes an individual clip.
- **Eraser Mode** — Toggle eraser, click any clip to delete. Full undo support.
- **Silence Clip** — Right-click → zero out audio buffer while keeping the clip in the timeline.
- **Multi-Clip Selection & Group Drag** — Shift+click to select multiple clips, drag them together with snap awareness.
- **BPM Auto-Detect** — Tempo estimator auto-sets the beat grid BPM when confidence > 15%.
- **Brighter Beat Grid** — Sub-beat lines 3x more visible (28% cyan), bar lines 2.5x (55% yellow).

### Project Save/Load

- Full project persistence via FastAPI backend
- Audio buffers encoded as WAV and uploaded to server
- Project list modal with load and delete
- Clip-by-clip audio restoration on load

### Export

- **Download All Stems** — One-click export of all tracks as separate WAV files
- In-browser WAV encoder (no external library needed)

### New Modules

- `stems.js` — AI stem separation integration
- `embed.js` — Embedding support

## Original Features (from upstream)

- Full waveform editor with cut, copy, paste, fade, normalize
- Multitrack mode with drag, crossfade, recording
- Effects: compressor, reverb, normalize, paragraphic EQ
- Tempo estimation with autocorrelation BPM detection
- MP3/WAV/FLAC export
- .amss session format
- Mobile touch support

## Tech Stack

- **Frontend:** Vanilla JavaScript, CSS, HTML (no frameworks)
- **Backend:** Python FastAPI (uvicorn)
- **No build step** — edit `src/*.js` and reload

## Running

```bash
cd audiomass
AUDIOMASS_PORT=5055 .venv/bin/uvicorn app:app --host 0.0.0.0 --port 5055 --app-dir backend
```

Then open `http://localhost:5055/?multitrack=1` in your browser.

## Credits

- **Original author:** [Pantelis Kalogiros (pkalogiros)](https://github.com/pkalogiros)
- **Fork enhancements:** Henry Bui ([hendrybui](https://github.com/hendrybui)) — built with AEGIS

## License

MIT — see [LICENSE](LICENSE)
