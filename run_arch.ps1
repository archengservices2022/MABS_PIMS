# Run ARCH Invoice application
Write-Host "Starting ARCH Invoice..." -ForegroundColor Cyan
$env:FIREBASE_PROJECT = "arch"
$env:FLASK_DEBUG = "1"

cd $PSScriptRoot
python web_app/app.py
