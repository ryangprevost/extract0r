# Sprint 14 — no more stalls while mixing, and velocity

Opened 2026-10-12 from Ryan:

> go ahead with velocity editing in the piano roll next. its getting better but i want it to
> not time out when im mixing things. getting a little frustrating.

---

## 1. The stalls — X0R-1451

Ryan bounced a six-minute song while this was asked. The API log and the export folder's file
times showed where the time went:

| step | took |
|---|---|
| the WAV | written by 16:54:09 |
| **the MP3** | **16:54:09 → 16:57:39, three and a half minutes** |
| the eight FLAC layers | about 15 seconds |

The MP3 is not slow because of LAME, which takes about 19 seconds for six minutes. It is slow
because, before LAME, the song is turned into 16-bit with **noise-shaped dither**. Each sample's
rounding depends on the error left by the one before it, so this was a plain Python loop over
every sample: about 32 million steps. Its own comment said it cost "a fraction of a second".
Worse, the loop **held Python's interpreter lock**, so every other request waited behind it:
the mixer, the audio it streams, the page asking how the job was going. That is what felt like
the site timing out. The same step runs **every time a mix is applied to a version**.

The same pattern was in two more places:

- **A moving filter** (automation of the low or high cut) recomputed its coefficients and
  called scipy once per 16-sample block. That is a million calls for a six-minute song,
  measured at **2.5-3.5 minutes** per automated filter.
- **Every change of sound on a part transcribed the stem again.** Trying three synths on one
  part paid for three identical transcriptions.

What changed:

- `mixdown/dither.py` — the error-feedback loop is compiled with **numba** (already installed
  with librosa) as `nogil`, so it also lets other requests run. The output is **bit-for-bit
  identical** to the old loop, measured on noise with a fade. 2 s → 0.013 s for 5 s of stereo:
  **about 1 s for a six-minute song instead of 2.5-3.5 minutes**. Where numba is not installed
  (the CI image), a loop over plain Python floats does the same arithmetic about 8x faster
  than the old one.
- `synth/mixer.py` `sweep` — the same treatment: coefficients for every block at once, then
  one compiled direct-form-I loop. It matches the scipy path to 3×10⁻¹⁴. A six-minute filter
  sweep goes from 141-219 s to under a second. Without numba, the scipy path is kept.
- `routes_master._transcribe` — a stem's notes are kept as `<stem>.notes.json` **beside the
  stem in the track's storage** (never the repository), keyed on the stem file's size and
  modification time and the transcriber. A new separation or another transcriber reads them
  afresh. Used by re-voicing, the version MIDI and the parts MIDI.

My own full test run was also competing with the server for CPU while Ryan mixed. It was
stopped, and the suite now runs at below-normal priority while he may be using the app.

## 2. Velocity — X0R-1450

The server already kept velocity per note, counted a velocity change as an edit, and every
renderer plays a note at velocity/127 of full level. The piano roll could not change it.

- **A velocity lane** under the roll, one stick per note, with guides at 127, 64 (about -6 dB)
  and 32 (about -12 dB).
  - **Drag a stick** to make that note harder or softer. If several notes are selected, they
    all move by the same amount, so the phrasing between them is kept.
  - **Drag across empty space** to draw: every note the pointer passes takes the height it is
    at, so a crescendo is one stroke. Shift keeps it to the selected notes.
- **Tools** apply to the selected notes, or to all of them:
  - **Set** gives them one velocity.
  - **Softer** / **Louder** scale them by 0.85 / 1.15 (about 1.4 dB / 1.2 dB), keeping their
    differences.
  - **Even out** pulls them halfway to their average.
  - **Humanize** moves each a few steps either way.
- **Alt+Up / Alt+Down** changes velocity in steps of 4 (16 with Shift).
- A new note takes the velocity in the box, else the part's usual velocity rather than a flat 100.
- The count line shows the selected notes' velocity range.

## 3. Saving to "null" — X0R-1452

The log also showed `PUT /parts/null/notes` rejected while Ryan edited. Closing the editor
cleared which part it was on, so an editor still on screen had no part to save to. Whether
the editor is showing and which part it edits are now kept separately, and Save and "Back to
as played" do nothing without a part.

## 4. Checked

- Dither: old vs new loops identical to the sample (numba and plain); sweep within 3×10⁻¹⁴ of
  scipy; a kept transcription is read back and a changed stem file is transcribed again.
  These are new tests in `test_dither.py`, `test_mixer.py` and `test_revoice_api.py`. Every
  test touching dither, MP3 export or the mixer passes with numba (74).
- In the browser, on the demo track only and without saving: dragged a stick (94 → 33), drew
  a ramp, and used Set, Softer, Louder, Even out, Humanize, Alt+Up and Undo.
- API restarted once, after the log showed Ryan's bounce had finished and nothing of his was
  running.
