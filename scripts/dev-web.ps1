# Requires Node 20+. Proxies /api to http://localhost:8000 (see next.config.ts).
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\apps\web"

if (-not (Test-Path "node_modules")) { npm install }
npm run dev
