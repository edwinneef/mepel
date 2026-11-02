param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
# Use the managed restart; input capability is enabled, but the bot stays Off.
& (Join-Path $PSScriptRoot 'tools/restart_engine.ps1') -EnableGameplayInput -Port $Port
