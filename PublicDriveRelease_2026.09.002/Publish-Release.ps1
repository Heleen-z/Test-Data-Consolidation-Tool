param(
    [string]$ReleaseRoot = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool',
    [string]$ConfigVersion = '2026.09.002',
    [Parameter(Mandatory = $true)][string]$AppVersion,
    [string]$ReleaseNote = 'ToolUseLogs logging, Excel 403 bridge, and manual queue sync'
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceConfig = Join-Path $packageRoot "configs\$ConfigVersion\operations.yaml"
$manifestPath = Join-Path $ReleaseRoot 'release-manifest.json'
$targetConfig = Join-Path $ReleaseRoot "configs\$ConfigVersion\operations.yaml"
$expectedExe = Join-Path $ReleaseRoot "app\$AppVersion\Testing Data Consolidation Tool.exe"

if (-not (Test-Path -LiteralPath $ReleaseRoot -PathType Container)) { throw "Cannot access release root: $ReleaseRoot" }
if (-not (Test-Path -LiteralPath $sourceConfig -PathType Leaf)) { throw "Release package is missing: $sourceConfig" }
if (Test-Path -LiteralPath $targetConfig) { throw "Config version already exists and will not be overwritten: $targetConfig" }
if (-not (Test-Path -LiteralPath $expectedExe -PathType Leaf)) { throw "Copy the EXE to this versioned public-drive location before publishing: $expectedExe" }

$current = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($current.schema_version -ne 1) { throw "Unsupported manifest schema_version: $($current.schema_version)" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetConfig) | Out-Null
Copy-Item -LiteralPath $sourceConfig -Destination $targetConfig
$configHash = (Get-FileHash -LiteralPath $targetConfig -Algorithm SHA256).Hash

$current.published_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
$current.published_by = $env:USERNAME
$current.config.version = $ConfigVersion
$current.config.path = "configs/$ConfigVersion/operations.yaml"
$current.config.sha256 = $configHash
$current.application.latest_version = $AppVersion
$current.application.download_path = "app/$AppVersion/Testing Data Consolidation Tool.exe"
$current.application.release_note = $ReleaseNote

$temporaryManifest = Join-Path $ReleaseRoot 'release-manifest.next.json'
try {
    $current | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporaryManifest -Encoding UTF8
    Get-Content -LiteralPath $temporaryManifest -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force
    Write-Host "Published config $ConfigVersion and activated application $AppVersion."
    Write-Host "Config SHA256: $configHash"
}
finally {
    Remove-Item -LiteralPath $temporaryManifest -Force -ErrorAction SilentlyContinue
}
