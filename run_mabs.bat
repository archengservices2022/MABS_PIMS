@echo off
REM Run MABS PIMS application
echo Starting MABS PIMS...
set FIREBASE_PROJECT=mabs
set FLASK_DEBUG=1
cd /d "%~dp0"
python web_app/app.py
pause
