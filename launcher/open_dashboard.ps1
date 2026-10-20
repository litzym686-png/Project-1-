# Starts the Service Reminder Dashboard (if needed), waits until /login responds, then opens Edge.
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$url = 'http://127.0.0.1:8000/login'
$dataDir = Join-Path $env:LOCALAPPDATA 'ServiceReminderDashboard'
$credFile = Join-Path $dataDir 'credential.dpapi'
$logFile = Join-Path $dataDir 'dashboard.log'

function Test-Login {
    try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 } catch { return $false }
}

function Open-Edge {
    if ($NoBrowser) { return }
    try { Start-Process 'msedge.exe' -ArgumentList $url } catch { Start-Process $url }
}

try {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $listener.OwningProcess)
        if (-not ($proc -and $proc.CommandLine -match '(?i)-m\s+app\.dashboard')) {
            throw 'Port 8000 is used by another program. Close it and try again.'
        }
        if (-not (Test-Login)) {
            throw 'The dashboard is running but not responding. Run stop_dashboard.ps1, then try again.'
        }
        Write-Host 'Dashboard is already running. Opening Edge...'
        Open-Edge
        return
    }

    New-Item -ItemType Directory -Force $dataDir | Out-Null
    if (Test-Path $credFile) {
        $secure = (Get-Content -LiteralPath $credFile -Raw).Trim() | ConvertTo-SecureString
    } else {
        $secure = Read-Host 'Dashboard password (input hidden)' -AsSecureString
    }
    if ($secure.Length -eq 0) { throw 'A non-empty password is required.' }

    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $env:DASHBOARD_USERNAME = 'LitzyMartinez'
        $env:DASHBOARD_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $python = (Get-Command python -All | Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1).Source
        if (-not $python) { $python = (Get-Command python).Source }
        Start-Process -FilePath $python -ArgumentList '-m', 'app.dashboard' -WorkingDirectory $root `
            -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err')
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        Remove-Item Env:DASHBOARD_PASSWORD -ErrorAction SilentlyContinue
    }

    Write-Host 'Starting dashboard...'
    $ready = $false
    for ($i = 0; $i -lt 30 -and -not $ready; $i++) {
        Start-Sleep -Seconds 1
        $ready = Test-Login
    }
    if (-not $ready) { throw "The dashboard did not start. See $logFile.err" }
    Write-Host 'Dashboard is ready. Opening Edge...'
    Open-Edge
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Start-Sleep -Seconds 8
    exit 1
}
