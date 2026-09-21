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

Both phases run for real. Demucs separates, basic-pitch and pYIN transcribe, librosa reads
the drums, and a mix can be mastered against a commercial reference and exported — all
verified on this machine, not just written.

| | |
|---|---|
| Backend tests | **680 passing**, 6 skipped without the ML extras |
| Domain layer | Pure Python, no third-party dependencies |
| Ingest | libsndfile for everything it reads, PyAV for m4a/AAC — no system ffmpeg |
| Separation | Demucs 4.1.0 + torch CPU — 6-stem, 0.72× realtime measured on a real track |
| Transcription | pYIN for bass/vocals, basic-pitch (ONNX) for guitar/piano, onsets for drums |
| Mastering | Tone, loudness and per-band stereo image matched to a reference, in numpy/scipy |
| Per-instrument matching | Snare against snare: level, tone in five bands, dynamics, transients, position, width |
| Monitoring | Web Audio channel strip per stem — settings audible without a render |
| Studio front end | ASP.NET Core + vanilla JS — **runs**; hamburger nav over Mastering, Tablature, Capabilities and Legal |
| Next.js front end | Written, **never built** — Node is not installed here |
| Transcription accuracy | **Unmeasured.** Needs a licensed eval set (X0R-306) |
| Mastering accuracy | Measured per change — see below |

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

## What the mastering chain actually does

Upload a mix and a commercial reference, and it matches the mix to the reference. Every
number below was measured on real tracks; where a thing could not be made to work, that
is recorded too, because a tool that only reports its wins is not a useful one.

**Tone.** A smoothed, clamped correction curve in log frequency, centred before clamping
so a loud reference cannot drag the whole mix up. Deep bass is guarded separately: an
early version let the match scoop 12 dB out of a kick's fundamental and the drums came
back flat.

**Stereo image, band by band.** A single width control is the wrong shape for this. A
home mix measured against the record it was aimed at was *twice as wide* at 120–250 Hz
and *a third as wide* above 8 kHz — records are tight at the bottom and open at the top,
and one factor over a crossover cannot do both. Matching per band took the error from
5.09 dB to 1.49 dB while leaving tonal balance untouched within 0.05 dB. Widening is
guarded: side content cancels when a phone sums to mono, so the result may never give up
more in mono than the reference itself does.

**Vocal placement.** Measured through the match curve rather than before it, because the
match is applied afterwards and a reference heavier at both ends scoops the midrange the
vocal lives in. The vocal's own range gets back what the match takes out of it — on its
own stem, so the master's tone is unchanged and only the vocal's share of the band moves.

**Artefacts.** The master is built as a correction to the original file rather than by
summing the stems, because separation is not lossless: six stems reconstructed one track
only to within −25.6 dB, worst in the presence range, which is exactly what a sizzle is.
Applying the *difference* instead reproduces the original bit for bit when nothing is
changed — −188 dB — and costs artefacts only in proportion to what you actually change.

**Instrument by instrument.** Matching two whole mixes can only move the sum: it can see
that the reference has more low end and cannot see whether that means the bass should come
up or the kick needs weight, so it tilts everything and takes the bass guitar with it.
Separate the reference too and the question becomes answerable — your snare against that
record's snare, on level, tone in five bands, dynamic range, transients, position and
width. Each difference comes back as its own control, so the air on the drums can be taken
and everything else declined.

Two things about it are worth more than the feature itself. The tone dial is *solved*
rather than assumed: a bell at 250 Hz covers less than the 120–500 Hz band it is
responsible for and the five filters overlap, so setting each one to its band's own number
under-delivers by about a third and lets them fight. Building the band-response matrix and
inverting it makes "+3 dB of air" deliver 2.99. And the compressor's dial is an *outcome* —
dB of dynamic range removed — because "4:1 at −18 dB" means something different on every
stem it is pointed at. Asking for 3 dB removes 2.94, measured, after one self-correction.

**A nudge, not a copy — and this took getting wrong first.** The first version closed each
gap completely: make your snare measure like their snare. Run on a real song it produced a
master its own author could not recognise, and he was right to say so. Two records are not
two takes of one arrangement. A reference whose guitars sit 9 dB hotter than yours may
simply be a wall-of-guitars record where yours is not, and "correcting" that replaces your
arrangement with someone else's. It asked for +9 dB on the guitars against −4 dB on the
bass: a 13 dB swing between two instruments, which is not a mix note.

Every suggestion is now **half the measured gap**, capped at 2.5 dB per band and 3 dB per
fader, with gaps big enough to be arrangement flagged rather than offered. A stem also gets
a total budget of 5 dB of tone change across all five bands, scaled proportionally when it
is exceeded — a real drum stem asked for +3 dB in four bands at once, which is not an EQ
move but a different drum sound.

