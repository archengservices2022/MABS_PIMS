"""

from pathlib import Path
Premium Design System — MABS Engineering PIMS
Modern enterprise-grade UI inspired by Linear, Stripe, and Vercel.
"""

# ── Core Design Tokens ─────────────────────────────────────────────────────
from pathlib import Path

INDIGO     = "#0F766E"
INDIGO_D   = "#115E59"
INDIGO_L   = "#ECFDF5"

VIOLET     = "#2563EB"
VIOLET_L   = "#EFF6FF"

CYAN       = "#06B6D4"
CYAN_L     = "#ECFEFF"

EMERALD    = "#10B981"
EMERALD_D  = "#059669"
EMERALD_L  = "#ECFDF5"

AMBER      = "#F59E0B"
AMBER_D    = "#D97706"
AMBER_L    = "#FFFBEB"

ROSE       = "#F43F5E"
ROSE_D     = "#E11D48"
ROSE_L     = "#FFF1F2"

# Neutrals
SLATE_50   = "#F8FAFC"
SLATE_100  = "#F1F5F9"
SLATE_200  = "#E2E8F0"
SLATE_300  = "#CBD5E1"
SLATE_400  = "#94A3B8"
SLATE_500  = "#64748B"
SLATE_600  = "#475569"
SLATE_700  = "#334155"
SLATE_800  = "#1E293B"
SLATE_900  = "#0F172A"

WHITE      = "#FFFFFF"


def make_filter_icon(color="#64748B", size=22):
    """Return a compact funnel icon used by filter entry buttons."""
    from PyQt5 import QtCore, QtGui

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    scale = size / 22.0
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(max(1.8, 2.0 * scale))
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    path = QtGui.QPainterPath()
    path.moveTo(4 * scale, 5 * scale)
    path.lineTo(18 * scale, 5 * scale)
    path.lineTo(13 * scale, 11 * scale)
    path.lineTo(13 * scale, 17 * scale)
    path.lineTo(9 * scale, 19 * scale)
    path.lineTo(9 * scale, 11 * scale)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return QtGui.QIcon(pixmap)


def filter_button_stylesheet(active=False):
    border = "#99F6E4" if active else "#E2E8F0"
    bg = "#F0FDFA" if active else "#FFFFFF"
    fg = "#0F766E" if active else "#475569"
    hover_border = "#5EEAD4" if active else "#CBD5E1"
    hover_bg = "#CCFBF1" if active else "#F8FAFC"
    return f"""
        QPushButton {{
            background: {bg};
            color: {fg};
            border: 1.5px solid {border};
            border-radius: 10px;
            font-size: 14px;
            font-weight: 800;
            padding: 0px 16px;
            text-align: left;
        }}
        QPushButton:hover {{
            background: {hover_bg};
            border-color: {hover_border};
        }}
        QPushButton:pressed {{
            background: #ECFEFF;
            border-color: #2DD4BF;
        }}
    """


def configure_filter_button(button, text="Filter", active=False, height=42):
    """Apply the shared filter-button visual treatment in place."""
    from PyQt5 import QtCore, QtGui

    button.setText(text)
    button.setIcon(make_filter_icon("#0F766E" if active else "#64748B", 22))
    button.setIconSize(QtCore.QSize(22, 22))
    button.setMinimumHeight(height)
    button.setMinimumWidth(126)
    button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
    button.setStyleSheet(filter_button_stylesheet(active))
    return button
_CURRENT_FONT_SIZE = 13   # updated at startup based on screen width


def set_font_size(size: int) -> None:
    global _CURRENT_FONT_SIZE
    _CURRENT_FONT_SIZE = size


PAGE_BG    = "#F6F8FB"    # neutral enterprise background
CHEVRON_URL = (Path(__file__).resolve().parent / "assets" / "icons" / "chevron-down.svg").as_posix()
CHEVRON_WHITE_URL = (Path(__file__).resolve().parent / "assets" / "icons" / "chevron-down-white.svg").as_posix()
CALENDAR_URL = (Path(__file__).resolve().parent / "assets" / "icons" / "calendar.svg").as_posix()


