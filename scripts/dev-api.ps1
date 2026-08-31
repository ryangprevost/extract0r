# Start the API. First run creates the in-project venv and installs the light deps.
#
#   .\scripts\dev-api.ps1                              # stub backends
#   .\scripts\dev-api.ps1 -Venv C:\Users\you\.x0r-venv  # real ML backends
param([string]$Venv)

$ErrorActionPreference = "Stop"
$api = Join-Path (Split-Path -Parent $PSScriptRoot) "services\api"

if (-not $Venv -and -not $env:EXTRACT0R_VENV -and -not (Test-Path "$api\.venv")) {
    Write-Host "Creating the app venv..."
    python -m venv "$api\.venv"
    & "$api\.venv\Scripts\python.exe" -m pip install --upgrade pip
    & "$api\.venv\Scripts\python.exe" -m pip install -r "$api\requirements.txt" -r "$api\requirements-dev.txt"
}

. "$PSScriptRoot\_venv.ps1"
$python = Resolve-X0rVenv -Venv $Venv

Set-Location $api
& $python -m uvicorn app.main:app --reload --port 8000
