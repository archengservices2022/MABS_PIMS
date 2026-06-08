import sys
import time
import shutil
import subprocess
from pathlib import Path
import ctypes
import os

# Args:
# 1 = new invoice exe (downloaded to TEMP)
# 2 = old invoice exe (current running app path)

if len(sys.argv) < 3:
    sys.exit(0)

new_exe = Path(sys.argv[1])
old_exe = Path(sys.argv[2])

time.sleep(3)  # wait for main app to fully close

old_bak = old_exe.with_suffix(".bak")

# ---- Delete existing .bak so rename never hits WinError 183 ----
if old_bak.exists():
    try:
        old_bak.unlink()
    except Exception:
        ctypes.windll.kernel32.MoveFileExW(str(old_bak), None, 4)

# ---- Rename current exe → .bak ----
try:
    os.replace(str(old_exe), str(old_bak))
except Exception:
    sys.exit(1)

# ---- Move new exe into place ----
try:
    shutil.move(str(new_exe), str(old_exe))
except Exception:
    # Restore backup so the app still works
    try:
        os.replace(str(old_bak), str(old_exe))
    except Exception:
        pass
    sys.exit(1)

# ---- Restart updated app ----
subprocess.Popen([str(old_exe)])

time.sleep(2)

# ---- Clean up .bak ----
def force_delete(path: Path):
    try:
        path.unlink()
    except Exception:
        ctypes.windll.kernel32.MoveFileExW(str(path), None, 4)  # delete on reboot

force_delete(old_bak)

# ---- Self-delete updater ----
force_delete(Path(sys.executable))

sys.exit(0)
