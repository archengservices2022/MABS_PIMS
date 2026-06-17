# quotations_tab.py
from PyQt5 import QtWidgets, QtCore, QtGui
from pathlib import Path
from datetime import datetime
from decimal import Decimal
import json

class QuotationsTab(QtWidgets.QWidget):
    """Quotations Tab - For creating and managing quotations"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.quotation_items = []
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header
        header_frame = QtWidgets.QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2c3e50, stop:1 #3498db);
                border-radius: 8px;
                padding: 15px;
            }
        """)
        header_layout = QtWidgets.QVBoxLayout(header_frame)
        
        title = QtWidgets.QLabel("💰 Quotation Management")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 5px;
            }
        """)
        
        subtitle = QtWidgets.QLabel("Create and manage professional quotations for clients")
        subtitle.setStyleSheet("""
            QLabel {
                color: #ecf0f1;
                font-size: 14px;
                margin-top: 0px;
            }
        """)
        
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header_frame)
        
        # Content Area
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QGridLayout(content_widget)
        content_layout.setSpacing(15)
        
        # Left Column - Quotation Details
        details_group = QtWidgets.QGroupBox("Quotation Details")
        details_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 16px;
                color: #2c3e50;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                margin-top: 1em;
                padding-top: 10px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        details_layout = QtWidgets.QFormLayout(details_group)
        details_layout.setVerticalSpacing(10)
        details_layout.setHorizontalSpacing(10)
        
        # Quotation Number
        self.quotation_number_edit = QtWidgets.QLineEdit()
        self.quotation_number_edit.setPlaceholderText("Auto-generated")
        self.quotation_number_edit.setReadOnly(True)
        
        # Client Selection
        self.client_combo = QtWidgets.QComboBox()
        self.client_combo.addItem("-- Select Client --")
        
        # Quotation Date
        self.quotation_date_edit = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.quotation_date_edit.setCalendarPopup(True)
        
        # Valid Until
        self.valid_until_edit = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addDays(30))
        self.valid_until_edit.setCalendarPopup(True)
        
        # Project Reference
        self.project_ref_edit = QtWidgets.QLineEdit()
        self.project_ref_edit.setPlaceholderText("Optional project reference")
        
        # Terms
        self.terms_combo = QtWidgets.QComboBox()
        self.terms_combo.addItems([
            "Net 15",
            "Net 30",
            "Net 45",
            "Net 60",
            "Due on Receipt",
            "50% Advance, 50% on Completion"
        ])
        
        details_layout.addRow("Quotation No:", self.quotation_number_edit)
        details_layout.addRow("Client:", self.client_combo)
        details_layout.addRow("Quotation Date:", self.quotation_date_edit)
        details_layout.addRow("Valid Until:", self.valid_until_edit)
        details_layout.addRow("Project Ref:", self.project_ref_edit)
        details_layout.addRow("Payment Terms:", self.terms_combo)
        
        content_layout.addWidget(details_group, 0, 0)
        
        # Right Column - Scope & Notes
        scope_group = QtWidgets.QGroupBox("Scope of Work & Notes")
        scope_group.setStyleSheet(details_group.styleSheet())
        scope_layout = QtWidgets.QVBoxLayout(scope_group)
        
        # Scope of Work
        scope_layout.addWidget(QtWidgets.QLabel("Scope of Work:"))
        self.scope_edit = QtWidgets.QTextEdit()
        self.scope_edit.setPlaceholderText("Describe the scope of work, deliverables, and inclusions...")
        self.scope_edit.setMaximumHeight(120)
        scope_layout.addWidget(self.scope_edit)
        
        # Exclusions
        scope_layout.addWidget(QtWidgets.QLabel("Exclusions:"))
        self.exclusions_edit = QtWidgets.QTextEdit()
        self.exclusions_edit.setPlaceholderText("List any exclusions or assumptions...")
        self.exclusions_edit.setMaximumHeight(80)
        scope_layout.addWidget(self.exclusions_edit)
        
        # Additional Notes
        scope_layout.addWidget(QtWidgets.QLabel("Additional Notes:"))
        self.notes_edit = QtWidgets.QTextEdit()
        self.notes_edit.setPlaceholderText("Any additional terms, conditions, or notes...")
        self.notes_edit.setMaximumHeight(80)
        scope_layout.addWidget(self.notes_edit)
        
        content_layout.addWidget(scope_group, 0, 1)
        
        # Middle Section - Quotation Items
        items_group = QtWidgets.QGroupBox("Quotation Items")
        items_group.setStyleSheet(details_group.styleSheet())
        items_layout = QtWidgets.QVBoxLayout(items_group)
        
        # Items Table
        self.items_table = QtWidgets.QTableWidget()
        self.items_table.setColumnCount(5)
        self.items_table.setHorizontalHeaderLabels([
            "Description", "Quantity", "Unit Price", "Total", "Actions"
        ])
        self.items_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.items_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)
        
        # Set column widths
        self.items_table.setColumnWidth(0, 300)  # Description
        self.items_table.setColumnWidth(1, 80)   # Quantity
        self.items_table.setColumnWidth(2, 100)  # Unit Price
        self.items_table.setColumnWidth(3, 100)  # Total
        self.items_table.setColumnWidth(4, 80)   # Actions
        
        items_layout.addWidget(self.items_table)
        
        # Add Item Button
        add_item_btn = QtWidgets.QPushButton("➕ Add Item")
        add_item_btn.clicked.connect(self.add_quotation_item)
        items_layout.addWidget(add_item_btn)
        
        content_layout.addWidget(items_group, 1, 0, 1, 2)
        
        # Bottom Section - Totals & Actions
        totals_group = QtWidgets.QGroupBox("Quotation Summary")
        totals_group.setStyleSheet(details_group.styleSheet())
        totals_layout = QtWidgets.QHBoxLayout(totals_group)
        
        # Totals
        totals_form = QtWidgets.QFormLayout()
        self.subtotal_label = QtWidgets.QLabel("$0.00")
        self.tax_label = QtWidgets.QLabel("$0.00")
        self.total_label = QtWidgets.QLabel("$0.00")
        self.total_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #2c3e50;")
        
        totals_form.addRow("Subtotal:", self.subtotal_label)
        totals_form.addRow("Tax (0%):", self.tax_label)
        totals_form.addRow("Total Amount:", self.total_label)
        
        totals_layout.addLayout(totals_form)
        totals_layout.addStretch()
        
        # Action Buttons
        buttons_layout = QtWidgets.QVBoxLayout()
        
        self.generate_quotation_btn = QtWidgets.QPushButton("📄 Generate Quotation PDF")
        self.generate_quotation_btn.setMinimumHeight(45)
        self.generate_quotation_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #28a745, stop:1 #218838);
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 6px;
                font-size: 14px;
                border: 2px solid #1e7e34;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34ce57, stop:1 #28a745);
            }
        """)
        self.generate_quotation_btn.clicked.connect(self.generate_quotation_pdf)
        
        self.save_draft_btn = QtWidgets.QPushButton("💾 Save as Draft")
        self.save_draft_btn.setMinimumHeight(35)
        self.save_draft_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #17a2b8, stop:1 #138496);
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 5px;
                font-size: 12px;
                border: 2px solid #117a8b;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1abc9c, stop:1 #17a2b8);
            }
        """)
        self.save_draft_btn.clicked.connect(self.save_quotation_draft)
        
        buttons_layout.addWidget(self.generate_quotation_btn)
        buttons_layout.addWidget(self.save_draft_btn)
        
        totals_layout.addLayout(buttons_layout)
        content_layout.addWidget(totals_group, 2, 0, 1, 2)
        
        layout.addWidget(content_widget)
        
        # Generate initial quotation number
        self.generate_quotation_number()
        
        # Connect signals
        self.quotation_date_edit.dateChanged.connect(self.generate_quotation_number)
        self.client_combo.currentTextChanged.connect(self.generate_quotation_number)
    
    def generate_quotation_number(self):
        """Generate a unique quotation number: QUO-YYMMDD-CLI-HHMM."""
        date_str = self.quotation_date_edit.date().toString("yyMMdd")
        time_str = datetime.now().strftime("%H%M")
        client = self.client_combo.currentText()

        if client and client != "-- Select Client --":
            client_code = ''.join(w[0].upper() for w in client.split() if w)[:3]
        else:
            client_code = "GEN"

        quotation_number = f"QUO-{date_str}-{client_code}-{time_str}"
        self.quotation_number_edit.setText(quotation_number)
    
    def add_quotation_item(self):
        """Add a new item to the quotation"""
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)
        
        # Description
        desc_item = QtWidgets.QTableWidgetItem("")
        self.items_table.setItem(row, 0, desc_item)
        
        # Quantity
        qty_item = QtWidgets.QTableWidgetItem("1")
        self.items_table.setItem(row, 1, qty_item)
        
        # Unit Price
        price_item = QtWidgets.QTableWidgetItem("0.00")
        self.items_table.setItem(row, 2, price_item)
        
        # Total (calculated)
        total_item = QtWidgets.QTableWidgetItem("0.00")
        total_item.setFlags(total_item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.items_table.setItem(row, 3, total_item)
        
        # Delete button
        delete_btn = QtWidgets.QPushButton("🗑️")
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 2px 5px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        delete_btn.clicked.connect(lambda: self.delete_quotation_item(row))
        self.items_table.setCellWidget(row, 4, delete_btn)
        
        # Connect signals for auto-calculation
        desc_item.textChanged.connect(self.calculate_totals)
        qty_item.textChanged.connect(self.calculate_totals)
        price_item.textChanged.connect(self.calculate_totals)
    
    def delete_quotation_item(self, row):
        """Delete quotation item"""
        self.items_table.removeRow(row)
        self.calculate_totals()
        # Reconnect signals for remaining rows
        self.reconnect_item_signals()
    
    def reconnect_item_signals(self):
        """Reconnect signals after row deletion"""
        # This would need to be implemented based on your specific needs
        pass
    
    def calculate_totals(self):
        """Calculate quotation totals"""
        subtotal = 0.0
        
        for row in range(self.items_table.rowCount()):
            try:
                qty = float(self.items_table.item(row, 1).text() or 0)
                price = float(self.items_table.item(row, 2).text() or 0)
                total = qty * price
                subtotal += total
                
                # Update total cell
                total_item = self.items_table.item(row, 3)
                if total_item:
                    total_item.setText(f"{total:.2f}")
            except (ValueError, AttributeError):
                continue
        
        # Update summary
        self.subtotal_label.setText(f"${subtotal:.2f}")
        self.total_label.setText(f"${subtotal:.2f}")
    
    def generate_quotation_pdf(self):
        """Generate quotation PDF"""
        if not self.validate_quotation():
            return
        
        QtWidgets.QMessageBox.information(
            self, "Quotation PDF", 
            "Quotation PDF generation would be implemented here."
        )
    
    def save_quotation_draft(self):
        """Save quotation as draft"""
        if not self.validate_quotation():
            return
        
        quotation_data = self.get_quotation_data()
        quotation_data["status"] = "Draft"
        
        # Save to Firebase
        if hasattr(self.main_window, 'firebase_manager'):
            success = self.main_window.firebase_manager.save_quotation(quotation_data)
            if success:
                QtWidgets.QMessageBox.information(
                    self, "Success", 
                    f"Quotation '{quotation_data['quotation_number']}' saved as draft!"
                )
            else:
                QtWidgets.QMessageBox.critical(
                    self, "Error", 
                    "Failed to save quotation to database."
                )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Warning", 
                "Database connection not available. Quotation saved locally only."
            )
    
    def get_quotation_data(self):
        """Get quotation data from form"""
        items = []
        for row in range(self.items_table.rowCount()):
            item = {
                "description": self.items_table.item(row, 0).text(),
                "quantity": float(self.items_table.item(row, 1).text() or 0),
                "unit_price": float(self.items_table.item(row, 2).text() or 0),
                "total": float(self.items_table.item(row, 3).text() or 0)
            }
            items.append(item)
        
        return {
            "quotation_number": self.quotation_number_edit.text(),
            "client": self.client_combo.currentText(),
            "quotation_date": self.quotation_date_edit.date().toString("yyyy-MM-dd"),
            "valid_until": self.valid_until_edit.date().toString("yyyy-MM-dd"),
            "project_reference": self.project_ref_edit.text(),
            "payment_terms": self.terms_combo.currentText(),
            "scope": self.scope_edit.toPlainText(),
            "exclusions": self.exclusions_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
            "items": items,
            "subtotal": float(self.subtotal_label.text().replace("$", "")),
            "total": float(self.total_label.text().replace("$", "")),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
    
    def validate_quotation(self):
        """Validate quotation form"""
        if self.client_combo.currentText() == "-- Select Client --":
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Please select a client.")
            return False
        
        if self.items_table.rowCount() == 0:
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Please add at least one quotation item.")
            return False
        
        if not self.scope_edit.toPlainText().strip():
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Scope of work is required.")
            return False
        
        return True
    
    def refresh_clients(self):
        """Refresh clients list from main window"""
        self.client_combo.clear()
        self.client_combo.addItem("-- Select Client --")
        
        if hasattr(self.main_window, 'clients'):
            for client_name in sorted(self.main_window.clients.keys()):
                self.client_combo.addItem(client_name)