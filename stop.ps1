param([int]$Port = 8765)

# Turn the bot off: stop the engine through its own API (keys released), close its
# launcher windows and close the in-game overlay.

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'tools/restart_engine.ps1') -StopOnly -Port $Port
