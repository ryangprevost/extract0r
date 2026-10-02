# Experiment 1 — the fingerprint, read cold

Run 2026-10-01 against [PR0DUCER.md](PR0DUCER.md) §7. Throwaway experiment, not a card.

**Result in one line.** The fingerprint is real and two of its figures told me something
I could not have guessed — but not the two the proposal is built on, and the headline
claim of X0R-1302 (programmed versus played) **cannot be made honestly at all**. Stage 1
is worth building at about **5 points, not 8**, and the 3 points come off by deleting the
card the proposal treats as the deliverable.

Code: [`app/services/analysis/fingerprint.py`](../../services/api/app/services/analysis/fingerprint.py),
tests in [`tests/test_fingerprint.py`](../../services/api/tests/test_fingerprint.py) (26, all
passing). Nothing is wired into the API or the UI.

---

## The tracks, and an admission about them

| | A | B |
|---|---|---|
| Track | MSTRKRFT — *Bounce (feat. N.O.R.E. + Isis)* | i.am.victory — *Vacant* |
| Why chosen | known programmed electro-house, famously sidechained | furthest from the rest of the library on tempo and low-end regularity |
| Clip | densest 28 s (36.0–64.0 s) | densest 28 s (192.0–220.0 s) |

**The experiment did not get the contrast it was designed for, and that weakens it.**
The brief asked for one programmed and one live-drummed record. `LIBRARY_DIR` holds five
source tracks and three extract0r outputs, and every one of them is electronic or
electro-pop — four of the five sit within 1 BPM of each other at ~129. There is no
live-drummed track in Ryan's library to test against. Both tracks I picked turned out to
be four-on-the-floor, so the fingerprint was asked to distinguish two records that are
genuinely similar in the dimension it measures best.

Two further caveats on the data. *Vacant* is an extract0r **output**, already mastered by
this tool, so its level and census figures describe a processed file. And a 28-second clip
is 15–19 bars of one section; nothing here tests whether a fingerprint of the chorus
describes the record.

---

## 1. The two fingerprints

| Measurement | MSTRKRFT — Bounce | i.am.victory — Vacant |
|---|---|---|
| **Tempo** | 128.90 BPM (grid conf 0.92) | 161.99 BPM (grid conf 0.97) |
| **Metre** | 4/4, 14.8 bars in the clip | 4/4, 18.8 bars |
| **Key** | F minor (conf **0.19**) | E minor (conf 0.58) |
| **Kick, per 16ths of the bar** | `13 0 0 0 · 12 0 0 0 · 15 0 0 0 · 12 0 0 0` | `15 0 0 0 · 14 0 0 0 · 12 0 0 0 · 14 0 0 0` |
| **Kick on a beat** | 52 of 59 beats, **0 off the beat** | 54 of 75 beats, **0 off the beat** |
| **Snare, per 16ths** | `8 0 0 0 · 13 0 0 0 · 10 7 0 0 · 11 0 0 0` | `16 0 0 0 · 15 0 0 0 · 17 0 0 0 · 15 0 0 0` |
| **Hats, per 16ths** | `3 1 15 0 · 6 1 14 0 · 0 13 1 0 · 5 0 10 0` | `15 0 11 10 · 14 8 16 15 · 18 0 17 8 · 15 16 10 14` |
| **Hats on the offbeat eighth** | **58.0%** (40 of 69), conf 0.92 | 28.9% (54 of 187), conf 0.96 |
| **Swing** | **0.459**, IQR 0.048, conf 0.74 | 0.519, IQR 0.134, conf 0.45 |
| **Hit spread, kick** | 7.67 ms — *inside detector jitter* | 8.39 ms — *inside detector jitter* |
| **Hit spread, snare** | 7.44 ms — *inside detector jitter* | 9.32 ms — *inside detector jitter* |
| **Hit spread, hats** | 17.37 ms, conf 0.88 | 10.46 ms — *inside detector jitter* |
| **Bass dip at kicks** | 45.0 dB (IQR 18.4) | 16.2 dB (IQR 5.2) |
| **…same dip away from kicks** | 14.5 dB (IQR 38.1) | 8.4 dB (IQR 8.0) |
| **Duck = excess at kick** | **ABSTAINS** — per-kick dips vary by 18 dB | **+7.8 dB**, conf 0.35 |
| **Bass not playing at all** | **17 of 52 kicks** | 3 of 55 kicks |

### Instrumentation census

