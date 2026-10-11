# Builds dist\ExamLoader\ExamLoader.exe (one-folder, windowed) with PyInstaller.
# Usage: .\build.ps1            (add -SkipTests to skip the unit tests)
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Set-Location $ProjectRoot

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment in .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv } else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment." }
}

Write-Host "Installing build dependencies ..."
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
& $VenvPython -m pip install -q -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Failed to install build dependencies." }

if (-not $SkipTests) {
    Write-Host "Running unit tests ..."
    & $VenvPython -m unittest test_cli test_automator test_browser
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed; build stopped." }
}

$Version = (& $VenvPython -c "import examnet; print(examnet.__version__)").Trim()
Write-Host "Building ExamLoader $Version ..."
& $VenvPython -m PyInstaller --noconfirm --clean --log-level WARN `
    --distpath dist --workpath build packaging\ExamLoader.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$OutDir = Join-Path $ProjectRoot "dist\ExamLoader"
$SizeMB = (Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Built {0} ({1:N0} MB)" -f (Join-Path $OutDir "ExamLoader.exe"), $SizeMB)
