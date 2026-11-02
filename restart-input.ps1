param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
# Start both controls after the managed restart; the bot stays Off.
& (Join-Path $PSScriptRoot 'tools/restart_engine.ps1') -EnableGameplayInput -StartNativeOverlay -Port $Port
Start-Process "http://127.0.0.1:$Port/"
