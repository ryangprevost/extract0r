# Experiment 2 — is "remix" reachable by turning the existing dials up?

Run 2026-10-02 against [PR0DUCER.md](PR0DUCER.md) §7 and
[EXPERIMENT-1-RESULTS.md](EXPERIMENT-1-RESULTS.md). Throwaway experiment, not a card.
Nothing in `app/` was modified and nothing was written to `storage/`.

**Six bounces are here:**
`C:\Users\rprevost\Downloads\extract0r-experiment-2`
— with the unprocessed source, the reference clip, two extra diagnostic bounces and a
`README.txt` that says what to listen for. **The subjective half is Ryan's and this
document does not pre-empt it.**

---

## Result in one line

**Turning the existing dials up closes about a third of the tonal gap and none of the
rhythmic one — but the dial this experiment was told to turn is not the one holding the
result back.** `match_strength` 0.4 → 1.0 buys 0.56 dB of mean spectral distance, under
half the 1.2 dB this codebase already calls a meaningful gap. Doubling the *clamps*
behind it buys 1.07 dB more, and removing them buys 2.15 dB. So the literal kill
criterion fails, and it fails in a way that **re-points stage 3 at one of its three cards
rather than killing the stage**.

---

## 1. What was run, and one correction to the brief

| | |
|---|---|
| Source | `02OhFreakSomeMore.mp3`, densest 28 s (45–73 s) |
| Reference | `MSTRKRFT — Bounce feat. N.O.R.E + ISIS`, densest 28 s (36–64 s) |
| Why this pair | It is the pair the code already argues about. `CLOSE_FRACTION`'s comment in `suggest.py` and `max_tilt_db`'s in `dsp.py` both cite "a bass-heavy electronic mix against MSTRKRFT's *Bounce*" as the case that produced "super hollow with no bass". The clip window is the same 36–64 s Experiment 1 used. |
| Separation | `htdemucs_6s`, CPU, in process. ~25 s per clip. |
| Drum kit | `punchy`, kick + snare, identical in all six |
| Varied | `match_strength` ∈ {0.4, 0.8, 1.0} × `drum_blend` ∈ {0.3, 0.9} |

### The correction, and it matters for how the kill criterion reads

The proposal's Experiment 2 says to vary **`CLOSE_FRACTION` 0.4 / 0.8 / 1.0**. The brief
for this run operationalised that as **`match_strength`**, which is the field on
`MasterRequest`. They are not the same control and the difference turns out to be the
whole finding:

- `CLOSE_FRACTION` lives in `suggest.py` and scales *suggested dial values* the user may
  accept. A pipeline run does not read it.
- `match_strength` becomes `MatchSettings.strength`, and in `matching_curve` it is applied
  at the **last** line — `db *= clip(strength, 0, 1)` — **after** `max_boost_db`,
  `max_cut_db`, `max_low_cut_db` and `max_tilt_db` have already clamped the curve. It
  scales an already-clamped move, and it is clipped at 1.0, so 1.0 is not "more", it is
  "all of what is permitted".

Measured on the bus stage of these bounces:

| `match_strength` | curve tilt applied | at a per-band clamp | `max_tilt_db` |
|---|---|---|---|
| 0.4 | 2.40 dB | 0% of points | 6.0 |
| 0.8 | 4.80 dB | 0% of points | 6.0 |
| 1.0 | **6.00 dB** | 0% of points | 6.0 |

The clamped curve sits **exactly on `max_tilt_db`**, and 2.40 / 4.80 are that same curve
scaled. The unclamped ask between these two records is **19.59 dB of tilt** (−15.77 to
+3.82). So the shipped engine is permitted to make 31% of the move the measurement asks
for, and `match_strength=1.0` means "make all 31%".

**Three other things do not move with the dial at all**, which bounds what the experiment
could ever have shown:

