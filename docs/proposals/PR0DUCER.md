# Proposal — pr0ducer

> **Named `pr0ducer`, not `remix0r`.** Ryan asked for the rename and this
> document's own research is the reason: the thing that literally does "remix the
> source in that style" is Suno's Cover feature, it ships today, and it replaces
> your recording with a new one. Every remix framing invites that comparison, which
> this loses on every axis except the ones that are actually its advantages — your
> performance, kept, re-produced, with every move still carrying its measurement.
> The verb in the UI is **re-produce**.


**Status: proposal. Nothing here is in [BACKLOG.md](../BACKLOG.md) and nothing is sprinted.**
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

**34 points total**, plus X0R-306 (5) which is already in the backlog and becomes a hard
prerequisite for stages 4 and 5.

### Stage 0 — the prerequisite that already exists

**X0R-306 · Separation and transcription quality benchmark · 5 · `TODO`** — already written,
already gating the transcription epic by its own text. Needed before stage 4 or 5, not before
stages 1-3. Its result may cancel stages 4 and 5, and that is the point of running it.

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

### Stage 4 — Re-perform: drums only · 7 points · gated on X0R-306

| Card | Title | Pts |
|---|---|---|
| X0R-1309 | Kits chosen by fingerprint, not by dropdown | 2 |
| X0R-1310 | More voices, same synthesis | 3 |
| X0R-1311 | Pattern observation, never pattern replacement | 2 |

**X0R-1309 · Kits chosen by fingerprint, not by dropdown · 2**
The three kits exist. This picks one and sets `drum_blend` from the reference's measured drum
character — decay length, transient sharpness, sub energy — and says in a sentence why it
chose what it chose. The dropdown stays.

**X0R-1310 · More voices, same synthesis · 3**
Tom, ride, crash, clap, rimshot as `Voice`s, tuned against measurements the way the existing
three were. Requires `detect.py` to classify them, which is X0R-406's one unfinished
criterion ("toms and cymbals classified, or explicitly reported as unsupported") — so this
card finishes an existing card rather than opening new ground.

**X0R-1311 · Pattern observation, never pattern replacement · 2**
Report the grid positions where the reference's kick lands and the source's does not. Offer
to *add* a synthesised hit at those positions, at low blend, opt-in per position, with the
count shown. **This is the line.** Adding a measured hit the user accepts one at a time is a
nudge. Rewriting the pattern is composing his song for him, and that is stage (c), which is
out.

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

**Stages 1, 3 and 4 — 23 points — are "the honest fingerprint plus the drum half", and that
is my recommendation if the appetite is for more than 6 points and less than everything.**

---

## 9. Recommendation

1. **Run experiment 1** (half a day, no cards). If the fingerprint does not tell Ryan
   something he can act on, stop here.
2. **Run experiment 2** (half a day, a loop). It settles whether this feature is a parameter
   change or a rebuild, and that determines everything after.
3. **Build stage 1** — 8 points, the fingerprint. Honest, cheap, uniquely ours, and good
   portfolio evidence.
4. **Build stage 3** — 8 points — if stage 1 lands and there is still appetite. X0R-1308
   (sidechain) is worth doing on its own merits regardless of this proposal.
5. **Skip stage 2.** Do not ship a genre label. If Ryan wants the word, ship the top-three
   hedge and never let it touch the DSP.
6. **Treat stages 4 and 5 as conditional on X0R-306**, and be willing to cancel them. Run
   experiment 3 before writing a line of stage 5.
7. **Do not call it pr0ducer in the UI.** The epic can be named that. The button says
   "produce my song more like this record" and then shows every change it made.
