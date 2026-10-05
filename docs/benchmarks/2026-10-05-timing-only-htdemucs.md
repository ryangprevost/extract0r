# Benchmark — timing only

**Ran:** 2026-10-05T14:14:46+00:00  
**Commit:** 3650ca8 (working tree dirty)  
**Machine:** Windows 11, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Python 3.12.10  
**Separation:** demucs `htdemucs`  
**Transcription:** auto  
**Recordings:** a real 28.0 s recording from the Experiment 2 pair, laid end to end  
**Licence:** Ryan's own copy; not redistributed and not part of the repository

| package | version |
|---|---|
| demucs | 4.1.0 |
| torch | 2.13.0+cpu |
| librosa | 1.0.0 |
| mir_eval | 0.8.2 |
| numpy | 2.5.2 |
| onnxruntime | 1.29.0 |
| soundfile | 0.14.0 |

## What this run could not measure

Above the results on purpose. A benchmark that reports only what it managed looks complete, and that is the most misleading thing it could do.

- No track has two or more ground-truth stems, so there is no SDR, SIR or SAR. Put the stems in `<track>/stems/<vocals|drums|bass|...>.wav`.
- No track has a ground-truth note list, so there is no note F1 and no cents accuracy. Put one in `<track>/notes/<stem>.csv` as `onset_s,offset_s,midi`. A DI part played to a click gives this exactly.
- No track has isolated drums, so DrumSep's per-stem bleed stays unmeasured - which is the figure every per-drum finding in sprint 2 is currently caveating without. Put close-miked kick, snare, cymbals and toms in `<track>/drums/`, or record four passes of one kit.

## Reconstruction — what separation lost

How far the stems sum away from the track they came out of. **More negative is better**: -25 dB means what the stems failed to account for sits 25 dB under the mixture. This needs no ground truth, which is why it is here on every run — and why it is the weaker question. A separator that put the whole bass in the vocals file would reconstruct the mixture perfectly and score well here. It bounds what was lost; SDR is what says whether the rest went in the right file.

| track | residual |
|---|---:|
| three-minutes | -27.08 dB |

## Speed

As a multiple of real time, which is the only form anybody plans around. Above 1 is faster than the music.

**The first run of a model includes fetching its weights**, which is a download and not a separation. Run a model once before you time it.

**Read a small change as noise.** The same three-minute track and the same model came back at 1.09x and then 1.24x on this machine on one afternoon - a 14% spread, whose only cause was what else the laptop was doing. A speed result is worth acting on when it moves the figure by more than that. Reconstruction, by contrast, repeated to the decimal place, so a change there is real.

| track | stage | audio | wall clock | × real time |
|---|---|---:|---:|---:|
| three-minutes | separation | 180.0 s | 192.6 s | 0.94× |


## Caveats carried by the recordings themselves

- **three-minutes** — a 28.0 s recording repeated to 180 s; timing is valid, nothing else is
