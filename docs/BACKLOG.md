# Extract0r — Work Breakdown

Sprint-ready cards. Each is independently demoable and sized in points (1 ≈ half a day,
2 ≈ a day, 3 ≈ two days, 5 ≈ most of a week, 8 ≈ split it before you start).

**Status legend** — `DONE` shipped and verified · `PARTIAL` partly built, gaps named on
the card · `TODO` not started · `NON-GOAL` decided against, with the reason on the epic.
A non-goal is not a card nobody got to; it is a card we are choosing not to do, and it
stays written down so the decision does not have to be re-argued every time someone
reads the backlog. Individual criteria are marked ✅ done, ⏳ blocked on
another card, ❌ not started.

| Epic | Theme | Points | Phase |
|---|---|---|---|
| [EPIC-01](#epic-01--foundation) | Foundation & dev loop | 13 | 1 |
| [EPIC-02](#epic-02--upload--ingest) | Upload & ingest | 16 | 1 |
| [EPIC-03](#epic-03--stem-separation) | Stem separation | 21 | 1 |
| [EPIC-04](#epic-04--transcription--tab) | Transcription & tab | 34 | 1 |
| [EPIC-05](#epic-05--export) | Export formats | 13 | 1 |
| [EPIC-06](#epic-06--legal--compliance) | Legal & compliance | 13 | 1 |
| [EPIC-07](#epic-07--persistence--operations) | Persistence & operations | ~~24~~ | `NON-GOAL` |
| [EPIC-08](#epic-08--reference-mastering) | Reference mastering | 29 | 2 |
| [EPIC-09](#epic-09--mix-editor) | Mix editor | 26 | 2 |
| [EPIC-10](#epic-10--mixdown--export) | Mixdown & export | 13 | 2 |
| [EPIC-11](#epic-11--per-instrument-matching) | Per-instrument matching | 60 | 2 |
| [EPIC-12](#epic-12--what-a-mastering-suite-has-that-this-does-not) | Mastering-suite parity | 23 | 3 |
| [EPIC-13](#epic-13--pr0ducer) | pr0ducer | 41 | 4 |
| [EPIC-14](#epic-14--speed-and-the-feel-of-using-it) | Speed and usability | ~15 | 3 · *placeholder* |

EPIC-08 and EPIC-11 were carrying their *original* scope in this table (21 and 24) while
cards kept being added underneath. Both are now the sum of the cards actually in them.
Current sprint plan: [sprints/SPRINT-2.md](sprints/SPRINT-2.md).

---

## EPIC-01 — Foundation

### X0R-101 · Monorepo scaffold and dev loop · 3 · `DONE`
**As a** developer **I want** one command per service to get running **so that** onboarding is minutes, not an afternoon.

**Acceptance criteria**
- `scripts/dev-api.ps1` creates the venv on first run and serves `/docs`.
- `scripts/dev-web.ps1` starts Next.js on :3000 with `/api` proxied to :8000.
- `scripts/test-api.ps1` runs the full suite green.
- `.env.example` documents every setting the app reads.

---

### X0R-102 · Domain core with zero heavy dependencies · 3 · `DONE`
**As a** developer **I want** notes, tab, and the `.x0r` writer to be pure Python **so that** the interesting logic is testable without a 2 GB ML install.

**Acceptance criteria**
- Nothing under `app/domain/` imports a third-party package.
- `pytest` passes with only `requirements.txt` + `requirements-dev.txt` installed.

---

### X0R-103 · Pluggable backends with graceful degradation · 2 · `DONE`
**As an** operator **I want** a missing ML dependency to degrade, not crash **so that** a misconfigured box fails fast and loudly at boot instead of silently at minute two of a job.

**Acceptance criteria**
- Each backend exposes `available()`; `factory.py` falls back to the stub and logs a warning.
- `GET /api/v1/capabilities` reports configured vs. actually-installed backends.

---

### X0R-104 · Job queue with progress reporting · 2 · `DONE`
**As a** user **I want** a progress bar **so that** a three-minute separation does not look like a hang.

**Acceptance criteria**
- `POST` endpoints return `202` with a job id; `GET /api/v1/jobs/{id}` returns state, progress 0–1, and a message.
- A worker exception marks the job `failed` with the exception text, never a 500 on the polling endpoint.

---

### X0R-105 · CI pipeline · 3 · `PARTIAL`
**As a** maintainer **I want** every push checked **so that** main stays releasable.

**Acceptance criteria**
- GitHub Actions: `ruff check`, `pytest --cov` on 3.11 and 3.12, `tsc --noEmit`, `next build`. ✅ written
- ML extras are **not** installed in the fast job; the stub backends cover the suite. ✅
- Coverage on `app/domain/` gated at >= 85%. ✅ written
- Nightly `ml-smoke` job installs the real backends and runs the `ml`-marked tests. ✅ written

Written but **never executed** — the project has no git remote, so nothing has run this
workflow. Treat `.github/workflows/ci.yml` as unverified until the first push.

---

## EPIC-02 — Upload & ingest

### X0R-201 · Upload endpoint with validation · 2 · `DONE`
**Acceptance criteria**
- Multipart `POST /api/v1/tracks` returns `201` with `track_id`, size, and SHA-256.
- Rejects: empty (`400`), over the size limit (`413`), unsupported extension (`415`).
- The uploaded filename never reaches disk — stored as `source.<ext>` under a UUID folder.

---

### X0R-202 · Rights-attestation gate · 2 · `DONE`
**As the** site owner **I want** processing blocked until the uploader affirms their rights **so that** the attestation is a control, not decoration.

**Acceptance criteria**
- Both checkboxes required; the API returns `403` without them regardless of what the UI sent.
- The attestation is recorded on the track and stamped into every `.x0r` export.
- Covered by a test asserting the `403`.

---

### X0R-203 · Upload UI with drag-and-drop · 3 · `PARTIAL`
Click-to-select and the attestation gate are built; drag-and-drop, client-side duration probe, and a real progress bar are not.

**Acceptance criteria**
- Drop zone responds to dragover/drop with a visible state change.
- Client reads duration via `AudioContext.decodeAudioData` and warns over the configured cap before uploading a byte.
- `XMLHttpRequest.upload.onprogress` drives a real percentage.

---

### X0R-204 · Chunked/resumable upload · 5 · `TODO`
**As a** user on a phone **I want** a dropped connection not to cost me the whole upload.

**Acceptance criteria**
- Files over 25 MB upload in chunks with a resumable session id.
- Killing the network mid-upload and retrying resumes rather than restarting.
- Abandoned sessions are garbage-collected on the retention sweep.

---

### X0R-205 · Audio probe and normalisation on ingest · 3 · `DONE`
**Acceptance criteria**
- Duration, sample rate, channels, and codec recorded on the track record. ✅
- Anything not 44.1 kHz stereo is normalised once, so downstream stages see one format. ✅
- Files under 5 s or over the maximum duration are rejected with a clear message. ✅

**Built differently from the card.** It specified `ffprobe`; the implementation prefers
`soundfile`, because the bundled libsndfile 1.2 reads WAV/FLAC/OGG/AIFF **and MP3** with
no system dependency at all. ffprobe is now only the fallback for m4a/aac. That took
ffmpeg off the Phase 1 critical path entirely.

Probing happens in the upload request — it is a header read, and it is what catches a
file that merely has an audio extension. Normalisation happens as the first step of the
separation job instead, so uploads stay fast and the decode gets a progress bar.

---

### X0R-206 · Rate limiting and abuse controls · 3 · `TODO`
**Acceptance criteria**
- Per-IP limits on upload count and total bytes per hour, returning `429` with `Retry-After`.
- Concurrent-job cap per client; excess is queued, not run.

---

## EPIC-03 — Stem separation

### X0R-301 · Separation contract and stub backend · 2 · `DONE`
**Acceptance criteria**
- `Separator` protocol returns `SeparationResult` with one file per `StemKind`.
- The stub runs anywhere and produces the full four-stem set, so the UI is buildable with no models.

---

### X0R-302 · Demucs v4 integration · 5 · `DONE`
Runs for real, verified on Python 3.12 / torch 2.13.0+cpu / demucs 4.1.0.

**Acceptance criteria**
- `htdemucs` produces drums, bass, vocals, other at 44.1 kHz with correct durations. ✅
- Failure surfaces as a `failed` job carrying the tail of Demucs' own output. ✅
- Model weights cached in a mounted volume, not re-downloaded per container start. ✅ compose config, unverified
- A three-minute song separates in under five minutes on 4 CPU cores. ✅ **measured**

`htdemucs_6s` produces all six stems — drums, bass, vocals, other, guitar, piano.
Measured on a real 4:17 track: **186 s, 0.72× realtime** on 8 CPU cores. A four-minute
song takes about three minutes.

**An earlier note here said 1.9× realtime and predicted the target would be missed. That
was wrong**, and wrong in an instructive way: it was measured on a 12-second synthetic
clip, where loading the model dominates the wall clock. Short-clip timings do not
extrapolate. Neither does the parallel speedup — `-j 4` measured 7% faster on a full
track, not the multiple the flag implies, and it crashes on Windows besides.

**The install was the hard part, not the code.** Windows MAX_PATH breaks
`pip install torch` inside this project tree and leaves a half-installed torch behind,
surfacing as `ModuleNotFoundError: No module named 'torchgen'`. The ML venv now lives on
a short path. Full write-up in docs/RUNBOOK.md.

**Found by running it:** Demucs exits 0 when handed a missing input file. A clean return
code is not proof of success, so the adapter also checks that stems were actually written
and includes Demucs' own output in the error.

---

### X0R-303 · Real progress from the separator · 3 · `DONE`
**As a** user **I want** the bar to move during separation **so that** I can tell the difference between working and hung.

**Acceptance criteria**
- Demucs' tqdm output is streamed, parsed, and mapped onto `JobHandle.update`. ✅
- Progress is monotonic and reaches 1.0 exactly once. ✅

`parse_progress()` is a pure function tested against captured CLI output, so a change in
Demucs' bar format is caught without a model download. Progress is clamped
non-decreasing because a bag-of-models run restarts its bar per model. Decoding owns the
first 5% of the job; the model owns the rest.

---

### X0R-304 · Stem preview playback · 3 · `DONE`
**Acceptance criteria**
- Each stem gets a waveform and an inline player in the studio. ✅
- Per-stem solo/mute during preview, with solo overriding mute as a DAW does. ✅
- Range requests supported so seeking does not re-download the file. ✅

Built as a stacked mixer rather than six separate players: one colour-coded lane per
instrument, all sharing a single grid column and one playhead, so the stack reads as one
song. Clicking any waveform seeks everything together.

Waveform envelopes are computed server-side and cached (`/stems/{stem}/peaks`) — shipping
six full stems to the browser to draw them would be hundreds of megabytes. They scale off
the 98th percentile rather than the maximum, so one snare crack does not flatten the song
into a flat line.

**This card turned out to matter more than its 3 points suggest.** It is the only way to
answer "is the tab wrong, or was the stem already wrong?", which is the first question
asked of every bad transcription.

---

### X0R-305 · Model selection in the UI · 2 · `TODO`
**Acceptance criteria**
- User chooses 4-stem (faster) or 6-stem (guitar + piano) before separation.
- The estimate shown comes from measured throughput, not a hard-coded guess.

---

### X0R-306 · Separation and transcription quality benchmark · 5 · `PARTIAL`
**Now the gating card for the whole transcription epic — promoted to lead sprint 2, and
re-sized from 3 to 5 because it must cover transcription as well as separation.**

**As a** developer **I want** a repeatable quality number **so that** a model or parameter change is a measurement, not a vibe.

**Acceptance criteria**
- SDR/SIR/SAR computed against a small licensed multitrack set (MUSDB18-HQ or self-recorded).
- Note-level precision/recall/F1 for transcription, with and without octave tolerance.
- Wall-clock separation time for a real three-minute song, as a realtime multiple.
- Results written to `docs/benchmarks/` with the model, backend versions, and commit.

**Why it was promoted.** Sprint 1 finished with every backend running and no idea whether
any of it is accurate. The end-to-end run on synthetic audio returned a bass line an
octave high and a tempo of 60 BPM against a true 120 — and a controlled check showed pYIN
reads those notes correctly from the *unseparated* signal, so the fault lay in feeding
Demucs synthetic sine waves it was never trained on.

The lesson is the important part: **synthetic audio cannot measure quality.** It exercises
the wiring and nothing else. Until there is a real eval set, every threshold in the
transcription stack — confidence cutoffs, minimum note length, pitch ranges — is a guess,
and X0R-405 and X0R-406 both have acceptance criteria parked waiting on this.

Recording a few DI bass and guitar parts gives exact ground truth faster than licensing
anything, and sidesteps the copyright question entirely.

**One item added 2026-10-02**, from the Melodyne probe: **pitch accuracy in cents on a
separated stem**, not only note-level F1. X0R-1320 reports how far a vocal sits from its own
tuning reference and measured 4.0 / 14.0 / 26.0 cents across three records; it ships that as
a caveated upper bound because nothing says what pYIN's own error through Demucs is. A DI
bass and a sung DI vocal answer it at the same time as the note-level criteria above.

**Status 2026-10-05: `PARTIAL`. The ruler is built and tested; two of the four criteria
are measured and two are waiting on twenty minutes of recording.**

| Criterion | State |
|---|---|
| SDR / SIR / SAR against a licensed multitrack set | **blocked** — there is no eval set |
| Note P / R / F1, with and without octave tolerance | **blocked** — there is no ground-truth note list |
| Wall clock for a real three-minute song, as a realtime multiple | **done** — 1.24× on CPU with `htdemucs_6s`, 0.94× with `htdemucs` |
| Results in `docs/benchmarks/` with model, versions and commit | **done** |

**What was built.** `app/services/benchmark/` holds the metrics, the eval-set format and
the report writer; `tools/benchmark.py` runs it; `docs/benchmarks/README.md` is how to
build a set. The metrics are `mir_eval`'s, not mine - so a number from here can sit next
to a number from a paper - and `tests/test_benchmark.py` proves this project reads them
correctly against signals whose answers are known on paper. That file is the one place
synthetic audio belongs in this card: it measures the ruler, and Demucs has nothing to do
with the question.

Three decisions in it are load-bearing and each one is a way to get a benchmark quietly
wrong. The permutation is **not** searched, so a model that filed the bass under `other`
scores as having failed. Long tracks are scored in thirty-second windows with the median
taken, because BSS Eval's cost grows with the square of the length. And cents accuracy is
measured over notes matched by **onset alone** - matching on pitch and then measuring
pitch is circular, and the circularity is invisible in the output because it just produces
a reassuringly small number bounded by whatever tolerance was passed in.

**What the first runs found.** Two models over one real three-minute track, twice each
in both orders: `htdemucs_6s` reconstructs to **-21.69 dB** at **1.24x** real time, and
`htdemucs` to **-27.08 dB** at **0.94x**. So the six-stem model is the faster one, which
is the opposite of what I expected and held in both orders - left as a measurement rather
than given an invented mechanism. And splitting into six loses 5.4 dB more of the track
than splitting into four, which is what the default costs to get piano and guitar. The
two bracket the -25.6 dB that `docs/API.md` and the Studio quote from an earlier one-off,
which is the first independent support that figure has had.

My first timing numbers were wrong and are not the ones above: I ran the test suite
during the separation, and the same track came back at 1.09x and then 1.24x. The report
template now says to read a small timing change as noise, and that reconstruction - which
repeated to the decimal place - is the one to trust.

**One metric was added that the card did not ask for**, because it is the only quality
figure that needs no ground truth and therefore works on every track anybody ever runs:
**reconstruction**, the residual between the mixture and the sum of its stems. It is the
number `preserve_source` exists because of. It is also the weaker question and is labelled
as such everywhere it appears - a separator that put the whole bass in the vocals file
would reconstruct perfectly and score well, which is asserted as a test.

**What is still needed, in the order it is worth doing.** All four are recording tasks,
and each is usable on its own:

1. **A DI bass to a click**, two minutes. Gives an exact reference stem, an exact note
   list, and the pitch-in-cents figure X0R-1320 currently ships as a caveated upper bound.
2. **A DI guitar over the same click.** Two stems means SDR and SIR become real.
3. **Drums with kick, snare and overheads on separate tracks.** The only route to
   DrumSep's per-stem bleed, which is the single most load-bearing unmeasured quantity in
   the project: every per-drum finding on the comparison screen says "some of this may be
   another drum" and cannot say how much.
4. **A sung DI vocal**, which separates pYIN's own pitch error from the singer's.

MUSDB18 remains the alternative the card names. It is the standard and it would make these
numbers comparable with the SiSEC leaderboard; it is also 22 GB, CC BY-NC-SA, and has to
be accepted and downloaded by a person, and it would not answer item 3 at all, because it
carries a drums stem rather than the drums inside it.

**One dependency note, now decided.** `mir_eval.separation` is deprecated as of 0.8 and
removed in 0.9, with upstream pointing at sigsep-museval. **Deferred, deliberately** -
see X0R-308, which is gated and must not be started before its trigger fires. The short
version: museval buys numbers on the MUSDB18 leaderboard's convention, and none of the
four eval sets this card is built around is MUSDB18, so what the benchmark needs is a
convention held *fixed* between runs rather than one that is standard. `mir_eval` is
pinned below 0.9 in both requirements files, with the unpin conditions written in the pin
comments themselves, and the whole BSS call is one function.

---

### X0R-307 · GPU path · 3 · `TODO`
**Acceptance criteria**
- `DEMUCS_DEVICE=cuda` is used when a GPU is present, CPU otherwise, decided at runtime.
- Documented CUDA container variant.

---

### X0R-308 · BSS Eval v4 via sigsep-museval, for MUSDB-comparable numbers · 2 · `TODO` *(gated)*
**As a** developer **I want** separation scores on the SiSEC convention **so that** a number
from this repo can sit next to a published MUSDB18 leaderboard entry rather than only next
to this repo's own previous run.

**Do not start before one of these is true, and say which in the PR:**
1. MUSDB18-HQ is on disk and has been run through `tools/benchmark.py`.
2. `mir_eval>=0.7,<0.9` no longer resolves in `requirements-ml.txt` or `requirements-dev.txt`.

Started before either, this adds fifteen packages - including a MUSDB dataset loader to a
project that does not load MUSDB - to make numbers comparable against an eval set that does
not exist. Note also that the eval set answering this project's most important open question,
DrumSep's per-stem bleed, is the one museval adds nothing to: MUSDB18 carries a `drums` stem
rather than the drums inside it, and BSS Eval over four drum mics has no MUSDB convention in
v3 or v4.

**Acceptance criteria**
- Museval is a **second** BSS backend behind a flag on `tools/benchmark.py`, not a
  replacement. The `mir_eval` path keeps working: it is the one that scores the per-drum
  bleed set.
- The report header names which convention produced each table - "BSS Eval v3,
  `bss_eval_sources`, mono downmix" or "BSS Eval v4, `bss_eval_images`, framewise". A reader
  must never have to guess which ruler a dB figure came from.
- Running one eval set through both backends is supported, and the delta between them is
  written to `docs/benchmarks/` once. That number is the only bridge between every
  pre-migration run and every post-migration one.
- The BSS assertions in `tests/test_benchmark.py` pass against both backends. They assert
  constructed facts - SIR 20 dB for a tenth of the other source, SDR above 100 dB for a
  perfect estimate, swapped estimates below 1 dB - so a backend failing them is wrong rather
  than differently conventioned. The exception is
  `test_a_long_signal_is_scored_in_windows_and_the_median_reported`, which asserts the
  framewise API's shape and will need rewriting for museval's.
- `docs/benchmarks/README.md` says which backend answers which question.
- The pins in both requirements files and the `metrics.py` docstring describe what was done
  rather than what was deferred.

**Out of scope**
- Removing the `mir_eval` path. It is not a fallback, it is the per-drum path.
- Restating historical runs in `docs/benchmarks/` on the new convention. The delta figure
  reconciles them; rewriting a dated record is worse than leaving it correctly labelled.
- `musdb`/`stempeg` as an ingest path. Museval is wanted for `museval.metrics`; the dataset
  loader arriving with it is a cost, and nothing under `app/` may import it.

**Not QA-verifiable in a browser**, and that is stated rather than hidden: `tools/benchmark.py`
never runs in the serving path. Every criterion is checkable from the generated
`docs/benchmarks/*.md` and the test suite, but a browser pass cannot confirm any of it.

---

## EPIC-04 — Transcription & tab

### X0R-401 · Note-event contract and stub transcriber · 2 · `DONE`
**Acceptance criteria**
- `NoteEvent` validates its own pitch range and time ordering.
- The stub is deterministic per input path, so tab-rendering tests are stable.

---

### X0R-402 · Fretboard solver · 5 · `DONE`
**As a** guitarist **I want** the tab to keep my hand in one place **so that** it is playable rather than technically correct.

**Acceptance criteria**
- Optimises position across a phrase, not note by note (Viterbi over onset clusters). ✅
- Chord notes never share a string; hand span never exceeds the configured maximum. ✅
- Out-of-range pitches are handled by an explicit, configurable policy. ✅ *revised — see below*
- Capo and span are configurable via `SolverConfig`. ✅
- Covered by tests asserting position stability, distinct strings, and note accounting. ✅

**Revised in sprint 1.** The original criterion — "out-of-range pitches raise
`UnplayableError` rather than being silently dropped" — was written against hand-entered
input and turned out to be wrong for model output. The first end-to-end run on real
Demucs + basic-pitch output died on a single G1 (MIDI 31) leaking from the bass into the
guitar stem: one stray note aborted the entire transcription.

`SolverConfig.unplayable` now selects `RAISE` / `DROP` / `FOLD`, defaulting to `DROP`.
`solve_with_report()` returns what was discarded, the counts reach the API as
`dropped_count` / `folded_count`, and the pipeline logs them — so nothing is *silently*
dropped, which was the point of the original criterion, without one bad note costing the
whole job.

---

### X0R-403 · ASCII tab renderer · 3 · `DONE`
**Acceptance criteria**
- One line per string, high string on top, bar lines on the beat, tempo and tuning in the header.
- Column spacing is quantised time, so rhythm is visible.
- Empty transcriptions render an empty staff plus an explanation, not a crash.

---

### X0R-404 · Drum tab renderer · 2 · `DONE`
**Acceptance criteria**
- GM percussion keys map to lanes (BD/SD/HH/T1/T2/FT/RD/CC); unused lanes are dropped.
- Open vs. closed hi-hat render as different noteheads.

---

### X0R-405 · Pitched transcription · 5 · `DONE`
Both backends run for real. The scope changed during the sprint — see below.

**Acceptance criteria**
- Polyphonic transcription of guitar and piano (basic-pitch). ✅
- Monophonic transcription of bass and vocals (pYIN). ✅
- Notes below the confidence threshold are filtered before reaching the solver. ✅
- Output survives the fretboard solver without unplayable pitches. ✅ smoke-tested
- A clean DI bass line transcribes with >= 90% note accuracy. ⏳ needs X0R-306's eval set

**Split into two backends, which was not the plan.** A bass line is monophonic, so a
polyphonic neural net is both slower and less accurate on it than a pitch tracker.
`PyinTranscriber` (librosa, no extra dependencies) now handles bass and vocals;
basic-pitch handles guitar, piano, and other. `TRANSCRIPTION_BACKEND=auto` chooses per
stem. Useful side effect: bass transcription works anywhere librosa does — no ONNX, no
torch.

**basic-pitch cannot be pip-installed on Python 3.12.** It pins `tensorflow<2.15.1`;
TensorFlow's oldest 3.12 wheel is 2.16. The package also ships ONNX weights, so it is
installed `--no-deps` and runs on onnxruntime. Verified: a 220 Hz sine gives exactly one
note, MIDI 57 (A3). `Transcription.backend` records `basic_pitch:onnx`, so the runtime is
visible in every `.x0r`. Write-up in docs/RUNBOOK.md.

**Found by running it:** librosa's default 2048-sample analysis frame is under two cycles
of a 5-string bass low B, which makes pYIN return wrong pitches *without raising
anything*. Frame length is now derived from the stem's lowest expected pitch.

---

### X0R-406 · Drum onset transcription · 5 · `PARTIAL`
Runs for real against librosa. Onsets, GM key mapping, and tempo detection are verified;
accuracy is not.

**Acceptance criteria**
- Finds the right number of onsets on a click track, and emits only GM drum keys. ✅
- Tempo comes from beat tracking, not the 120 BPM default. ✅
- Kick, snare, hi-hat separated with >= 80% F1 on the eval set. ⏳ needs X0R-306
- Toms and cymbals classified, or explicitly reported as unsupported. ❌ not started

**Found by running it: tempo octave ambiguity is real and immediate.** A 100 BPM click
track and a 200 BPM one both report ~99.4 BPM. That is normal beat-tracker behaviour
rather than a bug, but it means the tab grid can land at half or double time. Fixing it
needs a time signature and bar structure — so **X0R-407 is a prerequisite for trusting
drum output**, not a nice-to-have. Promote it accordingly.

---

### X0R-407 · Tempo, key, and time-signature detection · 3 · `DONE`
**As a** user **I want** the grid to match the song **so that** the tab lines up with bars instead of drifting.

**Acceptance criteria**
- Tempo from the full mix, not per stem, applied to every stem's grid. ✅
- Time signature detected **and** user-selectable; the metre drives bar lines. ✅
- A detected key is shown and used to prefer enharmonic spellings. ✅
- Tempo is user-overridable, with ×2 and ÷2 for the octave case. ✅

**The octave fix.** Rather than trusting the beat tracker, every octave of its reading is
scored against the onsets with an F-measure — precision is how many onsets land on a
beat, recall is how many beats carry an onset. The symmetry is the point: scoring only
precision ranks double-time perfectly, since every onset on a beat at N is also on one at
2N, and recall is what punishes the empty beats a doubled grid invents. Measured against
librosa on click tracks: **5 of 6 tempos correct**, including the 100 BPM case that
previously read 99.4 for both 100 and 200 BPM.

**Metre detection was rewritten mid-card.** The first version asked whether an onset
*existed* on the downbeat and reported 0.99 confidence on wrong answers — music that plays
on every beat fits any bar length equally well. It now compares onset *strength* on
candidate downbeats against the other beats, and returns 4/4 with **zero** confidence when
there is no accent, rather than inventing evidence. Confidently wrong is worse than
admitting ignorance.

**Detection is not good enough to trust blindly, and the UI says so.** A reading below 0.6
confidence is flagged in the studio. Overriding is part of the normal workflow, not an
escape hatch — the person who wrote the song knows its tempo. The original reading is kept
in the timing `source` so a correction is never silent.

---

### X0R-408 · Confidence surfacing and manual correction · 5 · `TODO`
**As a** user **I want** to see and fix what the model guessed at **so that** a near-miss is usable instead of discarded.

**Acceptance criteria**
- Low-confidence notes are visually flagged in the preview.
- Click a note to change pitch, string, fret, or delete it; the solver re-runs downstream of the edit.
- Edits persist into the `.x0r` and every subsequent export.

---

### X0R-409 · Tuning detection · 3 · `TODO`
**Acceptance criteria**
- The guitar/bass stem's pitch histogram is compared against known tunings and the best match is pre-selected.
- Detected tuning is shown with its confidence and can be overridden.

---

### X0R-410 · Techniques: bends, slides, hammer-ons, palm mutes · 5 · `TODO`
**Acceptance criteria**
- Pitch-contour analysis marks bends (`b`), slides (`/` `\`), hammer-ons (`h`), and pull-offs (`p`).
- Notation renders in both the ASCII tab and the `.x0r`.
- False-positive rate on the eval set stays under 10%.

---

### X0R-411 · Vocal and lead pitch line · 3 · `TODO`
**Acceptance criteria**
- Monophonic pitch tracking (CREPE or pYIN) on the vocal stem.
- Rendered as a note-name/timing list, explicitly not as tab.

---

### X0R-412 · Sample-accurate hit times, separately from triggering · 2 · `TODO`
**As a** developer measuring groove **I want** onset times that mean what they say **so that**
a figure derived from them is about the music and not about the detector.

`drums/detect.find_hits` calls librosa with `backtrack=True`, which walks every onset back
to a local minimum of the envelope by a variable amount. That is the right choice for what
it was written for — triggering a replacement sample wants the start of the transient — and
it is fatal for anything that reads the *time*.

Measured during the pr0ducer Experiment 1: re-placing the same kick events at sample
accuracy moved one track's hit spread from 7.67 ms to 6.83 and another's from 8.48 to 4.29.
**The ranking of the two reversed.** The detector was contributing 1–7 ms to a figure whose
whole signal is a few milliseconds, which is why "programmed versus played" could not be
measured honestly and was cut from that epic.

Nothing shipping is wrong today, because nothing yet reads these times for their own sake.
This is a card so that the next thing to try does not rediscover it.

**Re-checked for sprint 2 and deliberately not sprinted.** The path that matters avoids it:
`drums/separate._onsets` runs `backtrack=False` on purpose, with the reason in its docstring,
and `find_hits`' backtracking remains correct for the triggering it was written for. Nothing
in EPIC-13's stage 3B reads a hit time for measurement — the per-drum comparison reads
continuous band energy and level from the sub-stem audio. This card is needed by the first
card that measures *groove* (hat placement, swing, pattern comparison, programmed versus
played), and it stays here as the tripwire for that card rather than as work to do now.

**Re-measured 2026-10-02 on *pitched* stems, and it is four times worse there.**
`PyinTranscriber.transcribe` calls the same detector with the same `backtrack=True`, so every
note start it produces inherits this. Pairing the same onsets with and without backtracking
across three records: bass moves a median 14–17 ms (SD 6–9, max 41) and **vocals a median
23–29 ms (SD 13–17, max 75)**, against the 7 ms `DETECTOR_JITTER_MS` set from drums and a
real microtiming signal of 5–50 ms. It is larger than the thing being measured and the SD
says it cannot be subtracted as a constant. This card is therefore a **blocker**, not a
dependency, for the pitched half of X0R-1322. See
[PR0DUCER.md §10.4(b)](proposals/PR0DUCER.md).

**Acceptance criteria**
- A way to get hit times without backtracking, alongside the triggering-oriented ones.
- The two documented against each other, with the measured difference, so the choice is
  made deliberately rather than by whichever was imported first.
- A test that a synthesised click track's hits land within a millisecond of where they
  were placed.

---

### X0R-414 · Separate the drums into kick, snare and cymbals · 5 · `DONE`
**As a** person replacing drums **I want** each drum as its own audio **so that** a kick
sample lands on kicks and a snare sample lands on snares, every time.

Asked for directly: *"any drum replacement should happen per-drum. kick for kick, snare
for snare"*, and then, after the classifier was corrected, *"snare still seems to come in
and out at various kick hits."*

Both reports have one cause. `drums/detect` asks a *summed* drum stem which drum is
playing, by comparing how far two frequency bands rose. On real material those numbers are
often within a decibel of each other — measured on one 28-second clip, **six of
twenty-seven kicks sat within 6 dB of the line**, with consecutive kicks at -0.5, +5.3 and
-0.7 dB. A hard threshold across a straddling quantity does not give a few wrong labels,
it gives flicker, and flicker is what an ear picks out.

`kit.replaceable` currently stops the flicker reaching the speakers by allowing one drum
per stroke. That is a workaround and says so. **No threshold fixes this**, because the
information needed to decide is not in the summed stem.

What does fix it is a second separation pass: drums in, kick/snare/cymbals out, as audio.
Then replacement is per-drum by construction and needs no classifier at all — and the
per-instrument comparison gains three more things it can compare.

**Two models exist and both are real:**

- **[DrumSep](https://github.com/inagoy/drumsep)** — a Hybrid Demucs fine-tune, **MIT
  licensed**, four stems (kick, snare, cymbals, toms). Same architecture family as the
  separator already installed, so it is the same runtime, the same torch, and very nearly
  the same code path. An ONNX build also exists, and `onnxruntime` is already a
  dependency. **Start here.**
- **[LarsNet](https://github.com/polimi-ispl/larsnet)** — five stems including hi-hat
  separately from cymbals, five parallel U-Nets, faster than real time on CPU. Two
  caveats that matter: the pretrained weights are **CC BY-NC 4.0**, and it was trained on
  StemGMD, which is *synthesized* from MIDI — so a domain gap against real recordings is
  likely and should be measured rather than assumed.

**Acceptance criteria**
- ✅ A drums stem separates into kick, snare, cymbals and toms behind the existing
  separation seam, as an opt-in second pass — `app.services.drums.separate`,
  `DRUMSEP_ENABLED`, default off.
- ✅ `kit.layer` triggers from the separated stems. Measured on a 28 s clip: **zero**
  strokes carry more than one drum, where the classifier put kick *and* snare on three.
- ⚠️ `replaceable` is **kept**, not deleted — see below.
- ✅ Measured against the classifier on the same clip. Classifier: 82 strokes, 24
  kick+hihat, 19 snare+hihat, 3 claiming both kick and snare. Separation: 164 strokes —
  60 kick, 56 cymbals, 24 snare, 24 toms, none ambiguous. The kick count is the telling
  one: 60 strokes at every gate from −6 to −30 dB, which is a programmed
  four-on-the-floor and exactly what the record is.
- ✅ Licence recorded in [models/README.md](../models/README.md): MIT, © 2024 Iñaki
  Goyeneche. LarsNet was considered and rejected on its CC BY-NC weights and its
  synthesised training set.
- ✅ Opt-in and costed: ~16 s on CPU for a 30 s clip, about half the audio's length again
  on top of the main separation.

**Why `replaceable` stays.** The card asked for it to be deleted. Deleting it would mean
that a machine without the 167 MB weights — a fresh clone, or anyone who has not
downloaded them — gets the flicker back, because the fallback is still the band-rise
classifier. The workaround now guards only that fallback rather than the main path, which
is the useful half of "deleted". Its docstring points here.

**One thing the model made visible.** Onset detection on an isolated stem finds far more
strokes than on a summed one, and most of the extra are bleed: the snare file carried 103
strokes in 28 seconds where a backbeat at 125 BPM allows about 29. `QUIET_STROKE_DB`
gates each drum against its own loudest stroke. The threshold is a judgement and the
module says so — the kick has no knee because every stroke is the same, the cymbals have
one at about −14 dB, and the snare has none at all, sloping smoothly from backbeat into
bleed.

---

## EPIC-05 — Export

### X0R-501 · Plain-text tab export · 1 · `DONE`
**Acceptance criteria**
- `GET /tracks/{id}/tabs/{stem}` returns `text/plain` with a download disposition.

---

### X0R-502 · `.x0r` session container · 3 · `DONE`
**As a** user **I want** one file that holds everything **so that** I can reopen the session and see how it was produced.

**Acceptance criteria**
- JSON with a schema version, per-stem notes with exact timings, solved shapes, tuning, and the rendered tab.
- Provenance: source SHA-256, both backend names and versions, timestamp, rights attestation.
- Carries the copyright notice inside the file.

---

### X0R-503 · MIDI export · 2 · `TODO`
**Acceptance criteria**
- One `.mid` per stem, plus a combined multi-track file with named tracks.
- Drums land on channel 10 with GM keys.

---

### X0R-504 · MusicXML export · 3 · `TODO`
**Acceptance criteria**
- MusicXML 4.0 with `<technical><string>`/`<fret>` for tab staves.
- Imports cleanly into MuseScore 4 and Guitar Pro 8.

---

### X0R-505 · PDF tab export · 3 · `TODO`
**Acceptance criteria**
- Paginated, printable A4/Letter with title, tuning, tempo, and bar numbers.
- The copyright notice is on the page, not just in the app.

---

### X0R-506 · `.x0r` re-import · 1 · `TODO`
**Acceptance criteria**
- Uploading a `.x0r` restores the session read-only, without the source audio.
- An unknown `schema_version` is rejected with a clear message.

---

## EPIC-06 — Legal & compliance

### X0R-601 · Notices defined once, served everywhere · 2 · `DONE`
**Acceptance criteria**
- `app/legal.py` is the only source; the API serves it at `/api/v1/legal` and the web app renders it.
- The same notice is embedded in every `.x0r` export.

---

### X0R-602 · Terms, copyright, and DMCA pages · 2 · `DONE`
**Acceptance criteria**
- Terms page covers scope, uploader obligations, no-licence-granted, retention, accuracy, and enforcement.
- DMCA page lists the six required notice elements and the counter-notice route.
- Both are reachable from the footer of every page.

---

### X0R-603 · Retention enforcement · 2 · `DONE`
**As a** user **I want** my audio actually deleted **so that** the privacy claim is true.

**Acceptance criteria**
- Boot sweep purges track folders past the retention window.
- `DELETE /tracks/{id}` removes the directory and the record immediately.
- Covered by a test that ages a directory and asserts it is gone.

---

### X0R-604 · Legal review of the notices · 2 · `TODO`
**Blocks public launch.** The current copy was written by engineers and says so on the page.

**Acceptance criteria**
- A qualified lawyer reviews the terms, privacy, and DMCA copy for the launch jurisdiction.
- Registered DMCA agent (US) if the site accepts third-party uploads.
- The "written by engineers" banner is removed only after that review.

---

### X0R-605 · Scheduled retention sweep · 1 · `DONE`
**Acceptance criteria**
- Sweep runs on a timer (`RETENTION_SWEEP_MINUTES`), not only at boot. ✅
- Each sweep logs a count for audit, including zero. ✅

An asyncio task owned by the app lifespan and cancelled cleanly on shutdown. The purge
runs in a worker thread so a large storage directory cannot block the event loop.

---

### X0R-606 · Abuse reporting and takedown workflow · 3 · `TODO`
**Acceptance criteria**
- In-app report form producing a ticket with the track id and reporter details.
- Takedown deletes the material and records who acted and when.
- Repeat-infringer counter per account.

---

### X0R-607 · Privacy policy and cookie posture · 1 · `TODO`
**Acceptance criteria**
- Policy states what is stored, for how long, and what the retention sweep deletes.
- No non-essential cookies in the MVP, so no consent banner is needed — stated explicitly.

---

## EPIC-07 — Persistence & operations · `NON-GOAL`

**Decided against on 2026-10-01.** Every card below assumes a hosted, multi-user service:
a database behind the registry, a queue behind the jobs, object storage behind the files,
accounts in front of all of it. extract0r is not that. It is a local-first tool that runs
on one machine, holds one person's music, and deliberately keeps `profiles/` and
`storage/` off the network entirely — which is the privacy posture the app's own terms
describe, not an implementation detail waiting to be upgraded.

Building this would not make the tool better at the thing it is for. It would add an
install story, a migration story and a login screen to an application whose current
install story is "run two scripts", in service of a scaling problem that does not exist
for one person mastering their own songs.

The seams stay where they are. `TrackRegistry`, `JobStore` and `TrackStorage` are already
interfaces, and the retention sweep already honours a window. If this ever becomes a
hosted product, these cards are the plan and nothing here forecloses them.

**Two pieces worth keeping, re-homed rather than lost:**

- **Structured logging with a correlation id** (part of X0R-705) is useful on one machine
  too — when a separation fails at 60%, a log line that names the job is the difference
  between a diagnosis and a guess. Carried forward as X0R-707 below.
- **Live job progress** (X0R-706) already exists in a different form: the Studio polls and
  shows a progress bar with a running clock. The card describes replacing that with a
  stream in `lib/api.ts`, a file belonging to the retired Next.js front end.

---

### X0R-707 · Structured logs with a job correlation id · 2 · `TODO`
The one part of EPIC-07 that pays off on a single machine. Kept out of the non-goal above.

**Acceptance criteria**
- Every log line emitted during a job carries that job's id.
- A failed separation can be traced from the error shown in the browser to the backend
  lines that produced it, without raising the log level.
- Local files, no shipping anywhere — this is for reading, not for monitoring.

---

### X0R-701 · Postgres-backed track and job records · 5 · `NON-GOAL`
Replaces the in-memory `TrackRegistry` and `JobStore`.

**Acceptance criteria**
- SQLAlchemy models for tracks, stems, jobs, and exports; Alembic migrations.
- Restarting the API does not lose in-flight or completed job state.

---

### X0R-702 · Redis/RQ worker · 5 · `NON-GOAL`
**Acceptance criteria**
- Jobs survive an API restart and run in a separate worker process.
- Workers scale horizontally; `MAX_CONCURRENT_JOBS` becomes a worker-count concern.
- `JobStore` callers are unchanged (the seam already exists).

---

### X0R-703 · Object storage · 3 · `NON-GOAL`
**Acceptance criteria**
- S3/R2 behind the same `TrackStorage` interface, selected by config.
- Downloads use pre-signed URLs; the API never proxies audio bytes.
- Lifecycle rules mirror the retention window server-side.

---

### X0R-704 · Accounts and track history · 5 · `NON-GOAL`
**Acceptance criteria**
- Email magic-link auth; anonymous use still works with a shorter retention window.
- Signed-in users see their previous tracks and can re-download exports.

---

### X0R-705 · Observability · 3 · `NON-GOAL`
**Acceptance criteria**
- Structured JSON logs with a request/job correlation id.
- Metrics: job duration by kind, failure rate by backend, queue depth.
- Health endpoint reports backend availability, not just process liveness.

---

### X0R-706 · Live job updates over WebSocket/SSE · 3 · `NON-GOAL`
**Acceptance criteria**
- Replaces the polling loop in `lib/api.ts` with a stream, falling back to polling.
- A dropped connection reconnects and resyncs without losing progress state.

---

## EPIC-08 — Reference mastering (Phase 2)

### X0R-801 · Mastering engine · 5 · `DONE`
**Acceptance criteria**
- EBU R128 measurement of target and reference (integrated LUFS, true peak). ✅
- Target matched to the reference's integrated loudness with a −1 dBFS ceiling. ✅
- LRA (loudness range). ❌ needs gated short-term blocks; reported as 0.0 rather than faked

**Rebuilt around numpy rather than ffmpeg.** The original design shelled out to ffmpeg
for filtering and encoding, which meant Phase 2 could not run at all on a machine where
Phase 1 worked perfectly — including this one. numpy, scipy, `lameenc` and `pyloudnorm`
were already installed as transitive dependencies of the ML stack, so the whole chain now
runs with no external process. ffmpeg remains supported for m4a/aac input and nothing else.

Loudness is LUFS via ITU-R BS.1770 K-weighting, falling back to RMS with an explicit
warning when `pyloudnorm` is absent — a number labelled LUFS that is really RMS is worse
than no number.

---

### X0R-802 · Reference-track upload · 2 · `DONE`
**As a** user **I want** to upload a commercial track as a reference **so that** my mix sits in the same ballpark.

**Acceptance criteria**
- Reference upload goes through the same rights gate as the source. ✅
- References live inside the track folder, so retention deletes them with it. ✅
- The UI states that the reference is analysed, never sampled or mixed in. ✅
- Its measured loudness is shown on upload, so the target is visible before committing. ✅

Storing the reference *inside* the track directory is the mechanism, not a convenience:
the retention sweep deletes a folder, so a reference cannot outlive the track it was
uploaded for.

---

### X0R-803 · Spectral reference matching · 5 · `DONE`
**Acceptance criteria**
- STFT-based frequency-response matching plus loudness matching. ✅
- Result lands close to the reference's integrated loudness. ✅ within ~1.5 LU on test material
- Before/after loudness and the EQ curve are shown in the UI. ✅

**Written rather than pulled in.** `matchering` does not install cleanly here, and the
algorithm is not mysterious: average the long-term spectra, smooth both across log
frequency, divide, clamp, apply, then match level. Writing it means the behaviour is
tunable and unit-testable rather than opaque.

Three decisions worth keeping:

- **The curve is clamped** (+6 dB boost, −12 dB cut). Unclamped, it tries to turn any mix
  into any other and the result sounds broken. Boost is capped harder than cut because
  lifting a band the target barely contains amplifies noise and separation artefacts.
- **Smoothing is per-octave, not per-Hz**, because hearing is logarithmic — and without
  it the curve fits the partials of whatever note happened to be playing.
- **Tone and level are matched separately**, and the curve is normalised to be
  level-neutral. Conflating them makes both impossible to reason about.

A reconstruction test caught a real bug here: the overlap-add applied an analysis window
but normalised as though there were a synthesis window too, making every master exactly
4/3 too loud. Silent, and invisible without a round-trip test.

---

### X0R-804 · Mastering preview and A/B · 3 · `TODO`
**Acceptance criteria**
- 30-second preview rendered before committing to a full pass.
- Loudness-matched A/B toggle, so the louder version does not simply "win".

---

### X0R-805 · Per-stem vs. bus mastering · 3 · `TODO`
**Acceptance criteria**
- User chooses whether matching applies to the summed mix or to each stem.
- Per-stem mode warns that stem-level matching against a full-mix reference is musically dubious.

---

### X0R-806 · Mastering guardrails · 2 · `TODO`
**Acceptance criteria**
- Refuses to push a target more than a configured maximum gain, with an explanation.
- Flags a reference that is itself clipped or hyper-compressed as a poor choice.

---

### X0R-807 · Mastering quality report · 3 · `TODO`
**Acceptance criteria**
- Downloadable report: source/reference/result LUFS, true peak, LRA, spectrum overlay.
  ⏳ the spectrum overlay itself shipped as X0R-808; this card is the downloadable report
- Warnings for inter-sample peaks and for LRA collapse.

---

### X0R-808 · Three songs on one axis · 3 · `PARTIAL`
**As a** user **I want** to see my mix, my master and the reference on one set of axes **so
that** I can tell whether the master actually moved toward the reference.

Asked for directly: *"i want to see the EQ band displayed for both the original file,
updated song, and reference song to see how they align."*

**Built, tested, and not yet verified in a browser — X0R-1123 is that gate.**
`app/services/mastering/spectrum_view.py`, `apps/studio/wwwroot/spectrum.js`,
`GET /{track_id}/master/spectrum`.

**Acceptance criteria**
- ✅ Three curves — source, master, reference — on one log-frequency axis, 160 points.
- ✅ Each curve shifted by its own integrated loudness before drawing, and the shift
  reported per curve. Three songs at three loudnesses sit at three heights and the eye
  reads that offset as tone; what is left after the shift is balance.
- ✅ Smoothed to a third of an octave, the same width `matching_curve` uses, so a difference
  visible here is one the correction engine can act on.
- ✅ A Balance view and a Difference view, and a hover readout per curve. (Independently the
  same pair REFERENCE 2 offers — the curve needed to match, or the inverted difference.)
- ✅ This module decides nothing. It measures three recordings the same way; every other
  module in the package makes a judgement.
- ❌ Verified in a browser. → X0R-1123

---

### X0R-809 · The target as a range, not a line · 3 · `TODO`
**As a** user **I want** to be told whether my tone is inside the target **so that** I am
not asked to compare three overlapping curves by eye.

From Tonal Balance Control 2, which offers a Broad View of four bands with the target drawn
as a range and your mix as a single line, and a Fine View across the full spectrum. The
instruction collapses to "move until the line is inside the band", which costs far less
reading than three curves do.

**Deliberately held back from sprint 1.** X0R-808 shipped days ago, to a direct request,
and has not been through QA. Redesigning it before it has been looked at is the churn Ryan
named. Do this once X0R-808 is verified and has been lived with.

**Acceptance criteria**
- A broad view over the five bands the rest of the app already uses, with the reference
  drawn as a tolerance range rather than a curve.
- The source and the master each read as inside or outside per band, in words as well as
  graphically.
- The existing three-curve view stays, as the fine view. One control switches between them.
- The tolerance is derived from something measurable and stated on screen, not picked to
  look generous.

---

## EPIC-09 — Mix editor (Phase 2)

### X0R-901 · Mix specification model · 3 · `DONE`
**Acceptance criteria**
- Per-stem gain, pan, mute, solo, EQ bands, compressor, reverb — validated at the API boundary.
- Solo overrides mute the way a DAW does; an all-muted mix is a validation error, not silence.
- The filter-graph builder is pure and unit-tested without ffmpeg.

---

### X0R-902 · Mixer UI · 5 · `TODO`
**Acceptance criteria**
- Channel strip per stem: fader (dB scale), pan, mute, solo, meter.
- Keyboard accessible; drag with `Shift` for fine adjustment.
- State survives a page reload.

---

### X0R-903 · Web Audio real-time preview · 8 · `TODO`
**As a** user **I want** to hear changes as I make them **so that** mixing is not a render-and-wait loop.

**Acceptance criteria**
- Stems load into Web Audio with `GainNode`/`StereoPannerNode`/`BiquadFilterNode` per channel.
- Fader moves are audible in under 50 ms.
- Playback stays sample-aligned across stems on a 5-minute track.

---

### X0R-904 · Parametric EQ with a visual curve · 5 · `TODO`
**Acceptance criteria**
- Draggable band handles over a live spectrum analyser.
- Low/high shelf, up to four peaking bands, HPF/LPF per stem.
- The Web Audio preview and the ffmpeg render produce the same curve within 0.5 dB.

---

### X0R-905 · Effects: compression and reverb · 3 · `PARTIAL`
**Acceptance criteria**
- Vocal ducking: competing stems pulled down inside the vocal band while the vocal sings. ✅
- A limiter on the master bus with envelope-following gain reduction. ✅
- Compressor with threshold, ratio, attack, release, makeup, plus metering. ❌
- Reverb as a send with a wet/dry control. ❌
- Doubling/widening as an effect (short delay plus detune), distinct from M/S width. ❌

**Ducking landed early, ahead of the general effects work**, because a user reported
vocals sitting too quiet and level alone does not fix that. A vocal can be at the right
level and still be hard to follow, since guitars and keys occupy the same 1-4 kHz band.
Raising the vocal until it wins just makes everything loud; moving the competing parts
aside while it sings is what actually works.

Band-limited rather than broadband, because ducking a guitar's whole spectrum makes the
arrangement quieter without making the vocal any clearer, and is far more audible as an
effect. Bass and drums are never ducked - they sit above and below a vocal.

---

### X0R-907 · Vocal placement floor · 2 · `DONE`
**As a** user **I want** the vocal to sit where a listener expects **so that** matching a
reference cannot leave it buried.

**Acceptance criteria**
- A target placement in LU relative to the mix, selectable back / natural / forward. ✅
- Applied as a floor after reference matching, so it only ever lifts. ✅
- Capped, with the cap explained when it binds. ✅
- The result reports where the vocal was, where it was aimed, and how far it moved. ✅

**A measurement first, and it disproved the obvious theory.** The suspicion was that
integrated loudness under-measures vocals because they are intermittent while guitars run
continuously. On a real track, integrated and active-only loudness were identical
(-15.6 LUFS both): R128 gating already excludes silent blocks.

What the measurement *did* show is that the vocal sat at -6.8 LU below the mix where a
modern master places one nearer -4, and that nothing in the chain had an opinion about
that. Reference matching sets each instrument from the reference, which says nothing
about what a vocal *should* do - so a reference lacking a vocal, or imperfect separation,
leaves the vocal wherever the arithmetic drops it.

Verified end to end by measuring vocal-band energy of the exported MP3 at each setting:
0.3241 with placement off, 0.3355 at natural (+2.5 dB lift), 0.3506 at forward (+4.5 dB).
"Back" correctly did nothing, because this track's vocal already sat at exactly that
target.

---

### X0R-906 · Undo/redo and mix presets · 2 · `TODO`
**Acceptance criteria**
- Full undo history over every mix parameter.
- Save and recall named presets; presets are part of the `.x0r`.

---

## EPIC-10 — Mixdown & export (Phase 2)

### X0R-1001 · Render selected stems to one MP3 · 3 · `DONE`
**Acceptance criteria**
- Only stems the user selected are summed; solo/mute honoured. ✅
- Bitrate selectable (128/192/256/320). ✅
- Output is not clipped. ✅ enforced by a limiter and covered by a test

Encoding is `lameenc` — a LAME binding, not a subprocess — so export works with no
ffmpeg. Mixing deliberately does **not** normalise the sum: separation is additive, so
stems at unity reconstruct the original mix, and rescaling would quietly change the
balance the user set.

The limiter is the interesting part. It started as a single static gain reduction, which
is transparent but lets one transient decide the level of an entire song — matching a
loud reference landed 11 dB short. It now rides the gain with a fast attack and slow
release, which leaves the body of the track untouched. Measured: a track with one loud
spike keeps its full level under the limiter and loses 6 dB under peak normalisation.

---

### X0R-1002 · Additional export formats · 2 · `TODO`
**Acceptance criteria**
- WAV (16/24-bit) and FLAC alongside MP3.
- Stem bundle as a ZIP with a manifest.

---

### X0R-1003 · Export metadata and watermarking of provenance · 2 · `TODO`
**Acceptance criteria**
- ID3 tags record that the file was produced by Extract0r, with the source hash.
- Deliberately not an audio watermark — a metadata provenance record.

---

### X0R-1004 · Render queue and progress · 3 · `TODO`
**Acceptance criteria**
- Renders go through the same job store with real percentage from ffmpeg's `-progress`.
- Cancelling kills the ffmpeg process and cleans up partial output.

---

### X0R-1005 · Export history · 3 · `TODO`
**Acceptance criteria**
- Every export listed with its settings and a re-download link, until retention deletes it.
- Re-render from a past export's settings in one click.

---

## EPIC-11 — Per-instrument matching (Phase 2)

The whole-mix comparison can only move the sum. It can see that a reference has more low
end and it cannot see whether that means the bass should come up or the kick needs weight,
so it tilts everything and takes the bass guitar with it. This epic compares each
instrument with its counterpart in the reference and turns each difference into its own
control.

### X0R-1101 · Measure one instrument across the dimensions a mix note uses · 3 · `DONE`
**As a** mixer **I want** my snare described the way I would describe it **so that** the
comparison says something I can act on.

**Acceptance criteria**
- ✅ Level relative to the stem's own mix, never absolute.
- ✅ Tone in five bands, measured as a share of the stem so it is shape and not level.
- ✅ Dynamic range as p95 − p10 of short-term level, silence gated out (`dynamics`).
- ✅ Crest as peak minus RMS, reported separately because it is a different question.
- ✅ Stereo balance and width.
- ✅ Saturation deliberately absent: added harmonics cannot be told from played ones
  without the dry signal, and an invented number is worse than an honest gap.

---

### X0R-1102 · A tone control whose dial reads true · 2 · `DONE`
**As a** mixer **I want** "+3 dB of air" to deliver 3 dB **so that** the number on the
screen means something.

**Acceptance criteria**
- ✅ Filter gains solved from a band-response matrix rather than set to the band's own
  number — the naive version under-delivers by about a third and the filters fight.
- ✅ Weighted by the stem's own spectrum, because what a filter does to a band depends on
  where in that band the energy is.
- ✅ Measured: asking for +3 dB moves the band 2.99 dB against the other four.

---

### X0R-1103 · Compression calibrated in dB of range removed · 2 · `DONE`
**As a** mixer **I want** to ask for an outcome **so that** the setting means the same
thing on every stem it is pointed at.

**Acceptance criteria**
- ✅ Threshold placed half a knee above the quiet end so the floor is untouched.
- ✅ Ratio solved for the requested reduction, then measured and corrected once.
- ✅ Measured: asking for 3 dB removes 2.94.
- ✅ Level-matched afterwards, so the control is a balance and not a volume.
- ✅ Refuses to compress material that is already flat.

---

### X0R-1104 · Compare the two and offer a dial per difference · 3 · `DONE`
**Acceptance criteria**
- ✅ `POST /reference/instruments` returns each instrument with its moves and their controls.
- ✅ An instrument the reference does not play is named as such, not matched to residue.
- ✅ Bass is never asked to move sideways.
- ✅ Findings with no honest fix (transients) come back as notes with no dial.
- ✅ Comparing a track with itself suggests nothing.

---

### X0R-1105 · Take a suggestion one at a time · 2 · `DONE`
**Acceptance criteria**
- ✅ Each difference has its own slider and Apply, plus "take all" per instrument.
- ✅ Taking one by hand switches the automatic per-stem match off and says why.
- ✅ Applied state compares within half a slider step, not exactly.
- ✅ The moves reach the rendered file (`test_stem_shape_render`).

---

### X0R-1106 · Hear both sides · 2 · `DONE`
**Acceptance criteria**
- ✅ Reference stems stream with Range support, so seeking does not re-download.
- ✅ "Hear yours" solos the stem in the transport; "hear the reference" plays its
  counterpart on its own.
- ❌ A true locked A/B that crossfades between the two at the same musical position.
  Needs beat alignment between two different recordings — not just the same timestamp.

---

### X0R-1107 · Real-time monitoring · 3 · `DONE`
**As a** mixer **I want** to hear a setting without rendering **so that** the loop is
seconds rather than a minute.

**Acceptance criteria**
- ✅ Each stem routed through a Web Audio chain mirroring the server's channel strip.
- ✅ The EQ solve matrix is sent from the server, so the monitor runs the same band gains
  as the export rather than being a third out.
- ✅ Gain, mute, pan and width move through the graph, so a fader above unity is audible.
- ✅ Falls back to plain playback where Web Audio is unavailable.
- ✅ The page says plainly where the monitor and the render differ.
- ❌ Master-bus controls are not monitored: they act on the sum, after this point.

---

### X0R-1113 · Nudge toward the reference, never copy it · 3 · `DONE`
**As a** mixer **I want** suggestions that move my song toward a record I admire **so
that** it still sounds like my song afterwards.

**Acceptance criteria**
- ✅ Every suggestion is half the measured gap, capped at 3 dB per band and per fader.
- ✅ The whole measured gap is still reported next to what is being offered.
- ✅ Gaps large enough to be arrangement rather than mixing are flagged, not offered.
- ✅ Sliders reach further than the suggestions, so the user can go on if they want.
- ✅ Measured: drift from the user's own mix halved (4.98 → 2.55 dB) while the combined
  result landed *closer* to the reference than the old behaviour (2.85 vs 3.20 dB).
- ✅ Headlines reworded as observations — "the reference's drums have more presence" —
  rather than as faults in the user's mix.

---

### X0R-1114 · One upload, both splits · 2 · `DONE`
**Acceptance criteria**
- ✅ Song and reference both given on the first screen; one button runs both splits.
- ✅ The first screen says what will happen and roughly how long it takes.
- ✅ Matching the reference per instrument is an explicit, optional choice.
- ✅ Lands directly on the comparison when there is one, rather than on the mixer.

---

### X0R-1115 · Fewer clicks, and a way back · 2 · `DONE`
**Acceptance criteria**
- ✅ "Try all" is a button in each instrument's header, not a link beneath the rows.
- ✅ Apply is a toggle: pressing it again undoes that one move.
- ✅ Per-instrument undo appears once anything is applied.
- ✅ Bulk apply skips the moves flagged as worth hearing first.

---

### X0R-1116 · Auditions start where the music is · 1 · `DONE`
**Acceptance criteria**
- ✅ Each side starts at its own busiest stretch, found from a rolling loudness window.
- ✅ Measured on a real pair: the vocal's busy part began at 63.6 s in the source and
  142.5 s in the reference, so a shared playhead would have been wrong.
- ✅ Auditions stop themselves after twelve seconds, and there is a stop button.
- ✅ Stopping clears the solo, so the next thing played is the whole mix.

---

### X0R-1117 · A curve that does not comb · 2 · `DONE`
**As a** mixer **I want** applied suggestions to sound like EQ **so that** the master does
not come back hollow and swirly.

**Acceptance criteria**
- ✅ The band-to-filter solve is damped, so overlapping filters are not set in opposition.
- ✅ Worst swing inside one octave fell from 3.56 dB to 1.81 dB on a single-band request.
- ✅ A boost no longer has to dig a notch beside it: the curve floor went −1.36 → −0.28 dB.
- ✅ Per-stem tone budget of 5 dB total, scaled proportionally so shape survives.
- ✅ The browser receives the solve already inverted, so the monitor cannot drift from it.

---

### X0R-1118 · Read a card without opening it · 2 · `DONE`
**Acceptance criteria**
- ✅ Each instrument is a collapsed panel with a one-sentence plain-language summary:
  "Drums in Sleeping In could use less weight, more body, more mids and more presence."
- ✅ Apply-all and the auditions live on the header, so an instrument can be taken whole
  without being opened.
- ✅ A tick on the header shows which instruments have been acted on.
- ✅ All panels start closed.

---

### X0R-1119 · One wait, not two · 1 · `DONE`
**Acceptance criteria**
- ✅ The comparison runs inside the initial load, so arriving on the page costs nothing.
- ✅ The reference uploader on the mastering page is hidden when one was given up front.
- ✅ Starting an export stops whatever is playing.
- ✅ The name reads "extract0r studio" in the tab, the brand mark and the copy; "song"
  replaces "record" throughout.

---

### X0R-1121 · Pick a reference from music you own · 3 · `DONE`
**As a** user **I want** the tool to find me a reference **so that** I do not have to
guess which of my records makes a good target.

**Acceptance criteria**
- ✅ `GET /reference/library` reports whether a library is configured and where.
- ✅ `POST /reference/from-library` adopts a candidate, with the path resolved and checked
  to be inside the configured folder — traversal, absolute paths and symlinks all tested.
- ✅ Ranked candidates shown with the reason each is a target, and a one-click Use.
- ✅ Mirrors excluded: a file close in tone and no louder, wider or tighter is the same
  recording under another name. Pointed at a real folder it had been offering the song
  itself at "within 0.0 dB", plus three of extract0r's own exports of it.
- ✅ `LIBRARY_DIR` documented in `.env.example`.

**Why this and not a streaming picker.** Spotify and YouTube links are refused by name in
`app.services.fetch`, and the app's own terms are why. What makes a reference useful is
that its *audio* can be measured; a streaming link never offers that on terms this tool
will accept. Local music does, and can be explained rather than guessed at.

---

### X0R-1122 · Reference profiles · 5 · `DONE`
**As a** user **I want** to capture what a song teaches **so that** I can aim at it again
without keeping the audio.

**Acceptance criteria**
- ✅ A profile is a spectrum at 96 log-spaced points, side-to-mid per band, overall width,
  loudness and both peaks. About 3 KB. No audio and nothing reconstructable from it.
- ✅ It replaces the reference completely at the whole-mix stage: tonal curve, width
  match, level and headroom guard all read measurements and nothing else.
- ✅ Measured: a master from a profile matched the master from the audio to within 0.02 dB
  of applied gain, 0.01 LUFS of output, and 40.6 dB below signal on the waveform.
- ✅ Advice works from a profile too - `suggest` takes one in place of reference audio,
  so aiming at a profile gives findings and dial settings, not just a render.
- ✅ Per-instrument matching is refused with a reason, in the API and in the UI. It needs
  the reference's stems, and stems are audio.
- ✅ Curve resolution chosen by measurement: 96 points rebuild the matching curve within
  0.64 dB worst and 0.17 dB RMS, and more stops helping.
- ✅ Profiles live outside `storage_dir`, and the retention sweep now only deletes
  directories named like a track id rather than everything it finds.

**Why it is legitimate where a streaming rip is not.** Measurements of a recording are
facts about it - its loudness, its tonal balance, how wide it is - in the same family as
its tempo or its key. Ninety-six magnitudes with the phase discarded describes a song and
cannot become one.

---

### X0R-1125 · Per-instrument measurements in a profile · 3 · `PARTIAL`
**As a** user **I want** a saved profile to remember its instruments **so that** aiming at
it later costs one split instead of two.

**Built, tested, and not yet verified in a browser — X0R-1123 is that gate.**

X0R-1122 stored a profile's whole-mix measurements and refused per-instrument matching
outright, because that needs the reference's stems and stems are audio. That refusal was
one level too broad. The *comparison* does not read the reference's audio either; it reads
seven numbers per stem from it. A profile captured while the reference was separated can
carry those, and then a later song gets the full instrument-by-instrument screen from one
split rather than two.

**Acceptance criteria**
- ✅ `snapshot` / `from_snapshot` / `SNAPSHOT_FIELDS` in
  `app/services/mastering/instrument.py` round-trip exactly the fields `instrument.compare`
  reads from the reference side — no more, so the profile cannot drift from the comparison.
- ✅ A profile captured from an unseparated reference stays whole-mix-only, and both the
  save box and the picker row say which kind it is *before* the click.
- ✅ A profile saved before this change still drives the whole-mix match, and does not
  offer an instrument comparison it has no data for.
- ✅ Auditioning the reference side is absent rather than disabled, with the reason stated
  above the cards: a profile keeps the measurements, not the music.
- ❌ Verified in a browser. → X0R-1123

---

### X0R-1123 · Verify the unreviewed work in a browser · 2 · `TODO` *(sprint 1)*
**As the** developer **I want** the unreviewed work walked through in a browser **so that**
committing it is a decision rather than a hope.

About 1,080 lines across 15 files pass 759 tests and have never been opened in a browser by
anyone but their author. Five of those files are browser-facing. The riskiest changes are
conditional UI paths and a backward-compatibility path that unit tests structurally cannot
reach. Full criteria in [sprints/SPRINT-1.md](sprints/SPRINT-1.md).

**Acceptance criteria**
- The two profile kinds (with and without instruments) are distinguishable in the picker
  and announced before saving.
- An instrument-carrying profile reaches the comparison screen with no second split.
- A profile saved before the change still masters end to end and never shows an empty or
  broken comparison.
- The three-way spectrum panel draws three in-bounds named curves, both views switch, and
  the hover readout tracks.

**Out of scope.** A regression sweep of the rest of the app. The pytest segfault fix in
`demucs.py` — it has no user-visible surface and a clean suite exit is its verification.

---

### X0R-1124 · Hear one band, on both sides · 3 · `TODO` *(sprint 1)*
**As a** mixer **I want** to hear just the band a finding is about **so that** I can decide
whether the suggestion is real before I take it.

A tone finding names one of five bands. The audition plays the whole stem, so the band the
sentence is about is buried in everything else. Borrowed from Metric AB, whose filter bank
solos Sub / Bass / Low Mid / Mid / High on the mix *and* the reference at the same time —
the one feature the competitor survey turned up that this product clearly should have.

Cheap because the parts exist: five bands in `instrument`, per-side auditions from
X0R-1106, and each side already starting at its own busiest stretch from X0R-1116.

**Acceptance criteria**
- Band chips appear on an instrument's card only while that card is auditioning, and
  disappear when it stops.
- Selecting a band restricts playback to it within a second, without restarting from zero.
- The selection follows the audition across sides: picked on "yours", still applied on
  "theirs".
- "All" restores the full stem, and stopping clears the selection so nothing is silently
  filtered next time.
- Chips carry the same five band names the findings text uses, with the frequency range on
  hover.

**Out of scope.** Adjustable crossovers and filter slopes — Metric AB has both and they are
a mastering engineer's controls, not a "is this finding real" control. Band soloing at the
whole-mix stage or on the finished master.

---

### X0R-1108 · One page, four decisions, and a door · 5 · `TODO` *(sprint 1, re-scoped)*
**As a** user **I want** the mastering page to ask me four things **so that** I am not
reading nineteen sliders to find out that fifteen of them are optional.

**Re-scoped from "Basic and advanced modes" (3 pts).** The original card specified two
modes, and its own third criterion — "switching does not silently discard settings" —
exists because two modes are a trap. Progressive disclosure on one page delivers the same
outcome with no second rendering path and no state-loss bug to prevent. Re-sized to 5: it
touches `index.html`, `styles.css` and `app.js`, and must not desync the live monitor.

**Measured, in `apps/studio/wwwroot/index.html`:** between the comparison card and the
export button sit 19 labelled controls in one flat grid — 16 sliders, 5 dropdowns, 9
checkboxes, 17 buttons including 7 "Start from" presets. Every competitor surveyed puts
between 0 and 8 controls in front of the user and the rest behind one door; this page has
no door.

**Acceptance criteria**
- At most six interactive controls visible on a freshly loaded page: Start from
  (Suggested / Flat), Match strength, Vocal presence, Bitrate, Master.
- The other thirteen live in four named groups — Tone, Space and stereo, Dynamics and
  level, Export options — each closed on load and each carrying one line saying what it is
  for without being opened.
- Every one of the 19 controls appears in the default view or exactly one group. None
  missing, none duplicated, none changed in range, default, readout or tooltip.
- A group whose values have moved off default says so on its header.
- Which groups are open survives a reload.
- The live monitor still responds to a tone slider moved inside a group, with no re-render.
- A master exported with every group closed is byte-identical to one exported today at
  defaults.

**Out of scope.** No second mode and no separate code path. No change to any control's
range, default, wording or DSP. Control `id`s stay as they are — this card moves DOM and
adds disclosure, nothing more.

---

### X0R-1109 · On-screen help · 2 · `DONE`
**Acceptance criteria**
- ✅ Openable from the topbar on every screen, and from a link on the front page.
- ✅ A guided tour of eight scenes, captioned and self-advancing, with play/pause,
  step buttons and jump-to-step dots.
- ✅ Reference sections underneath covering the workflow, why suggestions are smaller
  than measurements, what the five tone bands are, the flagged rows, the limits of the
  preview, absent instruments, and the analysed-never-sampled guarantee.
- ✅ Drawn from the app's own CSS variables rather than recorded, so it follows the theme
  and cannot show an interface that no longer exists.
- ✅ Narration kept as text in `docs/WALKTHROUGH.md` so a voiceover could be recorded.
- ✅ Motion is additive: nothing is hidden behind an animation that might not run.
- ❌ Recorded audio narration. No text-to-speech is available here — see the note on
  X0R-1120.
- ❌ Reachable from the control it explains, not only from the topbar. Carried over from
  this card's first draft, which asked for a panel per control. The tour and the reference
  sections cover the *content*; what is still missing is help attached to the thing it is
  about. X0R-1108's group descriptions are the natural place for it.

---

### X0R-1120 · Narrated video walkthrough · 3 · `TODO`
**As a** new user **I want** to watch someone use this **so that** I can see it working
before I commit twenty minutes of splitting to it.

**Blocked on tooling, not design.** The captioned tour covers the same ground; what is
missing is audio and a real screen recording. Neither can be produced from this
environment: there is no text-to-speech and no screen capture. The script is written and
timed in `docs/WALKTHROUGH.md`, so the remaining work is recording rather than authoring.

**Acceptance criteria**
- A screen recording of a real session, from upload through export.
- Narration recorded over it, or generated from `docs/WALKTHROUGH.md`.
- Hosted rather than bundled, so the page weight does not grow.

---

### X0R-1110 · American spelling throughout · 1 · `TODO`
**Acceptance criteria**
- `colour`, `behaviour`, `centred`, `normalise`, `analysed`, `licence`, `metre` and their
  relatives converted, in code, comments, tests and UI copy.
- Identifiers renamed too, not only prose — `centre_bass_hz` is in the public API.
- A test or lint rule that keeps it that way.

---

### X0R-1111 · Audit what is no longer used · 2 · `TODO`
**Acceptance criteria**
- Candidates already noted: `matchering_engine`, the single-band `widen_above` now that
  per-band width matching exists, the ffmpeg path in `loudness.py`.
- Each one either deleted or given a comment saying what it is still for.

---

### X0R-1112 · Name the application "extract0r studio" · 1 · `TODO`
**Acceptance criteria**
- Consistent in the title, the brand mark, the About page and the export metadata.

---

### X0R-1318 · Compare instruments without being asked twice · 1 · `DONE`
**As a** person who ticked instrument-by-instrument on the first screen **I want** the
comparison already done when I arrive **so that** I am not asked for a decision I have
already made.

Reported directly: *"i want you to compare instruments automatically if i select it from
the first screen. i dont want to have to click the button again on the second page."*

**It is meant to work and it does not, for a one-line reason.** `upload()` computes

```js
const comparing =
  (state.referenceSeparated && !state.usingProfile) || ...
```

at `app.js:512`, and `state.referenceSeparated` is assigned in exactly one place —
`refreshPerStemState`, `app.js:1174` — which runs inside `afterReferenceUpload()` **ten
lines later**. So on the upload path the flag is still at its initial `false` when the
decision is made, the auto-run is skipped, and the user lands on a master page with an
un-pressed button.

The saved-profile path works, which is why this was not spotted: `state.profileHasInstruments`
is set in the use-profile branch, before `comparing` is read.

**Acceptance criteria**
- Upload a song and a reference with instrument-by-instrument ticked. On arrival at the
  master page the instrument cards are **already populated** — no button press, and the
  "Compare instruments" button reads "Compare again".
- The same is still true for a saved profile carrying instruments.
- A reference loaded *without* instrument-by-instrument still does **not** auto-compare:
  it costs a second separation the user declined.
- Loading a reference later, from the master page, behaves as it does today.
- The flag is read after it is written, or the ordering is removed as a thing to get
  right. A second `state` field that has to be set before another one is read is how this
  happened once.

---

### X0R-1127 · Decline to match a stem your own mix does not contain · 2 · `DONE` *(sprint 2)*
**As a** person whose song has no guitar **I want** the matcher to leave it alone **so that**
a reference's separation residue cannot become 9 dB of audible nothing in my master.

`stem_match.has_counterpart` asks only whether the *reference* contains the instrument.
There is no symmetric check on the source, so the case where **your** stem is empty and
theirs is residue goes straight through the level match.

Measured during pr0ducer Experiment 2, on a real pair. The source has no guitar (−59.73 LU,
`present=False`). *Bounce* has no guitar either — but its guitar stem is residue at −22.74
LU, which clears the −30 LU threshold, so `has_counterpart` returns true and every one of
six bounces carried `wanted +37.0 dB, capped at +9.0 dB` on a guitar that does not exist.

Inaudible in that instance because the stem sat at −50.7 LU even after the lift. The
mechanism is not bounded by that: a quiet *real* guitar against a reference's residue gets
an audible 9 dB lift of the wrong thing, and the louder the user's part, the louder the
mistake.

This is the same −30 LU threshold finding Experiment 1 made about *reporting*, appearing
in the *processing* path. `instrument.compare` already gets this right — it returns nothing
when `not mine.present or not theirs.present`. The two paths disagree.

**Acceptance criteria**
- `match_stem` declines when the source stem is absent, as it already does for the
  reference's, with a note saying which side was empty.
- The same threshold and the same rule as `instrument.compare`, named once rather than
  implemented twice.
- A test with an empty source stem and a residue reference stem asserting no gain is
  applied.

---

## EPIC-12 — What a mastering suite has that this does not (Phase 3)

Written after comparing the app feature by feature against iZotope Ozone, which is the
thing people reach for when they want this job done. The comparison is worth stating
carefully, because most of it does not go the way you would expect.

**Where this tool is already ahead.** Ozone's Master Rebalance guesses at vocal, bass and
drum levels inside a finished stereo file using source separation it does not expose. This
app separates properly, six ways, and lets each stem be measured, compared and moved on its
own — which is why the per-instrument comparison can exist at all. Ozone has no equivalent
of comparing *your snare* with *their snare*; its Match EQ works on the summed mix. Nor does
it have anything like reference profiles: a reference in Ozone is a file you must still
have. And the explanations are not a side feature — every suggestion here says what was
measured, what is being asked for, and why it is a fraction of the gap.

**Where the gap is real.** Ozone is twenty years of DSP, and the missing pieces below are
missing for good reasons — mostly that each one is a serious build. They are listed in the
order they would actually improve a master, not in the order Ozone lists them.

Two things deliberately *not* on this list. Codec preview (hearing what a streaming service's
AAC does to a master) is genuinely useful and out of reach without an encoder round-trip this
project does not have. Vintage-modelled EQ and compressor emulations are character effects,
and character is what a reference is for.

---

### X0R-1201 · Dither on export · 1 · `TODO` *(sprint 1)*
**As a** person exporting a master **I want** the quantisation noise shaped rather than
truncated **so that** fades and quiet passages do not gain a gritty edge.

The smallest real gap on this list and the least glamorous. Every float sample currently
becomes a 16-bit integer by truncation, which correlates the error with the signal — audible
as a crackle under anything quiet. TPDF dither with noise shaping is about thirty lines.

**Acceptance criteria**
- TPDF dither applied on the float-to-int conversion in `encode`, at the last stage.
- Optional noise shaping, default on, defeatable for anyone re-importing the file.
- A test measuring the noise floor of a dithered fade against a truncated one.
- Off for 32-bit float output, where it would be meaningless.

---

### X0R-1202 · True-peak limiting with lookahead · 3 · `TODO`
**As a** person whose master will be streamed **I want** peaks held under the ceiling after
codec conversion **so that** the encoder does not clip what the limiter let through.

The current limiter rides a one-pole envelope with no lookahead, and its own docstring
admits the consequence: "a few samples of a sharp attack can still poke through, which is
why the ceiling defaults below 0 dBFS rather than at it". A default of -1 dBFS is a
workaround for the missing lookahead, and it costs a decibel of loudness on every export.

Worse, the ceiling is enforced on *sample* peaks. Inter-sample peaks after lossy encoding
routinely run 1-2 dB higher, which is what `true_peak_db` already measures and the limiter
already ignores.

**Acceptance criteria**
- A lookahead delay of a few milliseconds so gain reduction begins before the transient.
- The ceiling enforced on the 4x-oversampled true peak, not the sample peak.
- Default ceiling raised to -0.3 dBFS once it can actually be held.
- A test driving a 0 dBFS square-edged transient and asserting the true peak of the result.

---

### X0R-1203 · Dynamic EQ, or resonance taming · 5 · `TODO`
**As a** person with one boomy note or one harsh cymbal **I want** it pulled down only when
it happens **so that** the rest of the song keeps its tone.

This is the single biggest *sonic* gap, and the reason is structural. Everything the tonal
match does is static: one curve for the whole song. A mix whose low E rings 6 dB hot for two
bars gets a permanent 6 dB cut at 82 Hz, which fixes those bars and hollows out every other
one. Ozone's Stabilizer and Spectral Shaper both exist for exactly this.

The measurement side is already here — `dynamics` computes dynamic range per band, and
`instrument` already reasons in five bands. What is missing is a per-band detector driving a
per-band gain, rather than a single number applied once.

**Acceptance criteria**
- A per-band detector with its own threshold, attack and release.
- Suggested from the measured *variance* of a band, not its average — a band that is
  consistently loud wants static EQ, and a band that is intermittently loud wants this.
- The distinction stated on screen, because offering both without explaining which is which
  is how a user ends up applying the wrong one.

---

### X0R-1204 · Multiband dynamics · 5 · `TODO`
**As a** person whose bass is squashing the whole mix **I want** compression applied per band
**so that** a loud kick stops ducking the vocal.

Compression here is broadband and per stem. That covers most of what a mix needs, and it
leaves out the thing a mastering compressor is for: a kick that pumps the top end because one
detector sees the whole spectrum. Related to X0R-1203 and worth building on the same per-band
detector rather than twice.

**Acceptance criteria**
- Crossovers at the existing five band edges, so this speaks the same language as the rest.
- Per-band threshold, ratio and make-up, with the dial being an outcome in dB as
  `dynamics.compress` already does rather than a ratio nobody can predict.
- Suggested from a comparison with the reference's per-band dynamic range, which is measured
  already and currently only reported.

---

### X0R-1205 · Metering worth the name · 3 · `TODO`
**As a** person deciding whether a master is finished **I want** to see what it is doing over
time **so that** I am not judging a four-minute song by four numbers.

Integrated LUFS, true peak and dynamic range are all measured and all shown as single figures
for the whole song. What is missing is everything time-varying: short-term and momentary
loudness, a loudness-range plot, and phase correlation — the last of which matters most,
because the width matching and the bass centring can both push a mix toward mono cancellation
and nothing currently warns about it.

**Acceptance criteria**
- Short-term (3 s) and momentary (400 ms) loudness over time, on the existing time axis
  beside the before/after envelopes.
- Phase correlation over time, with anything sustained below zero called out.
- A loudness-range figure computed the EBU way, distinct from the crest figure already shown.
- Reuses the peaks endpoint's caching, which already solves the "recompute on every load"
  problem this would otherwise have.

---

### X0R-1206 · Genre target curves · 3 · `TODO`
**As a** person without a reference to hand **I want** a sensible target for the kind of song
this is **so that** the tool is useful before I have found something to aim at.

Ozone's Tonal Balance Control ships target curves. This app has something better in kind — a
profile captured from a song you actually admire — and nothing at all when you have not made
one. A handful of built-in profiles would cover the gap, and the format already exists:
`ReferenceProfile` is the whole mechanism, so a genre target is a profile with no audio behind
it and a different provenance.

**Acceptance criteria**
- Built-in profiles shipped with the app, marked as targets rather than as captured songs.
- Derived from measurements that can be published, and honest in the UI about being averages
  rather than any particular record.
- Offered on the first screen beside saved profiles, clearly separated from them.

---

### X0R-1207 · Mid/side processing across the board · 3 · `TODO`
**As a** person with a wide mix **I want** to treat the middle and the sides differently
**so that** I can brighten the sides without brightening the vocal.

`to_mid_side` and `from_mid_side` exist in `dsp` and are used only by the width code. Every
EQ move in the app is applied to both channels equally. The classic mastering moves — cut the
bass out of the sides, lift the air only on the sides — are not expressible.

**Acceptance criteria**
- The tonal match and the polish stage both able to target mid, side or both.
- Per-band width already does the level half of this; this is the tone half, and the two
  should read as one idea rather than two controls in different places.

---
## EPIC-13 — pr0ducer (Phase 4)

Proposed in [proposals/PR0DUCER.md](proposals/PR0DUCER.md) and re-scoped there on 2026-10-02
after X0R-414 shipped. Two experiments were run before any card was written and both changed
the shape: [Experiment 1](proposals/EXPERIMENT-1-RESULTS.md) (the fingerprint, read cold)
cut stage 1 from 8 points to 5 and deleted its user-facing card;
[Experiment 2](proposals/EXPERIMENT-2-RESULTS.md) measured that **processing gets you tone,
never groove** — the drum layer moves the tonal gap to a reference by at most 0.09 dB and
places zero new grid positions.

**The epic's governing sentence, so no card in it drifts:** this is a *re-production*, not a
remix. Every move is a stated fraction of a stated measured gap, with the sentence that
produced it. The thing that literally does "remix the source in that style" is Suno's Cover
feature; it ships, it replaces your recording with a new one, and this is not it.

**Not in this epic, reasons on the proposal:** a genre label (§3 — genre has no acoustic
referent, and the precedent is this project's refusal to measure saturation), guitar or vocal
re-performance (§4 — synthesis cannot reach an amplified guitar), re-sequencing or tempo
change (§1(c) — measuring where the reference's kick sits is a measurement, moving the user's
kick there is composition), and shipping recorded samples (the licensing position in
`kit.py`).

| Stage | What | Pts | State |
|---|---|---|---|
| 0 | X0R-306, the benchmark | 5 | `TODO`, in EPIC-03. Gates stage 5 only. |
| 1 | The reference fingerprint | 5 | `TODO`, deferred twice. Conditional on X0R-1307/1308. |
| 2 | Genre as a hedge | 5 | `NON-GOAL`. Three documents running. |
| 3 | Re-produce: the processing half | 8 | `TODO`. X0R-1306 holds the measured headroom. |
| **3B** | **Compare drum to drum** | **11** | **sprint 2** |
| 4 | Re-perform: drums only | 6 | `TODO`. Ungated as of X0R-414, re-scoped. |
| 5 | Re-perform: bass only | 6 | `TODO`, gated on X0R-306 passing. |
| **6** | **Note-level comparison** (the Melodyne ask) | **15** | `TODO`. 5 of it buildable today; see below. |

**Stage 6 was added 2026-10-02**, on Ryan's request for *"comparisons with functionality from
melodyne"*. [PR0DUCER.md §10](proposals/PR0DUCER.md) carries the research and a probe of its
own. The short version: Melodyne's headline — DNA Direct Note Access — is patented, has no
open equivalent, and is **not needed**, because its required input is a single-instrument
recording, which separation already produces. What the ask is actually worth is the
*representation*: notes with a position, a pitch and a length. Of four candidate comparisons,
two are reachable now (**X0R-1320**, 3, and **X0R-1321**, 2), one is the most valuable card in
the epic and is blocked (**X0R-1322**, 5), and the blocker is a grid that the probe measured to
be wrong on both live-drummed records it tried (**X0R-1319**, 5). Note length, vibrato, key
agreement, polyphonic note comparison, pitch correction and quantising are all refused, with
reasons, in §10.5.

Sprint 2 is 13 points: this stage's 11 plus X0R-1127 (2), which belongs to EPIC-11 and is
pulled in because it is the presence rule stage 3B mirrors four ways.

Stage 3B is the sprint-2 work: [sprints/SPRINT-2.md](sprints/SPRINT-2.md) carries its three
design decisions (sub-drums are a nested level and **not** `StemKind` members; four
dimensions per drum rather than six; the profile carries them) and the full acceptance
criteria.

---

### X0R-1314 · Your kick against their kick · 5 · `DONE` *(sprint 2)*
**As a** person comparing my drums with a record's **I want** my kick measured against their
kick **so that** the advice is about an instrument rather than about a sum.

The drum bus is three instruments playing different things in different registers, averaged
into one number that describes none of them. "The reference's drums have 2.1 dB more weight"
cannot say whether the kick needs sub or the snare is too thin, which is the only form in
which the advice can be taken. X0R-414 returns kick, snare, cymbals and toms as audio, so
`instrument.compare` can go one level in — and that comparison is the thing this product is
uniquely good at. Ozone cannot compare your snare with their snare at all; this goes a level
below the snare.

**Sub-drums are a nested level inside the drums row, not `StemKind` members.** `StemKind` is
load-bearing in 21 modules under `app/`: the separation backends map a model's outputs onto
it, the transcription backends are chosen by it, `domain/tab/x0r.py` writes it into every
export, `StemSetting` is keyed by it. One consequence decides it on its own — `pipeline.run`
builds an `untouched` sum of *every* separated stem and `_apply_as_correction` subtracts it
from the original, so sub-drums as members would put the drums into that sum twice.

**Four dimensions, not six.** Level (relative to the drums stem, so it reads as balance
inside the kit), tone in the five existing bands with `QUIET_BAND_DB` refusing a lift into a
band the drum does not live in, dynamics, and punch — crest is the most diagnostic figure on
a kick, click against thud, and it is precisely what a bus comparison destroys by averaging.
**Pan and width are offered on cymbals and toms only.** `NEVER_MOVE_SIDEWAYS` exists because
a bass belongs in the middle; a kick and a snare belong there for the same reason, and
`MIN_MEANINGFUL_WIDTH` already refuses a ratio between two near-mono stems.

**Presence is a criterion, not an afterthought.** A record with no toms still yields a toms
stem: 24 tom strokes in 28 seconds were measured on a programmed electro-house record, which
is residue. A sub-drum is called present on its energy relative to the drums stem — the same
rule `ABSENT_BELOW_LU` applies against the mix — and **never on a stroke count**, because
`separate.QUIET_STROKE_DB` has no knee on the snare, whose counts run from 4 to 45 across the
gate's range.

**Acceptance criteria** (full text in the sprint plan; all checkable in a browser, and none
of them asks QA to listen)
- The Drums card shows a closed, named expander saying how many drums were measured.
- Opening it reveals four sub-rows with their own findings and dials, or a stated reason for
  having none; the drums stem's own findings stay unchanged above them.
- Every number on a sub-row matches the comparison job's JSON for that sub-drum.
- No pan or width row on kick or snare, under any pair.
- A sub-drum absent on either side names which side and offers no dials.
- "▶ yours" and "▶ theirs" play that drum alone; the X0R-1124 band chips apply to it.
- Every finding carries the bleed caveat with its own figure.
- Without the weights the Drums card behaves exactly as it does today.
- A profile captured from a per-drum-separated reference contains the four sub-drums'
  measurements.

---

### X0R-1315 · Take a per-drum suggestion · 3 · `DONE` *(sprint 2)*
**As a** person who agrees with a per-drum finding **I want** to take it **so that** the
comparison is advice rather than trivia.

Moving the kick inside a summed drums stem means the four sub-stems plus the residual that
separation left behind: apply each sub-drum's accepted move to its own sub-stem with the
existing `StemShape`, re-sum with the residual, and hand the result to the pipeline as the
drums stem. The same "apply the change, not the sum" approach `_apply_as_correction` uses for
the six-way split, one level further in.

**Acceptance criteria**
- The master report names the sub-drum a move was made on and the dB applied.
- The export differs in the drums from one with that dial at zero, and the other three
  sub-drums measure unchanged in a fresh comparison of the export.
- **A master with every per-drum dial at zero is identical to one exported with per-drum
  off.** Reconstruction must not change the drums when nothing was asked for. Not negotiable.
- Per-drum dials clamped by the same limits the stem dials are.
- A sub-drum called absent has no dial at all, rather than a dial at zero.
- The live monitor responds to a per-drum dial, or the card says the dial is render-only.
  Silently doing nothing is not acceptable.

---

### X0R-1317 · A profile remembers their kick · 2 · `DONE` *(sprint 2)*
**As a** person who keeps coming back to one reference **I want** its drums measured once
**so that** I do not pay a second separation every time I aim a song at it.

The reference side of a per-drum comparison costs a DrumSep pass — about half the audio's
length again on CPU. `snapshot` / `from_snapshot` / `SNAPSHOT_FIELDS` is the mechanism that
already avoids this for stems, and X0R-1125 is the card that did it. This is the same card
one level in. X0R-1314 puts the sub-drums into the snapshot *format*; this one is the capture
and reuse flow, so that dropping it costs the convenience and not the format.

**Acceptance criteria**
- The save box states, before the click, whether per-drum measurements will be included, and
  how to change it when they will not.
- A profile holding them says so in its picker row, distinct from "N instruments" and from
  "whole mix only".
- A fresh song aimed at such a profile reaches the per-drum comparison with **no** separation
  of the reference, and all four sub-rows show findings and dials.
- "▶ theirs" is absent on the sub-rows — not present-and-disabled — with one line saying a
  profile keeps measurements, not music. Same rule the stem rows already follow.
- A profile saved before this change still drives the whole-mix and per-stem comparison, and
  the per-drum expander is absent or refused with a reason. Never empty, never broken.

---

### X0R-1316 · The drum panel says which drums it found · 1 · `DONE` *(sprint 2)*
**As a** person laying a kit over my drums **I want** to know which mechanism ran and what it
cannot do **so that** I am not waiting for the groove to change.

X0R-414 shipped behind `DRUMSEP_ENABLED` with no surface at all. The panel still says the kit
"finds each kick, snare and hi-hat in the drum stem", which is one sentence describing two
mechanisms with different failure modes — separation where the weights are present, the
band-rise classifier where they are not.

**And a defect against X0R-414, recorded here rather than as its own card.** The hi-hat
checkbox is dead on the separated path: `kit.DRUMS` is `("kick", "snare", "hihat")`,
`separate.STEM_NAMES` produces `cymbals`, and `kit.layer` renders only names present in both.
A user who ticks hi-hat with per-drum separation on gets silence, and the 56 cymbal and 24 tom
strokes found per 28 seconds are all discarded. The fix belongs with this card because the
honest label and the working box are the same question.

**Acceptance criteria**
- The panel says which route it took on this machine and what that changes.
- When per-drum separation is unavailable it says what is missing, in the words
  `separate.why_unavailable` already produces.
- The hi-hat box is honestly labelled for what the cymbals stem contains, or disabled with the
  reason. A ticked box producing no sound is a defect against this criterion.
- The panel states that laying a kit reinforces the strokes already there and moves none of
  them, with the measured figure behind it.

---

### X0R-1301 · Rhythmic fingerprint of a reference · 3 · `TODO`
Kick, snare and hat times placed against a beat grid re-derived from the drums. Counts and
percentages, never adjectives. Prototyped in `app/services/analysis/fingerprint.py`
(`grid_from_drums`, `refine_grid`) during Experiment 1 and wired to nothing.

**Two constraints the proposal did not carry, both found by experiment.** The grid must be
re-derived from the kicks and snares rather than the mix — `choose_tempo` on the whole mix
returned 64.6 BPM against a true 128.9, and the documented tie-break is why. And any figure
compared *between* two files must be read against **one** grid: six bounces of the same audio
re-estimated six different tempos at confidences of 0.60–0.67. Drop "snare on N of M
backbeats" from the card text until the snare detector earns it — a snare claimed on 73% of
all beats is cross-triggering.

**Blocked on X0R-1319 as of 2026-10-02.** The Melodyne probe took the grid work prototyped
here to two live-drummed records and it failed on both: 66.30 BPM against ~132.7, metre 3/4
on a 4/4 record, and a flat kick histogram at every octave. Experiment 1's octave fix works
because a halved four-on-the-floor grid has empty beats; a rock backbeat fills them. Every
rhythmic figure in this card is downstream of that. See
[PR0DUCER.md §10.4(a)](proposals/PR0DUCER.md).

---

### X0R-1302 · Instrumentation census · 1 · `TODO`
Which of the six stems carry real content, in dB relative to the mix, with the threshold
stated and the residue caveat written on the card. The −30 LU threshold is right for its job
in `instrument.py` ("do not match to residue") and wrong for the census's job ("say what is
on the record"): it called guitar present on a record with no guitar.

**The programmed-versus-played half is cut.** It cannot be measured honestly — the detector
contributes 1–7 ms to a figure whose whole signal is a few milliseconds, and the ranking of
two records reversed when the timestamps were fixed. Shipping it would be the X0R-407 failure
the proposal cites as the house precedent.

---

### X0R-1303 · The fingerprint card · ~~2~~ 0 · `NON-GOAL`
Cut by Experiment 1. Read cold, the card is four lines of things you already knew plus one
line that is wrong. The two figures that carried information — hat placement, and whether the
bass plays through the kick — are *inputs to processing*, not reading material.

---

### X0R-1304 · The fingerprint travels in a reference profile · 1 · `TODO`
Extend `ReferenceProfile`. All scalars, so `profile.py`'s "a profile contains no audio and
cannot be played" argument is untouched.

---

### X0R-1305 · Three guesses and a score · 5 · `NON-GOAL`
A genre classifier. Feasible on the `onnxruntime` already installed, and feasibility is not
the question: genre is a social and commercial category, not an acoustic property, and
"Electronic / House, 0.82" is a well-calibrated statement about a Discogs field that a user
will read as a measurement of their audio. The same call this project already made about
saturation, and genre is the weaker case. Neither experiment wanted a label, and the two
figures that carried information are both ones a label would have obscured.

---

### X0R-1306 · A strength budget instead of a constant · 3 · `DONE`
`CLOSE_FRACTION`, `MAX_LEVEL_DB`, `MAX_BAND_DB` and `WIDTH_LIMITS` become one user-set
budget; today's values are the default and labelled *nudge*, and each wider notch says in dB
what it permits. `LIKELY_ARRANGEMENT_DB` stays a flag at every setting.

**It must be the clamps, not `match_strength`.** Experiment 2 measured both: the whole
`match_strength` sweep from 0.4 to 1.0 buys 0.56 dB of mean spectral distance against this
project's own 1.2 dB threshold for a meaningful gap, because `strength` scales an
already-clamped curve and is clipped at 1.0. Doubling the clamps buys 1.07 dB more, removing
them 2.15 dB. A budget slider wired to `match_strength` would ship a control that cannot do
anything, and it is the obvious way to build this card wrong.

---

**Shipped 2026-10-05 as `app/services/mastering/budget.py`**, with two notches rather than
a slider, and three departures from the card above - each one measured rather than argued.

**It ships with two notches because a third was built and measured at nothing.** Rendered
end to end on the Experiment 2 pair, against an unmastered distance of 5.73 dB:

| notch | scale | mean distance | closed |
|---|---:|---:|---:|
| Nudge (default) | ×1 | 4.14 dB | 27.7% |
| Further | ×2 | 3.63 dB | 36.6% |
| *a ×3 notch, removed* | *×3* | *3.57 dB* | *37.6%* |

The third is worth **0.06 dB** over the second. Asking the curve why: at ×2 the correction
sits exactly on the tilt cap, 12.00 dB against a cap of 12. At ×3 it sits at 13.25 against a
cap of 18 - so the cap has stopped being what holds it. **The deep-bass guard is.** Lifting
that guard from 1 dB to 6 takes the low-end cut from −4.96 to −6.00 dB, which is the move
that produced "super hollow with no bass" and the reason the guard is 1 dB. A notch past
Further is a control that measurably does nothing unless it also re-opens a fixed complaint,
which is this card's own failure mode. It stops at two.

**`CLOSE_FRACTION` and `NUDGE_SHARE` are deliberately not in the budget**, though the card
names the first. Ceilings scale; the share of the gap does not. `_nudge` is
`clip(gap * share, -limit, +limit)`, so raising the limit lets a *large* difference move
further and leaves a small one exactly where it was - while scaling the share would turn a
nudge into a match at the top notch, which the governing idea forbids. The property is
tested: on an 11 dB level gap, Nudge offers 3.0 dB (clamped) and Further offers 5.5 - half
the gap, and no higher ceiling can take it past that.

**What 0.51 dB is and is not.** It is the whole-mix match, which is all a render measures
when nobody has taken a suggestion. It is under the 1.2 dB threshold, and that is stated on
the control rather than hidden. Most of what the budget buys is in the per-instrument
suggestions, where the ceilings also double: a large gap can move 6 dB instead of 3, and
5 dB of tone instead of 2.5 - well past the threshold, but only for somebody who presses
Apply. Both comparison routes take the budget, so the suggestions are drawn at the chosen
notch and re-run when it changes.

`match_strength` is **left in place**, beside the new control, with a line saying which of
the two actually moves anything. Removing a control a user may be relying on is a separate
decision.

### The budget reaches the vocal guard, and that guard has its own ceiling

Found by rendering a real 3-minute song at both notches, identical settings, and reading
the progress log:

    nudge:   restoring 1.3 dB of vocal range · vocal lifted +1.9 dB to sit at -4.5 LU
    further: restoring 3.4 dB of vocal range · vocal lifted +1.5 dB to sit at -4.5 LU

**This is designed behaviour, not a side effect**, and the first explanation of it was
wrong. It is not that a wider budget changes the vocal's measured dynamic range. The
compensation curve *is the match's own cut inverted* - `vocals.match_compensation_curve`
hands the vocal back exactly what the match took out of 150 Hz to 4 kHz, band by band. The
budget scales the match curve, so the give-back scales with it automatically. A deeper cut
needing a bigger give-back is correct.

**What is worth watching is the ceiling it is heading for.** `MAX_VOCAL_COMPENSATION_DB`
is **4.0**, and Further reached **3.4 on a real song - 85% of it**. The budget does not
scale that cap and nothing says it should: it exists because "past a few decibels the
honest answer is that the two mixes disagree rather than that the vocal needs help."

So at a wide budget on a reference much darker than the source, the match keeps cutting and
the give-back stops, and the vocal thins out - which is the exact failure
`match_compensation_curve` was written to prevent. Nobody has hit it yet; Further on one
real pair came within 0.6 dB.

Two consequences, both for whoever touches this next:

- **A third reason the ×3 notch was right to remove.** It would have pushed the
  compensation into the cap on ordinary material, and the symptom - a thin vocal at the
  widest setting - would have read as the budget being bad rather than as two ceilings
  disagreeing.
- **If a wider notch is ever wanted, `MAX_VOCAL_COMPENSATION_DB` has to be part of the
  conversation**, and the question is a product one rather than a number: at what point
  does "the reference is darker than you" stop being something to correct for.

---

### X0R-1307 · Suggestions the fingerprint makes possible · 2 · `TODO`
Observations the app cannot currently make because it never looked: the reference's offbeat
hats sit 19 ms ahead of the beat midpoint and yours sit 7 ms behind; the reference's bass is
ducked to its kick and yours is written in the gaps. In the existing card form, each with its
measurement attached.

It gains a reason from Experiment 2: these figures are now *proven* to be ones no control in
the pipeline can act on, so reporting them is the only honest thing available. The card
should say that rather than implying a dial is coming.

---

### X0R-1308 · Sidechain duck from the measured kick · 3 · `TODO`
The most genre-defining process the app lacks, and measurable: kick times, with depth and
recovery from comparing the reference's bass envelope around its own kicks against the
source's — against a control measurement at kick-free grid positions, without which the
figure is mostly note envelope.

**Design the abstention in as the common path.** The figure abstained on one of two tracks in
Experiment 1 and on six of seven files in Experiment 2, because the per-kick dips varied by 8
to 18 dB, more than one compressor would produce. X0R-414 gives it cleaner kick times, which
is not why it abstained, so this is improved and not fixed.

---

### X0R-1309 · Kits chosen by fingerprint, not by dropdown · 2 · `TODO`
Picks one of the three kits and sets `drum_blend` from the reference's measured drum
character — decay length, transient sharpness, sub energy — and says in a sentence why. The
dropdown stays. Needs stage 1. Ungated as of X0R-414 and still not worth leading with: its
ceiling is one of three synthesised kits, and the measured move is ~0.09 dB.

---

### X0R-1310 · A tom voice · 2 · `TODO`
Re-scoped from "More voices, same synthesis · 3" on 2026-10-02. One `Voice`: toms, tuned
against measurements the way the three existing ones were. A tom is a pitched membrane, the
same family as the kick, and where synthesis is in its element.

**Ride, crash, clap and rimshot are retracted.** DrumSep returns a single `cymbals` stem
holding hats, rides and crashes together, so they cannot be voiced apart — the model that
splits hi-hat out is LarsNet, rejected on its CC BY-NC weights and its synthesised training
set (X0R-414). And a 35–130 ms filtered noise burst is a credible closed hat and not a
credible crash: shipping one would be this epic's version of the synthesised guitar the
proposal refuses to ship.

**Parked behind X0R-1314's sub-drum presence test.** 24 tom strokes were measured in 28
seconds on a record that has no toms. Built first, a tom voice puts synthesised toms on
records that have none.

---

**Started 2026-10-05 and stopped, because the gate this card relies on does not hold.**
X0R-1314's presence test shipped, which was supposed to unblock this. It does not:

- On the Experiment 2 reference, the separated **toms stem sits 4.7 LU under the kit**. The
  presence threshold is 30 LU, so the gate passes it by twenty-five decibels.
- It is not toms. 79% of its onsets land within 30 ms of a kick (100% of 37 on the source
  side), its strongest partial is at 80 Hz, and its waveform correlation with the kick is
  +0.08 - so it is not literally the kick either. It is loud separation residue that fires
  when other drums do.
- **So a tom voice built now does exactly what this card was parked to prevent, despite the
  gate.** The presence test was designed for digital residue at −40 LU; this is residue at
  −5.

**A replacement gate was proposed and also measured as dead.** The idea: a real drum
sometimes plays *alone*, while residue only exists when something else is loud. Measured as
the share of a drum's own strokes with no other drum within 30 ms, across all four as
controls:

| | kick | snare | cymbals | toms |
|---|---:|---:|---:|---:|
| reference | 41% | 4% | 42% | **1%** |
| source | **0%** | 5% | 58% | **0%** |

The source's *kick* is 0% independent, because a four-on-the-floor never plays without a
hat. The test rejects the kick. It measures density, not reality.

**And the voice cannot be tuned anyway.** The three existing voices were tuned against
measured band energies from real drums; there are no real toms on this machine, which is
the same finding from the other side.

All three roads end at the same place: **record a kit with kick, snare and overheads on
separate tracks** - item 3 of X0R-306's recording list. That gives the tuning material, a
real example of what a tom stem looks like against a residue one, and the data to design a
gate that works. Until then this card is blocked on audio, not on code.

---

### X0R-1311 · Pattern observation, never pattern replacement · 2 · `TODO`
Report the grid positions where the reference's kick lands and the source's does not, and
offer to *add* a synthesised hit there — low blend, opt-in per position, count shown.

**Buildable as of X0R-414**, where it was not before: the kick returns 60 strokes at every
gate from −6 to −30 dB, so the count is solid. Deliberately still out of sprint 2. It is the
only card in this epic that places a drum where the user did not play one, and it needs both
files read against **one** grid or it measures the ruler rather than the music. Adding a
measured hit the user accepts one at a time is a nudge; doing it in bulk is composing his
song for him, and that is stage (c), which is out.

---

### X0R-1312 · A synth bass patch set · 3 · `TODO` *(gated on X0R-306)*
Three patches in the `Voice` idiom — oscillator choice, filter envelope, glide — tuned against
measured spectra of real bass parts the way the kicks were.

---

### X0R-1313 · Layer a synth bass under the transcribed line · 3 · `TODO` *(gated on X0R-306 passing)*
Layered, never replacing, with level from the stem's own envelope so dynamics survive, and
muted wherever pYIN's note confidence is below threshold — an uncertain passage gets the
original bass alone rather than a confident wrong note.

**Carries its own kill criterion:** if X0R-306 reports worse than 95% note accuracy or any
octave error on clean DI bass, this card is not built. A wrong EQ move is a slightly wrong EQ
move; a synth note at the wrong pitch is a wrong note, and no patch design rescues one.


---

### X0R-1319 · A grid that survives a live drummer · 5 · `PARTIAL` · **affects shipped tab**
**As a** person comparing my band's record with someone else's **I want** the bar lines to be
in the right place on both **so that** a timing figure is about the playing and not about the
ruler.

Added 2026-10-02 from the Melodyne probe in [PR0DUCER.md §10.4(a)](proposals/PR0DUCER.md),
then **re-scoped the same day on a shipped-feature finding the probe did not look for.**

**This is not only a pr0ducer prerequisite. It is a live defect in transcription.**
`ascii_tab.py:59` and `drum_tab.py:59` both place every column with
`quantize(start_s - first_beat_s, tempo_bpm, division)`. A wrong tempo does not degrade a
tab, it rewrites it — every note lands in the wrong column, and at a halved tempo the bar
lines fall in the wrong place as well.

Verified independently of the probe, on the shipped path, same 28 s window:

**Correction, 2026-10-03.** The probe reported Special When Lit's true tempo as ~132.7
and concluded the error was 3:2 rather than an octave. **That ground truth does not
hold.** Three independent estimators — onset-envelope autocorrelation,
`librosa.feature.tempo`, and `beat_track` — agree on ~99.4 for that record once folded
into one octave. There is no 3:2 error, `octave_variants` *does* contain the right
answer, and a 4/3 factor would have been chasing a bug that does not exist. Both failures
are octave errors, in opposite directions:

| track | truth (3 estimators agree) | returned | confidence |
|---|---|---|---|
| MSTRKRFT *Bounce* (programmed) | 129.2 | **64.60** — halved | 0.576 |
| Special When Lit (live) | 99.4 | **198.77** — doubled | 0.570 |
| blink-182 *Edging* (live) | 147.7 | 147.66 ✅ | 0.611 |

**The confidence is 0.57–0.61 on all three**, so it does not separate a right answer from
a wrong one and nothing downstream can gate on it.

**What is fixed (2026-10-03): the halving.** `score_tempo`'s tolerance was a fraction of
the beat period, so a halved grid caught anything within 139 ms where the true one caught
70 — the wrong grid was scored on an easier test. `MAX_TOLERANCE_S = 0.060` caps it, and
`best_offset` uses the same cap so the offset search and the scorer agree. MSTRKRFT now
returns **129.20**; blink is unchanged at 147.66; 43 timing tests pass, and the four new
ones fail with the cap removed.

**What is not fixed: the doubling.** Special When Lit still returns 198.77 against a
truth of 99.4. The cap cannot help — it removes a bias toward *slower* grids, and this is
the opposite error. Recall is supposed to punish a doubled grid for the empty beats it
invents, and on dense material there are none: 196 onsets in 28 seconds is about two per
beat even at the doubled tempo, so every beat is occupied either way.

Strength-weighting the score was tried — a beat is where the *accented* events land, so
at double tempo half the beats should catch only weak onsets. It did not separate them
and it made MSTRKRFT worse. **Abandoned deliberately rather than tuned**: three
recordings is not enough to fit a scoring function against, and the next step would have
been overfitting. Octave ambiguity on dense material is a known-hard problem in the
literature, and what it needs is X0R-306's eval set, not another guess.

**So the honest state is one of two octave failures fixed**, and the remaining one
measured, named, and reproducible. A user transcribing a dense live record can still get
a doubled grid.

It is a prerequisite as well: **X0R-1301, X0R-1307, X0R-1311 and X0R-1322 all read a
grid, and on live-drummed material the grid is wrong in three different ways at once.**
Measured on two live records and one programmed control, 28 s each:

| | shipped grid | actual | grid conf | kick histogram |
|---|---|---|---|---|
| programmed electro | 128.91 BPM, 4/4 | 128.9 | 0.881 | `13 0 0 0 · 12 0 0 0 · 15 0 0 0 · 12 0 0 0` |
| live rock A | **66.30 BPM** | ~132.7 | 0.486 | `3 6 7 4 · 7 4 4 6 · 5 4 3 0 · 6 5 5 4` |
| live rock B | **147.58 BPM, 3/4** | ~147.3, 4/4 | 0.546 | twelve steps, unreadable |

1. **The octave.** Experiment 1's fix — run `choose_tempo` on the kicks and snares rather
   than the whole mix — works because a halved four-on-the-floor grid has empty beats that
   recall punishes. A rock backbeat fills every beat of the halved grid too, so the fix does
   not generalise and the shipped path returns half time at a confidence that clears
   `MIN_GRID_CONFIDENCE`.
2. **The metre.** 3/4 on a 4/4 record. X0R-407 made metre return zero *confidence* without
   an accent; it still returns a number, and every histogram is indexed by it.
3. **The drift, which is the part no octave fix reaches.** Fitting the drum anchors to each
   half of the clip separately: 0.00 BPM of drift on the programmed record, 0.61 and 0.97
   BPM on the live ones — and the median distance of a drum hit from its own best-fit
   sixteenth is **5.7 ms programmed against 23.3 and 30.5 ms live**, on steps of about
   110 ms. Musically meaningful microtiming is 5–50 ms, so on a live record the grid's own
   residual is the same size as the thing a groove card would report.

**Acceptance criteria**
- A tempo per bar, not per clip — a tempo map — fitted to the drum anchors, with the
  per-bar figure available to anything that reads a grid.
- On a record whose tempo drifts, the median distance of a kick or snare from its nearest
  sixteenth drops to the programmed record's order of magnitude, and the figure is reported
  so the improvement is visible rather than asserted.
- The octave decision is re-checked on material with a drum on every beat, and a reading it
  cannot resolve comes back at **zero** confidence rather than at 0.486 — the X0R-407 rule,
  applied to tempo.
- Metre either resolves or abstains; a histogram is never rendered against an unresolved
  metre.
- A clip the grid cannot lock is said so plainly, and every figure downstream abstains
  rather than being computed against it.
- Tested against at least one live-drummed and one programmed record, with the before and
  after numbers written down.

**Out of scope.** Tempo *editing* by the user. Any timing comparison — that is X0R-1322.
Beat tracking replaced wholesale with a different library; the failure here is in the
choosing and the fitting, not in librosa's onset envelope.

---

### X0R-1320 · Is their vocal tuned, and to what · 3 · `DONE`
**As a** person comparing my vocal with a record's **I want** to know whether that record
was pitch-corrected **so that** I stop trying to reach a sound that came from an editor.

Added 2026-10-02 from [PR0DUCER.md §10.4(c)](proposals/PR0DUCER.md), and it is the most
reachable Melodyne-shaped comparison available: it reads pYIN's **frame-level f0 contour,
not notes**, so it needs no note segmentation, no note offsets, no onset detector and **no
grid**. Measured on three records at 2-cent resolution, after removing each record's own
tuning reference:

| | A4 of the record | median \|cents\| from its own tuning | IQR |
|---|---|---|---|
| modern major-label rock vocal | 439.8 Hz | **4.0** | 8.0 |
| indie rock vocal | 444.9 Hz (+19 cents) | **14.0** | 26.0 |
| rapped vocal | 442.4 Hz | 26.0 | 51.5 |

2,900–4,300 voiced frames per 28 s, and the ordering is stable across a fivefold change of
analysis resolution. **Removing the record's own tuning reference is part of the measurement,
not a refinement** — these three records are tuned to three different A4s, and without that
step a record tuned sharp reads as a singer who is sharp.

**Acceptance criteria**
- Both sides' pitched stems report a **tuning reference** — the record's own A4 in Hz, and
  the cents it sits from 440 — with the frame count it came from.
- Both sides report the spread around that reference: median and a high percentile of
  absolute cents, with the sample size, in the existing finding form.
- The finding is an **observation with no dial**. There is no control that acts on it, and
  the card says so rather than implying one is coming — the X0R-1307 rule.
- **It abstains on a vocal that is not sung.** A rapped or spoken vocal is not out of tune;
  the gate and its threshold are stated on screen.
- The wording is "how close to the grid this vocal sits", never "how well this person sings".
  Vibrato and portamento inflate the figure and cannot be separated out — the probe's
  §10.4(e) finding is that vibrato cannot be measured at all here — so the caveat ships on
  the finding.
- The figure is presented as an **upper bound**: separation artefacts add spread rather than
  remove it, so *theirs is tighter than yours* is supported where *yours is 14 cents out* is
  not.
- The cost is stated before the run: about 5 s per pitched stem per side at the default
  resolution, about 30 s at the 2-cent resolution the figures above used.

**Out of scope.** Any correction, tuning or retuning of anything — see the refusals in
§10.5; this is the card whose obvious sequel is off-brief. Vibrato (§10.4(e)). Per-note
pitch; this is a contour measurement. Guitar, piano or `other` — polyphonic, and refused
until X0R-306.

**Not gated on X0R-306 to build.** It inherits pYIN's pitch accuracy and none of its note
segmentation. X0R-306 is what would let the card state a confidence instead of a caveat.

---

**Shipped 2026-10-05 as `mastering/tuning.py`, and the card's own method does not work.**

The card quotes its figures "@2c" and budgets 30 s a stem for it. Running pYIN at
`resolution=0.02` **destroys its voicing decision**: two real vocal stems come back 39% and
38% voiced at the default resolution and **3.2% and 0.2%** at 0.02. Finer bins spread the
observation probability thinner and the HMM's unvoiced state wins. The first build reported
77 and 6 voiced frames on loud vocals sitting 5 dB under their own mix, and would have
abstained on every record for entirely the wrong reason.

Voicing therefore comes from pYIN at its **default** resolution, where it is robust, and the
pitch from `librosa.yin`, which interpolates and returns a continuous f0 - 919 distinct
values against pYIN's 165 on the same frames. It is also **four times faster**: about 5 s a
stem for both passes, against the 30 the card budgeted for one that did not work.
Cross-checked against the probe, which measured a rapped vocal at 26.0 cents: this route
gives **24.4** on the same recording, by a different estimator.

**The sung/not-sung gate is R, the resultant length of the circular mean** over
cents-modulo-a-semitone - 1 when every frame sits on one point of the semitone, 0 when they
spread evenly, which is what speech looks like. Measured: a rapped vocal **0.027**, an
electro vocal **0.130**, a synthesised line 15 cents loose **0.672**, one dead on pitch
**0.911**. It earns its place twice, because it is also the confidence in the tuning
reference: at R = 0.027 the estimated A4 came back 36 cents sharp and meaningless, since a
circular mean over a uniform distribution points nowhere.

**The threshold moved once and there is a grey zone.** It was 0.35 until a singer
scattering 22 cents measured 0.26 and was told it was a rap - the card's named harm pointed
the other way. 0.25 clears both measured raps with margin, and corresponds to about 26 cents
of scatter, which is exactly where the probe's rap sat. **A vocal between roughly 20 and 30
cents could be a loose singer or a melodic rap and nothing here separates them.** X0R-306's
eval set is what would.

A `SAME_CENTS = 3.0` threshold was missing from the first build and showed up as a track
compared against *itself* reporting that the reference's vocal sat further from the grid
than its own, by zero cents. Every other dimension had one.

**The profile route cannot carry either observation**, because both read audio a second
time - a pitch contour and an onset list - and a profile has no audio. Advice that can be
*taken* is still identical from either side; the two rows that cannot be taken are absent
from the profile route. Noted here rather than hidden, and the natural home for fixing it
is X0R-1317's snapshot.

---

### X0R-1321 · How much space their parts leave · 2 · `DONE`
**As a** person comparing arrangements **I want** to know how often each part plays **so
that** "their mix sounds less busy" becomes a number.

Added 2026-10-02 from [PR0DUCER.md §10.4(d)](proposals/PR0DUCER.md). Median inter-onset
interval per stem, both sides. Measured on bass: **186 ms** on one record, 302 on another,
441 on a third — "their bass plays twice as often as yours" is an observation about
arrangement density that this app has never been able to make.

**Why the interval and not the note.** It needs **no grid**, so none of X0R-1319 applies to
it, and it is robust to the error that wrecks absolute placement: the onset detector's
`backtrack` shift is 15–31 ms on a pitched stem (§10.4(b)) and **cancels in the difference
between consecutive onsets**.

**Acceptance criteria**
- Median inter-onset interval per stem, both sides, with the onset count it came from.
- Onsets per bar as well, where the grid is usable, abstaining where it is not — this
  overlaps X0R-1302's census, which is prototyped in `analysis/fingerprint.py` as
  `_onsets_per_bar`; whichever lands second reuses the first rather than computing it twice.
- Observation only, no dial.
- Absent stems abstain rather than reporting the onset count of separation residue — the
  X0R-1127 rule.

---

**Shipped 2026-10-05 as `mastering/density.py`.** Both observations render as findings with
an empty `control`, which is the shape `punch` already uses, so the page needed no change
and there is one way a finding looks.

One thing the probe did not say, found by a test fixture rather than by music: **an abrupt
amplitude discontinuity is an onset, and the detector is right to call it one.** A test
click truncated at 13% of full scale produced two detections 58 ms apart, every click train
reported a 58 ms median whatever its real spacing, and five tests failed pointing at the
metric. The metric was fine. With the discontinuity removed a 250 ms train reads 255 ms and
a 450 ms train reads 453. It matters outside the test too: a chopped or gated sample really
does contain that extra event, and this measurement counts it.

**Out of scope.** **Note length, legato and staccato are refused**, not deferred. Measured
legato ratios came back at exactly 1.000 on one record (a ceiling artefact of abutting
notes), 0.946 with an IQR of 0.158 on another, and 0.757 with an **IQR of 0.592** on a
third, where the spread is wider than the whole difference between legato and staccato. Note
offsets are the least reliable quantity in transcription, which is why the field reports
F-measure and F-measure-no-offset separately. Note *counts* are also out: they depend on
segmentation thresholds nobody has benchmarked, and the median interval does not.

---

### X0R-1322 · Note timing against the grid, yours against theirs · 5 · `TODO` *(blocked on X0R-1319 and X0R-412)*
**As a** person who can hear that a record feels tighter than mine **I want** the difference
in milliseconds **so that** I know whether it is the playing or the production.

Added 2026-10-02 from [PR0DUCER.md §10.4(a)](proposals/PR0DUCER.md). **This is the most
valuable card in EPIC-13 and it is not buildable yet.** Experiment 2 measured that
processing gets you tone and never groove, so note-level timing is the only route to the
half of "sounds like that record" the product cannot currently touch. Melodyne's whole
premise is that notes have positions; this is the comparison that premise makes possible,
and it needs no DNA, no patent and — in its first phase — no transcription at all.

**Two phases, and they have different feasibility.**

*Phase one, percussive.* Per-drum onsets from the sub-stems X0R-1314 produces.
`drums/separate._onsets` already runs `backtrack=False` deliberately, so the times mean what
they say. Each drum's distribution of distance-from-grid, yours against theirs, with the
sample size: *their kick sits a median 4 ms from the sixteenth, yours 19.*

*Phase two, monophonic pitched.* The same figure for bass and lead vocal, which is where a
record's push or drag lives. **This phase needs X0R-412 first and is not merely improved by
it:** the onset detector's `backtrack` contributes 15–31 ms on a pitched stem with an SD of
6–17 ms and a maximum of 75 ms (§10.4(b)), against `DETECTOR_JITTER_MS = 7.0` on drums and a
real microtiming signal of 5–50 ms. It is larger than the thing being measured and it is not
a constant that can be subtracted.

**Why it is blocked on X0R-1319 as well, and this is the harder gate.** A comparison of two
records needs two independently estimated grids — unlike Experiment 2, which compared six
bounces of one song and could use one shared ruler. On the two live-drummed records tested
the grid came back at half time, at the wrong metre, and with a constant-tempo residual of
23–30 ms, which is inside the signal. Built before X0R-1319, this card reports the grid's
error as the drummer's feel.

**Acceptance criteria** — none of them writable until the two gates clear, listed so the
shape is agreed
- Per-drum and per-pitched-stem distance-from-grid distributions, both sides, with sample
  sizes and the grid confidence that produced them.
- **Abstains outright where either side's grid is unresolved**, rather than reporting a
  figure against a grid that failed. The whole card is downstream of X0R-1319's honesty.
- The detector's own contribution is stated alongside every figure, in the same units, so a
  reader can see when the measurement is smaller than its error bar — the
  `DETECTOR_JITTER_MS` precedent.
- Observation only. **No dial, ever.** Reporting where their kick sits is a measurement;
  moving the user's kick there is quantising, which is §1(c) and out.
- Tested on at least one live-drummed pair, since that is the case the whole card exists for
  and the case every grid in the codebase currently fails.

**Out of scope.** Quantise, groove transfer, swing imposition, nudging anything. Note length
(X0R-1321). Guitar, piano and `other`, which need polyphonic transcription and are refused
in §10.5.

---

## EPIC-14 — Speed and the feel of using it (Phase 3) · **placeholder, not scoped**

**Created 2026-10-05 at Ryan's request as a holding pen.** The cards below are seeded from
things already measured or already filed, so that whoever scopes this is starting from
numbers rather than from a blank page. **None of them has been through the PM**, none has
acceptance criteria a QA pass could run, and the point total is provisional. Treat the list
as evidence, not as a plan.

Two reasons this epic is worth opening now rather than when something feels slow.

**The first is that "feels slow" is finally measurable.** X0R-306 shipped a harness that
reports wall clock as a multiple of real time and writes it to `docs/benchmarks/` with the
model, the versions and the commit. Before that, a performance change could only be felt.
Now a change can be scored, and a regression can be caught by a number rather than by
somebody noticing.

**The second is that the waits got longer this week, on purpose.** Three features shipped
that each cost time, each for a good reason, and nobody has looked at the total.

### The measured baseline, as of 2026-10-05

All on CPU, on a three-minute track unless stated, from `docs/benchmarks/`:

| | cost | measured where |
|---|---|---|
| Separation, `htdemucs_6s` (the default) | **1.24× real time** — a 3½-minute song takes ~3 min | `2026-10-05-timing-only-htdemucs_6s.md` |
| Separation, `htdemucs` | 0.94× real time | `2026-10-05-timing-only-htdemucs.md` |
| Separating the reference too | **doubles the wait** before anything is on screen | the second separation is the same cost |
| The instrument comparison | **~5 s → ~20 s** this week, from the pitch contour on both sides | X0R-1320 |
| Per-drum separation | ~half the audio's length again, **per side** — 29 s on a 28 s pair | X0R-1314 |
| First call to `/tracks/drum-kits` | ~5 s, a cold subprocess probe | QA SPRINT-2 D5 |

The shape of it: **a user waits about six minutes before the comparison they came for is on
screen**, and three of those minutes are the reference, which a saved profile already
avoids on the second song. Nothing here is obviously wrong; nothing here has been looked at
as a whole either.

### Seeded candidates — performance

| id | title | pts | what is already known |
|---|---|---|---|
| X0R-1401 | The second song is fast, and the first one says so | 3 | A profile removes the reference separation entirely (X0R-1125, X0R-1317), and the per-drum pass with it. The machinery exists; what is missing is that nobody is *told* on their first run that the second will be three minutes shorter. Probably a product card, not a performance one. |
| X0R-1402 | Stop paying for the drum-kit probe on the request path | 1 | `drumsep.available` shells out to a fresh interpreter, cached per process, so the first call after a restart costs ~5 s on a plain GET. Warm it at startup or move it off the request. QA SPRINT-2 D5. |
| X0R-1403 | Measure where the comparison's 20 seconds actually goes | 2 | **`DONE` 2026-10-05.** Profiled with `tools/stage_profile.py` at two lengths. The assumption was right about the contour and wrong about everything else: **the comparison itself costs 0.00 s** across six instruments, so the whole wait is measurement. The character pass is 50% of the job and **the vocal alone is 40% of it** - the other five stems are ~2 s each. It is linear in the song's length at **0.47x real time**, so the "about twenty seconds" on screen was true only of the 28-second pair it was measured on. Numbers in `app/jobs/stages.py`. |
| X0R-1404 | A progress bar that reflects the work, not the step | 2 | **`DONE` 2026-10-05, and it was worse than "approximate".** The comparison reported **0.9 immediately before the stage that is half the job**, so the bar raced to ninety per cent and then appeared to hang for forty-odd seconds. `app/jobs/stages.py` now derives fractions from the X0R-1403 weights, and `tests/test_stages.py` asserts no stage may claim more than the work behind it - the assertion the old numbers fail by forty points. The front end stopped discarding the stage message at the same time (see **X0R-1409**). Fractions elsewhere are still hand-picked; this card bought the module they can move into. |
| — | **GPU path** | 3 | **Already filed as [X0R-307](#x0r-307--gpu-path--3--todo) in EPIC-03.** Not duplicated here. It is the single largest lever on this table and is worth scoping with the rest. |

### Seeded candidates — usability

| id | title | pts | what is already known |
|---|---|---|---|
| X0R-1405 | A dial that says "Applied" was applied | 2 | **A real defect, filed and not fixed.** `refreshMoveButtons` decides by comparing the lane's value with the suggestion, so any suggestion equal to the control's rest position reads as already applied — pan is where it bites, because a centred reference offers `pan: 0` and that is also where the control does nothing. Fixed in the per-drum rows by recording what was *taken*; the lanes keep no such record, and giving them one is a change to the mixer. QA SPRINT-2 D4. |
| X0R-1406 | Decide what happens to "Match strength" | 1 | It now sits beside a control that measurably does more (X0R-1306). Experiment 2 put its whole range at 0.56 dB, under half this project's own threshold. Leaving a working control next to one that only looks like it works is a decision, and right now it is an unmade one. **Ryan's call, not the PM's.** |
| X0R-1407 | The comparison screen after three sprints of additions | 3 | Sprint 1 spent 5 points reducing 19 controls to 6 groups. Since then the screen has gained a per-drum expander, a band ladder, two observation rows and a budget control. R8 of sprint 2 predicted exactly this and nobody has gone back to look. |
| X0R-1408 | Say what a run will cost before it starts, everywhere | 1 | **Half done 2026-10-05.** The instrument comparison's estimate was a flat "about twenty seconds" regardless of the song; it now scales with what the user loaded, from the X0R-1403 measurement, and a saved profile is quoted lower because it measurably is. **Separation still says nothing**, and it remains the longest wait in the application - that is what is left of this card. |
| X0R-1409 | A wait that shows it is alive | 2 | **`DONE` 2026-10-05, unplanned, from Ryan's "loading indicators when comparing stems".** The server had been sending a stage name on every poll since the job existed and `pollJobQuietly` dropped it on the floor - so a ninety-second wait showed one unchanging sentence and a pulsing dot. `apps/studio/wwwroot/waiting.js` draws the stage, a measured bar, and a clock counting up against the estimate, and says so when the estimate is overrun rather than going quiet. It deliberately does **not** creep the bar between stages: interpolating toward a boundary the page was never told about is inventing progress, which is the fault X0R-1404 exists to fix. |

### Unplanned, built 2026-10-05 — the chat box

| id | title | pts | state |
|---|---|---|---|
| X0R-1410 | Say what you want, in words | 5 | **`DONE`** |

Ryan's idea, in his words: *"it'd be awesome if there was the ability to have a chat prompt
and say things like 'I want this song a little bassier' or 'i want the guitars to pop a
little more'"*. Built as `app/services/mastering/ask.py`, `POST /tracks/{id}/ask`, and the
panel above the instrument comparison.

**The design decision worth recording is what it is not.** It is not a model and it invents
no processing. Every move it makes goes through `writeControl` - the same function the
comparison's own buttons use - so a sentence and a dragged fader end in the same place, the
slider visibly moves, the monitor hears it, and "Undo that" puts it back. Nothing is applied
that cannot be seen.

**And every reply carries the measurement.** Asking for more bass when the comparison has
you 1.8 dB above the reference's gets you the bass you asked for *and* the sentence saying
where that leaves you:

> A touch more bass: level +0.5 dB on the bass. The comparison put your bass 1.8 dB over
> Reference Song's, so this moves away from it, which may be exactly what you want.

That is the whole reason this was worth building rather than a worse set of faders.

**A vocabulary, not English** - no model runs on this machine, and a feature that depended
on a network call would make the one deterministic thing about this application untrue. The
cost is real, and the honest response to it is to fail loudly: it says when it has not
understood, lists what it knows, and publishes the whole vocabulary at
`GET /tracks/ask/vocabulary` so the page shows the edges rather than guessing at them. Four
families of request that get a straight "no, and here is the nearest thing that exists":
sounding professional, instrumentals, tempo and pitch, and adding reverb.

**Limits, because a box you can type into nine times is a box somebody will.** Each control
has its own ceiling measured from where the conversation started, not from where the last
sentence left it - so somebody who dragged a fader up by hand first is not refused their
opening request. 44 tests, including one that types the same thing nine times and one that
asserts every example it offers a user actually parses.

**One bug worth keeping on the record.** "Less mud" originally *added* low-mid. A complaint
word pulls its two signs apart - more mud is more low-mid, and somebody typing "muddy" wants
less of it - and conflating them inverts exactly the phrase a user is most likely to type.
Caught by a test, now locked by six parametrised cases.

**Two requests in one sentence work**, and did not at first: "less bass and more drums"
used to resolve by picking the longer verb and silently dropping the rest, which is the one
behaviour this box is least allowed to have. It now splits on a conjunction, applies each
half in turn against the faders the previous half left, and **only keeps the split when both
halves parse on their own** - so "a little more bass and" is still read as one sentence. A
modifier stated once governs both halves, because "bass and drums up a lot" means it about
both and giving one of them half as much is the sort of inconsistency a user notices and
cannot explain.

**What it still cannot do:** anything the five tone bands, six levels, width and dynamics
cannot. It has no memory of the conversation beyond the ceiling, so "no, less than that"
is not a sentence it understands - "less bass" is.

### What is deliberately **not** in here

- **Persistence of any kind.** EPIC-07 is a `NON-GOAL` and nothing in a performance epic may
  quietly reintroduce it. "Cache it between sessions" is a persistence decision wearing a
  performance hat.
- **Anything that trades honesty for speed.** Windowing the stem profiles was tried in
  `stem_match` and abandoned on the numbers — it put parts that come and go several dB out,
  which is enough to invent a finding. Shorter analysis is not free, and this epic does not
  get to spend accuracy without saying so.
- **Streaming or background rendering.** Not a speed problem, and the architecture that
  would make it one is EPIC-07.

### Before anything here is scoped

Run the benchmark on a real three-minute song **through the API rather than the harness**,
so the figures above include job overhead, I/O and the comparison, not just separation. The
numbers in the table are the separator alone, and the user's six minutes is not.
