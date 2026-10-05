# Proposal — pr0ducer

> **Named `pr0ducer`, not `remix0r`.** Ryan asked for the rename and this
> document's own research is the reason: the thing that literally does "remix the
> source in that style" is Suno's Cover feature, it ships today, and it replaces
> your recording with a new one. Every remix framing invites that comparison, which
> this loses on every axis except the ones that are actually its advantages — your
> performance, kept, re-produced, with every move still carrying its measurement.
> The verb in the UI is **re-produce**.


> ## Re-scoped 2026-10-02, after X0R-414 shipped
>
> **Status: partly sprinted.** [sprints/SPRINT-2.md](../sprints/SPRINT-2.md) takes 12
> points of this epic. The sprint leads with a card **this document does not contain** —
> per-drum comparison, *your kick against their kick* — and that is the largest thing the
> proposal got wrong.
>
> **The ordering is Ryan's call, not a new finding.** Given the choice between per-drum
> comparison and drum re-production he said: *"do the per-drum comparison, that sounds more
> valuable."* That is also what this re-scope recommended, so nothing below is a reversal —
> but the decision is his and is recorded as his. Drum re-production is **not cancelled**:
> it is ungated, re-scoped to 6 points, and sitting in EPIC-13 with what was learned on it.
>
> What changed and what it cost this document, in order of how much:
>
> 1. **Stage 3B is new, and it leads.** X0R-414 returns kick, snare, cymbals and toms as
>    audio, so the per-instrument comparison can go one level in. The proposal only ever
>    imagined the new audio being used to *trigger samples*. It is worth more as something
>    to *measure*. → new §6 Stage 3B, and **X0R-1314 / X0R-1315 / X0R-1317 / X0R-1316**.
> 2. **Stage 4's X0R-306 gate is retracted.** It was a gate on *classification* — drum
>    identity came from a band-rise classifier nobody had measured. Identity and onsets now
>    come from separation: zero ambiguous strokes on the measured clip, against three from
>    the classifier. Nothing on that path classifies anything.
> 3. **Stage 4 is re-scoped from 7 points to 6, and part of it is retracted.** X0R-1310's
>    "ride, crash, clap, rimshot" cannot be built from a single cymbals stem, and a noise
>    burst is not a crash — the proposal's own synthesised-guitar argument. X0R-1311 is now
>    buildable and still deliberately out.
> 4. **"Stage 4 is the cheap, exciting core" is tested and refused.** Cheap, yes. The core,
>    no: Experiment 2 measured drum layering at ≤0.09 dB of the tonal gap, zero new grid
>    positions, and dynamic range moving *away* from the reference. The honest sales line
>    for drum re-production is **"your drums, re-kitted, same groove"** — different drums,
>    not produced like that record. See SPRINT-2 §1.
> 5. **Stage 1 slips again**, for a new reason: per-drum comparison reads none of it.
>
> Everything not marked below stands as written. The two experiments'
> findings — [1](EXPERIMENT-1-RESULTS.md), [2](EXPERIMENT-2-RESULTS.md) — are unchanged by
> X0R-414: processing gets you tone, never groove.
>
> **And then §10, added later the same day**, on Ryan's request for Melodyne-like
> comparisons. It carries a probe of its own and one finding that reaches back into stage 1:
> on the two live-drummed records tested, **the grid is wrong** — 66.30 BPM against ~132.7,
> metre 3/4 on a 4/4 record, and a constant-tempo fit leaving drum hits a median 23–30 ms
> from their own best-fit sixteenth against 5.7 ms on the programmed control. X0R-1301 and
> X0R-1307 inherit that; see §10.4(a).

**Original status line, kept for the record: proposal. Nothing here is in
[BACKLOG.md](../BACKLOG.md) and nothing is sprinted.**
The first question is not how to build this, it is whether to.

Written 2026-10-01 in response to:

> "i'd also like for you to brainstorm a pr0ducer mode. one that will take a source track and
> reference track and determine the genre of the reference and remix the source in that
> similar style. this will require different sample patches for synth, guitar, drums, etc."

**Recommendation in one line.** Build the measurement half (8 points) and the processing
half (8 points). Do not build the genre classifier. Treat the regeneration half as
conditional on a benchmark that does not exist yet, and be willing to cancel it. And do not
call the result a remix — call it a re-production, because the thing that actually does what
"remix in that style" promises is Suno's Cover feature, it shipped, and this tool cannot and
should not try to beat it.

---

## 1. There are four products in that sentence

"Remix the source in that style" is doing a lot of work. Four distinguishable products fit
the words, they cost wildly different amounts, and three of them are not what the rest of
extract0r is.

### (a) A more aggressive mastering match

Take the existing whole-mix and per-instrument comparison and turn the clamps up. Nothing
new is built; `CLOSE_FRACTION`, `MAX_LEVEL_DB`, `MAX_BAND_DB` and `WIDTH_LIMITS` stop being
constants and become a budget the user sets.

Already ~95% built. See
[`suggest.py`](../../services/api/app/services/mastering/suggest.py) and
[`instrument.py`](../../services/api/app/services/mastering/instrument.py).

### (b) A production restyle — every note the source played, produced differently

Keep the performance exactly as recorded. Change how it sounds: per-stem tone, dynamics,
width, space, drum layering, sidechain ducking. This is what the research literature calls
*mixing style transfer*, and it is the category extract0r is already in — the drum kit in
[`drums/kit.py`](../../services/api/app/services/drums/kit.py) is a working instance of it.

Mostly built. The gaps are a sidechain ducker, a few more drum voices, and a reason to pick
the settings.

### (c) A re-sequence — same sounds, different rhythm and arrangement

Quantise the source onto a new grid, impose a genre-typical drum pattern, add or remove
hits, change the tempo, swing what was straight.

Not built, and mostly not measurable. "The reference's kick lands on every beat and yours
lands on 1 and 3" is a measurement. "Therefore your kick should land on every beat" is a
compositional decision about someone else's song. This is where the project would start
inventing.

### (d) A regeneration — transcribe the source, throw the audio away, re-perform the notes with patches

This is what the words "different sample patches for synth, guitar, drums" literally
describe. Separate six ways, transcribe each stem to notes, and play those notes back
through a synth voice chosen to suit the reference's style.

Technically the most interesting, and the one with the worst risk profile in this codebase —
section 4 is about why.

### What I think he means, and what is worth building

**He means (d), with (b)'s quality expectation.** "Different sample patches for synth,
guitar, drums" is a sentence about re-performance, not about EQ. Nobody describes a shelf
filter as a patch.

**What is worth building is (b), plus a strictly bounded slice of (d), plus a measurement
layer that is more useful than the genre label he asked for.** (a) is a parameter change
that takes three days and should be done regardless. (c) should not be built at all. (d)
should be attempted for drums and bass only, after a benchmark, and never for guitar or
vocals.

---

## 2. The tension with "nudge, not carbon copy" — a position, not a hedge

The brief governing this product is a nudge toward a reference, never a copy of it. pr0ducer
is the most transformative thing anyone has proposed for it. That tension is real and it is
not resolved by labelling the mode carefully.

**The clamps are not a stylistic preference. They are measurements.** This matters, because
it means the brief is not an aesthetic that can be set aside for one mode:

- [X0R-1113](../BACKLOG.md) measured it: halving each gap cut drift from the user's own mix
  from 4.98 dB to 2.55 dB *while landing closer to the reference* than the unclamped
  behaviour (2.85 vs 3.20 dB). Taking less of the gap produced a better result by both
  measures at once.
- `CLOSE_FRACTION` in `suggest.py` went from 0.7 to 0.4 because 0.7 against a real pair
  produced a master its author described as "super hollow with no bass".
- `MAX_LEVEL_DB` in `instrument.py` went from 9 dB to 3 dB with the reason written in the
  comment: 9 dB "is not a correction, it is a different mix".

And then the part that makes the tension structural rather than incidental:

```python
#: Past this, a level difference between the same instrument on two records is much more
#: likely to be a difference of arrangement ...
LIKELY_ARRANGEMENT_DB = 6.0
```

**The code already detects arrangement-scale differences and refuses to offer them.** It
reports them, flags them, and tells the user to hear both sides first. pr0ducer is precisely
the mode that would act on the differences this constant exists to decline.

### The position

**pr0ducer is a second product sharing a codebase, and it should be scoped down until the
overlap with the first product is the whole of it.**

The brief's enemy is an *unasked-for* transformation — a tool that quietly turns Ryan's
record into someone else's while claiming to help. It is not drasticness as such. A mode the
user deliberately enters, with a named control whose units are stated and an A/B that is
always one click away, is a different question being asked, not a violation.

But it only earns that status if it keeps the two things that make this product what it is:

1. **Every move still says what was measured, what is being asked for, and why.** A "remix
   in that style" button whose output nobody can account for is off-brief no matter what the
   mode is called. This is the non-negotiable one.