**The solve is damped, and that fixed a real complaint.** Masters came back "swirly",
"hollow" and "muddy". The cause was the exact solve: to hit a band target precisely it sets
overlapping filters against each other, so asking for +3 dB of presence produced +3.55 on
the presence bell against −2.02 on the air shelf. A boost and a notch that close together
is a crude comb, and it sounds like one. Adding a ridge term trades exactness for
smoothness — the same request now spans −0.28 to +2.18 dB with a worst swing of 1.81 dB
inside an octave, against −1.36 to +3.49 and 3.56 dB before. It delivers about two thirds
of what is asked, and the missing third was never worth having. The whole gap is
still reported — you see what was measured and what is being suggested, and the slider
reaches further than the suggestion if your ears disagree.

Measured on that same song, with the reference tone match off so nothing else is moving:

| | drift from your mix | distance from the reference |
|---|---|---|
| your mix, untouched | 0.00 dB | 7.59 dB |
| old: the whole gap, per instrument | 4.98 dB | 3.20 dB |
| now: half the gap, per instrument | **2.55 dB** | 5.23 dB |
| that, plus the whole-mix polish | 5.27 dB | **2.85 dB** |

The last row is the point, and it is why the two stages are separate. Nudging the
instruments and then letting the master bus close the tonal gap lands *closer* to the
reference than the old carbon-copy behaviour did — while moving the balance between your
instruments half as far. Tone is a thing to match; arrangement is a thing to keep.

Saturation is deliberately missing from the comparison. Distortion adds harmonics at
multiples of what is already there, so telling "this guitar was driven" from "this guitar
played a brighter voicing" needs the undistorted signal, which does not exist. It stays a
control the ear sets. An invented number would have made the table look complete and been
worth less than the gap.

**Hearing it before rendering it.** Every setting used to cost a full master to audition.
Each stem now runs through a Web Audio chain mirroring the server's channel strip, so a
slider is audible on the next buffer. The EQ solve matrix is sent from the server so the
monitor runs the same band gains as the export rather than its own approximation — and
where the two genuinely differ (biquads are not zero-phase curves; the browser's
compressor cannot measure its own result) the page says so. A preview that quietly
disagrees with the export is worse than no preview.

**What it will not do.** Clarity is not in the summed spectrum, so no master EQ can add
it. The comparison measures how crowded each band is and how much structure is left in
it, names the instruments competing for the range, and says plainly that the fix is an
arrangement change. Four automated fixes were built for it and all four failed to move
the numbers; the failures are written up in `services/api/app/services/mastering/clarity.py`
rather than quietly deleted.

---

## Running it

**Prerequisites:** Python 3.11+ and the .NET 9 SDK. Node 20+ only for the Next.js front
end. **No ffmpeg anywhere** — ingest reads MP3 through libsndfile and m4a/AAC through
PyAV's bundled libraries, and the whole mastering chain runs on numpy, scipy, `lameenc`
and `pyloudnorm`.

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
    mastering/        reference match, stereo image, vocals, clarity, library
    mixdown/          reading and writing audio, LAME encoding, ID3
  app/jobs/           thread-pool job store with progress
  app/api/            routes and wire schemas
  tests/              680 tests, 6 of them skipped without the ML extras
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

**Phase 2 — mastering and mixing.** Working today: upload a song, split it, upload a
commercial reference, and the mix is matched to that reference's tonal balance, loudness
and stereo image, then exported as an MP3 named after the song with the reference
recorded in its ID3 tag. Along the way it will place the vocal, lay a synthesised kit over
the drums, add convolution reverb per stem, and tell you in plain language where your mix
still differs — see [what the mastering chain actually does](#what-the-mastering-chain-actually-does).

It can also go looking for a reference. Point `library_dir` at a folder of music and it
measures every track and ranks which would make a useful reference for the one you are
working on — close in tonal balance, further along in loudness and width. The obvious
version of that feature reads a streaming link instead; it cannot be built, because
Spotify withdrew the audio-features and recommendations endpoints for new applications in
November 2024 and metadata alone says nothing about how a record was mastered.

Runs entirely on numpy, scipy, `lameenc` and `pyloudnorm` — **no ffmpeg**, so Phase 2
works anywhere Phase 1 does. Still to come: a level-matched A/B, platform loudness targets
(streaming normalises to −14 LUFS, so chasing a −4 LUFS reference is a losing trade), and
mastering without separating first, which would save four minutes a track.
