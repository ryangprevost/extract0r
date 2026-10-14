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
