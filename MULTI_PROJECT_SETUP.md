# Multi-Project Setup: MABS & ARCH

This application now supports running both **MABS PIMS** and **ARCH Invoice** projects using the same codebase.

## Quick Start

### Running MABS (Default)
**Windows Batch:**
```bash
run_mabs.bat
```

**PowerShell:**
```powershell
.\run_mabs.ps1
```

**Command Line:**
```bash
set FIREBASE_PROJECT=mabs
python web_app/app.py
```

### Running ARCH
**Windows Batch:**
```bash
run_arch.bat
```

**PowerShell:**
```powershell
.\run_arch.ps1
```

**Command Line:**
```bash
set FIREBASE_PROJECT=arch
python web_app/app.py
```

## Environment Variables

### FIREBASE_PROJECT
Controls which Firebase project to connect to.
- **Value:** `mabs` (default) or `arch`
- **Example:** `set FIREBASE_PROJECT=arch`

### Other Optional Variables
- **FIREBASE_API_KEY** - Override the default API key for the selected project
- **FIREBASE_DB_URL** - Override the default database URL for the selected project
- **FLASK_DEBUG** - Enable debug mode (set to `1`)
- **FLASK_HOST** - Server host (default: `0.0.0.0`)
- **PORT** - Server port (default: `5000`)

## Project Configuration

### MABS Project
- **Firebase Project ID:** `pims-955e3`
- **API Key:** `AIzaSyBZIG4Gj_ZRRCqI1DXcf8DSXpO_9PkTgeY`
- **Database URL:** `https://pims-955e3-default-rtdb.firebaseio.com`
- **Service Key File:** `data/servicekey_mabs.json`

### ARCH Project
- **Firebase Project ID:** `invoice-7fe93`
- **API Key:** `AIzaSyD6F6T_KIZ90TkCOL03-jSXTeuPM5WVwJY`
- **Database URL:** `https://invoice-7fe93-default-rtdb.firebaseio.com`
- **Service Key File:** `data/servicekey_arch.json`

## Service Key Files

Service keys are automatically selected based on the `FIREBASE_PROJECT` setting:

- MABS: `data/servicekey_mabs.json` ✓ (included)
- ARCH: `data/servicekey_arch.json` ✓ (included)

The app looks for keys in this order:
1. `~/.mabs/servicekey_[project].json` - Home directory
2. `data/servicekey_[project].json` - Project data directory
3. `servicekey_[project].json` - Project root
4. Fallback to generic `servicekey.json` names

## Working with Both Projects

You can run both projects simultaneously on different ports:

**Terminal 1 - MABS (Port 5000):**
```powershell
$env:FIREBASE_PROJECT = "mabs"
$env:PORT = "5000"
python web_app/app.py
```

**Terminal 2 - ARCH (Port 5001):**
```powershell
$env:FIREBASE_PROJECT = "arch"
$env:PORT = "5001"
python web_app/app.py
```

Then access:
- MABS: http://localhost:5000
- ARCH: http://localhost:5001

## Verifying Project Selection

When the app starts, check the console output:
```
INFO - Firebase initialised from ... (Project: MABS)
```
or
```
INFO - Firebase initialised from ... (Project: ARCH)
```

This confirms which Firebase project is connected.

## Troubleshooting

### "Firebase disabled" Error
- Ensure the correct service key file exists in the data directory
- Check file names: `servicekey_mabs.json` or `servicekey_arch.json`
- Verify Firebase credentials are valid

### Wrong Project Connected
- Check the `FIREBASE_PROJECT` environment variable
- Make sure it's set to either `mabs` or `arch`
- Restart the application after changing the environment variable

### Port Already in Use
- Change the PORT variable: `set PORT=5001`
- Or kill existing process on that port

## Deployment

For production deployment, set the `FIREBASE_PROJECT` environment variable in your hosting platform (Heroku, Docker, etc.) and the app will automatically use the correct Firebase credentials.
