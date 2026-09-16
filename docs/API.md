# Extract0r API

Base path `/api/v1`. Interactive docs at `/docs` when the service is running.

Long-running operations return `202` with a job id; poll `/jobs/{id}` until `state` is
`succeeded` or `failed`.

## Meta

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness, version, environment |
| `GET` | `/capabilities` | Configured backends vs. actually-installed ones, plus limits. Use it to explain a greyed-out feature instead of failing mid-job |
| `GET` | `/legal` | The notices, served from `app/legal.py` so the web app never holds its own copy |

## Tracks

| Method | Path | Notes |
|---|---|---|
| `POST` | `/tracks` | Multipart. Fields: `file`, `owns_or_licensed`, `personal_use_only`. Returns `201` with `track_id`, SHA-256, and probed duration/sample rate/channels |
| `POST` | `/tracks/{id}/separate` | `202` + job. Writes `storage/{id}/stems/` |
| `GET` | `/tracks/{id}/stems` | The separation result. `409` if separation has not finished |
| `DELETE` | `/tracks/{id}` | `204`. Immediate, unconditional — deletes the folder and the record |
| `GET` | `/tracks/tunings` | Tunings the solver can target, for the UI dropdown |
| `GET` | `/tracks/{id}/stems/{stem}/audio` | Stream one stem. Honours `Range`, so players can seek without re-downloading |
| `GET` | `/tracks/{id}/stems/{stem}/peaks` | Normalised amplitude envelope for drawing a waveform. `?buckets=50..4000`, cached on disk |

**Upload errors:** `400` empty · `403` missing rights attestation · `413` too large ·
`415` unsupported format, or a file that has an audio extension but is not decodable ·
`422` outside the configured duration limits. A rejected upload is deleted before the
response is returned.

## Transcription

| Method | Path | Notes |
|---|---|---|
| `GET` | `/tracks/{id}/timing` | Detected tempo, metre, and key for the whole track. Cached |
| `POST` | `/tracks/{id}/transcribe` | Body: `stems[]`, `tunings{}`, `capo`, `max_hand_span`, plus optional `tempo_bpm` / `beats_per_bar` overrides. `202` + job |
| `GET` | `/tracks/{id}/tabs/{stem}` | `text/plain` ASCII tab, as a download |
| `GET` | `/tracks/{id}/x0r` | The full session document |

The job result carries one artifact per stem: notation type, note count, download URL, a
2000-character preview, and `dropped_count` / `folded_count` — notes the instrument could
not play (usually separation bleed) and notes shifted by whole octaves to fit. Non-zero is
normal, not an error.

Timing is analysed once from the **full mix** and applied to every stem, so instruments
cannot drift apart. Beat trackers report half or double the real tempo often enough that
`tempo_bpm` and `beats_per_bar` overrides are part of the normal workflow — the response
reports the grid actually used, and keeps the original reading in `source`.

Stem audio and peaks exist for one workflow: when a transcription looks wrong, the first
question is whether the *stem* was already wrong. Listening to it, and seeing its envelope,
is the only way to tell a separation problem from a transcription one.

## Mastering (phase 2)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/tracks/{id}/reference` | Multipart. Store a reference to match against; same rights gate as an upload. Returns its measured loudness |
| `POST` | `/tracks/{id}/reference/url` | Fetch a reference from a direct link instead of uploading it. Same rights gate, size limit and probing |
| `POST` | `/tracks/{id}/reference/separate` | Split the reference into stems so matching can work per instrument. `202` + job |
| `GET` | `/tracks/{id}/reference/stems` | Whether the reference has been separated, and into what |
| `POST` | `/tracks/{id}/master` | Body: `stems[]` with gain/pan/width/mute/solo, optional `reference_track_id`, `per_stem_match`, `vocal_presence`, `vocal_duck_db`, `match_strength`, `brightness_db`, `brightness_from_hz`, `width`, `headroom_db`, `protect_dynamics`, `bitrate_kbps`. `202` + job |
| `GET` | `/tracks/{id}/master/download` | The rendered MP3 |
| `GET` | `/tracks/drum-kits` | The kits available to lay over a drum track |
| `GET` | `/tracks/{id}/master/suggest` | How this mix compares with its reference in plain language, plus where to set each finishing dial and why |
| `GET` | `/tracks/{id}/master/peaks` | The mix and the master as two envelopes on one time axis, plus their per-bucket difference in dB |

Stems are mixed **first** and matched **second**. Tonal balance is a property of a whole
mix — matching each stem separately against a full-mix reference would push every stem
towards a curve that includes all the other instruments.

The job result reports what was actually done: source, reference and result loudness in
LUFS, the gain applied, the EQ correction per band, and any warnings. Omit
`reference_track_id` to export the mix without matching anything.

