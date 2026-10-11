# Builds dist\ExamLoader\ExamLoader.exe (one-folder, windowed) with PyInstaller.
# Usage: .\build.ps1            (add -SkipTests to skip the unit tests)
#        .\build.ps1 -Installer (also builds dist\ExamLoader-examdotnet-setup-<version>.exe; needs Inno Setup 6)
param(
    [switch]$SkipTests,
    [switch]$Installer
)

function Find-InnoCompiler {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    throw "Inno Setup 6 was not found. Install it (winget install JRSoftware.InnoSetup) and re-run."
}

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
    & $VenvPython -m unittest test_cli test_automator test_browser test_updates
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

if ($Installer) {
    $Iscc = Find-InnoCompiler
    Write-Host "Building installer with $Iscc ..."
    & $Iscc /Q "/DAppVersion=$Version" packaging\ExamLoader.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
    $SetupExe = Join-Path $ProjectRoot "dist\ExamLoader-examdotnet-setup-$Version.exe"
    Write-Host ("Built {0} ({1:N0} MB)" -f $SetupExe, ((Get-Item $SetupExe).Length / 1MB))
}
