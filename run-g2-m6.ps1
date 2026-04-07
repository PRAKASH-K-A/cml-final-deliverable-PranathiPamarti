$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found in PATH."
}

Write-Host "[g2-m6] Installing dependencies..." -ForegroundColor Cyan
python -m pip install -r "$Root\requirements.txt"

Write-Host "[g2-m6] Running integrated G2-M6 suite..." -ForegroundColor Cyan
python "$Root\run_g2_m6_suite.py" --scenario "scenario.local.json" --base-url "http://localhost:8090" --reports-dir "reports"

Write-Host "[g2-m6] Completed. Check reports folder." -ForegroundColor Green
