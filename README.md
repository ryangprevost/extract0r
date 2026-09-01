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

Phase 1 runs for real. Demucs separates, basic-pitch and pYIN transcribe, librosa reads
the drums — all verified on this machine, not just written.

| | |
|---|---|
| Backend tests | **66 passing**, 6 skipped without the ML extras |
| ML smoke tests | **12 passing** against real Demucs / basic-pitch / librosa |
| Domain layer | Pure Python, no third-party dependencies |
| Separation | Demucs 4.1.0 + torch 2.13 CPU — 6-stem, 0.72× realtime measured on a real track |
| Transcription | pYIN for bass/vocals, basic-pitch (ONNX) for guitar/piano, onsets for drums |
| Studio front end | ASP.NET Core + vanilla JS — **runs**, full loop verified through its proxy |
| Next.js front end | Written, **never built** — Node is not installed here |
| CI | Written, **never executed** — no git remote yet |
| Accuracy | **Unmeasured.** Needs a licensed eval set (X0R-306) |

Two install traps cost most of a sprint and are now documented in
[docs/RUNBOOK.md](docs/RUNBOOK.md) and automated in `scripts/install-ml.ps1`:

- **Windows `MAX_PATH`** breaks `pip install torch` inside this project tree and leaves a
  half-installed torch behind, surfacing as `No module named 'torchgen'`. The ML venv
  therefore lives on a short path, separate from the app venv.
- **basic-pitch pins `tensorflow<2.15.1`**, which does not exist for Python 3.12. It
  ships ONNX weights too, so it is installed `--no-deps` and runs on onnxruntime.

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

**Prerequisites:** Python 3.11+ and the .NET 9 SDK. Node 20+ only for the Next.js front
end. ffmpeg only for Phase 2 mixdown and loudness matching — ingest does not need it,
because the bundled libsndfile reads MP3 directly.

### One command

```bash
powershell -File scripts/start.ps1
```

Starts the API (in its own window, so you can watch the separation logs), prints which
backends the server actually has, starts the Studio front end, and opens a browser at
`http://localhost:5080`. Ports already in use are reused rather than fought over.

Add `-Stubs` to skip the ML backends entirely — instant startup, fake stems, useful when
you are working on the UI.

### Or start the pieces yourself

```bash
powershell -File scripts/dev-api.ps1
```

Creates the venv on first run and serves the API on `http://localhost:8000` with
interactive docs at `/docs`. Then, in another terminal:

```bash
powershell -File scripts/dev-web.ps1
```

Next.js on `http://localhost:3000`, proxying `/api` to the API. **Needs Node 20+.**

### No Node? Use the Studio front end

`extract0r.sln` opens in Visual Studio and runs with F5 — or from a terminal:

```bash
dotnet run --project apps/studio/Extract0r.Studio.csproj --urls http://localhost:5080
```

`apps/studio` is an ASP.NET Core 9 host that serves a single hand-written page and
reverse-proxies `/api/*` to the Python service. Same-origin, so there is no CORS to
configure, and no build step — it is plain HTML, CSS, and JavaScript in `wwwroot`.

It covers the whole Phase 1 loop: upload with the rights gate, live separation progress,
stem selection with tuning choice, rendered tab, and `.txt` / `.x0r` downloads. The
header shows which backends the server actually has installed, so a stub fallback is
visible rather than silent.

**The stems are stacked as a mixer**, one colour-coded lane per instrument with its
waveform, sharing a single playhead so the six lanes read as one song. Each lane has solo
and mute, and clicking any waveform seeks everything together. That matters more than it
looks: when a tab comes out wrong, listening to the stem is the only way to tell a
*separation* problem from a *transcription* one.

Tests:

```bash
powershell -File scripts/test-api.ps1
```

### Turning on the real backends

The stubs let everything run with no models. For real output:

```bash
powershell -File scripts/install-ml.ps1
```

That builds a separate venv on a short path (Windows `MAX_PATH` — see the runbook),
installs torch/Demucs/librosa/basic-pitch, and **verifies each backend imports** before
declaring success. Then set in `.env`:

```
SEPARATION_BACKEND=demucs
TRANSCRIPTION_BACKEND=auto
DRUM_BACKEND=onset
```

`auto` picks per stem: pYIN for monophonic bass and vocals, basic-pitch for polyphonic
guitar and piano. Run the API against that venv:

```bash
powershell -File scripts/dev-api.ps1 -Venv "$env:USERPROFILE\.x0r-venv"
```

`GET /api/v1/capabilities` reports what is *configured* against what is actually
importable — they are different things, and the app silently falls back to stubs when
they disagree, so check it before concluding anything real happened.

`docker compose up` builds both services with the ML extras and ffmpeg included, and
avoids the Windows path problem entirely.

---

## Layout

```
extract0r.sln         opens the Studio project in Visual Studio
apps/studio           ASP.NET Core 9 host — serves the UI, proxies /api (no Node needed)
apps/web              Next.js 15 · React 19 · TypeScript · Tailwind v4
services/api          FastAPI · Python 3.12
  app/domain/         notes, fretboard solver, tab renderers, .x0r  (no deps)
  app/services/
    audio/            probing and canonical decode at ingest
    separation/       demucs · stub
    transcription/    pyin (mono) · basic_pitch (poly) · drums (onsets) · stub
    mastering/        matchering · loudness (ffmpeg)
    mixdown/          mix spec and ffmpeg filter graph
  app/jobs/           thread-pool job store with progress
  app/api/            routes and wire schemas
  tests/              66 tests + 12 ML smoke tests that skip without the extras
docs/                 architecture, runbook, backlog, roadmap, ADRs, legal
scripts/              PowerShell dev loop
storage/              uploads and artifacts — gitignored, auto-purged
```

---

## Documentation

| | |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit and why the domain layer is dependency-free |
| [RUNBOOK.md](docs/RUNBOOK.md) | Getting the real backends installed, and the two traps that will bite you |
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
