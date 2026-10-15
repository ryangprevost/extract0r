# Sprint 24 — judging a master honestly, and a tidy-up

Ryan: *"keep moving forward with extract0r dev please. find some backlog stuff to round out
the week."* Sprint 23 made the club finish a feature; this sprint is what the finish needs to
be trustworthy, plus two housekeeping cards.

---

## 1. A/B at the same loudness — X0R-804

A master is louder than the version it came from, and louder always sounds better. Comparing
them as they are tells you nothing - it is the oldest trap in mastering.

So the A/B plays **both files at once**, with the louder one turned down to the quieter one's
integrated loudness (`match_db` from the meters route). Switching is instant and in the same
place in the song, because nothing restarts: the inactive side is simply silent. The buttons
say which you are hearing, and that the version is being played *at the master's loudness*.

The card's other half - a 30-second preview before committing to a full pass - is not done
here and stays on the card: the club finish takes about 20 seconds on a four-minute song, so
there is little to save, and the mastering page's own pass is where the wait is.

## 2. Meters worth the name — X0R-1205 (the remix half)

`mastering/meters.py` and `GET /tracks/{id}/version/{label}/meters`, drawn under the finish:

- **Short-term loudness** (EBU's 3 s window) for the version and the master on one axis,
  with guides at -9 (club) and -14 (streaming) LUFS.
- **Momentary loudness** (400 ms), measured and returned.
- **Phase correlation** per half-second, in its own strip, red where it goes negative. This
  is the one that matters here: `synth/width.py` and the bass centring both push a mix
  towards cancellation, and nothing warned about it until now. A negative stretch of 1.5 s
  or more is called out in words, with how long it lasts and what to do.
- **Loudness range**, the EBU way, from the short-term series rather than from the crest
  figure already shown.

**"Could not measure" is not zero.** `loudness_range` returns `None` when too little of the
song sits above the relative gate, and the page says so rather than printing 0.0 LU. The
first version returned 0.0 for both, which is a made-up number.

**A quiet intro is gated out, by design.** A passage more than 20 LU under the song's own
loudness is an intro or a fade, not part of its range - so a song that is silent for half its
length still reports a small range. That surprised me while writing the test; the test now
says it is deliberate.

The card's other half - the same three series on the mastering page's existing time axis,
reusing the peaks endpoint's caching - stays open.

## 3. Housekeeping

**X0R-1111, the audit.** The three candidates the card named are all still reachable, and now
say so where they live: `widen_above` (used by `pipeline` and `spectral`), `MatcheringEngine`
(`MASTERING_BACKEND=matchering`, reported by `/capabilities`), and the ffmpeg path in
`loudness.py` (the *default* backend). Rather than rubber-stamp that, a sweep for
module-level definitions never referenced anywhere - app, tests, tools or the web app -
turned up 87 names, of which 83 are FastAPI route handlers (the framework calls them) or
Protocol bases. The remaining four were genuinely dead and are gone:

| gone | why it was dead |
|---|---|
| `schemas.RightsAttestation` | the gate is Form fields on the upload route; the export records rights through `x0r.Provenance`, which is what this class's docstring described |
| `notes.pitch_range` | never called |
| `clarity.ClarityReport` | never built |
| `space.describe_space` | never called |

**X0R-1112, one name.** The page already said "extract0r studio"; the API called itself
"Extract0r API" and exports were encoded by "extract0r". Both now say **extract0r studio**,
and so does the About page. The download *filename* keeps its short `[extract0r]` suffix -
it is a filename, not a brand mark, and the card's criteria are the title, the mark, the
About page and the metadata.

**And the master now carries provenance.** The club finish wrote an untagged MP3; it now gets
the same ID3 fields as every other export, plus what it was finished at: *"Finished with
extract0r studio at -9.6 LUFS"*, and the reference's name when one was matched.

## 4. Checked

- **Tests:** correlation knows agreement from cancellation and treats silence as agreement; an
  out-of-phase half is found and called out; an in-phase song is not; the series follow a
  three-level song; a quiet intro is gated out; an unmeasurable range is `None` and an even
  song is 0.0.
- **In the browser,** on the demo track: measured version and master, drew both, switched
  between them while playing, and confirmed the master's ID3 tag.