With `per_stem_match`, each entry in `per_stem` carries `matched`, `proportional` and
`user_gain_db` alongside the gain, width and EQ. An instrument the reference does not
contain cannot be matched, but it is not left alone either — standing still while every
other stem moves changes its place in the arrangement by accident. It takes the mean of the
matched gains instead (`proportional: true`). The per-stem `gain_db` you send is a separate
number applied at the mix bus: it stacks on top of matching rather than feeding into the
measurement matching is derived from, so you can lift the vocal a little and still match the
reference.

Two things used to cancel that fader out. Vocal placement re-measured the vocal *after*
the fader and handed back exactly what the fader added, and the whole-mix EQ match read
the raised band as a tonal deviation and cut it out again — a +3 dB vocal landed as
+0.01 dB in the export. Placement now measures the vocal where it naturally sits, and the
tonal correction is derived from a mix with the faders removed. Loudness is still measured
on what is actually exported, so the master lands on the reference's level wherever the
faders sit.

### Fetching a reference by URL

`reference/url` takes `{url, owns_or_licensed}` and stores the result exactly as an upload
would — it is a different way to get the bytes, not a different set of rules about them.

A server that fetches arbitrary URLs on request is a request-forgery primitive, so
`app/services/fetch.py` is mostly refusals:

- **http and https only.** `file://` reads the server's own disk.
- **Every resolved address is checked, not the hostname.** `internal.example.com` can
  resolve to `10.0.0.5`. Any private, loopback, link-local, reserved, multicast or
  carrier-NAT address disqualifies the name — *any*, not all, since which address gets
  connected to is not ours to choose. IPv4-mapped IPv6 (`::ffff:127.0.0.1`) is unmapped
  first.
- **Redirects are walked by hand and re-checked at every hop**, because a public URL that
  302s to `169.254.169.254` is the standard way to read a cloud instance's credentials.
  `follow_redirects=True` would land there happily.
- **The size cap is enforced while reading.** `Content-Length` is a claim, not a fact.
- **Content type must look like audio**, so an HTML page fails with a useful message
  rather than later as "unsupported format".

Streaming sites are **refused, not supported** — `422` with an explanation. Extract0r's own
terms (`NO_DRM_CIRCUMVENTION` in `app/legal.py`) say it will not process audio ripped from
a streaming service in breach of that service's terms, and building the downloader in
would make that sentence false. Those hosts are recognised only so the refusal can say why.

Errors: `400` a bad or unreachable URL · `403` missing rights attestation, or an internal
address · `413`/`400` too large · `415` not decodable audio · `422` a streaming page.

### Drum layering

`drum_kit`, `drum_targets` and `drum_blend` on the master request find each kick, snare and
hi-hat in the drums stem and trigger a synthesised sample on it.

**It layers, it does not replace.** Removing the original snare would mean separating drums
from drums, which the separator does not do. What happens instead — and what every
practical drum replacement does — is trigger a sample and blend it against the original.
`drum_blend` is how far to lean on the new one.

**The samples are synthesised, not sampled**, for the same reason a reference is analysed
and never sampled. Velocity comes from the detected hit, so ghost notes stay ghost notes.

Detection is in `app/services/drums/detect.py` and is a rewrite rather than a reuse of the
transcription classifier, which had two bugs that made it useless for this:

- **It picked one drum per onset.** A kick and a hat land together on almost every rock
  downbeat, so the hat won and the kick was never seen. Against a constructed beat with 32
  kicks and 32 snares — all under hats — it found none of either and still scored itself
  100% correct, because the hat it named was really there. Drums are now tested
  independently and a stroke can carry several.
- **It compared bands of unequal width.** Kick was 20–120 Hz and hi-hat 5–14 kHz, ninety
  times wider; summed raw the wide band wins whatever is playing. A real drum stem came
  back as 615 hi-hats, 205 kicks and *no snares at all* — which means drum tabs have never
  had snares either.

What replaced it measures each band's **rise** at the onset and requires the band to be
loud at the same time. Both are needed: a rise alone fires on noise in a silent band, and a
level alone cannot find a kick under a ringing crash. The presence ceiling is taken from
the onsets rather than the whole track, because a separated drums stem carries bass bleed —
on a real track the 30–120 Hz band idled at 24 dB from bleed and only reached 8 dB on an
actual kick, so a whole-track ceiling rejected every kick. Kick and snare each additionally
have to out-rise the hi-hat band, which is what separates them from cymbals.

Against the constructed beat: **kick 97%, snare 100%, hi-hat 99%, no false positives on
any of the three.**

### Finishing

