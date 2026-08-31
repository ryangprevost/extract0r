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

## Sprint 1 — Make it real · 20 pts

X0R-302 (Demucs, 5) · X0R-405 (basic-pitch, 5) · X0R-205 (audio probe, 3) ·
X0R-303 (real progress, 3) · X0R-105 (CI, 3) · X0R-605 (scheduled sweep, 1)

The riskiest sprint: every estimate here depends on model behaviour nobody has measured
yet. Budget the whole first day for getting torch and TensorFlow installed on Windows.

**Demo:** a real song separates and the bass line transcribes correctly.

**Exit criteria:** stub backends are no longer the default in any environment.

---

## Sprint 2 — Tab you would actually use · 21 pts

X0R-406 (drum transcription, 5) · X0R-407 (tempo/key, 3) · X0R-409 (tuning detection, 3) ·
X0R-203 (upload UX, 3) · X0R-304 (stem preview, 3) · X0R-306 (quality benchmark, 3) ·
X0R-503 (MIDI export, 2)

X0R-407 lands before the rest of the tab work because everything downstream quantises
against the detected tempo — doing it late means re-testing all of it.

**Demo:** drums and guitar from a real song, in the right tuning, on a correct grid.

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
| Torch/TensorFlow install pain on Windows | 1 | Do the Docker path first; treat native Windows as the fallback |
| Transcription accuracy below what a guitarist will tolerate | 2–3 | X0R-408 (manual correction) is the safety net; build it, do not defer it |
| Separation is too slow on CPU to feel interactive | 1 | Measure in sprint 1; if it exceeds ~2× real time, prioritise X0R-307 (GPU) |
| Legal review returns changes that alter the product | 4 | Start it in sprint 4, keep notices centralised in `app/legal.py` |
| Browser preview and server render disagree | 6 | Pick one as authoritative in the sprint-6 design spike |
