[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$KeepBuildCache
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleaseScript = Join-Path $ProjectRoot "build_release.ps1"

& $ReleaseScript -SkipTests:$SkipTests -KeepBuildCache:$KeepBuildCache
