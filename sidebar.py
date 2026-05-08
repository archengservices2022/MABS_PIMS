"""Premium sidebar navigation for the PIMS workspace."""
from PyQt5 import QtWidgets, QtCore, QtGui

SB_TOP = "#111827"
SB_MID = "#172033"
SB_BOT = "#0F172A"
ACCENT = "#0F766E"
DIVIDER = "rgba(255,255,255,0.07)"

ITEM_ACCENTS = ["#0F766E", "#2563EB", "#10B981", "#B45309"]

NAV_ITEMS = [
    ("dashboard", "D", "Dashboard"),
    ("quotes",    "Q", "Quote Forms"),
    ("projects",  "P", "Project & Invoice"),
    ("finance",   "$", "Financial"),
]
BOTTOM_ITEMS = [("settings", "S", "Settings")]


class _NavBtn(QtWidgets.QAbstractButton):
    def __init__(self, icon_ch, label, accent=ACCENT, parent=None):
        super().__init__(parent)
        self._icon = icon_ch
        self._label = label
        self._accent = accent
        self._active = False
        self.setFixedHeight(48)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setCheckable(True)
        self.setToolTip(label)

    def setActive(self, value):
        self._active = value
        self.setChecked(value)
        self.update()

    def paintEvent(self, _):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        width, height = self.width(), self.height()

        if self._active:
            r = int(self._accent[1:3], 16)
            g = int(self._accent[3:5], 16)
            b = int(self._accent[5:7], 16)
            painter.fillRect(0, 0, width, height, QtGui.QColor(r, g, b, 45))
            bar = QtGui.QPainterPath()
            bar.addRoundedRect(QtCore.QRectF(0, 8, 3, height - 16), 2, 2)
            painter.fillPath(bar, QtGui.QColor(self._accent))
        elif self.underMouse():
            painter.fillRect(0, 0, width, height, QtGui.QColor(255, 255, 255, 12))

        icon_rect = QtCore.QRect(16, 10, 28, 28)
        painter.setBrush(QtGui.QColor(self._accent) if self._active else QtGui.QColor(255, 255, 255, 24))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(icon_rect, 8, 8)

        painter.setFont(QtGui.QFont("Inter", 11, QtGui.QFont.Bold))
        painter.setPen(QtGui.QColor("#FFFFFF") if self._active else QtGui.QColor(255, 255, 255, 130))
        painter.drawText(icon_rect, QtCore.Qt.AlignCenter, self._icon)

        painter.setFont(QtGui.QFont("Inter", 13, QtGui.QFont.DemiBold if self._active else QtGui.QFont.Normal))
        painter.setPen(QtGui.QColor(255, 255, 255, 240 if self._active else 135))
        painter.drawText(QtCore.QRect(58, 0, width - 66, height), QtCore.Qt.AlignVCenter, self._label)
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class Sidebar(QtWidgets.QWidget):
    page_changed = QtCore.pyqtSignal(int)

    def __init__(self, company_name="MABS Engineering", parent=None):
        super().__init__(parent)
        self._company = company_name
        self._name_lbl = None
        self._buttons = []  # This is our list of _NavBtn objects
        self._settings_btn = None  # Store reference to settings button
        self.setFixedWidth(252)
        self._build()

    def paintEvent(self, _):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        grad = QtGui.QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QtGui.QColor(SB_TOP))
        grad.setColorAt(0.5, QtGui.QColor(SB_MID))
        grad.setColorAt(1.0, QtGui.QColor(SB_BOT))
        painter.fillRect(self.rect(), grad)
        painter.end()

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        logo = QtWidgets.QWidget()
        logo.setFixedHeight(84)
        logo.setStyleSheet("background:transparent;")
        logo_lay = QtWidgets.QVBoxLayout(logo)
        logo_lay.setContentsMargins(18, 18, 16, 14)
        logo_lay.setSpacing(3)

        name_row = QtWidgets.QHBoxLayout()
        name_row.setSpacing(0)
        self._name_lbl = QtWidgets.QLabel("PIMS")
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:24px; font-weight:900;"
            " font-family:'Inter','Segoe UI'; background:transparent;")
        name_row.addWidget(self._name_lbl, 1)

        sub = QtWidgets.QLabel("Project & Invoice Management")
        sub.setStyleSheet(
            f"color:{ACCENT}; font-size:11px; font-weight:800; letter-spacing:0px;"
            " font-family:'Inter','Segoe UI'; background:transparent;")

        logo_lay.addLayout(name_row)
        logo_lay.addWidget(sub)
        root.addWidget(logo)
        root.addWidget(self._div())
        root.addSpacing(10)

        section = QtWidgets.QLabel("WORKSPACE")
        section.setFixedHeight(22)
        section.setStyleSheet(
            "color:rgba(255,255,255,0.34); font-size:10px; font-weight:800;"
            " letter-spacing:1.4px; font-family:'Inter','Segoe UI';"
            " background:transparent; padding-left:18px;")
        root.addWidget(section)
        root.addSpacing(4)

        for idx, (_key, icon, label) in enumerate(NAV_ITEMS):
            btn = _NavBtn(icon, label, accent=ITEM_ACCENTS[idx % len(ITEM_ACCENTS)])
            btn.clicked.connect(lambda _, page_idx=idx: self._select(page_idx))
            self._buttons.append(btn)
            root.addWidget(btn)

        root.addStretch()
        root.addWidget(self._div())
        root.addSpacing(4)

        for _key, icon, label in BOTTOM_ITEMS:
            btn = _NavBtn(icon, label, accent="#94A3B8")
            btn.clicked.connect(lambda: self.page_changed.emit(99))
            self._buttons.append(btn)  # Also add settings to buttons list
            self._settings_btn = btn  # Store reference to settings button
            root.addWidget(btn)

        footer = QtWidgets.QLabel("MABS Engineering LLC")
        footer.setFixedHeight(28)
        footer.setStyleSheet(
            "color:rgba(255,255,255,0.24); font-size:9px;"
            " font-family:'Inter','Segoe UI'; background:transparent; padding-left:18px;")
        root.addWidget(footer)
        root.addSpacing(6)

        self._select(0, emit=False)

    def _div(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{DIVIDER}; border:none;")
        return line

    def _select(self, idx, emit=True):
        for button_idx, button in enumerate(self._buttons):
            # Only set active for main nav buttons (0-3), not settings button
            if button_idx < len(NAV_ITEMS):
                button.setActive(button_idx == idx)
        if emit:
            self.page_changed.emit(idx)

    def select(self, idx):
        """Select a navigation item by index (0-3) without emitting signal"""
        self._select(idx, emit=False)

    def update_company(self, name):
        self._company = name
        if self._name_lbl:
            self._name_lbl.setText("PIMS")
        self.update()

    # ========== NEW METHODS FOR ROLE-BASED ACCESS CONTROL ==========
    # These methods are added without changing existing functionality
    
    def set_enabled_only_quotes(self):
        """
        Restrict sidebar to only show Quote Forms for sales users.
        Disables other buttons and visually grays them out.
        """
        for idx, btn in enumerate(self._buttons):
            if idx < len(NAV_ITEMS):  # Main navigation buttons (0-3)
                if idx == 1:  # Quote Forms index
                    btn.setEnabled(True)
                    btn.setVisible(True)
                    # Reset accent for Quote Forms
                    btn._accent = ITEM_ACCENTS[1]
                else:
                    btn.setEnabled(False)
                    btn.setVisible(True)  # Keep visible but disabled
                    # Change accent to gray for disabled state
                    btn._accent = "#4B5563"
                    btn.update()  # Force repaint with new color
            else:
                # Settings button (index 4)
                btn.setEnabled(False)
                btn._accent = "#4B5563"
                btn.update()
    
    def set_visible_pages(self, visible_indices):
        """
        Set which navigation items are visible.
        
        Args:
            visible_indices: List of indices to show (e.g., [0,1] for Dashboard and Quote Forms)
                            Index mapping: 0:Dashboard, 1:Quote Forms, 2:Projects, 3:Financial
        """
        for idx, btn in enumerate(self._buttons):
            if idx < len(NAV_ITEMS):  # Main navigation buttons
                if idx in visible_indices:
                    btn.setVisible(True)
                    btn.setEnabled(True)
                    # Restore original accent
                    btn._accent = ITEM_ACCENTS[idx % len(ITEM_ACCENTS)]
                else:
                    btn.setVisible(False)
                    btn.setEnabled(False)
            else:
                # Settings button - only show if specifically requested or if admin
                if 99 in visible_indices:
                    btn.setVisible(True)
                    btn.setEnabled(True)
                    btn._accent = "#94A3B8"
                else:
                    btn.setVisible(False)
                    btn.setEnabled(False)
        
        # Force repaint for all buttons
        for btn in self._buttons:
            btn.update()
    
    def enable_all_pages(self):
        """Enable all navigation items (for admin users)"""
        for idx, btn in enumerate(self._buttons):
            if idx < len(NAV_ITEMS):  # Main navigation buttons
                btn.setEnabled(True)
                btn.setVisible(True)
                # Restore original accent
                btn._accent = ITEM_ACCENTS[idx % len(ITEM_ACCENTS)]
                btn.update()
            else:
                # Settings button
                btn.setEnabled(True)
                btn.setVisible(True)
                btn._accent = "#94A3B8"
                btn.update()
    
    def get_current_selection(self) -> int:
        """Return the currently selected page index"""
        for idx, btn in enumerate(self._buttons):
            if idx < len(NAV_ITEMS) and btn._active:
                return idx
        return 0
    
    def get_nav_buttons(self):
        """Return the list of navigation buttons (for compatibility)"""
        return self._buttons