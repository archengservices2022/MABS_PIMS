"""Settings dialog — Company Info · Security · Preferences"""
import json
from pathlib import Path
import re
from datetime import datetime
from PyQt5 import QtWidgets, QtCore, QtGui

# ── colour palette shared across all tabs ──────────────────────────────────
_BLUE   = "#0969da"
_GREEN  = "#1a7f37"
_RED    = "#cf222e"
_BG     = "#f6f8fa"
_BORDER = "#d0d7de"
_TEXT   = "#24292f"
_MUTED  = "#57606a"

SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "settings.json"


def _load_settings() -> dict:
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_settings(data: dict) -> bool:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# ── shared widget helpers ───────────────────────────────────────────────────
def _field(placeholder="", echo=QtWidgets.QLineEdit.Normal) -> QtWidgets.QLineEdit:
    w = QtWidgets.QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setEchoMode(echo)
    w.setStyleSheet(f"""
        QLineEdit {{
            padding: 8px 12px;
            border: 1px solid {_BORDER};
            border-radius: 6px;
            font-size: 13px;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            color: {_TEXT};
            background: white;
        }}
        QLineEdit:focus {{
            border-color: {_BLUE};
            outline: none;
        }}
    """)
    return w


def _label(text, bold=False, muted=False) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    color = _MUTED if muted else _TEXT
    weight = "600" if bold else "400"
    lbl.setStyleSheet(
        f"font-size: 13px; font-weight: {weight}; color: {color};"
        " font-family: 'Inter', 'Segoe UI', sans-serif;"
    )
    return lbl


def _section_title(text) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setStyleSheet(f"""
        font-size: 11px;
        font-weight: 700;
        color: {_MUTED};
        text-transform: uppercase;
        letter-spacing: 0.8px;
        font-family: 'Inter', 'Segoe UI', sans-serif;
        padding-bottom: 4px;
        border-bottom: 1px solid {_BORDER};
    """)
    return lbl


def _divider() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setFrameShape(QtWidgets.QFrame.HLine)
    f.setStyleSheet(f"color: {_BORDER}; margin: 4px 0;")
    return f


def _btn(text, color=_BLUE, text_color="white", width=None) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    if width:
        b.setFixedWidth(width)
    b.setFixedHeight(36)
    b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
    b.setStyleSheet(f"""
        QPushButton {{
            background-color: {color};
            color: {text_color};
            border: 1px solid {_BORDER if color == _BG else "transparent"};
            border-radius: 7px;
            font-size: 13px;
            font-weight: 600;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            padding: 0 18px;
        }}
        QPushButton:hover   {{ filter: brightness(0.92); }}
        QPushButton:pressed {{ filter: brightness(0.85); }}
    """)
    return b