- **Per-stem levels.** `match_stem` applies `reference.relative_lufs - source.relative_lufs`
  clamped to `MAX_STEM_GAIN_DB` and **never multiplied by strength**. Identical in all six
  bounces: vocals +1.04, drums +0.85, **bass −5.22**, guitar +9.00 (capped from +37.0),
  other −2.10, piano +0.71. The single most audible difference between the source and any
  bounce — the bass coming down 5.2 dB — is not under the control being tested.
- **Per-stem width**, same reason, give or take 0.1.
- **Bus loudness normalisation**, which is why all six land within 0.18 dB of each other.

---

## 2. The six, measured

Spectral distance is `spectrum_view.difference()` against the reference: level-matched to
0 LUFS, third-octave smoothed, 160 points over 20 Hz–16 kHz — the band and the smoothing
the correction engine itself works in. **Mean |gap|** is the mean absolute per-point
distance. Per-band columns are the same figure inside `suggest.BANDS`.

| Bounce | mean \|gap\| dB | gap closed | low 20–250 | body 250–800 | mid 0.8–2.5k | presence 2.5–8k | air 8–16k | LUFS | DR dB | crest dB |
|---|---|---|---|---|---|---|---|---|---|---|
| **source, unprocessed** | **5.73** | — | 4.36 | 4.55 | 3.93 | **10.19** | 8.03 | −9.07 | 2.31 | 10.79 |
| strength 0.4 / blend 0.3 | 4.29 | 25.1% | 4.41 | 3.72 | 3.06 | 6.11 | 3.84 | −8.04 | 3.30 | 8.42 |
| strength 0.4 / blend 0.9 | 4.20 | 26.7% | 4.14 | 4.16 | 3.39 | 6.12 | 2.63 | −8.14 | 5.06 | 8.54 |
| strength 0.8 / blend 0.3 | 3.85 | 32.8% | 4.22 | 3.19 | 3.04 | 4.64 | 3.62 | −7.98 | 3.30 | 8.55 |
| strength 0.8 / blend 0.9 | 3.87 | 32.5% | 4.04 | 3.59 | 3.29 | 4.97 | 3.00 | −8.11 | 4.97 | 8.65 |
| strength 1.0 / blend 0.3 | **3.68** | **35.8%** | 4.16 | 3.06 | 3.05 | 3.98 | 3.47 | −7.96 | 3.31 | 8.64 |
| strength 1.0 / blend 0.9 | 3.73 | 34.9% | 3.99 | 3.36 | 3.22 | 4.46 | 3.19 | −8.10 | 4.98 | 8.72 |
| *diagnostic:* clamps ×2 | *2.66* | *53.6%* | *3.07* | *2.26* | *2.18* | *2.64* | *2.67* | *−7.90* | *4.88* | *9.46* |
| *diagnostic:* no clamps | *1.58* | *72.4%* | *1.43* | *1.49* | *1.44* | *1.94* | *1.95* | *−7.96* | *4.54* | *10.63* |
| **reference** | 0 | — | — | — | — | — | — | **−5.90** | **2.19** | **9.11** |

The two italic rows are **not settings that exist**. They are the bus match re-run on the
1.0/0.9 mix with `MatchSettings`' clamps widened — ×2 on every clamp, then effectively
off. `MatchSettings` is a dataclass and `SpectralMatchEngine` takes one, so this needed no
source change. They are in the listening folder as `zz_diagnostic_*.mp3` because the
numbers alone cannot tell anyone whether 72% closure sounds like the reference or like the
"super hollow" master that lowered `CLOSE_FRACTION` in the first place.

### What the table says

1. **The strength sweep is worth 0.61 dB.** 0.4/0.3 → 1.0/0.3 moves the mean gap from 4.29
   to 3.68. Against the 5.73 dB baseline that is 10.6 percentage points of closure, on top
   of the 25.1 the weakest setting already achieved.
2. **The clamps are worth three and a half times that.** 1.0/0.9 → ×2 clamps is 1.07 dB;
   → no clamps is 2.15 dB. Everything the strength dial can reach, the clamps were already
   holding back by more.