def clean_dropdown_stylesheet() -> str:
    """Shared clean dropdown and spinner styling."""
    return f"""
QComboBox, QDateEdit {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1.5px solid {SLATE_200};
    border-radius: 8px;
    padding: 7px 22px 7px 12px;
    min-height: 24px;
    selection-background-color: {INDIGO_L};
    selection-color: {INDIGO_D};
}}
QComboBox:hover, QDateEdit:hover {{
    border-color: {SLATE_300};
    background: {WHITE};
}}
QComboBox:focus, QDateEdit:focus {{
    border: 1.5px solid #7C3AED;
    background: {WHITE};
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: none;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background: transparent;
}}
QComboBox::drop-down:hover, QDateEdit::drop-down:hover {{
    background: transparent;
    border-left: none;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url("{CHEVRON_URL}");
    width: 14px;
    height: 14px;
    margin-right: 2px;
}}
QDateEdit::down-arrow {{
    image: url("{CALENDAR_URL}");
    width: 15px;
    height: 15px;
    margin-right: 1px;
}}
QComboBox::down-arrow:on, QDateEdit::down-arrow:on {{
    top: 0px;
}}
QComboBox QAbstractItemView {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1px solid {SLATE_200};
    border-radius: 10px;
    selection-background-color: #F3EEFF;
    selection-color: {SLATE_900};
    padding: 8px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 7px 12px;
    border-radius: 7px;
}}
QComboBox QAbstractItemView::item:hover {{
    background: #F8F6FF;
    color: {SLATE_900};
}}
QComboBox QAbstractItemView::item:selected {{
    background: #F3EEFF;
    color: #6D28D9;
    font-weight: 800;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 0px;
    border: none;
    background: transparent;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}
"""


def install_clean_dropdown_style_patch() -> None:
    """Append dropdown cleanup rules to future local widget stylesheets."""
    from PyQt5 import QtCore, QtWidgets

    if getattr(QtWidgets.QWidget, "_mabs_clean_dropdown_patch", False):
        return

    original_set_style_sheet = QtWidgets.QWidget.setStyleSheet
    original_show_popup = QtWidgets.QComboBox.showPopup

    def patched_set_style_sheet(widget, style):
        style = style or ""
        if (
            ("QComboBox" in style or "QDateEdit" in style or "QSpinBox" in style or "QDoubleSpinBox" in style)
            and "mabs-clean-dropdown-style" not in style
        ):
            style = style + "\n/* mabs-clean-dropdown-style */\n" + clean_dropdown_stylesheet()
        return original_set_style_sheet(widget, style)

    def patched_show_popup(combo):
        if not combo.property("mabsStyledComboView"):
            view = QtWidgets.QListView(combo)
            view.setObjectName("mabsComboPopup")
            view.setUniformItemSizes(False)
            view.setSpacing(3)
            view.setMouseTracking(True)
            view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
            combo.setView(view)
            combo.setProperty("mabsStyledComboView", True)
        view = combo.view()
        if view is not None:
            view.setMinimumWidth(max(combo.width(), view.minimumWidth()))
            view.setAlternatingRowColors(False)
            view.setTextElideMode(QtCore.Qt.ElideRight)
            view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            view.setStyleSheet(f"""
                QListView {{
                    background: {WHITE};
                    color: {SLATE_800};
                    border: 1px solid {SLATE_200};
                    border-radius: 12px;
                    padding: 7px;
                    outline: none;
                    font-family: 'Inter', 'Segoe UI';
                    font-size: 13px;
                }}
                QListView::item {{
                    min-height: 28px;
                    padding: 8px 12px;
                    border-radius: 8px;
                    border: none;
                    color: {SLATE_800};
                }}
                QListView::item:hover {{
                    background: #F8F6FF;
                    color: {SLATE_900};
                }}
                QListView::item:selected {{
                    background: #F3EEFF;
                    color: #6D28D9;
                    font-weight: 800;
                    border: none;
                }}
                QScrollBar:vertical {{
                    width: 8px;
                    background: transparent;
                    margin: 8px 2px 8px 0;
                }}
                QScrollBar::handle:vertical {{
                    background: {SLATE_300};
                    border-radius: 4px;
                    min-height: 24px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background: #7C3AED;
                }}
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
            """)
        if combo.maxVisibleItems() > 8:
            combo.setMaxVisibleItems(8)
        return original_show_popup(combo)

    QtWidgets.QWidget.setStyleSheet = patched_set_style_sheet
    QtWidgets.QComboBox.showPopup = patched_show_popup
    QtWidgets.QWidget._mabs_clean_dropdown_patch = True


