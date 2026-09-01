# Run Flask locally connected to MABS Firebase (pims-955e3)
# Usage: .\run_mabs_local.ps1
#
# This points at the PRODUCTION database, so it starts in READ-ONLY mode:
# every Firebase write is a logged no-op. To allow writes for a specific
# session, run:  $env:FIREBASE_READONLY = "0";  .\run_mabs_local.ps1

# Kill any existing Flask on port 5000
Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

$env:FLASK_ENV          = "development"
$env:FLASK_DEBUG        = "1"
if (-not $env:FIREBASE_READONLY) { $env:FIREBASE_READONLY = "1" }  # fail safe against prod
$env:FIREBASE_API_KEY   = "AIzaSyBZIG4Gj_ZRRCqI1DXcf8DSXpO_9PkTgeY"
$env:FIREBASE_DB_URL    = "https://pims-955e3-default-rtdb.firebaseio.com"
$env:FIREBASE_SERVICE_ACCOUNT_JSON = (Get-Content "$env:USERPROFILE\.mabs\servicekey.json" -Raw)

Write-Host "Starting Flask with MABS Firebase (pims-955e3)..." -ForegroundColor Cyan
Write-Host "DB: $env:FIREBASE_DB_URL" -ForegroundColor Yellow
if ($env:FIREBASE_READONLY -eq "1") {
  Write-Host "READ-ONLY: Firebase writes are disabled this session." -ForegroundColor Green
} else {
  Write-Host "WRITES ENABLED against PRODUCTION data." -ForegroundColor Red
}
Write-Host "Open: http://127.0.0.1:5000" -ForegroundColor Green

Set-Location "$PSScriptRoot"
python web_app/app.py
