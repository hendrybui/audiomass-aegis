"""HTDemucs stem separator running directly in-process via PyTorch.

CPU-focused: inference is kept in float32 (FP16 is a no-op or slower on most
CPUs and the previous `torch.compile(mode="reduce-overhead")` path is a GPU
optimisation that costs several minutes of one-time compilation on CPU — far
more than it ever saves). The model is loaded once and reused across jobs.

All progress is emitted through the stdlib `logging` module so it can be
captured into the per-job pipeline log instead of vanishing on stdout.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import torch
import soundfile as sf

log = logging.getLogger("audiomass.demucs")

STEM_NAMES = ["drums", "bass", "other", "vocals", "guitar", "piano"]
SAMPLE_RATE = 44100
# HTDemucs internal segment: 39/5 seconds at 44100 Hz
CHUNK_SAMPLES = int(44100 * 39 / 5)  # 343980


class OptimizedDemucs:
    """Runs HTDemucs in-process. Construct once and reuse across jobs."""

    def __init__(self, model_name: str = "htdemucs_6s", compile_model: bool = False):
        from demucs.pretrained import get_model

        # CRITICAL: When PyTorch runs in Python daemon threads (via pipeline),
        # its OpenMP backend can conflict with Python threading, causing crashes.
        # Limiting to 1 thread prevents this without significant performance loss
        # for CPU inference (the bottleneck is I/O and model ops, not threading).
        torch.set_num_threads(1)

        # `compile_model` is accepted for backwards compatibility but ignored:
        # torch.compile(mode="reduce-overhead") targets GPUs and adds a multi-
        # minute compile + warmup cost on CPU with no payoff.
        if compile_model:
            log.warning(
                "torch.compile requested but disabled on CPU "
                "(it adds minutes of compile time with no CPU speedup)."
            )

        log.info("Loading %s ...", model_name)
        t0 = time.time()
        bag = get_model(model_name)
        self.model = bag.models[0]
        self.model.eval()
        self.model.use_train_segment = False  # allow arbitrary-length input

        self.device = torch.device("cpu")

        # Tiny warmup so the first real chunk isn't paying lazy-init costs.
        log.info("Warming up ...")
        dummy = torch.randn(1, 2, 44100, device=self.device, dtype=torch.float32)
        with torch.no_grad():
            _ = self.model(dummy)
        log.info("Ready in %.1fs.", time.time() - t0)

    def separate(
        self,
        input_path: str,
        output_dir: str,
        *,
        progress_callback=None,
    ) -> dict[str, str]:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Load audio
        audio, sr = sf.read(input_path, dtype="float32")
        if audio.ndim == 1:
            audio = np.stack([audio, audio], axis=0)
        elif audio.ndim == 2:
            audio = audio.T

        if audio.shape[0] > 2:
            audio = audio[:2]
        elif audio.shape[0] == 1:
            audio = np.stack([audio[0], audio[0]])

        # Resample if needed
        if sr != SAMPLE_RATE:
            target_len = int(audio.shape[1] * SAMPLE_RATE / sr)
            indices = np.linspace(0, audio.shape[1] - 1, target_len)
            audio = np.array([
                np.interp(indices, np.arange(audio.shape[1]), audio[c])
                for c in range(audio.shape[0])
            ])

        total_samples = audio.shape[1]
        n_chunks = max(1, (total_samples + CHUNK_SAMPLES - 1) // CHUNK_SAMPLES)

        # Pad
        pad_len = (n_chunks * CHUNK_SAMPLES) - total_samples
        if pad_len > 0:
            audio = np.pad(audio, ((0, 0), (0, pad_len)), mode="constant")

        # Collect stems
        n_stems = len(STEM_NAMES)
        all_stems = np.zeros((n_stems, 2, total_samples), dtype=np.float32)

        dtype = torch.float32
        t0 = time.time()

        for i in range(n_chunks):
            start = i * CHUNK_SAMPLES
            end = start + CHUNK_SAMPLES
            chunk = torch.from_numpy(audio[:, start:end]).unsqueeze(0).to(dtype)

            with torch.no_grad():
                out = self.model(chunk)

            stem_data = out[0].numpy()  # (6, 2, samples)
            actual_end = min(end, total_samples)
            for s in range(n_stems):
                all_stems[s, :, start:actual_end] = stem_data[s, :, :actual_end - start]

            if progress_callback:
                progress_callback(i + 1, n_chunks)

            elapsed = time.time() - t0
            pct = (i + 1) / n_chunks * 100
            remaining = elapsed / (i + 1) * (n_chunks - i - 1) if i > 0 else 0
            log.info(
                "Chunk %d/%d (%.0f%%) - %.1fs elapsed, ~%.0fs remaining",
                i + 1, n_chunks, pct, elapsed, remaining,
            )

        # Write stems
        stems: dict[str, str] = {}
        for s, name in enumerate(STEM_NAMES):
            out_path = out_dir / f"{name}.wav"
            sf.write(str(out_path), all_stems[s].T, SAMPLE_RATE)
            stems[name] = str(out_path)

        total_time = time.time() - t0
        audio_duration = total_samples / SAMPLE_RATE
        log.info(
            "Done in %.1fs (audio: %.1fs, %.2fx realtime)",
            total_time, audio_duration, total_time / audio_duration,
        )

        return stems
