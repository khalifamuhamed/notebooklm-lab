# Windows setup for notebooklm-lab (PowerShell).  Run from anywhere:  .\scripts\setup.ps1
# If scripts are blocked:  Set-ExecutionPolicy -Scope Process Bypass
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "1/4 Creating virtual environment (.venv) ..."
if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }

Write-Host "2/4 Activating ..."
. .\.venv\Scripts\Activate.ps1

Write-Host "3/4 Installing pinned requirements (notebooklm-py 0.8.6 + official mcp SDK + pytest) ..."
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .

Write-Host "4/4 Self-check ..."
python -m notebooklm_lab selfcheck --mcp

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  python -m notebooklm_lab demo --open        (offline sample, no login)"
Write-Host "  python -m notebooklm_lab login              (one-time Google sign-in on THIS computer)"
Write-Host "  python -m notebooklm_lab digest --file links.txt --open"
