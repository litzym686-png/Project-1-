# Creates Desktop shortcuts. Add -Startup to also start the dashboard when you sign in to Windows (optional).
# Add -RemoveStartup to undo it.
param([switch]$Startup, [switch]$RemoveStartup)

$launcher = $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function New-Shortcut($path, $script, $extra) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $ps
    $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $launcher $script)`" $extra"
    $s.WorkingDirectory = $launcher
    $s.Save()
}

New-Shortcut (Join-Path $desktop 'Service Reminder Dashboard.lnk') 'open_dashboard.ps1' ''
New-Shortcut (Join-Path $desktop 'Stop Service Reminder Dashboard.lnk') 'stop_dashboard.ps1' ''
Write-Host 'Desktop shortcuts created.'

$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Service Reminder Dashboard.lnk'
if ($Startup) {
    New-Shortcut $startupLink 'open_dashboard.ps1' '-NoBrowser'
    Write-Host 'Auto-start at sign-in enabled (requires the saved password from setup_saved_password.ps1).'
}
if ($RemoveStartup) {
    Remove-Item -LiteralPath $startupLink -ErrorAction SilentlyContinue
    Write-Host 'Auto-start removed.'
}
