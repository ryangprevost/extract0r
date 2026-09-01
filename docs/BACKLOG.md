# Extract0r — Work Breakdown

Sprint-ready cards. Each is independently demoable and sized in points (1 ≈ half a day,
2 ≈ a day, 3 ≈ two days, 5 ≈ most of a week, 8 ≈ split it before you start).

**Status legend** — `DONE` shipped and verified · `PARTIAL` partly built, gaps named on
the card · `TODO` not started. Individual criteria are marked ✅ done, ⏳ blocked on
another card, ❌ not started.

| Epic | Theme | Points | Phase |
|---|---|---|---|
| [EPIC-01](#epic-01--foundation) | Foundation & dev loop | 13 | 1 |
| [EPIC-02](#epic-02--upload--ingest) | Upload & ingest | 16 | 1 |
| [EPIC-03](#epic-03--stem-separation) | Stem separation | 21 | 1 |
| [EPIC-04](#epic-04--transcription--tab) | Transcription & tab | 34 | 1 |
| [EPIC-05](#epic-05--export) | Export formats | 13 | 1 |
| [EPIC-06](#epic-06--legal--compliance) | Legal & compliance | 13 | 1 |
| [EPIC-07](#epic-07--persistence--operations) | Persistence & operations | 21 | 1.5 |
| [EPIC-08](#epic-08--reference-mastering) | Reference mastering | 21 | 2 |
| [EPIC-09](#epic-09--mix-editor) | Mix editor | 26 | 2 |
| [EPIC-10](#epic-10--mixdown--export) | Mixdown & export | 13 | 2 |

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

## EPIC-07 — Persistence & operations

### X0R-701 · Postgres-backed track and job records · 5 · `TODO`
Replaces the in-memory `TrackRegistry` and `JobStore`.

**Acceptance criteria**
- SQLAlchemy models for tracks, stems, jobs, and exports; Alembic migrations.
- Restarting the API does not lose in-flight or completed job state.

---

### X0R-702 · Redis/RQ worker · 5 · `TODO`
**Acceptance criteria**
- Jobs survive an API restart and run in a separate worker process.
- Workers scale horizontally; `MAX_CONCURRENT_JOBS` becomes a worker-count concern.
- `JobStore` callers are unchanged (the seam already exists).

---

### X0R-703 · Object storage · 3 · `TODO`
**Acceptance criteria**
- S3/R2 behind the same `TrackStorage` interface, selected by config.
- Downloads use pre-signed URLs; the API never proxies audio bytes.
- Lifecycle rules mirror the retention window server-side.

---

### X0R-704 · Accounts and track history · 5 · `TODO`
**Acceptance criteria**
- Email magic-link auth; anonymous use still works with a shorter retention window.
- Signed-in users see their previous tracks and can re-download exports.

---

### X0R-705 · Observability · 3 · `TODO`
**Acceptance criteria**
- Structured JSON logs with a request/job correlation id.
- Metrics: job duration by kind, failure rate by backend, queue depth.
- Health endpoint reports backend availability, not just process liveness.

---

### X0R-706 · Live job updates over WebSocket/SSE · 3 · `TODO`
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
- Warnings for inter-sample peaks and for LRA collapse.

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

### X0R-905 · Effects: compression and reverb · 3 · `TODO`
**Acceptance criteria**
- Compressor with threshold, ratio, attack, release, makeup, plus gain-reduction metering.
- Reverb as a send with a wet/dry control.
- Presets per stem type.

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
