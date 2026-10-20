# OPTIONAL: saves the dashboard password encrypted with Windows DPAPI so the launcher never asks.
# The file can only be decrypted by your Windows account on this PC. It is never plain text and is outside the repo.
# Run again to change it. Run with -Remove to delete it.
param([switch]$Remove)

$dataDir = Join-Path $env:LOCALAPPDATA 'ServiceReminderDashboard'
$credFile = Join-Path $dataDir 'credential.dpapi'

if ($Remove) {
    Remove-Item -LiteralPath $credFile -ErrorAction SilentlyContinue
    Write-Host 'Saved password removed.'
    return
}

$secure = Read-Host 'Dashboard password to save (input hidden)' -AsSecureString
if ($secure.Length -eq 0) { Write-Host 'No password entered. Nothing saved.'; exit 1 }
New-Item -ItemType Directory -Force $dataDir | Out-Null
$secure | ConvertFrom-SecureString | Set-Content -LiteralPath $credFile -Encoding ascii
Write-Host 'Password saved (encrypted for your Windows account only).'
