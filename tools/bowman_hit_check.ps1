param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Space', 'Ctrl')]
    [string]$Key,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$action = if ($Key -eq 'Space') { 'attack' } else { 'skill' }
Push-Location $root
try {
    $arguments = @('-m', 'maplebot.hit_check', '--action', $action)
    if ($Check) { $arguments += '--check' }
    & "$root\.venv\Scripts\python.exe" @arguments
    if ($LASTEXITCODE -ne 0) { throw "Hit-check capture stopped; review the saved evidence/error." }
} finally {
    Pop-Location
}
