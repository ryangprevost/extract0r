# Sprint 11 — the whole mix, a page that stays put, and a faster pr0ducer

Opened 2026-10-12 from Ryan:

> go ahead with automation on the whole mix next. also, clicking around the pr0ducor seems to
> take me back to the mastering studio content. please fix that. also, make sure the page is
> as fast as possible for the producer sections

---

## 1. The page went back to the mastering studio — fixed

**Cause, caught in the act** (by wrapping `goToPage` in the live page and logging who called
it): opening a song runs a chain of slow steps - the mixer, the reference, the instrument
comparison - and the last line of it was `goToPage("master")`. Anybody who went to pr0ducer
while the song loaded was taken back to mastering about 25 seconds later; anybody who opened a
song *from* pr0ducer landed on mastering. Uploading, splitting the reference, and a mastering
render or error all ended the same way.

**Fix:** every one of those flows now lands on the page the person is on when it finishes
(`goToPage(state.page)`). The only fixed `"master"` left is the first page at startup.
Checked in the page: a song opened from pr0ducer, logged page changes `produce, produce`, and
still on pr0ducer 35 seconds later.

---

## 2. pr0ducer, faster

Measured on a real four-minute song before and after, first visit then every visit after:

| | before | after, first read | after, every read since |
|---|---:|---:|---:|
| tempo | 9.3 s - again after every restart | 9-12 s, once | **9 ms** |
| sections | 2.6 s every visit | ~5 s, once (with drops) | **9 ms** |
| drops | 2.6 s every visit | shared with sections | **8 ms** |
| mixer layers (demo) | 21 MB of WAV | | **2.2 MB of FLAC** |

* **The tempo is kept beside the track** (`timing.json`), so a restart does not cost a
  re-read; correcting it rewrites the file.
* **Sections and drops are worked out together** from one decode of the song and kept beside
  it (`shape.json`), keyed by the tempo and first beat - a corrected tempo is a new key and
  is read again.
* **The page starts reading the moment a song opens**, on any page, so pr0ducer is ready
  when it is visited; on the page, drops and sections are fetched side by side.
* **Two requests for the same slow read wait for one answer** - the prefetch and the page
  were each working out the tempo at the same time.
* **Mixer layers are FLAC** - lossless, so heard still equals bounced (the flat-mix test
  holds) - and a layer that is silent throughout is not written at all. Versions bounced
  before this still play from their WAV layers.

(The ~0.2 s every request seemed to take from a terminal was `curl` trying IPv6 for
`localhost` first; through the studio, as a browser sees it, a small request is 7 ms.)

---

## 3. Automation on the whole mix — X0R-1430

| | |
|---|---|
| **Whole-mix strip** | After every part and both effect returns: level, low cut, high cut - the moves made on a whole mix. A fade-out fades the reverb's tail too. |
| **Lanes** | *Whole mix* is a lane target for level, low cut and high cut. |
| **Server** | `mixer.whole_mix`, after the sum and before the -1 dBFS ceiling; `"master"` is accepted in a mix and carried by saved mixes to every version. A new starter, *Fade in*. |
| **Heard = bounced** | A fade-in and a high-cut sweep on the whole mix, with a part's reverb under them: **-88.4 dB**. |
