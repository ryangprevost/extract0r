$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\services\api"
.\.venv\Scripts\python.exe -m pytest -q
