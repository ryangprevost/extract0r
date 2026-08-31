# Extract0r — Sprint sequencing

Two-week sprints, ~20 points each for one developer. Card details are in
[BACKLOG.md](BACKLOG.md).

## Sprint 0 — Skeleton · **complete**

X0R-101, 102, 103, 104, 201, 202, 301, 401, 402, 403, 404, 501, 502, 601, 602, 603, 901

The whole pipeline runs end to end on stub backends, the domain layer is real and tested,
and the legal gate is enforced server-side. What is missing is the machine learning, not
the application.

**Demo:** upload → separate → pick stems → get playable tab → download `.txt` and `.x0r`.

---

## Sprint 1 — Make it real · 20 pts · **complete**

X0R-302 (Demucs, 5) ✅ · X0R-405 (pitched transcription, 5) ✅ · X0R-205 (audio probe, 3) ✅ ·
X0R-303 (real progress, 3) ✅ · X0R-605 (scheduled sweep, 1) ✅ · X0R-105 (CI, 3) — written,
never executed

**Demo:** `tools/verify_pipeline.py` runs a synthesised mix through the real backends end
to end. Measured on this machine: `htdemucs_6s` produced all six stems (drums, bass,
vocals, other, guitar, piano) from 12 s of audio in 23 s — **1.9× realtime on 4 CPU
cores**, right at the threshold that would trigger X0R-307 (GPU). Transcription of four
stems added 10 s.

### What the sprint actually cost

"Budget the whole first day for getting torch installed on Windows" turned out to be the
accurate part of the plan. Two install blockers, neither of which is a code problem:

1. **Windows MAX_PATH.** `pip install torch` fails inside this project tree — the path is
   long enough that torch's bundled licence directory exceeds 260 characters — and leaves
   a *half-installed* torch behind. The visible symptom is
   `ModuleNotFoundError: No module named 'torchgen'`, which points nowhere near the cause.
   Resolved with a second venv on a short path.
2. **basic-pitch pins `tensorflow<2.15.1`**, and TensorFlow ships nothing below 2.16 for
   Python 3.12. pip responds by backtracking to a source distribution and trying to build
   numpy, so the error you see is `Failed to build 'numpy'`. Resolved by installing
   `--no-deps` and running the bundled ONNX weights on onnxruntime.

Both are now in docs/RUNBOOK.md and automated in `scripts/install-ml.ps1`, which verifies
each backend imports before it claims success.

### What changed versus the plan

- **Ingest does not use ffprobe.** `soundfile`'s bundled libsndfile reads MP3, so probing
  and decoding need no system dependency. ffmpeg left the Phase 1 critical path entirely.
- **Pitched transcription became two backends, not one.** Bass is monophonic, so pYIN
  (librosa, no extra install) beats a polyphonic neural net on it. basic-pitch now covers
  only guitar and piano. `TRANSCRIPTION_BACKEND=auto` selects per stem.

### Four things running the real backends taught us

- **Demucs exits 0 on a missing input file.** A clean return code is not proof of success,
  so the adapter checks that stems were written and surfaces Demucs' own output.
- **librosa's default pYIN frame is too short for bass.** 2048 samples is under two cycles
  of a 5-string low B, and it returns wrong pitches *without raising anything*. Frame
  length is now derived from the stem's lowest expected pitch.
- **Tempo octave ambiguity is immediate and unavoidable.** A 100 BPM click and a 200 BPM
  click both report ~99.4 BPM. This makes X0R-407 a prerequisite for trusting drum output,
  not the nice-to-have it was scheduled as.
- **One out-of-range note aborted the whole transcription.** Bass bleed into the guitar
  stem produced a G1, and the solver's strict `UnplayableError` — correct for
  hand-entered input — killed the job. Real model output needs a policy, not an
  exception. Now `DROP` by default, with the counts reported. This only surfaced because
  the pipeline was run end to end on real output; no unit test would have found it.

### Still open

- **No accuracy number exists for anything**, and sprint 1 showed why that matters more
  than it looked. The end-to-end run returned a bass line an octave high and a drum tempo
  of 60 BPM against a true 120. A controlled check ruled pYIN out — it reads the same
  notes correctly from the unseparated signal — so the fault is Demucs being fed
  synthetic sine waves, far outside its training distribution. **The synthetic harness
  cannot measure quality**; it only proves the wiring. X0R-306 is now the gating card for
  the entire transcription epic.
- Separation speed measured at 1.9× realtime on synthetic audio only. A real three-minute
  song is still unmeasured, and 1.9× leaves almost no headroom.
- CI has never run: no git remote.

---

