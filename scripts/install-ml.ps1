# Installs the heavy backends (Demucs, basic-pitch, librosa, matchering) into the API venv.
# Expect several GB and a long download. ffmpeg must already be on PATH.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\services\api"

.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt

Write-Host "Now set SEPARATION_BACKEND=demucs, TRANSCRIPTION_BACKEND=basic_pitch, DRUM_BACKEND=onset in .env"
