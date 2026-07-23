from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from domain.enums import JobStatus, SourceType


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateJobRequest(BaseModel):
    source_type: SourceType
    url: Optional[str] = None
    filename: Optional[str] = None
    stems: list[str] = Field(
        default_factory=lambda: ["vocals", "drums", "bass", "guitar", "piano", "other"]
    )


class JobSnapshot(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = 0.0
    step: str = "created"
    message: str = "Job initialized"
    cancellable: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class AnalysisSummary(BaseModel):
    bpm: Optional[float] = None
    key: Optional[str] = None
    scale: Optional[str] = None
    confidence: Optional[float] = None
    lufs_integrated: Optional[float] = None
    peak_dbfs: Optional[float] = None
    duration_sec: Optional[float] = None
    stem_energy: Optional[dict[str, float]] = None


class ManifestSource(BaseModel):
    type: SourceType
    url: Optional[str] = None
    filename: Optional[str] = None


class ManifestResponse(BaseModel):
    job_id: str
    status: JobStatus
    source: ManifestSource
    selected_stems: list[str] = Field(default_factory=list)
    available_stems: list[str] = Field(default_factory=list)
    duration_sec: Optional[float] = None
    analysis: AnalysisSummary = Field(default_factory=AnalysisSummary)
    files: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ToolReadiness(BaseModel):
    name: str
    available: bool
    path: Optional[str] = None
    detail: Optional[str] = None


class DiagnosticsResponse(BaseModel):
    service: str = "splinter-x"
    ready: bool
    tools: list[ToolReadiness]
