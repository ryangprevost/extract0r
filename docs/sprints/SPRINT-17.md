# Sprint 17 — punch and width

Opened 2026-10-13 from Ryan, on the gritty remix:

> much better! can you redo it with a punchier kick and some stereo wideness? also make the
> snare more punchy and direct. it's getting there for sure

---

## 1. Width — X0R-1471

The sampled and multisampled synths render in **mono**, so every synth sat in the middle, on
top of the vocal and the kick. `synth/width.py` spreads a part the way a stereo synth patch
does:

- **The side signal.** The part's mono sum stays the middle. Two copies of it go through
  short delays (8 and 11 ms) that drift slowly (0.31 and 0.37 Hz, 1 ms deep), and their
  difference is added left and subtracted right.
- **Mono-safe.** Summed to mono it is exactly the part as it was (error 1e-16), so a club's
  mono system never hears the comb filtering a plain Haas delay leaves.
- **Low end centered.** The side is high-passed at 150 Hz; at 55 Hz it sits 29 dB under its
  level at 220 Hz.

`BounceRequest.width` takes `{stem: 0..1}` and is applied after grit (a distorted synth is
spread, rather than a spread one distorted). The account says so, there is a width slider
on every part row, and it is tested in `test_width.py`.

On the remix: synths at 75–85% width moved the whole mix's side from -16.7 to -9.8 dB against
the middle, and its left/right correlation from 0.96 to 0.81.

## 2. Punch — a shaped kit, measured

The punch was measured as the share of each hit's energy in its first 30 ms, plus how long
it takes to fall 20 dB:

| drum | edm kit (before) | punchy kit | **club punch** |
|---|---|---|---|
| kick, front | 23% | 43% | **40%** |
| kick, to -20 dB | 475 ms | 232 ms | **254 ms**, 98% of it in 30–100 Hz |
| snare, front | 16% | 90% | **90%** |
| snare, to -20 dB | 161 ms | 61 ms | **61 ms** |

**club punch** is the punchy kit with the kick's punch, snap and length up and its tune
lowered a little, saved through the ordinary shaped-sound route. It sits in every kit list.
The pump went from 8 to 10 dB, so the synths clear out of the kick's way.

## 3. The finish

A clean limiter could not make the punchier mix loud. Reaching -10.6 LUFS took up to 12.5 dB
of gain riding on the kicks, which flattens exactly the punch that was asked for. Club
masters put a **soft clipper** before the limiter instead: it shaves only the tips of the
transients. That is 0.3% of samples clipped by more than 3.5 dB, and the limiter then
averages 0.2 dB. Both cuts finish at -10.6/-10.7 LUFS with the true peak at -1 dBTP. This
finish is a one-off script for the remix, not yet a feature of the app.
