# Runbook — getting the real backends running

The stub backends need nothing. This page is about the other ones, and about the traps
that cost time when you first install them.

## The two-venv setup on Windows

**Extract0r uses two virtual environments on Windows, and that is deliberate.**

| | Path | Contents |
|---|---|---|
| App venv | `services/api/.venv` | FastAPI, pydantic, soundfile, pytest — the light stuff |
| ML venv | `C:\Users\<you>\.x0r-venv` | torch, demucs, librosa, basic-pitch |

### Why

`pip install torch` fails on this project with:

```
ERROR: Could not install packages due to an OSError: [WinError 206]
The filename or extension is too long:
'...\extract0r\services\api\.venv\Lib\site-packages\torch-2.13.0+cpu.dist-info\licenses\
 third_party\kineto\libkineto\third_party\dynolog\third_party\DCGM\testing\python3\
 libs_3rdparty\colorama\...'
```

That is Windows `MAX_PATH`. Torch's bundled licence tree is about 160 characters deep on
its own; add a project path like
`C:\Users\you\Documents\Projects\extract0r\services\api\.venv\Lib\site-packages\`
and you are past the 260-character limit.

**The failure is worse than a clean error**: pip reports the OSError but leaves a
partially-installed torch behind, so the next thing you see is a baffling
`ModuleNotFoundError: No module named 'torchgen'` from inside `import torch`.

Check whether the limit is even being enforced:

```bash
powershell -Command "(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled).LongPathsEnabled"
```

`0` means enforced.

### The three ways out, in order of preference

1. **Short-path ML venv** (no admin needed) — what `scripts/install-ml.ps1` does.
   Creates `C:\Users\<you>\.x0r-venv` and installs the heavy stack there.
2. **Enable long paths** — one-time, **needs an administrator prompt**:
   ```
   Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1
   ```
   Reboot afterwards. This is a machine-wide change; run it yourself rather than having
   a script do it.
3. **Docker** — `docker compose up` sidesteps the whole thing, and is the closest match
   to how this runs in production.

If a previous attempt already left a broken torch behind, remove it before retrying:

```bash
powershell -Command "Remove-Item -Recurse -Force 'services/api/.venv/Lib/site-packages/torch*'"
```

## Running with the ML backends

`scripts/install-ml.ps1` builds the ML venv and prints the path. Point the API at it:

```bash
powershell -File scripts/dev-api.ps1 -Venv "C:\Users\<you>\.x0r-venv"
```

or set it once for the session:

```bash
powershell -Command "$env:EXTRACT0R_VENV = 'C:\Users\<you>\.x0r-venv'"
```

Then switch the backends on in `.env`:

```
SEPARATION_BACKEND=demucs
TRANSCRIPTION_BACKEND=auto
DRUM_BACKEND=onset
```

Confirm what the server actually has, rather than what it was told to use:

```bash
curl http://localhost:8000/api/v1/capabilities
```

`configured` is what `.env` asked for; `installed` is what is importable right now. When
they disagree, the factory falls back to the stub and logs a warning — so a green
`configured` field is not evidence that anything real is happening.

## basic-pitch cannot be pip-installed on Python 3.12

```
ERROR: Could not find a version that satisfies the requirement
       tensorflow<2.15.1,>=2.4.1 ... (from basic-pitch)
       (from versions: 2.16.0rc0, 2.16.1, ... 2.21.0)
```

basic-pitch 0.4.0 (the newest release) declares a hard `tensorflow<2.15.1` pin.
TensorFlow's oldest Python 3.12 wheel is 2.16. The two cannot both be satisfied, and pip
responds by backtracking through basic-pitch 0.3.x until it reaches an sdist and tries to
**build numpy from source**, which then fails for its own reasons. The error you actually
see is `Failed to build 'numpy'`, which points nowhere near the real problem.

**The fix.** basic-pitch ships three sets of weights, not one:

```
saved_models/icassp_2022/nmp/saved_model.pb   1.1 MB   TensorFlow
saved_models/icassp_2022/nmp.onnx             0.2 MB   ONNX
saved_models/icassp_2022/nmp.tflite           0.2 MB   TFLite
```

`ICASSP_2022_MODEL_PATH` resolves to the ONNX file when TensorFlow is not importable, and
`predict()` runs it through onnxruntime. So install it without its dependency metadata:

```bash
pip install --no-deps basic-pitch==0.4.0
```

and supply its real runtime needs, which resolve fine (they are in
`requirements-ml.txt`): `onnxruntime`, `pretty_midi`, `mir_eval`, `resampy<0.4.3`, plus
librosa/scipy/scikit-learn/numpy.

Verified on Python 3.12: a 220 Hz sine transcribes to exactly one note, MIDI 57 (A3).
`Transcription.backend` reports `basic_pitch:onnx` so the runtime in use is visible in
every `.x0r` export.

The three `WARNING:root: ... is not installed` lines basic-pitch logs on import are
expected and harmless — it is reporting the runtimes it did *not* find.

## Which transcriber runs for which stem

`TRANSCRIPTION_BACKEND=auto` picks per stem, because the right tool genuinely differs:

| Stem | Backend | Why |
|---|---|---|
| bass, vocals | pYIN (librosa) | Monophonic. Faster and more accurate than a polyphonic net, and needs no extra install. |
| guitar, piano, other | basic-pitch (ONNX) | Polyphonic — several notes at once. |
| drums | onset + band energy | No pitch to track. |

pYIN needs only librosa, so bass transcription works on any machine that can run the drum
backend — no ONNX, no torch.

## Model weights

Demucs downloads its checkpoint on first use (~80 MB for `htdemucs`, ~300 MB for
`htdemucs_6s`) into `~/.cache/torch/hub/checkpoints`. The first separation is therefore
much slower than the rest. In Docker this is a named volume (`demucs-models`) so it
survives container rebuilds.

## ffmpeg

Only two things need it, and neither is on the Phase 1 path:

- mixdown rendering (`MixdownRenderer`)
- loudness matching (`LoudnessMatchEngine`)

Ingest does **not** need it. `soundfile` bundles libsndfile 1.2, which reads WAV, FLAC,
OGG, AIFF **and MP3**; ffmpeg is only the fallback for m4a/aac. That is why
`/api/v1/capabilities` can report `ffmpeg: false` while uploads and transcription work
perfectly.

## Running the ML smoke tests

They are marked `ml` and skip themselves when a backend is missing, so the default run
stays fast:

```bash
pytest -m ml -q
```

With the app venv (no ML installed) every one of them skips — that is the expected
result, not a failure. Run them against the ML venv to actually exercise the adapters.

## Expected timings (CPU, 4 cores)

| Step | 8 s clip | 3 min song |
|---|---|---|
| Probe | instant | instant |
| Normalise | instant | ~1 s |
| Demucs `htdemucs` | ~20 s | ~4 min |
| Demucs `htdemucs_6s` | ~35 s | ~7 min |
| basic-pitch per stem | ~2 s | ~20 s |

If separation exceeds roughly 2× real time, that is the trigger for X0R-307 (GPU path).
