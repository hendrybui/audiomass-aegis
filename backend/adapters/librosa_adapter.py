from __future__ import annotations

import numpy as np

try:
    import librosa
except ImportError:
    librosa = None  # type: ignore[assignment]

# Krumhansl-Schmuckler key profiles (major / minor)
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


class LibrosaAdapter:
    """Analyzes tempo (BPM) and musical key/scale with confidence."""

    def analyze_tempo_and_key(self, audio_path: str) -> dict:
        if librosa is None:
            return {'bpm': None, 'key': None, 'scale': None, 'confidence': None}

        y, sr = librosa.load(audio_path, sr=22050, mono=True)

        bpm = self._estimate_bpm(y, sr)
        key, scale, confidence = self._estimate_key(y, sr)

        return {
            'bpm': round(bpm, 1) if bpm else None,
            'key': key,
            'scale': scale,
            'confidence': round(confidence, 3) if confidence else None,
        }

    def _estimate_bpm(self, y: np.ndarray, sr: int) -> float | None:
        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
            beats_plp = librosa.beat.beat_track(y=y, sr=sr, onset_envelope=onset_env)
            tempo = float(beats_plp[0]) if isinstance(beats_plp[0], (int, float, np.floating)) else float(beats_plp[0][0])
            if tempo <= 0:
                return None
            # Normalize to reasonable range (60–200 BPM)
            while tempo > 200:
                tempo /= 2
            while tempo < 60:
                tempo *= 2
            return tempo
        except Exception:
            return None

    def _estimate_key(self, y: np.ndarray, sr: int) -> tuple[str | None, str | None, float | None]:
        try:
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            chroma_avg = np.mean(chroma, axis=1)  # (12,)

            best_key: str | None = None
            best_scale: str | None = None
            best_corr: float = -1.0

            for shift in range(12):
                rotated = np.roll(chroma_avg, -shift)

                corr_major = float(np.corrcoef(rotated, MAJOR_PROFILE)[0, 1])
                if np.isnan(corr_major):
                    corr_major = 0.0
                if corr_major > best_corr:
                    best_corr = corr_major
                    best_key = NOTE_NAMES[shift]
                    best_scale = 'major'

                corr_minor = float(np.corrcoef(rotated, MINOR_PROFILE)[0, 1])
                if np.isnan(corr_minor):
                    corr_minor = 0.0
                if corr_minor > best_corr:
                    best_corr = corr_minor
                    best_key = NOTE_NAMES[shift]
                    best_scale = 'minor'

            return best_key, best_scale, best_corr
        except Exception:
            return None, None, None