| Stem | Bounce, rel. LUFS | present | onsets/bar | Vacant, rel. LUFS | present | onsets/bar |
|---|---|---|---|---|---|---|
| vocals | −5.14 | yes | 9.3 | −4.59 | yes | 7.2 |
| drums | −4.65 | yes | 7.9 | −7.94 | yes | 7.2 |
| bass | −8.60 | yes | 7.4 | −9.85 | yes | 14.9 |
| guitar | **−22.74** | **yes** ⚠ | 10.8 | −8.48 | yes | 8.8 |
| piano | −54.38 | no | — | −60.51 | no | — |
| other | −12.63 | yes | 10.0 | −14.89 | yes | 5.3 |

⚠ There is no guitar on *Bounce*. See §3.

---

## 2. The experiment's question, answered

> **Reading only this, do you know something about that record you did not know, and do
> you know what you would do to your mix because of it?**

**A little, and less than the proposal assumes. Two figures out of roughly a dozen.**

### What genuinely told me something

**The hat subdivision and its placement.** *Bounce* puts 58% of its hats on the offbeat
eighth and **zero** on the sixteenths between — the histogram has hard zeros at steps
3, 7, 11, 15. *Vacant* spreads hats across all sixteen positions. That is the single
clearest difference between the two records in the whole table, and it is the one a
listener would describe loosely ("one's got that offbeat thing") and could not quantify.

And underneath it, the figure I would not have guessed at all: **Bounce's offbeat hats sit
at 0.459, not 0.5** — **19.1 ms *ahead*** of the exact midpoint of the beat, median over
43 events with a standard error of 2.5 ms. *Vacant*'s sit at 0.519, **7.0 ms late**
(SE 3.7 ms). The hats are pushed on one record and dragged on the other.

I nearly threw this out, because `backtrack` biases an onset earlier by an amount that
depends on how soft the attack is, and a hat and a kick do not have the same attack — so a
hat offset measured against a kick-fitted grid could be pure artefact. What rescues it is
that **the two signs are opposite**. A systematic detector bias pushes both the same way;
it cannot make one record's hats early and the other's late. So the difference between the
two is trustworthy even though neither absolute figure is fully clean, and "your hats are
19 ms later than that record's" is a legitimate suggestion where "that record pushes its
hats 19 ms" is not quite.

**Whether the bass plays through the kick, and what it does there.** On *Vacant* the bass
is sounding either side of 52 of 55 kicks and drops 7.8 dB more at a kick than at an
equivalent kick-free position — a duck. On *Bounce* the bass **is not playing at all
across 17 of 52 kicks**: the part is written in the gaps rather than compressed into them.
Those are two different production decisions that sound similar and are fixed differently,
and I could not have told them apart by ear with any confidence.

### What told me nothing

- **"Kick on every beat."** True of both, and audible in one bar. The histogram is a
  satisfying thing to look at and it is not news.
- **Tempo and key.** Correct, useful, and every DJ tool on the machine already reports
  them. The key *confidence* difference (0.19 vs 0.58) is mildly interesting as a proxy
  for harmonic ambiguity, which is not what it is for.
- **The census.** "No piano on this record" is a thing you know instantly. The one
  non-obvious claim it made — guitar present on *Bounce* — is **wrong**.
- **Programmed versus played.** The marquee claim of X0R-1302. See §3; it is not that the
  answer was boring, it is that there is no answer.

### The conclusion I did not expect

The two figures that carried information are both **inputs to processing**, not things
worth reading. "Your offbeat hats sit 26 ms later than that record's" and "that bass is
ducked 8 dB and yours is not" are suggestions, and they key directly into X0R-1307 and
X0R-1308 in **stage 3**. Neither is improved by being printed on a card first.

So the fingerprint survives the experiment, and **X0R-1303 — the fingerprint card — does
not.** Read cold, as a card, it is four lines of things you knew and one line that is
wrong. Read as a steering signal for the processing half, it has two real dials in it.
That is a different product from the one §6 of the proposal describes.

---

## 3. What was reliable, what was marginal, what could not be done

### Reliable

| Figure | Why it holds |
|---|---|
| **Kick placement against the grid** | Unambiguous once the grid is right. Both tracks: every kick on a beat, zero elsewhere, across 100+ events. |
| **Hat subdivision and offbeat share** | Large samples (69 and 187 hits), hard zeros where they should be. |
| **Tempo, after re-derivation from the drums** | 0.92 and 0.97 F-measure against the drum hits. |
| **Stem absence** | Piano at −54 and −60 LU. A stem that far down genuinely is not there. |
| **Swing, when the IQR is tight** | *Bounce* at IQR 0.048 is a real distribution. *Vacant* at 0.134 is marginal and its confidence (0.45) says so. |

