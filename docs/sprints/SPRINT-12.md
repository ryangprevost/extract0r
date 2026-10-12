# Sprint 12 — real synths, and styles

Opened 2026-10-12 from Ryan:

> looks like the site timed out again. can you please find some actual synth samples (they're
> usually just a bunch of C notes) that can be used as starting points? i want this to sound
> like the style and i dont know a lot about configuring tones with synths.

and, mid-sprint:

> also please let me determine the parts of the song instead of parsing them. this can be a
> future enhancement

---

## 1. The timeouts — X0R-1441

Both servers were up and answering in milliseconds when checked, and neither log held an
error. The likely cause was this session: the API ran under `uvicorn --reload`, so **every
server-code change restarted it**, and anything Ryan pressed during the seconds it was down
failed or hung - and there were many changes. With his approval it now runs **without
auto-reload**; changes go live only when restarted deliberately, after checking nothing of his
is running. (One restart did cut off a job that was being polled at that moment; he was told.)

## 2. Real synth samples — X0R-1440

Searched for free, clearly licensed one-shots and multisamples, and with Ryan's approval
downloaded three sets (63.6 MB) into **his samples folder - never the repository**:

| set | licence | became |
|---|---|---|
| [Sonic Pi](https://github.com/sonic-pi-net/sonic-pi/tree/dev/etc/samples) bundled samples | CC0 (freesound.org) | 7 single-note synth basses (trance, hard, thick, voxy, woodsy, hit, DnB); an *electro* drum kit |
| [VCSL](https://github.com/sgossner/VCSL) Yamaha TX81Z | CC0 1.0 | *TX81Z FM piano* (19 notes), *TX81Z Clavisynth* (18) |
| [Modular Samples](https://github.com/publicsamples) hardware multisamples | Public domain (Unlicense) | *MicroBrute sharp bass, saw lead, strings*; *MG-1 wobble bass, pad*; *Jupiter-style stack*; *Big stack*; *Cluster strings* - 25 chromatic notes each |

`tools/import_instruments.py` (no audio in it - sources, licences and how to sort them) decodes
each file, trims the leading silence (MP3 encoder delay would make every note late), **measures
its pitch with pYIN** rather than trusting the file name (VCSL's named notes are cross-checked;
4 that disagreed were left out), normalises it, and files it as a note of an *instrument* with
its licence beside it. Every hardware set came out as two clean chromatic octaves.

`synth/instruments.py` plays any part on an instrument the way a sampler does: each note from the
recording nearest in pitch, moved the rest of the way, released by kind (a pad lets go over
0.35 s, a bass at once). Instruments are voices everywhere - the part rows, previews, the
library - labelled "(real synth)".

**Found on the first remix:** a pad recorded from C2 to C4 was given chords around E4-G5, and
half its notes were stretched more than an octave. A producer would play that part an octave
down, so now a part that sits mostly outside an instrument's range moves by **the smallest whole
number of octaves that fits** - harmony unchanged - and the part row says so.

## 3. Styles — for somebody who does not configure synths

*Make it …* now has a style picker: **EDM, House, Trance, Drum and bass, Synthwave**. A style is
every choice a producer would make for the genre - tempo, beat, kit, pump, drop - and a sound
for every part: a real synth where one is installed, this app's own voice where not
(`synth/styles.py`, `GET /tracks/styles`). On this install every style puts four parts on real
synths. Every choice lands in the ordinary controls, so it can be seen and changed.

## 4. Future — X0R-1442

Ryan wants to mark the song's parts himself instead of having them detected. Filed as a card.
