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

EPIC-08 and EPIC-11 were carrying their *original* scope in this table (21 and 24) while
cards kept being added underneath. Both are now the sum of the cards actually in them.
Current sprint plan: [sprints/SPRINT-1.md](sprints/SPRINT-1.md).

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

### X0R-306 · Separation and transcription quality benchmark · 5 · `TODO`
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

---

### X0R-307 · GPU path · 3 · `TODO`
**Acceptance criteria**
- `DEMUCS_DEVICE=cuda` is used when a GPU is present, CPU otherwise, decided at runtime.
- Documented CUDA container variant.

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

### X0R-1127 · Decline to match a stem your own mix does not contain · 2 · `TODO`
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
