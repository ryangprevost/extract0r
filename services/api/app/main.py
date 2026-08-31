"""FastAPI entrypoint.

Run it with:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_jobs, routes_meta, routes_mix, routes_tracks, routes_transcription
from app.api.deps import get_storage
from app.config import get_settings
from app.legal import COPYRIGHT_NOTICE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("extract0r")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Sweep on boot so a crashed process cannot leave user audio sitting past retention.
    removed = get_storage().purge_expired(settings.retention_hours)
    if removed:
        log.info("purged %d expired track(s) on startup", len(removed))
    yield


app = FastAPI(
    title="Extract0r API",
    version=get_settings().app_version,
    description=(
        "Stem separation, automatic tablature, and reference mastering.\n\n"
        f"**Copyright:** {COPYRIGHT_NOTICE}"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_meta.router)
app.include_router(routes_tracks.router)
app.include_router(routes_transcription.router)
app.include_router(routes_mix.router)
app.include_router(routes_jobs.router)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": "Extract0r API", "docs": "/docs", "health": "/api/v1/health"}
