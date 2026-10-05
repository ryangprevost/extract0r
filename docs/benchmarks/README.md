# Benchmarks

Every file in this folder is the output of one run of `services/api/tools/benchmark.py`,
in a pair: a `.md` to read and a `.json` to diff against the next run. Nothing here is
hand-written except this page.

**Why the folder exists.** Sprint 1 finished with every backend running and nobody able to
say whether any of it was accurate. The end-to-end run returned a bass line an octave high
and a tempo of 60 against a true 120 — and a controlled check showed pYIN reads those notes
correctly from the *unseparated* signal, so the fault was in feeding Demucs synthetic sine
waves it was never trained on. Until a model change can be scored, every threshold in the
stack is a guess and every improvement is a vibe. That is X0R-306.

**The one rule.** *Synthetic audio cannot measure quality.* It exercises the wiring and
nothing else. `tools/verify_pipeline.py` is for wiring and says so; nothing in this folder
should ever come from generated audio.

---

## What gets measured

| | what it answers | needs |
|---|---|---|
| **SDR / SIR / SAR** | how clean the separation is, and whether the error is leakage or invention | ground-truth stems |
| **Per-drum SIR** | how much of a kick is in the snare file — the bleed figure sprint 2 ships without | isolated close-miked drums |
| **Note P / R / F1** | how much of the part the transcriber got, with and without octave tolerance | a ground-truth note list |
| **Cents error** | how far off the pitches are, over notes matched by onset alone | the same note list |
| **Reconstruction** | how much energy separation lost, as a residual under the mixture | nothing but a mixture |
| **× real time** | how long a three-minute song takes | nothing but a mixture |

The last two rows are why the tool runs with no eval set at all. The other four are why a
run without one leads with what it could not measure.

**Reconstruction is the weaker question and is labelled as such wherever it appears.** It
needs no ground truth, so it is on every run — including a song a user uploaded five
minutes ago — and it is the number `preserve_source` exists because of. But a separator
that put the whole bass in the vocals file would reconstruct the mixture perfectly and
score well on it. It bounds what was lost; SDR is what says whether the rest went in the
right file.

### Three choices that make these numbers mean something

**The permutation is fixed.** BSS Eval will by default try every assignment of estimates to
references and keep the best. That is right for blind separation and wrong here: a model
that filed the bass under `other` has failed, and searching the permutation would say it
had not.

**Long tracks are scored in thirty-second windows and the median is reported.** BSS Eval
solves a least-squares projection whose cost grows with the square of the length. Thirty
seconds is SiSEC's window, and the median survives the one window where a stem is silent.

**Cents accuracy is measured over notes matched by *onset*, not by pitch.** Matching on
pitch and then measuring pitch is circular — the answer can never exceed the tolerance, so
it always looks reassuring. The question worth asking is: for the notes it found at the
right time, how far off was it?

All three are tested in `tests/test_benchmark.py`, against signals whose answers are known
on paper. That file is the one place synthetic audio belongs: it measures the ruler, and
Demucs has nothing to do with the question.

---

## What the first runs showed

Two models over one real three-minute track, on CPU, run twice each in both orders. No
ground truth yet, so this is reconstruction and speed only.

| model | stems | reconstruction | × real time |
|---|---:|---:|---:|
| `htdemucs` | 4 | **−27.08 dB** | 0.94× |
| `htdemucs_6s` | 6 | **−21.69 dB** | 1.24× |

**The six-stem model is the faster one.** That is the opposite of what I expected, and it
held across both runs in both orders, so it is not the laptop. I do not know why, and the
honest thing is to leave it as a measurement rather than invent a mechanism for it.

**Splitting into six loses more of the track than splitting into four**, by 5.4 dB. That
direction is unsurprising — more sources means more places for energy to be dropped or
double-counted — but the size is worth knowing, because the product uses the six-stem
model by default to get piano and guitar, and this is what that costs. The two figures
bracket the **−25.6 dB** that `docs/API.md` and the Studio have been quoting from an
earlier one-off measurement, which is the first independent support that number has had.

**Reconstruction repeated to the decimal place across runs; speed moved by 14%.** Treat a
small timing change as noise and a small reconstruction change as real.

What none of this says is whether any instrument ended up in the right file. That needs
ground truth, and the table above is exactly what a benchmark looks like without it.

---

## Building an eval set

> **If you take the MUSDB18 route, read X0R-308 first.** The figures this tool produces
> are BSS Eval **v3** (`bss_eval_sources`, mono downmix) and will not line up with the
> MUSDB18 leaderboard, which is v4. That is a deliberate deferral, not an oversight, and
> the card says what to do about it.

**The fastest route to ground truth is not a dataset.** MUSDB18 is the standard, and it is
also 22 GB, CC BY-NC-SA, and has to be accepted and downloaded by a person. A DI bass
played to a click gives an exact reference stem *and* an exact note list, takes twenty
minutes, and sidesteps the licensing question entirely — which is what X0R-306 said when
it was written.

A set is a folder. Only `mixture.wav` is required.

```
<eval-set>/
  manifest.json
  <track-id>/
    mixture.wav                 the file the separator is run on
    stems/vocals.wav            ground truth, named for StemKind
    stems/bass.wav              ... two or more, or there is no SIR
    drums/kick.wav              isolated drums, for the bleed figure
    drums/snare.wav             ... kick, snare, cymbals, toms
    notes/bass.csv              onset_s,offset_s,midi — one note a line
```

`manifest.json` carries the provenance, which is not optional in any sense that matters.
Six months from now the only question about an SDR of 6.1 dB is *on what*, and a number
whose source and license are not written beside it cannot be reproduced or defended.

```json
{
  "name": "di-parts-2026",
  "source": "DI bass and guitar recorded 2026-10-12, drums from a sample kit",
  "license": "mine; not redistributed",
  "notes": "Bass tuned to A=440. Note times from the DAW, so exact.",
  "tracks": [
    { "id": "one", "seconds": 184.0, "caveats": ["the guitar take has bleed from the room"] }
  ]
}
```

A set with no manifest still runs. It gets an empty `source` and `license`, and the report
says so rather than letting an unattributed number through looking like an attributed one.

### What to record, in the order it is worth doing

1. **A DI bass to a click.** One part, two minutes. Gives a reference stem, an exact note
   list, and the pitch-in-cents figure X0R-1320 currently ships as a caveated upper bound.
   Bass first because pYIN is monophonic and this is where the octave errors live.
2. **A DI guitar over the same click.** Now there are two stems, so SDR and SIR are real.
3. **Drums with the kick, snare and overheads on separate tracks.** This is the only way to
   get the per-drum bleed number, and it is the single most load-bearing unmeasured
   quantity in the project — every per-drum finding on the comparison screen currently says
   "some of this may be another drum" and cannot say how much.
4. **A sung DI vocal.** Answers what pYIN's own pitch error is through Demucs, separately
   from the singer's.

Each step is usable on its own; none of them needs the next one.

---

## Running it

```bash
cd services/api
~/.x0r-venv/Scripts/python.exe tools/benchmark.py --eval-set <folder>
```

From the ML virtualenv, not the app one — from the app venv `make_separator` falls back to
the stub, and a run that measured the stub and wrote it here is exactly the failure this
card exists to stop. The tool defaults to the real backends rather than to the configured
ones for the same reason, says which ran in the report header, and puts a line in
**Skipped** when the fallback happened anyway.

Useful flags: `--model htdemucs` for the faster four-stem split, `--track <id>` to run one,
`--backend stub` to test the harness itself.
