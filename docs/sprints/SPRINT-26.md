# Sprint 26 — a style is a whole recipe

Ryan:

> I'd like for the suggestion box to be more insightful and pick up more vocabulary. Like
> "extend the midi notes", "add suggested chops at key areas", make it more complextro or
> electro, etc. maybe have a style guideline with parameters of what make each type unique
> in the background. Styles like techno, trance, electro house, house, complextro, etc. have
> behind the scenes configs for each and use them as a starting point for the remix.

---

## 1. Each style carries its own config — X0R-1520

A style used to be a tempo, a beat, a kit, a pump flag and a list of sounds. So **"Make it
Complextro" produced none of the chopping, grit, width or note editing that complextro
actually is** - it set six things and stopped, and the rest was left to whatever the last
remix had done.

Every style now carries a **recipe**: the same shape `synth/describe.py` reads a sentence
into, holding everything that makes the genre itself - how hard each part is driven, how
wide it sits, how deep it ducks on the kick, whether the chords become stabs, whether a
single gritty line plays over clean chords, how the notes are tidied and held, how much the
track is chopped, and whether it swings.

**Four new styles**, from Ryan's list: **Electro house**, **Complextro**, **Electro** and
**Techno**, beside the seven that existed. What separates them:

| style | tempo | beat | what it does to the parts |
|---|---|---|---|
| House | 120-126 | swung four on the floor | clean and warm, a light pump, offbeat stabs |
| Electro house | 126-130 | four on the floor | bass driven hard, lead stacked wide, deep pump |
| Complextro | 125-132 | sixteenth hats | the most chopped: stabs, rises, a gritty line over clean chords |
| Electro | 125-132 | four on the floor | distortion on everything, mid-forward, narrow |
| Techno | 130-140 | relentless sixteenths | dark and even: long notes, little harmony, gates |
| Trance | 134-142 | four on the floor | a rolling bass under supersaws held to the bar |

Complextro was previously read as "EDM, plus some extras", which is how a genre ends up
half-described. It is its own style now, and the test that pinned the old behaviour was
updated to say so.

**"Make it X" runs the whole recipe** through the same `applyRecipe` the Describe box uses,
so a style and a sentence that names it land in exactly the same place. Measured on the demo:
*Make it Complextro* set the techno beat and trap kit, grit at 50/65/50 on bass, keys and
other, widths of 100/80/35, five pump depths from 4 to 14 dB, stabs, a gritty lead over clean
chords, and chops on the instruments. *Make it Techno* set its own: gentler grit, a narrower
bass, shallower pumps and only a few chops.

## 2. A style you can read and argue with

Under the picker, **What makes this style itself** reads the config back out in sentences,
generated from the numbers rather than written beside them:

> Lives at 125-132 BPM, on a techno beat, trap kit. Driven hard: bass, keys, other. Spread
> wide: guitars, other (the low end stays centered). Ducks on the kick by 4-14 dB, and keeps
> pulsing where the beat drops out. Notes tidied onto the grid, moved onto the bass's chords,
> held into each other. A single gritty line over clean chords. The chords re-cut into short
> syncopated stabs. Chopped heavily at phrase ends, on the instruments as well as the whole
> track.

A preset that quietly changes eleven controls is a black box; one that says what it is about
to do is a starting point.

## 3. The suggestion box got more insightful, and wider

**One table of genres, not two.** `describe.py` had its own idea of what each genre meant,
beside the style picker's. It now reads the styles, with their aliases, so a word and a
button cannot drift apart and a style added in one place is understood in the other the same
day. Naming a genre brings its whole recipe - and the reply is the style's guide, so you see
what it will do before pressing Make it.

**New words, including Ryan's own phrasings:**

| you say | it sets |
|---|---|
| extend the midi notes, butt them up, no gaps, run into the next | every note run exactly into the next (`fill`) |
| add suggested chops at key areas, chops at phrase ends, breaks in the beat | chops at the ends of phrases |
| chop it up, chop it to pieces, more chops | lots of chops |
| the odd stutter, subtle chops | a few |
| swung, shuffle, groovy | the off-sixteenths swung |
| dead straight, square, no swing | on the grid, no swing |
| no drums, lose the drummer | the band's drums out, the added beat in their place |
| keep the drummer, their drums | the band's own drums kept |
| electro house, bloghouse, madeon, hardstyle, jungle, retrowave, 80s... | the style they name |

Longest name wins, so "electro house" is never read as "electro".

## 4. A bug the testing found

Switching styles **inherited the last one's treatment**: picking Techno after Complextro left
the keys at 65% grit, because techno's config says nothing about keys and the old value
simply stayed. A named style is a complete statement of how the parts are treated, so
anything it does not mention now goes back to nothing. A sentence with no style in it still
only changes what it names - "a bit more grit on the bass" should not wipe the rest.

Verified on the demo: Complextro then Trance leaves no grit anywhere, and Trance's version
has no distortion line at all.

## 5. Checked

- **Tests:** every style's recipe validates as a `Recipe` and names only real parts, kits and
  beats, and every style says something about itself; the genres Ryan listed all exist; a
  genre word brings its whole recipe; the longest name wins; each new phrase sets what it
  should; a style says what it will do before doing it.
- **In the browser,** on the demo track: eleven styles with their tempo fits and guides; the
  prompt *"make it more complextro, extend the midi notes and add suggested chops at key
  areas"* read correctly and ran end to end; *Make it Techno* and *Make it Trance* each
  produced their own settings.
