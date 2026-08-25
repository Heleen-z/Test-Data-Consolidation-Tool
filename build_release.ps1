[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$KeepBuildCache
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv-build"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ExePath = Join-Path $ProjectRoot "dist\Testing Data Consolidation Tool.exe"
$InfoPath = Join-Path $ProjectRoot "dist\release-info.txt"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-HostPython {
    $versionCheck = "import sys; v=sys.version_info; raise SystemExit(0 if (3,11) <= v[:2] < (3,14) else 1)"
    $candidates = @()

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += ,@($py.Source, "-3.13")
        $candidates += ,@($py.Source, "-3.12")
        $candidates += ,@($py.Source, "-3.11")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += ,@($python.Source)
    }

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $baseArgs = @()
        if ($candidate.Count -gt 1) {
            $baseArgs = $candidate[1..($candidate.Count - 1)]
        }
        try {
            & $exe @baseArgs -c $versionCheck 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
            continue
        }
    }

    throw "Python 3.11-3.13 was not found. Install Python from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'."
}

function Invoke-HostPython {
    param(
        [string[]]$PythonCommand,
        [string[]]$Arguments
    )
    $exe = $PythonCommand[0]
    $baseArgs = @()
    if ($PythonCommand.Count -gt 1) {
        $baseArgs = $PythonCommand[1..($PythonCommand.Count - 1)]
    }
    & $exe @baseArgs @Arguments
}

function Assert-OutputExeCanBeReplaced {
    if (-not (Test-Path -LiteralPath $ExePath)) {
        return
    }

    try {
        $stream = [System.IO.File]::Open($ExePath, "Open", "ReadWrite", "None")
        $stream.Close()
    }
    catch {
        throw "The existing EXE is currently in use and cannot be replaced. Close 'Testing Data Consolidation Tool.exe' first, then run build_release.ps1 again. Path: $ExePath"
    }
}

Set-Location -LiteralPath $ProjectRoot

Write-Step "Checking Python"
$HostPython = Get-HostPython
Invoke-HostPython $HostPython @("-c", "import sys; v=sys.version_info; raise SystemExit(0 if (3,11) <= v[:2] < (3,14) else 1)")
if ($LASTEXITCODE -ne 0) {
    throw "Python version must be 3.11, 3.12, or 3.13."
}

Write-Step "Creating build virtual environment"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Invoke-HostPython $HostPython @("-m", "venv", $VenvDir)
}

Write-Step "Installing build dependencies"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -e ".[dev,build]"

if (-not $SkipTests) {
    Write-Step "Running automated tests"
    & $VenvPython -m pytest -q
}
else {
    Write-Step "Skipping automated tests"
}

if (-not $KeepBuildCache) {
    Write-Step "Cleaning previous build output"
    Assert-OutputExeCanBeReplaced
    $BuildDir = Join-Path $ProjectRoot "build"
    if (Test-Path -LiteralPath $BuildDir) {
        Remove-Item -LiteralPath $BuildDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $ExePath) {
        Remove-Item -LiteralPath $ExePath -Force
    }
}

Write-Step "Building Windows EXE"
& $VenvPython -m PyInstaller --noconfirm --clean TestingDataTool.spec

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build finished but EXE was not found at: $ExePath"
}

$Hash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash
$SizeMb = [math]::Round((Get-Item -LiteralPath $ExePath).Length / 1MB, 2)
$Commit = "unknown"
try {
    $Commit = (git rev-parse --short HEAD).Trim()
}
catch {
    $Commit = "not-a-git-checkout"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InfoPath) | Out-Null
@(
    "Testing Data Consolidation Tool release build"
    "Built at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    "Git commit: $Commit"
    "EXE: $ExePath"
    "Size MB: $SizeMb"
    "SHA256: $Hash"
) | Set-Content -LiteralPath $InfoPath -Encoding UTF8

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "EXE: $ExePath"
Write-Host "Size: $SizeMb MB"
Write-Host "SHA256: $Hash"
Write-Host "Release info: $InfoPath"
