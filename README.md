# extract0r

Split a song into stems, transcribe the parts you care about into playable tablature, then
remix and master what comes out.

```
upload ──► separate ──► pick stems ──► transcribe ──► export
             Demucs                     basic-pitch      .txt  .x0r  .mid
                                        + fretboard      .mp3  (phase 2)
                                          solver
```

> **Only upload audio you have the right to use.** Recordings and the compositions
> underneath them are usually copyrighted, and separating, transcribing, and remixing all
> create derivative works. See [docs/LEGAL.md](docs/LEGAL.md).

---

## Status

The application is complete and tested end to end on **stub backends**. The ML backends
(Demucs, basic-pitch, librosa, matchering) are written against real APIs but have never
been run — this machine has no torch, no ffmpeg, and no Node. What is missing is the
machine learning, not the app.

| | |
|---|---|
| Backend tests | **38 passing** (`services/api`) |
| Domain layer | Real — no third-party dependencies, fully tested |
| ML backends | Adapters written, unrun (see `PARTIAL` cards in the backlog) |
| Web app | Written, never built — Node is not installed here |

---

## What the solver actually does

Given raw MIDI pitches, `app/domain/tab/fretboard.py` picks *where on the neck* to play
them by running Viterbi over onset clusters — minimising hand travel, stretch, and fret
height, and rewarding open strings. Real output from `docs/samples/guitar.txt`:

```
 e|---------------------------------|0---------------3---------------|2--|
 B|---------------------------------|0---------------0---------------|3--|
 G|---------------------------------|0---------------0---------------|2--|
 D|---------------------------------|2---------------0---------------|0--|
 A|---------0-----------2---0-------|2---------------2---------------|---|
 E|-0---3-------3---0-----------3---|0---------------3---------------|---|
```

Nothing told it those were chords. It was handed pitch numbers and chose `022000`,
`320003`, and `xx0232` — Em, G, D in open position — because that is the cheapest path
through the lattice.

---

## Running it

**Prerequisites:** Python 3.11+. Node 20+ for the web app, ffmpeg for mixdown and loudness
matching — neither is installed on this machine yet.

```bash
powershell -File scripts/dev-api.ps1
```

Creates the venv on first run and serves the API on `http://localhost:8000` with
interactive docs at `/docs`. Then, in another terminal:

```bash
powershell -File scripts/dev-web.ps1
```

Next.js on `http://localhost:3000`, proxying `/api` to the API.

Tests:

```bash
powershell -File scripts/test-api.ps1
```

### Turning on the real backends

The stubs let everything run with no models. To get real output:

```bash
powershell -File scripts/install-ml.ps1
```

Then set in `.env`:

```
SEPARATION_BACKEND=demucs
TRANSCRIPTION_BACKEND=basic_pitch
DRUM_BACKEND=onset
MASTERING_BACKEND=matchering
```

Expect several GB of downloads. `GET /api/v1/capabilities` reports what is configured
versus what is actually importable, and the app falls back to stubs with a warning rather
than failing mid-job.

`docker compose up` builds both services with the ML extras and ffmpeg included, which is
the less painful path on Windows.

---

## Layout

```
apps/web              Next.js 15 · React 19 · TypeScript · Tailwind v4
services/api          FastAPI · Python 3.12
  app/domain/         notes, fretboard solver, tab renderers, .x0r  (no deps)
  app/services/       separation · transcription · mastering · mixdown · storage
  app/jobs/           thread-pool job store with progress
  app/api/            routes and wire schemas
  tests/              38 tests, no ML stack required
docs/                 architecture, backlog, roadmap, ADRs, legal
scripts/              PowerShell dev loop
storage/              uploads and artifacts — gitignored, auto-purged
```

---

## Documentation

| | |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit and why the domain layer is dependency-free |
| [BACKLOG.md](docs/BACKLOG.md) | 10 epics, ~60 sprint-ready cards with acceptance criteria |
| [ROADMAP.md](docs/ROADMAP.md) | Sprint sequencing, dependencies, standing risks |
| [LEGAL.md](docs/LEGAL.md) | Copyright posture and the pre-launch checklist |
| [API.md](docs/API.md) | Endpoint reference |
| [adr/](docs/adr) | Four decisions, with the alternatives that were rejected |

---

## The two phases

**Phase 1 — transcription.** Upload, separate, select stems, transcribe to tab, export as
`.txt` and `.x0r`. Epics 01–07.

**Phase 2 — mastering and mixing.** Reference-track mastering, a per-stem mixer with EQ and
effects, mixdown to a single MP3. Epics 08–10. The mix specification and the ffmpeg filter
graph builder are already written and unit-tested.
