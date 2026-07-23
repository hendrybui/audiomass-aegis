from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None  # type: ignore[assignment]

from adapters.librosa_adapter import LibrosaAdapter
from adapters.loudness_adapter import LoudnessAdapter


class AnalysisService:
    """Orchestrates BPM, key/scale, LUFS, peak, duration, and per-stem energy analysis."""

    def __init__(self) -> None:
        self.librosa_adapter = LibrosaAdapter()
        self.loudness_adapter = LoudnessAdapter()

    def analyze(self, job_id: str, job_dir: Path, input_wav: str, stem_paths: dict[str, str]) -> dict:
        """Run full analysis on the canonical input and all produced stems.

        Returns a dict with keys: bpm, key, scale, confidence, lufs_integrated,
        peak_dbfs, duration_sec, stem_energy, and writes analysis/summary.json.
        """
        results: dict = {
            'bpm': None,
            'key': None,
            'scale': None,
            'confidence': None,
            'lufs_integrated': None,
            'peak_dbfs': None,
            'duration_sec': None,
            'stem_energy': {},
        }

        # Tempo + key from canonical input
        tk = self.librosa_adapter.analyze_tempo_and_key(input_wav)
        results['bpm'] = tk['bpm']
        results['key'] = tk['key']
        results['scale'] = tk['scale']
        results['confidence'] = tk['confidence']

        # Loudness from canonical input
        ld = self.loudness_adapter.analyze_loudness(input_wav)
        results['lufs_integrated'] = ld['lufs_integrated']
        results['peak_dbfs'] = ld['peak_dbfs']

        # Duration from canonical input
        results['duration_sec'] = self._get_duration(input_wav)

        # Per-stem RMS energy
        for stem_name, stem_path in stem_paths.items():
            energy = self._compute_rms_energy(stem_path)
            if energy is not None:
                results['stem_energy'][stem_name] = round(energy, 4)

        # Write summary to disk
        analysis_dir = job_dir / 'analysis'
        analysis_dir.mkdir(parents=True, exist_ok=True)
        summary_path = analysis_dir / 'summary.json'
        summary_path.write_text(json.dumps(results, indent=2))

        return results

    def _get_duration(self, audio_path: str) -> float | None:
        try:
            if sf is not None:
                info = sf.info(audio_path)
                return round(info.duration, 3)
        except Exception:
            pass
        return None

    def _compute_rms_energy(self, audio_path: str) -> float | None:
        try:
            if sf is None:
                return None
            data, _ = sf.read(audio_path)
            return float(np.sqrt(np.mean(data ** 2)))
        except Exception:
            return None
