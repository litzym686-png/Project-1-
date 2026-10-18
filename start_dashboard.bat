@echo off
setlocal

echo Starting the local Service Reminder Dashboard...
echo Keep this window open while using http://127.0.0.1:8000
echo Press Ctrl+C to stop the dashboard.
echo.

set "DASHBOARD_WORKTREE=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $secure=$null; $ptr=[IntPtr]::Zero; $password=$null; try { $secure=Read-Host 'Dashboard password (input hidden)' -AsSecureString; if($secure.Length -eq 0){ throw 'A non-empty password is required.' }; $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); $password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr); $env:DASHBOARD_USERNAME='LitzyMartinez'; $env:DASHBOARD_PASSWORD=$password; Set-Location -LiteralPath $env:DASHBOARD_WORKTREE; $listeners=@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue); foreach($listener in $listeners){ $process=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); if($process -and $process.CommandLine -match '(?i)(^|\s)-m\s+app\.dashboard(\s|$)'){ Stop-Process -Id $process.ProcessId -Force } }; & python -m app.dashboard; exit $LASTEXITCODE } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 } finally { if($ptr -ne [IntPtr]::Zero){ [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }; $password=$null; Remove-Item Env:DASHBOARD_PASSWORD -ErrorAction SilentlyContinue }"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Dashboard stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