# ══════════════════════════════════════════════════════════════════════════════
#  Company Info tab
# ══════════════════════════════════════════════════════════════════════════════
class _CompanyTab(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()

    def __init__(self, settings: dict):
        super().__init__()
        self._settings = settings
        co = settings.get("company", {})

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        layout.addWidget(_section_title("Company Details"))

        form = QtWidgets.QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self.name_e    = _field("e.g. MABS Engineering LLC")
        self.phone_e   = _field("e.g. 314-303-0004")
        self.email_e   = _field("e.g. admin@company.com")
        self.website_e = _field("e.g. www.company.com")

        self.name_e.setText(co.get("name", ""))
        self.phone_e.setText(co.get("phone", ""))
        self.email_e.setText(co.get("email", ""))
        self.website_e.setText(co.get("website", ""))

        form.addRow(_label("Company Name", bold=True), self.name_e)
        form.addRow(_label("Phone", bold=True),        self.phone_e)
        form.addRow(_label("Email", bold=True),        self.email_e)
        form.addRow(_label("Website", bold=True),      self.website_e)
        layout.addLayout(form)

        # Address (multi-line)
        layout.addWidget(_label("Address", bold=True))
        self.addr_e = QtWidgets.QPlainTextEdit()
        self.addr_e.setPlainText(co.get("address", ""))
        self.addr_e.setFixedHeight(72)
        self.addr_e.setStyleSheet(f"""
            QPlainTextEdit {{
                padding: 8px 12px;
                border: 1px solid {_BORDER};
                border-radius: 6px;
                font-size: 13px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                color: {_TEXT};
            }}
            QPlainTextEdit:focus {{ border-color: {_BLUE}; }}
        """)
        layout.addWidget(self.addr_e)

        layout.addSpacing(10)
        layout.addWidget(_section_title("Company Logo"))

        logo_row = QtWidgets.QHBoxLayout()
        self.logo_preview = QtWidgets.QLabel()
        self.logo_preview.setFixedSize(80, 80)
        self.logo_preview.setStyleSheet(f"""
            border: 2px dashed {_BORDER};
            border-radius: 8px;
            background: white;
        """)
        self.logo_preview.setAlignment(QtCore.Qt.AlignCenter)
        self._refresh_logo_preview(settings.get("company", {}).get("logo_path", ""))

        logo_col = QtWidgets.QVBoxLayout()
        self.logo_path_lbl = _label(
            settings.get("company", {}).get("logo_path", "No logo selected"), muted=True)
        self.logo_path_lbl.setWordWrap(True)

        pick_btn = _btn("Choose Logo…", color=_BG, text_color=_TEXT, width=140)
        pick_btn.clicked.connect(self._pick_logo)
        logo_col.addWidget(self.logo_path_lbl)
        logo_col.addWidget(pick_btn)
        logo_col.addStretch()

        logo_row.addWidget(self.logo_preview)
        logo_row.addSpacing(12)
        logo_row.addLayout(logo_col)
        logo_row.addStretch()
        layout.addLayout(logo_row)
        layout.addStretch()

    def _pick_logo(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Logo", "", "Images (*.png *.jpg *.jpeg *.bmp *.svg)"
        )
        if path:
            self._settings.setdefault("company", {})["logo_path"] = path
            self.logo_path_lbl.setText(path)
            self._refresh_logo_preview(path)
            self.changed.emit()

    def _refresh_logo_preview(self, path: str):
        if path and Path(path).exists():
            pix = QtGui.QPixmap(path).scaled(
                76, 76, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.logo_preview.setPixmap(pix)
        else:
            self.logo_preview.setText("No logo")
            self.logo_preview.setStyleSheet(
                f"border: 2px dashed {_BORDER}; border-radius:8px;"
                f" background:white; color:{_MUTED}; font-size:11px;")

    def collect(self) -> dict:
        co = self._settings.get("company", {})
        co.update({
            "name":    self.name_e.text().strip(),
            "phone":   self.phone_e.text().strip(),
            "email":   self.email_e.text().strip(),
            "website": self.website_e.text().strip(),
            "address": self.addr_e.toPlainText().strip(),
        })
        return co


# ══════════════════════════════════════════════════════════════════════════════
#  Security tab - Complete User Management
# ══════════════════════════════════════════════════════════════════════════════
# In settings_dialog.py, update the _SecurityTab class:

class _SecurityTab(QtWidgets.QWidget):
    def __init__(self, settings: dict):
        super().__init__()
        self._settings = settings
        self._init_ui()
        self._load_users()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        layout.addWidget(_section_title("User Management (Firebase)"))
        layout.addWidget(_label(
            "Add, edit, or remove user credentials. All users are stored securely in Firebase.\n"
            "Admin users have full access; Sales users only see Quote Forms tab.",
            muted=True))
        layout.addSpacing(8)

        # Add User button
        add_row = QtWidgets.QHBoxLayout()
        add_row.addStretch()
        self.add_user_btn = _btn("+ Add New User", color=_GREEN, width=160)
        self.add_user_btn.clicked.connect(self._open_add_user_dialog)
        add_row.addWidget(self.add_user_btn)
        layout.addLayout(add_row)

        layout.addSpacing(8)

        # Users Table
        self.users_table = QtWidgets.QTableWidget()
        self.users_table.setColumnCount(6)
        self.users_table.setHorizontalHeaderLabels([
            "Username", "Email", "Role", "Created", "Last Modified", "Actions"
        ])
        
        self.users_table.setStyleSheet(f"""
            QTableWidget {{
                background: white;
                border: 1px solid {_BORDER};
                border-radius: 8px;
                gridline-color: {_BORDER};
                font-size: 12px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }}
            QTableWidget::item {{
                padding: 8px 12px;
            }}
            QTableWidget::item:selected {{
                background: #e8f0fe;
                color: {_TEXT};
            }}
            QHeaderView::section {{
                background: {_BG};
                color: {_TEXT};
                font-weight: 600;
                padding: 8px 12px;
                border: none;
                border-bottom: 1px solid {_BORDER};
                font-size: 12px;
            }}
        """)
        
        header = self.users_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)

        self.users_table.setColumnWidth(2, 110)
        self.users_table.setColumnWidth(3, 130)
        self.users_table.setColumnWidth(4, 140)
        self.users_table.setColumnWidth(5, 180)
        self.users_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        
        self.users_table.verticalHeader().setVisible(False)
        self.users_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.users_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.users_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.users_table, 1)

    def _load_users(self):
        """Load users from Firebase and populate the table"""
        self.users_table.setRowCount(0)
        
        from main import FirebaseManager, FIREBASE_AVAILABLE
        
        if not FIREBASE_AVAILABLE:
            QtWidgets.QMessageBox.warning(
                self, "Firebase Error",
                "Firebase is not available. Cannot load users."
            )
            return
        
        users = FirebaseManager.get_all_users()
        
        for user in users:
            row = self.users_table.rowCount()
            self.users_table.insertRow(row)
            
            # Username
            username_item = QtWidgets.QTableWidgetItem(user.get('username', ''))
            username_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self.users_table.setItem(row, 0, username_item)
            
            # Email
            email_item = QtWidgets.QTableWidgetItem(user.get('email', ''))
            email_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self.users_table.setItem(row, 1, email_item)
            
            # Role
            role = user.get('role', 'sales')
            role_item = QtWidgets.QTableWidgetItem(role.capitalize())
            role_item.setTextAlignment(QtCore.Qt.AlignCenter)
            if role == "admin":
                role_item.setForeground(QtGui.QColor(_GREEN))
            else:
                role_item.setForeground(QtGui.QColor(_BLUE))
            self.users_table.setItem(row, 2, role_item)
            
            # Created date
            created = user.get('created_at', 'N/A')
            if created != "N/A" and "T" in created:
                created = created.split("T")[0]
            created_item = QtWidgets.QTableWidgetItem(created)
            created_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.users_table.setItem(row, 3, created_item)
            
            # Last Modified
            updated = user.get('updated_at', 'N/A')
            if updated != "N/A" and "T" in updated:
                updated = updated.split("T")[0]
            updated_item = QtWidgets.QTableWidgetItem(updated)
            updated_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.users_table.setItem(row, 4, updated_item)
            
            # Actions widget
            actions_widget = QtWidgets.QWidget()
            actions_layout = QtWidgets.QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(4, 4, 4, 4)
            actions_layout.setSpacing(8)
            actions_layout.setAlignment(QtCore.Qt.AlignCenter)
            
            _cell_btn_ss = (
                "QPushButton {"
                "  border-radius: 6px; font-size: 12px; font-weight: 600;"
                "  font-family: 'Inter','Segoe UI',sans-serif;"
                "  padding: 0 8px; height: 28px;"
                "}"
                "QPushButton:hover { filter: brightness(0.92); }"
                "QPushButton:pressed { filter: brightness(0.85); }"
            )
            edit_btn = QtWidgets.QPushButton("Edit")
            edit_btn.setFixedSize(72, 28)
            edit_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            edit_btn.setStyleSheet(_cell_btn_ss + f"QPushButton {{ background:{_BLUE}; color:white; border:none; }}")
            edit_btn.clicked.connect(lambda checked, u=user.get('username'): self._open_edit_user_dialog(u))

            delete_btn = QtWidgets.QPushButton("Delete")
            delete_btn.setFixedSize(72, 28)
            delete_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            delete_btn.setStyleSheet(_cell_btn_ss + f"QPushButton {{ background:{_RED}; color:white; border:none; }}")
            if user.get('username') == "admin":
                delete_btn.setEnabled(False)
                delete_btn.setToolTip("Default admin account cannot be deleted")
            else:
                delete_btn.clicked.connect(lambda checked, u=user.get('username'): self._delete_user(u))
            
            actions_layout.addWidget(edit_btn)
            actions_layout.addWidget(delete_btn)
            
            self.users_table.setCellWidget(row, 5, actions_widget)
            self.users_table.setRowHeight(row, 50)

    def _open_add_user_dialog(self):
        """Open dialog to add a new user to Firebase"""
        dialog = FirebaseUserDialog(self.window(), mode="add")
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            username, email, password, role = dialog.get_user_data()
            self._add_user(username, email, password, role)

    def _open_edit_user_dialog(self, username: str):
        """Open dialog to edit an existing user"""
        from main import FirebaseManager
        user = FirebaseManager.get_user_by_username(username)
        if user:
            dialog = FirebaseUserDialog(
                self.window(), 
                mode="edit",
                username=username,
                email=user.get('email', ''),
                role=user.get('role', 'sales')
            )
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                new_username, new_email, new_password, new_role = dialog.get_user_data()
                self._edit_user(username, new_username, new_email, new_password, new_role)

    def _add_user(self, username: str, email: str, password: str, role: str):
        """Add a new user to Firebase"""
        from main import FirebaseManager
        
        if FirebaseManager.save_user_to_firebase(username, email, password, role):
            # Send welcome email - Import the function from main
            from main import send_welcome_email
            send_welcome_email(email, username, role, password)
            
            self._load_users()
            QtWidgets.QMessageBox.information(
                self, "User Added",
                f"User '{username}' has been added successfully with {role} role.\n"
                f"A welcome email has been sent to {email}"
            )
        else:
            QtWidgets.QMessageBox.critical(
                self, "Error",
                "Failed to save user. Username or email may already exist."
            )

    def _edit_user(self, old_username: str, new_username: str, new_email: str, new_password: str, new_role: str):
        """Edit an existing user in Firebase"""
        from main import FirebaseManager
        from firebase_admin import auth
        from firebase_admin import db
        from access_control import normalize_role
        
        # Get existing user
        user = FirebaseManager.get_user_by_username(old_username)
        if not user:
            QtWidgets.QMessageBox.critical(self, "Error", "User not found.")
            return
        
        firebase_uid = user.get('firebase_uid')
        if not firebase_uid:
            QtWidgets.QMessageBox.critical(self, "Error", "User is missing a Firebase UID.")
            return
        ref = db.reference(f'/users/{firebase_uid}')
        new_email = new_email.strip().lower()
        normalized_role = normalize_role(new_role)

        if old_username != new_username:
            existing = FirebaseManager.get_user_by_username(new_username)
            if existing and existing.get('firebase_uid') != firebase_uid:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate Username",
                    f"Username '{new_username}' already exists. Choose a different username.",
                )
                return
        
        # Update fields
        updates = {}
        auth_updates = {}
        
        if old_username != new_username:
            updates['username'] = new_username
            auth_updates['display_name'] = new_username
        
        if str(user.get('email', '')).strip().lower() != new_email:
            updates['email'] = new_email
            auth_updates['email'] = new_email
        
        if new_password:
            auth_updates['password'] = new_password
        
        if normalize_role(user.get('role')) != normalized_role:
            updates['role'] = normalized_role
        
        updates['updated_at'] = datetime.now().isoformat()
        
        if auth_updates:
            try:
                auth.update_user(firebase_uid, **auth_updates)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Firebase Auth Error",
                    f"Could not update Firebase Authentication for this user:\n{exc}",
                )
                return

        if updates:
            try:
                ref.update(updates)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Database Update Error",
                    f"Firebase Authentication was updated, but the user profile could not be saved:\n{exc}",
                )
                return
        
        self._load_users()
        QtWidgets.QMessageBox.information(
            self, "User Updated",
            f"User '{new_username}' has been updated successfully."
        )

    def _delete_user(self, username: str):
        """Delete a user from Firebase"""
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete user '{username}'?\n\n"
            f"This action cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        from main import FirebaseManager
        if FirebaseManager.delete_user_from_firebase(username):
            self._load_users()
            QtWidgets.QMessageBox.information(
                self, "User Deleted",
                f"User '{username}' has been deleted successfully."
            )
        else:
            QtWidgets.QMessageBox.critical(
                self, "Error",
                "Failed to delete user."
            )

