$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean TestingDataTool.spec
Write-Host "Build complete: $ProjectRoot\dist\Testing Data Consolidation Tool.exe"

