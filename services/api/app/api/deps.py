"""Process-wide singletons, exposed as FastAPI dependencies so tests can override them."""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.jobs.store import JobStore
from app.services.registry import TrackRegistry
from app.services.storage import TrackStorage


@lru_cache
def get_storage() -> TrackStorage:
    return TrackStorage(get_settings().storage_dir)


@lru_cache
def get_registry() -> TrackRegistry:
    return TrackRegistry()


@lru_cache
def get_jobs() -> JobStore:
    return JobStore(max_workers=get_settings().max_concurrent_jobs)


def get_config() -> Settings:
    return get_settings()
