from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
import uuid

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


class EmployeeAdvanceTab(QtWidgets.QWidget):
    """Employee Advance Entry and Management Tab"""

    advance_updated = QtCore.pyqtSignal()

    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.advances_data = {}
        self.employees = {}
        self.current_advance_id = None
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        """Build the UI layout"""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header
        header = QtWidgets.QFrame()
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0f3f56, stop:0.55 #0f766e, stop:1 #1e293b);
                border-radius: 8px;
            }
        """)
        header_lay = QtWidgets.QHBoxLayout(header)
        header_lay.setContentsMargins(20, 16, 20, 16)
        header_lay.setSpacing(12)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(3)
        title = QtWidgets.QLabel("Employee Advance Entry")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-family: 'Inter', 'Segoe UI';
                font-size: 22px;
                font-weight: 900;
                background: transparent;
                border: none;
            }
        """)
        title_col.addWidget(title)
        header_lay.addLayout(title_col)
        header_lay.addStretch()
        root.addWidget(header)

        # Main content area with splitter
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: #e5e7eb;
                margin: 2px 0px 2px 0px;
            }
        """)

        # Form Section
        form_widget = QtWidgets.QWidget()
        form_lay = QtWidgets.QVBoxLayout(form_widget)
        form_lay.setContentsMargins(0, 0, 0, 0)
        form_lay.setSpacing(10)

        form_title = QtWidgets.QLabel("New Advance Entry")
        form_title.setStyleSheet("""
            QLabel {
                color: #1f2937;
                font-family: 'Inter', 'Segoe UI';
                font-size: 14px;
                font-weight: 700;
                padding: 8px 0px 0px 0px;
            }
        """)
        form_lay.addWidget(form_title)

        form_grid = QtWidgets.QGridLayout()
        form_grid.setSpacing(12)

        # Advance No
        form_grid.addWidget(QtWidgets.QLabel("Advance No:"), 0, 0)
        self.advance_no_input = QtWidgets.QLineEdit()
        self.advance_no_input.setReadOnly(True)
        self.advance_no_input.setStyleSheet("""
            QLineEdit {
                background: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-family: 'Segoe UI', monospace;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.advance_no_input, 0, 1)

        auto_label = QtWidgets.QLabel("(Auto)")
        auto_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        form_grid.addWidget(auto_label, 0, 2)

        # Date
        form_grid.addWidget(QtWidgets.QLabel("Date:"), 0, 3)
        self.date_input = QtWidgets.QDateEdit()
        self.date_input.setDate(QtCore.QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setStyleSheet("""
            QDateEdit {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.date_input, 0, 4)

        # Employee
        form_grid.addWidget(QtWidgets.QLabel("Employee:"), 1, 0)
        self.employee_combo = QtWidgets.QComboBox()
        self.employee_combo.setStyleSheet("""
            QComboBox {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.employee_combo, 1, 1, 1, 2)

        # Advance Amount
        form_grid.addWidget(QtWidgets.QLabel("Advance Amount:"), 1, 3)
        self.amount_input = QtWidgets.QDoubleSpinBox()
        self.amount_input.setMaximum(9999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setStyleSheet("""
            QDoubleSpinBox {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.amount_input, 1, 4)

        # Reason
        form_grid.addWidget(QtWidgets.QLabel("Reason:"), 2, 0)
        self.reason_input = QtWidgets.QLineEdit()
        self.reason_input.setPlaceholderText("e.g., Medical Emergency")
        self.reason_input.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.reason_input, 2, 1, 1, 2)

        # Payment Method
        form_grid.addWidget(QtWidgets.QLabel("Payment Method:"), 2, 3)
        self.payment_method_combo = QtWidgets.QComboBox()
        self.payment_method_combo.addItems(["Cash", "Bank Transfer", "Cheque"])
        self.payment_method_combo.setStyleSheet("""
            QComboBox {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.payment_method_combo, 2, 4)

        # Status
        form_grid.addWidget(QtWidgets.QLabel("Status:"), 3, 0)
        self.status_display = QtWidgets.QLineEdit()
        self.status_display.setText("Open")
        self.status_display.setReadOnly(True)
        self.status_display.setStyleSheet("""
            QLineEdit {
                background: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 10px;
                font-size: 11px;
            }
        """)
        form_grid.addWidget(self.status_display, 3, 1)

        form_lay.addLayout(form_grid)
        form_lay.addSpacing(12)

        # Buttons
        button_lay = QtWidgets.QHBoxLayout()
        button_lay.setSpacing(10)

        save_btn = QtWidgets.QPushButton("💾 Save")
        save_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        save_btn.setStyleSheet("""
            QPushButton {
                background: #3b82f6;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #2563eb;
            }
            QPushButton:pressed {
                background: #1d4ed8;
            }
        """)
        save_btn.clicked.connect(self.save_advance)
        button_lay.addWidget(save_btn)

        cancel_btn = QtWidgets.QPushButton("✕ Cancel")
        cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #e5e7eb;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #d1d5db;
            }
        """)
        cancel_btn.clicked.connect(self.clear_form)
        button_lay.addWidget(cancel_btn)
        button_lay.addStretch()

        form_lay.addLayout(button_lay)

        # Table Section
        table_widget = QtWidgets.QWidget()
        table_lay = QtWidgets.QVBoxLayout(table_widget)
        table_lay.setContentsMargins(0, 0, 0, 0)
        table_lay.setSpacing(10)

        table_title = QtWidgets.QLabel("Advance List")
        table_title.setStyleSheet("""
            QLabel {
                color: #1f2937;
                font-family: 'Inter', 'Segoe UI';
                font-size: 14px;
                font-weight: 700;
                padding: 8px 0px 0px 0px;
            }
        """)
        table_lay.addWidget(table_title)

        self.advances_table = QtWidgets.QTableWidget()
        self.advances_table.setColumnCount(8)
        self.advances_table.setHorizontalHeaderLabels([
            "Advance No", "Date", "Employee", "Amount", "Adjusted", "Balance", "Status", "Actions"
        ])
        self.advances_table.setColumnWidth(0, 120)
        self.advances_table.setColumnWidth(1, 100)
        self.advances_table.setColumnWidth(2, 120)
        self.advances_table.setColumnWidth(3, 90)
        self.advances_table.setColumnWidth(4, 80)
        self.advances_table.setColumnWidth(5, 80)
        self.advances_table.setColumnWidth(6, 90)
        self.advances_table.setColumnWidth(7, 150)

        self.advances_table.setStyleSheet("""
            QTableWidget {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                gridline-color: #e5e7eb;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #f9fafb;
                padding: 8px;
                border: none;
                border-right: 1px solid #e5e7eb;
                border-bottom: 1px solid #e5e7eb;
                font-weight: 600;
                color: #374151;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            QTableWidget::item:selected {
                background: #dbeafe;
            }
        """)
        self.advances_table.horizontalHeader().setStretchLastSection(False)
        self.advances_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.advances_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.advances_table.setAlternatingRowColors(True)
        table_lay.addWidget(self.advances_table)

        self.total_label = QtWidgets.QLabel("Total: 0 Record(s)")
        self.total_label.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 11px;
                padding: 4px 0px;
            }
        """)
        table_lay.addWidget(self.total_label)

        splitter.addWidget(form_widget)
        splitter.addWidget(table_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter)

    def load_data(self):
        """Load advances and employees from Firebase"""
        try:
            if not FIREBASE_AVAILABLE:
                return

            # Load employees
            employees_ref = db.reference('/employees')
            employees_data = employees_ref.get()
            if employees_data:
                self.employees = employees_data if isinstance(employees_data, dict) else {}

            # Load advances
            advances_ref = db.reference('/employee_advances')
            advances_data = advances_ref.get()
            if advances_data:
                self.advances_data = advances_data if isinstance(advances_data, dict) else {}

            self.refresh_employee_combo()
            self.refresh_table()
        except Exception as e:
            _log.error(f"Error loading data: {e}")

    def refresh_employee_combo(self):
        """Refresh employee dropdown"""
        self.employee_combo.clear()
        employee_names = []

        if self.employees:
            for emp_id, emp_data in self.employees.items():
                if isinstance(emp_data, dict):
                    name = emp_data.get('name', 'Unknown')
                    employee_names.append((name, emp_id))

        employee_names.sort(key=lambda x: x[0])
        for name, emp_id in employee_names:
            self.employee_combo.addItem(name, emp_id)

    def refresh_table(self):
        """Refresh the advances table"""
        self.advances_table.setRowCount(0)

        advances_list = []
        if self.advances_data:
            for adv_id, adv_data in self.advances_data.items():
                if isinstance(adv_data, dict):
                    advances_list.append((adv_id, adv_data))

        advances_list.sort(key=lambda x: x[1].get('date', ''), reverse=True)

        for row_idx, (adv_id, adv_data) in enumerate(advances_list):
            self.advances_table.insertRow(row_idx)

            # Advance No
            adv_no = adv_data.get('advance_no', 'N/A')
            item = QtWidgets.QTableWidgetItem(adv_no)
            item.setData(QtCore.Qt.UserRole, adv_id)
            item.setFont(QtGui.QFont('Segoe UI', 10, QtGui.QFont.Bold))
            self.advances_table.setItem(row_idx, 0, item)

            # Date
            date_str = adv_data.get('date', '')
            self.advances_table.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(date_str))

            # Employee
            employee_id = adv_data.get('employee_id', '')
            employee_name = 'N/A'
            if employee_id in self.employees:
                employee_name = self.employees[employee_id].get('name', 'Unknown')
            self.advances_table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(employee_name))

            # Amount
            amount = adv_data.get('amount', 0)
            self.advances_table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(f"{float(amount):,.2f}"))

            # Adjusted
            adjusted = adv_data.get('adjusted', 0)
            self.advances_table.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(f"{float(adjusted):,.2f}"))

            # Balance
            balance = float(amount) - float(adjusted)
            balance_item = QtWidgets.QTableWidgetItem(f"{balance:,.2f}")
            self.advances_table.setItem(row_idx, 5, balance_item)

            # Status
            status = adv_data.get('status', 'Open')
            status_item = QtWidgets.QTableWidgetItem(status)
            if status == 'Closed':
                status_item.setForeground(QtGui.QColor('#10b981'))
            else:
                status_item.setForeground(QtGui.QColor('#3b82f6'))
            self.advances_table.setItem(row_idx, 6, status_item)

            # Actions
            actions_widget = QtWidgets.QWidget()
            actions_lay = QtWidgets.QHBoxLayout(actions_widget)
            actions_lay.setContentsMargins(2, 2, 2, 2)
            actions_lay.setSpacing(4)

            edit_btn = QtWidgets.QPushButton("✎ Edit")
            edit_btn.setFixedSize(60, 28)
            edit_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            edit_btn.setStyleSheet("""
                QPushButton {
                    background: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: 600;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background: #2563eb;
                }
            """)
            edit_btn.clicked.connect(lambda checked, aid=adv_id: self.open_adjustment(aid))
            actions_lay.addWidget(edit_btn)

            delete_btn = QtWidgets.QPushButton("🗑 Delete")
            delete_btn.setFixedSize(60, 28)
            delete_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            delete_btn.setStyleSheet("""
                QPushButton {
                    background: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: 600;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background: #dc2626;
                }
            """)
            delete_btn.clicked.connect(lambda checked, aid=adv_id: self.delete_advance(aid))
            actions_lay.addWidget(delete_btn)
            actions_lay.addStretch()

            self.advances_table.setCellWidget(row_idx, 7, actions_widget)

        self.total_label.setText(f"Total: {len(advances_list)} Record(s)")

    def generate_advance_no(self) -> str:
        """Generate next advance number"""
        highest_num = 0
        for adv_data in self.advances_data.values():
            if isinstance(adv_data, dict):
                adv_no = adv_data.get('advance_no', '')
                if adv_no.startswith('ADV-'):
                    try:
                        num = int(adv_no.split('-')[1])
                        highest_num = max(highest_num, num)
                    except (ValueError, IndexError):
                        pass

        new_num = highest_num + 1
        return f"ADV-{new_num:05d}"

    def save_advance(self):
        """Save new advance to Firebase"""
        try:
            if not self.employee_combo.currentData():
                QtWidgets.QMessageBox.warning(self, "Validation Error", "Please select an employee")
                return

            if self.amount_input.value() <= 0:
                QtWidgets.QMessageBox.warning(self, "Validation Error", "Advance amount must be greater than 0")
                return

            advance_id = str(uuid.uuid4())
            employee_id = self.employee_combo.currentData()
            employee_name = self.employee_combo.currentText()

            advance_data = {
                'advance_no': self.generate_advance_no(),
                'date': self.date_input.date().toString("dd-MMM-yy"),
                'employee_id': employee_id,
                'employee_name': employee_name,
                'amount': self.amount_input.value(),
                'reason': self.reason_input.text() or "",
                'payment_method': self.payment_method_combo.currentText(),
                'status': 'Open',
                'adjusted': 0,
                'adjustments': {},
                'created_at': datetime.now().isoformat()
            }

            if FIREBASE_AVAILABLE:
                advances_ref = db.reference('/employee_advances')
                advances_ref.child(advance_id).set(advance_data)

                # Sync to finance expenses
                self._sync_advance_to_finance(advance_id, advance_data)

            self.advances_data[advance_id] = advance_data
            self.refresh_table()
            self.clear_form()
            QtWidgets.QMessageBox.information(self, "Success", "Advance saved successfully!")
            self.advance_updated.emit()

        except Exception as e:
            _log.error(f"Error saving advance: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", f"Error saving advance: {e}")

    def clear_form(self):
        """Clear the form inputs"""
        self.advance_no_input.clear()
        self.date_input.setDate(QtCore.QDate.currentDate())
        self.employee_combo.setCurrentIndex(0)
        self.amount_input.setValue(0)
        self.reason_input.clear()
        self.payment_method_combo.setCurrentIndex(0)
        self.status_display.setText("Open")

    def _sync_advance_to_finance(self, advance_id: str, advance_data: Dict):
        """Sync advance to finance expenses"""
        try:
            if not FIREBASE_AVAILABLE:
                return

            balance_due = float(advance_data.get("amount", 0)) - float(advance_data.get("adjusted", 0))

            # Don't create finance entry if balance due is 0
            if balance_due <= 0:
                self._delete_advance_finance_entry(advance_id)
                return

            # Get current user name from settings
            settings = db.reference('/settings').get() or {}
            current_user_name = settings.get("user_name", "") or advance_data.get("created_by", "")

            # Build expense name and description with optional reason
            advance_no = advance_data.get('advance_no', '')
            employee_name = advance_data.get('employee_name', 'Unknown')
            reason = advance_data.get('reason', '').strip()

            expense_name = f"{advance_no}_{employee_name}"
            if reason:
                description = f"Advance {advance_no} for {employee_name} - {reason}"
            else:
                description = f"Advance {advance_no} for {employee_name}"

            expense_data = {
                "expense_type": "Employee Advance",
                "expense_name": expense_name,
                "description": description,
                "amount": balance_due,
                "category": "Advance for employee",
                "date": advance_data.get("date", datetime.now().strftime("%d-%b-%y")),
                "vendor": "Employee Advances",
                "notes": f"Original: ${float(advance_data.get('amount', 0)):.2f} | Adjusted: ${float(advance_data.get('adjusted', 0)):.2f}",
                "advance_id": advance_id,
                "advance_no": advance_data.get("advance_no", ""),
                "employee_id": advance_data.get("employee_id", ""),
                "employee_name": advance_data.get("employee_name", ""),
                "status": "Approved",
                "submitted_by_name": current_user_name,
                "created_at": advance_data.get("created_at", datetime.now().isoformat()),
            }

            # Check if finance entry already exists
            expenses_ref = db.reference('/balance_sheet_expenses')
            expenses = expenses_ref.get() or {}
            finance_entry_id = None

            if isinstance(expenses, dict):
                for exp_id, exp_data in expenses.items():
                    if isinstance(exp_data, dict) and exp_data.get("advance_id") == advance_id:
                        finance_entry_id = exp_id
                        break

            if finance_entry_id:
                # Update existing entry
                expenses_ref.child(finance_entry_id).update(expense_data)
            else:
                # Create new entry
                expenses_ref.push(expense_data)

        except Exception as e:
            _log.error(f"Error syncing advance to finance: {e}")

    def _delete_advance_finance_entry(self, advance_id: str):
        """Delete finance entry for an advance"""
        try:
            if not FIREBASE_AVAILABLE:
                return

            expenses_ref = db.reference('/balance_sheet_expenses')
            expenses = expenses_ref.get() or {}

            if isinstance(expenses, dict):
                for exp_id, exp_data in expenses.items():
                    if isinstance(exp_data, dict) and exp_data.get("advance_id") == advance_id:
                        expenses_ref.child(exp_id).delete()
                        break

        except Exception as e:
            _log.error(f"Error deleting advance finance entry: {e}")

    def open_adjustment(self, advance_id: str):
        """Open adjustment dialog for an advance"""
        if advance_id not in self.advances_data:
            QtWidgets.QMessageBox.warning(self, "Error", "Advance not found")
            return

        dialog = AdvancementAdjustmentDialog(
            advance_id=advance_id,
            advance_data=self.advances_data[advance_id],
            employees=self.employees,
            parent=self
        )
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            # Reload data after adjustment
            self.load_data()
            self.advance_updated.emit()

    def delete_advance(self, advance_id: str):
        """Delete an advance"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this advance?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            try:
                if FIREBASE_AVAILABLE:
                    # Delete from finance expenses first
                    self._delete_advance_finance_entry(advance_id)
                    # Then delete the advance
                    db.reference('/employee_advances').child(advance_id).delete()

                if advance_id in self.advances_data:
                    del self.advances_data[advance_id]

                self.refresh_table()
                QtWidgets.QMessageBox.information(self, "Success", "Advance deleted successfully!")
                self.advance_updated.emit()

            except Exception as e:
                _log.error(f"Error deleting advance: {e}")
                QtWidgets.QMessageBox.critical(self, "Error", f"Error deleting advance: {e}")


class AdvancementAdjustmentDialog(QtWidgets.QDialog):
    """Dialog for adjusting employee advances"""

    def __init__(self, advance_id: str, advance_data: Dict, employees: Dict, parent=None):
        super().__init__(parent)
        self.advance_id = advance_id
        self.advance_data = advance_data
        self.employees = employees
        self.adjustment_history = advance_data.get('adjustments', {})

        self.setWindowTitle("Employee Advance Adjustment")
        self.setGeometry(100, 100, 1000, 700)
        self.setStyleSheet("""
            QDialog {
                background: #f9fafb;
            }
        """)

        self._build_ui()
        self._load_adjustment_history()

    def _build_ui(self):
        """Build the dialog UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header with back button
        header_lay = QtWidgets.QHBoxLayout()
        back_btn = QtWidgets.QPushButton("← Back to Advance List")
        back_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        back_btn.setStyleSheet("""
            QPushButton {
                background: #e5e7eb;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #d1d5db;
            }
        """)
        back_btn.clicked.connect(self.reject)
        header_lay.addWidget(back_btn)
        header_lay.addStretch()
        layout.addLayout(header_lay)

        # Title
        title = QtWidgets.QLabel("Employee Advance Adjustment")
        title.setStyleSheet("""
            QLabel {
                color: #1f2937;
                font-family: 'Inter', 'Segoe UI';
                font-size: 18px;
                font-weight: 900;
            }
        """)
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Adjust advance amount through Payroll or Manual Entry")
        subtitle.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 12px;
            }
        """)
        layout.addWidget(subtitle)

        # Main content area
        content_widget = QtWidgets.QWidget()
        content_lay = QtWidgets.QHBoxLayout(content_widget)
        content_lay.setSpacing(20)

        # Left panel - Advance info and adjustment form
        left_panel = QtWidgets.QWidget()
        left_lay = QtWidgets.QVBoxLayout(left_panel)
        left_lay.setSpacing(14)

        # Info box
        info_frame = QtWidgets.QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 6px;
            }
        """)
        info_lay = QtWidgets.QVBoxLayout(info_frame)
        info_lay.setContentsMargins(16, 12, 16, 12)
        info_lay.setSpacing(8)

        # Advance No selector
        adv_no_lay = QtWidgets.QHBoxLayout()
        adv_no_lay.addWidget(QtWidgets.QLabel("Advance No"))
        self.advance_no_combo = QtWidgets.QComboBox()
        self.advance_no_combo.addItem(self.advance_data.get('advance_no', ''), self.advance_id)
        self.advance_no_combo.setStyleSheet("""
            QComboBox {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)
        adv_no_lay.addWidget(self.advance_no_combo)
        adv_no_lay.addStretch()
        info_lay.addLayout(adv_no_lay)

        # Employee info
        employee_id = self.advance_data.get('employee_id', '')
        employee_name = 'N/A'
        if employee_id in self.employees:
            employee_name = self.employees[employee_id].get('name', 'Unknown')

        info_text = QtWidgets.QLabel(
            f"Employee : {employee_name}\n"
            f"Advance Date : {self.advance_data.get('date', '')}\n"
            f"Advance Amount : {float(self.advance_data.get('amount', 0)):,.2f}"
        )
        info_text.setStyleSheet("""
            QLabel {
                color: #374151;
                font-size: 11px;
                background: #f9fafb;
                padding: 8px;
                border-radius: 4px;
                border: 1px solid #e5e7eb;
            }
        """)
        info_lay.addWidget(info_text)

        # Info boxes row
        info_boxes_lay = QtWidgets.QHBoxLayout()
        info_boxes_lay.setSpacing(10)

        for label, value, bg_color in [
            ("Total Advance Amount", f"{float(self.advance_data.get('amount', 0)):,.2f}", "#dbeafe"),
            ("Total Adjusted", f"{float(self.advance_data.get('adjusted', 0)):,.2f}", "#fef3c7"),
            ("Current Balance", f"{float(self.advance_data.get('amount', 0)) - float(self.advance_data.get('adjusted', 0)):,.2f}", "#dcfce7"),
        ]:
            box = QtWidgets.QWidget()
            box_lay = QtWidgets.QVBoxLayout(box)
            box_lay.setContentsMargins(12, 10, 12, 10)
            box_lay.setSpacing(4)

            box.setStyleSheet(f"""
                QWidget {{
                    background: {bg_color};
                    border-radius: 6px;
                    border: 1px solid #e5e7eb;
                }}
            """)

            label_w = QtWidgets.QLabel(label)
            label_w.setStyleSheet("color: #6b7280; font-size: 10px; font-weight: 600;")
            box_lay.addWidget(label_w)

            value_w = QtWidgets.QLabel(value)
            value_w.setStyleSheet("color: #1f2937; font-size: 13px; font-weight: 700;")
            box_lay.addWidget(value_w)

            info_boxes_lay.addWidget(box)

        info_lay.addLayout(info_boxes_lay)
        left_lay.addWidget(info_frame)

        # Adjustment form
        form_frame = QtWidgets.QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 6px;
            }
        """)
        form_lay = QtWidgets.QVBoxLayout(form_frame)
        form_lay.setContentsMargins(16, 12, 16, 12)
        form_lay.setSpacing(12)

        form_title = QtWidgets.QLabel("Add Adjustment")
        form_title.setStyleSheet("color: #1f2937; font-weight: 700; font-size: 12px;")
        form_lay.addWidget(form_title)

        # Adjustment Date
        adj_date_lay = QtWidgets.QHBoxLayout()
        adj_date_lay.addWidget(QtWidgets.QLabel("Adjustment Date *"))
        self.adj_date_input = QtWidgets.QDateEdit()
        self.adj_date_input.setDate(QtCore.QDate.currentDate())
        self.adj_date_input.setCalendarPopup(True)
        self.adj_date_input.setStyleSheet("""
            QDateEdit {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)
        adj_date_lay.addWidget(self.adj_date_input)
        adj_date_lay.addStretch()
        form_lay.addLayout(adj_date_lay)

        # Adjustment Amount
        adj_amt_lay = QtWidgets.QHBoxLayout()
        adj_amt_lay.addWidget(QtWidgets.QLabel("Adjustment Amount *"))
        self.adj_amount_input = QtWidgets.QDoubleSpinBox()
        self.adj_amount_input.setMaximum(9999999.99)
        self.adj_amount_input.setDecimals(2)
        self.adj_amount_input.setStyleSheet("""
            QDoubleSpinBox {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)
        adj_amt_lay.addWidget(self.adj_amount_input)

        # Reference
        adj_amt_lay.addWidget(QtWidgets.QLabel("Reference"))
        self.reference_input = QtWidgets.QLineEdit()
        self.reference_input.setPlaceholderText("e.g., July Payroll")
        self.reference_input.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)
        adj_amt_lay.addWidget(self.reference_input)
        adj_amt_lay.addStretch()
        form_lay.addLayout(adj_amt_lay)

        # Adjustment Type
        adj_type_lay = QtWidgets.QHBoxLayout()
        adj_type_lay.addWidget(QtWidgets.QLabel("Adjustment Type"))
        self.adj_type_combo = QtWidgets.QComboBox()
        self.adj_type_combo.addItems(["Payroll Deduction", "Manual Adjustment", "Partial Payment"])
        self.adj_type_combo.setStyleSheet("""
            QComboBox {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)
        adj_type_lay.addWidget(self.adj_type_combo)
        adj_type_lay.addStretch()
        form_lay.addLayout(adj_type_lay)

        # Remarks
        remarks_lay = QtWidgets.QVBoxLayout()
        remarks_lay.addWidget(QtWidgets.QLabel("Remarks"))
        self.remarks_input = QtWidgets.QTextEdit()
        self.remarks_input.setMaximumHeight(60)
        self.remarks_input.setStyleSheet("""
            QTextEdit {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
            }
        """)
        remarks_lay.addWidget(self.remarks_input)
        form_lay.addLayout(remarks_lay)

        # Save/Cancel buttons
        btn_lay = QtWidgets.QHBoxLayout()
        btn_lay.setSpacing(10)

        save_adj_btn = QtWidgets.QPushButton("💾 Save Adjustment")
        save_adj_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        save_adj_btn.setStyleSheet("""
            QPushButton {
                background: #3b82f6;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #2563eb;
            }
        """)
        save_adj_btn.clicked.connect(self.save_adjustment)
        btn_lay.addWidget(save_adj_btn)

        cancel_btn = QtWidgets.QPushButton("✕ Cancel")
        cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #e5e7eb;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #d1d5db;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(cancel_btn)
        btn_lay.addStretch()

        form_lay.addLayout(btn_lay)
        left_lay.addWidget(form_frame)
        left_lay.addStretch()

        # Right panel - Adjustment history table
        right_panel = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right_panel)
        right_lay.setSpacing(10)

        history_title = QtWidgets.QLabel("Adjustment History for This Advance")
        history_title.setStyleSheet("color: #1f2937; font-weight: 700; font-size: 12px;")
        right_lay.addWidget(history_title)

        self.history_table = QtWidgets.QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "SL", "Adjustment Date", "Adjustment Type", "Reference", "Adjustment Amount", "Remarks", "Adjusted By"
        ])
        self.history_table.setColumnWidth(0, 40)
        self.history_table.setColumnWidth(1, 110)
        self.history_table.setColumnWidth(2, 120)
        self.history_table.setColumnWidth(3, 100)
        self.history_table.setColumnWidth(4, 120)
        self.history_table.setColumnWidth(5, 150)
        self.history_table.setColumnWidth(6, 80)

        self.history_table.setStyleSheet("""
            QTableWidget {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                gridline-color: #e5e7eb;
                font-size: 10px;
            }
            QHeaderView::section {
                background: #f9fafb;
                padding: 6px;
                border: none;
                border-right: 1px solid #e5e7eb;
                border-bottom: 1px solid #e5e7eb;
                font-weight: 600;
                color: #374151;
                font-size: 10px;
            }
            QTableWidget::item {
                padding: 6px;
                border: none;
            }
        """)
        right_lay.addWidget(self.history_table)

        # Summary info
        info_frame_bottom = QtWidgets.QFrame()
        info_frame_bottom.setStyleSheet("""
            QFrame {
                background: #ecfdf5;
                border: 1px solid #a7f3d0;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        info_lay_bottom = QtWidgets.QHBoxLayout(info_frame_bottom)

        info_icon = QtWidgets.QLabel("ℹ")
        info_icon.setStyleSheet("color: #059669; font-weight: bold; font-size: 14px;")
        info_lay_bottom.addWidget(info_icon)

        info_msg = QtWidgets.QLabel("When balance becomes 0, the advance status will be automatically marked as Closed.")
        info_msg.setStyleSheet("color: #047857; font-size: 11px;")
        info_msg.setWordWrap(True)
        info_lay_bottom.addWidget(info_msg)
        info_lay_bottom.addStretch()

        right_lay.addWidget(info_frame_bottom)

        # Add total adjusted label
        self.total_adj_label = QtWidgets.QLabel("Total Adjusted: 0.00")
        self.total_adj_label.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px 0px;")
        right_lay.addWidget(self.total_adj_label)

        content_lay.addWidget(left_panel, 2)
        content_lay.addWidget(right_panel, 3)

        layout.addWidget(content_widget)

    def _load_adjustment_history(self):
        """Load and display adjustment history"""
        self.history_table.setRowCount(0)

        adjustments = []
        if self.adjustment_history:
            for adj_id, adj_data in self.adjustment_history.items():
                if isinstance(adj_data, dict):
                    adjustments.append((adj_data.get('date', ''), adj_data))

        adjustments.sort(key=lambda x: x[0], reverse=True)

        total_adjusted = 0
        for row_idx, (_, adj_data) in enumerate(adjustments):
            self.history_table.insertRow(row_idx)

            # SL
            sl_item = QtWidgets.QTableWidgetItem(str(row_idx + 1))
            self.history_table.setItem(row_idx, 0, sl_item)

            # Adjustment Date
            date_item = QtWidgets.QTableWidgetItem(adj_data.get('date', ''))
            self.history_table.setItem(row_idx, 1, date_item)

            # Adjustment Type
            type_item = QtWidgets.QTableWidgetItem(adj_data.get('type', ''))
            self.history_table.setItem(row_idx, 2, type_item)

            # Reference
            ref_item = QtWidgets.QTableWidgetItem(adj_data.get('reference', ''))
            self.history_table.setItem(row_idx, 3, ref_item)

            # Adjustment Amount
            amount = float(adj_data.get('amount', 0))
            amount_item = QtWidgets.QTableWidgetItem(f"{amount:,.2f}")
            self.history_table.setItem(row_idx, 4, amount_item)
            total_adjusted += amount

            # Remarks
            remarks_item = QtWidgets.QTableWidgetItem(adj_data.get('remarks', ''))
            self.history_table.setItem(row_idx, 5, remarks_item)

            # Adjusted By
            by_item = QtWidgets.QTableWidgetItem(adj_data.get('adjusted_by', 'System'))
            self.history_table.setItem(row_idx, 6, by_item)

        self.total_adj_label.setText(f"Total Adjusted: {total_adjusted:,.2f}")

    def save_adjustment(self):
        """Save adjustment to Firebase"""
        try:
            if self.adj_amount_input.value() <= 0:
                QtWidgets.QMessageBox.warning(self, "Validation Error", "Adjustment amount must be greater than 0")
                return

            # Check if adjustment would exceed balance
            current_balance = float(self.advance_data.get('amount', 0)) - float(self.advance_data.get('adjusted', 0))
            if self.adj_amount_input.value() > current_balance:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Amount Exceeded",
                    f"Adjustment amount cannot exceed current balance ({current_balance:,.2f})"
                )
                return

            adjustment_id = str(uuid.uuid4())
            adjustment_data = {
                'date': self.adj_date_input.date().toString("dd-MMM-yy"),
                'amount': self.adj_amount_input.value(),
                'type': self.adj_type_combo.currentText(),
                'reference': self.reference_input.text() or "",
                'remarks': self.remarks_input.toPlainText() or "",
                'adjusted_by': 'Admin',
                'created_at': datetime.now().isoformat()
            }

            if FIREBASE_AVAILABLE:
                adv_ref = db.reference(f'/employee_advances/{self.advance_id}')

                # Update adjusted amount
                new_adjusted = float(self.advance_data.get('adjusted', 0)) + self.adj_amount_input.value()
                adv_ref.child('adjusted').set(new_adjusted)

                # Check if balance is now 0
                new_balance = float(self.advance_data.get('amount', 0)) - new_adjusted
                if new_balance <= 0:
                    adv_ref.child('status').set('Closed')

                # Add adjustment to history
                adv_ref.child('adjustments').child(adjustment_id).set(adjustment_data)

                # Update local data
                self.advance_data['adjusted'] = new_adjusted
                self.advance_data['adjustments'][adjustment_id] = adjustment_data
                if new_balance <= 0:
                    self.advance_data['status'] = 'Closed'

                # Sync updated advance to finance
                parent_dialog = self.parent()
                if parent_dialog and hasattr(parent_dialog, '_sync_advance_to_finance'):
                    parent_dialog._sync_advance_to_finance(self.advance_id, self.advance_data)

            # Refresh history
            self._load_adjustment_history()
            self.adj_date_input.setDate(QtCore.QDate.currentDate())
            self.adj_amount_input.setValue(0)
            self.reference_input.clear()
            self.remarks_input.clear()

            QtWidgets.QMessageBox.information(self, "Success", "Adjustment saved successfully!")

        except Exception as e:
            _log.error(f"Error saving adjustment: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", f"Error saving adjustment: {e}")