3. **It is all in the top half.** Presence closes 10.19 → 3.98 (61%) and air 8.03 → 3.47
   (57%). The **low band does not close at all**: 4.36 → 3.99 at best, 8%, because
   `max_low_cut_db` is 1.0 dB below 220 Hz by design and this source is bass-heavy by
   2.8 dB there. "Processing gets you tone" is itself uneven — it gets you the top.
4. **`drum_blend` is not a tone control.** 0.3 → 0.9 moves the mean gap by at most 0.09 dB
   at any strength — inside the noise. It does one real thing, in §4.

---

## 3. The rhythmic figures do not move, and the proof is that the movement is quantised

Experiment 1 kept two figures: **hat placement** and **whether the bass plays through the
kick**. The brief's expectation was that neither can move, because no control in the
pipeline changes when a hat lands. **Confirmed, and more cleanly than expected.**

Measured first the way `fingerprint.measure` does it — each file against its own
re-estimated grid — the hat offbeat share looked like it moved a great deal: 26.8% on the
source against 39.8–41.8% on the bounces. **That reading is an artefact**, and it is worth
recording because stage 1 would ship it. The source clip's own `choose_tempo` picks
**64.98 BPM** — half time, the exact failure Experiment 1 documented — so its "offbeat
eighth" is the real beat. The six bounces each re-estimated somewhere between 129.16 and
129.94 BPM, all different, all at grid confidence 0.60–0.67 against the reference's 0.918.
Comparing figures read off seven different rulers measures the rulers.

Re-measured against **one** ruler — least-squares fitted to the source's own kicks and
snares at the correct octave, 129.95 BPM, valid for all seven files because
`preserve_source` keeps every bounce on the original's sample timeline:

| | hats found | offbeat share | swing | hat-pattern distance to ref | median hat offset vs source |
|---|---|---|---|---|---|
| **reference** | 69 | **58.0%** | **0.459** | 0 | — |
| source, unprocessed | 82 | 39.0% | 0.492 | 0.980 | 0.00 ms |
| strength 0.4 / blend 0.3 | 82 | 40.2% | 0.495 | 0.955 | 5.81 ms |
| strength 0.4 / blend 0.9 | 80 | 42.5% | 0.508 | 0.915 | 11.61 ms |
| strength 0.8 / blend 0.3 | 83 | 39.8% | 0.495 | 0.963 | 5.81 ms |
| strength 0.8 / blend 0.9 | 79 | 41.8% | 0.508 | **0.907** | 11.61 ms |
| strength 1.0 / blend 0.3 | 82 | 40.2% | 0.495 | 0.955 | 5.81 ms |
| strength 1.0 / blend 0.9 | 80 | 41.2% | 0.503 | 0.915 | 5.81 ms |

*Hat-pattern distance is the L1 distance between the two sixteenth-position histograms,
each normalised to sum to 1. Zero is an identical pattern, 2 is disjoint.*

**The hats did not move.** The median offset of every bounce's hats from the source's is
**0, 5.81 or 11.61 ms** — and 256/44100 = **5.805 ms**, one hop of the STFT `find_hits`
runs. Every "movement" in the table is exactly one or two detector frames. A process that
actually shifted a hat would produce a number that is not an integer multiple of the
detector's frame.

The rest follows:

- **Offbeat share** moves 39.0 → 42.5 at its furthest against a 19-point gap to the
  reference: **18% of the gap, at the weakest strength setting**, and it is not monotonic
  in `match_strength` at all — 1.0/0.3 gives exactly the same 40.2% as 0.4/0.3. What
  variation exists tracks `drum_blend`, because a layered kick and snare change which
  onsets the detector is willing to call a hat.
- **Swing** moves 0.492 → 0.503–0.508, i.e. **away** from the reference's 0.459, by at most
  0.016 against a 0.033 gap.
