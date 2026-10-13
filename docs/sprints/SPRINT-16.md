# Sprint 16 — grit, and a chorus-only club remix

Opened 2026-10-13 from Ryan, after the first club remix of VaVaVa:

> make the synths more like bounce.mp3. i want gritty, distorted synths. this is a decent
> foundation but not what im looking for. also, no need to keep the verses in here, mix up
> the chorus and keep the instrumental.

---

## 1. Grit — X0R-1470

`synth/grit.py` drives a part into distortion:

- **Oversampled 2x**, so the new harmonics do not fold back as fizz.
- **An asymmetric `tanh` clipper.** Its input is offset, so one side of the wave clips sooner
  than the other, which gives even harmonics as well as odd. On a 220 Hz sine at 60%, the
  2nd harmonic comes in at -24 dB and the 3rd at -10 dB.
- **A gentle low-pass**, then DC removal.
- **Level matched** to the part as it went in, so the control changes the sound, not the
  volume.

How it reaches the version:

- `BounceRequest.grit` takes `{stem: 0..1}`. It is applied to the part as it will be heard
  (its re-played render, else the stem) before anything is stretched, pumped or summed.
- The account names it: *"Driven into distortion (grit): bass 50%, guitar 60% ..."*.
- Each part row on the remix page has a **grit** slider. It is heard in the version, not in
  the part's own player.

**Not measured, on purpose.** The first version matched the amount to the reference part,
first by crest factor, then by the share of energy above 2 kHz. On VaVaVa against "Bounce",
neither told their synths from ours. A separated stem is several layers plus leakage and
attacks, and those decide both numbers: their synth stem read as *less* squashed and *duller*
than a clean pad. A "match their grit" button that cannot actually match would be a false
reassurance, so the amount is set by ear. Their exact tone comes from sampling it (Sprint 15).

## 2. A test deleted a real sampled instrument — fixed

`DELETE /tracks/{id}` read `get_settings()` directly. Under the test suite that paired the
test's temporary storage with the real samples folder, and the suite deleted the sampled
MSTRKRFT bass as an orphan. The route now uses the injected settings, and each sampled
instrument records the storage it was made in; `forget_missing` only ever judges it against
that storage.

## 3. The remix Ryan asked for

Built on a **copy** of VaVaVa's track, with this sprint's code in its own process, so the
running server and Ryan's own version 169 (which he was listening to) were untouched.

- **Synths** (also listed in each version's account):
  - **Bass:** MSTRKRFT's bass, sampled, 50% grit.
  - **Guitars and keys:** their synth (sampled from the reference's other part: F#1, A#1,
    A#2, F5), 60% grit.
  - **Other:** synth strings, 35% grit.
- **Beat:** house groove, edm kit, pump; the band's drums out. Tempo stays at 169 BPM.
- **Arrangement:** no verses; 84 bars, about 2:00, in 12 blocks:
  1. intro
  2. a vocal-less, beat-less chorus teaser
  3. drop into the hook
  4. the first chorus
  5. the bridge as a beat-free breakdown, then the beat builds back
  6. drop into the final chorus
  7. an instrumental chorus tag
  8. the hook again
  9. outro
- **Two cuts:**
  - with the chorus vocals;
  - fully instrumental.
- **Finish:** a quick club finish to -10.4 LUFS, true peak -1 dBTP, limiter averaging 1.2 dB.
  The grit makes inter-sample peaks, which costs about a dB against the first remix at the
  same peak ceiling.
