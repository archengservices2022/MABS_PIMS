"""Executive dashboard for project, invoice, quote, and finance activity."""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from app_theme import add_shadow

log = logging.getLogger("pims.dashboard")


def _dashboard_cache_path() -> Path:
    try:
        from main import Config
        return Config.DATA_DIR / "dashboard_cache.json"
    except Exception:
        return Path.home() / ".pims_dashboard_cache.json"


def _save_dashboard_cache(data: dict) -> None:
    """Persist dashboard data to disk so next startup can render instantly."""
    try:
        path = _dashboard_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, default=str, ensure_ascii=False)
    except Exception as exc:
        log.debug("dashboard cache save failed: %s", exc)


def _load_dashboard_cache() -> dict | None:
    """Return last-saved dashboard data, or None if no cache exists."""
    try:
        path = _dashboard_cache_path()
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:
        log.debug("dashboard cache load failed: %s", exc)
    return None


class _LoaderSignals(QtCore.QObject):
    done = QtCore.pyqtSignal(dict)


class _DashboardLoader(QtCore.QRunnable):
    """Fetches all dashboard data in a thread pool so the UI stays responsive."""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.signals = _LoaderSignals()

    def run(self):
        result = {"invoices": [], "projects": [], "revenue": [], "quotes": []}

        def _load_invoices():
            try:
                from main import FirebaseManager
                return FirebaseManager.load_invoices() or []
            except Exception as e:
                log.warning("Dashboard loader (invoices): %s", e)
                return []

        def _load_projects():
            try:
                from main import FirebaseManager
                return FirebaseManager.load_projects() or []
            except Exception as e:
                log.warning("Dashboard loader (projects): %s", e)
                return []

        def _load_revenue():
            try:
                from balance_sheet_tab import BalanceSheetFirebaseManager
                return BalanceSheetFirebaseManager.load_revenue() or []
            except Exception as e:
                log.warning("Dashboard loader (revenue): %s", e)
                return []

        def _load_quotes():
            try:
                from main import FirebaseManager
                data = FirebaseManager.load_job_forms() or []
                if data:
                    return data
            except Exception as e:
                log.warning("Dashboard loader (quotes): %s", e)
            # fallback to cached tab data
            jt = getattr(self.main_window, "job_form_tab", None)
            return list(getattr(jt, "job_forms", None) or [])

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_load_invoices): "invoices",
                pool.submit(_load_projects): "projects",
                pool.submit(_load_revenue):  "revenue",
                pool.submit(_load_quotes):   "quotes",
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result[key] = future.result()
                except Exception as e:
                    log.warning("Dashboard loader (%s) failed: %s", key, e)

        log.info("Dashboard loaded — invoices:%d projects:%d revenue:%d quotes:%d",
                 len(result["invoices"]), len(result["projects"]),
                 len(result["revenue"]), len(result["quotes"]))
        self.signals.done.emit(result)

INDIGO = "#0F766E"
INDIGO_D = "#115E59"
INDIGO_L = "#ECFDF5"
VIOLET = "#2563EB"
CYAN = "#06B6D4"
EMERALD = "#10B981"
AMBER = "#F59E0B"
ROSE = "#F43F5E"

PAGE = "#F6F8FB"
WHITE = "#FFFFFF"
S50 = "#F8FAFC"
S100 = "#F1F5F9"
S200 = "#E2E8F0"
S400 = "#94A3B8"
S500 = "#64748B"
S600 = "#475569"
S700 = "#334155"
S800 = "#1E293B"
S900 = "#0F172A"

KPI_CONFIG = [
    ("#0F766E", "#2563EB", "Revenue This Month"),
    ("#B45309", "#DC2626", "Outstanding Invoices"),
    ("#2563EB", "#0F766E", "Active Quotes"),
    ("#059669", "#0F766E", "Active Projects"),
]


def _lbl(text, size=13, weight=400, color=S800, wrap=False):
    label = QtWidgets.QLabel(text)
    label.setStyleSheet(
        f"font-size:{size}px; font-weight:{weight}; color:{color};"
        " font-family:'Inter','Segoe UI',sans-serif; background:transparent; border:none;")
    label.setWordWrap(wrap)
    return label


