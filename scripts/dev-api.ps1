# Start the API with the stub backends. First run creates the venv.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\services\api"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
}

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
