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
| `POST` | `/tracks/{id}/reference/separate` | Split the reference into stems so matching can work per instrument. `202` + job |
| `GET` | `/tracks/{id}/reference/stems` | Whether the reference has been separated, and into what |
| `POST` | `/tracks/{id}/master` | Body: `stems[]` with gain/pan/width/mute/solo, optional `reference_track_id`, `per_stem_match`, `vocal_presence`, `vocal_duck_db`, `match_strength`, `bitrate_kbps`. `202` + job |
| `GET` | `/tracks/{id}/master/download` | The rendered MP3 |
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