Matching answers "what does that record sound like?", not "what do I want this to sound
like?". Three dials cover the gap, applied after the tonal match and **before** the level
stage — widening and a brightness lift both add peak energy, so doing them after the
limiter would push the master back over its ceiling.

| Field | What it does |
|---|---|
| `brightness_db` | High shelf on top of the matched tone, ±6 dB. The match can only give you the reference's top end; this is how you ask for more |
| `brightness_from_hz` | Where the shelf starts. ~3 kHz reads as clarity and presence, ~10 kHz as air |
| `bass_db` | Low shelf below `bass_from_hz` (default 90 Hz), ±4 dB. A *shelf* here where warmth is a bell: at 90 Hz there is nothing underneath to protect, and lifting everything below the corner is exactly what "more bass" means |
| `warmth_db` | Bell around `warmth_from_hz` (default 450 Hz), ±4 dB. A bell, not a shelf — every shelf lifts *everything* below its corner, so a shelf placed for 250–800 Hz also lifts 40 Hz and the result is boomy rather than warm |
| `width` | Side-channel scale **above `width_floor_hz`** (default 250 Hz), 0.7–1.6. The low end is never widened |
| `headroom_db` | Sit this far under the reference on purpose, 0–6 dB |
| `protect_dynamics` | Aim at the reference's loudness *relative to its own peak* rather than absolutely. On by default |

Widening is band-limited because side content cancels when channels sum to mono, and the
low end carries most of a mix's energy — widen everything and the bass is huge on
headphones and gone on a phone speaker.

`protect_dynamics` is a peak-alignment correction, not a dynamics measurement. A
commercial master typically peaks at or above 0 dBFS while this pipeline limits to −1;
chasing its LUFS number from a lower ceiling means over-driving the limiter by exactly
that difference. The back-off is `reference_peak − ceiling`, which as an identity leaves
the master with the reference's own crest factor. Measured on a real pair: matching
outright gave a 7.91 dB crest with the limiter working on 31% of the track; backing off
1.31 dB gives 9.08 dB and 6%. It will not make a master *more* dynamic than its reference
— that is what `headroom_db` is for.

### Suggestions

`master/suggest` compares the track with its reference and returns a value for every
finishing dial, each with the sentence behind it. It reads the two uploads directly — no
separation, no mastering run — so it answers in a couple of seconds and can be called the
moment a reference lands.

Each finding also carries an `action` — `{label, dials}` — where one dial addresses that
one difference, so the card can offer "Add body" next to the sentence explaining why. The
values are read off the computed suggestion rather than worked out again, so applying one
finding and applying everything can never disagree about the number.

Where there is no action, `handled_by_match` says whether that is because the tonal match
already covers it. Between them every difference is accounted for: it has a dial, or it is
handled, or it is context. A difference with none of the three would look ignored, and a
test enforces that none exist.

It returns a `summary` alongside the settings: a one-line verdict and a list of findings,
each with an `area` (tone, dynamics, width, loudness, balance), a `severity` (`match`,
`slight`, `notable`), a headline and a sentence. Findings are sorted differences-first,
largest-first.

Areas are `tone`, `dynamics`, `width`, `loudness`, `balance` and `space`. The last two
compare instrument by instrument and need **both** sides separated.

`balance` is how loud each instrument sits *relative to its own mix*, against the same
instrument in the reference — "your vocal sits 3.4 dB further back than that record's" is
a mix note, not a mastering one, and band energies cannot give you it.

`space` is per-instrument stereo width and an estimate of how wet each part sounds. Width
is exact. Wetness is not: reverb cannot be measured without the dry signal, so what is
measured is how fast a part falls after each hit — a dry source stops, a reverberant one
slides down at the room's rate. Comparing the same instrument on both sides cancels some
of the confound, and the wording says what is left.

Two limits are enforced in code rather than left to the reader. Bass is excluded from the
wetness estimate: measured against a real reference its bass came out at −5.9 dB/s against
the source's −41.3, which reads as enormous reverb and is nothing of the kind — a legato
bass line never stops between notes, so there is no decay to measure. And a width ratio
between two near-mono stems is refused, because dividing 0.02 by 0.00 produced "your bass
is wider than the reference's" for two stems that are both centred on purpose.

`space` findings carry a reverb offer where one makes sense. Per-stem `reverb_s` and
`reverb_mix` on the master request put a stem in a space; the suggested length is the
reference's own measured decay.

The estimate is validated rather than asserted. Convolving dry hits with a tail of known
length, it reads back within **0.1 s at every length from 0.4 s to 2.5 s**, and gives the
same answer at 30% wet as at 70% — a tail's decay rate does not depend on its level, and
neither does the estimate. Getting there needed the fit bounded by level rather than time
(−5 dB to −25 dB below each hit, as RT20 has always been measured): fitting from the peak
measured the instrument stopping rather than the room continuing and turned a known 1.2 s
into 0.58 s.

