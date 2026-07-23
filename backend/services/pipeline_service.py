from __future__ import annotations

import shutil
from pathlib import Path
from threading import Thread

from adapters.demucs_adapter import DemucsAdapter
from adapters.ffmpeg_adapter import FFmpegAdapter
from adapters.optimized_demucs import OptimizedDemucs
from adapters.process_utils import ExternalToolError, append_log
from adapters.yt_dlp_adapter import YtDlpAdapter
from domain.enums import JobStatus, SourceType
from services.analysis_service import AnalysisService
from services.cancellation_service import cancellation_service
from services.device_service import DeviceService
from services.waveform_service import WaveformService
from storage.job_store import JobStore


class PipelineService:
    """Phase 1 processing pipeline with pragmatic fallbacks for local development."""

    def __init__(self, job_service: 'JobService') -> None:
        self.job_service = job_service
        self.job_store = JobStore()
        self.yt_dlp = YtDlpAdapter()
        self.ffmpeg = FFmpegAdapter()
        self.demucs = DemucsAdapter()
        self.device_service = DeviceService()
        self.analysis_service = AnalysisService()
        self.waveform_service = WaveformService()

    def start(self, job_id: str) -> None:
        Thread(target=self.run, args=(job_id,), daemon=True).start()

    def run(self, job_id: str) -> None:
        job_dir = self.job_store.ensure_job_dir(job_id)
        log_path = job_dir / 'logs' / 'pipeline.log'
        try:
            manifest = self.job_service.get_manifest(job_id)
            if manifest is None:
                raise RuntimeError('Manifest missing')

            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.validating_input, progress=0.05, step=JobStatus.validating_input.value, message='Validating job request')
            source_path = self._prepare_source(job_id, manifest.source.type.value, manifest.source.url, manifest.source.filename, job_dir, log_path)
            self.job_service.update_manifest_files(job_id, {'input_original': str(source_path)})

            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.transcoding, progress=0.25, step=JobStatus.transcoding.value, message='Converting source to canonical WAV')
            canonical_wav = job_dir / 'source' / 'input.wav'
            self.ffmpeg.transcode_to_wav(str(source_path), str(canonical_wav), job_id=job_id, log_path=log_path)
            self.job_service.update_manifest_files(job_id, {'input_wav': str(canonical_wav)})

            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.separating, progress=0.55, step=JobStatus.separating.value, message='Separating selected stems')
            manifest_after_transcode = self.job_service.get_manifest(job_id)
            selected_stems = manifest_after_transcode.selected_stems if manifest_after_transcode else []
            final_stems = self._separate_or_fallback(job_id, canonical_wav, selected_stems, job_dir, log_path)
            self.job_service.update_manifest_files(job_id, final_stems)

            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.postprocessing, progress=0.82, step=JobStatus.postprocessing.value, message='Creating mix and original tracks')
            stem_inputs = [path for key, path in final_stems.items() if key in selected_stems]
            mix_path = job_dir / 'stems' / 'mix.wav'
            self.ffmpeg.mix_wavs(stem_inputs, str(mix_path), job_id=job_id, log_path=log_path)
            original_path = job_dir / 'stems' / 'original.wav'
            self.ffmpeg.copy_audio(str(canonical_wav), str(original_path))
            self.job_service.update_manifest_files(job_id, {'mix': str(mix_path), 'original': str(original_path)})

            # --- Analyzing ---
            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.analyzing, progress=0.88, step=JobStatus.analyzing.value, message='Analyzing audio (BPM, key, loudness)')
            all_stem_paths = dict(final_stems)
            all_stem_paths['mix'] = str(mix_path)
            all_stem_paths['original'] = str(original_path)
            analysis = self.analysis_service.analyze(job_id, job_dir, str(canonical_wav), all_stem_paths)
            self.job_service.update_analysis(job_id, analysis)

            # --- Waveform generation ---
            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.analyzing, progress=0.92, step='generating_waveforms', message='Generating waveform summaries')
            waveform_map = self.waveform_service.generate_for_stems(job_dir, all_stem_paths)
            for stem_name, wf_path in waveform_map.items():
                self.job_service.update_manifest_files(job_id, {f'waveform_{stem_name}': wf_path})

            # --- Packaging ---
            self._check_cancel(job_id)
            self.job_service.update_job(job_id, status=JobStatus.packaging, progress=0.95, step=JobStatus.packaging.value, message='Finalizing manifest and outputs')
            self.job_service.mark_done(job_id)
        except CancelledError:
            append_log(log_path, 'Job cancelled')
            self._cleanup_partial_outputs(job_dir)
            self.job_service.mark_cancelled(job_id, 'Job cancelled before completion')
        except Exception as exc:
            append_log(log_path, f'Pipeline error: {exc}')
            self._cleanup_partial_outputs(job_dir)
            self.job_service.mark_failed(job_id, self._friendly_error_message(exc))
        finally:
            cancellation_service.clear(job_id)

    def _prepare_source(self, job_id: str, source_type: str, url: str | None, filename: str | None, job_dir: Path, log_path: Path) -> Path:
        self.job_service.update_job(job_id, status=JobStatus.ingesting_source, progress=0.12, step=JobStatus.ingesting_source.value, message='Preparing source media')
        source_dir = job_dir / 'source'
        if source_type == SourceType.upload.value:
            if not filename:
                raise RuntimeError('Upload job missing filename')
            candidate = Path(filename)
            if not candidate.exists():
                raise RuntimeError('Uploaded file placeholder path does not exist yet')
            target = source_dir / candidate.name
            shutil.copy2(candidate, target)
            return target
        if not url:
            raise RuntimeError('URL-based job missing source URL')
        return Path(self.yt_dlp.download(url, str(source_dir), job_id=job_id, log_path=log_path))

    def _separate_or_fallback(self, job_id: str, canonical_wav: Path, selected_stems: list[str], job_dir: Path, log_path: Path) -> dict[str, str]:
        raw_dir = job_dir / 'stems_raw'
        final_dir = job_dir / 'stems'
        raw_stems: dict[str, str] = {}

        # Try optimized PyTorch separator first (torch.compile + FP16, 2-3x faster)
        try:
            append_log(log_path, 'Using optimized Demucs (torch.compile + FP16)')
            separator = OptimizedDemucs(compile_model=True)
            raw_stems = separator.separate(
                str(canonical_wav), str(final_dir),
                progress_callback=lambda done, total: self._separation_progress(job_id, done, total),
            )
            outputs: dict[str, str] = {}
            for stem in selected_stems:
                target = final_dir / f'{stem}.wav'
                outputs[stem] = str(target) if target.exists() else ''
            return outputs
        except Exception as exc:
            append_log(log_path, f'Optimized separator failed, falling back to Demucs CLI: {exc}')
            raw_stems = {}

        # Fallback: Demucs CLI
        detected_device = self.device_service.detect().get('device', 'cpu')
        try:
            raw_stems = self.demucs.separate(str(canonical_wav), str(raw_dir), job_id=job_id, log_path=log_path, device=detected_device)
        except ExternalToolError as exc:
            append_log(log_path, f'Demucs unavailable or failed, using placeholder fallback: {exc}')
            raw_stems = {}
        outputs = {}
        for stem in selected_stems:
            target = final_dir / f'{stem}.wav'
            if stem in raw_stems:
                self.ffmpeg.copy_audio(raw_stems[stem], str(target))
            else:
                self.ffmpeg.copy_audio(str(canonical_wav), str(target))
            outputs[stem] = str(target)
        return outputs

    def _separation_progress(self, job_id: str, done: int, total: int) -> None:
        """Update job progress during chunk-based separation."""
        base = 0.55
        span = 0.25
        pct = base + (done / max(total, 1)) * span
        self.job_service.update_job(job_id, status=JobStatus.separating, progress=round(pct, 2), step=JobStatus.separating.value, message=f'Separating stems ({done}/{total} chunks)')

    def _check_cancel(self, job_id: str) -> None:
        if cancellation_service.is_cancelled(job_id):
            raise CancelledError()

    def _cleanup_partial_outputs(self, job_dir: Path) -> None:
        for folder_name in ['stems', 'stems_raw', 'analysis', 'waveforms']:
            target = job_dir / folder_name
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if folder_name != 'stems_raw':
                target.mkdir(parents=True, exist_ok=True)

    def _friendly_error_message(self, exc: Exception) -> str:
        message = str(exc)
        if 'Required command not found' in message:
            return message + '. Install the missing tool and ensure it is on PATH.'
        return f'Pipeline failed: {message}'


class CancelledError(Exception):
    pass
