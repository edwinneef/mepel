param([switch]$EnableGameplayInput)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run .\install.ps1 first.'
}
$debugArguments = @('-m', 'maplebot', 'debug')
if (-not $EnableGameplayInput) {
    $debugArguments += '--capture-only'
}
& .venv\Scripts\python.exe @debugArguments
