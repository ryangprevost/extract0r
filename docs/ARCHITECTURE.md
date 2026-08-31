# Extract0r — Architecture

## Shape

```
apps/web            Next.js 15 (App Router, React 19, TS, Tailwind v4)
  └── /api/*        rewritten to the API origin, so the browser sees one host

services/api        FastAPI (Python 3.12)
  app/domain/       pure Python: notes, fretboard solver, tab renderers, .x0r
  app/services/     adapters: separation, transcription, mastering, mixdown, storage
  app/jobs/         thread-pool job store with progress reporting
  app/api/          HTTP routes + wire schemas
```

Two services, not one. The audio work needs the Python ML ecosystem (Demucs, basic-pitch,
librosa, matchering); the UI wants React. Nothing is gained by forcing either side into
the other's runtime.

## The pipeline

```
upload ──► separate ──► select stems ──► transcribe ──► render ──► export
             (Demucs)                     (basic-pitch      (fretboard      .txt
                                           / onset drums)    solver)        .x0r
                                                                            .mid
                                                                            .mp3
```

Every stage writes into `storage/<track_id>/`, so a track is one folder and cleanup is
one `rmtree`.

## The layer that matters

`app/domain/` has **no third-party dependencies at all**. Notes, the fretboard solver,
both tab renderers, and the `.x0r` writer are plain Python, which means:

- they are unit-tested without torch, TensorFlow, librosa, or ffmpeg installed;
- swapping transcription backends cannot break tab rendering;
- the interesting engineering (position optimisation) is isolated and reviewable.

Everything heavy sits behind a `Protocol` in `app/services/*/base.py` with at least two
implementations: the real one and a stub. `app/services/factory.py` picks based on config
and **falls back to the stub with a warning** if a backend's dependencies are missing,
rather than failing two minutes into a job.

## The fretboard solver

The part worth reading. A pitch is playable in three or four places on a guitar neck;
choosing badly produces a tab nobody can play.

1. Group notes into onset clusters (≤45 ms apart = one chord).
2. Enumerate every voicing of each cluster — one note per string, hand span ≤ 5 frets.
3. Viterbi across clusters. Static cost penalises wide stretches and high frets and
   rewards open strings; transition cost is how far the fretting hand travels.
4. Walk the backpointers from the cheapest end state.

Weights live in `SolverConfig`, so "prefer open position" versus "stay up the neck" is a
UI knob, not a rewrite.

## Jobs

Separation is minutes of CPU; it cannot happen in a request. Today: a `ThreadPoolExecutor`
plus a dict, with `/api/v1/jobs/{id}` for polling. That is single-node and forgets on
restart — deliberately (ADR-0003). The `JobStore.submit(kind, track_id, work)` signature is
the seam where Redis/RQ drops in without touching a route.

## Storage and retention

One directory per track, deleted on a boot sweep and on user request. Uploaded filenames
never reach the filesystem — the source is always stored as `source.<ext>`.

## Frontend data flow

Server components fetch config (`/capabilities`); client components own the interactive
work (upload gate, job polling, stem selection). Job polling is a plain `setTimeout` loop
in `lib/api.ts` — WebSockets are on the backlog (X0R-706), not in the MVP.
