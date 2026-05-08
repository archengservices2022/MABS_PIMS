"""login_window.py - MABS Engineering PIMS Login"""
import logging
import re
import sys
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import pyqtSignal

log = logging.getLogger("pims.login")


def _firebase():
    m = sys.modules.get("main")
    if m:
        return m.FirebaseManager, m.FIREBASE_AVAILABLE
    return None, False


def _logo_pixmap(size=76):
    try:
        from main import Config
        from PIL import Image
        import io
        lp = Config.get_logo_path()
        if lp and lp.exists():
            img = Image.open(str(lp)).convert("RGBA").resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            pix = QtGui.QPixmap()
            pix.loadFromData(buf.getvalue())
            if not pix.isNull():
                return pix
    except (ImportError, FileNotFoundError, OSError, AttributeError) as e:
        log.debug(f"Could not load logo: {e}")
    except Exception as e:
        log.warning(f"Unexpected error loading logo: {e}")
    return None


class LoginWindow(QtWidgets.QWidget):
    login_successful = pyqtSignal(str, str, str)   # username, email, role

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pw_visible = False
        self.setWindowTitle("MABS Engineering - Sign In")
        
        # Dynamic sizing based on screen
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        win_w = max(900, min(1100, int(screen.width() * 0.65)))
        win_h = max(580, min(680, int(screen.height() * 0.72)))
        self.setMinimumSize(900, 560)
        self.resize(win_w, win_h)
        self._first_show = True
        self._build()

    def _build(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── LEFT dark panel ───────────────────────────────────────────────
        left = QtWidgets.QWidget()
        left.setMinimumWidth(300)
        left.setMaximumWidth(450)
        left.setStyleSheet(
            "QWidget { background: qlineargradient("
            "x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0d1b2a, stop:0.6 #1b2e3c, stop:1 #243447); }"
        )
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(44, 52, 44, 44)
        ll.setSpacing(0)

        logo_lbl = QtWidgets.QLabel()
        logo_lbl.setFixedSize(76, 76)
        logo_lbl.setAlignment(QtCore.Qt.AlignCenter)
        pix = _logo_pixmap(76)
        if pix:
            logo_lbl.setPixmap(pix)
            logo_lbl.setStyleSheet("background:transparent;border:none;")
        else:
            logo_lbl.setText("M")
            logo_lbl.setStyleSheet(
                "background:rgba(255,255,255,0.12);border-radius:16px;"
                "font-size:34px;font-weight:900;color:white;border:none;")
        ll.addWidget(logo_lbl)
        ll.addSpacing(22)

        try:
            from main import Config
            name = Config.COMPANY.get("name", "MABS Engineering LLC")
        except (ImportError, AttributeError, KeyError) as e:
            log.debug(f"Could not load company name: {e}")
            name = "MABS Engineering LLC"

        co = QtWidgets.QLabel(name)
        co.setWordWrap(True)
        co.setStyleSheet(
            "color:white;font-size:21px;font-weight:900;"
            "background:transparent;border:none;"
            "font-family:'Inter','Segoe UI',sans-serif;")
        ll.addWidget(co)
        ll.addSpacing(8)

        tag = QtWidgets.QLabel("Project & Invoice\nManagement System")
        tag.setStyleSheet(
            "color:rgba(255,255,255,0.60);font-size:14px;font-weight:500;"
            "background:transparent;border:none;"
            "font-family:'Inter','Segoe UI',sans-serif;")
        ll.addWidget(tag)
        ll.addStretch()

        for txt in [
            "Quote & Project Management",
            "Invoice Generation & Tracking",
            "Financial Overview & Reports",
        ]:
            row = QtWidgets.QLabel("  +  " + txt)
            row.setStyleSheet(
                "color:rgba(255,255,255,0.65);font-size:12px;font-weight:600;"
                "background:transparent;border:none;"
                "font-family:'Inter','Segoe UI',sans-serif;")
            ll.addWidget(row)
            ll.addSpacing(6)

        ll.addSpacing(16)
        ver = QtWidgets.QLabel("v2.1   2025 MABS Engineering LLC")
        ver.setStyleSheet(
            "color:rgba(255,255,255,0.28);font-size:10px;"
            "background:transparent;border:none;")
        ll.addWidget(ver)

        root.addWidget(left)

        # ── RIGHT form panel ──────────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background:#f0f4f8;")
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        card = QtWidgets.QFrame()
        card.setFixedWidth(380)
        card.setStyleSheet(
            "QFrame{"
            "background:white;"
            "border-radius:14px;"
            "border:1px solid #dde3ec;"
            "}")
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(36, 36, 36, 36)
        cl.setSpacing(0)

        title = QtWidgets.QLabel("Sign In")
        title.setStyleSheet(
            "font-size:24px;font-weight:900;color:#111827;"
            "background:transparent;border:none;"
            "font-family:'Inter','Segoe UI',sans-serif;")
        cl.addWidget(title)
        cl.addSpacing(4)

        sub = QtWidgets.QLabel("Enter your email and password to continue")
        sub.setStyleSheet(
            "font-size:12px;color:#6b7280;background:transparent;border:none;"
            "font-family:'Inter','Segoe UI',sans-serif;")
        cl.addWidget(sub)
        cl.addSpacing(26)

        _field = (
            "QLineEdit{"
            "background:#f9fafb;border:1.5px solid #e5e7eb;"
            "border-radius:8px;padding:10px 12px;"
            "font-size:14px;color:#111827;"
            "font-family:'Inter','Segoe UI',sans-serif;}"
            "QLineEdit:focus{border-color:#00756f;background:white;}"
        )
        _label = (
            "font-size:12px;font-weight:700;color:#374151;"
            "background:transparent;border:none;"
            "font-family:'Inter','Segoe UI',sans-serif;"
        )

        # Email field
        el = QtWidgets.QLabel("Email Address")
        el.setStyleSheet(_label)
        cl.addWidget(el)
        cl.addSpacing(5)
        self.email_edit = QtWidgets.QLineEdit()
        self.email_edit.setPlaceholderText("your@email.com")
        self.email_edit.setMinimumHeight(44)
        self.email_edit.setStyleSheet(_field)
        cl.addWidget(self.email_edit)
        cl.addSpacing(16)

        # Password field
        pl = QtWidgets.QLabel("Password")
        pl.setStyleSheet(_label)
        cl.addWidget(pl)
        cl.addSpacing(5)

        self.pw_edit = QtWidgets.QLineEdit()
        self.pw_edit.setPlaceholderText("Enter your password")
        self.pw_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pw_edit.setMinimumHeight(44)
        self.pw_edit.setStyleSheet(_field)
        cl.addWidget(self.pw_edit)
        cl.addSpacing(6)

        # Show password checkbox — clear and universally understood
        self.show_chk = QtWidgets.QCheckBox("Show password")
        self.show_chk.setStyleSheet(
            "QCheckBox{font-size:12px;color:#6b7280;background:transparent;"
            "border:none;font-family:'Inter','Segoe UI',sans-serif;spacing:6px;}"
            "QCheckBox:hover{color:#374151;}"
            "QCheckBox::indicator{width:15px;height:15px;"
            "border:1.5px solid #d1d5db;border-radius:3px;background:white;}"
            "QCheckBox::indicator:checked{background:#00756f;border-color:#00756f;}"
        )
        self.show_chk.stateChanged.connect(self._toggle_pw)
        cl.addWidget(self.show_chk)
        cl.addSpacing(4)

        # Forgot password
        fp_row = QtWidgets.QHBoxLayout()
        fp_row.addStretch()
        fp = QtWidgets.QPushButton("Forgot password?")
        fp.setFlat(True)
        fp.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        fp.setStyleSheet(
            "QPushButton{color:#00756f;font-size:12px;font-weight:700;"
            "border:none;background:transparent;}"
            "QPushButton:hover{color:#00514d;}")
        fp.clicked.connect(self._forgot_pw)
        fp_row.addWidget(fp)
        cl.addLayout(fp_row)
        cl.addSpacing(18)

        # Error label
        self.err = QtWidgets.QLabel("")
        self.err.setAlignment(QtCore.Qt.AlignCenter)
        self.err.setWordWrap(True)
        self.err.setStyleSheet(
            "QLabel{color:#b91c1c;font-size:12px;font-weight:600;"
            "background:#fef2f2;border:1px solid #fecaca;"
            "border-radius:7px;padding:8px;}")
        self.err.setVisible(False)
        cl.addWidget(self.err)
        cl.addSpacing(4)

        # Sign In button
        self.btn = QtWidgets.QPushButton("Sign In")
        self.btn.setMinimumHeight(48)
        self.btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn.setStyleSheet(
            "QPushButton{background:#00756f;color:white;border:none;"
            "border-radius:10px;font-size:15px;font-weight:900;"
            "font-family:'Inter','Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#00645f;}"
            "QPushButton:disabled{background:#cbd5e1;color:#94a3b8;}"
        )
        self.btn.clicked.connect(self._login)
        cl.addWidget(self.btn)

        cl.addSpacing(16)
        note = QtWidgets.QLabel("Secured connection  |  Firebase sync enabled")
        note.setAlignment(QtCore.Qt.AlignCenter)
        note.setStyleSheet(
            "color:#9ca3af;font-size:11px;background:transparent;border:none;")
        cl.addWidget(note)

        # Create a container widget for the card with overlay
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(card)

        # Loading overlay (hidden by default, positioned over the card)
        self._loading = QtWidgets.QWidget(container)
        self._loading.setGeometry(card.geometry())
        self._loading.setStyleSheet("background:#f0f4f8;")
        self._loading.setVisible(False)
        
        lo = QtWidgets.QVBoxLayout(self._loading)
        lo.setAlignment(QtCore.Qt.AlignCenter)

        spin_lbl = QtWidgets.QLabel()
        spin_lbl.setAlignment(QtCore.Qt.AlignCenter)
        spin_lbl.setFixedSize(60, 60)
        spin_lbl.setStyleSheet(
            "border:5px solid #e2e8f0;border-top:5px solid #00756f;"
            "border-radius:30px;background:transparent;")
        self._spin_lbl = spin_lbl

        self._spin_timer = QtCore.QTimer(self)
        self._spin_angle = 0
        self._spin_timer.timeout.connect(self._spin_tick)

        lo.addStretch()
        lo.addWidget(spin_lbl, 0, QtCore.Qt.AlignCenter)
        lo.addSpacing(18)

        load_txt = QtWidgets.QLabel("Loading workspace...")
        load_txt.setAlignment(QtCore.Qt.AlignCenter)
        load_txt.setStyleSheet(
            "font-size:16px;font-weight:700;color:#374151;"
            "background:transparent;border:none;"
            "font-family:'Inter','Segoe UI',sans-serif;")
        lo.addWidget(load_txt)

        sub_txt = QtWidgets.QLabel("Connecting to Firebase and loading your data")
        sub_txt.setAlignment(QtCore.Qt.AlignCenter)
        sub_txt.setStyleSheet(
            "font-size:12px;color:#9ca3af;background:transparent;border:none;")
        lo.addWidget(sub_txt)
        lo.addStretch()

        rl.addStretch(1)
        rl.addWidget(container, 0, QtCore.Qt.AlignHCenter)
        rl.addStretch(1)

        self._right = right
        self._card = card
        root.addWidget(right, 1)

        self.email_edit.returnPressed.connect(lambda: self.pw_edit.setFocus())
        self.pw_edit.returnPressed.connect(self._login)

    # ── actions ────────────────────────────────────────────────────────────
    def show_loading(self):
        """Switch the right panel to a loading spinner — window stays fully visible."""
        if self._loading:
            self._loading.raise_()
            self._loading.resize(self._loading.parent().size())
            self._loading.setVisible(True)
        self._spin_timer.start(16)   # ~60fps rotation

    def hide_loading(self):
        """Return to the login form if workspace loading fails."""
        self._spin_timer.stop()
        if self._loading:
            self._loading.setVisible(False)

    def _spin_tick(self):
        self._spin_angle = (self._spin_angle + 6) % 360
        self._spin_lbl.setStyleSheet(
            f"border:5px solid #e2e8f0;"
            f"border-top:5px solid #00756f;"
            f"border-radius:30px;background:transparent;"
            # Qt CSS doesn't support rotation, so we fake it with border colours
        )
        # Rotate border highlight by cycling which border is coloured
        angle = self._spin_angle % 360
        borders = {
            0:   "border-top:5px solid #00756f;border-right:5px solid #e2e8f0;border-bottom:5px solid #e2e8f0;border-left:5px solid #e2e8f0;",
            90:  "border-top:5px solid #e2e8f0;border-right:5px solid #00756f;border-bottom:5px solid #e2e8f0;border-left:5px solid #e2e8f0;",
            180: "border-top:5px solid #e2e8f0;border-right:5px solid #e2e8f0;border-bottom:5px solid #00756f;border-left:5px solid #e2e8f0;",
            270: "border-top:5px solid #e2e8f0;border-right:5px solid #e2e8f0;border-bottom:5px solid #e2e8f0;border-left:5px solid #00756f;",
        }
        seg = (angle // 90) * 90
        self._spin_lbl.setStyleSheet(
            f"border-radius:30px;background:transparent;{borders[seg]}")

    def _toggle_pw(self, state=None):
        show = self.show_chk.isChecked()
        self.pw_edit.setEchoMode(
            QtWidgets.QLineEdit.Normal if show else QtWidgets.QLineEdit.Password)

    def _show_error(self, msg):
        self.err.setText(msg)
        self.err.setVisible(True)
        QtCore.QTimer.singleShot(4000, lambda: self.err.setVisible(False))

    def _login(self):
        email = self.email_edit.text().strip().lower()
        pw = self.pw_edit.text()

        if not email:
            self._show_error("Please enter your email address.")
            self.email_edit.setFocus()
            return
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            self._show_error("Please enter a valid email address.")
            self.email_edit.setFocus()
            return
        if not pw:
            self._show_error("Please enter your password.")
            self.pw_edit.setFocus()
            return

        self.btn.setEnabled(False)
        self.btn.setText("Verifying...")
        QtWidgets.QApplication.processEvents()

        try:
            FM, _ = _firebase()
            if not FM:
                self._show_error("Authentication service is unavailable. Please restart the app.")
            else:
                ok, username, user_email, role = FM.validate_user_email(email, pw)
                if ok and username:
                    self.show_loading()
                    QtWidgets.QApplication.processEvents()
                    self.login_successful.emit(username, user_email, role)
                    return

                message = getattr(FM, "last_auth_message", "") or "Invalid email or password. Please try again."
                self._show_error(message)
        except Exception as exc:
            log.exception("Unexpected login error")
            self._show_error("Unexpected login error. Please restart the app or contact an administrator.")

        # Reset loading state if authentication failed
        self.hide_loading()
        self.btn.setText("Sign In")
        self.btn.setEnabled(True)
        self.pw_edit.clear()
        self.pw_edit.setFocus()

    def _forgot_pw(self):
        email = self.email_edit.text().strip()
        if not email:
            email, ok = QtWidgets.QInputDialog.getText(
                self, "Reset Password", "Enter your email address:")
            if not ok or not email:
                return
        FM, _ = _firebase()
        if not FM:
            QtWidgets.QMessageBox.warning(self, "Error", "Firebase not available.")
            return
        if FM.send_password_reset_email(email):
            QtWidgets.QMessageBox.information(
                self, "Email Sent",
                f"Reset link sent to {email}.\nCheck your inbox or spam folder.")
        else:
            QtWidgets.QMessageBox.warning(
                self, "Failed", "Could not send reset email. Check the address.")

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - self.width()) // 2
            y = screen.y() + (screen.height() - self.height()) // 2
            self.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def closeEvent(self, event):
        event.accept()
