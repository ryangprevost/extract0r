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

**Upload errors:** `400` empty · `403` missing rights attestation · `413` too large ·
`415` unsupported format, or a file that has an audio extension but is not decodable ·
`422` outside the configured duration limits. A rejected upload is deleted before the
response is returned.

## Transcription

| Method | Path | Notes |
|---|---|---|
| `POST` | `/tracks/{id}/transcribe` | Body: `stems[]`, `tunings{}`, `capo`, `max_hand_span`. `202` + job |
| `GET` | `/tracks/{id}/tabs/{stem}` | `text/plain` ASCII tab, as a download |
| `GET` | `/tracks/{id}/x0r` | The full session document |

The job result carries one artifact per stem: notation type, note count, download URL, a
2000-character preview, and `dropped_count` / `folded_count` — notes the instrument could
not play (usually separation bleed) and notes shifted by whole octaves to fit. Non-zero is
normal, not an error.

## Mix and master (phase 2)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/tracks/{id}/mix` | Per-stem gain, pan, mute, solo, EQ, compressor, reverb. `202` + job |
| `POST` | `/tracks/{id}/master` | Body: `reference_track_id`. Requires an existing mixdown |
| `GET` | `/tracks/{id}/mixdown` | The rendered MP3 |
| `GET` | `/tracks/{id}/mastered` | The mastered WAV |

Solo overrides mute; a mix with nothing audible is a validation error, not silence.

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
