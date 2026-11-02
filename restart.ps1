param(
    # Force an input-capable or a capture-only session. Without either, the running
    # session's mode is kept (capture-only when nothing is running).
    [switch]$EnableGameplayInput,
    [switch]$CaptureOnly,
    # Skip the in-game overlay (drawings; dashboard batches run through it).
    [switch]$NoOverlay,
    # Also open a dashboard tab. Off by default: the open tab reconnects by itself, and a
    # second tab would compete with it for dashboard controls.
    [switch]$Browser,
    [int]$Port = 8765
)

# Restart the bot: stop the engine and overlay, then start both again. The bot stays Off.
# Keys saved in Set up > Keys take effect here.

$ErrorActionPreference = 'Stop'
if ($EnableGameplayInput -and $CaptureOnly) { throw 'Choose -EnableGameplayInput or -CaptureOnly, not both.' }
$gameInput = [bool]$EnableGameplayInput
if (-not $EnableGameplayInput -and -not $CaptureOnly) {
    try {
        $status = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/status" -TimeoutSec 2
        $gameInput = $status.capture_only -eq $false
    } catch { $gameInput = $false }
}
& (Join-Path $PSScriptRoot 'tools/restart_engine.ps1') -EnableGameplayInput:$gameInput -NoOverlay:$NoOverlay -Port $Port
if ($Browser) { Start-Process "http://127.0.0.1:$Port/" }
