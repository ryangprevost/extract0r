# Sprint 7 — mix each part

Opened 2026-10-12 from Ryan:

> go ahead with mixing each part next

---

## What was built — X0R-1370

| | |
|---|---|
| **Layers** | *Make the version* now also keeps every layer of the version on its own - each part, the added beat, the builds and drops - at the version's tempo and arrangement, scaled so that a flat mix of them **is** the bounced file. |
| **Live mixer** | A strip per layer: level (to off), pan, mute, solo, low cut, high cut, reverb send, delay send. Heard while it plays, with Web Audio; play, pause, stop and a position bar. |
| **Bounce this mix** | `POST /tracks/{id}/version/{label}/mix` mixes the saved layers on the server - nothing is played or stretched again, so it takes seconds - and the account says what was done: *"Bass: panned 40% left." "Drums: muted."* |
| **One reverb, one delay** | Shared buses, post-fader sends, as on a desk. The delay is a dotted eighth at the version's tempo; the reverb's impulse is generated on the server and served to the page. |

`synth/mixer.py`, `apps/studio/wwwroot/mixer.js`.

---

## What is heard is what is bounced — measured

Every component was checked by rendering the same mix in the browser (an `OfflineAudioContext`
built exactly as the page builds its graph) and comparing it, sample for sample, with the
server's bounce of the same settings:

| | first try | after |
|---|---:|---:|
| flat | -16.8 dB | **-92.5 dB** |
| level and pan | | **-92.6 dB** |
| low cut 120 Hz | -15.3 dB | **-94.3 dB** |
| high cut 3 kHz | | **-92.4 dB** |
| delay | -31.3 dB | **-87.5 dB** |
| reverb | | **-92.3 dB** |
| all of it at once | -14.6 dB | **-84.8 dB** |

Each "first try" was a real mismatch between the browser and the server, and each is the
kind of thing that would have made the mixer quietly lie:

* **"Off" was not off.** The page parked an unused low cut at 10 Hz. It barely moves the
  level, but it turns the phase of an 808's sub - enough for a flat mix to differ by -16.8 dB.
  An unused filter is now out of the chain.
* **Web Audio's Q is in decibels** for low and high pass (the spec's alpha_QdB). The obvious
  `Q = 0.707` is a ratio of 1.085 - a slightly peaky filter. The page now sets -3.01 dB, the
  flat Butterworth the server uses.
* **Chromium adds 128 samples to a delay inside a feedback loop.** The second echo of a
  15504-sample delay came at 31136, not 31008, drifting further on every repeat. The page
  now builds the delay from two delays - first echo outside the loop, repeats inside it,
  shortened by the loop latency the browser is *measured* to add at load.
* **The bottom of the fader** played silence on the page and -60 dB in the file.

---

## Still open

1. **Shape the sounds** - knobs on each synth and kit.
2. Automation (a fader that moves over time), and saving a mix to reuse on another version.
3. Velocity editing in the piano roll; a two-bar step grid (from Sprint 6).
