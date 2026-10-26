$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
}
& .venv\Scripts\python.exe -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw 'Could not initialize pip in the project virtual environment.' }
& .venv\Scripts\python.exe -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Push-Location (Join-Path $PSScriptRoot 'ui')
try {
    npm ci --ignore-scripts
    if ($LASTEXITCODE) { throw 'UI dependency installation failed.' }
    node node_modules/electron/install.js
    if ($LASTEXITCODE) { throw 'Overlay runtime installation failed.' }
    npm run build
    if ($LASTEXITCODE) { throw 'Overlay build failed.' }
} finally { Pop-Location }
Write-Output 'Installed engine and native overlay. Run .\run.ps1; F7 opens settings, F6 toggles On/Off.'
