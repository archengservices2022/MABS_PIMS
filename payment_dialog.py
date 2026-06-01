"""Payment Management Dialog - Add/Edit payments for projects"""
import re
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import pyqtSignal
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from payment_tracker import get_payment_tracker, Payment


def _clean_stage_label(stage: str) -> str:
    """Strip percentage suffixes and normalize a payment stage for display."""
    cleaned = re.sub(r'\s*\(\d+%\)', '', stage or '').strip()
    lo = cleaned.lower()
    if any(x in lo for x in ("down payment", "deposit")):
        return "Down Payment"
    if any(x in lo for x in ("1st installment", "1st payment", "payment 1", "term 1")):
        return "1st Installment"
    if any(x in lo for x in ("2nd installment", "2nd payment", "payment 2", "term 2")):
        return "2nd Installment"
    if any(x in lo for x in ("3rd installment", "3rd payment", "payment 3", "term 3")):
        return "3rd Installment"
    if any(x in lo for x in ("4th installment", "4th payment", "payment 4", "term 4")):
        return "4th Installment"
    if "final" in lo:
        return "Final Payment"
    if any(x in lo for x in ("balance", "due payment")):
        return "Balance Payment"
    if any(x in lo for x in ("full amount", "full payment")):
        return "Full Payment"
    return cleaned or "Manual"


_STAGE_ORDER = {
    "down payment": 0, "deposit": 0,
    "1st installment": 1, "1st payment": 1, "payment 1": 1, "term 1": 1,
    "2nd installment": 2, "2nd payment": 2, "payment 2": 2, "term 2": 2,
    "3rd installment": 3, "3rd payment": 3, "payment 3": 3, "term 3": 3,
    "4th installment": 4, "4th payment": 4, "payment 4": 4, "term 4": 4,
    "5th installment": 5, "5th payment": 5, "payment 5": 5, "term 5": 5,
    "balance payment": 80, "due payment": 80,
    "final payment": 90, "full payment": 91, "full amount": 91,
    "tax": 99,
}

def _payment_sort_key(p):
    """Sort key: (stage priority, parsed date). Groups same-stage payments together,
    oldest first within each stage."""
    lo = re.sub(r'\s*\(\d+%\)', '', p.payment_stage or '').strip().lower()
    priority = 50  # unknown stages sort in the middle
    for keyword, rank in _STAGE_ORDER.items():
        if keyword in lo:
            priority = rank
            break
    d = p.payment_date or ""
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return (priority, datetime.strptime(d, fmt))
        except ValueError:
            pass
    return (priority, datetime.min)


