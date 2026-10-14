# Sprint 22 — a DAW's piano roll, and tuning a sampled sound

Opened 2026-10-14 from Ryan:

> please allow for easier MIDI editing. id like to extend all notes to butt up against other
> notes after quantizing. i want this to feel more like a DAW as opposed to clunky clicking.
> maybe an option to extend notes to 1/8, 1/4, 1/2, whole, etc. something more of a bulk
> action than it currently is.

> also the ability to fine tune the EQ, length, pitch, etc on an extracted sample from the
> reference song would be great

---

## 1. The piano roll, as a DAW has it — X0R-1490

**Two tools, as in Ableton and FL:**

- **Select (V), the new default.** Drag across empty space for a dashed box that selects
  every note it touches (Shift adds to the selection). Double-click empty space to add a note.
- **Draw (B).** Click to add a note, as before.

**Bulk lengths** - on the selected notes, or on all of them when none are selected:

- **1/16, 1/8, 1/4, 1/2 and 1 bar,** each in one press.
- **Fill to next (L).** Each note runs exactly into the next note in the part: gaps closed,
  overlaps trimmed, a chord's notes together. The last note keeps its length, and none runs
  past two bars. Unlike the earlier Legato, it shortens as well as lengthens, which is what
  "butt up" means in a DAW.
- **Quantize + fill:** quantize, then fill, in one press - the move Ryan described.

**Keys:**

| Keys | Does |
|---|---|
| Shift+←/→ | Shorten or lengthen by the grid |
| Ctrl+C / Ctrl+V | Copy / paste (after the selection) |
| Ctrl+D | Duplicate the selection after itself |
| Q | Quantize |
| L | Fill to next |
| V / B | Select / Draw tool |
| Esc | Deselect |
| Ctrl+scroll | Zoom in time |

These sit alongside the existing Delete, arrows, Ctrl+A and Ctrl+Z.

Checked in the browser on the demo track:

- a box dragged over a note selected exactly that note;
- 1/8 set every note's length;
- fill ran 4 notes into the next;
- Ctrl+A, Ctrl+D (5 → 10 notes), Ctrl+Z (back to 5), Esc and Quantize + fill all worked.

## 2. Tuning a sampled sound — X0R-1491

Each sound sampled from the reference has a **Tune** panel, under *Your sampled sounds* in
the sampler box:

- **Pitch:** semitones, plus fine tune in cents.
- **Start:** skip into each recording, past a messy attack.
- **Attack:** a fade-in.
- **Length:** cut every note at a set length, or let it ring as played.
- **Release:** how long a note fades after it ends.
- **EQ:** low cut, high cut, and bass (200 Hz) and treble (4 kHz) shelves.

Moving a slider previews the sound 0.35 s later. **Keep** saves the settings, **Reset** goes
back to the sound as sampled, and **Play the parts on it again** re-renders every part that
uses it.

**Non-destructive.** The settings live in the instrument's `tweak` and are applied whenever
it plays (`instruments.clean_tweak`, `tweak_recording`, `tweak_tone`). The recordings are
never changed.

**The EQ comes after the pitching, as in a sampler.** It was first applied to each
recording before the note was pitched, so a note an octave up moved a 1 kHz cut to 2 kHz.
The test caught it.

**Routes:** `POST /tracks/instruments/{name}/preview` and `PUT
/tracks/instruments/{name}/tweak`.

**Checked:**

- **Tests:**
  - settings are clamped into their ranges;
  - an untuned sound plays as sampled;
  - +12 semitones gives an octave;
  - a 0.2 s length with no release is silent after 0.25 s;
  - a 1 kHz high cut leaves under 2% of the power above 3 kHz;
  - preview, keep and reset through the API.
- **In the browser,** on a bass sampled from the demo's reference: tuned to +15 cents, a
  3 kHz high cut and 0.4 s notes; previewed, kept, then reset.

## 3. VaVaVa regenerated: filled notes, better-tuned samples

Ryan:

> can you regenerate the vavava sample i was working on with extended midi notes and a better
> tuned synth sample for both bass and synth mstrkrft mappings to vavava bass and guitar?

**Measured first** (pitch over each recording's held part, where its attack lands, energy
above 6 kHz, and rumble below the fundamental):

- **The MSTRKRFT bass is sound.** Every note is within about 3 cents and the top is clean.
  Several notes have rumble under the fundamental (kick bleed from the separation, up to
  -22 dB). Its settings now: a 30 Hz low cut, a 5 kHz high cut against hat bleed, a 2 ms
  attack and a 60 ms release.
- **The MSTRKRFT synth had two bad recordings out of five.** A#2 is only 0.62 s long, too
  short to hold an extended note, and its top end is hat bleed at -7 dB. F#1 is mostly noise
  and does not read as a pitch. F4 and F5 are clean, last 3+ s, and are within 10 cents.
  So **"MSTRKRFT Bounce synth 3"** keeps just F4 and F5, with a 150 Hz low cut (off the
  bass), a 9 kHz high cut, a 5 ms attack and a 180 ms release, so filled notes join
  smoothly. `octaves_to_fit` plays the chords an octave up, near the recordings.

**Extended notes:** the bass, guitar chords and lead are quantized and filled into the next
note (`edit.fill`, now also `fill` on the quantize route - the piano roll's Fill to next,
server-side). Average length went to 1.87 beats on the bass and 1.95 on the chords and the
lead. The stabs stay short.

Everything else is as in the version Ryan liked: arrangement, chops, stabs, levels matched
to "Bounce", and the master at -9.6/-9.7 LUFS.
