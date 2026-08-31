# Resolves which virtual environment to use.
#
# Precedence: -Venv argument, then $env:EXTRACT0R_VENV, then the in-project .venv.
# The override exists because the heavy ML stack cannot live in the project tree on
# Windows without blowing past MAX_PATH - see docs/RUNBOOK.md.

function Resolve-X0rVenv {
    param([string]$Venv)

    $root = Split-Path -Parent $PSScriptRoot
    $candidate = if ($Venv) { $Venv }
        elseif ($env:EXTRACT0R_VENV) { $env:EXTRACT0R_VENV }
        else { Join-Path $root "services\api\.venv" }

    $python = Join-Path $candidate "Scripts\python.exe"
    if (-not (Test-Path $python)) {
        throw "No Python at $python. Run scripts/dev-api.ps1 first, or pass -Venv <path>."
    }
    return $python
}
