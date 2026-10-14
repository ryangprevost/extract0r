# Sprint 21 — Describe it

Opened 2026-10-14 from Ryan:

> I guess I'm looking for something generative like Suno that takes prompts and uses a
> reference track

> keep it free for now but allow architecture to easily switch to the API as needed.

---

## 1. Not a generator - a recipe — X0R-1480

Suno generates new audio from a model trained on other people's records. This makes nothing
new. A sentence is read into a **recipe**, a fixed set of this app's own controls:

- style, tempo, beat and kit;
- per part: grit, width and pump depth;
- a gritty lead over clean chords, and stabs;
- tidy, follow the bass, and legato;
- how many chops, and whether they go on the instruments;
- the arrangement: which parts are left out, which are subdued, where the drop is;
- parts left out of the version;
- the reference's own sampled sounds, and the reference's levels.

The page then sets those controls and makes the version the ordinary way. Everything it
chose is a control the person can see and change afterwards. That is `mastering/ask.py`'s
rule for words: the words choose the control.

**On the page:** a **Describe it** box at the top of the remix page.

- **Read it** shows what each phrase set and lists the words it did not use.
- **Make it** then:
  1. sets the part sounds, grit and width;
  2. plays each part once, so it has notes to edit;
  3. tidies the notes, puts them on the bass's chords, cuts the lead and stabs from the
     chords, and holds them;
  4. plays the parts again;
  5. sets the beat, kit and pump, the arrangement and the chops;
  6. makes the version;
  7. matches the reference's levels and re-bounces the mix.

## 2. Two readers, one recipe

`synth/describe.py`:

- **`VocabularyReader`, the default.** Free, offline and deterministic (tested: the same
  words make the same recipe). It knows genre words (complextro, electro, madeon, house,
  half-time...), textures, parts, chops, the song's *own* section labels and tempo, and
  says which words it did not use.
- **`ClaudeReader`, built but off.** It asks Claude to fill the recipe's JSON schema, given
  the song's labels, styles and kits, and validates the answer as a `Recipe` before anything
  uses it - it can only choose controls that exist. Switch it on with `PROMPT_READER=claude`,
  `ANTHROPIC_API_KEY` and, optionally, `PROMPT_MODEL` in the local `.env`. Every prompt is
  then billed to that key. It is tested with a fake client; it has not been run against the
  live API.

`reader_for(settings)` chooses one, and falls back to the vocabulary unless Claude is both
asked for and has a key.

Section labels are matched as whole words, longest first: "chorus" is not the "chorus" in
"post-chorus". Commas end a clause, so "subdued, drop into the chorus" does not read as a
subdued chorus.

## 3. The reference's levels — X0R-1475

`synth/levels.py` and `POST /tracks/{id}/version/{label}/match-levels`, plus a **Match the
reference's levels** button on the version mixer.

- Each group (drums, bass, synths, vocals) is measured against its bass, in the reference's
  stems and in the version's layers. The difference is the fader move, held within the
  mixer's -24..+12 dB.
- A group more than 30 LU under its bass is "hardly there" and is left alone. The demo's
  near-empty vocal stem would otherwise have been turned up 5 dB.

## 4. Checked

- **Tests:** genre words, whole-word labels, tempo, unused words, determinism, the Claude
  reader with a fake client, the reader switch, the level moves, absent groups, and stabs
  keeping their grit.
- **In the browser,** on a freshly generated demo song and house reference (the old demo
  had been removed by retention), not on Ryan's tracks:
  - The prompt *"complextro, gritty lead over clean chords, wide, punchy kick, chops on the
    instruments, levels like the reference, keep the tempo, sparkly"* read correctly;
    "sparkly" was reported unused.
  - **Make it** ran end to end: parts re-voiced and edited, beat and chops set, version
    made, levels matched (synths -12.5 dB, drums -5.9 dB, the near-empty vocal left alone),
    mix re-bounced.
- **Fixed on the way:**
  - Clean chords had made the stabs clean.
  - A sampled sound from another song's reference was picked up. Sampled sounds now only
    come from this track's own reference, and only when asked for.