The processor is a convolution rather than a feedback network so that its parameter is the
decay time directly, which is what the estimator produces. Damping and truncation steepen
the decay, so a response built to the requested length actually ran 0.86× short — the same
0.86 at every length, so it divides out, and without it asking for 1.4 s delivered 1.2 s.

Two refusals: anything measuring over `PLAUSIBLE_MAX_S` (3 s) is reported as nothing rather
than as reverb, because at that length it is sustain — a real reference's guitar stem came
back at 6.0 s and its piano at 5.2 s — and bass is excluded entirely, since a legato line
never stops long enough to have a decay. Reverb is also never suggested in order to
*remove* it, because nothing here can.

### Two calls, not one slow one

`?stems=true` adds the `balance` and `space` findings. It is a separate call because it
reads every stem on both sides in full — about 25 seconds against 5 for everything else.

Sampling a window from the middle of each stem was tried instead and abandoned on the
numbers: against the full-track answer a 60-second window put `other` 6.8 dB out and
`guitar` 3 dB out, which is enough to invent a finding that is not there. The response
carries `includes_stems` and `stems_available` so the page knows whether to ask again.

Findings describe the mix **before** the tonal match, because "your low mids are 7 dB
lighter than that record" is a fact about your mix; where matching is about to close a gap
the finding says how much. The suggested dial values are computed from the residual after
matching — the two questions have different right answers.

Two things the settings get right that a naive version does not:

**It compares against the *matched* mix, not the raw one.** The tonal match already moves
the source toward the reference; a gap it is about to close is not a gap the dials should
close again. On a real pair the raw comparison showed a 7.0 dB body deficit and wanted the
full +4 dB shelf on top of a +3.2 dB correction that was already coming. Predicting the
post-match spectrum — the correction curve applied to the source's average spectrum, no
audio rendered — brings that to a 1.5 dB residual and a proportionate +2.5 dB.

**It solves for the gain numerically.** A filter does not move a band by its own gain: the
shelf is still climbing through most of the band, and because the gaps are measured as a
*share* of the whole, lifting one band moves the denominator too. Two linear estimates
were tried and both undershot by around 40%; bisection over the exact expression costs a
few dozen operations and cannot be wrong about either.

A filter that cannot deliver its share of a gap returns zero rather than a clamped
maximum — dividing by a small overlap is how a 1.5 dB gap became a 16 dB demand that
looked like a considered recommendation.

The job result reports all of it under `finishing`, including `limiter_max_db`,
`limiter_mean_db` and `limiter_active`. Those three are the answer to "does this sound
squashed": two masters can meter identically on loudness and peak and sound nothing alike.

None of this needs ffmpeg. Processing is numpy/scipy, encoding is `lameenc`, metering is
`pyloudnorm`.

Solo overrides mute; a mix with nothing audible is a validation error, not silence.

`master/peaks` exists because the numbers in the report say what mastering *decided*, not
what it *did*. `before` is the mix as you balanced it and `after` is that mix once the
reference has been matched; `delta_db` is the difference bucket by bucket, which is the
part a waveform alone will not show — a couple of dB on a 55 dB scale is a few pixels, so
the moments where the limiter worked hardest only become visible on their own axis. The
response is `{"matched": false}` when no reference was used, because then there is no
"before". Envelopes are RMS in dBFS against a fixed floor, so the two are directly
comparable; the shared implementation is `app/services/waveform.py`, which the stem lanes
use too. Results are cached under a key containing both files' mtime and size, so a
re-render can never serve the previous run's picture.

## Jobs

`GET /jobs/{id}` → `{ job_id, kind, track_id, state, progress, message, result, error }`

`state` is `queued` · `running` · `succeeded` · `failed`. `progress` is 0–1. A worker
exception lands in `error` with the job marked `failed` — the polling endpoint itself never
500s.

## Example: upload to tab

```bash
curl -X POST http://localhost:8000/api/v1/tracks \
  -F "file=@song.wav" \
  -F "owns_or_licensed=true" \
  -F "personal_use_only=true"
```

```bash
curl -X POST http://localhost:8000/api/v1/tracks/$TRACK/separate
```

```bash
curl http://localhost:8000/api/v1/jobs/$JOB
```

```bash
curl -X POST http://localhost:8000/api/v1/tracks/$TRACK/transcribe \
  -H "Content-Type: application/json" \
  -d '{"stems":["bass","drums"],"tunings":{"bass":"bass_5"}}'
```

```bash
curl -O http://localhost:8000/api/v1/tracks/$TRACK/tabs/bass
```