2. **The original is always there.** Not a bypass toggle buried in a group — the unprocessed
   source as a first-class thing to return to.

So the shape is: **the same comparison engine with the clamps exposed as a budget, a
measured fingerprint in place of a genre label, and bounded re-performance on drums and bass
only.** Everything past that line — regenerating guitar, rewriting patterns, changing tempo,
inventing parts — is out, not because it is hard, but because it is the other product.

### And a naming argument that is really a product argument

**Do not call it pr0ducer in the UI.** Call it what it does: re-produce, or restyle.

A remix changes the arrangement. This changes the production. If the button says "remix in
the style of this reference", every user — including Ryan in six months — measures the result
against [Suno's Cover feature](https://suno.com/blog/audio-inputs), which takes arbitrary
audio and re-renders it in a new style while preserving the melody, ships today, and is a
large generative model in the cloud. extract0r will lose that comparison every time.

If the button says "produce my song more like this record, and show me every change", it
competes with nothing, and the things it does that Suno cannot — explain itself, keep the
actual recording, run with nothing leaving the machine — become the point rather than
excuses.

`pr0ducer` is a fine internal name for the epic. It is a promise the UI cannot keep.

---

## 3. The honest version of genre detection

Short answer: **do not detect genre. Measure the reference and describe it.** The
description is more useful than the label, and unlike the label it can be checked.

### What is measurable, and where it already is

| Property | Status | Where |
|---|---|---|
| Tempo, with the octave resolved | **built** | `domain/timing.py` — `choose_tempo`, scored by F-measure against onsets; 5 of 6 click tempos correct |
| Metre / beats per bar | **built** | `detect_beats_per_bar` — returns 4/4 at *zero* confidence when there is no accent |
| Key and mode | **built** | `estimate_key`, Krumhansl-Schmuckler, no training data |
| Spectral balance, five bands | **built** | `instrument.BANDS`, `suggest.BANDS` |
| Per-stem level relative to its own mix | **built** | `instrument.snapshot` → `relative_lufs` |
| Dynamic range and crest, per stem | **built** | `dynamics.dynamic_range_db`, `crest_db` |
| Stereo width, per band | **built** | `width.width_profile` |
| Kick / snare / hat times and strengths | **built** | `drums/detect.find_hits` |
| **Instrumentation present** | free, unbuilt | energy per stem after a six-way split; a stem near silence means the instrument is not on the record |
| **Onset density per stem per bar** | free, unbuilt | librosa onsets ÷ the bar grid that already exists |
| **Kick/snare positions against the beat grid** | free, unbuilt | `find_hits` times + `TimingEstimate.first_beat_s` and `tempo_bpm`. "Four on the floor" is literally *a kick on every beat* — a count, not an opinion |
| **Swing ratio** | cheap, unbuilt | where off-beat onsets actually fall between consecutive beats, against the straight 50% |
| **Programmed vs played drums** | cheap, unbuilt | timing variance of hits around the grid. A drummer scatters; a sequencer does not |
| **Bass ducked to the kick** | cheap, unbuilt | correlation of the bass stem's envelope against the kick times from `find_hits` |

That is eleven to thirteen properties, most of them already computed, several of them
genuinely diagnostic, and every one of them a number with a referent.

### What is not honestly measurable

**The genre label itself.** Genre is a social and commercial category, not an acoustic
property. Two records with identical measurements can sit in different genres and vice
versa. The standard evidence that this is not a solved measurement problem is
[Sturm's analysis of GTZAN](https://arxiv.org/abs/1306.1461), the most-used genre benchmark
in the field: it contains repeated tracks, cover versions, digital clipping and skips, and
two classes of mislabelling. His conclusion is the relevant one here — results across papers
using the *same* data are not comparable, and the ceiling on reported accuracy is partly the
labels being wrong.

The modern alternatives do not fix this, they relocate it. Essentia's Discogs-400 model
classifies into 400 categories taken from a *record-marketplace taxonomy*. A score of 0.82
for "Electronic / House" is a well-calibrated statement about a Discogs field. It is not a
measurement of the audio, and the user will read it as one.

This is the same call the project already made about saturation, and the precedent is written
down in `instrument.py`: distortion has no dimension in the comparison because added
harmonics cannot be distinguished from played ones. Genre is a weaker case than saturation,
not a stronger one — saturation is at least a physical process.

**The project's own best precedent for how to behave here is X0R-407.** Metre detection was
rewritten mid-card because the first version reported 0.99 confidence on wrong answers.
It now returns 4/4 with zero confidence when the evidence is absent. *Confidently wrong is
worse than admitting ignorance* is already the house rule.

### What the UI should say

A fingerprint, in the sentence form the app already uses. Something like:

> **This reference, measured.** 128 BPM, 4/4, in F minor.
> Kick on all four beats of every bar (64 of 64 bars). Hats on the offbeats, swung 54% —
> near straight. Hit timing varies by 3 ms, which is programmed rather than played.
> No guitar and no piano on the record. Bass dips 4.2 dB within 30 ms of every kick, so it
> is ducked to the kick rather than just arranged around it.
> Dynamic range 5.1 dB against your 11.4. Mids sit 4 dB behind yours; air sits 3 dB ahead.
>
> *We are not naming a genre. Every line above is something measured in this file, and you
> can disagree with any of it. A genre label would be a guess at a marketing category, and
> it would not tell you what to change.*

**That last paragraph is the feature.** It is more useful than the word "house", it is
falsifiable, and it is the only version that is consistent with the rest of the product.

### If a classifier is built anyway

It is feasible, and the constraints are specific:

- **Essentia's Python bindings do not support Windows at all**, so the obvious route —
  `essentia-tensorflow` with the Discogs-400 or MTG-Jamendo models — is unavailable on
  Ryan's machine. That is not a preference, it is the platform.
- The viable route is ONNX. MTG publishes **ONNX versions of Discogs-EffNet and the
  MTG-Jamendo heads with dynamic batch size**, and `onnxruntime>=1.19` is *already* in
  [`requirements-ml.txt`](../../services/api/requirements-ml.txt) because basic-pitch is
  installed `--no-deps` and runs on it. The embedding model is ~16 MB. This fits local-first
  with no new runtime.
- Hard conditions if it ships: **top three with scores, never one label.** Downloaded on
  first use the way Demucs' weights are, not committed. Defeatable. And — the important one —
  **no processing decision may read the label.** The processing keys off the measurements.
  The label is decoration, and decoration that drives DSP is how a tool starts lying.

My recommendation is still not to build it. See section 7.

---

## 4. Instrument patches

### What a patch is here

Not a folder of WAVs. **A patch is a parameterised synthesis recipe plus a trigger policy** —
and the codebase already contains the reference implementation of exactly that:

```python
@dataclass(slots=True)
class Voice:
    """One drum's synthesis parameters."""
    length_s: float
    pitch_from: float = 0.0
    pitch_to: float = 0.0
    pitch_decay: float = 20.0
    ...
```

Three kits, three voices each, built from a swept oscillator and filtered noise. Eight
numbers per drum. A reviewer can read a patch and disagree with it.

### Synthesis versus samples — keep synthesis, and the drum kit already made the argument

From [`kit.py`](../../services/api/app/services/drums/kit.py):

> "shipping a library of recorded hits would mean shipping someone's recordings — with the
> licensing that implies, and with no way for anyone to check where they came from. These
> are built from oscillators and noise, so the kit weighs nothing, needs no licence, and
> cannot contain anyone else's record."

Four reasons to keep it, in order of weight:

1. **Licensing.** Ship nothing of anyone else's. Every alternative requires knowing the
   provenance and licence of every byte, forever.
2. **Consistency with the profile argument.** `profile.py` justifies reference profiles on
   the grounds that *measurements of a recording are facts about it* while its waveform is
   not ours to carry. Shipping recorded hits while making that argument about references
   would be incoherent.
3. **Install size.** The current install is two scripts and a documented MAX_PATH
   workaround. A sample library is the kind of thing that turns that into a download page.
4. **Auditability.** The kick tuning in `kit.py` was set against a measurement — real kicks
   average -2.25 dB of their energy in 20-60 Hz, the first versions were 5 to 9.5 dB short
   there, and all three kits now land within 0.1 dB. You cannot do that argument with a WAV.

**The counter-argument deserves airing, because it is strong where it applies.** A kick is a
swept sine plus a noise transient, and synthesis is genuinely competitive — arguably better,
since it is tunable. An electric guitar is a plucked string, a nonlinear amplifier, a cabinet
response and a player's hands. **A synthesised guitar patch will sound like a synth**, and
shipping one would be the first thing in this codebase that is worse than the alternative
rather than more honest than it.

So the conclusion is not "synthesis everywhere", it is **synthesise only where synthesis is
the real instrument**:

| Stem | Patch? | Why |
|---|---|---|
| Drums | **yes** | proven; three kits already ship and are tuned against measurements |
| Bass | **yes** | a mono synth bass is not an imitation of a bass, it *is* the instrument half the reference genres use |
| Piano / keys / pads | **yes, later** | same argument; a pad is a synthesis recipe |
| Guitar | **no** | synthesis cannot reach it. Process the recorded guitar instead |
| Vocals | **never** | not a patch question, and nothing good is downstream of it |

### A third option, borrowed from the sample-manager tools

[Algonaut Atlas](https://www.soundonsound.com/reviews/algonaut-atlas-2) and
[XLN XO](https://www.attackmagazine.com/reviews/gear-software/xln-audio-xo/) both solve a
version of this problem, and Atlas solves it the licensing-safe way: it ships essentially no
content and instead **classifies and maps the samples you already own**, clustering them by
instrument type and timbre so you can navigate your own library by ear. XO does both — ~8000
factory samples *and* indexing of your folders.

The Atlas pattern fits this project unusually well: it ships nothing, it is local-first by
construction, and it sidesteps the synthesis-quality ceiling entirely because the samples are
real ones Ryan licensed himself. The cost is that it only helps users who have a library, and
it needs a one-shot classifier (kick/snare/hat from an isolated hit — a much easier problem
than genre, and `detect.py` already does the band analysis it would need).

Worth keeping as a stage-6 option. Not worth doing before the synthesised path is exhausted.

### How a transcribed part becomes a re-performed one — and the weakest link

The chain is:

```
mix → Demucs htdemucs_6s → stem → pyin / basic_pitch → notes → patch → audio → layer
```

Five lossy stages before a note is sounded, and the error compounds. **The weakest link is
transcription accuracy, and the decisive fact is that nobody knows what it is.**

- [X0R-306](../BACKLOG.md) — "Separation and transcription quality benchmark" — is `TODO`, and
  its own card says it is "now the gating card for the whole transcription epic".
- X0R-405's criterion "a clean DI bass line transcribes with >= 90% note accuracy" is marked
  ⏳ *needs X0R-306's eval set*. It has never been measured.
- X0R-406's criterion "kick, snare, hi-hat separated with >= 80% F1" is marked the same way.
  Also never measured.
- The only end-to-end run on record ([ROADMAP.md](../ROADMAP.md), sprint 1) returned **a bass
  line an octave high and a tempo of 60 BPM against a true 120**. The cause was traced to
  feeding Demucs synthetic sine waves, and the lesson written down was that synthetic audio
  cannot measure quality. Which means the real number is still unknown in both directions.

**Why this is fatal for regeneration specifically, and survivable for processing.** The two
halves of this feature fail differently:

- An EQ move computed from a slightly wrong measurement is a slightly wrong EQ move. The
  error is proportional, inaudible at the margin, and bounded by the clamp.
- **A synth note at a wrong pitch is a wrong note.** Nothing about that is proportional. A
  listener identifies it instantly and without training, and a single octave error ruins a
  bar. Re-performance is a lossless amplifier of transcription error.

This reframes the drum kit's design choice. `kit.py` explains layering as a consequence of
not being able to separate drums from drums — true, but it is also *error tolerance*, and
that is the part that generalises. A mistriggered kick sitting under the real kick is a
slightly thickened kick. A regenerated bass line an octave high is garbage. **Layering is
what makes a wrong note survivable, and it is the only reason stage 5 below is proposable at
all.**

**Consequence for sequencing: X0R-306 is a hard prerequisite for any regeneration stage.**
Not a nice-to-have, not "should probably land first". If it comes back at 70% note F1,
stages 4 and 5 are cancelled, and that is a correct outcome rather than a failure.

---

## 5. What comparable tools actually do

The gap between what ships and what is a demo is the whole story here, so this is split that
way. (Ozone was covered in EPIC-12 and has nothing in this territory — its Stem EQ splits
four ways and offers EQ, no re-performance, no reference comparison per stem.)

### Ships and works

| Tool | What it does | What it does *not* do |
|---|---|---|
| **[Moises AI Studio / Stem Generation](https://moises.ai/newsroom/product-announcements/launch-ai-studio/)** | Separates up to 27 stem types. **Generates new instrument parts** conditioned on your audio plus a style direction given as an audio reference, a text prompt, or a genre preset. Infers tempo, beat grid, key and structure from your stems so new parts lock to them. Harmony-adherence control. | Does not restyle *your* performance — it adds generated parts alongside it. Cloud. Closest shipping thing to the brief, and it answers a different question: *play something new that fits*, not *re-produce what I played*. |
| **[Hit'n'Mix RipX DAW PRO](https://hitnmix.com/ripx-daw-pro/)** | The closest shipping thing to (d). Separates a mix to note-level objects, then lets you edit individual notes, **swap timbres**, clone pitch variation / timbre / panning from one note to another, and edit harmonics directly. | Manual, note by note. No genre analysis, no reference-driven automation, no "do this to the whole song". It is a surgical editor, not a mode. Proof that note-level restyling is possible *and* that the viable product shape is an editor rather than a button. |
| **[Suno Cover](https://suno.com/blog/audio-inputs) / Udio audio-to-audio** | Upload any audio — demo, voice memo, finished record — and re-render it in a new style, preserving the melody. Change genre, instrumentation, vocal character, production. | Cloud-only, generative, nothing explained, your recording is not in the output — a new recording of your tune is. **This is literally what "remix the source in that style" describes, and it already exists.** Reason to not claim that framing. |
| **[Algonaut Atlas 2](https://www.soundonsound.com/reviews/algonaut-atlas-2)** | Classifies and spatially maps **your own** drum library by instrument type and timbre; build kits by navigating a map. | Ships no restyling, no reference analysis, no genre. Valuable as a *licensing pattern*, not as a feature to match. |
| **[XLN XO](https://www.attackmagazine.com/reviews/gear-software/xln-audio-xo/)** | Same idea, plus ~8000 factory samples and a sequencer. | Same. The factory library is the thing this project deliberately will not ship. |
| **[Samplab](https://samplab.net/)** | Polyphonic audio → MIDI with note editing, then play the result through any soft-synth. The exact transcribe-and-re-perform workflow. | **Requires an internet connection — audio is uploaded to their server.** Free tier caps at 10 s and mono; 127 notes maximum per file. Degrades on dense mixes, distortion and long reverb tails. A commercial product with a paid team hits the same transcription wall described in section 4, and solves it by capping the input. |

### Research results — take seriously, do not plan around

- **[Music Mixing Style Transfer](https://arxiv.org/abs/2211.02247)** (Koo et al., ICASSP
  2023) — the closest academic work to extract0r's actual territory. A contrastively-trained
  encoder extracts *only effects-related* information from a reference and converts an input
  multitrack's mixing style to match. Code and a Hugging Face demo exist. Its own framing
  concedes the key limitation: **replicating a reference's audio effects is not the same as
  transferring a mixing style**, because style includes artistic decisions that are not
  effect parameters. It changes processing, never notes.
- **[DeepAFx-ST](https://csteinmetz1.github.io/DeepAFx-ST/)** (Steinmetz et al.) and
  **ST-ITO** (ISMIR 2024 best paper) — predict or search audio-effect parameters to match a
  reference's production style, with differentiable DSP and inference-time optimisation.
  Grounded in real effects, so interpretable. Again: processing only.
- **Diff-MST** (ISMIR 2024) and the 2025-26 follow-ups — same family, differentiable
  mixing-console style transfer from a reference.
- **Timbre transfer / DDSP** — the research line that would be needed for (d) done properly,
  and the one with the clearest unsolved limitation: **DDSP's harmonic synthesiser assumes
  one fundamental per time step, and its CREPE pitch encoder is monophonic, so the whole
  family is restricted to monophonic harmonic instruments.** 2025-26 work (PolyDDSP, AdaTT,
  diffusion-based inpainting) is actively trying to lift this; AdaTT is still monophonic and
  still does not preserve spatial cues. Polyphonic timbre transfer is not a shipping
  technology.

**The two findings that should change the plan.**

1. **Every serious effort in this space — academic and commercial — that produces usable
   results restyles the *processing* and leaves the notes alone.** The one shipping product
   that restyles notes (RipX) is a manual editor. The one that re-renders whole songs (Suno)
   replaces your recording with a new one. Nothing in between ships. That is extremely strong
   evidence about where the line is, and it is the same line `kit.py` drew by accident.
2. **The monophonic restriction in the timbre-transfer literature maps exactly onto the two
   stems proposed for regeneration below.** Drums and bass are where this is tractable.
   Guitar and piano are polyphonic, which is why they are excluded — not out of caution, but
   because the technique does not exist.

---

## 6. Work breakdown — EPIC-13 · pr0ducer (Phase 4)

Five stages. Each is independently useful, each could be the last one built, and the
numbering continues from EPIC-12 and X0R-12xx.

~~**34 points total**~~ **41 points total as re-scoped** (36 without the dead genre
stage) — stage 1 at 5 rather than 8
(Experiment 1), stage 3B's 12 added, stage 4 at 6 rather than 7 — plus X0R-306 (5), which is
already in the backlog and is a hard prerequisite for ~~stages 4 and~~ stage 5 only.

### Stage 0 — the prerequisite that already exists

**X0R-306 · Separation and transcription quality benchmark · 5 · `TODO`** — already written,
already gating the transcription epic by its own text. ~~Needed before stage 4 or 5~~
**Needed before stage 5 only**, not before stages 1–3, 3B or 4. Its result may cancel
~~stages 4 and~~ stage 5, and that is the point of running it.

*Updated 2026-10-02.* The stage 4 gate is retracted — it was a gate on classification, and
there is no classifier on that path any more. The card has, however, **gained** two items
and a reason to lead the next sprint: DrumSep's per-stem bleed (which the per-drum
comparison measures band energies through) and the band-rise classifier's F1 (which is what
a machine without the weights still runs, since `DRUMSEP_ENABLED` defaults off). Those two
numbers are what would retire `separate.QUIET_STROKE_DB` and the bleed caveat from being
judgements.

### Stage 1 — The reference fingerprint · 8 points

*Independently useful: it tells Ryan things about a reference the tool cannot currently tell
him, it ships no models and no audio, and it makes the existing comparison better on its own.
If the epic stops here it was still worth doing.*

| Card | Title | Pts |
|---|---|---|
| X0R-1301 | Rhythmic fingerprint of a reference | 3 |
| X0R-1302 | Instrumentation census and programmed-vs-played | 2 |
| X0R-1303 | The fingerprint card, with no genre word on it | 2 |
| X0R-1304 | The fingerprint travels in a reference profile | 1 |

**X0R-1301 · Rhythmic fingerprint of a reference · 3**
Kick, snare and hat times from `find_hits`, placed against the beat grid from
`TimingEstimate`. Reported as counts and percentages, never as adjectives: *kick on 64 of 64
downbeats and 61 of 64 backbeats*; *hats on 94% of offbeats*; *swing 54%*; *onset density per
bar per stem*. Zero confidence where the grid confidence is already below the X0R-407
threshold, rather than a number derived from a bad grid.

**X0R-1302 · Instrumentation census and programmed-vs-played · 2**
Which of the six stems carry real content, in dB relative to the mix, with a stated threshold
below which a stem is reported as absent. Plus hit-timing variance around the grid as a
programmed/played indicator, with the millisecond figure shown rather than the verdict alone.

**X0R-1303 · The fingerprint card, with no genre word on it · 2**
The UI. Sentence form, matching the existing instrument cards. Includes a short standing
explanation of *why* no genre is named — this is a user-facing statement of the project's
position, and it is the kind of thing that makes the tool trustworthy rather than coy.

**X0R-1304 · The fingerprint travels in a reference profile · 1**
Extend `ReferenceProfile`. It is all scalars, so the "a profile contains no audio and cannot
be played" argument in `profile.py` is untouched.

### Stage 2 — Genre as a hedge · 5 points · optional, and I recommend against it

**X0R-1305 · Three guesses and a score · 5**
Discogs-EffNet embeddings plus an MTG-Jamendo head, ONNX, on the `onnxruntime` already
installed for basic-pitch. Essentia's Python bindings do not build on Windows, so ONNX is the
only route. Weights download on first use like Demucs'.

Conditions, all of them hard: **top three with scores, never one label**; defeatable; and **no
processing decision may read the output**. If the label ever becomes an input to DSP, this
card has made the product less honest and should be reverted.

Build this only if stage 1 ships and leaves a felt gap. My expectation is that it will not.

### Stage 3 — Re-produce: the processing half · 8 points

*No new notes, no transcription, no X0R-306 gate. This is the stage that delivers "it sounds
more like that record" and it is reachable now.*

| Card | Title | Pts |
|---|---|---|
| X0R-1306 | A strength budget instead of a constant | 3 |
| X0R-1307 | Suggestions the fingerprint makes possible | 2 |
| X0R-1308 | Sidechain duck from the measured kick | 3 |

**X0R-1306 · A strength budget instead of a constant · 3**
`CLOSE_FRACTION`, `MAX_LEVEL_DB`, `MAX_BAND_DB` and `WIDTH_LIMITS` become one user-set
budget. Today's values are the default and are labelled *nudge*; the wider settings are
labelled for what they are and say in dB what each notch permits. The `LIKELY_ARRANGEMENT_DB`
flag stays a flag at every setting — a wider budget may close a gap further, it may not stop
telling the user that a 9 dB guitar difference is probably an arrangement.

**This card is the smallest honest version of the entire feature, and it is three days.**

**X0R-1307 · Suggestions the fingerprint makes possible · 2**
Observations the app cannot currently make because it never looked: the reference has no live
cymbals and yours does; the reference's drums are programmed and yours are played; the
reference's bass is ducked to its kick and yours is not. Observations, in the existing card
form, each with its measurement attached.

**X0R-1308 · Sidechain duck from the measured kick · 3**
The single most genre-defining process the app lacks, and fully measurable: kick times come
from `find_hits`, the depth and recovery come from comparing the reference's bass envelope
around its own kicks against the source's. A real suggestion with a real number behind it —
*"the reference's bass dips 4.2 dB within 30 ms of each kick; yours dips 0.4 dB"* — and a
fraction of that gap applied, like everything else.

### Stage 3B — Compare drum to drum · 11 points · not gated · **added 2026-10-02, and it leads**

*Not in the original proposal at all. X0R-414 separates a drums stem into kick, snare,
cymbals and toms as audio; this stage measures those four and compares each with its
counterpart on the reference, instead of averaging three instruments into one number that
describes none of them.*

| Card | Title | Pts |
|---|---|---|
| X0R-1314 | Your kick against their kick | 5 |
| X0R-1315 | Take a per-drum suggestion | 3 |
| X0R-1317 | A profile remembers their kick | 2 |
| X0R-1316 | The drum panel says which drums it found | 1 |
| *X0R-1127* | *Decline to match a stem your own mix does not contain* — EPIC-11, pulled in | *2* |

11 points in this epic, 13 in [sprint 2](../sprints/SPRINT-2.md) counting X0R-1127, which
belongs to EPIC-11 and is pulled in because it is the presence rule stage 3B mirrors four
ways. Full acceptance criteria in the sprint plan; the cards are in
[BACKLOG.md](../BACKLOG.md) under EPIC-13.

**Three design decisions the sprint plan takes and this section is too early to:** sub-drums
are a nested level inside the drums row and **not** `StemKind` members — that enum is
load-bearing in 21 modules, and `pipeline.run`'s `untouched` sum would contain the drums
twice; **four** dimensions per drum rather than six, because `NEVER_MOVE_SIDEWAYS` and
`MIN_MEANINGFUL_WIDTH` already say what pan and width mean on a near-mono signal; and the
reference's sub-drums belong in a `ReferenceProfile`, so the second separation pass is paid
once per reference rather than once per song.

**Why this outranks everything else in the epic.** It is the only part whose audible output
points *at* the reference rather than merely away from the source — every move is a stated
fraction of a stated per-drum gap with the sentence that produced it, so it is on-brief by
construction with no new product rule. It extends `instrument.compare`, which is the moat,
four instruments deeper. And it is the first time in this app that one drum can be soloed
against another record's same drum. Nothing in §5's competitor table does any of this; Ozone
cannot compare your snare with their snare at all, and this goes a level below the snare.

**What it rests on, honestly.** Two judgements, named rather than hidden:
`separate.QUIET_STROKE_DB` (the snare has no knee between backbeat and bleed, so stroke
counts run 4 to 45 across the gate's range — nothing in this stage may read a stroke count)
and DrumSep's unmeasured bleed (a kick's trace in the snare file biases the snare's low
band). X0R-306 is what would turn both into numbers, and that is a new reason for a card
that has been deferred for three sprints.

### Stage 4 — Re-perform: drums only · ~~7~~ **6 points** · ~~gated on X0R-306~~ **not gated**

**Re-scoped 2026-10-02.** The X0R-306 gate is retracted: it was a gate on classification,
and drum identity now comes from separation. Being ungated did not make this stage the core
of the epic — Experiment 2 measured the drum layer at ≤0.09 dB of the tonal gap and zero new
grid positions. It changes how the drums *sound*, never where they land.

| Card | Title | Pts |
|---|---|---|
| X0R-1309 | Kits chosen by fingerprint, not by dropdown | 2 |
| X0R-1310 | ~~More voices, same synthesis~~ **A tom voice** | ~~3~~ 2 |
| X0R-1311 | Pattern observation, never pattern replacement | 2 |

**X0R-1309 · Kits chosen by fingerprint, not by dropdown · 2**
The three kits exist. This picks one and sets `drum_blend` from the reference's measured drum
character — decay length, transient sharpness, sub energy — and says in a sentence why it
chose what it chose. The dropdown stays.

**X0R-1310 · ~~More voices, same synthesis · 3~~ A tom voice · 2** *(re-scoped 2026-10-02)*
~~Tom, ride, crash, clap, rimshot as `Voice`s~~. One `Voice`: **toms**, tuned against
measurements the way the existing three were. A tom is a pitched membrane, which is the
same family as the kick and the place synthesis is in its element.

**Ride, crash, clap and rimshot are retracted, for two reasons.** DrumSep returns a single
`cymbals` stem holding hats, rides and crashes together, so they cannot be voiced apart —
the model that splits hi-hat out is LarsNet, rejected on its CC BY-NC weights and its
synthesised training set (X0R-414). And a 35–130 ms filtered noise burst is a credible
closed hat and not a credible crash; shipping one would be this epic's version of the
synthesised guitar §4 refuses to ship.

The classification half of the original card is moot: it required `detect.py` to classify
toms and cymbals, and separation answers that by construction. X0R-406's unfinished
criterion is now satisfiable by pointing at `separate.py`.

**This card is parked behind X0R-1314's sub-drum presence test.** Measured on the one clip:
24 tom strokes in 28 seconds on a programmed electro-house record, which is residue, not
toms. A tom voice built first puts synthesised toms on records that have none.

**X0R-1311 · Pattern observation, never pattern replacement · 2**
Report the grid positions where the reference's kick lands and the source's does not. Offer
to *add* a synthesised hit at those positions, at low blend, opt-in per position, with the
count shown. **This is the line.** Adding a measured hit the user accepts one at a time is a
nudge. Rewriting the pattern is composing his song for him, and that is stage (c), which is
out.

*Updated 2026-10-02: this card is now **buildable** where it was not — the kick returns 60
strokes at every gate from −6 to −30 dB, so the count is solid. It is deliberately still out
of sprint 2. It is the only card in the epic that places a drum where the user did not play
one, and it needs both files read against **one** grid (Experiment 2 §3) or it measures the
ruler rather than the music. That is a decision about composing someone's song, and it
deserves to be taken on its own rather than inside a sprint about comparison.*

### Stage 5 — Re-perform: bass only · 6 points · gated on X0R-306 *passing*

| Card | Title | Pts |
|---|---|---|
| X0R-1312 | A synth bass patch set | 3 |
| X0R-1313 | Layer a synth bass under the transcribed line | 3 |

**X0R-1312 · A synth bass patch set · 3**
Three patches in the `Voice` idiom — oscillator choice, filter envelope, glide — tuned against
measured spectra of real bass parts the way the kicks were.

**X0R-1313 · Layer a synth bass under the transcribed line · 3**
Layered, never replacing. Level from the stem's own envelope so dynamics survive. **Mutes
itself wherever pYIN's note confidence is below threshold**, so an uncertain passage gets the
original bass alone rather than a confident wrong note. The card carries its own kill
criterion: if X0R-306 reports worse than 95% note accuracy or any octave errors on clean DI
bass, this card does not get built.

### Deliberately out of scope, with reasons

| Not doing | Why |
|---|---|
| Guitar patches | Synthesis cannot reach an amplified guitar. It would be the first thing in this codebase that is worse than the alternative. Process the recorded guitar instead. |
| Vocal regeneration | Not a patch question, and nothing good is downstream of it. |
| Re-sequencing, quantising, tempo change | Product (c). Measuring where the reference's kick sits is a measurement; moving the user's kick there is composition. |
| Generative part invention | Moises does this well and in the cloud. Not this product's question, and it cannot be explained, which makes it off-brief by rule 4 of the role definition. |
| Shipping recorded samples | The licensing position in `kit.py` is strong and should not be traded for a sound that can be synthesised. |
| A genre label driving DSP | Section 3. The label has no referent; wiring it to processing would make the tool lie. |

---

## 7. The smallest honest prototype

Three experiments, in order, each cheap, each with a stated kill criterion. **The first two
need almost no code and should be run before any card is written.**

### Experiment 1 — the fingerprint, read cold · half a day

A script, not a card. One source and one reference Ryan already has. Print the fingerprint:
tempo, metre and key (already built), plus kick positions against the grid, swing, hit-timing
variance, stem census, and bass-dip-around-kick. No UI, no model, no processing.

Then one question, asked before he hears anything:

> **Reading only this, do you know something about that record you did not know, and do you
> know what you would do to your mix because of it?**

**Kills the epic if:** he reads it and shrugs. If a fingerprint of a record he admires does
not tell him anything actionable, stage 1 is not worth 8 points and stages 3-5 have no
steering signal, because every one of them keys off these numbers.

**This is the right first experiment** because stage 1 is the foundation of everything else
and it is the cheapest thing to falsify.

### Experiment 2 — is "remix" reachable by turning the existing dials up? · half a day

A loop, not a card. Bounce the same source against the same reference six ways: the existing
per-instrument match at `CLOSE_FRACTION` 0.4 / 0.8 / 1.0, each with the drum kit at `blend`
0.3 / 0.9. Six files, no new DSP.

**Kill criterion, and it is the most informative one available:** if the 1.0 / 0.9 bounce does
not sound meaningfully closer to the reference's genre than the 0.4 / 0.3 bounce, then
**"remix in that style" is not reachable by loosening clamps**, and the only path to it is
regeneration — which is gated on an unmeasured transcriber. In that case the correct decision
is to build stage 1, skip stages 3-5 entirely, and revisit after X0R-306.

If the louder bounce *does* get meaningfully closer, then stage 3 is the whole feature and
stages 4-5 are optional polish. Either answer is decisive, and it costs a loop.

### Experiment 3 — the transcription round trip · one day · only if stages 4-5 are reached

Ryan records a DI bass line, so ground truth is exact and no licensing question exists — the
route X0R-306's card already recommends. Mix it into a full backing, separate it, transcribe
it, re-perform it with a crude synth voice, and **count wrong notes against what he played**.

**Kill criterion: more than one wrong note in twenty, or any octave error at all, and bass
regeneration is dead.** No amount of patch design rescues a wrong note. A listener forgives a
wrong EQ and never forgives a wrong note, and this is the experiment that settles whether the
feature is magic or mush.

---

## 8. What would make this a bad idea

Not a risks table. These are the arguments against, and three of them are good enough to act
on.

**1. It enters a race against Suno's Cover and loses.** Cover takes any audio and re-renders
it in a new style, preserving the melody, today, for anyone. That is the brief's sentence,
implemented, by a generative model with resources this project does not have. extract0r
cannot beat it on result quality and should not try. What it can do that Cover cannot is
explain every change, keep Ryan's actual recording in the output, and run with nothing
leaving the machine. **Those advantages only register if the framing is "re-produce", not
"remix".** Under the remix framing, every honest limitation reads as a shortfall.

**2. It dilutes the only moat, and the sprint-1 research says so in writing.** The moat is
per-instrument comparison with explanations — Ozone 12's Stem EQ splits four ways with an EQ
each and still cannot tell you what their snare does that yours does not. 34 points on
restyling is 34 points not spent there, with EPIC-11 still carrying X0R-1108, X0R-1123 and
X0R-1124 open and EPIC-12 naming X0R-1203 (dynamic EQ) as the biggest remaining *sonic* gap.
**pr0ducer is more exciting and less valuable than dynamic EQ**, and that is an uncomfortable
sentence worth sitting with.

**3. Half of it is built on a number nobody has, and this is the strongest objection.**
*Amended 2026-10-02: a third of this objection has been answered by X0R-414 and the rest
stands. Stage 4 does not depend on transcription accuracy and never really did — it depended
on knowing which drum a stroke was, which separation now answers by construction. **Stage 5's
6 points remain built on a guess**, and so do two judgement thresholds in stage 3B that
X0R-306 would retire. Read "13 of these 34 points were never buildable" below as "6 of these
42".*

Stages 4 and 5 depend on transcription accuracy. X0R-306 has been TODO since sprint 1, is the
self-declared gating card for the entire transcription epic, and two cards' acceptance
criteria are parked on it. The only end-to-end run on record produced an octave error and a
half-time tempo. Building re-performance before that benchmark is building on a guess, and if
the benchmark returns 70% note F1 then 13 of these 34 points were never buildable. **The
honest sequencing is X0R-306 first, with the expectation that it may cancel a third of the
epic.**

**4. "Genre" is the exact kind of claim this project exists not to make.** The saturation
decision is the precedent and genre is a weaker case, not a stronger one. A model that says
"House, 0.82" invites trust in a number whose referent is a Discogs field, and the most-used
benchmark in the field is full of mislabels and duplicates. Stage 2 is the one stage that
makes the product *less* honest, which is why it is isolated, optional, and why I recommend
skipping it. If Ryan wants the word, the top-three hedge is the most it can honestly be.

**5. A half-working feature is worse portfolio evidence than a finished one.** This project is
portfolio evidence as well as a tool. Reviewers discount demos and reward finished things, and
"AI remix" is the single most demo-shaped feature available. A fingerprint card that measures
thirteen honest properties and explains why it will not name a genre is *better* evidence than
a synthesised guitar that sounds like a synth — it demonstrates judgement, which is the rarer
signal.

**6. Install cost compounds.** Stage 2 adds a model download to an install that already needs
two scripts, a short-path venv for torch's MAX_PATH problem, and a `--no-deps` install for
basic-pitch. Each added weight file is one more thing that breaks on a fresh machine, and the
RUNBOOK is already longer than the feature list it supports.

### The case for "no", stated properly

It is a real case. It goes: the fingerprint is nice-to-have, the budget slider is a parameter
change anyone could make in an afternoon, the sidechain ducker is one card that belongs in
EPIC-12 on its own merits, and everything genuinely new about pr0ducer is either unmeasurable
(genre), unreachable (guitar synthesis), off-brief (re-sequencing), or blocked on a benchmark
that has been deferred for two sprints. On that reading the correct answer is: **take
X0R-1308 (sidechain) into EPIC-12, take X0R-1306 (budget) into EPIC-11, and close the
proposal.** That is 6 points instead of 34, and it loses almost nothing a user would miss.

I do not quite agree, because of one thing: the fingerprint is the only item here that the
tool cannot already do *and* that is pure measurement. It is the kind of feature this product
is uniquely positioned to ship, and no competitor does it — they all either name a genre or
say nothing. But the "no" case is close enough that it should be Ryan's call rather than
assumed away.

### And the case for "only the drum half"

Also strong, and the briefing guessed it. Drums are where this works: synthesis is genuinely
competitive, the kit already ships and is already tuned against measurements, the rhythmic
fingerprint is the most diagnostic part of a reference, layering makes detection errors
survivable, and `detect.py` + `kit.py` are the two modules in the codebase most ready to be
extended. Bass is plausible and conditional. Everything else is either processing (already
the product) or out of reach.

~~**Stages 1, 3 and 4 — 23 points — are "the honest fingerprint plus the drum half", and that
is my recommendation if the appetite is for more than 6 points and less than everything.**~~

*Revised 2026-10-02. The instinct — "drums are where this works" — was right and the reason
given for it was the wrong one. The argument above is about **synthesis** being competitive
on drums. The better reason is that drums are the one stem where the stem is not an
instrument, and X0R-414 made its contents measurable. **Stage 3B, 11 points, is "the drum
half" as it should have been written**, and it needs neither the fingerprint nor a single
synthesised sample.*

---

## 9. Recommendation

**Superseded 2026-10-02 by §9a. Kept because the first two items were run and their results
are what changed the rest.**

1. ~~**Run experiment 1**~~ **Run** (half a day, no cards). If the fingerprint does not tell
   Ryan something he can act on, stop here. → [run](EXPERIMENT-1-RESULTS.md): two figures
   out of a dozen carried information, stage 1 cut from 8 to 5, X0R-1303 deleted.
2. ~~**Run experiment 2**~~ **Run** (half a day, a loop). → [run](EXPERIMENT-2-RESULTS.md):
   processing gets you tone, never groove. The clamps, not `match_strength`, hold the
   headroom.
3. ~~**Build stage 1** — 8 points~~ — **deferred twice.** 5 points, not 8, and it is now
   conditional on X0R-1307/1308 being sprinted (Experiment 2 §6). Stage 3B reads none of it.
4. **Build stage 3** — 8 points — ~~if stage 1 lands~~ **and before stage 1, not after.**
   X0R-1306 must be the *clamps*, not `match_strength`, or it is a no-op control.
5. **Skip stage 2.** Unchanged. Do not ship a genre label.
6. ~~**Treat stages 4 and 5 as conditional on X0R-306**~~ — **stage 5 only.** Run
   experiment 3 before writing a line of stage 5.
7. **Do not call it pr0ducer in the UI.** Unchanged, and reinforced: nothing in sprint 2
   re-produces anything, so the verb there is still *compare*.

## 9a. Recommendation as re-scoped · 2026-10-02

1. **Build stage 3B first** — 11 points, 13 as [sprint 2](../sprints/SPRINT-2.md) with
   X0R-1127 pulled in from EPIC-11. Per-drum
   comparison: *your kick against their kick*. Cheapest, most on-brief, and the only part of
   this epic whose audible result is aimed at the reference rather than merely away from the
   source.
2. **Then X0R-306** — 5 points, leading sprint 3. It no longer gates drums and it has gained
   two items. It is the card that turns this epic's two remaining judgements into numbers.
3. **Then stage 3** — X0R-1306 (the clamps, 3) is the best-measured headroom in the whole
   processing half: 1.07 dB at ×2 clamps against 0.56 dB for the entire strength sweep.
4. **Then stage 4, re-scoped to 6** — X0R-1310 (toms, 2) once the presence test lands,
   X0R-1309 (kit by fingerprint, 2) once there is a fingerprint. Sold as *your drums,
   re-kitted, same groove* and not as anything else.
5. **Stage 1 after that, if X0R-1307/1308 are being built.** Not before, and not alone.
6. **Stage 5 still conditional, stage 2 still dead, X0R-1311 still out** — the last on the
   grounds that placing a drum the user did not play is a composition decision, not a nudge.

---

# 10. Melodyne — what of it is reachable here · added 2026-10-02

Written in response to:

> "also add comparisons with functionality from melodyne as part of the remix0r scope of
> work. id like to take advantage of something similar."

**Recommendation in one line.** Two of the candidate comparisons are reachable and cheap —
**5 points, X0R-1320 and X0R-1321** — one is the most valuable thing in the list and is
**blocked on a grid this section measured to be broken on live-drummed records**, which is a
5-point card nobody had written (**X0R-1319**). Nothing here needs Direct Note Access,
nothing here is a note editor, and the one Melodyne feature that actually matters to this
product is its least glamorous: the **tempo map**.

A probe was run before any card was written, the way the rest of this proposal was. Its
numbers are in §10.4 and they changed the answer twice.

---

## 10.1 What Melodyne actually does

Researched rather than remembered, from Celemony's own documentation.
[Melodyne 5's editions](https://www.celemony.com/en/melodyne/melodyne-5-editions) split the
feature set four ways, which is useful here because it pins "something similar" to features
rather than to a brand.

| Capability | Edition | What it operates on |
|---|---|---|
| Pitch / intonation, position, duration, note separation | essential | one note at a time, monophonic |
| Vibrato, pitch drift, amplitude, fades, sibilants, formants, attack speed; audio-to-MIDI | assistant | same, monophonic |
| **DNA Direct Note Access** — individual notes inside chords | **editor** | one polyphonic *instrument* |
| Scale and chord functions, **tempo and tempo-progression editing** | editor | the whole track |
| Multitrack note editing, overtone-level Sound Editor | studio | several tracks at once |

Three facts from the
[algorithm documentation](https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_AudioAlgorithms?env=standAlone)
reframe the request, and they cut in ways the headline does not suggest:

1. **DNA separates notes by pitch, not by instrument.** Celemony's own wording: two
   instruments playing the same note produce one blob, not two. The polyphonic algorithms
   require single-instrument recordings and fall back to percussive detection on material
   without enough tonal content. **DNA is not a mix-unmixer.** Its required input is
   precisely what Demucs already hands this project — one instrument, alone — so the
   interesting question is not "can we do DNA" but "what would we do with the stem we
   already have".
2. **Celemony says the detection is not always right.** Its wording: the detection process
   cannot, for reasons to do with immutable principles, always deliver perfect results,
   particularly on polyphonic material. The commercial product with the patent and a
   twenty-year head start ships a *manual correction workflow* around its transcription.
   That is the strongest available evidence that unattended note-level transcription is not
   a thing to build a comparison on.
3. **Melodyne is an editor.** Every capability in the table is something a person does to
   one note with a mouse. None of it measures a record and none of it compares two records.
   The overlap with extract0r is not the feature set, it is the *representation* underneath
   it — audio as notes with pitch, time, length and level.

**DNA is patented** — presented at Musikmesse 2008 and described by Celemony as patented.
Nothing proposed below reimplements it and nothing should. There is also no open
equivalent: a search for one returns monophonic pitch correctors, which is a problem that
was solved in 1997.

---

## 10.2 The question that matters

extract0r is not a note editor and must not become one. Its brief is comparison and
explanation. So the question is **what can we compare with note-level information that we
cannot compare today**, and there are six candidates. Each was tested rather than accepted.

| Candidate | What it would say | Verdict |
|---|---|---|
| **Timing tightness** | "their kick sits 4 ms off the grid, yours 19" | **the most valuable, and the only one that reaches groove — and it is blocked.** §10.4(a) |
| **Pitch centredness** | "their vocal sits 4 cents from its own tuning, yours 14" | **reachable now, and it discriminates sharply.** §10.4(c) |
| **Note density and spacing** | "their bass plays a note every 186 ms, yours every 441" | **reachable now, cheap, grid-free.** §10.4(d) |
| **Note length — legato vs staccato** | "theirs is 95% legato, yours 76%" | **refused.** Note offsets are the least reliable quantity in transcription. §10.4(d) |
| **Vibrato** | "their vocal has 5.6 Hz vibrato, yours 5.0" | **refused — the measurement is noise.** §10.4(e) |
| **Scale and key agreement** | "theirs is F minor, yours E minor" | **refused.** `estimate_key` already does it, Experiment 1 found it carried nothing, and the only action it implies is transposing a song. |

Timing is the one that matters most, and for the reason the briefing gives: Experiment 2
measured that **processing gets you tone and never groove**, so note-level timing is the
only route to the half of "sounds like that record" the product currently cannot touch.
That is why §10.4(a) is the longest part of this section and why its answer is *not yet*.

---

## 10.3 The probe

Not Experiment 3 — §7's Experiment 3 is the DI-bass round trip and is still unrun. This is
a separate, cheaper probe, run 2026-10-02. Throwaway harness in the session scratchpad,
nothing in `app/` modified, nothing written to `storage/`.

**It fixes the library problem both earlier experiments complained about.** Experiment 1
recorded that `LIBRARY_DIR` holds no live-drummed record, so the fingerprint was asked to
tell apart two four-on-the-floor electro tracks. There are live-drummed records on this
machine, outside the library, and this probe uses two.

| | Role | Why |
|---|---|---|
| **Special When Lit — *Spare Me The Love Song*** | source-shaped | live drums, played bass, untuned sung vocal — the case the product is for |
| **blink-182 — *Edging*** (2023) | reference-shaped | live drums, modern major-label production, same genre family |
| **MSTRKRFT — *Bounce*** | programmed control | the same 36–64 s clip Experiments 1 and 2 used, so the figures line up |

Densest 28 s of each, `htdemucs_6s` on CPU, grid from `fingerprint.grid_from_drums`, notes
and pitch from the shipped `PyinTranscriber` settings.

**Caveats, up front:** two live records, one genre family, 28 seconds each, and no ground
truth for any of it. Everything below is a feasibility reading, not a benchmark. That is
what X0R-306 is for.

---

## 10.4 What the probe found

### (a) The grid is broken on live drums, and that blocks every timing comparison

This is the finding, and it is not what the probe went looking for.

Every note-timing comparison needs a correct grid **on both records**. Unlike Experiment 2
— which compared six bounces of one song and could therefore use one shared ruler — two
different records have two different tempos and need two independently estimated grids. The
shipped path for that is `grid_from_drums` + `refine_grid`, built during Experiment 1
precisely to fix a grid failure.

| | shipped grid | actual | grid confidence | kick histogram |
|---|---|---|---|---|
| MSTRKRFT (programmed) | **128.91 BPM, 4/4** | 128.9 | 0.881 | `13 0 0 0 · 12 0 0 0 · 15 0 0 0 · 12 0 0 0` |
| Special When Lit (live) | **66.30 BPM** | ~132.7 | 0.486 | `3 6 7 4 · 7 4 4 6 · 5 4 3 0 · 6 5 5 4` |
| blink-182 (live) | **147.58 BPM, 3/4** | ~147.3, in 4/4 | 0.546 | twelve steps, unreadable |

Three separate failures, and the confidence floor catches none of them —
`MIN_GRID_CONFIDENCE` is 0.35 and both live records clear it:

1. **Experiment 1's octave fix does not generalise.** That fix was to run `choose_tempo` on
   the kicks and snares rather than the whole mix, and it works for the reason
   `score_tempo` was built on: on a four-on-the-floor record the halved grid has no drum on
   half its beats, and recall punishes it. **A rock backbeat has a drum on every beat of the
   halved grid too.** On *Spare Me The Love Song* the shipped path returns **66.30 BPM
   against a record at about 132.7**, at a confidence that passes the floor. Scored against
   the anchors at a fixed phase, 33 BPM out-ranks both.
2. **Metre detection returns 3/4 on a 4/4 record.** X0R-407 made metre return *zero*
   confidence when there is no accent; it still returns a number, and the histogram is
   indexed by it, so a wrong metre makes every rhythmic figure unreadable rather than merely
   uncertain.
3. **And the part no octave fix can reach: a live band's tempo drifts, and every grid in
   this codebase is a straight line.** Fitting the drum anchors to the first and second
   halves of each clip separately:

| | tempo, first half | second half | drift over 28 s | **median distance of a drum hit from its own best-fit sixteenth** |
|---|---|---|---|---|
| MSTRKRFT (programmed) | 128.896 | 128.893 | **0.00 BPM** | **5.7 ms** of a 116 ms step |
| blink-182 (live) | 147.356 | 146.748 | 0.61 BPM | **23.3 ms** of a 102 ms step |
| Special When Lit (live) | 133.259 | 132.286 | **0.97 BPM** | **30.5 ms** of a 113 ms step |

**The last column is the kill number.** The
[microtiming literature](https://www.nature.com/articles/s41598-019-55981-3) puts musically
meaningful deviations at roughly **5 to 50 ms**. On the two live records the *grid's own
residual* is 23 and 30 ms — squarely inside the signal, and five times the programmed
record's. A constant-tempo line through a performance that drifts a whole BPM scatters
about a quarter of a sixteenth everywhere, and a groove comparison would report that
scatter as the drummer's feel.

So: **on exactly the records where groove is a human thing worth measuring, the grid error
is the same size as the groove.** Nothing note-level about timing can be built until that is
fixed, and the fix is the Melodyne feature nobody would pick out of the brochure — a
**tempo map**, a tempo per bar rather than a tempo per clip. Melodyne puts it in the Editor
tier next to DNA. For this product it is worth more than DNA.

→ **X0R-1319**, 5 points, prerequisite for X0R-1301, X0R-1307, X0R-1311 and X0R-1322.

### (b) On a pitched stem the onset detector is four times worse than on drums

Experiment 1 measured `backtrack=True` contributing 1–7 ms to drum hit times and set
`DETECTOR_JITTER_MS = 7.0` from it. `PyinTranscriber` calls the same detector with the same
flag ([`pyin.py`](../../services/api/app/services/transcription/pyin.py), in `transcribe`),
so every note start it produces inherits the problem. Nobody had measured how much. Pairing
the same onsets detected with and without backtracking:

| stem | paired onsets | median shift | mean absolute | max | **SD** |
|---|---|---|---|---|---|
| bass, SWL | 16 | 14.5 ms | 15.2 | 34.8 | 6.1 |
| bass, blink | 102 | 17.4 ms | 19.1 | 40.6 | 8.6 |
| bass, MSTRKRFT | 68 | 17.4 ms | 18.8 | 40.6 | 7.9 |
| vocals, SWL | 38 | 23.2 ms | 25.5 | 69.7 | 12.7 |
| vocals, blink | 48 | 23.2 ms | 26.2 | 75.5 | 13.7 |
| vocals, MSTRKRFT | 37 | 29.0 ms | 30.9 | 63.9 | 16.8 |

**15 to 31 ms, against 7 ms on drums**, and the SD column is the part that matters: it is
not a constant anyone can subtract. A vocal note's start moves up to 75 ms on a flag. So
X0R-412 is not a dependency of pitched-stem timing, it is a **blocker** — on its own the
detector is larger than the entire microtiming signal.

One consolation, and it is what makes §10.4(d) proposable at all: a shift that is roughly
constant within a stem **cancels in the difference between consecutive onsets**. Note
*spacing* survives what note *placement* does not.

### (c) Pitch centredness works, and it discriminates sharply

The measurement: pYIN's frame-level f0 on the vocal stem, converted to cents from the
nearest equal-tempered semitone, then **the record's own tuning reference removed** before
anything is called off-pitch. That second step is not optional, and the probe found out why
— these three records are tuned to three different A4s.

At pYIN's default 10-cent resolution and again at 2 cents:

| | A4 of the record | median \|cents\| from its own tuning, @10c | **@2c** | IQR @2c |
|---|---|---|---|---|
| **blink-182 vocal** | 439.8 Hz | 0.0 | **4.0** | 8.0 |
| **Special When Lit vocal** | 444.9 Hz (≈ +19 cents) | 10.0 | **14.0** | 26.0 |
| **MSTRKRFT vocal** (rapped) | 442.4 Hz | 30.0 | **26.0** | 51.5 |

Over 2,900–4,300 voiced frames per 28-second clip. The ordering is stable across a fivefold
change of analysis resolution, and 4.0 against 14.0 cents is a 3.5× separation that no
amount of detector noise explains. The reading is the obvious one: **blink's vocal is
pitch-corrected and Special When Lit's is not** — and whether a record was tuned is a
*production* decision, which is this product's subject, rather than a performance one.

Four things make this the healthiest candidate in the section:

- It reads the **f0 contour, not notes**. No segmentation, no note offsets, no onset
  detector and **no grid** — none of §10.4(a) or (b) touches it.
- The tuning reference is a useful figure in its own right and nothing in the app has ever
  reported it. A record 19 cents sharp of A440 is a fact about that record.
- It survives separation. A hard-tuned vocal reads 4 cents *through* Demucs and pYIN;
  artefacts would add spread, not remove it, so the figure is a safe **upper bound** on the
  real deviation. "Theirs is tighter than yours" is sound even where "yours is 14 cents out"
  is not.
- The cost is known: 5 s per stem at 10-cent resolution, **30 s at 2 cents**, per side.

And three honest problems, which belong on the card rather than in this document:

- **Vibrato and portamento inflate it.** A singer with wide vibrato reads as less centred
  without being out of tune, and §10.4(e) shows the vibrato cannot be measured well enough
  to compensate. The figure is "how close to the grid this vocal sits", not "how well this
  person sings", and it has to be worded that way.
- **It must abstain on a vocal that is not sung.** MSTRKRFT's 26 cents is a rap, and a rap
  is not out of tune. Without a gate the app calls a rapper flat.
- **No ground truth.** Nobody has confirmed blink's vocal was tuned; it is an inference from
  a number. X0R-306 would put a confidence on the pitch track underneath it. It would not
  validate the inference, and the card must not pretend otherwise.

→ **X0R-1320**, 3 points, reachable now.

### (d) Note spacing works and is nearly free; note length does not

Median inter-onset interval per stem, from the shipped transcriber:

| | bass median IOI | bass median note length |
|---|---|---|
| blink-182 | **186 ms** | 151 ms |
| MSTRKRFT | 302 ms | 192 ms |
| Special When Lit | 441 ms | 401 ms |

"Their bass plays twice as often as yours" is a real observation about arrangement density,
it is the kind of thing a mix decision follows from, and — per §10.4(b) — the interval is
robust to the one error that wrecks absolute placement. It needs **no grid at all**.

The length column is where it stops. Legato ratio — note length over the interval to the
next note — came back at exactly 1.000 on blink's bass, which is a ceiling artefact of notes
abutting; 0.946 with an IQR of 0.158 on SWL's; and 0.757 with an **IQR of 0.592** on
MSTRKRFT's, where the spread is wider than the whole difference between legato and
staccato. That is what you would expect: **note offsets are the least reliable quantity in
transcription**, which is why the field reports F-measure and F-measure-no-offset as two
separate numbers.

→ **X0R-1321**, 2 points, spacing only. Length is refused in §10.5.

### (e) Vibrato is noise

Measured per sustained note as the dominant 3–9 Hz component of the detrended cents
contour: 4.96 Hz at ±14.7 cents on SWL's vocal over 16 notes, 5.63 Hz at ±7.5 cents on
blink's over 34, and nothing at all on MSTRKRFT's rap.

The rates look plausible — human vibrato is 5–7 Hz — and they are not measuring vibrato.
**The inter-note IQR of the rate is 2.7–3.5 Hz**, which is most of the band being searched:
the estimator is picking the largest bin of a flat spectrum. And the extents, 7.5 to 14.7
cents, are an order of magnitude below real vocal vibrato and sit at the pitch track's own
resolution. A finer pitch tracker might rescue this. Nothing here says it would, and the
literature's finding that pYIN is at its **worst** on fluctuating vibrato contours says it
probably would not.

---

## 10.5 What I am explicitly refusing to propose

| Refused | Why |
|---|---|
| **Direct Note Access, or anything that separates notes inside a chord** | Patented, and there is no open equivalent — a search for one returns monophonic pitch correctors. It is also unnecessary: DNA's required input is a single-instrument recording, which separation already produces. |
| **A note editor — clicking a note to change it** | That is RipX, named in §5, and it is a different product. It is also the only shipping shape of note-level restyling, which is informative about the category and not an argument to enter it. |
| **Pitch correction toward the reference** | The obvious next sentence after X0R-1320, and the one that must not be said. "Their vocal is 10 cents tighter, shall I tune yours" changes a performance rather than a production, and it runs straight into the asymmetry this proposal already wrote down: a wrong measurement is a wrong sentence, a wrong note is a wrong note. X0R-1320 ships a number and no dial, deliberately. |
| **Quantising, or transferring the reference's microtiming** | §1(c), unchanged. Measuring where their kick sits is a measurement; moving the user's kick there is composing his song. |
| **Note length / legato comparison** | §10.4(d). Offsets are the least reliable quantity available and the measured spread is wider than the effect. |
| **Vibrato comparison** | §10.4(e). The estimator returns the middle of whatever band it is given. |
| **Note-level comparison of guitar, piano or "other"** | These need polyphonic transcription. basic-pitch is what ships here, and [its own paper](https://arxiv.org/abs/2203.09893) reports note F-measure around 0.76 on **clean solo** GuitarSet and 0.68 on MAESTRO piano, with the stated limitation that the model was **not trained on multi-instrument mixtures** — and a Demucs stem is exactly that, re-separated. One note in four wrong on the easy case, unmeasured on ours, and X0R-306 has never been run. Monophonic bass and vocals are a different and much better-founded case, and that is where every card here lives. |
| **Key / scale agreement as a finding** | `estimate_key` already computes it, Experiment 1 found it carried no information, and the only action implied by "yours is in E minor and theirs is in F minor" is transposing a song. |
| **Swapping pYIN for CREPE as part of any of this** | Worth knowing it is available — [torchcrepe](https://github.com/maxrmorrison/torchcrepe) and [onnxcrepe](https://github.com/yqzhishen/onnxcrepe) are both MIT, and torch and `onnxruntime` are both already installed, so it is a dependency question and not a platform one. But swapping the pitch tracker before X0R-306 can say whether it is the limitation is trading one unmeasured thing for another. A card for after the benchmark, not before. |

---

## 10.6 The work, and where it sits

| Card | Title | Pts | State |
|---|---|---|---|
| **X0R-1319** | A grid that survives a live drummer | **5** | `TODO` — prerequisite for every timing figure in this epic |
| **X0R-1320** | Is their vocal tuned, and to what | **3** | `TODO` — reachable now |
| **X0R-1321** | How much space their parts leave | **2** | `TODO` — reachable now |
| **X0R-1322** | Note timing against the grid, yours against theirs | **5** | `TODO` — blocked on X0R-1319 and X0R-412 |

**15 points, of which 5 are buildable today.** X0R-1322 is the one worth having and it is
the one that is blocked. That is the honest shape of this request and it should not be
softened.

**Dependency on X0R-306, card by card**, because everything note-level inherits a benchmark
that has never been run:

- **X0R-1319** — none. It is a grid card: it reads drum onsets, which separation already
  produces, and it is measured against the drums themselves.
- **X0R-1320** — not gated to *build*. It reads a frame-level f0 contour, not notes, so it
  inherits pYIN's pitch accuracy and none of its note segmentation. X0R-306 is what would
  let the card state a confidence rather than a caveat.
- **X0R-1321** — not gated. Onset spacing, not notes.
- **X0R-1322** — **gated**, and least of all on the percussive half. Per-drum onsets come
  from `drums/separate._onsets`, which already runs `backtrack=False` on purpose; the
  pitched half needs X0R-412 first and X0R-306 to say what a note onset is worth.

**Which kind of transcription each one needs**, since that is the axis that decides
feasibility:

| | percussive onsets only | monophonic pitch | polyphonic notes |
|---|---|---|---|
| | *already reliable — per-drum separation ships, zero ambiguous strokes measured* | *easier — bass and lead vocal, pYIN ships, unbenchmarked* | *hard, unmeasured, refused* |
| X0R-1319 | all of it | — | — |
| X0R-1320 | — | f0 contour only, no notes | — |
| X0R-1321 | yes | yes | — |
| X0R-1322 | phase one | phase two, after X0R-412 | never |

### Does any of it jump the queue?

**No, and not out of politeness.**

- **Not ahead of sprint 2.** Nothing here reads a sub-drum measurement, and sprint 2 reads
  none of this.
- **Not ahead of X0R-306.** The benchmark is what turns three caveats in this section into
  numbers, and it leads sprint 3.
- **Not ahead of X0R-1306.** The clamp budget is still the best-measured headroom in the
  processing half — 1.07 dB, Experiment 2 — and these are observation cards.

**Inside EPIC-13 the order does change.** X0R-1320 is 3 points, has no gate, and produces a
sentence no competitor in §5 can produce: *"that record's vocal sits within four cents of
its own tuning and yours sits fourteen cents out — and the record is tuned 19 cents sharp of
A440."* That is better value than X0R-1301 (3 points, and now **blocked by the same grid
problem** this section measured), better than X0R-1309 and X0R-1310, and it is the first
thing I would build in this epic after sprint 2 and X0R-306.

X0R-1319 has a claim worth stating plainly even though I am not making it: it is the only
card in the epic that has been *measured* to be broken rather than suspected, and four other
cards sit on top of it. It shows the user nothing, which is why it is not jumping — but the
next person to write a groove card without reading §10.4(a) will ship a comparison of two
broken rulers.