## Sprint 2 — Trust the output · 21 pts · **re-ordered after sprint 1**

X0R-306 (quality benchmark, 3) · X0R-407 (tempo/key, 3) · X0R-406 finish (drums, 5) ·
X0R-409 (tuning detection, 3) · X0R-203 (upload UX, 3) · X0R-304 (stem preview, 3) ·
X0R-503 (MIDI export, 2)

**X0R-306 moved to the front of the sprint.** It was scheduled sixth. Sprint 1 ended with
every backend running and *no idea whether any of it is accurate* — the smoke tests prove
the adapters work, not that the transcription is right. Until there is a number, every
tuning decision downstream is guesswork. Do it first; it also unblocks the deferred
acceptance criteria on X0R-405 and X0R-406.

Getting a licensed multitrack set is the long pole. MUSDB18-HQ is the obvious choice for
separation; for transcription, recording a few DI bass and guitar parts is faster than
licensing anything and gives exact ground truth.

X0R-407 stays early: everything downstream quantises against the detected tempo, and
sprint 1 showed the tempo can be out by a factor of two.

**Demo:** drums and guitar from a real song, in the right tuning, on a correct grid — with
an accuracy figure next to it.

---

## Sprint 3 — Corrections and formats · 21 pts

X0R-408 (manual correction, 5) · X0R-410 (techniques, 5) · X0R-504 (MusicXML, 3) ·
X0R-505 (PDF, 3) · X0R-411 (vocal line, 3) · X0R-506 (`.x0r` re-import, 1) ·
X0R-607 (privacy policy, 1)

X0R-408 is the highest-value card in the project: it converts "the model got it 85% right"
from a failure into a usable draft.

**Demo:** fix a wrong note, export to MuseScore and PDF.

---

## Sprint 4 — Ship it · 21 pts

X0R-701 (Postgres, 5) · X0R-702 (Redis worker, 5) · X0R-703 (object storage, 3) ·
X0R-705 (observability, 3) · X0R-206 (rate limiting, 3) · X0R-604 (legal review, 2)

**X0R-604 blocks public launch.** Start the lawyer conversation at the beginning of this
sprint, not the end — it is the one card that cannot be unblocked by working harder.

**Exit criteria:** Phase 1 is publicly usable.

---

## Sprint 5 — Mastering · 21 pts

X0R-802 (reference upload, 2) · X0R-803 (matchering, 5) · X0R-801 finish (3) ·
X0R-804 (preview and A/B, 3) · X0R-806 (guardrails, 2) · X0R-807 (quality report, 3) ·
X0R-805 (per-stem vs bus, 3)

**Demo:** a rough mix matched to a commercial reference, with the before/after numbers on
screen.

---

## Sprint 6 — Mix editor · 21 pts

X0R-903 (Web Audio preview, 8) · X0R-902 (mixer UI, 5) · X0R-904 (parametric EQ, 5) ·
X0R-906 (undo/presets, 2)

X0R-903 is an 8 and should be split at planning: (a) load and play stems in sync,
(b) live parameter changes, (c) metering. Its real risk is drift between the browser
preview and the server render — decide up front which one is authoritative.

---

## Sprint 7 — Export and polish · 18 pts

X0R-1001 finish (3) · X0R-905 (effects, 3) · X0R-1004 (render queue, 3) ·
X0R-1002 (formats, 2) · X0R-1003 (metadata, 2) · X0R-1005 (export history, 3) ·
X0R-704 (accounts, 5 — pull forward if history is wanted sooner)

**Demo:** full Phase 2 loop — upload, separate, master to a reference, mix, export one MP3.

---

## Standing risks

| Risk | Sprint | Mitigation |
|---|---|---|
| ~~Torch/TensorFlow install pain on Windows~~ | ~~1~~ | **Hit, and resolved.** Two-venv setup plus the ONNX path; see docs/RUNBOOK.md |
| Transcription accuracy below what a guitarist will tolerate | 2–3 | **Still entirely unknown.** X0R-306 now leads sprint 2; X0R-408 (manual correction) is the safety net |
| Separation is too slow on CPU to feel interactive | 2 | Still unmeasured on a real song. `tools/verify_pipeline.py` prints a realtime multiple; if it exceeds ~2×, prioritise X0R-307 (GPU) |
| Tempo detection off by an octave, corrupting every grid | 2 | Seen in sprint 1. X0R-407 promoted to a prerequisite for drum output |
| Legal review returns changes that alter the product | 4 | Start it in sprint 4, keep notices centralised in `app/legal.py` |
| Browser preview and server render disagree | 6 | Pick one as authoritative in the sprint-6 design spike |