class PaymentDialog(QtWidgets.QDialog):
    """Dialog for adding/editing payments"""
    
    payment_added = pyqtSignal(str, float)  # project_number, amount
    
    def __init__(self, parent=None, project_number: str = "", 
                 project_name: str = "", total_amount: float = 0.0,
                 edit_payment: Payment = None, invoice_rows=None):
        super().__init__(parent)
        self.project_number = project_number
        self.project_name = project_name
        self.total_amount = total_amount
        self.edit_payment = edit_payment
        self.invoice_rows = invoice_rows or []
        self.payment_tracker = get_payment_tracker()
        
        self.setWindowTitle(f"{'Edit' if edit_payment else 'Add'} Payment - {project_number}")
        self.setFixedSize(620, 630)
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setStyleSheet("""
            QDialog {
                background: #f8fafc;
            }
            QLabel {
                color: #1e293b;
                font-size: 13px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QLineEdit, QDateEdit, QComboBox, QTextEdit {
                background: white;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 12px;
                font-size: 13px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                min-height: 22px;
            }
            QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QTextEdit:focus {
                border-color: #3b82f6;
                outline: none;
            }
            QComboBox::drop-down, QDateEdit::drop-down {
                border: none;
                width: 34px;
                background: #0f766e;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox::down-arrow, QDateEdit::down-arrow {
                image: none;
                border: none;
            }
            QPushButton {
                background: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background: #2563eb;
            }
            QPushButton:pressed {
                background: #1d4ed8;
            }
            QPushButton:disabled {
                background: #94a3b8;
            }
        """)
        
        self._init_ui()
        self._load_existing_data()
    
    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Project Info
        info_group = QtWidgets.QGroupBox("Project Information")
        info_group.setStyleSheet("""
            QGroupBox {
                font-weight: 600;
                color: #374151;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px 0 4px;
            }
        """)
        info_layout = QtWidgets.QFormLayout(info_group)
        info_layout.setContentsMargins(18, 18, 18, 14)
        info_layout.setHorizontalSpacing(18)
        info_layout.setVerticalSpacing(8)
        info_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        
        self.project_number_label = QtWidgets.QLabel(self.project_number)
        self.project_name_label = QtWidgets.QLabel(self.project_name)
        self.total_amount_label = QtWidgets.QLabel(f"${self.total_amount:,.2f}")
        self.project_name_label.setWordWrap(True)
        
        info_layout.addRow("Project Number:", self.project_number_label)
        info_layout.addRow("Project Name:", self.project_name_label)
        info_layout.addRow("Total Amount:", self.total_amount_label)
        
        layout.addWidget(info_group)
        
        # Payment Details
        payment_group = QtWidgets.QGroupBox("Payment Details")
        payment_group.setStyleSheet(info_group.styleSheet())
        payment_layout = QtWidgets.QFormLayout(payment_group)
        payment_layout.setContentsMargins(18, 20, 18, 16)
        payment_layout.setHorizontalSpacing(18)
        payment_layout.setVerticalSpacing(12)
        payment_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        payment_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.invoice_combo = QtWidgets.QComboBox()
        self.invoice_combo.setMinimumHeight(36)
        selectable_rows = []
        for invoice in self.invoice_rows:
            # Tax stage is only recorded automatically from invoice history — never manually
            if _clean_stage_label(invoice.get("stage", "")).lower() == "tax":
                continue
            remaining_value = invoice.get("remaining_value", None)
            is_paid = False
            if remaining_value is not None:
                try:
                    is_paid = float(remaining_value) <= 0
                except (TypeError, ValueError):
                    is_paid = False
            # Normalize both sides so "Down Payment (30%)" matches "Down Payment"
            editing_this_stage = (
                self.edit_payment
                and _clean_stage_label(invoice.get("stage", "")) == _clean_stage_label(
                    getattr(self.edit_payment, "payment_stage", "") or "")
                and invoice.get("invoice_number", "") == getattr(self.edit_payment, "invoice_number", "")
            )
            if not is_paid or editing_this_stage:
                selectable_rows.append(invoice)

        if selectable_rows and not self.edit_payment:
            selectable_rows = selectable_rows[:1]

        # In edit mode, ensure the payment's own stage is always in the combo —
        # but never surface Tax stage here; tax edits flow through invoice history.
        if self.edit_payment:
            ep_inv = getattr(self.edit_payment, "invoice_number", "") or ""
            ep_stage = getattr(self.edit_payment, "payment_stage", "") or ""
            ep_stage_clean = _clean_stage_label(ep_stage)
            if ep_stage_clean.lower() != "tax":
                already_present = any(
                    row.get("invoice_number", "") == ep_inv
                    and _clean_stage_label(row.get("stage", "")) == ep_stage_clean
                    for row in selectable_rows
                )
                if not already_present and ep_stage:
                    selectable_rows.insert(0, {
                        "invoice_number": ep_inv,
                        "stage": ep_stage,
                        "remaining_value": None,
                    })

        if not selectable_rows:
            self.invoice_combo.addItem(
                "Manual payment / no invoice selected",
                {"invoice_number": "", "stage": "", "remaining_value": self.total_amount}
            )

        for invoice in selectable_rows:
            invoice_number = invoice.get("invoice_number", "")
            stage = invoice.get("stage", "") or "Invoice"
            remaining = invoice.get("remaining_value", None)
            invoice_prefix = f"{invoice_number} - " if invoice_number else ""
            label = f"{invoice_prefix}{stage}"
            if remaining is not None:
                label = f"{label} | Remaining ${float(remaining):,.2f}"
            elif invoice.get("amount", ""):
                label = f"{label} ({invoice.get('amount')})"
            self.invoice_combo.addItem(label, {
                "invoice_number": invoice_number,
                "stage": stage,
                "remaining_value": remaining,
            })
        self.invoice_combo.currentIndexChanged.connect(self._prefill_stage_amount)
        self.invoice_combo.currentIndexChanged.connect(self._update_stage_limit_label)
        payment_layout.addRow("Payment Stage:", self.invoice_combo)

        # Payment Amount
        self.amount_edit = QtWidgets.QLineEdit()
        self.amount_edit.setPlaceholderText("0.00")
        self.amount_edit.setMinimumHeight(36)
        self.amount_edit.textChanged.connect(self._update_remaining)
        payment_layout.addRow("Payment Amount ($):", self.amount_edit)

        # Stage limit hint label (shown below the amount field)
        self.stage_limit_label = QtWidgets.QLabel("")
        self.stage_limit_label.setStyleSheet(
            "font-size: 11px; color: #64748b; padding: 0px 2px;"
        )
        payment_layout.addRow("", self.stage_limit_label)
        
        # Payment Date
        self.date_edit = QtWidgets.QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM-dd-yyyy")
        self.date_edit.setDate(QtCore.QDate.currentDate())
        self.date_edit.setMinimumHeight(36)
        # Prevent future payment dates
        self.date_edit.setMaximumDate(QtCore.QDate.currentDate())
        # Gray out future dates in the calendar popup
        _pcal = self.date_edit.calendarWidget()
        if _pcal:
            _pcal.setStyleSheet("""
                QCalendarWidget QAbstractItemView {
                    selection-background-color: #00756f;
                    selection-color: white;
                }
                QCalendarWidget QAbstractItemView:disabled {
                    color: #c8c8c8;
                }
            """)
            _gray_fmt = QtGui.QTextCharFormat()
            _gray_fmt.setForeground(QtGui.QBrush(QtGui.QColor("#c8c8c8")))
            _today = QtCore.QDate.currentDate()
            _d = _today.addDays(1)
            _end = _today.addYears(1)
            while _d <= _end:
                _pcal.setDateTextFormat(_d, _gray_fmt)
                _d = _d.addDays(1)
        self.date_edit.wheelEvent = lambda e: e.ignore()
        self.date_edit.stepBy = lambda x: None
        payment_layout.addRow("Payment Date:", self.date_edit)
        
        # Payment Method
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems([
            "Cash", "Check", "Bank Transfer", "Credit Card",
            "Wire Transfer", "Invoice", "Other"
        ])
        self.method_combo.setMinimumHeight(36)
        self.method_combo.wheelEvent = lambda e: e.ignore()
        self.method_combo.keyPressEvent = lambda e, c=self.method_combo: (
            QtWidgets.QComboBox.keyPressEvent(c, e)
            if e.key() not in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down) or c.view().isVisible()
            else e.ignore()
        )
        self.method_combo.currentIndexChanged.connect(
            lambda: QtCore.QTimer.singleShot(0, self.method_combo.clearFocus))
        payment_layout.addRow("Payment Method:", self.method_combo)
        
        # Notes
        self.notes_edit = QtWidgets.QTextEdit()
        self.notes_edit.setFixedHeight(74)
        self.notes_edit.setPlaceholderText("Optional notes about this payment...")
        payment_layout.addRow("Notes:", self.notes_edit)
        
        layout.addWidget(payment_group)
        
        # Payment Summary
        summary_group = QtWidgets.QGroupBox("Payment Summary")
        summary_group.setStyleSheet(info_group.styleSheet())
        summary_layout = QtWidgets.QFormLayout(summary_group)
        summary_layout.setContentsMargins(18, 18, 18, 14)
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(8)
        summary_layout.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        
        self.total_paid_label = QtWidgets.QLabel("$0.00")
        self.remaining_label = QtWidgets.QLabel(f"${self.total_amount:,.2f}")
        self.percentage_label = QtWidgets.QLabel("0%")
        
        # Get existing payments
        if self.project_number:
            existing_summary = self.payment_tracker.get_payment_summary(
                self.project_number, self.total_amount
            )
            self.total_paid_label.setText(f"${existing_summary['total_paid']:,.2f}")
            self.remaining_label.setText(f"${existing_summary['remaining']:,.2f}")
            self.percentage_label.setText(f"{existing_summary['payment_percentage']:.1f}%")
        
        summary_layout.addRow("Total Paid:", self.total_paid_label)
        summary_layout.addRow("Remaining:", self.remaining_label)
        summary_layout.addRow("Payment Progress:", self.percentage_label)
        
        layout.addWidget(summary_group)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setFixedSize(112, 42)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.save_btn = QtWidgets.QPushButton("Save Payment")
        self.save_btn.setFixedSize(140, 42)
        self.save_btn.clicked.connect(self._save_payment)
        self.save_btn.setDefault(True)
        
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.save_btn)
        layout.addLayout(button_layout)
        QtCore.QTimer.singleShot(0, self._prefill_stage_amount)
        QtCore.QTimer.singleShot(50, self._update_stage_limit_label)
    
    def _load_existing_data(self):
        """Load data if editing existing payment"""
        if self.edit_payment:
            self.amount_edit.setText(str(float(self.edit_payment.amount)))
            self._set_payment_date(self.edit_payment.payment_date)
            self.method_combo.setCurrentText(self.edit_payment.payment_method)
            self.notes_edit.setText(self.edit_payment.notes)
            ep_inv = getattr(self.edit_payment, "invoice_number", "") or ""
            ep_stage_clean = _clean_stage_label(
                getattr(self.edit_payment, "payment_stage", "") or "")
            for index in range(self.invoice_combo.count()):
                data = self.invoice_combo.itemData(index) or {}
                if (
                    data.get("invoice_number", "") == ep_inv
                    and _clean_stage_label(data.get("stage", "")) == ep_stage_clean
                ):
                    self.invoice_combo.setCurrentIndex(index)
                    break

    def _set_payment_date(self, date_text: str):
        """Load existing payment dates saved in either MM-DD-YYYY or YYYY-MM-DD."""
        for fmt in ("MM-dd-yyyy", "yyyy-MM-dd"):
            parsed = QtCore.QDate.fromString(date_text or "", fmt)
            if parsed.isValid():
                self.date_edit.setDate(parsed)
                return
        self.date_edit.setDate(QtCore.QDate.currentDate())

    def _get_stage_limit(self):
        """Return (limit_value, is_edit_adjusted) for the currently selected stage.
        Returns None if no limit applies."""
        data = self.invoice_combo.currentData() or {}
        remaining = data.get("remaining_value", None)
        if remaining in (None, ""):
            return None
        try:
            limit = float(remaining)
            if self.edit_payment:
                # For edits, add back the original payment amount so the ceiling is
                # (remaining + old amount) — i.e., what this payment slot actually allows.
                try:
                    limit += float(self.edit_payment.amount)
                except (TypeError, ValueError):
                    pass
            return limit
        except (TypeError, ValueError):
            return None

    def _update_stage_limit_label(self):
        if not hasattr(self, "stage_limit_label"):
            return
        limit = self._get_stage_limit()
        if limit is not None:
            self.stage_limit_label.setText(f"Max allowed for this stage: ${limit:,.2f}")
            self.stage_limit_label.setStyleSheet("font-size: 11px; color: #64748b; padding: 0px 2px;")
        else:
            self.stage_limit_label.setText("")
        # Re-validate current amount against new limit
        self._update_remaining()

    def _prefill_stage_amount(self):
        self._update_stage_limit_label()
        if self.edit_payment:
            return
        data = self.invoice_combo.currentData() or {}
        remaining = data.get("remaining_value", None)
        if remaining in (None, ""):
            return
        current = self.amount_edit.text().strip()
        if current:
            return
        try:
            self.amount_edit.setText(f"{float(remaining):.2f}")
        except (TypeError, ValueError):
            pass
    
    def _update_remaining(self):
        """Update remaining amount display and stage-limit validation."""
        try:
            amount = Decimal(self.amount_edit.text() or "0")
            existing_summary = self.payment_tracker.get_payment_summary(
                self.project_number, self.total_amount
            )

            if self.edit_payment:
                total_paid = existing_summary['total_paid'] - self.edit_payment.amount + amount
            else:
                total_paid = existing_summary['total_paid'] + amount

            remaining = Decimal(str(self.total_amount)) - total_paid
            percentage = float(total_paid / Decimal(str(self.total_amount)) * 100) if self.total_amount > 0 else 0

            self.total_paid_label.setText(f"${total_paid:,.2f}")
            self.remaining_label.setText(f"${remaining:,.2f}")
            self.percentage_label.setText(f"{percentage:.1f}%")

            # Color coding for overall project remaining
            if remaining <= 0:
                self.remaining_label.setStyleSheet("color: #059669; font-weight: 600;")
                self.percentage_label.setStyleSheet("color: #059669; font-weight: 600;")
            elif remaining < Decimal(str(self.total_amount * 0.1)):
                self.remaining_label.setStyleSheet("color: #d97706; font-weight: 600;")
                self.percentage_label.setStyleSheet("color: #d97706; font-weight: 600;")
            else:
                self.remaining_label.setStyleSheet("color: #dc2626; font-weight: 600;")
                self.percentage_label.setStyleSheet("color: #dc2626; font-weight: 600;")

            # Stage-limit real-time indicator
            if hasattr(self, "stage_limit_label"):
                limit = self._get_stage_limit()
                if limit is not None:
                    try:
                        entered = float(self.amount_edit.text() or "0")
                        if entered > limit + 0.005:
                            self.stage_limit_label.setText(
                                f"⚠ Exceeds stage limit of ${limit:,.2f} — cannot save"
                            )
                            self.stage_limit_label.setStyleSheet(
                                "font-size: 11px; color: #dc2626; font-weight: 600; padding: 0px 2px;"
                            )
                        else:
                            self.stage_limit_label.setText(f"Max allowed for this stage: ${limit:,.2f}")
                            self.stage_limit_label.setStyleSheet(
                                "font-size: 11px; color: #64748b; padding: 0px 2px;"
                            )
                    except (TypeError, ValueError):
                        pass

        except (InvalidOperation, ValueError):
            pass
    
    def _save_payment(self):
        """Save the payment"""
        try:
            # Validate inputs
            amount_text = self.amount_edit.text().strip()
            if not amount_text:
                QtWidgets.QMessageBox.warning(self, "Error", "Please enter a payment amount.")
                return
            
            amount = float(amount_text)
            if amount <= 0:
                QtWidgets.QMessageBox.warning(self, "Error", "Payment amount must be greater than 0.")
                return
            
            if not self.date_edit.date().isValid():
                QtWidgets.QMessageBox.warning(self, "Error", "Please enter a valid payment date.")
                return
            if self.date_edit.date() > QtCore.QDate.currentDate():
                QtWidgets.QMessageBox.warning(
                    self, "Invalid Date",
                    "Payment date cannot be in the future.\nPlease select today or an earlier date."
                )
                self.date_edit.setFocus()
                return
            date_text = self.date_edit.date().toString("MM-dd-yyyy")
            
            payment_method = self.method_combo.currentText()
            notes = self.notes_edit.toPlainText().strip()
            invoice_data = self.invoice_combo.currentData() or {}
            invoice_number = invoice_data.get("invoice_number", "")
            payment_stage = invoice_data.get("stage", "")
            # For edits, always fall back to the original stage/invoice when the
            # combo resolved to "Manual" or has no stage (Tax/fully-paid row).
            if self.edit_payment and not payment_stage:
                invoice_number = invoice_number or getattr(self.edit_payment, "invoice_number", "")
                payment_stage = getattr(self.edit_payment, "payment_stage", "")
            if self.invoice_rows and not payment_stage and not self.edit_payment:
                QtWidgets.QMessageBox.warning(self, "Error", "Please select a payment stage.")
                return
            # Enforce stage limit for both new and edit payments
            limit = self._get_stage_limit()
            if payment_stage and limit is not None:
                if amount > limit + 0.005:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Payment Amount Exceeds Stage Limit",
                        f"The payment amount ${amount:,.2f} exceeds the maximum allowed "
                        f"for the '{payment_stage}' stage (${limit:,.2f}).\n\n"
                        "Please enter an amount equal to or less than the stage limit."
                    )
                    self.amount_edit.setFocus()
                    self.amount_edit.selectAll()
                    return
            
            # Show saving state immediately
            self.save_btn.setEnabled(False)
            orig_text = self.save_btn.text()
            self.save_btn.setText("Saving...")
            self.save_btn.setStyleSheet(self.save_btn.styleSheet() + "background:#64748b;")
            QtWidgets.QApplication.processEvents()

            try:
                if self.edit_payment:
                    success = self.payment_tracker.update_payment(
                        self.edit_payment.payment_id,
                        amount=amount,
                        payment_date=date_text,
                        payment_method=payment_method,
                        notes=notes,
                        invoice_number=invoice_number,
                        payment_stage=payment_stage
                    )
                    if success:
                        self.payment_added.emit(self.project_number, amount)
                        self.accept()
                    else:
                        self.save_btn.setText(orig_text)
                        self.save_btn.setEnabled(True)
                        self.save_btn.setStyleSheet(self.save_btn.styleSheet().replace("background:#64748b;", ""))
                        QtWidgets.QMessageBox.critical(self, "Error", "Failed to update payment.")
                else:
                    success = self.payment_tracker.add_payment(
                        self.project_number,
                        amount,
                        date_text,
                        payment_method,
                        notes,
                        invoice_number=invoice_number,
                        payment_stage=payment_stage
                    )
                    if success:
                        self.payment_added.emit(self.project_number, amount)
                        self.accept()
                    else:
                        self.save_btn.setText(orig_text)
                        self.save_btn.setEnabled(True)
                        self.save_btn.setStyleSheet(self.save_btn.styleSheet().replace("background:#64748b;", ""))
                        QtWidgets.QMessageBox.critical(self, "Error", "Failed to add payment.")
            except Exception as inner_e:
                self.save_btn.setText(orig_text)
                self.save_btn.setEnabled(True)
                self.save_btn.setStyleSheet(self.save_btn.styleSheet().replace("background:#64748b;", ""))
                raise inner_e

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")