def get_stylesheet() -> str:
    fs = _CURRENT_FONT_SIZE          # e.g. 13 (normal) or 11 (small screen)
    fs_sm = max(9, fs - 2)           # table header / calendar header
    fs_tip = max(10, fs - 1)         # tooltip
    return f"""

/* ══ FOUNDATION ══ */
* {{ font-family: 'Inter', 'Segoe UI', 'Arial', sans-serif; outline: none; }}

QMainWindow, QDialog, QWidget {{
    background: {PAGE_BG};
    color: {SLATE_800};
    font-size: {fs}px;
}}

/* ══ NESTED TABS ══ */
QTabWidget::pane {{
    border: 1px solid {SLATE_200};
    background: {WHITE};
    border-radius: 12px;
}}
QTabBar::tab {{
    background: transparent;
    color: {SLATE_500};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 11px 22px;
    font-size: {fs}px;
    font-weight: 500;
    min-width: 120px;
}}
QTabBar::tab:selected {{
    color: {INDIGO};
    border-bottom: 2px solid {INDIGO};
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{
    color: {SLATE_700};
    background: {INDIGO_L};
    border-radius: 8px 8px 0 0;
}}

/* ══ BUTTONS ══ */
QPushButton {{
    background: {INDIGO};
    color: {WHITE};
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: {fs}px;
    font-weight: 600;
    min-height: 24px;
}}
QPushButton:hover   {{ background: {INDIGO_D}; }}
QPushButton:pressed {{ background: #2d40b8; }}
QPushButton:disabled {{
    background: {SLATE_200};
    color: {SLATE_400};
}}

QPushButton#success {{
    background: {EMERALD};
}}
QPushButton#success:hover {{ background: {EMERALD_D}; }}

QPushButton#danger {{
    background: {ROSE};
}}
QPushButton#danger:hover {{ background: {ROSE_D}; }}

QPushButton#outline {{
    background: transparent;
    color: {INDIGO};
    border: 1.5px solid {INDIGO};
}}
QPushButton#outline:hover {{ background: {INDIGO_L}; }}

QPushButton#ghost {{
    background: {WHITE};
    color: {SLATE_600};
    border: 1px solid {SLATE_200};
}}
QPushButton#ghost:hover {{
    background: {SLATE_100};
    border-color: {SLATE_300};
    color: {SLATE_800};
}}

/* ══ INPUTS ══ */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1.5px solid {SLATE_200};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: {fs}px;
    selection-background-color: {INDIGO_L};
    selection-color: {INDIGO};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1.5px solid {INDIGO};
    background: {WHITE};
}}
QLineEdit:disabled {{
    background: {SLATE_100};
    color: {SLATE_400};
}}

QSpinBox, QDoubleSpinBox, QDateEdit {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1.5px solid {SLATE_200};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: {fs}px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 1.5px solid {INDIGO};
}}

/* ══ COMBO ══ */
QComboBox {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1.5px solid {SLATE_200};
    border-radius: 8px;
    padding: 7px 12px;
    font-size: {fs}px;
    min-height: 24px;
}}
QComboBox:focus {{ border-color: {INDIGO}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: url("{CHEVRON_URL}");
    border: none;
    width: 14px;
    height: 14px;
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1px solid {SLATE_200};
    border-radius: 8px;
    selection-background-color: {INDIGO_L};
    selection-color: {INDIGO};
    padding: 4px;
    outline: none;
}}

/* ══ LABELS ══ */
{clean_dropdown_stylesheet()}

QLabel {{
    color: {SLATE_800};
    background: transparent;
    font-size: {fs}px;
    border: none;
}}

/* ══ GROUP BOX ══ */
QGroupBox {{
    background: {WHITE};
    border: 1px solid {SLATE_200};
    border-radius: 12px;
    margin-top: 16px;
    padding: 18px 14px 14px 14px;
    font-weight: 700;
    font-size: {fs}px;
    color: {SLATE_700};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {INDIGO};
    font-weight: 700;
}}

/* ══ TABLE ══ */
QTableWidget, QTableView {{
    background: {WHITE};
    gridline-color: {SLATE_100};
    border: none;
    alternate-background-color: {SLATE_50};
    selection-background-color: {INDIGO_L};
    selection-color: {SLATE_800};
    font-size: {fs}px;
    color: {SLATE_800};
}}
QTableWidget::item, QTableView::item {{
    padding: 11px 14px;
    border: none;
    border-bottom: 1px solid {SLATE_100};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {INDIGO_L};
    color: {INDIGO};
}}
QTableWidget::item:hover, QTableView::item:hover {{
    background: {SLATE_50};
}}
QHeaderView::section {{
    background: {SLATE_900};
    color: rgba(255,255,255,0.90);
    padding: 12px 14px;
    border: none;
    border-right: 1px solid rgba(255,255,255,0.08);
    font-size: {fs_sm}px;
    font-weight: 700;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}}
QHeaderView::section:first {{ border-top-left-radius: 10px; }}
QHeaderView::section:last  {{ border-right: none; border-top-right-radius: 10px; }}
QHeaderView::section:hover {{ background: {SLATE_800}; }}

/* ══ SCROLLBARS ══ */
QScrollBar:vertical {{
    background: transparent; width: 5px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {SLATE_300}; border-radius: 3px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: {SLATE_400}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 5px; border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {SLATE_300}; border-radius: 3px; min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: {SLATE_400}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ══ MENU ══ */
QMenu {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1px solid {SLATE_200};
    border-radius: 10px;
    padding: 6px 0;
    font-size: {fs}px;
}}
QMenu::item {{ padding: 9px 20px; background: transparent; border-radius: 5px; }}
QMenu::item:selected {{ background: {INDIGO_L}; color: {INDIGO}; }}
QMenu::separator {{ height: 1px; background: {SLATE_100}; margin: 4px 10px; }}

/* ══ CHECKBOX ══ */
QCheckBox, QRadioButton {{ color: {SLATE_800}; spacing: 8px; font-size: {fs}px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1.5px solid {SLATE_300};
    border-radius: 4px; background: {WHITE};
}}
QCheckBox::indicator:checked {{
    background: {INDIGO}; border-color: {INDIGO};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QRadioButton::indicator:checked {{ background: {INDIGO}; border-color: {INDIGO}; }}

/* ══ TOOLTIP ══ */
QToolTip {{
    background: {WHITE};
    color: {SLATE_900};
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: {fs_tip}px;
    font-weight: 600;
}}

/* ══ CALENDAR POPUP ══ */
QCalendarWidget {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1px solid {SLATE_200};
    border-radius: 10px;
}}
QCalendarWidget QWidget {{
    background: {WHITE};
    color: {SLATE_800};
    alternate-background-color: {SLATE_50};
}}
/* Navigation bar (month/year row) */
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {INDIGO};
    border-radius: 8px 8px 0 0;
    padding: 4px;
}}
QCalendarWidget QToolButton {{
    color: {WHITE};
    background: transparent;
    border: none;
    border-radius: 6px;
    font-weight: 700;
    font-size: {fs}px;
    padding: 4px 8px;
    min-width: 28px;
}}
QCalendarWidget QToolButton:hover {{
    background: {INDIGO_D};
}}
QCalendarWidget QSpinBox {{
    color: {WHITE};
    background: transparent;
    border: none;
    font-weight: 700;
    font-size: {fs}px;
}}
QCalendarWidget QSpinBox::up-button,
QCalendarWidget QSpinBox::down-button {{
    width: 0;
}}
/* Day-of-week header row — override the global dark QHeaderView::section rule */
QCalendarWidget QHeaderView::section {{
    background: {SLATE_100};
    color: {SLATE_600};
    border: none;
    border-bottom: 1px solid {SLATE_200};
    padding: 6px 0;
    font-size: {fs_sm}px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}
/* Date cells */
QCalendarWidget QAbstractItemView:enabled {{
    background: {WHITE};
    color: {SLATE_800};
    selection-background-color: {INDIGO};
    selection-color: {WHITE};
    outline: none;
    font-size: {fs}px;
}}
QCalendarWidget QAbstractItemView:disabled {{
    color: {SLATE_300};
}}

/* ══ PROGRESS BAR ══ */
QProgressBar {{
    background: {SLATE_100}; border: none;
    border-radius: 4px; height: 6px; color: transparent;
}}
QProgressBar::chunk {{
    background: {INDIGO}; border-radius: 3px;
}}

/* ══ LIST ══ */
QListWidget {{
    background: {WHITE}; border: 1px solid {SLATE_200};
    border-radius: 10px; font-size: {fs}px; color: {SLATE_800}; outline: none;
}}
QListWidget::item {{ padding: 9px 12px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {INDIGO_L}; color: {INDIGO}; }}
QListWidget::item:hover {{ background: {SLATE_50}; }}

/* ══ MESSAGE BOX ══ */
QMessageBox {{ background: {WHITE}; }}
QMessageBox QLabel {{ color: {SLATE_800}; font-size: {fs}px; min-width: 280px; }}
QMessageBox QPushButton {{
    background: {WHITE};
    color: {SLATE_900};
    border: 1px solid {SLATE_300};
    border-radius: 8px;
    padding: 8px 20px;
    min-width: 74px;
    min-height: 28px;
    font-size: {fs}px;
    font-weight: 800;
}}
QMessageBox QPushButton:hover {{
    background: {INDIGO_L};
    color: {INDIGO_D};
    border-color: {INDIGO};
}}
QMessageBox QPushButton:pressed {{
    background: {INDIGO};
    color: {WHITE};
    border-color: {INDIGO};
}}
QMessageBox QPushButton:disabled {{
    background: {SLATE_200};
    color: {SLATE_600};
}}

/* ══ SCROLL AREA ══ */
QScrollArea {{ background: {PAGE_BG}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {PAGE_BG}; }}
"""


