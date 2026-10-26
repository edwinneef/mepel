param([switch]$Uninstall)

# MapleStory runs as administrator, and Windows (UIPI) silently drops keys sent from a
# non-elevated process. This registers a "MapleBot" task that starts the input-capable
# engine with highest privileges, so run.ps1 -EnableGameplayInput needs no UAC prompt.
# Registering or removing the task needs one UAC approval.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$taskName = 'MapleBot'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$admin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $admin) {
    $arguments = @('-NoProfile', '-File', $PSCommandPath)
    if ($Uninstall) { $arguments += '-Uninstall' }
    $process = Start-Process pwsh -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Elevated task setup failed (exit $($process.ExitCode))" }
    $installed = [bool](Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)
    if ($Uninstall -eq $installed) { throw "Task $taskName was not $(if ($Uninstall) { 'removed' } else { 'registered' })" }
    "Task $taskName $(if ($Uninstall) { 'removed' } else { 'registered' })"
    return
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    return
}

$pwsh = (Get-Command pwsh).Source
# No -NoExit: the window closes with the engine, so restarts never leave elevated windows.
$action = New-ScheduledTaskAction -Execute $pwsh -WorkingDirectory $root `
    -Argument "-NoProfile -File `"$root\run.ps1`" -EnableGameplayInput -InTask"
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal `
    -Settings $settings -Description 'Maple External Bot input-capable engine (elevated)' `
    -Force | Out-Null
