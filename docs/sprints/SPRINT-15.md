# Sprint 15 — a sound from the reference, and styles that keep a song's speed

Opened 2026-10-12 from Ryan:

> not loving the synth sounds honestly. can you allow for sampling a note of a synth in the
> reference and applying that to the midi? thatd be huge. also i dont know the best way to turn
> something like a pop punk song into edm. it just doesnt seem to translate well it feels
> slowed down and boring

and, stepping away:

> keep at this im stepping away. you can use the latest run i have with vavava as the source
> and mstrkft bounce as the reference

---

## 1. Sample a sound from your reference — X0R-1460

**Sample a sound from your reference** on the pr0ducer page:

1. Pick one of the reference's separated parts (synths/other, bass, keys, guitar, or vocals
   for a chop) and press **Find clean notes**.
2. Each candidate plays the way it would be sampled, ranked by clarity, with how long it can
   hold a note and how far it was tuned. The clean ones that can hold a note start ticked.
3. Tick **I may sample this recording**, name it, and press **Make it an instrument**.

The new instrument then appears on every part as *"… (from your reference)"*. It plays like
the real synths from Sprint 12: every note of your part comes from the sampled note nearest
in pitch.

`synth/sampled.py` does the work:

- **Finding clean notes.** Every note the transcriber found in that part is scored on:
  - whether it plays alone, with no other pitch under it;
  - how much of its energy sits on its own harmonics;
  - how steady its pitch is while held;
  - how long it is;
  - how loud it is against the part's own loud passages, so leakage from other parts is not
    offered.

  At most one candidate is kept per pitch, and at most 12 in all.
- **Cutting.** A note is cut from its real attack (the steepest rise within 30 ms) to just
  before the next note. It is **tuned** to the semitone, because records sit a few cents off,
  and every note of your part would inherit that. When it's short, it is **held by looping**
  its steady middle with crossfades, up to 3 s, the way a hardware sampler sustains.

### On VaVaVa with MSTRKRFT "Bounce" as the reference

- **The reference's bass:** 426 notes transcribed, 11 clean candidates from D#1 to D#3.
  Typically over 90% of each note's energy is on its own harmonics, and pitch wander is
  5–16 cents.
- **The instrument:** made from the nine that hold a note, then VaVaVa's bass part re-played
  on it at 169 BPM.
- **Tuning of the result:** across 172 held notes, the median is +0.7 cents and 90% are
  within 3.6 cents.
- **The Half-time version** with that bass took 22 s to make. Its account says: *"Played on a
  sound sampled from your reference - clear the sample before you release this: bass."*

### This changes a promise, so it is done carefully

Everywhere else extract0r analyzes the reference and never samples it, and it said so in the
help, on the mastering page and in the terms. This is the one exception, because Ryan asked
for it:

- **Opt-in.** The API refuses without `may_sample`, quoting the new `legal.SAMPLING_NOTICE`.
- **Named.** The instrument's name, its `origin`, its description and every version made with
  it say it came from the reference.
- **Deleted with its track** (`sampled.forget_missing`, run after every retention sweep and
  every delete). The terms promise that everything derived from an upload goes with it.
- **Never in the repository:** sampled sounds live in the samples folder.
- **Wording updated.** The help, the mastering line, the terms and the docstrings now say
  "analyzed, not sampled — unless you ask in pr0ducer".

## 2. Styles that keep the song's speed — X0R-1461

Why the pop-punk version felt slow: the bounce said **169 to 129 BPM, 24% slower**. Every note
was a quarter slower, and a sung vocal stretched that far drags. Pop punk lives at 160–200 BPM
and house at 120–126, so no setting of house fixes that.

- **Each style has a tempo range**, the range its records actually sit in. `styles.fit` uses
  the song's own tempo when it is inside the range (nothing is stretched at all), and
  otherwise the nearest end of the range.
- **The picker says what each style does to your song.** For VaVaVa it reads "Drum and bass ·
  169 · keeps its speed" and "House · 126 · 25% slower". Choosing House says *"Slows your song
  25% to 126 BPM. A sung vocal drags at that much - fine for an instrumental. Drum and bass or
  Half-time keep it at its own speed."*
- **A song opens on a style that keeps its speed.**
- **Two new styles for fast songs:**
  - **Half-time:** the trap/future-bass beat, kick and snare at half the rate, at the song's
    own tempo. It hits like an 85 BPM drop while the vocal keeps its real speed.
  - **Hard dance:** 150–160 BPM, four on the floor.
- **No stretch at the song's own speed.** A target within 0.2% of the song's tempo is snapped
  to it exactly (`_as_asked`), so "keeps its speed" stretches nothing. The page shows the
  tempo to a tenth of a BPM, and without the snap 169.0 against a measured 169.04 meant a
  0.02% stretch of every part, plus an added beat 57 ms adrift by the end.

The other half of "boring" is arrangement. The drop option and Sprint 13's part marking are
how a chorus becomes the drop.

## 3. Upload names lost on restart — X0R-1462

Uploads' names lived only in memory, so every API restart turned "VaVaVa.mp3" into
"source.mp3" in the list, on the page, and in a sampled instrument's description. They're now
kept in `names.json` beside the track (deleted with it) and read back at startup. VaVaVa's
names were restored by hand; tracks uploaded before this keep showing "source.mp3".

## 4. Checked

- Tests (`test_sampled.py`):
  - On synthetic saw notes 20 cents sharp, the clean notes are found and the chord is not.
  - A cut is tuned to within 4 cents and held past its played length.
  - An instrument is named for its reference and deleted when its track goes.
  - A 169 BPM song is offered Drum and bass and Half-time.
  - A tempo a hair from the song's own is snapped to it.
- API, end to end on VaVaVa:
  - Without consent the request is refused; with it, the instrument is made.
  - The instrument is listed in the sound pickers.
  - The re-play takes 4 s and the bounce 22 s, with the account lines above.
- In the browser on VaVaVa:
  - The picker labels and the default style.
  - The House wording.
  - The sampler on the reference's synth part: 9 candidates, 4 pre-ticked.