### Marginal

**Snare labelling.** `find_hits` puts a snare on 48 of *Vacant*'s 75 beats and on 38 beats
of *Bounce* that already have a kick — kick and snare coincide on most beats of both
records. Some of that is real (claps layered on the kick), but a snare claimed on ~73% of
all beats is cross-triggering: a kick with body in 160–450 Hz clears `SNARE_BODY_RISE_DB`,
and cymbal wash fills the rattle band. **"Snare on 61 of 64 backbeats" is not a sentence
this detector can currently support**, which matters because X0R-1301's card text uses
exactly that example.

**The bass duck.** The measurement works — but only after a control was added, and it
abstained on the one record of the two that certainly is sidechained. The first version
reported a confident 16.2 dB duck on *Vacant* and 45.0 dB on *Bounce*; both were mostly
**note envelope**, because every plucked bass note decays and nothing was comparing that
against anything. Running the identical measurement at kick-free grid positions cuts
*Vacant*'s figure to +7.8 dB and sends *Bounce*'s to an abstention. Worth having, and
confidence 0.35 is the honest ceiling on 28 seconds.

**Key.** F minor at confidence 0.19 is, correctly, an abstention in all but name.

**The −30 LU presence threshold.** It calls guitar *present* on *Bounce* at −22.7 LU. There
is no guitar on that record; that stem is separation residue with 10.8 onsets per bar of
nothing. The threshold is right for its original job in `instrument.py` — "do not match to
residue" — and wrong for the census's job, which is "say what is on the record". A level
alone cannot tell them apart.

### Could not be done honestly at all

**Programmed versus played. This is the important one.**

The figures came back at 7.7 ms (Bounce kick) and 8.4 ms (Vacant kick) — close enough to
be the same number, and both well above the 1.7 ms frame-quantisation floor, which would
read as "both played by a human". For a 2009 electro-house single that is almost certainly
false.

So I tested the measurement against itself: same kick events, same grid, timestamps
re-placed at the steepest rise of the low-passed waveform instead of at `find_hits`' frame.

| | `find_hits` (hop 256, backtrack) | same events, sample-accurate |
|---|---|---|
| Bounce kick | 7.67 ms | 6.83 ms |
| Vacant kick | 8.48 ms | **4.29 ms** |

**The ranking reverses.** By the shipped detector *Bounce* is the tighter record; measured
properly *Vacant* is, by a factor of 1.6. The detector contributes somewhere between 1 and
7 ms, it is not a constant, and it is the same size as the thing being measured. Most of it
is `backtrack=True` walking each onset back to a local envelope minimum by a variable
amount — correct for triggering a replacement sample, fatal for measuring placement.

A verdict read off these numbers is a coin toss. `DETECTOR_JITTER_MS` in the module is set
to 7.0 from this measurement, and any figure under twice it now carries a caveat refusing
the programmed/played reading — which is every figure either track produced.

**And there is no ground truth to calibrate against.** Fixing the timestamps is maybe half
a day; knowing whether the fixed number means anything requires a record with known-human
drumming, and Ryan's library does not contain one. A synthetic jitter sweep (in the tests)
confirms the *arithmetic* recovers a known standard deviation within 30% from 3 ms to
20 ms. That validates the formula and says nothing about the audio chain in front of it.

### The failure that nearly invalidated the whole run

The first pass produced a kick histogram of `[4, 4, 3, 3, 5, 2, 4, 3, …]` on *Bounce* —
flat, no pattern, a record with a kick on literally every beat. Two separate grid problems,
both of which stage 1 must solve and neither of which appears in any card:

1. **Octave.** `choose_tempo`, reading the whole mix's onsets, chose **64.6 BPM**. It is
   not a bug: at half time the synths, vocal and hats still fill the intervening beats, the
   two octaves score nearly alike, and the documented tie-break prefers the slower reading
   — which is the right call for a tab and a catastrophic one for a fingerprint. Scored
   against the **kicks and snares alone** the same function gets it right, 0.94 against
   0.67, because recall punishes the halved grid for its empty beats. `score_tempo` already
   had the mechanism; it was being fed the wrong evidence.