- **The hat pattern itself is untouched.** The reference puts its hats on the offbeat eighth
  and leaves the downbeat nearly empty (`[3,1,15,0 · 6,1,14,0 · 0,13,1,0 · 5,0,10,0]`). The
  source is downbeat-dominant (`[16,0,7,0 · 12,0,8,0 · 12,0,8,0 · 10,0,9,0]`) and every
  bounce still is (`[11,0,9,0 · 13,0,8,0 · 10,0,7,0 · 13,0,9,0]` at 1.0/0.9). The pattern
  distance improves 0.980 → 0.907, **7.4%**, all of it from hit-count noise.
- **Kick placement.** Both records are four-on-the-floor and every bounce stays so. What
  `drum_blend` 0.9 does is make existing kicks easier to detect — 20–25 found at 0.3 against
  29–31 at 0.9 — at **zero new grid positions**. The layer reinforces; it does not place.
- **The duck.** `excess_db` abstains on the source (confidence 0.002) and on five of six
  bounces (confidence 0.000–0.147, caveat "the per-kick dips vary by 8–11 dB, more than one
  compressor would produce"). It is a figure that refuses to resolve at this clip length,
  and there is no sidechain in the pipeline for any control to drive, so nothing here could
  have moved it. The apparent 14.5 → 21.0 dB spread across bounces is re-separation noise on
  a figure that already declined to be read.

**So: processing gets you tone, never groove.** That is the most likely outcome the brief
named, and it is now a measured one rather than an expectation.

---

## 4. Loudness and dynamics: "closer" is not "louder", and one control moves the wrong way

The spectral measure is normalised to 0 LUFS per curve, so it cannot be gamed by level.
Independently:

- All six bounces land between **−8.14 and −7.96 LUFS**, a 0.18 dB spread. The source is
  −9.07 and the reference −5.90. Every bounce is ~1 dB louder than the source and ~2.1 dB
  quieter than the reference, and **none of the ranking in §2 is a loudness effect**.
- **Crest** improves and then overshoots: source 10.79, reference 9.11, bounces 8.42–8.72.
  All six are now *sharper-transient* than the reference by ~0.5 dB.
- **Dynamic range is the one place `drum_blend` does something measurable, and it is the
  wrong direction.** Reference 2.19 dB, source 2.31. Blend 0.3 → 3.30; **blend 0.9 → ~5.0**.
  Laying synthesised kick and snare over the stem adds transient peaks the R128-style window
  reads as range. The source started **0.12 dB** from the reference's dynamic range; the
  blend-0.9 bounces end **2.8 dB** from it. A listener may well prefer it; it is not
  "closer to that record" by this measurement, and nothing in the UI would currently say so.

---

## 5. The kill criterion, decided

> If the 1.0/0.9 bounce isn't meaningfully closer to the reference's genre than 0.4/0.3,
> then "remix" is not reachable by loosening clamps.

### Where "meaningfully" sits

The codebase already writes down a threshold for this exact kind of quantity.
`suggest.MEANINGFUL_GAP_DB = 1.2` — *"below this a gap is inside the noise of the
measurement and not worth a dial move"*. It is defined per band rather than as a mean
across the axis, so using it here is an analogy and not an identity; it is also the only
number in the project with a written claim about when a tonal difference is worth acting
on, and inventing a different one for this experiment would be worse.

**Threshold: a change of 1.2 dB in mean |gap|.** Below it, the project's own position is
that the difference is not worth a control.

### The verdict

| Comparison | Δ mean \|gap\| | Verdict |
|---|---|---|
| 1.0/0.9 vs 0.4/0.3 | **0.56 dB** | **fails** — 47% of the threshold |
| 1.0/0.3 vs 0.4/0.3 (best vs weakest, blend held) | 0.61 dB | fails — 51% |
| any bounce vs the unprocessed source | 1.44–2.05 dB | **passes** — matching at *any* strength is worth having |
| 1.0/0.9 vs clamps ×2 | 1.07 dB | borderline — 89% |
| 1.0/0.9 vs clamps off | 2.15 dB | **passes** — 179% |
| rhythmic: any bounce vs source | 7.4% of hat-pattern distance, all of it detector noise | **fails outright** |

**The criterion fails as written.** The 1.0/0.9 bounce is not meaningfully closer to the
reference than 0.4/0.3, by the project's own yardstick, and it is not closer at all in the
dimension — groove — that the word "genre" is mostly doing work for.

**And the criterion's conclusion does not follow, because the dial it was applied to is not
the clamps.** The proposal wrote the criterion about `CLOSE_FRACTION` and the clamp
constants; this run varied `match_strength`, which scales an already-clamped curve. The
clamps still hold back two-thirds of the measured ask (6 dB of tilt permitted against
19.6 dB asked), and widening them moves the result by more than the entire strength sweep
does. "Loosening what already exists" has not actually been tested at full extent by the
six bounces — it has been tested by the two diagnostic rows, and **there it passes.**

So the honest reading is three-part:

1. **Loosening the strength dial is spent.** It is already at its ceiling at 1.0 and the
   ceiling is cheap. Nothing is gained by exposing it.
2. **Loosening the clamps is not spent, and is the only measured headroom in the processing
   half.** ×2 clamps closes 54% of the tonal gap against 36%.
3. **Neither reaches groove, at any setting.** Rhythmic figures move by less than the
   detector's own frame. Anything that is about where a hat lands requires regeneration,
   and regeneration is gated on X0R-306, which has never been run.

---

## 6. Recommendation

I **partly disagree with the proposal and partly with Experiment 1**, in both directions.

### Stage 3 — build it, but it is one card, not three

| Card | Proposal | Mine | Why |
|---|---|---|---|
| X0R-1306 · A strength budget instead of a constant | 3 | **3 — build first** | This is the only card with measured headroom: 1.07 dB at ×2 clamps against 0.56 dB for the whole strength sweep. But it must be **the clamps**, not `match_strength`. A budget slider wired to `match_strength` would ship a control that cannot do anything, and that is the obvious way to build this card wrong. |
| X0R-1307 · Suggestions the fingerprint makes possible | 2 | **2** | Unchanged, and it gains a reason: the figures it reports — hat placement, pattern shape — are now *proven* to be ones no control can act on, so reporting them is the only honest thing available. It should say so. |
| X0R-1308 · Sidechain duck from the measured kick | 3 | **3, but expect it to decline** | Still the only card that adds a process the pipeline lacks. But its input figure abstained on six of seven files measured here and on one of two in Experiment 1. Design the abstention in as the common path, not the edge case. |

The honest sales line for stage 3 is **"produce my song more like this record, tonally"**.
At the shipped ceiling it delivers 36% of the tonal gap and 0% of the rhythmic one; with
the budget card, around 54%. That is a real and useful product. It is not what anyone
reading the word "remix" expects, which is the proposal's own §2 argument arriving with a
number attached.

### Stage 1 — 5 points, and conditional on stage 3 in a stronger sense than Experiment 1 said

Experiment 1 cut X0R-1303 and left stage 1 resting entirely on being a steering signal for
stage 3. This experiment tightens that: of the two figures Experiment 1 kept,

- **hat placement feeds X0R-1307 only** — an observation, because no control can act on it,
  as §3 now demonstrates;
- **the duck feeds X0R-1308** — and it abstains most of the time.

So **stage 1 is worth building if and only if X0R-1307 and X0R-1308 are sprinted.** Built
alone it computes numbers that nothing reads. Build stage 3 first and let it pull the
measurements it needs; that inverts the proposal's ordering (§9 items 3 and 4) and I think
the inversion is right.

One thing stage 1 **must** carry regardless, found here: `grid_from_drums` and `refine_grid`
exist and are necessary, and this run shows they are not sufficient. The source clip's grid
came back at **half time** and the six bounces re-estimated six different tempos spanning
0.8 BPM at confidences of 0.60–0.67. Any figure compared *between* two files must be read
against **one** grid, or the comparison measures the grid. That is a design constraint on
X0R-1301's card text and it is not in it.

### Unchanged

- **Stage 2 (genre): still dead.** Nothing here wanted a label.
- **Stages 4 and 5: still gated on X0R-306.** This experiment is the positive case for that
  gate rather than the negative one — if groove is unreachable by processing and groove is
  what "in that style" mostly means, then X0R-306 is the card that decides whether the epic
  has a second half at all. It should be run before stage 4 is scoped, not before it is
  built.
- **Do not call it a remix.** Measured: tone moves by a third, groove by nothing.

---

## 7. What I could not measure, and what is wrong that I did not fix

**Could not measure.**

- **Whether any of this sounds closer.** That is the half of the kill criterion that is
  Ryan's, and the six files plus two diagnostics are in the folder for exactly that. The
  precedent is live: `CLOSE_FRACTION` went from 0.7 to 0.4 because a master that closed
  *more* of the measured gap was described as "super hollow with no bass". A 72%-closed
  diagnostic bounce is a plausible repeat of that, and the numbers cannot tell.
- **Whether 28 seconds generalises.** One section of one pair. The spectral figures are
  long-term averages and should be stable; the rhythmic ones come from 69–83 hat events.
- **The per-stem clamps' headroom.** The two diagnostic rows widen the **bus** clamps only.
  `MAX_STEM_GAIN_DB`, `WIDTH_LIMITS` and the per-stem tone clamps were left alone, so
  1.58 dB is an upper bound on the gap that a bus-only budget could leave, not the floor
  for stage 3 as a whole. A full budget card would reach somewhat further.
- **Anything about a live-drummed reference.** Same library limitation Experiment 1 hit.

**Wrong, and left alone deliberately — no source file was edited.**

1. **An absent stem is matched to the reference's separation residue.** The source has no
   guitar (−59.73 LU, `present=False`); *Bounce* has no guitar either, but its guitar stem
   is residue at −22.74 LU, which clears the −30 LU threshold and so `has_counterpart`
   returns true. Every one of the six bounces therefore contains `wanted +37.0 dB, capped at
   +9.0 dB` on the source's guitar. At −50.7 LU the result is inaudible and nothing here is
   invalidated by it — but the mechanism is not bounded by the levels involved, and a source
   with a quiet real guitar against a reference's residue would get an audible 9 dB lift of
   the wrong thing. This is Experiment 1's "−30 LU presence threshold is wrong for the census"
   finding showing up in the **processing** path rather than the reporting one, which is
   worse. Suggested fix: `match_stem` should decline when the *source* stem is absent, the
   same way it already declines when the reference's is. Worth a backlog line on its own
   merits, independent of this epic.
2. **`find_hits(backtrack=True)` remains wrong for measurement**, as Experiment 1 said. §3
   leans on it only through differences that turned out to be exact multiples of its frame,
   which is what makes them readable as artefact.
3. **A budget card wired to `match_strength` would be a no-op control.** Recorded here
   because the field is named as if it were the budget and the pipeline plumbs it through
   from the API, so it is the obvious thing to reach for.

---

## Appendix — reproducing

Clips cut to the densest 28 s window by one-second RMS, separated with `htdemucs_6s` on CPU
in process, six `pipeline.run` calls driven directly with different `MasterRequest`s (no API,
no Studio, nothing written to `storage/`). Spectral figures from
`mastering.spectrum_view.measure` / `.difference`; loudness from
`mastering.loudness_meter.integrated_loudness`; dynamics from `mastering.dynamics`; rhythmic
figures from `analysis.fingerprint`, once through `measure()` and once against a single
shared `BeatGrid` built with `refine_grid`. Each bounce was re-separated to fingerprint it
(~25 s each). The two diagnostic rows construct a `MatchSettings` with widened clamps and
call `SpectralMatchEngine.match` on the 1.0/0.9 bounce's `mix.wav`. The harness lives in the
session scratchpad and is deliberately not committed; total runtime about twelve minutes.
