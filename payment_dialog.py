"""Payment Management Dialog - Add/Edit payments for projects"""
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import pyqtSignal
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from payment_tracker import get_payment_tracker, Payment


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
            remaining_value = invoice.get("remaining_value", None)
            is_paid = False
            if remaining_value is not None:
                try:
                    is_paid = float(remaining_value) <= 0
                except (TypeError, ValueError):
                    is_paid = False
            editing_this_stage = (
                self.edit_payment
                and invoice.get("stage", "") == getattr(self.edit_payment, "payment_stage", "")
                and invoice.get("invoice_number", "") == getattr(self.edit_payment, "invoice_number", "")
            )
            if not is_paid or editing_this_stage:
                selectable_rows.append(invoice)

        if selectable_rows and not self.edit_payment:
            selectable_rows = selectable_rows[:1]

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
        payment_layout.addRow("Payment Stage:", self.invoice_combo)
        
        # Payment Amount
        self.amount_edit = QtWidgets.QLineEdit()
        self.amount_edit.setPlaceholderText("0.00")
        self.amount_edit.setMinimumHeight(36)
        self.amount_edit.textChanged.connect(self._update_remaining)
        payment_layout.addRow("Payment Amount ($):", self.amount_edit)
        
        # Payment Date
        self.date_edit = QtWidgets.QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM-dd-yyyy")
        self.date_edit.setDate(QtCore.QDate.currentDate())
        self.date_edit.setMinimumHeight(36)
        payment_layout.addRow("Payment Date:", self.date_edit)
        
        # Payment Method
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems([
            "Cash", "Check", "Bank Transfer", "Credit Card", 
            "Wire Transfer", "Other"
        ])
        self.method_combo.setMinimumHeight(36)
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
    
    def _load_existing_data(self):
        """Load data if editing existing payment"""
        if self.edit_payment:
            self.amount_edit.setText(str(float(self.edit_payment.amount)))
            self._set_payment_date(self.edit_payment.payment_date)
            self.method_combo.setCurrentText(self.edit_payment.payment_method)
            self.notes_edit.setText(self.edit_payment.notes)
            for index in range(self.invoice_combo.count()):
                data = self.invoice_combo.itemData(index) or {}
                if (
                    data.get("invoice_number") == getattr(self.edit_payment, "invoice_number", "")
                    and data.get("stage") == getattr(self.edit_payment, "payment_stage", "")
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

    def _prefill_stage_amount(self):
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
        """Update remaining amount display"""
        try:
            amount = Decimal(self.amount_edit.text() or "0")
            existing_summary = self.payment_tracker.get_payment_summary(
                self.project_number, self.total_amount
            )
            
            if self.edit_payment:
                # Subtract old payment amount if editing
                total_paid = existing_summary['total_paid'] - self.edit_payment.amount + amount
            else:
                total_paid = existing_summary['total_paid'] + amount
            
            remaining = Decimal(str(self.total_amount)) - total_paid
            percentage = float(total_paid / Decimal(str(self.total_amount)) * 100) if self.total_amount > 0 else 0
            
            self.total_paid_label.setText(f"${total_paid:,.2f}")
            self.remaining_label.setText(f"${remaining:,.2f}")
            self.percentage_label.setText(f"{percentage:.1f}%")
            
            # Color coding
            if remaining <= 0:
                self.remaining_label.setStyleSheet("color: #059669; font-weight: 600;")
                self.percentage_label.setStyleSheet("color: #059669; font-weight: 600;")
            elif remaining < Decimal(str(self.total_amount * 0.1)):  # Less than 10% remaining
                self.remaining_label.setStyleSheet("color: #d97706; font-weight: 600;")
                self.percentage_label.setStyleSheet("color: #d97706; font-weight: 600;")
            else:
                self.remaining_label.setStyleSheet("color: #dc2626; font-weight: 600;")
                self.percentage_label.setStyleSheet("color: #dc2626; font-weight: 600;")
                
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
            date_text = self.date_edit.date().toString("MM-dd-yyyy")
            
            payment_method = self.method_combo.currentText()
            notes = self.notes_edit.toPlainText().strip()
            invoice_data = self.invoice_combo.currentData() or {}
            invoice_number = invoice_data.get("invoice_number", "")
            payment_stage = invoice_data.get("stage", "")
            if self.invoice_rows and not payment_stage:
                QtWidgets.QMessageBox.warning(self, "Error", "Please select a payment stage.")
                return
            stage_remaining = invoice_data.get("remaining_value", None)
            if not self.edit_payment and payment_stage and stage_remaining not in (None, ""):
                try:
                    stage_remaining_value = float(stage_remaining)
                    if amount > stage_remaining_value + 0.01:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Payment Amount",
                            f"{payment_stage} only has ${stage_remaining_value:,.2f} remaining.\n\n"
                            "Save that amount for this stage, then add another payment for the next installment."
                        )
                        return
                except (TypeError, ValueError):
                    pass
            
            if self.edit_payment:
                # Update existing payment
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
                    QtWidgets.QMessageBox.information(self, "Success", "Payment updated successfully!")
                    self.accept()
                else:
                    QtWidgets.QMessageBox.critical(self, "Error", "Failed to update payment.")
            else:
                # Add new payment
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
                    QtWidgets.QMessageBox.information(self, "Success", "Payment added successfully!")
                    self.payment_added.emit(self.project_number, amount)
                    self.accept()
                else:
                    QtWidgets.QMessageBox.critical(self, "Error", "Failed to add payment.")
        
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

        self.payments_table.setColumnWidth(0, 140)  # Invoice #
        self.payments_table.setColumnWidth(1, 155)  # Term
        self.payments_table.setColumnWidth(2, 130)  # Payment Date
        self.payments_table.setColumnWidth(3, 115)  # Amount
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
     
    def _load_payments(self, *_args):
        """Load and display payments with running balance per row."""
        payments = self.payment_tracker.get_project_payments(self.project_number)
        summary = self.payment_tracker.get_payment_summary(self.project_number, self.total_amount)
        self.payments_changed.emit(self.project_number)

        total_paid = float(summary['total_paid'])
        remaining  = float(summary['remaining'])
        pct        = float(summary['payment_percentage'])

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
        self.payments_table.setRowCount(len(payments) if payments else 1)

        if not payments:
            empty_item = QtWidgets.QTableWidgetItem(
                "No payment records yet. Click Add Payment to enter amount, paid date, and method."
            )
            empty_item.setTextAlignment(QtCore.Qt.AlignCenter)
            empty_item.setForeground(QtGui.QColor("#64748b"))
            self.payments_table.setItem(0, 0, empty_item)
            self.payments_table.setSpan(0, 0, 1, self.payments_table.columnCount())
            self.payments_table.setRowHeight(0, 48)
            return

        sorted_payments = sorted(payments, key=lambda p: p.payment_date or "")
        running_balance = Decimal(str(self.total_amount))

        for row, payment in enumerate(sorted_payments):
            running_balance -= payment.amount
            balance_after = max(running_balance, Decimal("0"))

            # col 0 – Invoice #
            col_data = [
                (payment.invoice_number or "Manual",   QtCore.Qt.AlignCenter),
                (payment.payment_stage or "Manual",    QtCore.Qt.AlignCenter),
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

            _btn_base = """
                QPushButton {
                    border: none; border-radius: 5px;
                    font-size: 12px; font-weight: 800;
                    color: white; padding: 0 10px;
                }
            """
            edit_btn = QtWidgets.QPushButton("Edit")
            edit_btn.setFixedHeight(28)
            edit_btn.setMinimumWidth(54)
            edit_btn.setStyleSheet(_btn_base + "QPushButton { background:#2563eb; } QPushButton:hover { background:#1d4ed8; }")
            edit_btn.clicked.connect(lambda checked, p=payment: self._edit_payment(p))

            delete_btn = QtWidgets.QPushButton("Delete")
            delete_btn.setFixedHeight(28)
            delete_btn.setMinimumWidth(62)
            delete_btn.setStyleSheet(_btn_base + "QPushButton { background:#dc2626; } QPushButton:hover { background:#b91c1c; }")
            delete_btn.clicked.connect(lambda checked, p=payment: self._delete_payment(p))

            actions_layout.addWidget(edit_btn)
            actions_layout.addWidget(delete_btn)

            self.payments_table.setCellWidget(row, 7, actions_widget)
            self.payments_table.setRowHeight(row, 40)
    
    def _add_payment(self):
        """Open dialog to add new payment"""
        dialog = PaymentDialog(
            self,
            self.project_number,
            self.project_name,
            self.total_amount,
            invoice_rows=self.invoice_rows
        )
        dialog.payment_added.connect(self._load_payments)
        dialog.exec_()
    
    def _edit_payment(self, payment: Payment):
        """Open dialog to edit payment"""
        dialog = PaymentDialog(self, self.project_number, self.project_name, 
                             self.total_amount, edit_payment=payment,
                             invoice_rows=self.invoice_rows)
        dialog.payment_added.connect(self._load_payments)
        dialog.exec_()
    
    def _delete_payment(self, payment: Payment):
        """Delete a payment"""
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete this payment of ${payment.amount:,.2f}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            success = self.payment_tracker.delete_payment(payment.payment_id)
            if success:
                QtWidgets.QMessageBox.information(self, "Success", "Payment deleted successfully!")
                self._load_payments()
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "Failed to delete payment.")
