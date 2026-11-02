param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'tools/start_overlay.ps1') -WaitForEngine -Port $Port