2. **Precision.** Even at the right octave, librosa's 129.2 against a true 128.90 is a
   0.23% error — about 136 ms of drift over 28 seconds, more than a whole sixteenth at that
   tempo. Fixed by least-squares fitting period and phase to the drum hits, iterated. A
   rotation step is needed after the fit, because least squares recovers the sixteenth
   lattice but not which rung of it is a beat.

With both: `[13, 0, 0, 0 · 12, 0, 0, 0 · 15, 0, 0, 0 · 12, 0, 0, 0]`. Same audio, same
detector, same hits — only the grid changed. **Every rhythmic figure in stage 1 is
downstream of this**, and the proposal costs it at zero.

---

## 4. What stage 1 would actually cost

The proposal says 8 points (3 + 2 + 2 + 1). **I disagree in both directions**: the work it
names is underestimated, and a third of it should not be built.

### Not costed in the proposal, and mandatory

| Work | Points |
|---|---|
| Re-derive the grid from the drums — octave re-check against kick/snare, least-squares period/phase fit, beat rotation | **+2** |
| Sample-accurate onset refinement, without which the timing figure is a coin toss | +1, **and blocked** on ground truth that does not exist |
| A presence test that distinguishes an instrument from residue (the −30 LU threshold does not) | +1, not in stage 1 |

The grid work is prototyped and tested in `fingerprint.py` as `grid_from_drums` and
`refine_grid`, so part of that +2 is paid. It would not have been, without this experiment.

### Card by card

| Card | Proposal | Mine | Why |
|---|---|---|---|
| X0R-1301 Rhythmic fingerprint | 3 | **3** | Real and valuable. The grid work is the new cost; the prototype offsets it. Drop "snare on N of M backbeats" from the card text until the snare detector earns it. |
| X0R-1302 Census + programmed/played | 2 | **1** | Split it. The census is cheap and keeps its stated threshold *with the residue caveat written on the card*. **Cut the programmed/played half entirely** — it cannot be measured honestly, and shipping it would be exactly the X0R-407 failure the proposal cites as the house precedent. |
| X0R-1303 The fingerprint card | 2 | **0 — cut** | This is the experiment's actual finding. Read cold, the card is things you knew plus one thing that is wrong. The two figures that carried information are processing inputs, not reading material. |
| X0R-1304 Travels in a reference profile | 1 | **1** | Unchanged. All scalars. |

**Revised stage 1: 5 points.** It ships a measurement, not a card, and it exists to steer
stage 3.

### What this does to the epic

The proposal's recommendation is stage 1 (8) + stage 3 (8), skip stage 2, gate 4 and 5.
This experiment does not change that shape, and it moves weight within it:

- **Stage 1 shrinks to 5** and loses its user-facing deliverable. If stage 3 is not going
  to be built, stage 1 on its own is now a weak proposition — "independently useful" was
  resting on X0R-1303, and X0R-1303 does not survive.
- **X0R-1308 (sidechain duck from the measured kick, 3 points) looks better than the
  proposal thought.** It is the card that consumes the best figure produced here. But it
  needs the control measurement, and the duck abstained on one of two tracks, so expect it
  to decline to act often — which is on-brief and should be designed in, not discovered.
- **Stage 2 (genre) is confirmed dead.** Nothing here wanted a label, and the two useful
  figures are both ones a label would have obscured.

### One recommendation before any of it is sprinted

Run **Experiment 2** first, not stage 1. The proposal already places it second and calls
its kill criterion the most informative available, and this experiment has made that
ordering stronger rather than weaker: stage 1's remaining value is now almost entirely as
a steering signal for stage 3, so whether stage 3 is reachable by loosening clamps is the
question that decides whether stage 1 is worth 5 points or zero. It costs a loop.

### And one thing to fix regardless

`find_hits`' `backtrack=True` is correct for drum replacement and wrong for measurement.
Whatever happens to this epic, any future card that reads hit *times* rather than
triggering on them needs a sample-accurate refinement pass. Worth a backlog line on its
own.

---

## Appendix — reproducing

Clips were cut to the densest 28-second window of each track, separated with
`htdemucs_6s` on CPU via `DemucsSeparator` in-process (about 50 s per clip), and measured
with `fingerprint.measure`. Nothing was written to `storage/` and the API was not used.
The harness lives in the session scratchpad and is deliberately not committed; `measure`
takes a mix path and a `{StemKind: Path}` dict and is the whole entry point.
