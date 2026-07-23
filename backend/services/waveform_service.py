from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None  # type: ignore[assignment]


class WaveformService:
    """Builds backend waveform summaries (min/max buckets) for fast canvas rendering."""

    # Target number of data points — roughly 1 point per pixel at common widths
    DEFAULT_BUCKETS = 2000

    def generate(self, audio_path: str, output_path: str, *, buckets: int | None = None) -> dict:
        """Read a WAV file and write a JSON waveform summary.

        The output JSON contains:
          { "sample_rate": int, "duration_sec": float, "channels": int,
            "buckets": int, "min": [...], "max": [...] }
        """
        if sf is None:
            raise RuntimeError('soundfile is not installed')

        data, sr = sf.read(audio_path)
        n_samples, n_channels = data.shape if data.ndim > 1 else (len(data), 1)

        # Use left channel for mono representation, or average to mono
        if n_channels > 1:
            mono = np.mean(data, axis=1)
        else:
            mono = data

        n_buckets = buckets or self.DEFAULT_BUCKETS
        # Don't create more buckets than samples
        n_buckets = min(n_buckets, len(mono))

        bucket_size = len(mono) / n_buckets
        min_vals = np.empty(n_buckets)
        max_vals = np.empty(n_buckets)

        for i in range(n_buckets):
            start = int(i * bucket_size)
            end = int((i + 1) * bucket_size)
            if end > len(mono):
                end = len(mono)
            chunk = mono[start:end]
            if len(chunk) == 0:
                min_vals[i] = 0.0
                max_vals[i] = 0.0
            else:
                min_vals[i] = float(np.min(chunk))
                max_vals[i] = float(np.max(chunk))

        duration = len(mono) / sr
        result = {
            'sample_rate': sr,
            'duration_sec': round(duration, 3),
            'channels': n_channels,
            'buckets': n_buckets,
            'min': min_vals.tolist(),
            'max': max_vals.tolist(),
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(result))

        return result

    def generate_for_stems(self, job_dir: Path, stem_paths: dict[str, str]) -> dict[str, str]:
        """Generate waveform summaries for all stems and write to waveforms/ dir.

        Returns a mapping of stem_name -> waveform JSON path.
        """
        wf_dir = job_dir / 'waveforms'
        wf_dir.mkdir(parents=True, exist_ok=True)

        waveform_map: dict[str, str] = {}
        for stem_name, audio_path in stem_paths.items():
            out_path = str(wf_dir / f'{stem_name}.json')
            try:
                self.generate(audio_path, out_path)
                waveform_map[stem_name] = out_path
            except Exception:
                pass  # Skip stems that fail

        return waveform_map
