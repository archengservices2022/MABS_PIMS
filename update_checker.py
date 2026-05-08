import sys
import os
import json
import time
import shutil
import subprocess
import ctypes
import hashlib
import requests
from pathlib import Path
from packaging import version
from PyQt5 import QtWidgets, QtCore
from datetime import datetime

# =====================================================
# CONFIG — loaded from data/settings.json if present
# =====================================================
def _load_update_config():
    settings_path = Path(__file__).resolve().parent / "data" / "settings.json"
    try:
        if settings_path.exists():
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            gh = data.get("github", {})
            return gh.get("repo", "Ashajyothi12/invoice"), gh.get("current_version", "1.2")
    except Exception:
        pass
    return "Ashajyothi12/invoice", "1.2"

GITHUB_REPO, CURRENT_VERSION = _load_update_config()
UPDATE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def cleanup_old_backup():
    exe = Path(sys.executable)
    bak = exe.with_suffix(".bak")
    if bak.exists():
        try:
            bak.unlink()
        except:
            pass

# =====================================================
# UPDATE MODE (REPLACES OLD EXE)
# =====================================================

# =====================================================
# UPDATE CHECKER (NORMAL MODE)
# =====================================================
class UpdateChecker:

    def __init__(self, parent=None):
        self.parent = parent
        self.release_info = None
        self.latest_version = None

    # -------------------------------------------------
    def check_for_updates(self, silent=False):
        try:
            response = requests.get(UPDATE_API_URL, timeout=10)
            response.raise_for_status()

            self.release_info = response.json()
            tag = self.release_info.get("tag_name", "").lstrip("v")

            if not tag:
                return False

            self.latest_version = tag

            if version.parse(tag) > version.parse(CURRENT_VERSION):
                if not silent:
                    self._show_update_dialog()
                return True

            if not silent:
                QtWidgets.QMessageBox.information(
                    self.parent,
                    "Up to Date",
                    f"You are using the latest version (v{CURRENT_VERSION})."
                )
            return False

        except Exception as e:
            if not silent:
                QtWidgets.QMessageBox.warning(
                    self.parent,
                    "Update Error",
                    str(e)
                )
            return False

    def show_update_available_dialog(self):
        """Public wrapper used by UpdateIndicator"""
        self._show_update_dialog()

    # -------------------------------------------------
    def _show_update_dialog(self):
        dialog = QtWidgets.QDialog(self.parent)
        dialog.setWindowTitle("Update Available")
        dialog.setFixedWidth(420)

        layout = QtWidgets.QVBoxLayout(dialog)

        # ---- Title ----
        title = QtWidgets.QLabel("🚀 New Version Available")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        title.setAlignment(QtCore.Qt.AlignCenter)

        # ---- Version Info (ABOVE notes) ----
        info = QtWidgets.QLabel(
            f"Current Version: v{CURRENT_VERSION}\n"
            f"Latest Version: v{self.latest_version}"
        )
        info.setAlignment(QtCore.Qt.AlignCenter)
        info.setStyleSheet("margin-bottom: 8px;")

        layout.addWidget(title)
        layout.addWidget(info)

        # ---- FILTERED GITHUB RELEASE NOTES ----
        raw_notes = (self.release_info.get("body") or "").strip()

        clean_lines = []
        for line in raw_notes.splitlines():
            if "full changelog" in line.lower():
                continue
            clean_lines.append(line)

        release_notes = "\n".join(clean_lines).strip()

        if release_notes:
            whats_new = QtWidgets.QLabel("What’s New")
            whats_new.setStyleSheet("""
                QLabel {
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 4px;
                }
            """)

            notes = QtWidgets.QTextEdit()
            notes.setReadOnly(True)
            notes.setMaximumHeight(120)
            notes.setText(release_notes)

            layout.addWidget(whats_new)
            layout.addWidget(notes)

        # ---- Buttons ----
        btns = QtWidgets.QHBoxLayout()

        later = QtWidgets.QPushButton("Remind Me Later")
        update = QtWidgets.QPushButton("Install Now")
        update.setStyleSheet("font-weight:bold;")

        later.clicked.connect(dialog.reject)
        update.clicked.connect(lambda: self._install_update(dialog))

        btns.addWidget(later)
        btns.addWidget(update)

        # ---- Footer ----
        footer = QtWidgets.QLabel(
            f"Checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        footer.setStyleSheet("font-size:10px;color:gray;")
        footer.setAlignment(QtCore.Qt.AlignCenter)

        layout.addLayout(btns)
        layout.addWidget(footer)

        dialog.exec_()


    # -------------------------------------------------
    def _install_update(self, dialog):
        try:
            assets = self.release_info.get("assets", [])

            invoice_asset = None
            updater_asset = None
            invoice_checksum_asset = None
            updater_checksum_asset = None

            for asset in assets:
                name = asset["name"].lower()
                if name == "invoice.exe":
                    invoice_asset = asset
                elif name == "invoice_updater.exe":
                    updater_asset = asset
                elif name == "invoice.exe.sha256":
                    invoice_checksum_asset = asset
                elif name == "invoice_updater.exe.sha256":
                    updater_checksum_asset = asset

            if not invoice_asset or not updater_asset or not invoice_checksum_asset or not updater_checksum_asset:
                raise Exception("Release must contain invoice.exe, invoice_updater.exe, and matching .sha256 files")

            temp_dir = Path(os.environ["TEMP"])
            invoice_new = temp_dir / "invoice_new.exe"
            updater_new = temp_dir / "invoice_updater.exe"

            # ---- Progress Dialog ----
            progress = QtWidgets.QProgressDialog(
                "Downloading update...", "Cancel", 0, 100, self.parent
            )
            progress.setWindowTitle("Updating")
            progress.setWindowModality(QtCore.Qt.ApplicationModal)
            progress.show()

            def download(asset, target, base_progress):
                r = requests.get(asset["browser_download_url"], stream=True, timeout=30)
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0

                with open(target, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if progress.wasCanceled():
                            raise Exception("Update cancelled")
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            percent = int((downloaded / total) * 50)
                            progress.setValue(base_progress + percent)

            download(invoice_asset, invoice_new, 0)
            download(updater_asset, updater_new, 50)
            self._verify_download(invoice_new, invoice_checksum_asset)
            self._verify_download(updater_new, updater_checksum_asset)

            progress.setValue(100)

            # ---- Launch updater ----
            current_exe = Path(sys.executable)

            subprocess.Popen(
                [
                    str(updater_new),
                    str(invoice_new),
                    str(current_exe)
                ],
                creationflags=subprocess.DETACHED_PROCESS,
                close_fds=True
            )

            dialog.accept()
            QtWidgets.QApplication.quit()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self.parent, "Update Failed", str(e))

    def _verify_download(self, file_path: Path, checksum_asset: dict) -> None:
        expected = requests.get(checksum_asset["browser_download_url"], timeout=15).text.strip().split()[0].lower()
        actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual != expected:
            try:
                file_path.unlink()
            except Exception:
                pass
            raise Exception(f"Checksum verification failed for {file_path.name}")


    
    # -------------------------------------------------
    def check_on_startup(self):
        QtCore.QTimer.singleShot(
            3000, lambda: self.check_for_updates(silent=True)
        )
