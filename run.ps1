param([switch]$EnableGameplayInput, [switch]$InTask)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run .\install.ps1 first.'
}
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($EnableGameplayInput -and -not $InTask -and -not $admin) {
    # MapleStory runs elevated; Windows drops keys from a non-elevated bot.
    if (-not (Get-ScheduledTask -TaskName 'MapleBot' -ErrorAction SilentlyContinue)) {
        throw 'Run .\tools\install_elevated_task.ps1 once to register the elevated MapleBot task.'
    }
    Start-ScheduledTask -TaskName 'MapleBot'
    'Started the elevated MapleBot task; its window shows the debugger URL.'
    return
}
$debugArguments = @('-m', 'maplebot', 'debug')
if (-not $EnableGameplayInput) {
    $debugArguments += '--capture-only'
}
# The browser dashboard owns the control lease. Native overlay remains an explicit opt-in.
& .venv\Scripts\python.exe @debugArguments
if ($InTask -and $LASTEXITCODE) {
    Read-Host "Engine exited with code $LASTEXITCODE. Press Enter to close"
}
