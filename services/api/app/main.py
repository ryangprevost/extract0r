"""FastAPI entrypoint.

Run it with:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_audio,
    routes_jobs,
    routes_master,
    routes_meta,
    routes_mix,
    routes_tracks,
    routes_transcription,
)
from app.api.deps import get_storage
from app.config import get_settings
from app.legal import COPYRIGHT_NOTICE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("extract0r")


async def _retention_sweep(interval_minutes: int, retention_hours: int) -> None:
    """Purge expired tracks on a timer for as long as the process lives.

    A boot-only sweep is not enough: a long-running server would happily hold audio
    for weeks past the window we promise users in the privacy policy.
    """
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            removed = await asyncio.to_thread(get_storage().purge_expired, retention_hours)
            # Always log the count, including zero - this is the audit trail.
            log.info("retention sweep purged %d track(s)", len(removed))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("retention sweep failed; will retry next interval")



def _warm_probes() -> None:
    """Pay for the out-of-process capability probes at boot, off the request path.

    Daemon so it can never hold up a shutdown, and every failure swallowed: this is an
    optimisation, and an optimisation that can break startup is not one. Whatever goes
    wrong here, the probe runs again on first use exactly as it used to.
    """
    import threading

    def warm() -> None:
        try:
            from app.services.separation.demucs import demucs_is_importable

            started = time.perf_counter()
            answer = demucs_is_importable()
            log.info(
                "demucs importable: %s (probed in %.2fs at startup)",
                answer,
                time.perf_counter() - started,
            )
        except Exception:
            log.info("startup probe failed; it will run again on first use", exc_info=True)

    threading.Thread(target=warm, name="warm-probes", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Sweep on boot so a crashed process cannot leave user audio sitting past retention.
    removed = get_storage().purge_expired(settings.retention_hours)
    if removed:
        log.info("purged %d expired track(s) on startup", len(removed))

    # Ask whether demucs can be imported before anybody asks the API. The probe shells
    # out to a fresh interpreter - deliberately, see `demucs_is_importable` - and it was
    # measured at 2.53 s on this machine, paid by whichever request happened to be first.
    # That request is `GET /tracks/drum-kits`, which the drums UI calls on open, so the
    # cost landed on a plain read of a static capability list.
    #
    # In a thread rather than awaited, because a two-and-a-half-second startup is a worse
    # trade than a two-and-a-half-second first request: the server should accept
    # connections immediately. A request arriving before the thread finishes simply waits
    # on the same work it would have done itself, so the worst case is today's behaviour.
    _warm_probes()

    sweeper: asyncio.Task | None = None
    if settings.retention_sweep_minutes > 0:
        sweeper = asyncio.create_task(
            _retention_sweep(settings.retention_sweep_minutes, settings.retention_hours),
            name="retention-sweep",
        )
        log.info("retention sweep every %d min", settings.retention_sweep_minutes)

    try:
        yield
    finally:
        if sweeper is not None:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper


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
app.include_router(routes_audio.router)
app.include_router(routes_master.router)
app.include_router(routes_mix.router)
app.include_router(routes_jobs.router)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": "Extract0r API", "docs": "/docs", "health": "/api/v1/health"}
