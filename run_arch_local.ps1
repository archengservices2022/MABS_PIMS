# Run Flask locally connected to Arch Firebase (invoice-7fe93)
# Usage: .\run_arch_local.ps1
#
# This points at the PRODUCTION database, so it starts in READ-ONLY mode:
# every Firebase write is a logged no-op. To allow writes for a specific
# session, run:  $env:FIREBASE_READONLY = "0";  .\run_arch_local.ps1

# Kill any existing Flask on port 5000
Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

$env:FLASK_ENV          = "development"
$env:FLASK_DEBUG        = "1"
if (-not $env:FIREBASE_READONLY) { $env:FIREBASE_READONLY = "1" }  # fail safe against prod
$env:FIREBASE_API_KEY   = "AIzaSyD6F6T_KIZ90TkCOL03-jSXTeuPM5WVwJY"
$env:FIREBASE_DB_URL    = "https://invoice-7fe93-default-rtdb.firebaseio.com"
$env:FIREBASE_SERVICE_ACCOUNT_JSON = (Get-Content "$env:USERPROFILE\.arch\servicekey.json" -Raw)

Write-Host "Starting Flask with ARCH Firebase (invoice-7fe93)..." -ForegroundColor Cyan
Write-Host "DB: $env:FIREBASE_DB_URL" -ForegroundColor Yellow
if ($env:FIREBASE_READONLY -eq "1") {
  Write-Host "READ-ONLY: Firebase writes are disabled this session." -ForegroundColor Green
} else {
  Write-Host "WRITES ENABLED against PRODUCTION data." -ForegroundColor Red
}
Write-Host "Open: http://127.0.0.1:5000" -ForegroundColor Green

Set-Location "$PSScriptRoot"
python web_app/app.py