class FirebaseUserDialog(QtWidgets.QDialog):
    """Dialog for adding or editing user credentials in Firebase"""
    
    def __init__(self, parent=None, mode="add", username="", email="", role="sales"):
        super().__init__(parent)
        self.mode = mode
        self._username = username
        self._email = email
        self._role = role
        self._password_visible = False
        self._init_ui()
    
    def _init_ui(self):
        self.setWindowTitle(f"{'Add' if self.mode == 'add' else 'Edit'} User")
        self.setFixedSize(500, 560)
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setWindowFlags(
            QtCore.Qt.Dialog
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.WindowSystemMenuHint
            | QtCore.Qt.WindowCloseButtonHint
            | QtCore.Qt.MSWindowsFixedSizeDialogHint
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { background: transparent; }
        """)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        
        icon = QtWidgets.QLabel("👤")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet("font-size: 0px; background: transparent;")
        icon.setVisible(False)
        layout.addWidget(icon)
        
        title = QtWidgets.QLabel(f"{'Add New' if self.mode == 'add' else 'Edit'} User")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: 800;
            color: #0f172a;
            font-family: 'Inter', 'Segoe UI', sans-serif;
        """)
        layout.addWidget(title)
        subtitle = QtWidgets.QLabel("Create app access and assign a workspace role.")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setStyleSheet("""
            font-size: 12px;
            color: #64748b;
            font-family: 'Inter', 'Segoe UI', sans-serif;
        """)
        layout.addWidget(subtitle)
        
        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        
        # Username
        self.username_edit = _field("Enter username")
        if self.mode == "edit":
            self.username_edit.setText(self._username)
        form_layout.addRow(_label("Username:", bold=True), self.username_edit)
        
        # Email
        self.email_edit = _field("Enter email address")
        if self.mode == "edit":
            self.email_edit.setText(self._email)
        form_layout.addRow(_label("Email:", bold=True), self.email_edit)
        
        # Password
        password_container = QtWidgets.QWidget()
        password_layout = QtWidgets.QHBoxLayout(password_container)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(8)
        
        self.password_edit = _field(
            "Enter password (min 6 chars)" if self.mode == "add" else "New password (leave blank to keep current)",
            QtWidgets.QLineEdit.Password
        )
        self.password_edit.setMinimumHeight(36)
        
        self.eye_btn = QtWidgets.QPushButton("👁")
        self.eye_btn.setText("Show")
        self.eye_btn.setFixedSize(58, 36)
        self.eye_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.eye_btn.setStyleSheet(f"""
            QPushButton {{
                background: #f8fafc;
                border: 1px solid {_BORDER};
                border-radius: 6px;
                color: {_TEXT};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        self.eye_btn.clicked.connect(self._toggle_password)
        
        password_layout.addWidget(self.password_edit)
        password_layout.addWidget(self.eye_btn)
        form_layout.addRow(_label("Password:", bold=True), password_container)
        
        # Confirm Password
        self.confirm_edit = _field("Confirm password", QtWidgets.QLineEdit.Password)
        self.confirm_edit.setMinimumHeight(36)
        form_layout.addRow(_label("Confirm:", bold=True), self.confirm_edit)
        
        # Role
        self.role_combo = QtWidgets.QComboBox()
        self.role_combo.setObjectName("userRoleCombo")
        self.role_combo.addItems(["admin", "sales", "projects", "finance"])
        self.role_combo.setCurrentText(self._role)
        self.role_combo.setMinimumHeight(38)
        self.role_combo.setStyleSheet(f"""
            QComboBox#userRoleCombo {{
                background: white;
                border: 1px solid {_BORDER};
                border-radius: 6px;
                color: {_TEXT};
                font-size: 13px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                padding: 0 34px 0 12px;
            }}
            QComboBox#userRoleCombo:focus {{
                border-color: {_BLUE};
            }}
            QComboBox#userRoleCombo::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid {_BORDER};
                background: #f8fafc;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }}
            QComboBox#userRoleCombo::down-arrow {{
                image: none;
            }}
            QComboBox#userRoleCombo QAbstractItemView {{
                background: white;
                border: 1px solid {_BORDER};
                selection-background-color: #e8f0fe;
                selection-color: {_TEXT};
                outline: none;
            }}
        """)
        form_layout.addRow(_label("Role:", bold=True), self.role_combo)
        
        layout.addLayout(form_layout)
        
        role_desc = QtWidgets.QLabel(
            "<b>Role Permissions:</b><br>"
            "• <b>Admin</b> - Full access to all tabs<br>"
            "• <b>Projects</b> - Projects & Invoice only<br>"
            "• <b>Finance</b> - Financial Management only<br>"
            "• <b>Sales</b> - Quote Forms only"
        )
        role_desc.setStyleSheet(f"""
            font-size: 12px;
            color: {_MUTED};
            background: #f8fafc;
            border: 1px solid {_BORDER};
            padding: 12px;
            border-radius: 6px;
        """)
        role_desc.setWordWrap(True)
        layout.addWidget(role_desc)
        
        layout.addSpacing(8)
        
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(12)
        
        cancel_btn = _btn("Cancel", color=_BG, text_color=_TEXT, width=100)
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = _btn("Save", color=_GREEN, width=100)
        save_btn.clicked.connect(self._validate_and_save)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.ensurePolished()
        self.updateGeometry()
        self.update()
        QtCore.QTimer.singleShot(0, self._finish_initial_paint)

    def _finish_initial_paint(self):
        if not self.isVisible():
            return
        parent = self.parentWidget()
        if parent is not None:
            parent_rect = parent.frameGeometry()
            self.move(parent_rect.center() - self.rect().center())
        self.repaint()
        for child in self.findChildren(QtWidgets.QWidget):
            child.update()
        self.raise_()
        self.activateWindow()
    
    def _toggle_password(self):
        if self._password_visible:
            self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            self.eye_btn.setText("👁")
        else:
            self.password_edit.setEchoMode(QtWidgets.QLineEdit.Normal)
            self.eye_btn.setText("⊘")
        self._password_visible = not self._password_visible
        self.eye_btn.setText("Hide" if self._password_visible else "Show")
    
    def _validate_and_save(self):
        import re
        
        username = self.username_edit.text().strip()
        email = self.email_edit.text().strip().lower()
        password = self.password_edit.text()
        confirm = self.confirm_edit.text()
        role = self.role_combo.currentText()
        
        if not username:
            QtWidgets.QMessageBox.warning(self, "Error", "Username is required.")
            return
        
        if " " in username:
            QtWidgets.QMessageBox.warning(self, "Error", "Username cannot contain spaces.")
            return
        
        if not email:
            QtWidgets.QMessageBox.warning(self, "Error", "Email is required.")
            return
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            QtWidgets.QMessageBox.warning(self, "Error", "Please enter a valid email address.")
            return
        
        if self.mode == "add":
            if not password:
                QtWidgets.QMessageBox.warning(self, "Error", "Password is required for new users.")
                return
            if len(password) < 6:
                QtWidgets.QMessageBox.warning(self, "Error", "Password must be at least 6 characters.")
                return
            if password != confirm:
                QtWidgets.QMessageBox.warning(self, "Error", "Passwords do not match.")
                return
        else:
            if password:
                if len(password) < 6:
                    QtWidgets.QMessageBox.warning(self, "Error", "Password must be at least 6 characters.")
                    return
                if password != confirm:
                    QtWidgets.QMessageBox.warning(self, "Error", "Passwords do not match.")
                    return
        
        self._username_result = username
        self._email_result = email
        self._password_result = password
        self._role_result = role
        self.accept()
    
    def get_user_data(self):
        return self._username_result, self._email_result, self._password_result, self._role_result  

class UserCredentialDialog(QtWidgets.QDialog):
    """Dialog for adding or editing user credentials"""
    
    def __init__(self, parent=None, mode="add", username="", role="sales"):
        super().__init__(parent)
        self.mode = mode
        self._username = username
        self._role = role
        self._password_visible = False
        self._init_ui()
    
    def _init_ui(self):
        self.setWindowTitle(f"{'Add' if self.mode == 'add' else 'Edit'} User")
        self.setFixedSize(420, 480)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{
                background: {_BG};
            }}
        """)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)
        
        # Icon
        icon = QtWidgets.QLabel("👤")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet("font-size: 48px; background: transparent; border: none;")
        layout.addWidget(icon)
        
        # Title
        title = QtWidgets.QLabel(f"{'Add New' if self.mode == 'add' else 'Edit'} User")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 20px;
            font-weight: 700;
            color: #0f172a;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            margin-bottom: 8px;
        """)
        layout.addWidget(title)
        
        # Form fields
        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        
        # Username field
        self.username_edit = _field("Enter username")
        if self.mode == "edit":
            self.username_edit.setText(self._username)
        form_layout.addRow(_label("Username:", bold=True), self.username_edit)
        
        # Password field (with toggle)
        password_container = QtWidgets.QWidget()
        password_layout = QtWidgets.QHBoxLayout(password_container)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(8)
        
        self.password_edit = _field(
            "Enter password" if self.mode == "add" else "New password (leave blank to keep current)",
            QtWidgets.QLineEdit.Password
        )
        self.password_edit.setMinimumHeight(36)
        
        self.eye_btn = QtWidgets.QPushButton("👁")
        self.eye_btn.setFixedSize(36, 36)
        self.eye_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.eye_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_BG};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: #e2e8f0;
            }}
        """)
        self.eye_btn.clicked.connect(self._toggle_password)
        
        password_layout.addWidget(self.password_edit)
        password_layout.addWidget(self.eye_btn)
        
        form_layout.addRow(_label("Password:", bold=True), password_container)
        
        # Confirm password field
        self.confirm_edit = _field("Confirm password", QtWidgets.QLineEdit.Password)
        form_layout.addRow(_label("Confirm:", bold=True), self.confirm_edit)
        
        # Role selection
        self.role_combo = QtWidgets.QComboBox()
        self.role_combo.addItems(["admin", "sales", "projects", "finance"])
        self.role_combo.setCurrentText(self._role)
        self.role_combo.setStyleSheet(f"""
            QComboBox {{
                padding: 8px 12px;
                border: 1px solid {_BORDER};
                border-radius: 6px;
                font-size: 13px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                background: white;
                min-height: 36px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
        """)
        form_layout.addRow(_label("Role:", bold=True), self.role_combo)
        
        layout.addLayout(form_layout)
        
        # Role description
        role_desc = QtWidgets.QLabel(
            "<b>Role Permissions:</b><br>"
            "• <b>Admin</b> - Full access to all tabs<br>"
            "• <b>Projects</b> - Projects & Invoice only<br>"
            "• <b>Finance</b> - Financial Management only<br>"
            "• <b>Sales</b> - Quote Forms only"
        )
        role_desc.setStyleSheet(f"""
            font-size: 11px;
            color: {_MUTED};
            background: {_BG};
            padding: 12px;
            border-radius: 6px;
            margin-top: 8px;
        """)
        role_desc.setWordWrap(True)
        layout.addWidget(role_desc)
        
        layout.addSpacing(8)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(12)
        
        cancel_btn = _btn("Cancel", color=_BG, text_color=_TEXT, width=100)
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = _btn("Save", color=_GREEN, width=100)
        save_btn.clicked.connect(self._validate_and_save)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
    
    def _toggle_password(self):
        """Toggle password visibility"""
        if self._password_visible:
            self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            self.eye_btn.setText("👁")
        else:
            self.password_edit.setEchoMode(QtWidgets.QLineEdit.Normal)
            self.eye_btn.setText("⊘")
        self._password_visible = not self._password_visible
    
    def _validate_and_save(self):
        """Validate inputs and save"""
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        confirm = self.confirm_edit.text()
        role = self.role_combo.currentText()
        
        # Validate username
        if not username:
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Username is required.")
            self.username_edit.setFocus()
            return
        
        if " " in username:
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Username cannot contain spaces.")
            self.username_edit.setFocus()
            return
        
        # Validate password for new user
        if self.mode == "add":
            if not password:
                QtWidgets.QMessageBox.warning(self, "Validation Error", "Password is required for new users.")
                self.password_edit.setFocus()
                return
            if len(password) < 6:
                QtWidgets.QMessageBox.warning(self, "Validation Error", "Password must be at least 6 characters.")
                self.password_edit.setFocus()
                return
            if password != confirm:
                QtWidgets.QMessageBox.warning(self, "Validation Error", "Passwords do not match.")
                self.confirm_edit.setFocus()
                return
        else:
            # For edit mode, password is optional
            if password:
                if len(password) < 6:
                    QtWidgets.QMessageBox.warning(self, "Validation Error", "Password must be at least 6 characters.")
                    self.password_edit.setFocus()
                    return
                if password != confirm:
                    QtWidgets.QMessageBox.warning(self, "Validation Error", "Passwords do not match.")
                    self.confirm_edit.setFocus()
                    return
        
        self._username_result = username
        self._password_result = password
        self._role_result = role
        self.accept()
    
    def get_user_data(self):
        """Return the user data from the dialog"""
        return self._username_result, self._password_result, self._role_result