def _calendar_local_css() -> str:
    """Local stylesheet applied directly on QCalendarWidget instances.
    Local stylesheets beat the global app stylesheet, so plain (un-prefixed)
    selectors here correctly override PAGE_BG / SLATE_900 global rules."""
    return f"""
QCalendarWidget {{
    background: {WHITE};
    border: 1px solid {SLATE_200};
    border-radius: 10px;
}}
QWidget {{
    background: {WHITE};
    color: {SLATE_800};
    alternate-background-color: {WHITE};
}}
QWidget#qt_calendar_navigationbar {{
    background: {INDIGO};
    border-radius: 8px 8px 0 0;
    padding: 4px;
}}
QToolButton {{
    color: {WHITE};
    background: transparent;
    border: none;
    border-radius: 6px;
    font-weight: 700;
    font-size: 13px;
    padding: 4px 8px;
    min-width: 28px;
}}
QToolButton:hover {{
    background: {INDIGO_D};
}}
QSpinBox {{
    color: {WHITE};
    background: transparent;
    border: none;
    font-weight: 700;
    font-size: 13px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}
QHeaderView {{
    background: {SLATE_100};
}}
QHeaderView::section {{
    background: {SLATE_100};
    color: {SLATE_600};
    border: none;
    border-bottom: 1px solid {SLATE_200};
    padding: 6px 0;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}
QAbstractItemView {{
    background: {WHITE};
    color: {SLATE_800};
    selection-background-color: {INDIGO};
    selection-color: {WHITE};
    alternate-background-color: {WHITE};
    outline: none;
    font-size: 13px;
}}
QAbstractItemView:disabled {{
    color: {SLATE_300};
}}
"""


