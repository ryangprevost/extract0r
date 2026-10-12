# Sprint 8 — shape the sounds

Opened 2026-10-12 from Ryan:

> go ahead with shaping the sounds next

The last of the four kinds of "more manipulation" he listed after Sprint 4: rearrange the song
(Sprint 5), edit notes and beats (6), mix each part (7), and now shape the sounds.

---

## What was built — X0R-1380

| | |
|---|---|
| **Knobs** | Eight on every synth voice - brightness, attack, length, sustain, width, drive, pluck, weight - and five on every drum of every kit - tune, length, snap, tone, punch. Each runs -1 to +1, 0 is the stock sound exactly, and each is named for what is heard, with its two ends in words ("Darker ↔ brighter"). `synth/shape.py`. |
| **Hear it as you turn** | `POST /tracks/sounds/preview` renders the phrase a voice is previewed on, or two bars of a beat for a kit, with the same engine that plays your parts. The page re-renders a moment after a knob stops and plays it. |
| **Keep it** | `POST /tracks/sounds` saves a name, a base and knob positions - a few bytes of JSON in `samples/sounds/`, outside the repository like your kits. A kept voice is in every part's voice list; a kept kit plays drum parts and added beats anywhere a built-in kit does. Described in words: *"the 808, brighter, longer"*. |
| **API** | `GET /tracks/sounds`, `POST /tracks/sounds/preview`, `POST /tracks/sounds`, `DELETE /tracks/sounds/{name}`; `/voices` and `/library` list your sounds. |

---

## Every shaped voice still plays its note — found and fixed

`test_synth` holds the built-in voices to one rule: the loudest partial is the note asked for,
within 3%. The shaped voices are held to it at every extreme - every knob alone at -1 and +1,
and all of them together - at four pitches. The first version failed it nine times:

* **Weight added a sub-octave**, and on the stacked voices (supersaw, pad, pluck) the detuned
  copies partly cancel at the fundamental - so the sub won, and the supersaw at +1 weight
  peaked an octave low at middle C. Weight now lifts the voice's own fundamental and second
  harmonic, and adds a sub-octave only to single-copy voices.
* **Brightness tilted uncapped**, and the pad's octave came out louder than its note.
  Brighter now lifts upper harmonics to at most 0.55 of the fundamental; the stock saws sit
  at 0.5.
* **Width went to 55 cents**, where the copies themselves are 3% off the note. It now stops
  at 30.

What was *not* a fix: a shortened reese read 0.966 at 65 Hz in a 0.6 s window. Its copies sit
1.3% either side of the note and the window's bins are 1.7 Hz apart - bin spacing, not a wrong
note. The shaped-voice test uses a 1.2 s note, said so in the test.

---

## Where "more manipulation" stands

All four kinds Ryan named are built. Open, smaller:

1. Automation - a fader or a knob that moves over time.
2. Saving a mix to reuse on another version.
3. Velocity editing in the piano roll; a two-bar step grid.
4. Shaping a sample you uploaded (gain, pitch, start, length) the way a built-in is shaped.
