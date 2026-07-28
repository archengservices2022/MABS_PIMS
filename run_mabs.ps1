# Run MABS PIMS application
Write-Host "Starting MABS PIMS..." -ForegroundColor Cyan
$env:FIREBASE_PROJECT = "mabs"
$env:FLASK_DEBUG = "1"

cd $PSScriptRoot
python web_app/app.py
