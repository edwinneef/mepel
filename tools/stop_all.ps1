param([int]$Port = 8765)

# Turn the bot off: shut the engine down through its own API, close its launcher
# windows and close the overlay. restart_engine.ps1 -StopOnly owns that logic.

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'restart_engine.ps1') -StopOnly -Port $Port
