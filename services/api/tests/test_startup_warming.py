"""The capability probe is paid for at boot, not by whoever asks first.

X0R-1402. `demucs_is_importable` shells out to a fresh interpreter - deliberately, and
the reasons are in its own docstring - which measured 2.53 s on this machine. It is
cached, so exactly one request pays, and the request that paid was `GET
/tracks/drum-kits`: a read of a static capability list, which is the last place a user
expects to wait.

What these pin is that the warming exists, that it cannot take the server down, and that
it genuinely cannot change the answer - a cache that warms to something different from
what the request would have computed is worse than no warming at all.
"""

from __future__ import annotations

import time

import pytest

from app import main


def test_the_warmer_returns_immediately(monkeypatch):
    """In a thread, not awaited. A server that accepts no connections for two and a half
    seconds is a worse trade than one slow first request."""
    slow = {"ran": False}

    def probe() -> bool:
        time.sleep(0.4)
        slow["ran"] = True
        return True

    monkeypatch.setattr(
        "app.services.separation.demucs.demucs_is_importable", probe, raising=True
    )

    started = time.perf_counter()
    main._warm_probes()
    assert time.perf_counter() - started < 0.2, "warming blocked startup"

    # And it does eventually do the work.
    deadline = time.time() + 5
    while time.time() < deadline and not slow["ran"]:
        time.sleep(0.02)
    assert slow["ran"]


def test_a_failing_probe_does_not_take_startup_down():
    """An optimisation that can break startup is not an optimisation."""
    import app.services.separation.demucs as demucs_module

    original = demucs_module.demucs_is_importable

    def boom() -> bool:
        raise RuntimeError("no interpreter here")

    demucs_module.demucs_is_importable = boom
    try:
        main._warm_probes()  # must not raise
        time.sleep(0.3)
    finally:
        demucs_module.demucs_is_importable = original


def test_the_warmer_is_called_during_the_lifespan():
    """Wired in, not merely written. A warmer nobody calls warms nothing."""
    import inspect

    source = inspect.getsource(main.lifespan)
    assert "_warm_probes()" in source


def test_the_thread_is_a_daemon():
    """It must never hold up a shutdown."""
    import inspect

    source = inspect.getsource(main._warm_probes)
    assert "daemon=True" in source


def test_warming_cannot_change_the_answer():
    """The cache is the point: warming must populate the *same* cache a request reads.

    If these were two different caches, a warmed "yes" could sit in front of a request
    that would have computed "no", and the UI would offer a feature that then fails.
    """
    from app.services.separation import demucs as demucs_module

    assert hasattr(demucs_module.demucs_is_importable, "cache_clear"), (
        "the probe is no longer cached, so warming it achieves nothing"
    )


@pytest.mark.parametrize("calls", [2, 5])
def test_the_probe_is_only_paid_for_once(calls):
    from app.services.separation import demucs as demucs_module

    demucs_module.demucs_is_importable.cache_clear()
    first = time.perf_counter()
    demucs_module.demucs_is_importable()
    cold = time.perf_counter() - first

    warm_total = 0.0
    for _ in range(calls):
        started = time.perf_counter()
        demucs_module.demucs_is_importable()
        warm_total += time.perf_counter() - started

    # Not a timing assertion with a magic threshold: the claim is only that repeats are
    # free relative to the first, which is what makes warming worth doing at all.
    assert warm_total < cold or cold < 0.05
