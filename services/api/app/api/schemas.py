"""Wire contracts. Kept separate from the domain so the HTTP shape can evolve freely."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.notes import StemKind


class RightsAttestation(BaseModel):
    """What the uploader affirms before we touch their file.

    Recorded on the track and stamped into every .x0r export. It is the difference
    between a tool and an infringement service.
    """

    owns_or_licensed: bool = Field(
        description="Uploader owns the recording, has a licence, or the use is otherwise lawful"
    )
    personal_use_only: bool = Field(
        description="Output will be used for study, practice, or other personal use"
    )
    accepted_terms_version: str = "2026-08-31"


class TrackResponse(BaseModel):
    track_id: str
    original_filename: str
    size_bytes: int
    sha256: str
    duration_s: float | None = None


class StemInfo(BaseModel):
    stem: StemKind
    filename: str
    bytes: int


class SeparationResponse(BaseModel):
    track_id: str
    backend: str
    model: str
    stems: list[StemInfo]


class TranscribeRequest(BaseModel):
    stems: list[StemKind] = Field(min_length=1)
    # Keys from app.domain.tab.fretboard.TUNINGS, e.g. {"guitar": "guitar_drop_d"}.
    tunings: dict[StemKind, str] = Field(default_factory=dict)
    capo: int = 0
    max_hand_span: int = Field(default=5, ge=2, le=8)


class TabArtifact(BaseModel):
    stem: StemKind
    notation: str
    note_count: int
    download_url: str
    preview: str


class TranscribeResponse(BaseModel):
    track_id: str
    artifacts: list[TabArtifact]
    x0r_url: str


class JobResponse(BaseModel):
    job_id: str
    kind: str
    track_id: str
    state: Literal["queued", "running", "succeeded", "failed"]
    progress: float
    message: str
    result: dict | None = None
    error: str | None = None


class EqBandModel(BaseModel):
    kind: Literal["lowshelf", "highshelf", "peaking", "highpass", "lowpass"]
    frequency_hz: float = Field(gt=0, le=22050)
    gain_db: float = Field(default=0.0, ge=-24, le=24)
    q: float = Field(default=0.707, gt=0, le=10)


class CompressorModel(BaseModel):
    threshold_db: float = Field(default=-18.0, ge=-60, le=0)
    ratio: float = Field(default=3.0, ge=1, le=20)
    attack_ms: float = Field(default=20.0, ge=0.1, le=500)
    release_ms: float = Field(default=250.0, ge=10, le=5000)
    makeup_db: float = Field(default=0.0, ge=0, le=24)


class ReverbModel(BaseModel):
    wet: float = Field(default=0.2, ge=0, le=1)
    delay_ms: float = Field(default=60.0, ge=5, le=500)
    decay: float = Field(default=0.4, ge=0, le=0.95)


class StemSettingsModel(BaseModel):
    stem: StemKind
    gain_db: float = Field(default=0.0, ge=-60, le=12)
    pan: float = Field(default=0.0, ge=-1, le=1)
    muted: bool = False
    solo: bool = False
    eq: list[EqBandModel] = Field(default_factory=list)
    compressor: CompressorModel | None = None
    reverb: ReverbModel | None = None


class MixRequest(BaseModel):
    stems: list[StemSettingsModel] = Field(min_length=1)
    master_gain_db: float = Field(default=0.0, ge=-24, le=12)
    normalize_lufs: float | None = Field(default=-14.0, ge=-30, le=-5)
    bitrate_kbps: Literal[128, 192, 256, 320] = 320


class MasterRequest(BaseModel):
    """Phase 2: match the mixed track to an already-uploaded reference."""

    reference_track_id: str
    apply_to_stems: bool = False
