# Sprint 3 — pop punk to EDM, and what the field already solved

Opened 2026-10-11 from three instructions from Ryan:

> I'm ok with produc0r using free third party APIs to assist with the remixing but self
> contained code is best. Iterative is fine, I just want to see it taking pop punk songs to
> edm songs as a use case for now

> Continue probing the web for similar software and functionality that could be useful for
> extractor. Add any findings to a new backlog sprint for review

**This is a review document, not a plan.** Nothing below is scheduled. It exists so the
scope decision at the top is made deliberately rather than discovered halfway through a
sprint.

---

## 1. The scope decision this requires, stated plainly

Pop punk sits around 170 BPM. EDM sits around 128. **Getting from one to the other is a
tempo change, and tempo change is a recorded non-goal** — [PR0DUCER.md §1(c)][proposal], and
EPIC-13's governing sentence:

> this is a *re-production*, not a remix … The thing that literally does "remix the source
> in that style" is Suno's Cover feature; it ships, it replaces your recording with a new
> one, and this is not it.

That line was written because Ryan asked for it, and the reasoning behind it has not
changed: a remix framing invites a comparison with Suno that this loses on every axis
except its real advantage — *your performance, kept, with every move showing its
measurement*.

**What has changed is that Ryan now wants the thing the non-goal excludes.** That is his
call to make and he has made it. What should not happen is the non-goal quietly eroding
card by card. So:

- **The non-goal needs formally reopening on the epic**, with a sentence saying what
  replaced it, before any card below is built.
- **The advantage still has to survive.** "Your performance, kept" is the whole argument
  against Suno. A pipeline that re-synthesises everything has thrown it away and should be
  honest that it has.
- **`NO_DRM_CIRCUMVENTION` and the streaming block are untouched by any of this.** Nothing
  in this document proposes fetching audio from a streaming service, and nothing should.

---

## 2. The finding that changes the shape of the work

Time-stretching is the hard part of a tempo change, and it is hard for one specific reason:
**transients smear.** librosa's own documentation says its phase vocoder

> does not try to handle transients and is likely to produce many audible artifacts

and points users at Rubber Band instead. Drums are nothing *but* transients, so a pop punk
record stretched down to 128 with a plain phase vocoder arrives with its snare turned to
mush.

**This project does not have to stretch most of it.**

`drums/kit.py` already finds every drum hit and synthesises a kit on those positions.
`synth/voice.py` already plays a transcribed part from its notes. Both of those emit audio
*at whatever times they are given* — so for any part that has been transcribed or
hit-detected, a tempo change is **re-emission at new positions, not stretching**. Nothing is
smeared because nothing is stretched.

That splits the use case into two very different halves:

| part | at a new tempo | cost |
|---|---|---|
| drums | re-triggered from detected hits | **free**, already built |
| bass, synths, anything re-voiced | re-emitted from notes | **free**, already built |
| vocals | must actually be stretched | the real work |
| guitars kept as recorded | must actually be stretched | or re-voice them, which is free |

**So the honest version of this feature is: everything transcribed moves for nothing, and
the vocal is the problem.** That is a much smaller sprint than "build a remixer", and it is
almost entirely made of parts that already exist.

It also means the measurement from X0R-1325 is load-bearing in a new way: recall 1.000 and
pitch accuracy at the clean-DI ceiling is what makes re-emission viable at all. If the
notes were wrong, re-emitting them at a new tempo would be wrong twice.

---

## 3. Time-stretching, for the vocal

Three options, and the licence matters as much as the quality here — this project already
rejected LarsNet on its licence and synthesises its drums rather than shipping recordings.

| | quality | licence | dependency |
|---|---|---|---|
| **librosa `time_stretch`** | its own docs call it *"mainly for reference and teaching"* | ISC, already installed | none new |
| **Rubber Band** | the reference implementation; resets phase at transients | **GPL, or paid commercial** | a CLI binary |
| **Signalsmith Stretch** | reported comparable to Rubber Band | **MIT** | C++ header lib, needs a binding |

**Rubber Band would make extract0r GPL**, or cost money. Its licence page is explicit: code
received under the GPL means "your application must also be Free Software and you must
provide source code for it." For a portfolio project that may not matter, and it is a
decision rather than a detail.

**Signalsmith is the interesting one, with one specific caveat that lands exactly on this
use case.** It is MIT, it is reported comparable in quality — and its own README says
time-stretching "sounds best for more modest changes (between 0.75x and 1.5x)".

**170 → 128 BPM is a ratio of 0.753.** Right on the boundary. Close enough to be worth
measuring rather than assuming, and far enough from the middle that it should be measured
*before* anyone commits to it.

There is no Python binding for Signalsmith today; there is a Rust crate. That is real work,
and it is the kind of work that pays off once.

---

### Candidate D, measured 2026-10-12 — and the decision is Signalsmith

Each stretcher was run on a vocal-like part synthesised at 170 and compared against the same
part synthesised directly at 128 — what a singer at the slower tempo would actually produce.
Two things a real singer does were built into that truth on purpose: vibrato keeps its rate,
and consonants keep their length.

