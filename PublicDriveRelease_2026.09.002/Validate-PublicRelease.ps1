param(
    [string]$ReleaseRoot = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool'
)

$ErrorActionPreference = 'Stop'

function Resolve-ReleasePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Relative,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $normalized = $Relative.Replace('/', '\')
    if ([System.IO.Path]::IsPathRooted($normalized) -or $normalized.Split('\') -contains '..') {
        throw "$Label must be a safe relative path: $Relative"
    }
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $rootFull $normalized))
    if (-not $resolved.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label resolves outside the release root: $Relative"
    }
    return $resolved
}

if (-not (Test-Path -LiteralPath $ReleaseRoot -PathType Container)) {
    throw "Release root does not exist or is not accessible: $ReleaseRoot"
}

$manifestPath = Join-Path $ReleaseRoot 'release-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "release-manifest.json was not found: $manifestPath"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema_version -ne 1) {
    throw "Unsupported manifest schema_version: $($manifest.schema_version)"
}

foreach ($version in @(
    $manifest.config.version,
    $manifest.templates.version,
    $manifest.application.latest_version,
    $manifest.application.minimum_supported_version
)) {
    if ($version -notmatch '^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$') {
        throw "Invalid version: $version"
    }
}

$configPath = Resolve-ReleasePath $ReleaseRoot $manifest.config.path 'config.path'
$templatePath = Resolve-ReleasePath $ReleaseRoot $manifest.templates.path 'templates.path'
$appPath = Resolve-ReleasePath $ReleaseRoot $manifest.application.download_path 'application.download_path'

$checks = @(
    [PSCustomObject]@{ Item = 'Manifest'; Path = $manifestPath; Exists = $true; HashOK = $null },
    [PSCustomObject]@{ Item = 'Operations config'; Path = $configPath; Exists = (Test-Path -LiteralPath $configPath -PathType Leaf); HashOK = $null },
    [PSCustomObject]@{ Item = 'Template bundle'; Path = $templatePath; Exists = (Test-Path -LiteralPath $templatePath -PathType Leaf); HashOK = $null },
    [PSCustomObject]@{ Item = 'Application'; Path = $appPath; Exists = (Test-Path -LiteralPath $appPath -PathType Leaf); HashOK = $null }
)

if (-not $checks[1].Exists -or -not $checks[2].Exists -or -not $checks[3].Exists) {
    $checks | Format-Table -AutoSize
    throw 'One or more release files are missing.'
}

$checks[1].HashOK = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $manifest.config.sha256
$checks[2].HashOK = (Get-FileHash -LiteralPath $templatePath -Algorithm SHA256).Hash -eq $manifest.templates.sha256

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($templatePath)
try {
    $xlsxCount = @($archive.Entries | Where-Object { $_.FullName -match '\.xlsx$' -and $_.Name -notlike '~$*' }).Count
} finally {
    $archive.Dispose()
}

$checks | Format-Table -AutoSize
Write-Host "App version: $($manifest.application.latest_version)"
Write-Host "Config version: $($manifest.config.version)"
Write-Host "Template version: $($manifest.templates.version)"
Write-Host "XLSX files in template bundle: $xlsxCount"

if (-not $checks[1].HashOK -or -not $checks[2].HashOK) {
    throw 'SHA256 verification failed.'
}
if ($xlsxCount -le 0) {
    throw 'No XLSX templates were found in TemplateBundle.zip.'
}

Write-Host 'Managed release validation passed.' -ForegroundColor Green