def _card(radius=12):
    frame = QtWidgets.QFrame()
    frame.setStyleSheet(f"QFrame{{background:{WHITE}; border-radius:{radius}px; border:none;}}")
    add_shadow(frame, blur=22, x=0, y=4, color=(67, 97, 238, 16))
    return frame


def _action_btn(text, bg, hover, on_click):
    button = QtWidgets.QPushButton(text)
    button.setFixedHeight(36)
    button.setMinimumWidth(118)
    button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
    button.setStyleSheet(f"""
        QPushButton {{
            background:{bg};
            color:white;
            border:none;
            border-radius:8px;
            font-size:12px;
            font-weight:800;
            font-family:'Inter','Segoe UI';
            padding:0 14px;
        }}
        QPushButton:hover {{ background:{hover}; }}
    """)
    button.clicked.connect(on_click)
    return button


class KPICard(QtWidgets.QFrame):
    def __init__(self, g0, g1, title, value="0", sub="", parent=None):
        super().__init__(parent)
        self._g0 = g0
        self._g1 = g1
        self.setMinimumHeight(126)
        self.setStyleSheet("QFrame{border-radius:14px; border:none;}")
        add_shadow(self, blur=26, x=0, y=8, color=(67, 97, 238, 40))

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(9)

        self._title = QtWidgets.QLabel(title.upper())
        self._title.setStyleSheet(
            "font-size:10px; font-weight:800; color:rgba(255,255,255,0.72);"
            " letter-spacing:0.6px; font-family:'Inter','Segoe UI';"
            " background:transparent; border:none;")
        lay.addWidget(self._title)

        self._val = QtWidgets.QLabel(value)
        self._val.setStyleSheet(
            "font-size:32px; font-weight:900; color:#FFFFFF;"
            " font-family:'Inter','Segoe UI'; background:transparent; border:none;")
        lay.addWidget(self._val)

        self._sub = QtWidgets.QLabel(sub)
        self._sub.setStyleSheet(
            "font-size:11px; color:rgba(255,255,255,0.70);"
            " font-family:'Inter','Segoe UI'; background:transparent; border:none;")
        lay.addWidget(self._sub)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        grad = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QtGui.QColor(self._g0))
        grad.setColorAt(1, QtGui.QColor(self._g1))
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 14, 14)
        painter.fillPath(path, grad)
        shine = QtGui.QLinearGradient(0, 0, 0, self.height() * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 28))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)
        painter.end()
        super().paintEvent(event)

    def update_value(self, value, sub=""):
        self._val.setText(value)
        self._sub.setText(sub)


