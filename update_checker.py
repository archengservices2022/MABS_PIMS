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
from PyQt5 import QtWidgets, QtCore, QtGui

# =====================================================
# CONFIG
# =====================================================

# *** CHANGE THIS when building a new release ***
APP_VERSION = "1.2"

def _load_update_config():
    """Read GitHub repo from settings.json and sync current_version to APP_VERSION.
    Version is always the hardcoded APP_VERSION — settings.json is updated to match
    automatically so every other part of the app sees the correct version."""
    settings_path = Path(__file__).resolve().parent / "data" / "settings.json"
    try:
        if settings_path.exists():
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            gh = data.setdefault("github", {})
            repo = gh.get("repo", "archengservices2022/MABS_PIMS")
            # Keep settings.json in sync — no manual edit needed on release
            if gh.get("current_version") != APP_VERSION:
                gh["current_version"] = APP_VERSION
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            return repo
    except Exception:
        pass
    return "archengservices2022/MABS_PIMS"

GITHUB_REPO = _load_update_config()
CURRENT_VERSION = APP_VERSION
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
class _UpdateWorker(QtCore.QThread):
    """Fetches the latest release info from GitHub on a background thread."""
    update_available = QtCore.pyqtSignal(str, dict)   # tag, release_info
    up_to_date       = QtCore.pyqtSignal()
    error            = QtCore.pyqtSignal(str)

    def __init__(self, api_url, current_version, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self.current_version = current_version

    def run(self):
        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            info = response.json()
            tag = (UpdateChecker._extract_version(info.get("name", ""))
                   or UpdateChecker._extract_version(info.get("tag_name", "")))
            if not tag:
                self.up_to_date.emit()
                return
            if version.parse(tag) > version.parse(self.current_version):
                self.update_available.emit(tag, info)
            else:
                self.up_to_date.emit()
        except Exception as e:
            self.error.emit(str(e))


class UpdateChecker:

    def __init__(self, parent=None):
        self.parent = parent
        self.release_info = None
        self.latest_version = None
        self._worker = None  # keep reference so it isn't GC'd while running

    # -------------------------------------------------
    @staticmethod
    def _extract_version(s: str) -> str:
        """Return a clean dotted version from strings like 'V1.2', 'v1.2.3', or 'PIMS - v1.2'."""
        import re
        s = (s or "").strip()
        # Strict: entire string is a version label (e.g. "V1.2", "v1.2.3", "1.2")
        m = re.match(r'^[vV]?(\d+(?:\.\d+)+)$', s)
        if m:
            return m.group(1)
        # Loose: version embedded in a longer name (e.g. "PIMS - v1.2")
        m = re.search(r'[vV](\d+(?:\.\d+)+)\b', s)
        return m.group(1) if m else ""

    def check_for_updates(self, silent=False):
        """Start a background check. Never blocks the main thread."""
        # Avoid duplicate background checks
        if self._worker and self._worker.isRunning():
            return

        self._worker = _UpdateWorker(UPDATE_API_URL, CURRENT_VERSION, self.parent)

        if silent:
            self._worker.update_available.connect(self._on_update_found_silent)
            # silent errors are intentionally ignored
        else:
            self._worker.update_available.connect(self._on_update_found_explicit)
            self._worker.up_to_date.connect(
                lambda: QtWidgets.QMessageBox.information(
                    self.parent, "Up to Date",
                    f"You are using the latest version (v{CURRENT_VERSION})."
                )
            )
            self._worker.error.connect(
                lambda msg: QtWidgets.QMessageBox.warning(
                    self.parent, "Update Error", msg
                )
            )

        self._worker.start()

    def _on_update_found_silent(self, tag: str, info: dict):
        """Called on the main thread when background check finds a newer release."""
        self.latest_version = tag
        self.release_info = info
        if self._get_dismissed_version() != tag:
            self._show_update_dialog(startup=True)

    def _on_update_found_explicit(self, tag: str, info: dict):
        """Called on the main thread for a manual (non-silent) check."""
        self.latest_version = tag
        self.release_info = info
        self._show_update_dialog(startup=False)

    def show_update_available_dialog(self):
        """Public wrapper used by UpdateIndicator"""
        self._show_update_dialog(startup=False)

    # -------------------------------------------------
    def _get_dismissed_version(self) -> str:
        settings_path = Path(__file__).resolve().parent / "data" / "settings.json"
        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("github", {}).get("dismissed_version", "")
        except Exception:
            return ""

    def _save_dismissed_version(self, tag: str) -> None:
        settings_path = Path(__file__).resolve().parent / "data" / "settings.json"
        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("github", {})["dismissed_version"] = tag
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # -------------------------------------------------
    def _show_update_dialog(self, startup: bool = False):
        from datetime import datetime as _dt
        dialog = QtWidgets.QDialog(self.parent)
        dialog.setWindowTitle("Update Available")
        dialog.setFixedWidth(440)
        dialog.setWindowFlags(
            dialog.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        dialog.setStyleSheet("QDialog { background: #ffffff; }")

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(28, 28, 28, 20)
        layout.setSpacing(10)

        # ── Title ──────────────────────────────────────────────────────────
        title = QtWidgets.QLabel("🚀  New Version Available")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: 800; color: #0d1b2a;"
            " font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(title)

        # ── Version info (two lines, centered) ────────────────────────────
        info = QtWidgets.QLabel(
            f"Current Version: v{CURRENT_VERSION}\n"
            f"Latest Version: v{self.latest_version}")
        info.setAlignment(QtCore.Qt.AlignCenter)
        info.setStyleSheet(
            "font-size: 13px; color: #64748b; line-height: 1.6;"
            " font-family: 'Segoe UI', sans-serif; margin-bottom: 4px;")
        layout.addWidget(info)

        # ── Separator ──────────────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color: #e2e8f0; background: #e2e8f0; max-height: 1px;")
        layout.addWidget(sep)

        # ── Release notes ──────────────────────────────────────────────────
        raw_notes = (self.release_info.get("body") or "").strip()
        clean = "\n".join(
            ln for ln in raw_notes.splitlines()
            if "full changelog" not in ln.lower()
        ).strip()

        if clean:
            whats_new_lbl = QtWidgets.QLabel("What's New")
            whats_new_lbl.setStyleSheet(
                "font-size: 13px; font-weight: 700; color: #374151;"
                " font-family: 'Segoe UI', sans-serif; margin-top: 4px;")
            layout.addWidget(whats_new_lbl)

            notes_box = QtWidgets.QTextEdit()
            notes_box.setReadOnly(True)
            notes_box.setFixedHeight(120)
            notes_box.setPlainText(clean)
            notes_box.setStyleSheet("""
                QTextEdit {
                    background: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    padding: 10px 12px;
                    font-size: 12px;
                    font-family: 'Segoe UI', sans-serif;
                    color: #475569;
                }
            """)
            layout.addWidget(notes_box)

        layout.addSpacing(4)

        # ── Buttons — equal width, same blue style (matches reference image) ─
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)

        _blue_btn = """
            QPushButton {
                background: #2196f3;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover   { background: #1976d2; }
            QPushButton:pressed { background: #1565c0; }
        """

        later_btn = QtWidgets.QPushButton("Remind Me Later")
        later_btn.setFixedHeight(38)
        later_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        later_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        later_btn.setStyleSheet(_blue_btn)

        install_btn = QtWidgets.QPushButton("Install Now")
        install_btn.setFixedHeight(38)
        install_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        install_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        install_btn.setStyleSheet(_blue_btn)

        def _on_later():
            if startup:
                self._save_dismissed_version(self.latest_version)
            dialog.reject()

        later_btn.clicked.connect(_on_later)
        install_btn.clicked.connect(lambda: self._install_update(dialog))

        btn_row.addWidget(later_btn)
        btn_row.addWidget(install_btn)
        layout.addLayout(btn_row)

        # ── Footer timestamp ────────────────────────────────────────────────
        footer_lbl = QtWidgets.QLabel(
            f"Checked:  {_dt.now().strftime('%Y-%m-%d  %H:%M:%S')}")
        footer_lbl.setAlignment(QtCore.Qt.AlignCenter)
        footer_lbl.setStyleSheet(
            "font-size: 10px; color: #94a3b8;"
            " font-family: 'Segoe UI', sans-serif; margin-top: 2px;")
        layout.addWidget(footer_lbl)

        # Center over parent window
        if self.parent and self.parent.isVisible():
            pg = self.parent.frameGeometry()
            dialog.adjustSize()
            dialog.move(
                pg.x() + (pg.width()  - dialog.width())  // 2,
                pg.y() + (pg.height() - dialog.height()) // 2,
            )

        dialog.exec_()

    # -------------------------------------------------
    def _show_up_to_date_dialog(self):
        from datetime import datetime as _dt
        dialog = QtWidgets.QDialog(self.parent)
        dialog.setWindowTitle("Software Update")
        dialog.setFixedWidth(380)
        dialog.setWindowFlags(
            dialog.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        dialog.setStyleSheet("QDialog { background: #ffffff; }")

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(28, 28, 28, 20)
        layout.setSpacing(12)

        # Checkmark icon
        icon_lbl = QtWidgets.QLabel("✔")
        icon_lbl.setAlignment(QtCore.Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            "font-size: 36px; color: #16a34a; font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(icon_lbl)

        # Title
        title = QtWidgets.QLabel("You're Up to Date!")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 18px; font-weight: 800; color: #0d1b2a;"
            " font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(title)

        # Version info
        ver_lbl = QtWidgets.QLabel(
            f"You are running the latest version  (v{CURRENT_VERSION}).")
        ver_lbl.setAlignment(QtCore.Qt.AlignCenter)
        ver_lbl.setWordWrap(True)
        ver_lbl.setStyleSheet(
            "font-size: 12px; color: #64748b; font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(ver_lbl)

        layout.addSpacing(6)

        # OK button
        ok_btn = QtWidgets.QPushButton("OK")
        ok_btn.setFixedHeight(38)
        ok_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #1d4ed8;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover   { background: #2563eb; }
            QPushButton:pressed { background: #1e40af; }
        """)
        ok_btn.clicked.connect(dialog.accept)
        layout.addWidget(ok_btn)

        # Footer timestamp
        footer_lbl = QtWidgets.QLabel(
            f"Checked:  {_dt.now().strftime('%Y-%m-%d  %H:%M:%S')}")
        footer_lbl.setAlignment(QtCore.Qt.AlignCenter)
        footer_lbl.setStyleSheet(
            "font-size: 10px; color: #94a3b8; font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(footer_lbl)

        if self.parent and self.parent.isVisible():
            pg = self.parent.frameGeometry()
            dialog.adjustSize()
            dialog.move(
                pg.x() + (pg.width()  - dialog.width())  // 2,
                pg.y() + (pg.height() - dialog.height()) // 2,
            )

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

            if not invoice_asset or not updater_asset:
                raise Exception("Release must contain invoice.exe and invoice_updater.exe")

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

            # Verify checksums only if .sha256 files are present in the release
            if invoice_checksum_asset:
                self._verify_download(invoice_new, invoice_checksum_asset)
            if updater_checksum_asset:
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
        # 5 s delay so the main window is fully loaded before the popup appears
        QtCore.QTimer.singleShot(
            5000, lambda: self.check_for_updates(silent=True)
        )
