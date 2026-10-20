# Stops only the dashboard server (python -m app.dashboard) listening on port 8000.
$stopped = 0
foreach ($listener in @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $listener.OwningProcess)
    if ($proc -and $proc.CommandLine -match '(?i)-m\s+app\.dashboard') {
        Stop-Process -Id $proc.ProcessId -Force
        $stopped++
    }
}
if ($stopped) { Write-Host 'Dashboard stopped.' } else { Write-Host 'Dashboard is not running.' }
Start-Sleep -Seconds 3