class BarChart(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._labels = []
        self._rev = []
        self._exp = []

    def set_data(self, labels, revenue, expenses):
        self._labels = labels
        self._rev = revenue
        self._exp = expenses
        self.update()

    def paintEvent(self, _):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if not self._labels:
            painter.setFont(QtGui.QFont("Inter", 12))
            painter.setPen(QtGui.QColor(S400))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No financial data yet")
            painter.end()
            return

        width, height = self.width(), self.height()
        pl, pr, pt, pb = 72, 18, 22, 36
        chart_h = height - pt - pb
        chart_w = width - pl - pr
        max_val = max(self._rev + self._exp) or 1
        group_w = chart_w / max(len(self._labels), 1)
        gap = 8
        bar_w = max(5, (group_w - gap * 3) / 2)

        painter.setPen(QtGui.QPen(QtGui.QColor(S200), 1, QtCore.Qt.DashLine))
        for idx in range(1, 5):
            y = pt + chart_h - int(chart_h * idx / 4)
            painter.drawLine(pl, y, width - pr, y)
            value = max_val * idx / 4
            painter.setPen(QtGui.QColor(S500))
            painter.setFont(QtGui.QFont("Inter", 8, QtGui.QFont.Bold))
            painter.drawText(QtCore.QRect(0, y - 9, pl - 8, 18), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, f"${value:,.0f}")
            painter.setPen(QtGui.QPen(QtGui.QColor(S200), 1, QtCore.Qt.DashLine))

        for idx, label in enumerate(self._labels):
            x = pl + idx * group_w + gap
            for offset, value, color0, color1 in (
                (0, self._rev[idx] if idx < len(self._rev) else 0, INDIGO, CYAN),
                (bar_w + gap, self._exp[idx] if idx < len(self._exp) else 0, AMBER, ROSE),
            ):
                bar_h = max(4, int((value / max_val) * chart_h)) if value else 4
                rect = QtCore.QRectF(x + offset, pt + chart_h - bar_h, bar_w, bar_h)
                path = QtGui.QPainterPath()
                path.addRoundedRect(rect, 5, 5)
                grad = QtGui.QLinearGradient(0, pt + chart_h - bar_h, 0, pt + chart_h)
                grad.setColorAt(0, QtGui.QColor(color0))
                grad.setColorAt(1, QtGui.QColor(color1))
                painter.fillPath(path, grad)
                if value:
                    painter.setPen(QtGui.QColor(S800))
                    painter.setFont(QtGui.QFont("Inter", 8, QtGui.QFont.Bold))
                    label_rect = QtCore.QRectF(x + offset - 18, pt + chart_h - bar_h - 18, bar_w + 36, 16)
                    painter.drawText(label_rect, QtCore.Qt.AlignCenter, f"${value:,.0f}")

            painter.setPen(QtGui.QColor(S500))
            painter.setFont(QtGui.QFont("Inter", 10))
            lx = int(pl + idx * group_w + group_w / 2)
            painter.drawText(QtCore.QRect(lx - 24, height - pb + 6, 48, 22), QtCore.Qt.AlignCenter, label)
        painter.end()


class ActivityItem(QtWidgets.QFrame):
    def __init__(self, badge, title, detail, ts, dot_color, on_click=None, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        if on_click:
            self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setStyleSheet(f"""
            QFrame {{ background:{WHITE}; border:none; border-bottom:1px solid {S100}; }}
            QFrame:hover {{ background:{S50}; }}
        """)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(18, 11, 18, 11)
        lay.setSpacing(14)

        avatar = QtWidgets.QLabel(badge)
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setStyleSheet(f"""
            QLabel {{
                background:{dot_color}1A;
                color:{dot_color};
                border-radius:18px;
                font-size:12px;
                font-weight:900;
                border:none;
            }}
        """)
        lay.addWidget(avatar)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(_lbl(title, 13, 700, S800))
        text_col.addWidget(_lbl(detail, 11, 500, S500))
        lay.addLayout(text_col, 1)

        badge_label = QtWidgets.QLabel(ts)
        badge_label.setStyleSheet(f"""
            QLabel {{
                background:{INDIGO_L};
                color:{INDIGO};
                border-radius:10px;
                padding:2px 10px;
                font-size:11px;
                font-weight:700;
                font-family:'Inter','Segoe UI';
                border:none;
            }}
        """)
        lay.addWidget(badge_label)

    def mousePressEvent(self, event):
        if self._on_click and event.button() == QtCore.Qt.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class InsightPill(QtWidgets.QFrame):
    def __init__(self, title, detail, color, parent=None):
        super().__init__(parent)
        self.setObjectName("InsightPill")
        self.setStyleSheet(f"""
            QFrame#InsightPill {{
                background:{WHITE};
                border:1px solid {S200};
                border-left:4px solid {color};
                border-radius:10px;
            }}
        """)
        self.setMinimumHeight(62)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Minimum,
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(3)
        lay.addWidget(_lbl(title, 12, 800, S800))
        detail_lbl = _lbl(detail, 11, 500, S500, wrap=True)
        detail_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred,
        )
        lay.addWidget(detail_lbl)


class DashboardTab(QtWidgets.QWidget):
    open_quotes = QtCore.pyqtSignal()
    open_invoices = QtCore.pyqtSignal()
    open_overdue_invoices = QtCore.pyqtSignal()
    open_projects = QtCore.pyqtSignal()
    open_expenses = QtCore.pyqtSignal()
    open_project_record = QtCore.pyqtSignal(object)
    open_invoice_record = QtCore.pyqtSignal(object)  # emitted when user clicks a specific invoice
    data_ready = QtCore.pyqtSignal()  # emitted once after first data load completes

    def __init__(self, main_window, firebase_available=False, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.FIREBASE_AVAILABLE = firebase_available
        self._invoices = []
        self._quotes = []
        self._projects = []
        self._revenue_records = []
        self._data_ready_emitted = False
        self.setStyleSheet(f"background:{PAGE}; border:none;")
        self._build()
        QtCore.QTimer.singleShot(0, self._initial_load)

        # Add real-time listeners for dashboard data
        QtCore.QTimer.singleShot(2000, self._setup_realtime_listeners)

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"background:{PAGE}; border:none;")

        body = QtWidgets.QWidget()
        body.setStyleSheet(f"background:{PAGE}; border:none;")
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(26, 18, 26, 26)
        body_lay.setSpacing(16)

        actions = QtWidgets.QFrame()
        actions.setStyleSheet(f"""
            QFrame {{
                background:{WHITE};
                border:1px solid {S200};
                border-radius:10px;
            }}
        """)
        actions_lay = QtWidgets.QHBoxLayout(actions)
        actions_lay.setContentsMargins(18, 14, 18, 14)
        actions_lay.setSpacing(12)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(2)
        self._greet = _lbl("Business Overview", 18, 900, S900)
        self._sub_lbl = _lbl("Quotes, invoices, projects, and cash flow at a glance.", 12, 600, S500)
        title_col.addWidget(self._greet)
        title_col.addWidget(self._sub_lbl)
        actions_lay.addLayout(title_col, 1)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)
        for text, bg, hover, signal in [
            ("New Quote", INDIGO, INDIGO_D, self.open_quotes.emit),
            ("New Invoice", EMERALD, "#059669", self.open_invoices.emit),
            ("Project", VIOLET, "#1D4ED8", self.open_projects.emit),
            ("Expense", AMBER, "#B45309", self.open_expenses.emit),
        ]:
            action_row.addWidget(_action_btn(text, bg, hover, signal))
        actions_lay.addLayout(action_row)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setFixedSize(96, 36)
        self.refresh_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self._refresh_btn_style = f"""
            QPushButton {{
                background:{WHITE};
                color:{INDIGO};
                border:1.5px solid {INDIGO};
                border-radius:8px;
                font-size:12px;
                font-weight:800;
                font-family:'Inter','Segoe UI';
            }}
            QPushButton:hover {{ background:{INDIGO_L}; }}
        """
        self._refresh_btn_busy_style = f"""
            QPushButton {{
                background:{INDIGO_L};
                color:{INDIGO};
                border:1.5px solid {INDIGO};
                border-radius:8px;
                font-size:12px;
                font-weight:800;
                font-family:'Inter','Segoe UI';
            }}
        """
        self.refresh_btn.setStyleSheet(self._refresh_btn_style)
        self.refresh_btn.clicked.connect(lambda: self.refresh(force_firebase=True))
        actions_lay.addWidget(self.refresh_btn)
        body_lay.addWidget(actions)

        kpi_row = QtWidgets.QHBoxLayout()
        kpi_row.setSpacing(16)
        self._kpis = []
        for g0, g1, title in KPI_CONFIG:
            card = KPICard(g0, g1, title)
            self._kpis.append(card)
            kpi_row.addWidget(card, 1)
        body_lay.addLayout(kpi_row)

        main_row = QtWidgets.QHBoxLayout()
        main_row.setSpacing(18)

        chart_card = _card(12)
        chart_card.setMinimumHeight(310)
        chart_lay = QtWidgets.QVBoxLayout(chart_card)
        chart_lay.setContentsMargins(24, 20, 24, 20)
        chart_lay.setSpacing(12)
        chart_header = QtWidgets.QHBoxLayout()
        chart_header.addWidget(_lbl("Revenue vs Expenses", 15, 800, S800))
        chart_header.addStretch()
        for color, label in ((INDIGO, "Revenue"), (AMBER, "Expenses")):
            dot = QtWidgets.QLabel("")
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{color}; border-radius:5px;")
            chart_header.addWidget(dot)
            chart_header.addWidget(_lbl(label, 12, 600, S500))
            chart_header.addSpacing(8)
        chart_lay.addLayout(chart_header)
        self._chart = BarChart()
        chart_lay.addWidget(self._chart, 1)
        main_row.addWidget(chart_card, 3)

        activity_card = _card(12)
        activity_card.setMinimumHeight(310)
        activity_lay = QtWidgets.QVBoxLayout(activity_card)
        activity_lay.setContentsMargins(0, 0, 0, 0)
        activity_lay.setSpacing(0)
        activity_header = QtWidgets.QWidget()
        activity_header.setStyleSheet(f"background:{WHITE}; border:none;")
        ah = QtWidgets.QHBoxLayout(activity_header)
        ah.setContentsMargins(20, 16, 20, 12)
        ah.addWidget(_lbl("Recent Activity", 15, 800, S800))
        ah.addStretch()
        activity_lay.addWidget(activity_header)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{S100}; border:none;")
        activity_lay.addWidget(line)
        self._act_scroll = QtWidgets.QScrollArea()
        self._act_scroll.setWidgetResizable(True)
        self._act_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._act_scroll.setStyleSheet(f"background:{WHITE}; border:none;")
        self._act_inner = QtWidgets.QWidget()
        self._act_inner.setStyleSheet(f"background:{WHITE}; border:none;")
        self._act_lay = QtWidgets.QVBoxLayout(self._act_inner)
        self._act_lay.setContentsMargins(0, 0, 0, 0)
        self._act_lay.setSpacing(0)
        self._act_lay.addStretch()
        self._act_scroll.setWidget(self._act_inner)
        activity_lay.addWidget(self._act_scroll, 1)
        main_row.addWidget(activity_card, 2)
        body_lay.addLayout(main_row)

        self._insights_card = _card(12)
        self._insights_card.setMinimumHeight(140)
        self._insights_card.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Minimum,
        )
        insights_lay = QtWidgets.QVBoxLayout(self._insights_card)
        insights_lay.setContentsMargins(22, 18, 22, 20)
        insights_lay.setSpacing(12)
        insights_lay.addWidget(_lbl("Automation Insights", 15, 800, S800))
        self._insights_lay = QtWidgets.QVBoxLayout()
        self._insights_lay.setSpacing(10)
        insights_lay.addLayout(self._insights_lay)
        body_lay.addWidget(self._insights_card)

        self._ov = QtWidgets.QFrame()
        self._ov.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #FFF1F2, stop:1 #FFFBEB);
                border: 1px solid #FECDD3;
                border-left: 4px solid {ROSE};
                border-radius: 10px;
            }}
        """)
        ov_lay = QtWidgets.QHBoxLayout(self._ov)
        ov_lay.setContentsMargins(20, 14, 20, 14)
        ov_lay.setSpacing(14)
        ov_lay.addWidget(_lbl("!", 20, 900, ROSE))
        self._ov_lbl = _lbl("", 13, 700, "#9F1239", wrap=True)
        ov_lay.addWidget(self._ov_lbl, 1)
        view_btn = QtWidgets.QPushButton("View Invoices")
        view_btn.setFixedHeight(34)
        view_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        view_btn.setStyleSheet(f"""
            QPushButton {{
                background:{ROSE};
                color:white;
                border:none;
                border-radius:8px;
                font-size:12px;
                font-weight:800;
                font-family:'Inter','Segoe UI';
                padding:0 16px;
            }}
            QPushButton:hover {{ background:#E11D48; }}
        """)
        view_btn.clicked.connect(self.open_overdue_invoices.emit)
        ov_lay.addWidget(view_btn)
        self._ov.setVisible(False)
        body_lay.addWidget(self._ov)

        body_lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)

    @staticmethod
    def _greeting():
        hour = datetime.now().hour
        if hour < 12:
            return "Good Morning"
        if hour < 17:
            return "Good Afternoon"
        return "Good Evening"

    def refresh(self, force_firebase=False):
        """Update dashboard. Reads from tab caches by default; uses background
        Firebase fetch only when force_firebase=True (manual/auto refresh)."""
        if force_firebase:
            self._sub_lbl.setText("Refreshing...")
            if hasattr(self, "refresh_btn"):
                self.refresh_btn.setEnabled(False)
                self.refresh_btn.setText("Refreshing...")
                self.refresh_btn.setStyleSheet(self._refresh_btn_busy_style)
            QtWidgets.QApplication.processEvents()
            worker = _DashboardLoader(self.main_window)
            worker.signals.done.connect(self._on_data_loaded)
            QtCore.QThreadPool.globalInstance().start(worker)
        else:
            self._load_from_cache()
            self._render()

    def _load_from_cache(self):
        """Read data already loaded by individual tabs — no Firebase calls."""
        mw = self.main_window
        cutoff = datetime.now() - timedelta(days=30)

        # Invoices — from FirebaseManager in-memory cache (no new network request)
        try:
            from main import FirebaseManager
            cache = FirebaseManager._invoices_cache
            if cache is not None:  # None means never fetched; keep existing self._invoices
                self._invoices = list(cache)
        except Exception:
            pass

        # Projects — from project tab cache only
        all_projects = list(getattr(getattr(mw, "project_tab", None), "generated_projects", None) or [])
        self._all_projects = all_projects
        self._projects = [
            p for p in all_projects
            if self._within_30_days(p.get("created_at") or p.get("updated_at", ""), cutoff)
        ]

        # Revenue — from balance_sheet_tab cache only
        try:
            bst = getattr(mw, "balance_sheet_tab", None)
            self._revenue_records = list(getattr(bst, "revenue_data", None) or [])
        except Exception:
            self._revenue_records = []
        if not self._revenue_records:
            self._revenue_records = [inv.get("meta", inv) for inv in self._invoices]

        # Quotes — from tab cache only
        jt = getattr(mw, "job_form_tab", None)
        self._quotes = list(getattr(jt, "job_forms", None) or [])

    def _initial_load(self):
        """Show last-session cache instantly, then silently refresh from Firebase."""
        cached = _load_dashboard_cache()
        if cached:
            # Render previous session's data right now — zero network wait
            self._on_data_loaded(cached, _save=False)
        # Fetch fresh Firebase data in background; updates display when it arrives
        worker = _DashboardLoader(self.main_window)
        worker.signals.done.connect(self._on_data_loaded)
        QtCore.QThreadPool.globalInstance().start(worker)

    def _setup_realtime_listeners(self):
        """Set up real-time listeners for dashboard data"""
        try:
            from main import FirebaseManager
            FirebaseManager.add_invoices_listener(self._on_invoices_updated)
            FirebaseManager.add_projects_listener(self._on_projects_updated)
            FirebaseManager.add_quotes_listener(self._on_quotes_updated)
            FirebaseManager.add_balance_sheet_listener(self._on_balance_updated)
        except Exception:
            pass

    def _on_invoices_updated(self, data):
        """Called when invoices are updated"""
        try:
            QtCore.QTimer.singleShot(300, self._initial_load)
        except Exception as e:
            log.warning("Error updating dashboard invoices: %s", e)

    def _on_projects_updated(self, data):
        """Called when projects are updated"""
        try:
            QtCore.QTimer.singleShot(300, self._initial_load)
        except Exception as e:
            log.warning("Error updating dashboard projects: %s", e)

    def _on_quotes_updated(self, data):
        """Called when quotes are updated"""
        try:
            QtCore.QTimer.singleShot(300, self._initial_load)
        except Exception as e:
            log.warning("Error updating dashboard quotes: %s", e)

    def _on_balance_updated(self, data):
        """Called when balance sheet data is updated"""
        try:
            QtCore.QTimer.singleShot(300, self._initial_load)
        except Exception as e:
            log.warning("Error updating dashboard balance: %s", e)

    def _on_data_loaded(self, data: dict, *, _save: bool = True):
        """Receives results from background Firebase thread and updates UI."""
        cutoff = datetime.now() - timedelta(days=30)
        self._invoices = data.get("invoices", [])
        all_projects = data.get("projects", [])
        # Keep all projects for KPI count; use 30-day window only for recent activity feed
        self._all_projects = all_projects
        self._projects = [
            p for p in all_projects
            if self._within_30_days(p.get("created_at") or p.get("updated_at", ""), cutoff)
        ]
        self._revenue_records = data.get("revenue", []) or [inv.get("meta", inv) for inv in self._invoices]
        self._quotes = data.get("quotes", [])
        if not self._quotes:
            jt = getattr(self.main_window, "job_form_tab", None)
            self._quotes = list(getattr(jt, "job_forms", None) or [])
        self._render()
        if not self._data_ready_emitted:
            self._data_ready_emitted = True
            self.data_ready.emit()
        if _save and (self._invoices or self._projects or self._revenue_records or self._quotes):
            threading.Thread(target=_save_dashboard_cache, args=(data,), daemon=True).start()

    def _render(self):
        self._update_kpis()
        self._update_chart()
        self._update_activity()
        self._update_overdue()
        self._update_insights()
        self._sub_lbl.setText(f"Last updated {datetime.now().strftime('%I:%M %p')}")
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("Refresh")
            self.refresh_btn.setStyleSheet(self._refresh_btn_style)

    def _within_30_days(self, ts: str, cutoff: datetime) -> bool:
        """Return True if the ISO timestamp string is on or after cutoff."""
        if not ts:
            return False
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            return dt_naive >= cutoff
        except Exception:
            return False

    def _money_to_float(self, value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").strip()
            try:
                return float(cleaned) if cleaned else 0.0
            except ValueError:
                return 0.0
        return 0.0

    def _record_amount(self, record: dict) -> float:
        for key in ("amount", "total_amount", "total", "payment_due"):
            if key in record:
                amount = self._money_to_float(record.get(key))
                if amount:
                    return amount
        return 0.0

    def _record_date(self, record: dict):
        for key in ("date", "invoice_date", "received_date", "expense_date", "created_at"):
            text = str(record.get(key, "") or "").strip()
            if not text or text == "N/A":
                continue
            iso_text = text[:10]
            for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%B %d, %Y"):
                try:
                    return datetime.strptime(iso_text if fmt == "%Y-%m-%d" else text, fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(text[:19])
            except ValueError:
                continue
        return None

    def _current_revenue_records(self):
        return self._revenue_records or [inv.get("meta", inv) for inv in self._invoices]

    def _current_expense_records(self):
        balance_tab = getattr(self.main_window, "balance_sheet_tab", None)
        records = list(getattr(balance_tab, "expenses_data", None) or getattr(balance_tab, "annual_expenses_data", None) or [])
        if records:
            return records

        try:
            from balance_sheet_tab import BalanceSheetFirebaseManager
            records = BalanceSheetFirebaseManager.load_expenses() or []
        except Exception:
            records = []

        if records:
            return records

        expenses_tab = getattr(self.main_window, "expenses_tab", None)
        return list(getattr(expenses_tab, "expenses", []) or [])

    def _update_kpis(self):
        now = datetime.now()
        revenue = 0.0
        outstanding = 0
        for record in self._current_revenue_records():
            date = self._record_date(record)
            status = record.get("status", "")
            if status in ("Unpaid", "Overdue", "Pending"):
                continue
            if date and date.month == now.month and date.year == now.year:
                revenue += self._record_amount(record)

        from status_enums import InvoiceStatus
        for inv in self._invoices:
            meta = inv.get("meta", inv)
            if meta.get("status", InvoiceStatus.UNPAID) in InvoiceStatus.OPEN:
                outstanding += 1

        from status_enums import QuoteStatus, ProjectStatus
        active_quotes = len([q for q in self._quotes if q.get("status") not in QuoteStatus.INACTIVE])
        _all_proj = getattr(self, "_all_projects", self._projects)
        active_projects = len([p for p in _all_proj if p.get("status") not in ProjectStatus.INACTIVE])
        self._kpis[0].update_value(f"${revenue:,.0f}", f"Month of {now.strftime('%B %Y')}")
        self._kpis[1].update_value(str(outstanding), "Need follow-up")
        self._kpis[2].update_value(str(active_quotes), f"{len(self._quotes)} total")
        self._kpis[3].update_value(str(active_projects), f"{len(_all_proj)} total")

    def _update_chart(self):
        now = datetime.now()
        months = []
        revenue_months = defaultdict(float)
        expense_months = defaultdict(float)
        for idx in range(5, -1, -1):
            month_index = now.year * 12 + now.month - 1 - idx
            year = month_index // 12
            month = month_index % 12 + 1
            months.append((f"{year}-{month:02d}", datetime(year, month, 1).strftime("%b")))

        for record in self._current_revenue_records():
            date = self._record_date(record)
            if date:
                revenue_months[date.strftime("%Y-%m")] += self._record_amount(record)

        for expense in self._current_expense_records():
            date = self._record_date(expense)
            if date:
                expense_months[date.strftime("%Y-%m")] += self._record_amount(expense)

        self._chart.set_data(
            [label for _key, label in months],
            [revenue_months.get(key, 0) for key, _label in months],
            [expense_months.get(key, 0) for key, _label in months],
        )

    def _update_activity(self):
        while self._act_lay.count() > 1:
            item = self._act_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        events = []
        for quote in self._quotes:
            ts = quote.get("updated_at") or quote.get("created_at", "")
            if ts:
                events.append((ts, "Q", INDIGO, f"Quote {quote.get('job_number', '')}",
                               f"{quote.get('project_name', '-')} - {quote.get('client', '-')}", quote))
        for inv in self._invoices:
            meta = inv.get("meta", inv)
            ts = meta.get("updated_at") or meta.get("created_at", "")
            if ts:
                events.append((ts, "I", EMERALD, f"Invoice {meta.get('invoice_number', '')}",
                               f"{meta.get('client_name', '-')} - {meta.get('status', '-')}", inv))
        for project in self._projects:
            ts = project.get("updated_at") or project.get("created_at", "")
            if ts:
                events.append((ts, "P", VIOLET, f"Project {project.get('project_number', '')}",
                               f"{project.get('project_name', '-')} - {project.get('status', '-')}", project))

        events.sort(key=lambda item: item[0], reverse=True)
        if not events:
            empty = _lbl("No activity yet. Start by creating a quote.", 13, 500, S400)
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setContentsMargins(0, 30, 0, 30)
            self._act_lay.insertWidget(0, empty)
            return

        for ts, badge, color, title, detail, record in events[:10]:
            on_click = None
            if badge == "P":
                on_click = lambda rec=record: self.open_project_record.emit(rec)
            elif badge == "Q":
                on_click = self.open_quotes.emit
            elif badge == "I":
                on_click = lambda rec=record: self.open_invoice_record.emit(rec)
            self._act_lay.insertWidget(
                self._act_lay.count() - 1,
                ActivityItem(badge, title, detail, self._fmt(ts), color, on_click),
            )

    def _update_overdue(self):
        overdue = [inv for inv in self._invoices if inv.get("meta", inv).get("status") == "Overdue"]
        if overdue:
            self._ov_lbl.setText(f"Action required: {len(overdue)} invoice(s) are overdue and need attention.")
            self._ov.setVisible(True)
        else:
            self._ov.setVisible(False)

    def _update_insights(self):
        while self._insights_lay.count():
            item = self._insights_lay.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
                w.deleteLater()

        from status_enums import InvoiceStatus, QuoteStatus, ProjectStatus
        now = datetime.now()
        stale_cutoff = now.timestamp() - QuoteStatus.STALE_DAYS * 86400

        outstanding = [inv for inv in self._invoices if inv.get("meta", inv).get("status", InvoiceStatus.UNPAID) in InvoiceStatus.OPEN]

        stale_quotes = []
        for q in self._quotes:
            if q.get("status") in QuoteStatus.INACTIVE:
                continue
            created_raw = q.get("created_at") or q.get("updated_at", "")
            try:
                created_ts = datetime.fromisoformat(str(created_raw).replace("Z", "")).timestamp()
                if created_ts < stale_cutoff:
                    stale_quotes.append(q)
            except Exception:
                pass  # If no valid date, skip from stale list

        _all_proj = getattr(self, "_all_projects", self._projects)
        active_projects = [p for p in _all_proj if p.get("status") not in ProjectStatus.INACTIVE]

        insights = []
        if outstanding:
            amount = sum(self._record_amount(inv.get("meta", inv)) for inv in outstanding)
            insights.append(("Collect faster", f"{len(outstanding)} open invoice(s), about ${amount:,.0f} outstanding.", ROSE))
        if stale_quotes:
            insights.append(("Convert quotes", f"{len(stale_quotes)} quote(s) haven't moved in 30+ days. Follow up before they go cold.", INDIGO))
        if active_projects:
            insights.append(("Keep projects moving", f"{len(active_projects)} active project(s) are available for invoice auto-fill.", EMERALD))
        if not insights:
            insights.append(("All clear", "No urgent automation recommendations right now.", EMERALD))

        for title, detail, color in insights[:3]:
            self._insights_lay.addWidget(InsightPill(title, detail, color))
        self._insights_card.updateGeometry()

    @staticmethod
    def _fmt(ts):
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone().replace(tzinfo=None)
            delta = datetime.now() - dt
            if delta.total_seconds() < 0:
                if delta.total_seconds() > -300:
                    return "Just now"
                return dt.strftime("%b %d")
            if delta.days == 0:
                minutes = int(delta.seconds / 60)
                if minutes < 1:
                    return "Just now"
                if minutes < 60:
                    return f"{minutes}m ago"
                return f"{minutes // 60}h ago"
            if delta.days == 1:
                return "Yesterday"
            if delta.days < 7:
                return f"{delta.days}d ago"
            return dt.strftime("%b %d")
        except Exception:
            return ""
