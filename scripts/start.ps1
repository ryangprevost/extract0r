# Start Extract0r: the Python API, then the Studio front end, then open a browser.
#
#   .\scripts\start.ps1              # real backends if the ML venv exists, stubs otherwise
#   .\scripts\start.ps1 -Stubs       # force the stub backends (fast, no models)
#   .\scripts\start.ps1 -NoBrowser
#
# The API opens in its own window so you can watch the separation logs; the Studio runs
# in this one. Ctrl+C here stops the Studio, and closing the other window stops the API.

param(
    [string]$Venv,
    [switch]$Stubs,
    [switch]$NoBrowser,
    [int]$ApiPort = 8000,
    [int]$StudioPort = 5080
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"

function Test-PortBusy([int]$Port) {
    $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# ── pick a Python ───────────────────────────────────────────────────────────────
# The ML venv lives outside the project tree because torch cannot be installed inside
# it on Windows (MAX_PATH). See docs/RUNBOOK.md.
if (-not $Venv) {
    $Venv = if ($env:EXTRACT0R_VENV) { $env:EXTRACT0R_VENV } else { "$env:USERPROFILE\.x0r-venv" }
}
$mlPython = Join-Path $Venv "Scripts\python.exe"
$appPython = Join-Path $api ".venv\Scripts\python.exe"

if ($Stubs -or -not (Test-Path $mlPython)) {
    if (-not (Test-Path $appPython)) {
        throw "No virtual environment found. Run .\scripts\dev-api.ps1 once to create it."
    }
    $python = $appPython
    if (-not $Stubs) {
        Write-Host "No ML venv at $Venv - starting with the STUB backends." -ForegroundColor Yellow
        Write-Host "Separation will return copies of your file, not real stems." -ForegroundColor Yellow
        Write-Host "Run .\scripts\install-ml.ps1 to get the real ones.`n" -ForegroundColor Yellow
    }
} else {
    $python = $mlPython
    Write-Host "Using the ML venv at $Venv" -ForegroundColor DarkGray
}

# ── API ─────────────────────────────────────────────────────────────────────────
# Bound to 0.0.0.0 rather than 127.0.0.1 so it answers on IPv4 and IPv6 alike: anything
# reaching it via the name "localhost" resolves to ::1 first on Windows, and a v4-only
# listener makes every such call wait out a connect timeout.
if (Test-PortBusy $ApiPort) {
    Write-Host "Something is already listening on :$ApiPort - reusing it." -ForegroundColor DarkGray
} else {
    Write-Host "Starting the API on http://localhost:$ApiPort ..." -ForegroundColor Cyan
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$ApiPort") `
        -WorkingDirectory $api

    # Wait for it to answer rather than guessing at a sleep duration.
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 400
        try {
            $health = Invoke-RestMethod "http://localhost:$ApiPort/api/v1/health" -TimeoutSec 2
        } catch { $health = $null }
    } while (-not $health -and (Get-Date) -lt $deadline)

    if (-not $health) { throw "The API did not come up on :$ApiPort. Check the other window." }
    Write-Host "API is up (v$($health.version), $($health.env))." -ForegroundColor Green
}

# ── report what the API can actually do ─────────────────────────────────────────
try {
    $caps = Invoke-RestMethod "http://localhost:$ApiPort/api/v1/capabilities" -TimeoutSec 5
    Write-Host ""
    Write-Host "Backends installed on this server:" -ForegroundColor Cyan
    foreach ($name in $caps.installed.PSObject.Properties.Name) {
        $on = $caps.installed.$name
        Write-Host ("  {0,-14} {1}" -f $name, $(if ($on) { "yes" } else { "no" })) `
            -ForegroundColor $(if ($on) { "Green" } else { "DarkGray" })
    }
    Write-Host ""
} catch {
    Write-Host "Could not read /capabilities - continuing anyway.`n" -ForegroundColor Yellow
}

# ── Studio ──────────────────────────────────────────────────────────────────────
if (Test-PortBusy $StudioPort) {
    Write-Host "Something is already listening on :$StudioPort." -ForegroundColor Yellow
    if (-not $NoBrowser) { Start-Process "http://localhost:$StudioPort" }
    return
}

if (-not $NoBrowser) {
    # Fire the browser off on a delay so the page loads into a listening server.
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 4
        Start-Process "http://localhost:$using:StudioPort"
    } | Out-Null
}

Write-Host "Starting the Studio on http://localhost:$StudioPort  (Ctrl+C to stop)" -ForegroundColor Cyan
dotnet run --project (Join-Path $root "apps\studio\Extract0r.Studio.csproj") `
    --urls "http://localhost:$StudioPort"
