"""Premium top bar with search, manual refresh, and sync status."""
from datetime import datetime
from PyQt5 import QtWidgets, QtCore, QtGui

WHITE = "#FFFFFF"
INDIGO = "#0F766E"
INDIGO_L = "#ECFDF5"
SLATE50 = "#F8FAFC"
SLATE200 = "#E2E8F0"
SLATE400 = "#94A3B8"
SLATE600 = "#475569"
SLATE800 = "#1E293B"
SLATE900 = "#0F172A"


class TopBar(QtWidgets.QFrame):
    search_submitted = QtCore.pyqtSignal(str)
    search_text_changed = QtCore.pyqtSignal(str)
    settings_clicked = QtCore.pyqtSignal()
    logout_clicked = QtCore.pyqtSignal()
    refresh_clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(116)
        self.setStyleSheet(f"""
            QFrame {{
                background: {WHITE};
                border: none;
                border-bottom: 1px solid {SLATE200};
            }}
        """)
        self._build()

    def _build(self):
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(28, 0, 24, 0)
        lay.setSpacing(14)

        self._logo_label = QtWidgets.QLabel()
        self._logo_label.setFixedSize(96, 96)
        self._logo_label.setAlignment(QtCore.Qt.AlignCenter)
        self._logo_label.setVisible(False)
        self._logo_label.setStyleSheet("""
            QLabel {
                background: white;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
        """)
        lay.addWidget(self._logo_label)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(0)
        self._company_title = QtWidgets.QLabel("MABS Engineering LLC")
        self._company_title.setFixedHeight(38)
        self._company_title.setStyleSheet(
            f"color:{SLATE900}; font-size:30px; font-weight:900;"
            " font-family:'Inter','Segoe UI'; background:transparent; border:none;")
        self._page_label = QtWidgets.QLabel("Dashboard")
        self._page_label.setFixedHeight(20)
        self._page_label.setStyleSheet(
            f"color:{INDIGO}; font-size:15px; font-weight:900;"
            " font-family:'Inter','Segoe UI'; background:transparent; border:none;")
        self._sub = QtWidgets.QLabel(datetime.now().strftime("Today - %A, %B %d %Y"))
        self._sub.setFixedHeight(20)
        self._sub.setStyleSheet(
            f"color:{SLATE400}; font-size:13px; font-weight:700;"
            " font-family:'Inter','Segoe UI'; background:transparent; border:none;")
        meta_row = QtWidgets.QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(10)
        meta_row.addWidget(self._page_label)
        meta_row.addWidget(self._sub)
        meta_row.addStretch()
        title_col.addWidget(self._company_title)
        title_col.addLayout(meta_row)
        lay.addLayout(title_col)
        lay.addStretch()

        search_wrap = QtWidgets.QFrame()
        search_wrap.setFixedSize(360, 40)
        search_wrap.setStyleSheet(f"""
            QFrame {{
                background: {SLATE50};
                border: 1.5px solid {SLATE200};
                border-radius: 10px;
            }}
            QFrame:focus-within {{
                border-color: {INDIGO};
                background: {WHITE};
            }}
        """)
        search_lay = QtWidgets.QHBoxLayout(search_wrap)
        search_lay.setContentsMargins(12, 0, 12, 0)
        search_lay.setSpacing(8)

        icon = QtWidgets.QLabel("Q")
        icon.setFixedWidth(18)
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet(
            f"font-size:12px; font-weight:800; color:{SLATE400};"
            " background:transparent; border:none;")
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search quotes, invoices, projects...   Ctrl+K")
        self.search_edit.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                font-size: 13px;
                color: {SLATE800};
                font-family: 'Inter', 'Segoe UI';
                padding: 0;
            }}
        """)
        self.search_edit.returnPressed.connect(
            lambda: self.search_submitted.emit(self.search_edit.text().strip()))
        self.search_edit.textChanged.connect(self.search_text_changed.emit)
        search_lay.addWidget(icon)
        search_lay.addWidget(self.search_edit, 1)
        lay.addWidget(search_wrap)

        self.sync_label = QtWidgets.QLabel("Ready")
        self.sync_label.setFixedHeight(28)
        self.set_status("Ready")
        self.sync_label.setVisible(False)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.VLine)
        divider.setFixedHeight(28)
        divider.setStyleSheet(f"background:{SLATE200}; border:none;")
        lay.addWidget(divider)

        self.settings_btn = QtWidgets.QPushButton("Settings")
        self.settings_btn.setFixedHeight(36)
        self.settings_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.settings_btn.setStyleSheet(f"""
            QPushButton {{
                background: {WHITE};
                color: {SLATE600};
                border: 1px solid {SLATE200};
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Inter', 'Segoe UI';
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: {INDIGO_L};
                border-color: {INDIGO};
                color: {INDIGO};
            }}
        """)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        lay.addWidget(self.settings_btn)

        self.logout_btn = QtWidgets.QPushButton("Logout")
        self.logout_btn.setFixedHeight(36)
        self.logout_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: #FEF2F2;
                color: #B91C1C;
                border: 1px solid #FECACA;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 700;
                font-family: 'Inter', 'Segoe UI';
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: #FEE2E2;
                border-color: #FCA5A5;
                color: #991B1B;
            }}
        """)
        self.logout_btn.clicked.connect(self.logout_clicked.emit)
        lay.addWidget(self.logout_btn)

        avatar = QtWidgets.QLabel("ME")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setStyleSheet(f"""
            QLabel {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {INDIGO}, stop:1 #2563EB);
                color: white;
                border-radius: 18px;
                font-size: 12px;
                font-weight: 800;
                font-family: 'Inter', 'Segoe UI';
                border: none;
            }}
        """)
        lay.addWidget(avatar)

        self._rslot = QtWidgets.QHBoxLayout()
        self._rslot.setSpacing(4)
        lay.addLayout(self._rslot)

    def set_title(self, title):
        self._page_label.setText(title)

    def set_company(self, name):
        self._company_title.setText(name or "MABS Engineering LLC")

    def set_logo(self, path):
        pix = QtGui.QPixmap(str(path)) if path else QtGui.QPixmap()
        if pix.isNull():
            self._logo_label.clear()
            self._logo_label.setVisible(False)
            return
        self._logo_label.setPixmap(
            pix.scaled(90, 90, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        )
        self._logo_label.setVisible(True)

    def set_status(self, text, tone="neutral"):
        colors = {
            "neutral": (SLATE50, SLATE600, SLATE200),
            "success": ("#ECFDF5", "#047857", "#A7F3D0"),
            "warning": ("#FFFBEB", "#B45309", "#FDE68A"),
            "busy": (INDIGO_L, INDIGO, "#C7D2FE"),
        }
        bg, fg, border = colors.get(tone, colors["neutral"])
        self.sync_label.setText(text)
        self.sync_label.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 14px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 700;
                font-family: 'Inter', 'Segoe UI';
            }}
        """)

    def add_right_widget(self, widget):
        self._rslot.addWidget(widget)

    def get_search_widget(self):
        return self.search_edit