class PaymentHistoryDialog(QtWidgets.QDialog):
    """Dialog to view payment history for a project"""

    payments_changed = pyqtSignal(str)  # emits project_number after any add/edit/delete

    def __init__(self, parent=None, project_number: str = "",
                 project_name: str = "", total_amount: float = 0.0,
                 invoice_rows=None):
        super().__init__(parent)
        self.project_number = project_number
        self.project_name = project_name
        self.total_amount = total_amount
        self.invoice_rows = invoice_rows or []
        self.payment_tracker = get_payment_tracker()
        
        self.setWindowTitle(f"Payment History - {project_number}")
        self.resize(1280, 700)
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setStyleSheet("""
            QDialog {
                background: #f8fafc;
            }
            QTableWidget {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                gridline-color: #f3f4f6;
                font-size: 12px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QTableWidget::item {
                padding: 8px 12px;
            }
            QTableWidget::item:selected {
                background: #dbeafe;
                color: #1e40af;
            }
            QHeaderView::section {
                background: #f9fafb;
                color: #374151;
                font-weight: 600;
                padding: 8px 12px;
                border: none;
                border-bottom: 1px solid #e5e7eb;
                font-size: 12px;
            }
        """)
        
        self._init_ui()
        self._load_payments()

        # Auto-refresh: redraw from in-memory tracker state so external changes
        # (e.g. auto-recorded payments from invoice history) appear within 2 s.
        self._auto_refresh_timer = QtCore.QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._redraw_payments_table)
        self._auto_refresh_timer.start(2000)

    def closeEvent(self, event):
        """Stop the auto-refresh timer so it can't fire after the dialog is hidden."""
        try:
            self._auto_refresh_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)


    def _redraw_payments_table(self):
        """Redraw the payments table and summary from current tracker state (no emit)."""
        # Exclude Tax-stage payments — tax is managed from invoice history only
        payments = [
            p for p in self.payment_tracker.get_project_payments(self.project_number)
            if (p.payment_stage or "").strip().lower() != "tax"
        ]
        project_payments = [
            p for p in self.payment_tracker.get_project_payments(self.project_number)
            if (p.payment_stage or "").strip().lower() != "tax"
        ]
        total_paid = sum(float(p.amount) for p in project_payments)
        remaining = max(self.total_amount - total_paid, 0)
        pct = (
            (total_paid / self.total_amount) * 100
            if self.total_amount > 0 else 0
        )
        self.paid_amount_label.setText(f"Paid: ${total_paid:,.2f}")
        self.remaining_label.setText(f"Remaining: ${max(remaining, 0):,.2f}")
        self.progress_label.setText(f"Progress: {pct:.1f}%")
        self.progress_bar.setValue(min(int(pct), 100))
        if hasattr(self, "add_payment_btn"):
            self.add_payment_btn.setEnabled(remaining > 0)
        # Repopulate the payments table
        self.payments_table.clearSpans()
        self.payments_table.setRowCount(0)   # wipe all rows + cell widgets first
        self.payments_table.setRowCount(len(payments) if payments else 1)
        if not payments:
            empty_item = QtWidgets.QTableWidgetItem("No payments recorded yet.")
            empty_item.setTextAlignment(QtCore.Qt.AlignCenter)
            empty_item.setForeground(QtGui.QColor("#94a3b8"))
            f = empty_item.font()
            f.setItalic(True)
            empty_item.setFont(f)
            self.payments_table.setItem(0, 0, empty_item)
            self.payments_table.setSpan(0, 0, 1, self.payments_table.columnCount())
            self.payments_table.setRowHeight(0, 52)
            return
        sorted_payments = sorted(payments, key=_payment_sort_key)
        running_balance = Decimal(str(self.total_amount))
        for row, payment in enumerate(sorted_payments):
            running_balance -= payment.amount
            balance_after = max(running_balance, Decimal("0"))
            col_data = [
                (payment.invoice_number or "Manual", QtCore.Qt.AlignCenter),
                (_clean_stage_label(payment.payment_stage), QtCore.Qt.AlignCenter),
                (payment.payment_date, QtCore.Qt.AlignCenter),
                (f"${float(payment.amount):,.2f}", QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter),
                (f"${float(balance_after):,.2f}", QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter),
                (payment.payment_method, QtCore.Qt.AlignCenter),
                (payment.notes or "", QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter),
            ]
            for col, (value, align) in enumerate(col_data):
                cell = QtWidgets.QTableWidgetItem(str(value))
                cell.setTextAlignment(align)
                if col == 4:
                    if balance_after <= 0:
                        cell.setForeground(QtGui.QColor("#059669"))
                        font = cell.font(); font.setBold(True); cell.setFont(font)
                    else:
                        cell.setForeground(QtGui.QColor("#b45309"))
                        font = cell.font(); font.setBold(True); cell.setFont(font)
                self.payments_table.setItem(row, col, cell)
            # col 7 – Actions (Edit / Delete)
            _aw = QtWidgets.QWidget()
            _aw.setStyleSheet("background:transparent;")
            _al = QtWidgets.QHBoxLayout(_aw)
            _al.setContentsMargins(6, 4, 6, 4)
            _al.setSpacing(6)
            _al.setAlignment(QtCore.Qt.AlignCenter)
            _eb = QtWidgets.QPushButton("Edit")
            _eb.setFixedSize(54, 32)
            _eb.setStyleSheet("""
                QPushButton { background-color:#2563eb; color:white; border:none;
                    border-radius:6px; font-size:12px; font-weight:800; padding:0px; }
                QPushButton:hover { background-color:#1d4ed8; }
                QPushButton:pressed { background-color:#1e40af; }
            """)
            _eb.clicked.connect(lambda _, p=payment: self._edit_payment(p))
            _db = QtWidgets.QPushButton("Delete")
            _db.setFixedSize(62, 32)
            _db.setStyleSheet("""
                QPushButton { background-color:#dc2626; color:white; border:none;
                    border-radius:6px; font-size:12px; font-weight:800; padding:0px; }
                QPushButton:hover { background-color:#b91c1c; }
                QPushButton:pressed { background-color:#991b1b; }
            """)
            _db.clicked.connect(lambda _, p=payment: self._delete_payment(p))
            _al.addWidget(_eb); _al.addWidget(_db)
            self.payments_table.setCellWidget(row, 7, _aw)
            self.payments_table.setRowHeight(row, 48)

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Project Info
        info_label = QtWidgets.QLabel(f"Project: {self.project_number} - {self.project_name}")
        info_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #1e293b;")
        layout.addWidget(info_label)
        
        # Summary cards row
        summary_layout = QtWidgets.QHBoxLayout()
        summary_layout.setSpacing(8)

        self.total_amount_label = QtWidgets.QLabel(f"Total: ${self.total_amount:,.2f}")
        self.paid_amount_label  = QtWidgets.QLabel("Paid: $0.00")
        self.remaining_label    = QtWidgets.QLabel("Remaining: $0.00")
        self.progress_label     = QtWidgets.QLabel("Progress: 0.0%")

        for label in [self.total_amount_label, self.paid_amount_label,
                      self.remaining_label, self.progress_label]:
            label.setStyleSheet(
                "font-size: 13px; font-weight: 600; padding: 8px 12px;"
                "background: white; border-radius: 6px;"
            )

        summary_layout.addWidget(self.total_amount_label)
        summary_layout.addWidget(self.paid_amount_label)
        summary_layout.addWidget(self.remaining_label)
        summary_layout.addWidget(self.progress_label)
        summary_layout.addStretch()
        layout.addLayout(summary_layout)

        # Progress bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #e2e8f0;
                border-radius: 5px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0f766e, stop:1 #059669);
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)

        invoice_label = QtWidgets.QLabel("Payment Schedule")
        invoice_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #0f172a;")
        layout.addWidget(invoice_label)

        self.invoice_table = QtWidgets.QTableWidget()
        self.invoice_table.setColumnCount(6)
        self.invoice_table.setHorizontalHeaderLabels([
            "Stage", "Planned", "Paid", "Remaining", "Invoice #", "Status"
        ])
        invoice_header = self.invoice_table.horizontalHeader()
        invoice_header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        invoice_header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        invoice_header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        invoice_header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        invoice_header.setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        invoice_header.setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
        self.invoice_table.setColumnWidth(1, 120)
        self.invoice_table.setColumnWidth(2, 110)
        self.invoice_table.setColumnWidth(3, 120)
        self.invoice_table.setColumnWidth(4, 145)
        self.invoice_table.setColumnWidth(5, 120)
        self.invoice_table.verticalHeader().setVisible(False)
        self.invoice_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.invoice_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.invoice_table.setAlternatingRowColors(True)
        self.invoice_table.setFixedHeight(138)
        layout.addWidget(self.invoice_table)
        self._load_invoices()
        
        # Payments Table
        payments_label = QtWidgets.QLabel("Payments Received")
        payments_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #0f172a;")
        layout.addWidget(payments_label)

        self.payments_table = QtWidgets.QTableWidget()
        self.payments_table.setColumnCount(8)
        self.payments_table.setHorizontalHeaderLabels([
            "Invoice #", "Term", "Payment Date", "Amount", "Balance After", "Method", "Notes", "Actions"
        ])

        header = self.payments_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)    # Invoice #
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)    # Term
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)    # Date
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)    # Amount
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)    # Balance After
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)    # Method
        header.setSectionResizeMode(6, QtWidgets.QHeaderView.Stretch)  # Notes
        header.setSectionResizeMode(7, QtWidgets.QHeaderView.Fixed)    # Actions

        self.payments_table.setColumnWidth(0, 175)  # Invoice #
        self.payments_table.setColumnWidth(1, 190)  # Term
        self.payments_table.setColumnWidth(2, 160)  # Payment Date
        self.payments_table.setColumnWidth(3, 145)  # Amount
        self.payments_table.setColumnWidth(4, 135)  # Balance After
        self.payments_table.setColumnWidth(5, 120)  # Method
        self.payments_table.setColumnWidth(7, 160)  # Actions

        self.payments_table.verticalHeader().setVisible(False)
        self.payments_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.payments_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.payments_table.setAlternatingRowColors(True)
        self.payments_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.payments_table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

        layout.addWidget(self.payments_table)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self.add_payment_btn = QtWidgets.QPushButton("Add Payment")
        self.add_payment_btn.clicked.connect(self._add_payment)
        self.add_payment_btn.setStyleSheet("""
            QPushButton {
                background: #0f766e;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 9px 18px;
                font-size: 13px;
                font-weight: 800;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QPushButton:hover { background: #0d625c; }
            QPushButton:pressed { background: #0a4f49; }
        """)
        
        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: #64748b;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 9px 18px;
                font-size: 13px;
                font-weight: 800;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            QPushButton:hover { background: #475569; }
        """)
        
        button_layout.addWidget(self.add_payment_btn)
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)

    def _load_invoices(self):
        self.invoice_table.clearSpans()
        self.invoice_table.setRowCount(len(self.invoice_rows) if self.invoice_rows else 1)
        if not self.invoice_rows:
            item = QtWidgets.QTableWidgetItem("No payment schedule found for this project yet.")
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            item.setForeground(QtGui.QColor("#64748b"))
            self.invoice_table.setItem(0, 0, item)
            self.invoice_table.setSpan(0, 0, 1, self.invoice_table.columnCount())
            self.invoice_table.setRowHeight(0, 38)
            return

        for row, invoice in enumerate(self.invoice_rows):
            planned_value = float(invoice.get("amount_value", 0) or 0)
            paid_value = float(invoice.get("paid_value", 0) or 0)
            remaining_value = float(invoice.get("remaining_value", planned_value) or 0)
            values = [
                invoice.get("stage", ""),
                f"${planned_value:,.2f}",
                f"${paid_value:,.2f}",
                f"${remaining_value:,.2f}",
                invoice.get("invoice_number", "") or "Not Created",
                invoice.get("status", ""),
            ]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value or "N/A"))
                item.setToolTip(str(value or "N/A"))
                align = QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter if col in (1, 2, 3) else QtCore.Qt.AlignCenter
                item.setTextAlignment(align)
                if col == 3 and remaining_value <= 0:
                    item.setForeground(QtGui.QColor("#059669"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.invoice_table.setItem(row, col, item)
            self.invoice_table.setRowHeight(row, 34)
     
    @staticmethod
    def _normalize_stage_key(stage: str) -> str:
        """Collapse any stage label to a canonical keyword for fuzzy comparison."""
        lo = (stage or "").strip().lower()
        if any(x in lo for x in ("down payment", "deposit", "50%")):
            return "down_payment"
        if any(x in lo for x in ("remaining balance", "remaining", "balance")):
            return "remaining_balance"
        if any(x in lo for x in ("1st installment", "first installment", "payment 1", "term 1")):
            return "installment_1"
        if any(x in lo for x in ("2nd installment", "second installment", "payment 2", "term 2")):
            return "installment_2"
        if any(x in lo for x in ("3rd installment", "third installment", "payment 3", "term 3")):
            return "installment_3"
        if any(x in lo for x in ("final payment", "4th", "fourth", "term 4")):
            return "final_payment"
        if any(x in lo for x in ("full amount", "full payment", "due payment")):
            return "full_amount"
        return lo

    def _refresh_invoice_rows(self):
        """Recompute paid_value / remaining_value for each invoice row from live payments.

        Uses normalised stage-key matching so labels like 'Down Payment (50%)' and
        'Down Payment' are treated as the same stage.  Callers must reload the
        payment tracker from disk before calling this method.
        """
        if not self.invoice_rows:
            return
        # Exclude Tax-stage entries — tax is tracked separately and must never
        # inflate the project-stage "Paid" amount shown in the schedule table.
        payments = [
            p for p in self.payment_tracker.get_project_payments(self.project_number)
            if (p.payment_stage or "").strip().lower() != "tax"
        ]
        one_row = len(self.invoice_rows) == 1

        for inv_row in self.invoice_rows:
            stage = inv_row.get("stage", "") or ""
            stage_key = self._normalize_stage_key(stage)
            planned = float(inv_row.get("amount_value", 0) or 0)

            if one_row:
                matched = payments
            else:
                matched = []

                invoice_no = str(inv_row.get("invoice_number", "") or "").strip()

                for p in payments:
                    payment_stage_key = self._normalize_stage_key(str(p.payment_stage or ""))

                    # First priority: invoice number match
                    invoice_match = (
                        invoice_no
                        and str(p.invoice_number or "").strip() == invoice_no
                    )

                    # Second priority: stage match
                    stage_match = (
                        payment_stage_key == stage_key
                        or (stage_key and stage_key in payment_stage_key)
                        or (payment_stage_key and payment_stage_key in stage_key)
                    )

                    # Accept either exact invoice match or stage match
                    if invoice_match or stage_match:
                        matched.append(p)

            paid = sum(float(p.amount) for p in matched)
            remaining = max(planned - paid, 0)
            inv_row["paid_value"] = paid
            inv_row["remaining_value"] = remaining

            if remaining <= 0 and planned > 0:
                inv_row["status"] = "Paid"
            elif paid > 0:
                inv_row["status"] = "Partially Paid"
            else:
                # Revert to invoice status if no payments matched
                if not inv_row.get("invoice_number"):
                    inv_row["status"] = "Not Invoiced"

    def _find_balance_sheet_tab(self):
        """Walk the widget parent chain to find the balance_sheet_tab."""
        w = self.parent()
        while w is not None:
            bs = getattr(w, "balance_sheet_tab", None)
            if bs is not None:
                return bs
            mw = getattr(w, "main_window", None)
            if mw is not None:
                bs = getattr(mw, "balance_sheet_tab", None)
                if bs is not None:
                    return bs
            w = w.parent() if hasattr(w, "parent") else None
        return None

    @staticmethod
    def _parse_payment_date(date_str: str):
        """Parse a payment date string into a datetime for comparison."""
        for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                pass
        return datetime.min

    def _latest_payment_date(self, payments) -> str:
        """Return the date string of the most-recent payment, properly parsed."""
        best_dt = datetime.min
        best_str = "N/A"
        for p in payments:
            d = p.payment_date
            if not d:
                continue
            dt = self._parse_payment_date(d)
            if dt > best_dt:
                best_dt = dt
                best_str = d
        return best_str

    def _update_balance_sheet_after_payment_change(self):
        """Balance sheet status/received_date is now managed exclusively by the
        invoice_status_changed signal emitted from _recompute_invoice_status in
        payment_tracker.py. That path uses the same logic as invoice history
        (Paid/Partially Paid/Unpaid/Overdue + due-date check) so both tabs stay
        in sync without any duplicate custom logic here."""
        return

    def _load_payments(self, *_args):
        """Refresh the payments display from the in-memory tracker state.
        No network call needed — tracker.payments is always updated optimistically
        before any Firebase write completes."""
        self._refresh_invoice_rows()
        self._update_balance_sheet_after_payment_change()
        self._load_invoices()
        # Exclude Tax-stage payments — tax is managed from invoice history only
        payments = [
            p for p in self.payment_tracker.get_project_payments(self.project_number)
            if (p.payment_stage or "").strip().lower() != "tax"
        ]
        self.payments_changed.emit(self.project_number)

        project_payments = [
            p for p in self.payment_tracker.get_project_payments(self.project_number)
            if (p.payment_stage or "").strip().lower() != "tax"
        ]
        total_paid = sum(float(p.amount) for p in project_payments)
        remaining = max(self.total_amount - total_paid, 0)
        pct = (
            (total_paid / self.total_amount) * 100
            if self.total_amount > 0 else 0
        )

        # Summary labels
        self.paid_amount_label.setText(f"Paid: ${total_paid:,.2f}")
        self.remaining_label.setText(f"Remaining: ${max(remaining, 0):,.2f}")
        self.progress_label.setText(f"Progress: {pct:.1f}%")
        self.progress_bar.setValue(min(int(pct), 100))

        paid_lbl_ss = (
            "font-size:13px;font-weight:600;padding:8px 12px;border-radius:6px;"
        )
        if remaining <= 0:
            self.remaining_label.setStyleSheet(paid_lbl_ss + "background:#dcfce7;color:#166534;")
            self.progress_label.setStyleSheet(paid_lbl_ss + "background:#dcfce7;color:#166534;")
        else:
            self.remaining_label.setStyleSheet(paid_lbl_ss + "background:#fef2f2;color:#dc2626;")
            self.progress_label.setStyleSheet(paid_lbl_ss + "background:#fef2f2;color:#dc2626;")
        if hasattr(self, "add_payment_btn"):
            self.add_payment_btn.setEnabled(remaining > 0)
            self.add_payment_btn.setToolTip("" if remaining > 0 else "This project is fully paid.")

        # Populate table — sort payments by date ascending for running-balance calc
        self.payments_table.clearSpans()
        self.payments_table.setRowCount(0)   # wipe all rows + cell widgets first
        self.payments_table.setRowCount(len(payments) if payments else 1)

        if not payments:
            empty_item = QtWidgets.QTableWidgetItem("No payments recorded yet.")
            empty_item.setTextAlignment(QtCore.Qt.AlignCenter)
            empty_item.setForeground(QtGui.QColor("#94a3b8"))
            f = empty_item.font()
            f.setItalic(True)
            empty_item.setFont(f)
            self.payments_table.setItem(0, 0, empty_item)
            self.payments_table.setSpan(0, 0, 1, self.payments_table.columnCount())
            self.payments_table.setRowHeight(0, 52)
            return

        sorted_payments = sorted(payments, key=_payment_sort_key)
        running_balance = Decimal(str(self.total_amount))

        for row, payment in enumerate(sorted_payments):
            running_balance -= payment.amount
            balance_after = max(running_balance, Decimal("0"))

            # col 0 – Invoice #
            col_data = [
                (payment.invoice_number or "Manual",              QtCore.Qt.AlignCenter),
                (_clean_stage_label(payment.payment_stage),       QtCore.Qt.AlignCenter),
                (payment.payment_date,                 QtCore.Qt.AlignCenter),
                (f"${float(payment.amount):,.2f}",     QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter),
                (f"${float(balance_after):,.2f}",      QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter),
                (payment.payment_method,               QtCore.Qt.AlignCenter),
                (payment.notes or "",                  QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter),
            ]
            for col, (value, align) in enumerate(col_data):
                cell = QtWidgets.QTableWidgetItem(str(value))
                cell.setTextAlignment(align)
                cell.setToolTip(str(value))
                if col == 0:
                    cell.setToolTip(f"Payment ID: {payment.payment_id}")
                # Colour the Balance-After cell: green when 0, amber otherwise
                if col == 4:
                    if balance_after <= 0:
                        cell.setForeground(QtGui.QColor("#059669"))
                        font = cell.font(); font.setBold(True); cell.setFont(font)
                    else:
                        cell.setForeground(QtGui.QColor("#b45309"))
                        font = cell.font(); font.setBold(True); cell.setFont(font)
                self.payments_table.setItem(row, col, cell)

            # col 7 – Actions
            actions_widget = QtWidgets.QWidget()
            actions_layout = QtWidgets.QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(6, 4, 6, 4)
            actions_layout.setSpacing(6)
            actions_layout.setAlignment(QtCore.Qt.AlignCenter)

            edit_btn = QtWidgets.QPushButton("Edit")
            edit_btn.setFixedSize(54, 32)
            edit_btn.setStyleSheet("""
                QPushButton { background-color:#2563eb; color:white; border:none;
                    border-radius:6px; font-size:12px; font-weight:800; padding:0px; }
                QPushButton:hover { background-color:#1d4ed8; }
                QPushButton:pressed { background-color:#1e40af; }
            """)
            edit_btn.clicked.connect(lambda _, p=payment: self._edit_payment(p))

            delete_btn = QtWidgets.QPushButton("Delete")
            delete_btn.setFixedSize(62, 32)
            delete_btn.setStyleSheet("""
                QPushButton { background-color:#dc2626; color:white; border:none;
                    border-radius:6px; font-size:12px; font-weight:800; padding:0px; }
                QPushButton:hover { background-color:#b91c1c; }
                QPushButton:pressed { background-color:#991b1b; }
            """)
            delete_btn.clicked.connect(lambda _, p=payment: self._delete_payment(p))

            actions_layout.addWidget(edit_btn)
            actions_layout.addWidget(delete_btn)

            self.payments_table.setCellWidget(row, 7, actions_widget)
            self.payments_table.setRowHeight(row, 48)
    
    def _find_projects_tab(self):
        """Walk parent chain to find the ProjectNumberGeneratorTab (has _invoice_sync_done)."""
        obj = self.parent()
        while obj is not None:
            if hasattr(obj, '_invoice_sync_done'):
                return obj
            try:
                obj = obj.parent()
            except Exception:
                break
        return None

    def _wait_for_sync_then(self, msg: str, on_done):
        """Show a progress dialog and call on_done only after all Firebase syncing completes.

        Hooks into the ProjectNumberGeneratorTab._invoice_sync_done signal which fires
        after _auto_sync_invoice_statuses finishes updating invoice history and balance sheet.
        Falls back to a 6-second timeout so it never blocks forever.
        """
        progress = QtWidgets.QProgressDialog(msg, None, 0, 0, self)
        progress.setWindowTitle("Syncing...")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QtWidgets.QApplication.processEvents()

        tab = self._find_projects_tab()
        timeout_timer = QtCore.QTimer(self)
        timeout_timer.setSingleShot(True)
        _finished = [False]

        def _finish():
            if _finished[0]:
                return
            _finished[0] = True
            try:
                if tab:
                    tab._invoice_sync_done.disconnect(_on_sync_done)
            except Exception:
                pass
            timeout_timer.stop()
            progress.close()
            QtWidgets.QApplication.processEvents()
            on_done()

        def _on_sync_done():
            _finish()

        timeout_timer.timeout.connect(_finish)
        timeout_timer.start(6000)

        if tab:
            tab._invoice_sync_done.connect(_on_sync_done)
        else:
            QtCore.QTimer.singleShot(1200, _finish)

    def _add_payment(self):
        """Open dialog to add new payment"""
        self._refresh_invoice_rows()
        self._load_invoices()
        summary = self.payment_tracker.get_payment_summary(self.project_number, self.total_amount)
        remaining = float(summary['remaining'])
        self.remaining_label.setText(f"Remaining: ${max(remaining, 0):,.2f}")
        if hasattr(self, "add_payment_btn"):
            self.add_payment_btn.setEnabled(remaining > 0)
            if remaining <= 0:
                return  # nothing left to pay

        dialog = PaymentDialog(
            self,
            self.project_number,
            self.project_name,
            self.total_amount,
            invoice_rows=self.invoice_rows
        )
        dialog.payment_added.connect(self._load_payments)
        result = dialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            self._show_success_toast("Payment saved successfully!")

    def _edit_payment(self, payment: Payment):
        """Open dialog to edit payment"""
        dialog = PaymentDialog(self, self.project_number, self.project_name,
                             self.total_amount, edit_payment=payment,
                             invoice_rows=self.invoice_rows)
        dialog.payment_added.connect(self._load_payments)
        result = dialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            self._show_success_toast("Payment updated successfully!")

    def _show_success_toast(self, message: str):
        """Show a brief non-blocking success notification near the top of the dialog."""
        toast = QtWidgets.QLabel(f"✓  {message}", self)
        toast.setStyleSheet("""
            QLabel {
                background: #d1fae5;
                color: #065f46;
                border: 1px solid #6ee7b7;
                border-radius: 8px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 700;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
        """)
        # Pass through mouse events so the toast never blocks buttons underneath
        toast.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        toast.setAlignment(QtCore.Qt.AlignCenter)
        toast.adjustSize()
        # Position at top-centre so it doesn't overlap bottom buttons
        x = (self.width() - toast.width()) // 2
        y = 12
        toast.move(x, y)
        toast.show()
        toast.raise_()
        QtCore.QTimer.singleShot(2500, toast.deleteLater)

    def _cascade_refresh_after_change(self):
        """Immediately refresh invoice history, balance sheet and annual summary
        after any payment add / edit / delete."""
        try:
            # Prefer the parent tab's main_window reference (most direct)
            parent_tab = self.parent()
            main_win = getattr(parent_tab, "main_window", None)
            if main_win is None:
                # Fall back to walking the QObject parent chain
                main_win = parent_tab
                while main_win and not hasattr(main_win, "balance_sheet_tab"):
                    main_win = main_win.parent()

            if not main_win:
                return

            # Balance sheet (includes annual summary via load_all_financial_data)
            for attr in ("balance_sheet_tab", "finance_overview_tab"):
                tab = getattr(main_win, attr, None)
                if tab and hasattr(tab, "refresh_data"):
                    try:
                        tab.refresh_data()
                    except Exception:
                        pass

            # Invoice history — creates fresh widget that reads updated Firebase data
            hist_tab = getattr(main_win, "history_tab", None)
            if hist_tab and hasattr(hist_tab, "refresh_invoices_immediately"):
                hist_tab.refresh_invoices_immediately()

        except Exception:
            pass
    
    def _delete_payment(self, payment: Payment):
        """Delete a payment and cascade: removes linked balance-sheet entry,
        reverts the invoice status in invoice history, and refreshes finance tabs."""
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete this payment of ${payment.amount:,.2f}?\n\n"
            f"This will also remove the linked balance-sheet entry and\n"
            f"update the invoice status accordingly.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            success = self.payment_tracker.delete_payment(payment.payment_id)
            if success:
                self._load_payments()
                self._show_success_toast("Payment deleted successfully!")
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "Failed to delete payment.")
