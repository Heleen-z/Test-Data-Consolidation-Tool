param([string]$DemoFolder = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$demoPath = (Resolve-Path -LiteralPath $DemoFolder).Path
if (-not (Test-Path -LiteralPath (Join-Path $demoPath 'expected.json'))) {
    throw 'Choose the generated outputs/ui-demo directory with -DemoFolder.'
}
$exePath = Join-Path $demoPath 'Testing Data Consolidation Tool.exe'
if (-not (Test-Path -LiteralPath $exePath)) {
    $repoPath = Split-Path (Split-Path $demoPath -Parent) -Parent
    $sourceExe = Join-Path $repoPath 'dist/Testing Data Consolidation Tool.exe'
    if (-not (Test-Path -LiteralPath $sourceExe)) { throw 'Build the release EXE first.' }
    Copy-Item -LiteralPath $sourceExe -Destination $exePath
}
# Only the new child inherits this isolated profile; the current shell is restored.
$previousProfile = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = Join-Path $demoPath 'profile'
    $process = Start-Process -FilePath $exePath -WorkingDirectory $demoPath -WindowStyle Hidden -PassThru
    Write-Output "Demo EXE started. PID: $($process.Id)"
} finally {
    $env:LOCALAPPDATA = $previousProfile
}
