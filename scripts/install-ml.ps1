# Installs the heavy backends: torch, Demucs, basic-pitch, librosa, matchering.
#
# Two things here are not a plain `pip install`, and both have bitten this project:
#
#   1. MAX_PATH. Torch's bundled licence tree is ~160 characters deep. Inside a normal
#      project path that exceeds the Windows limit of 260, pip fails with WinError 206
#      and leaves a HALF-INSTALLED torch behind. The symptom is a baffling
#      "ModuleNotFoundError: No module named 'torchgen'" on import. Hence the venv lives
#      on a short path by default, not in services/api/.venv.
#
#   2. basic-pitch pins tensorflow<2.15.1, and TensorFlow publishes nothing below 2.16
#      for Python 3.12, so it cannot resolve. The package also ships ONNX weights, and
#      ICASSP_2022_MODEL_PATH resolves to them when TensorFlow is absent - so it is
#      installed with --no-deps and runs on onnxruntime instead.
#
# See docs/RUNBOOK.md for the alternatives (enabling long paths, or Docker).
param([string]$Venv = "$env:USERPROFILE\.x0r-venv")

$ErrorActionPreference = "Stop"
$api = Join-Path (Split-Path -Parent $PSScriptRoot) "services\api"

$longPaths = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
    -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
if ($longPaths -ne 1) {
    Write-Host "Windows long paths are disabled, so the short venv path matters." -ForegroundColor Yellow
}
if ($Venv.Length -gt 40) {
    Write-Warning "$Venv is long. If the install fails with WinError 206, pick something shorter."
}

if (-not (Test-Path $Venv)) {
    Write-Host "Creating the ML venv at $Venv ..."
    python -m venv $Venv
}
$python = Join-Path $Venv "Scripts\python.exe"

& $python -m pip install --upgrade pip
& $python -m pip install -r "$api\requirements.txt" -r "$api\requirements-dev.txt"
& $python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Fail here, loudly, rather than three minutes into someone's first separation.
& $python -c "import torch; print('torch', torch.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "torch did not import cleanly - almost certainly MAX_PATH. See docs/RUNBOOK.md."
}

& $python -m pip install -r "$api\requirements-ml.txt"
& $python -m pip install --no-deps "basic-pitch==0.4.0"

Write-Host ""
Write-Host "Verifying the backends actually import..." -ForegroundColor Cyan
Push-Location $api
& $python -c @"
from app.services.separation.demucs import DemucsSeparator
from app.services.transcription.basic_pitch import BasicPitchTranscriber
from app.services.transcription.drums import OnsetDrumTranscriber
from app.services.transcription.pyin import PyinTranscriber

checks = [
    ('demucs', DemucsSeparator()),
    ('basic_pitch', BasicPitchTranscriber()),
    ('pyin', PyinTranscriber()),
    ('onset_drums', OnsetDrumTranscriber()),
]
for name, backend in checks:
    print(('  OK    ' if backend.available() else '  FAIL  ') + name)
raise SystemExit(1 if [n for n, b in checks if not b.available()] else 0)
"@
$verified = $LASTEXITCODE -eq 0
Pop-Location

if (-not $verified) {
    throw "One or more backends failed to import. See docs/RUNBOOK.md."
}

Write-Host ""
Write-Host "Done. To use it:" -ForegroundColor Green
Write-Host "  .\scripts\dev-api.ps1 -Venv `"$Venv`""
Write-Host "  .\scripts\test-api.ps1 -Venv `"$Venv`" -Ml"
Write-Host ""
Write-Host "Then in .env: SEPARATION_BACKEND=demucs, TRANSCRIPTION_BACKEND=auto, DRUM_BACKEND=onset"