# ══════════════════════════════════════════════════════════════════════════════
#  Preferences tab
# ══════════════════════════════════════════════════════════════════════════════
class _PreferencesTab(QtWidgets.QWidget):
    def __init__(self, settings: dict):
        super().__init__()
        self._settings = settings
        app = settings.get("app", {})
        gh  = settings.get("github", {})

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # ── Invoice defaults ───────────────────────────────────────────────
        layout.addWidget(_section_title("Invoice Defaults"))

        form = QtWidgets.QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self.tax_e = _field("e.g. 8.5")
        self.tax_e.setText(str(settings.get("company", {}).get("default_tax_rate", "0")))
        tax_row = QtWidgets.QHBoxLayout()
        tax_row.addWidget(self.tax_e)
        tax_row.addWidget(_label("%", muted=True))
        tax_row.addStretch()
        form.addRow(_label("Default Tax Rate", bold=True), tax_row)

        self.terms_e = QtWidgets.QPlainTextEdit()
        self.terms_e.setPlainText(settings.get("company", {}).get(
            "default_terms",
            "Thank you for your business!\nBest regards,\n\nMABS Engineering LLC"))
        self.terms_e.setFixedHeight(90)
        self.terms_e.setStyleSheet(f"""
            QPlainTextEdit {{
                padding: 8px 12px; border: 1px solid {_BORDER};
                border-radius: 6px; font-size: 13px;
                font-family: 'Inter', 'Segoe UI', sans-serif; color: {_TEXT};
            }}
            QPlainTextEdit:focus {{ border-color: {_BLUE}; }}
        """)
        form.addRow(_label("Default Terms", bold=True), self.terms_e)
        layout.addLayout(form)

        layout.addSpacing(8)
        layout.addWidget(_section_title("Application"))

        # Auto-update toggle
        upd_row = QtWidgets.QHBoxLayout()
        self.upd_chk = QtWidgets.QCheckBox("Check for updates automatically at startup")
        self.upd_chk.setChecked(app.get("auto_check_updates", True))
        self.upd_chk.setStyleSheet(
            f"font-size: 13px; font-family: 'Inter', 'Segoe UI'; color: {_TEXT};")
        upd_row.addWidget(self.upd_chk)
        upd_row.addStretch()
        layout.addLayout(upd_row)

        # Log level
        log_row = QtWidgets.QHBoxLayout()
        log_row.addWidget(_label("Log level:", bold=True))
        self.log_combo = QtWidgets.QComboBox()
        self.log_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_combo.setCurrentText(app.get("log_level", "INFO"))
        self.log_combo.setFixedWidth(110)
        self.log_combo.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 10px; border: 1px solid {_BORDER};
                border-radius: 6px; font-size: 13px;
                font-family: 'Inter', 'Segoe UI'; background: white; color: {_TEXT};
            }}
        """)
        log_row.addWidget(self.log_combo)
        log_row.addStretch()
        layout.addLayout(log_row)

        layout.addSpacing(8)
        layout.addWidget(_section_title("GitHub / Updates"))

        gh_form = QtWidgets.QFormLayout()
        gh_form.setSpacing(10)
        gh_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        gh_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self.repo_e    = _field("owner/repo")
        self.version_e = _field("e.g. 1.3")
        self.repo_e.setText(gh.get("repo", ""))
        self.version_e.setText(gh.get("current_version", ""))
        gh_form.addRow(_label("GitHub Repo", bold=True),      self.repo_e)
        gh_form.addRow(_label("Current Version", bold=True),  self.version_e)
        layout.addLayout(gh_form)

        layout.addStretch()

    def collect(self) -> dict:
        app = self._settings.get("app", {})
        app["auto_check_updates"] = self.upd_chk.isChecked()
        app["log_level"]          = self.log_combo.currentText()

        co = self._settings.get("company", {})
        try:
            co["default_tax_rate"] = float(self.tax_e.text().strip())
        except ValueError:
            pass
        co["default_terms"] = self.terms_e.toPlainText().strip()

        gh = self._settings.get("github", {})
        gh["repo"]            = self.repo_e.text().strip()
        gh["current_version"] = self.version_e.text().strip()

        return {"app": app, "company": co, "github": gh}


# ══════════════════════════════════════════════════════════════════════════════
#  Main dialog
# ══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(QtWidgets.QDialog):
    settingsSaved = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = max(1080, min(1280, int(screen.width() * 0.86)))
        h = max(660, min(820, int(screen.height() * 0.82)))
        self.resize(w, h)
        self.setMinimumSize(1000, 620)

        self._settings = _load_settings()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── header bar ────────────────────────────────────────────────────
        hdr = QtWidgets.QFrame()
        hdr.setFixedHeight(64)
        hdr.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0f2944, stop:0.6 #1a5276, stop:1 #0f2944);
            }
        """)
        hdr_lay = QtWidgets.QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(24, 0, 24, 0)

        ico = QtWidgets.QLabel("⚙")
        ico.setStyleSheet("font-size:26px; color:white;")
        ttl = QtWidgets.QLabel("Settings")
        ttl.setStyleSheet(
            "font-size:20px; font-weight:700; color:white;"
            " font-family:'Inter','Segoe UI',sans-serif; margin-left:10px;")
        sub = QtWidgets.QLabel("Company · Security · Preferences")
        sub.setStyleSheet(
            "font-size:12px; color:rgba(255,255,255,0.7);"
            " font-family:'Inter','Segoe UI'; margin-left:10px;")

        hdr_lay.addWidget(ico)
        hdr_lay.addWidget(ttl)
        hdr_lay.addWidget(sub)
        hdr_lay.addStretch()
        root.addWidget(hdr)

        # ── tab widget ────────────────────────────────────────────────────
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: {_BG};
            }}
            QTabBar::tab {{
                background: {_BG};
                color: {_MUTED};
                padding: 12px 26px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                border-bottom: 3px solid transparent;
                min-width: 150px;
            }}
            QTabBar::tab:selected {{
                color: {_BLUE};
                border-bottom: 3px solid {_BLUE};
                background: white;
            }}
            QTabBar::tab:hover:!selected {{
                color: {_TEXT};
                background: #eaeef2;
            }}
        """)

        self._co_tab   = _CompanyTab(self._settings)
        self._sec_tab  = _SecurityTab(self._settings)
        self._pref_tab = _PreferencesTab(self._settings)

        self._tabs.addTab(self._co_tab,   "Company Info")
        self._tabs.addTab(self._sec_tab,  "Security")
        self._tabs.addTab(self._pref_tab, "Preferences")
        root.addWidget(self._tabs, 1)

        # ── footer ────────────────────────────────────────────────────────
        ftr = QtWidgets.QFrame()
        ftr.setFixedHeight(60)
        ftr.setStyleSheet(f"background:white; border-top:1px solid {_BORDER};")
        ftr_lay = QtWidgets.QHBoxLayout(ftr)
        ftr_lay.setContentsMargins(24, 0, 24, 0)
        ftr_lay.setSpacing(10)

        self._status_lbl = QtWidgets.QLabel("")
        self._status_lbl.setStyleSheet(f"color:{_GREEN}; font-size:13px; font-family:'Inter','Segoe UI';")

        cancel_b = _btn("Cancel",        color=_BG,   text_color=_TEXT, width=100)
        save_b   = _btn("Save Settings", color=_BLUE, width=140)

        cancel_b.clicked.connect(self.reject)
        save_b.clicked.connect(self._save)

        ftr_lay.addWidget(self._status_lbl, 1)
        ftr_lay.addWidget(cancel_b)
        ftr_lay.addWidget(save_b)
        root.addWidget(ftr)

    # ──────────────────────────────────────────────────────────────────────
    def _save(self):
        # Collect company info
        self._settings["company"] = self._co_tab.collect()

        # Collect preferences (but preserve users from security tab)
        pref = self._pref_tab.collect()
        self._settings["app"]     = pref["app"]
        self._settings["github"]  = pref["github"]
        self._settings["company"].update({
            k: v for k, v in pref["company"].items()
            if k not in self._settings["company"] or k in ("default_tax_rate", "default_terms")
        })

        if _save_settings(self._settings):
            self._status_lbl.setText("✓  Settings saved")
            QtCore.QTimer.singleShot(2500, lambda: self._status_lbl.setText(""))
            self.settingsSaved.emit()

            # Hot-reload Config so the running app picks up changes immediately
            try:
                import main as _main
                _main.Config.load()
            except Exception:
                pass
        else:
            QtWidgets.QMessageBox.critical(self, "Error", "Could not write settings.json")
