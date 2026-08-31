"""Runtime configuration. Every knob is an env var so containers stay immutable."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # Absolute, so the API picks up the same .env no matter where it is launched from.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env",), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Extract0r API"
    app_version: str = "0.1.0"
    environment: str = "development"

    # --- storage -----------------------------------------------------------
    storage_dir: Path = Field(default=REPO_ROOT / "storage")
    max_upload_mb: int = 60
    # Anything shorter is almost certainly a mis-drop; anything longer blows out job time.
    min_duration_s: float = 5.0
    max_duration_s: float = 600.0
    # Uploads are deleted this long after the job finishes. Keeping user audio around
    # is a legal liability, not a feature.
    retention_hours: int = 24
    # How often the background sweep runs. 0 disables it (boot sweep still happens).
    retention_sweep_minutes: int = 30

    # --- backends ----------------------------------------------------------
    separation_backend: str = "stub"        # stub | demucs
    demucs_model: str = "htdemucs_6s"
    demucs_device: str = "cpu"
    # auto = pyin for monophonic stems, basic_pitch for polyphonic ones.
    transcription_backend: str = "stub"     # stub | auto | pyin | basic_pitch
    drum_backend: str = "stub"              # stub | onset
    mastering_backend: str = "loudness"     # loudness | matchering

    # --- jobs --------------------------------------------------------------
    job_backend: str = "inline"             # inline | redis
    redis_url: str = "redis://localhost:6379/0"
    max_concurrent_jobs: int = 2

    # --- web ---------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- legal -------------------------------------------------------------
    # Uploading without an affirmative rights attestation is blocked when true.
    require_rights_attestation: bool = True
    dmca_contact_email: str = "dmca@example.com"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