class _CalendarStyleFilter:
    """Application-level event filter that styles every QCalendarWidget on show."""

    def __init__(self, css: str):
        self._css = css

    def eventFilter(self, obj, event):
        from PyQt5 import QtCore, QtWidgets
        if (
            event.type() == QtCore.QEvent.Show
            and isinstance(obj, QtWidgets.QCalendarWidget)
        ):
            obj.setStyleSheet(self._css)
            # Force the internal grid view with explicit selectors
            view = obj.findChild(QtWidgets.QAbstractItemView)
            if view:
                view.setStyleSheet(
                    f"QAbstractItemView {{ background:{WHITE}; color:{SLATE_800};"
                    f" alternate-background-color:{WHITE};"
                    f" selection-background-color:{INDIGO};"
                    f" selection-color:{WHITE}; }}"
                    f"QAbstractItemView:disabled {{ color:{SLATE_300}; }}"
                )
                vp = view.viewport()
                if vp:
                    vp.setStyleSheet(f"background:{WHITE};")
            # Force the day-of-week header to override the global dark QHeaderView rule
            header = obj.findChild(QtWidgets.QHeaderView)
            if header:
                header.setStyleSheet(
                    f"QHeaderView {{ background:{SLATE_100}; }}"
                    f"QHeaderView::section {{ background:{SLATE_100}; color:{SLATE_600};"
                    f" border:none; border-bottom:1px solid {SLATE_200};"
                    f" padding:6px 0; font-size:11px; font-weight:700; }}"
                )
        return False


_cal_filter_instance = None  # keep a reference so it isn't GC'd


def install_calendar_style_filter(app) -> None:
    """Call once after QApplication is created. Styles all calendar popups."""
    from PyQt5 import QtCore

    global _cal_filter_instance

    class _QObjFilter(QtCore.QObject):
        def __init__(self, delegate):
            super().__init__()
            self._d = delegate

        def eventFilter(self, obj, event):
            self._d.eventFilter(obj, event)
            return False  # never consume the event

    _cal_filter_instance = _QObjFilter(_CalendarStyleFilter(_calendar_local_css()))
    app.installEventFilter(_cal_filter_instance)


def add_shadow(widget, blur=24, x=0, y=4, color=(67, 97, 238, 20)):
    from PyQt5 import QtWidgets
    from PyQt5.QtGui import QColor
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(x, y)
    eff.setColor(QColor(*color))
    widget.setGraphicsEffect(eff)
    return widget
