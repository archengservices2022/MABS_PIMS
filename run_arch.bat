@echo off
REM Run ARCH Invoice application
echo Starting ARCH Invoice...
set FIREBASE_PROJECT=arch
set FLASK_DEBUG=1
cd /d "%~dp0"
python web_app/app.py
pause
