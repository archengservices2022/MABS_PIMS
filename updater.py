import sys
import time
import shutil
import subprocess
from pathlib import Path
import ctypes
import os

# Args:
# 1 = new invoice exe
# 2 = old invoice exe

if len(sys.argv) < 3:
    sys.exit(0)

new_exe = Path(sys.argv[1])
old_exe = Path(sys.argv[2])

time.sleep(3)  # ensure main app closed

temp_dir = Path(os.environ["TEMP"])

old_backup = temp_dir / "invoice.exe.bak"
updater_exe = Path(sys.executable)
updater_backup = temp_dir / "invoice_updater.exe.bak"

# ---- Backup old invoice.exe ----
try:
    if old_backup.exists():
        old_backup.unlink()
    shutil.move(str(old_exe), str(old_backup))
except:
    pass

# ---- Replace invoice.exe ----
shutil.move(str(new_exe), str(old_exe))

# ---- Restart app ----
subprocess.Popen([str(old_exe)])

time.sleep(2)

# ---- Move updater to temp ----
try:
    shutil.move(str(updater_exe), str(updater_backup))
except:
    pass

# ---- DELETE BACKUPS ----
def force_delete(file):
    try:
        file.unlink()
    except:
        ctypes.windll.kernel32.MoveFileExW(
            str(file), None, 4  # DELETE ON REBOOT
        )

force_delete(old_backup)
force_delete(updater_backup)

sys.exit(0)
