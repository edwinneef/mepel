param([switch]$WaitForEngine, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$electron = Join-Path $root 'ui/node_modules/electron/dist/electron.exe'
if (-not (Test-Path -LiteralPath $electron)) { throw 'Run npm install in ui/ before starting the overlay.' }
if ($WaitForEngine) {
    $deadline = (Get-Date).AddSeconds(120)
    $ready = $false
    while ((Get-Date) -lt $deadline -and -not $ready) {
        try {
            $null = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/status" -TimeoutSec 2
            $ready = $true
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Engine did not become available for the overlay.' }
}
$env:MAPLEBOT_PORT = "$Port"
# Electron needs its desktop runtime even when called from a Node-based host.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Start-Process -FilePath $electron -ArgumentList ('"' + (Join-Path $root 'ui/overlay/main.cjs') + '"') -WorkingDirectory $root | Out-Null
