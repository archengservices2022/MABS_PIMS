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
PAGE_BG    = "#F6F8FB"    # neutral enterprise background
CHEVRON_URL = (Path(__file__).resolve().parent / "assets" / "icons" / "chevron-down.svg").as_posix()
CHEVRON_WHITE_URL = (Path(__file__).resolve().parent / "assets" / "icons" / "chevron-down-white.svg").as_posix()


def clean_dropdown_stylesheet() -> str:
    """Shared clean dropdown and spinner styling."""
    return f"""
QComboBox, QDateEdit {{
    padding-right: 44px;
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 38px;
    border: none;
    border-left: 1px solid #0B6B66;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background: {INDIGO};
}}
QComboBox::drop-down:hover, QDateEdit::drop-down:hover {{
    background: {INDIGO_D};
    border-left: 1px solid {INDIGO_D};
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url("{CHEVRON_WHITE_URL}");
    width: 12px;
    height: 12px;
    margin-right: 13px;
}}
QComboBox::down-arrow:on, QDateEdit::down-arrow:on {{
    top: 1px;
}}
QComboBox QAbstractItemView {{
    background: {WHITE};
    color: {SLATE_800};
    border: 1px solid #BFD7D5;
    border-radius: 10px;
    selection-background-color: #DDF7F3;
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
    background: {SLATE_100};
    color: {SLATE_900};
}}
QComboBox QAbstractItemView::item:selected {{
    background: #DDF7F3;
    color: {INDIGO_D};
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
                    border: 1px solid #8FC5BF;
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
                    background: #F1F8F7;
                    color: {SLATE_900};
                }}
                QListView::item:selected {{
                    background: #DDF7F3;
                    color: {INDIGO_D};
                    font-weight: 800;
                    border: none;
                }}
                QScrollBar:vertical {{
                    width: 8px;
                    background: transparent;
                    margin: 8px 2px 8px 0;
                }}
                QScrollBar::handle:vertical {{
                    background: #9BCBC6;
                    border-radius: 4px;
                    min-height: 24px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background: {INDIGO};
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
    return f"""

/* ══ FOUNDATION ══ */
* {{ font-family: 'Inter', 'Segoe UI', 'Arial', sans-serif; outline: none; }}

QMainWindow, QDialog, QWidget {{
    background: {PAGE_BG};
    color: {SLATE_800};
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
    min-height: 24px;
}}
QComboBox:focus {{ border-color: {INDIGO}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {SLATE_400};
    margin-right: 6px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 11px;
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
    font-size: 13px;
}}
QMenu::item {{ padding: 9px 20px; background: transparent; border-radius: 5px; }}
QMenu::item:selected {{ background: {INDIGO_L}; color: {INDIGO}; }}
QMenu::separator {{ height: 1px; background: {SLATE_100}; margin: 4px 10px; }}

/* ══ CHECKBOX ══ */
QCheckBox, QRadioButton {{ color: {SLATE_800}; spacing: 8px; font-size: 13px; }}
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
    font-size: 12px;
    font-weight: 600;
}}

/* ══ CALENDAR POPUP ══ */
QCalendarWidget {{
    background: {WHITE};
    color: {SLATE_800};
}}
QCalendarWidget QWidget {{
    background: {WHITE};
    color: {SLATE_800};
    alternate-background-color: #F8FAFC;
}}
QCalendarWidget QToolButton {{
    color: {SLATE_900};
    background: {WHITE};
    border: none;
    font-weight: 700;
}}
QCalendarWidget QToolButton:hover {{
    background: #F1F5F9;
    border-radius: 6px;
}}
QCalendarWidget QSpinBox {{
    color: {SLATE_900};
    background: {WHITE};
    border: 1px solid #E2E8F0;
    border-radius: 4px;
}}
QCalendarWidget QAbstractItemView {{
    background: {WHITE};
    color: {SLATE_900};
    selection-background-color: #0F766E;
    selection-color: {WHITE};
}}
QCalendarWidget QAbstractItemView:disabled {{
    color: #94A3B8;
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
    border-radius: 10px; font-size: 13px; color: {SLATE_800}; outline: none;
}}
QListWidget::item {{ padding: 9px 12px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {INDIGO_L}; color: {INDIGO}; }}
QListWidget::item:hover {{ background: {SLATE_50}; }}

/* ══ MESSAGE BOX ══ */
QMessageBox {{ background: {WHITE}; }}
QMessageBox QLabel {{ color: {SLATE_800}; font-size: 13px; min-width: 280px; }}
QMessageBox QPushButton {{
    background: {WHITE};
    color: {SLATE_900};
    border: 1px solid {SLATE_300};
    border-radius: 8px;
    padding: 8px 20px;
    min-width: 74px;
    min-height: 28px;
    font-size: 13px;
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


def add_shadow(widget, blur=24, x=0, y=4, color=(67, 97, 238, 20)):
    from PyQt5 import QtWidgets
    from PyQt5.QtGui import QColor
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(x, y)
    eff.setColor(QColor(*color))
    widget.setGraphicsEffect(eff)
    return widget
