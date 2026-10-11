param(
    [switch]$InstallPlaywrightBrowsers,
    [switch]$StrictPlaywrightInstall,
    [switch]$Gui,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
$MainModule = "examnet"

function Get-SystemPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 3 was not found. Install Python 3.8+ and re-run this launcher."
}

function Test-VenvHealthy {
    param(
        [string]$VenvPath,
        [string]$VenvPythonPath
    )

    if (-not (Test-Path $VenvPythonPath)) {
        return $false
    }

    $cfgPath = Join-Path $VenvPath "pyvenv.cfg"
    if (Test-Path $cfgPath) {
        $homeLine = Select-String -Path $cfgPath -Pattern '^\s*home\s*=\s*(.+)\s*$' | Select-Object -First 1
        if ($homeLine) {
            $homeDir = $homeLine.Matches[0].Groups[1].Value.Trim()
            if (-not (Test-Path $homeDir)) {
                return $false
            }
        }
    }

    & $VenvPythonPath -c "import sys; print(sys.version)"
    return ($LASTEXITCODE -eq 0)
}

function New-Venv {
    param(
        [string]$VenvPath
    )

    Write-Host "Creating virtual environment in .venv ..."
    $pyCmd = Get-SystemPython
    if ($pyCmd.Length -gt 1) {
        $pyArgs = @()
        $pyArgs += $pyCmd[1..($pyCmd.Length - 1)]
        $pyArgs += @("-m", "venv", $VenvPath)
        & $pyCmd[0] @pyArgs
    } else {
        & $pyCmd[0] -m venv $VenvPath
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }
}

if (-not (Test-Path $ReqFile)) {
    throw "Could not find requirements file: $ReqFile"
}

if (-not (Test-VenvHealthy -VenvPath $VenvDir -VenvPythonPath $VenvPython)) {
    if (Test-Path $VenvDir) {
        Write-Host "Existing virtual environment is invalid for this machine. Recreating .venv ..."
        Remove-Item -Recurse -Force $VenvDir
    }
    New-Venv -VenvPath $VenvDir
}

Write-Host "Installing/updating Python dependencies ..."
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
Write-Host "Set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 for this session."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip in virtual environment."
}

& $VenvPython -m pip install -r $ReqFile
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements."
}

if ($InstallPlaywrightBrowsers -or $StrictPlaywrightInstall) {
    Write-Warning "Ignoring Playwright browser install flags on this launcher; browser download is disabled for protected-network use."
}
Write-Host "Skipping Playwright browser installation (always disabled in this launcher)."

if ($Gui) {
    Write-Host "Starting exam automation GUI ..."
    & $VenvPython -m "$MainModule.gui"
} else {
    Write-Host "Starting exam automation ..."
    & $VenvPython -m $MainModule @AppArgs
}
exit $LASTEXITCODE
