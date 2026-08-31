# Run the API test suite. Pass -Venv to run the `ml`-marked tests against a real backend.
param([string]$Venv, [switch]$Ml)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_venv.ps1"
$python = Resolve-X0rVenv -Venv $Venv

Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "services\api")

if ($Ml) { & $python -m pytest -m ml -q } else { & $python -m pytest -q }
