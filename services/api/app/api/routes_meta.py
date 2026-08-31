"""Health, capability, and legal-notice endpoints.

`/capabilities` exists so the front end can tell the user *why* a feature is greyed
out ("Demucs isn't installed on this server") instead of failing halfway through a job.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_config
from app.config import Settings
from app.legal import COPYRIGHT_NOTICE, TERMS_VERSION, UPLOAD_GATE_TEXT

router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/health")
def health(settings: Settings = Depends(get_config)) -> dict:
    return {"status": "ok", "version": settings.app_version, "env": settings.environment}


@router.get("/capabilities")
def capabilities(settings: Settings = Depends(get_config)) -> dict:
    from app.services.mastering.loudness import LoudnessMatchEngine
    from app.services.mastering.matchering_engine import MatcheringEngine
    from app.services.separation.demucs import DemucsSeparator
    from app.services.transcription.basic_pitch import BasicPitchTranscriber
    from app.services.transcription.drums import OnsetDrumTranscriber

    return {
        "configured": {
            "separation": settings.separation_backend,
            "transcription": settings.transcription_backend,
            "drums": settings.drum_backend,
            "mastering": settings.mastering_backend,
        },
        "installed": {
            "demucs": DemucsSeparator().available(),
            "basic_pitch": BasicPitchTranscriber().available(),
            "onset_drums": OnsetDrumTranscriber().available(),
            "matchering": MatcheringEngine().available(),
            "ffmpeg": LoudnessMatchEngine().available(),
        },
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "retention_hours": settings.retention_hours,
        },
    }


@router.get("/legal")
def legal(settings: Settings = Depends(get_config)) -> dict:
    """Single source of truth for the notices the web app renders."""
    return {
        "terms_version": TERMS_VERSION,
        "copyright_notice": COPYRIGHT_NOTICE,
        "upload_gate": UPLOAD_GATE_TEXT,
        "retention_hours": settings.retention_hours,
        "dmca_contact": settings.dmca_contact_email,
    }
