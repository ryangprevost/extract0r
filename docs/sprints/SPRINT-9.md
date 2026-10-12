# Sprint 9 — automation

Opened 2026-10-12 from Ryan:

> go ahead with automation next

---

## What was built — X0R-1390

| | |
|---|---|
| **Lanes** | In the mixer, *Automation*: pick a setting - level, pan, low cut, high cut, reverb, delay - and a part, and a lane opens along the song in bars. Click to add a point (on the beat), drag to move it, double-click to remove it. |
| **Shapes from the playhead** | Each lane offers the two moves a producer reaches for, starting where the song is playing, over 1-16 bars: *Fade in / Fade out*, *Sweep left to right*, *Thin out / Fill back in*, *Open up / Close down*, *Wash in / Dry out*. |
| **Heard live** | Each lane is scheduled on its Web Audio parameter from the playhead - a value now, then a ramp to every point to come - and rescheduled the moment a point moves. Mute and solo moved to their own stage so they never fight a moving fader. |
| **Bounced the same** | `ChannelIn.automation` - `{setting: [[beat, value], ...]}`, validated (known settings, no point before the first beat, 256 points a lane) - rendered by `mixer.curve`, `pan_moving` and `sweep`. The account: *"Bass: level, high cut moving over the song."* |

Points are in **beats from the version's first beat** - the bounce now reports where that
is - so a point drawn on bar 9 is on bar 9.

---

## How it moves, and why it matches

* Between two points a setting moves in a straight line and holds before the first and after
  the last - exactly what an AudioParam does with `setValueAtTime` and a ramp per point.
* **Level ramps in linear gain**, as a GainNode's does; -60 dB is off.
* **Cuts sweep exponentially** - evenly in pitch, which is how a filter sweep is heard - with
  `exponentialRampToValueAtTime` on the page and the same curve on the server.
* **A moving filter** recomputes its coefficients every 16 samples and carries its past
  across each change as direct-form-I state - inputs and outputs, as a BiquadFilterNode
  holds it. Held at one cutoff it is the fixed filter exactly (tested to 1e-9), so a sweep
  never clicks.

**Measured, heard against bounced**, with five lanes at once on the demo - a bass fade-in, a
high cut opening on the rest, the beat panned left to right, the guitar's reverb washing in,
the keys' low cut sweeping: **-90 dB**.

---

## A note on testing against the real server

One browser test opened the wrong track - a song and reference uploaded at 11:51 that
someone was using at the same time - and bounced a test version into its exports
(`version.same.*` and its layers). Nothing of the song, its stems or its reference was
touched; the file is left in place rather than risk deleting a version that was not ours.
Every test since names the demo track by id. The lesson for these sessions: *pick tracks by
id, never by position in a list a person might be adding to.*

---

## Still open

1. Saving a mix (and its automation) to reuse on another version.
2. Automation on the master, and on the build/drop layer's own sweep.
3. Velocity editing in the piano roll; a two-bar step grid; shaping uploaded samples.
