from datetime import datetime
from decimal import Decimal

from PyQt5 import QtWidgets, QtCore, QtGui

from app_logger import get_logger

_log = get_logger(__name__)

try:
    import firebase_admin
    from firebase_admin import db
    FIREBASE_AVAILABLE = True
except ImportError:
    firebase_admin = None
    db = None
    FIREBASE_AVAILABLE = False


class FinanceOverviewTab(QtWidgets.QWidget):
    """Executive finance overview driven by invoices, revenue, expenses, and salary."""

    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.current_year = datetime.now().year
        self.cards = {}
        self._build_ui()
        self.refresh_data()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QtWidgets.QFrame()
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0f3f56, stop:0.55 #0f766e, stop:1 #1e293b);
                border-radius: 10px;
            }
        """)
        header_lay = QtWidgets.QHBoxLayout(header)
        header_lay.setContentsMargins(24, 18, 24, 18)
        header_lay.setSpacing(12)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)
        title = QtWidgets.QLabel("Finance Overview")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-family: 'Inter', 'Segoe UI';
                font-size: 24px;
                font-weight: 900;
                background: transparent;
                border: none;
            }
        """)
        subtitle = QtWidgets.QLabel("Automated business health from invoices, expenses, payroll, and cash received")
        subtitle.setStyleSheet("""
            QLabel {
                color: #d9f4ef;
                font-family: 'Inter', 'Segoe UI';
                font-size: 13px;
                font-weight: 600;
                background: transparent;
                border: none;
            }
        """)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_lay.addLayout(title_col)
        header_lay.addStretch()

        self.sync_label = QtWidgets.QLabel("Auto-sync ready")
        self.sync_label.setAlignment(QtCore.Qt.AlignCenter)
        self.sync_label.setStyleSheet("""
            QLabel {
                color: #064e3b;
                background: #ecfdf5;
                border: 1px solid #99f6e4;
                border-radius: 15px;
                padding: 6px 14px;
                font-family: 'Inter', 'Segoe UI';
                font-size: 12px;
                font-weight: 800;
            }
        """)
        header_lay.addWidget(self.sync_label)
        root.addWidget(header)

        cards_grid = QtWidgets.QGridLayout()
        cards_grid.setSpacing(12)
        card_specs = [
            ("cash_received", "Cash Received", "$0.00", "#047857", "#ecfdf5"),
            ("unpaid_revenue", "Unpaid Revenue", "$0.00", "#d97706", "#fffbeb"),
            ("expenses", "Expenses", "$0.00", "#dc2626", "#fff1f2"),
            ("salary", "Payroll", "$0.00", "#2563eb", "#eff6ff"),
            ("net_profit", "Net Profit/Loss", "$0.00", "#0f766e", "#ecfdf5"),
            ("unpaid_invoices", "Unpaid Invoices", "0", "#7c3aed", "#f5f3ff"),
        ]
        for index, (key, label, value, accent, bg) in enumerate(card_specs):
            card, value_label = self._create_metric_card(label, value, accent, bg)
            self.cards[key] = value_label
            cards_grid.addWidget(card, index // 3, index % 3)
        root.addLayout(cards_grid)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        self.summary_panel = self._create_summary_panel()
        self.action_panel = self._create_action_panel()
        body.addWidget(self.summary_panel, 2)
        body.addWidget(self.action_panel, 1)
        root.addLayout(body, 1)

    def _create_metric_card(self, title, value, accent, bg):
        card = QtWidgets.QFrame()
        card.setMinimumHeight(118)
        card.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1px solid #d8e2ec;
                border-left: 6px solid {accent};
                border-radius: 8px;
            }}
        """)
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                color: #475569;
                font-family: 'Inter', 'Segoe UI';
                font-size: 13px;
                font-weight: 800;
            }
        """)
        value_label = QtWidgets.QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {accent};
                font-family: 'Inter', 'Segoe UI';
                font-size: 28px;
                font-weight: 900;
            }}
        """)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch()
        return card, value_label

    def _create_summary_panel(self):
        panel = QtWidgets.QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #d8e2ec;
                border-radius: 8px;
            }
        """)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QtWidgets.QLabel("Automated Summary")
        title.setStyleSheet("font: 900 17px 'Inter', 'Segoe UI'; color: #0f172a; background: transparent; border: none;")
        layout.addWidget(title)
        self.summary_text = QtWidgets.QLabel()
        self.summary_text.setWordWrap(True)
        self.summary_text.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                color: #334155;
                font-family: 'Inter', 'Segoe UI';
                font-size: 14px;
                line-height: 1.35;
            }
        """)
        layout.addWidget(self.summary_text)
        layout.addStretch()
        return panel

    def _create_action_panel(self):
        panel = QtWidgets.QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #d8e2ec;
                border-radius: 8px;
            }
        """)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QtWidgets.QLabel("Quick Actions")
        title.setStyleSheet("font: 900 17px 'Inter', 'Segoe UI'; color: #0f172a; background: transparent; border: none;")
        layout.addWidget(title)

        refresh_btn = self._action_button("Refresh Finance Now", "#00756f")
        refresh_btn.clicked.connect(lambda: self.refresh_data(auto=False))
        layout.addWidget(refresh_btn)

        expenses_btn = self._action_button("Open Expenses", "#2563eb")
        expenses_btn.clicked.connect(lambda: self._select_finance_tab("Expenses"))
        layout.addWidget(expenses_btn)

        balance_btn = self._action_button("Open Balance Sheet", "#334155")
        balance_btn.clicked.connect(lambda: self._select_finance_tab("Balance Sheet"))
        layout.addWidget(balance_btn)
        layout.addStretch()
        return panel

    def _action_button(self, text, color):
        btn = QtWidgets.QPushButton(text)
        btn.setFixedHeight(44)
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                color: white;
                border: none;
                border-radius: 8px;
                font-family: 'Inter', 'Segoe UI';
                font-size: 14px;
                font-weight: 900;
            }}
            QPushButton:hover {{ background: #0f766e; }}
        """)
        return btn

    def refresh_data(self, auto=False):
        metrics = self._collect_metrics()
        self.cards["cash_received"].setText(self._money(metrics["cash_received"]))
        self.cards["unpaid_revenue"].setText(self._money(metrics["unpaid_revenue"]))
        self.cards["expenses"].setText(self._money(metrics["expenses"]))
        self.cards["salary"].setText(self._money(metrics["salary"]))
        self.cards["net_profit"].setText(self._money(metrics["net_profit"]))
        self.cards["unpaid_invoices"].setText(str(metrics["unpaid_invoice_count"]))
        self._update_summary(metrics)
        label = "Auto-synced" if auto else "Synced"
        self.sync_label.setText(datetime.now().strftime(f"{label} %I:%M %p"))

    def _collect_metrics(self):
        invoices = self._load_node("invoices")
        revenue = self._load_node("revenue")
        expenses = self._load_node("balance_sheet_expenses")
        salary = self._load_node("salary")

        cash_received = 0.0
        unpaid_revenue = 0.0
        unpaid_invoice_count = 0
        for invoice in invoices:
            meta = invoice.get("meta", invoice)
            status = str(meta.get("status", "")).lower()
            amount = self._amount(meta.get("total_amount", meta.get("total", meta.get("amount", 0))))
            if status == "paid":
                cash_received += amount
            else:
                unpaid_revenue += amount
                unpaid_invoice_count += 1

        for rev in revenue:
            if rev.get("is_invoice"):
                status = str(rev.get("status", "")).lower()
                if status == "paid":
                    cash_received += self._amount(rev.get("amount", 0))
                elif status == "partially paid":
                    cash_received += self._amount(rev.get("paid_amount", rev.get("down_payment_amount", 0)))
                    unpaid_revenue += self._amount(rev.get("unpaid_amount", rev.get("amount", 0)))
                    unpaid_invoice_count += 1
                elif not invoices:
                    unpaid_revenue += self._amount(rev.get("amount", 0))
                    unpaid_invoice_count += 1
                continue
            status = str(rev.get("status", "")).lower()
            amount = self._amount(rev.get("amount", 0))
            if status == "paid":
                cash_received += amount
            elif status == "partially paid":
                cash_received += self._amount(rev.get("paid_amount", 0))
                unpaid_revenue += self._amount(rev.get("unpaid_amount", amount))
            else:
                unpaid_revenue += amount

        expense_total = sum(self._amount(item.get("amount", 0)) for item in expenses)
        salary_total = 0.0
        for item in salary:
            if isinstance(item, dict):
                salary_total += self._amount(item.get("amount", 0))

        return {
            "cash_received": cash_received,
            "unpaid_revenue": unpaid_revenue,
            "expenses": expense_total,
            "salary": salary_total,
            "net_profit": cash_received - expense_total - salary_total,
            "unpaid_invoice_count": unpaid_invoice_count,
        }

    def _load_node(self, node):
        if not FIREBASE_AVAILABLE or db is None:
            return []
        try:
            data = db.reference(node).get() or {}
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            if isinstance(data, dict):
                if node == "salary":
                    rows = []
                    for value in data.values():
                        if isinstance(value, dict) and ("amount" in value or "region" in value):
                            rows.append(value)
                        elif isinstance(value, list):
                            rows.extend([item for item in value if isinstance(item, dict)])
                    return rows
                return [value for value in data.values() if isinstance(value, dict)]
        except Exception as exc:
            _log.warning("Finance overview failed to load %s: %s", node, exc)
        return []

    def _update_summary(self, metrics):
        net = metrics["net_profit"]
        tone = "positive" if net >= 0 else "negative"
        result = "profitable" if net >= 0 else "running at a loss"
        self.summary_text.setText(
            f"This year currently looks {result} based on received cash. "
            f"Cash received is {self._money(metrics['cash_received'])}, while expenses and payroll total "
            f"{self._money(metrics['expenses'] + metrics['salary'])}. "
            f"There are {metrics['unpaid_invoice_count']} unpaid invoice(s) representing "
            f"{self._money(metrics['unpaid_revenue'])} still outstanding."
        )
        color = "#047857" if tone == "positive" else "#dc2626"
        self.cards["net_profit"].setStyleSheet(f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {color};
                font-family: 'Inter', 'Segoe UI';
                font-size: 28px;
                font-weight: 900;
            }}
        """)

    def _select_finance_tab(self, tab_name):
        if self.main_window and hasattr(self.main_window, "finance_inner_tabs"):
            tabs = self.main_window.finance_inner_tabs
            for index in range(tabs.count()):
                if tabs.tabText(index) == tab_name:
                    tabs.setCurrentIndex(index)
                    return

    def _amount(self, value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace("$", "").replace(",", "").strip() or 0)
            except ValueError:
                return 0.0
        return 0.0

    def _money(self, value):
        return f"${value:,.2f}"
