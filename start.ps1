param(
    # Allow gameplay keys (elevated MapleBot task). Without it the session is capture-only.
    [switch]$EnableGameplayInput,
    # Skip the in-game overlay (drawings and widget).
    [switch]$NoOverlay,
    # Do not open the dashboard in the browser.
    [switch]$NoBrowser,
    [int]$Port = 8765
)

# Start the bot: engine, in-game overlay and browser dashboard. The bot stays Off.
# Use .\restart.ps1 when it is already running and .\stop.ps1 to turn everything off.

$ErrorActionPreference = 'Stop'
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "The engine is already running on port $Port. Use .\restart.ps1 to restart it or .\stop.ps1 to stop it."
}
& (Join-Path $PSScriptRoot 'tools/restart_engine.ps1') -EnableGameplayInput:$EnableGameplayInput `
    -NoOverlay:$NoOverlay -Port $Port
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