| | licence | length | pitch | vibrato | spectral fidelity | attacks | time |
|---|---|---:|---:|---:|---:|---:|---:|
| truth | | 0.0% | 0 c | 5.5 Hz | 0.0 dB | 1.00 | |
| librosa | ISC | 0.0% | 3 c | 4.1 Hz | 6.1 dB | 0.20 | 1.67 s |
| **Signalsmith** | **MIT** | 0.0% | 3 c | 4.1 Hz | **3.8 dB** | 0.34 | **0.14 s** |
| Rubber Band | GPLv2 / paid | 0.0% | 3 c | 4.1 Hz | 5.2 dB | **0.81** | 0.41 s |

**Signalsmith wins on what matters for the parts that are actually stretched.** A vocal, or a
guitar kept as recorded, is mostly sustained tonal material, and Signalsmith is the most
faithful of the three on it — and twelve times faster than librosa. Rubber Band's genuine
advantage is attacks, 0.81 against 0.34. **But attacks are exactly what this design never
stretches**: drums are re-struck, not processed. So the architecture and the licence point the
same way, which is a better reason to choose it than that it is free. The 0.75x boundary in
its README did not bite at 0.753.

None of them keeps vibrato at its own rate — all three slow it to 4.1 Hz, which is 5.5 ÷ 1.328.
That is inherent to stretching and is the main audible tell on a held vocal note.

**The measurement nearly gave the opposite answer, and that is worth more than the table.**
The first spectral metric floored silence at -120 dB, so it measured noise floors rather than
music. Signalsmith scored *26.9 dB* — worst by far — and the recommendation would have been to
pay for Rubber Band or go GPL. What exposed it: an inaudible 16-bit round trip moved the
metric from 12 dB to 33. Flooring each frame 60 dB below its own peak fixed it, and both
columns now move 0.00 dB under that round trip. A measure that is not checked against an
inaudible change is not a measure.

Also caught: Signalsmith's time factor is a *speed* factor, the opposite way round from the
other two. `setTimeFactor(1.328)` made audio shorter. Encoded in `retempo.stretch` with a
test on the output length.

pylibrb was installed for the measurement and removed afterwards, so nothing GPL is left in
the environment. `python-stretch` is pinned in `requirements-ml.txt` with this reasoning.

## 4. Separation — nothing to do, and that is worth recording

The 2026 field has moved to the **BS-RoFormer / Mel-RoFormer** families, which sit above
HTDemucs on the MVSEP leaderboard. Worth knowing and **not worth acting on yet**:

- **The weights' licences are unclear.** Community checkpoints are frequently shared with no
  licence at all, and the code licence routinely differs from the weights licence. This
  project has already turned down a better model for exactly this reason.
- **Separation is not the bottleneck.** X0R-1325 measured transcription recall at 1.000
  *through* htdemucs_6s. Separation is not what is limiting anything today.
- X0R-306 is the card that should decide this, with numbers, if it ever matters.

---

## 5. Candidate cards, for review and not yet scheduled

| | what | points | note |
|---|---|---|---|
| A | Reopen the tempo non-goal on EPIC-13, or decline to | 0 | **done** — Ryan reopened it |
| B | A target tempo on the pr0ducer page, and a re-emitted drum part at it | 3 | **done** — X0R-1332 |
| C | Re-emit any re-voiced part at the target tempo | 2 | **done** — X0R-1332 |
| D | Measure the three stretchers on a real vocal at 0.753 | 2 | **done** — Signalsmith, see §3 |
| E | Stretch the parts that are kept as audio | 5 | **done** — `retempo.stretch` and the bounce |
| F | Say which parts moved and which were re-emitted | 1 | **done** — the bounce's counted summary, X0R-1333 |
| G | A remix palette: EDM kit, 808 / pluck / pad, the pump, four on the floor, one button | 5 | **done** — X0R-1334, added at Ryan's request mid-sprint |
| H | The build and the drop: a suggested bar, a riser, a roll, an impact | 3 | **done** — X0R-1335 |

B and C together are a demo: a pop punk record whose drums and bass arrive at 128 BPM with
no smearing at all, because neither was stretched. That is most of the way to the use case
and needs no new dependency, no API and no licence decision.

---

## 6. On "free third party APIs"

Ryan allowed them and said self-contained is better. Recording why self-contained keeps
winning here, so the question does not need re-litigating each time:

- Every audio API is **an upload of the user's music to someone else's machine**. The whole
  legal posture of this application — the attestation gate, the retention sweep, profiles
  and samples kept local and gitignored — is built on the audio not leaving. Samplab, the
  closest commercial equivalent to the transcribe-and-re-perform workflow, requires exactly
  that upload and caps its free tier at 10 seconds and mono.
- Nothing identified above is actually gated on an API. The hard part is time-stretching a
  vocal, and that is a library, not a service.

So: allowed, not needed, and the bar for using one should stay "it does something no local
library does".

[proposal]: ../proposals/PR0DUCER.md

---

**Sources:** [Rubber Band licensing](https://breakfastquay.com/rubberband/license.html) ·
[pyrubberband](https://pyrubberband.readthedocs.io/) ·
[librosa phase_vocoder](https://librosa.org/doc/0.8.1/generated/librosa.phase_vocoder.html) ·
[Signalsmith Stretch (Qt attribution, MIT)](https://doc.qt.io/qt-6.9/qtmultimedia-attribution-signalsmith-stretch.html) ·
[OpenMPT issue comparing the two](https://bugs.openmpt.org/view.php?id=1808) ·
[Rubber Band technical notes](https://breakfastquay.com/rubberband/technical.html) ·
[2026 separation roundup](https://mixinggpt.com/blog/best-ai-stem-separation-tools-2026)
