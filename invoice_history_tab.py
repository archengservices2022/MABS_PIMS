# invoice_history_tab.py
import os
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import base64
import tempfile
import openpyxl
import openpyxl.utils
from openpyxl.styles import Font, Alignment
from openpyxl.styles import PatternFill
from main import PDFGenerator
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import QTimer
import pandas as pd
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from datetime import datetime


from app_logger import get_logger
from app_theme import (
    INDIGO,
    INDIGO_D,
    INDIGO_L,
    AMBER,
    AMBER_D,
    AMBER_L,
    EMERALD,
    EMERALD_L,
    VIOLET,
    VIOLET_L,
    SLATE_50,
    SLATE_100,
    SLATE_200,
    SLATE_300,
    SLATE_500,
    SLATE_600,
    SLATE_700,
    SLATE_800,
    SLATE_900,
    WHITE,
)
_log = get_logger(__name__)
_invoice_data_changed = QtCore.pyqtSignal(str)

PROJECT_FONT = '"Inter", "Segoe UI", "Arial", sans-serif'

# Import from main application
try:
    from arch_invoice_generator import Config, FileManager, Invoice, Currency, FirebaseManager, FIREBASE_AVAILABLE, InvoiceItem
except ImportError:
    try:
        from main import Config, FileManager, Invoice, Currency, FirebaseManager, FIREBASE_AVAILABLE, InvoiceItem
    except ImportError:
        class Config: pass
        class FileManager: pass  
        class Invoice: pass
        class Currency: 
            @staticmethod
            def format(value): return f"${value}"
            @staticmethod
            def format_whole(value): return f"${int(float(value))}"
        class InvoiceItem: pass
        class FirebaseManager: 
            @staticmethod
            def load_invoices(): return []
            @staticmethod
            def sync_status_to_firebase(client_name, invoice_number, status): pass
        FIREBASE_AVAILABLE = False

def _normalize_payment_stage(stage: str) -> str:
    """Canonicalise any payment stage label to the current unified name."""
    s = (stage or "").strip()
    lo = s.lower()
    if any(x in lo for x in ("down payment", "deposit", "50%")):
        return "Down Payment (50%)"
    if any(x in lo for x in ("2nd", "term 2", "second")):
        return "2nd Payment"
    if any(x in lo for x in ("3rd", "term 3", "third")):
        return "3rd Payment"
    if any(x in lo for x in ("4th", "term 4", "fourth")):
        return "4th Payment"
    if any(x in lo for x in ("balance", "due payment", "full amount due")):
        return "Balance Payment"
    if "final" in lo:
        return "Final Payment"
    if any(x in lo for x in ("full amount", "full payment")):
        return "Full Amount"
    return s  # keep as-is if unknown


def _normalize_date(date_str: str) -> str:
    """Return date as MM-dd-YYYY. Falls back to today if unparseable."""
    from datetime import datetime as _dt
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return _dt.strptime((date_str or "").strip()[:10], fmt).strftime("%m-%d-%Y")
        except (ValueError, TypeError):
            pass
    return _dt.now().strftime("%m-%d-%Y")


import io
try:
    from PyPDF2 import PdfReader, PdfWriter
    PDF_AVAILABLE = True
except ImportError:
    try:
        from pypdf import PdfReader, PdfWriter
        PDF_AVAILABLE = True
    except ImportError:
        PDF_AVAILABLE = False

class PDFWatermarker:
    """Professional PDF watermarking utility - WATERMARK ONLY FOR PAID STATUS"""
    
    @staticmethod
    def add_watermark_simple(input_pdf_path: Path, status: str) -> Path:
        try:
            if status != "Paid":
                return input_pdf_path
            
            output_pdf_path = input_pdf_path.parent / f"{input_pdf_path.stem}_watermarked{input_pdf_path.suffix}"
            watermark_config = PDFWatermarker.get_watermark_config(status)
            
            with open(input_pdf_path, 'rb') as input_file:
                existing_pdf = PdfReader(input_file)
                total_pages = len(existing_pdf.pages)
                output_pdf = PdfWriter()
                
                for page_num in range(total_pages):
                    page = existing_pdf.pages[page_num]
                    packet = io.BytesIO()
                    can = canvas.Canvas(packet, pagesize=A4)
                    
                    can.setFillAlpha(watermark_config['opacity'])
                    can.setFillColor(watermark_config['color'])
                    can.setFont("Helvetica-Bold", watermark_config['font_size'])
                    
                    page_width = A4[0]
                    page_height = A4[1]
                    text = watermark_config['text']
                    text_width = can.stringWidth(text, "Helvetica-Bold", watermark_config['font_size'])
                    
                    x = page_width / 2 - text_width / 2
                    y = page_height / 2
                    
                    can.saveState()
                    can.translate(x, y)
                    can.rotate(40)
                    can.drawString(0, 0, text)
                    can.restoreState()
                    can.save()
                    
                    packet.seek(0)
                    watermark_pdf = PdfReader(packet)
                    watermark_page = watermark_pdf.pages[0]
                    page.merge_page(watermark_page)
                    output_pdf.add_page(page)
                
                with open(output_pdf_path, 'wb') as output_file:
                    output_pdf.write(output_file)
            
            return output_pdf_path
        except Exception as e:
            _log.warning("Error in watermarking: %s", e)
            return input_pdf_path

    @staticmethod
    def get_watermark_config(status: str) -> Dict:
        if status == "Paid":
            return {
                'text': 'PAID',
                'color': colors.HexColor('#27ae60'),
                'font_size': 65,
                'opacity': 0.15
            }
        else:
            return {'text': '', 'color': colors.black, 'font_size': 0, 'opacity': 0}

    @staticmethod
    def add_watermark_to_pdf(input_pdf_path: Path, status: str) -> Path:
        return PDFWatermarker.add_watermark_simple(input_pdf_path, status)


class YearCalendarGrid(QtWidgets.QWidget):
    """Professional 3x3 grid for year selection with unlimited past/future years"""
    
    year_selected = QtCore.pyqtSignal(int)
    
    def __init__(self, parent=None, start_year=1, end_year=9999):
        super().__init__(parent)
        self.selected_year = datetime.now().year
        self.start_year = start_year
        self.end_year = end_year
        self.year_buttons = []
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet('* { font-family: "Inter", "Segoe UI", Arial, sans-serif; }')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        nav_layout = QtWidgets.QHBoxLayout()
        nav_layout.setSpacing(10)
        
        self.prev_block_btn = QtWidgets.QPushButton("◀◀")
        self.prev_block_btn.setFixedSize(40, 30)
        self.prev_block_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #2980b9; }
            QPushButton:pressed { background: #21618c; }
        """)
        self.prev_block_btn.clicked.connect(self.prev_nine_year_block)
        
        self.block_label = QtWidgets.QLabel("")
        self.block_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 14px;")
        self.block_label.setAlignment(QtCore.Qt.AlignCenter)
        
        self.next_block_btn = QtWidgets.QPushButton("▶▶")
        self.next_block_btn.setFixedSize(40, 30)
        self.next_block_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #2980b9; }
            QPushButton:pressed { background: #21618c; }
        """)
        self.next_block_btn.clicked.connect(self.next_nine_year_block)
        
        nav_layout.addWidget(self.prev_block_btn)
        nav_layout.addWidget(self.block_label)
        nav_layout.addWidget(self.next_block_btn)
        layout.addLayout(nav_layout)
        
        grid_container = QtWidgets.QWidget()
        grid_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #dfe6e9;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        grid_layout = QtWidgets.QGridLayout(grid_container)
        grid_layout.setSpacing(8)
        grid_layout.setContentsMargins(10, 10, 10, 10)
        
        self.year_buttons = []
        self.current_block_start = self.calculate_block_start(self.selected_year)
        
        for row in range(3):
            for col in range(3):
                year_btn = QtWidgets.QPushButton()
                year_btn.setFixedSize(70, 45)
                year_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
                self.year_buttons.append(year_btn)
                grid_layout.addWidget(year_btn, row, col)
        
        layout.addWidget(grid_container)
        
        current_layout = QtWidgets.QHBoxLayout()
        current_layout.addStretch()
        self.current_year_label = QtWidgets.QLabel(f"Selected: {self.selected_year}")
        self.current_year_label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                color: #27ae60;
                font-size: 13px;
                background: #e8f6f3;
                padding: 6px 12px;
                border-radius: 6px;
                border: 1px solid #a3e4d7;
            }
        """)
        current_layout.addWidget(self.current_year_label)
        current_layout.addStretch()
        layout.addLayout(current_layout)
        
        self.update_nine_year_block_grid()
    
    def calculate_block_start(self, year):
        return ((year - 1) // 9) * 9 + 1
    
    def update_nine_year_block_grid(self):
        years = [self.current_block_start + i for i in range(9)]
        first_year = years[0]
        last_year = years[-1]
        self.block_label.setText(f"{first_year} - {last_year}")
        current_year = datetime.now().year
        
        for i, year_btn in enumerate(self.year_buttons):
            year = years[i]
            if year < 1 or year > 9999:
                year_btn.setText("")
                year_btn.setEnabled(False)
                year_btn.setStyleSheet("""
                    QPushButton {
                        background: #f8f9fa;
                        border: 1px solid #dfe6e9;
                        border-radius: 5px;
                        color: #bdc3c7;
                    }
                """)
                continue
            
            year_btn.setText(str(year))
            year_btn.setEnabled(True)
            
            if year == self.selected_year:
                year_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #27ae60, stop:1 #2ecc71);
                        color: white;
                        border: 2px solid #229954;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #229954, stop:1 #27ae60);
                    }
                """)
            elif year == current_year:
                year_btn.setStyleSheet("""
                    QPushButton {
                        background: #3498db;
                        color: white;
                        border: 2px solid #2980b9;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover { background: #2980b9; }
                """)
            else:
                year_btn.setStyleSheet("""
                    QPushButton {
                        background: white;
                        color: #2c3e50;
                        border: 1px solid #dfe6e9;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background: #f8f9fa;
                        border-color: #3498db;
                        color: #3498db;
                    }
                """)
            
            try:
                year_btn.clicked.disconnect()
            except TypeError:
                pass
            year_btn.clicked.connect(lambda checked, y=year: self.select_year(y))
    
    def select_year(self, year):
        self.selected_year = year
        self.current_year_label.setText(f"Selected: {year}")
        self.update_nine_year_block_grid()
        self.year_selected.emit(year)
    
    def prev_nine_year_block(self):
        self.current_block_start -= 9
        self.update_nine_year_block_grid()
    
    def next_nine_year_block(self):
        self.current_block_start += 9
        self.update_nine_year_block_grid()
    
    def set_selected_year(self, year):
        if year < 1:
            year = 1
        elif year > 9999:
            year = 9999
        self.selected_year = year
        self.current_block_start = self.calculate_block_start(year)
        self.current_year_label.setText(f"Selected: {year}")
        self.update_nine_year_block_grid()
    
    def get_selected_year(self):
        return self.selected_year


class YearCalendarPopup(QtWidgets.QDialog):
    """Professional popup window for year selection"""
    
    year_selected = QtCore.pyqtSignal(int)
    
    def __init__(self, parent=None, current_year=None):
        super().__init__(parent)
        self.current_year = current_year or datetime.now().year
        self.setWindowTitle("Select Year")
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowCloseButtonHint)
        self.setFixedSize(380, 450)
        self.setStyleSheet("""
            YearCalendarPopup {
                background: #ffffff;
                border: 1px solid #d1d8e0;
                border-radius: 12px;
            }
        """)
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet('* { font-family: "Inter", "Segoe UI", Arial, sans-serif; }')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        
        header = QtWidgets.QLabel("📅 Select Year")
        header.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #2c3e50;
                padding: 10px 0;
                text-align: center;
                border-bottom: 2px solid #3498db;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(header)
        
        self.year_calendar = YearCalendarGrid(start_year=1, end_year=9999)
        self.year_calendar.set_selected_year(self.current_year)
        self.year_calendar.setStyleSheet("""
            YearCalendarGrid {
                background: white;
                border: 1px solid #e1e8ed;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.year_calendar)
        
        selected_layout = QtWidgets.QHBoxLayout()
        selected_layout.addStretch()
        self.selected_label = QtWidgets.QLabel("")
        self.selected_label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                color: #27ae60;
                font-size: 14px;
            }
        """)
        selected_layout.addWidget(self.selected_label)
        selected_layout.addStretch()
        layout.addLayout(selected_layout)
        
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setFixedSize(120, 45)
        self.cancel_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #e74c3c;
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #c0392b;
                border: 2px solid #e74c3c;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.select_btn = QtWidgets.QPushButton("Select Year")
        self.select_btn.setFixedSize(120, 45)
        self.select_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.select_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #27ae60, stop:1 #2ecc71);
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #229954, stop:1 #27ae60);
                border: 2px solid #27ae60;
            }
        """)
        self.select_btn.clicked.connect(self.on_select_clicked)
        
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.select_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.year_calendar.year_selected.connect(self.on_year_changed)
    
    def on_year_changed(self, year):
        self.current_year = year
    
    def on_select_clicked(self):
        self.year_selected.emit(self.current_year)
        self.accept()
    
    def get_selected_year(self):
        return self.current_year


class PDFExportDialog(QtWidgets.QDialog):
    """Professional PDF/Excel Export Dialog with Tabs"""
    
    def __init__(self, parent=None, client_name="", available_dates=None):
        super().__init__(parent)
        self.client_name = client_name
        self.available_dates = available_dates or []
        self.export_range = "all"
        self.selected_dates = []
        self.export_type = "pdf"
        self.year_calendar_popup = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f"📊 Export Manager - {self.client_name}")
        self.setFixedSize(700, 750)
        self.setStyleSheet("""
            PDFExportDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fafc, stop:1 #e2e8f0);
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        
        header = QtWidgets.QLabel("📤 Export Manager")
        header.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #2c3e50;
                padding: 15px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2c3e50);
                color: white;
                border-radius: 10px;
                text-align: center;
            }
        """)
        header.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(header)
        
        client_card = QtWidgets.QWidget()
        client_card.setStyleSheet("""
            QWidget {
                background: white;
                border-radius: 10px;
                border: 2px solid #3498db;
                padding: 10px;
            }
        """)
        client_layout = QtWidgets.QVBoxLayout(client_card)
        client_label = QtWidgets.QLabel(f"🏢 Client: {self.client_name}")
        client_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #2c3e50;
                padding: 8px;
            }
        """)
        client_layout.addWidget(client_label)
        layout.addWidget(client_card)
        
        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                background-color: white;
            }
            QTabBar::tab {
                background-color: #ecf0f1;
                color: #2c3e50;
                padding: 12px 20px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                background-color: #3498db;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #d5dbdb;
            }
        """)
        
        self.pdf_tab = QtWidgets.QWidget()
        self.setup_pdf_tab()
        self.tab_widget.addTab(self.pdf_tab, "📄 PDF Export")
        
        self.excel_tab = QtWidgets.QWidget()
        self.setup_excel_tab()
        self.tab_widget.addTab(self.excel_tab, "📊 Excel Export")
        
        layout.addWidget(self.tab_widget)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                text-align: center;
                background-color: #ecf0f1;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        button_layout = QtWidgets.QHBoxLayout()
        
        self.export_btn = QtWidgets.QPushButton("🚀 Export PDF")
        self.export_btn.setFixedHeight(45)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #27ae60, stop:1 #2ecc71);
                color: white;
                border: none;
                padding: 12px 25px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                min-width: 150px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #229954, stop:1 #27ae60);
            }
            QPushButton:disabled {
                background: #bdc3c7;
                color: #7f8c8d;
            }
        """)
        self.export_btn.clicked.connect(self.start_export)
        
        self.cancel_btn = QtWidgets.QPushButton("❌ Cancel")
        self.cancel_btn.setFixedHeight(45)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #e74c3c;
                color: white;
                border: none;
                padding: 12px 25px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                min-width: 120px;
            }
            QPushButton:hover {
                background: #c0392b;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.export_btn)
        layout.addLayout(button_layout)
    
    def setup_pdf_tab(self):
        layout = QtWidgets.QVBoxLayout(self.pdf_tab)
        layout.setSpacing(15)
        
        options_card = QtWidgets.QGroupBox("🎯 PDF Export Options")
        options_card.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        options_layout = QtWidgets.QVBoxLayout(options_card)
        
        range_group = QtWidgets.QButtonGroup(self)
        
        self.all_radio = QtWidgets.QRadioButton("📋 Export All Invoices")
        self.all_radio.setChecked(True)
        self.all_radio.toggled.connect(lambda: self.on_range_changed("all"))
        
        self.date_range_radio = QtWidgets.QRadioButton("📅 Export by Date Range")
        self.date_range_radio.toggled.connect(lambda: self.on_range_changed("date_range"))
        
        self.month_radio = QtWidgets.QRadioButton("🗓️ Export by Month")
        self.month_radio.toggled.connect(lambda: self.on_range_changed("month"))
        
        self.year_radio = QtWidgets.QRadioButton("📊 Export by Year")
        self.year_radio.toggled.connect(lambda: self.on_range_changed("year"))
        
        options_layout.addWidget(self.all_radio)
        options_layout.addWidget(self.date_range_radio)
        options_layout.addWidget(self.month_radio)
        options_layout.addWidget(self.year_radio)
        
        range_group.addButton(self.all_radio)
        range_group.addButton(self.date_range_radio)
        range_group.addButton(self.month_radio)
        range_group.addButton(self.year_radio)
        
        layout.addWidget(options_card)
        
        self.date_selection_container = QtWidgets.QWidget()
        self.date_selection_layout = QtWidgets.QVBoxLayout(self.date_selection_container)
        self.date_selection_layout.setSpacing(15)
        self.date_selection_layout.setContentsMargins(10, 10, 10, 10)
        
        self.date_range_group = QtWidgets.QGroupBox("📅 Select Date Range")
        self.date_range_group.setMinimumHeight(120)
        self.date_range_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        date_range_layout = QtWidgets.QHBoxLayout(self.date_range_group)
        date_range_layout.setSpacing(20)
        
        from_layout = QtWidgets.QVBoxLayout()
        from_label = QtWidgets.QLabel("From Date:")
        from_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        from_layout.addWidget(from_label)
        self.from_date = QtWidgets.QDateEdit()
        self.from_date.setDisplayFormat("MM-dd-yyyy")
        self.from_date.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.from_date.setCalendarPopup(True)
        self.from_date.setFixedSize(160, 45)
        self.from_date.setStyleSheet("""
            QDateEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
            }
            QDateEdit:hover { border-color: #3498db; }
        """)
        from_layout.addWidget(self.from_date)
        date_range_layout.addLayout(from_layout)
        
        to_layout = QtWidgets.QVBoxLayout()
        to_label = QtWidgets.QLabel("To Date:")
        to_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        to_layout.addWidget(to_label)
        self.to_date = QtWidgets.QDateEdit()
        self.to_date.setDisplayFormat("MM-dd-yyyy")
        self.to_date.setDate(QtCore.QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        self.to_date.setFixedSize(160, 45)
        self.to_date.setStyleSheet("""
            QDateEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
            }
            QDateEdit:hover { border-color: #3498db; }
        """)
        to_layout.addWidget(self.to_date)
        date_range_layout.addLayout(to_layout)
        date_range_layout.addStretch()
        self.date_selection_layout.addWidget(self.date_range_group)
        
        self.month_group = QtWidgets.QGroupBox("🗓️ Select Month and Year")
        self.month_group.setMinimumHeight(150)
        self.month_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        month_layout = QtWidgets.QVBoxLayout(self.month_group)
        month_layout.setSpacing(15)
        
        month_year_row_layout = QtWidgets.QHBoxLayout()
        month_year_row_layout.setSpacing(15)
        
        month_container = QtWidgets.QHBoxLayout()
        month_label = QtWidgets.QLabel("Select Month:")
        month_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        month_container.addWidget(month_label)
        self.month_combo = QtWidgets.QComboBox()
        self.month_combo.setFixedSize(200, 45)
        self.month_combo.setStyleSheet("""
            QComboBox {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
            }
            QComboBox:hover { border-color: #3498db; }
        """)
        self.populate_months()
        month_container.addWidget(self.month_combo)
        month_year_row_layout.addLayout(month_container)
        
        year_container = QtWidgets.QHBoxLayout()
        year_label_month = QtWidgets.QLabel("Select Year:")
        year_label_month.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        year_container.addWidget(year_label_month)
        
        self.year_edit_month = QtWidgets.QLineEdit(str(datetime.now().year))
        self.year_edit_month.setFixedSize(150, 45)
        self.year_edit_month.setReadOnly(True)
        self.year_edit_month.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
                color: #2c3e50;
                font-weight: bold;
            }
        """)
        
        self.year_calendar_btn_month = QtWidgets.QPushButton("📅")
        self.year_calendar_btn_month.setFixedSize(50, 45)
        self.year_calendar_btn_month.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.year_calendar_btn_month.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: 2px solid #2980b9;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2980b9;
                border-color: #21618c;
            }
            QPushButton:pressed {
                background: #21618c;
            }
        """)
        self.year_calendar_btn_month.clicked.connect(self.show_year_popup_for_month)
        
        year_container.addWidget(self.year_edit_month)
        year_container.addWidget(self.year_calendar_btn_month)
        month_year_row_layout.addLayout(year_container)
        month_year_row_layout.addStretch()
        month_layout.addLayout(month_year_row_layout)
        self.date_selection_layout.addWidget(self.month_group)
        
        self.year_group = QtWidgets.QGroupBox("📊 Select Year")
        self.year_group.setMinimumHeight(120)
        self.year_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        year_layout = QtWidgets.QVBoxLayout(self.year_group)
        year_layout.setSpacing(15)
        
        year_row_layout = QtWidgets.QHBoxLayout()
        year_label = QtWidgets.QLabel("Select Year:")
        year_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        year_row_layout.addWidget(year_label)
        
        self.year_edit = QtWidgets.QLineEdit(str(datetime.now().year))
        self.year_edit.setFixedSize(150, 45)
        self.year_edit.setReadOnly(True)
        self.year_edit.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
                color: #2c3e50;
                font-weight: bold;
            }
        """)
        
        self.year_calendar_btn = QtWidgets.QPushButton("📅")
        self.year_calendar_btn.setFixedSize(50, 45)
        self.year_calendar_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.year_calendar_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: 2px solid #2980b9;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2980b9;
                border-color: #21618c;
            }
            QPushButton:pressed {
                background: #21618c;
            }
        """)
        self.year_calendar_btn.clicked.connect(self.show_year_popup)
        
        year_row_layout.addWidget(self.year_edit)
        year_row_layout.addWidget(self.year_calendar_btn)
        year_row_layout.addStretch()
        year_layout.addLayout(year_row_layout)
        self.date_selection_layout.addWidget(self.year_group)
        
        layout.addWidget(self.date_selection_container)
        
        self.date_selection_container.setVisible(False)
        self.date_range_group.setVisible(False)
        self.month_group.setVisible(False)
        self.year_group.setVisible(False)
        
        preview_card = QtWidgets.QGroupBox("👁️ PDF Export Preview")
        preview_card.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #27ae60;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        preview_layout = QtWidgets.QVBoxLayout(preview_card)
        
        self.preview_label = QtWidgets.QLabel("Ready to export all invoices as PDF")
        self.preview_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #7f8c8d;
                padding: 10px;
                background-color: #ecf0f1;
                border-radius: 5px;
            }
        """)
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        
        layout.addWidget(preview_card)
        
        self.from_date.dateChanged.connect(self.update_preview)
        self.to_date.dateChanged.connect(self.update_preview)
        self.month_combo.currentTextChanged.connect(self.update_preview)
    
    def setup_excel_tab(self):
        layout = QtWidgets.QVBoxLayout(self.excel_tab)
        layout.setSpacing(15)
        
        options_card = QtWidgets.QGroupBox("🎯 Excel Export Options")
        options_card.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        options_layout = QtWidgets.QVBoxLayout(options_card)
        
        self.excel_all_radio = QtWidgets.QRadioButton("📋 Export All Invoices")
        self.excel_all_radio.setChecked(True)
        self.excel_all_radio.toggled.connect(lambda: self.on_excel_range_changed("all"))
        
        self.excel_date_range_radio = QtWidgets.QRadioButton("📅 Export by Date Range")
        self.excel_date_range_radio.toggled.connect(lambda: self.on_excel_range_changed("date_range"))
        
        self.excel_month_radio = QtWidgets.QRadioButton("🗓️ Export by Month")
        self.excel_month_radio.toggled.connect(lambda: self.on_excel_range_changed("month"))
        
        self.excel_year_radio = QtWidgets.QRadioButton("📊 Export by Year")
        self.excel_year_radio.toggled.connect(lambda: self.on_excel_range_changed("year"))
        
        options_layout.addWidget(self.excel_all_radio)
        options_layout.addWidget(self.excel_date_range_radio)
        options_layout.addWidget(self.excel_month_radio)
        options_layout.addWidget(self.excel_year_radio)
        
        range_group = QtWidgets.QButtonGroup(self)
        range_group.addButton(self.excel_all_radio)
        range_group.addButton(self.excel_date_range_radio)
        range_group.addButton(self.excel_month_radio)
        range_group.addButton(self.excel_year_radio)
        
        layout.addWidget(options_card)
        
        self.excel_date_selection_container = QtWidgets.QWidget()
        self.excel_date_selection_layout = QtWidgets.QVBoxLayout(self.excel_date_selection_container)
        self.excel_date_selection_layout.setSpacing(15)
        self.excel_date_selection_layout.setContentsMargins(10, 10, 10, 10)
        
        self.excel_date_range_group = QtWidgets.QGroupBox("📅 Select Date Range")
        self.excel_date_range_group.setMinimumHeight(120)
        self.excel_date_range_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        excel_date_range_layout = QtWidgets.QHBoxLayout(self.excel_date_range_group)
        excel_date_range_layout.setSpacing(20)
        
        excel_from_layout = QtWidgets.QVBoxLayout()
        excel_from_label = QtWidgets.QLabel("From Date:")
        excel_from_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        excel_from_layout.addWidget(excel_from_label)
        self.excel_from_date = QtWidgets.QDateEdit()
        self.excel_from_date.setDisplayFormat("MM-dd-yyyy")
        self.excel_from_date.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.excel_from_date.setCalendarPopup(True)
        self.excel_from_date.setFixedSize(160, 45)
        self.excel_from_date.setStyleSheet("""
            QDateEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
            }
            QDateEdit:hover { border-color: #3498db; }
        """)
        excel_from_layout.addWidget(self.excel_from_date)
        excel_date_range_layout.addLayout(excel_from_layout)
        
        excel_to_layout = QtWidgets.QVBoxLayout()
        excel_to_label = QtWidgets.QLabel("To Date:")
        excel_to_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        excel_to_layout.addWidget(excel_to_label)
        self.excel_to_date = QtWidgets.QDateEdit()
        self.excel_to_date.setDisplayFormat("MM-dd-yyyy")
        self.excel_to_date.setDate(QtCore.QDate.currentDate())
        self.excel_to_date.setCalendarPopup(True)
        self.excel_to_date.setFixedSize(160, 45)
        self.excel_to_date.setStyleSheet("""
            QDateEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
            }
            QDateEdit:hover { border-color: #3498db; }
        """)
        excel_to_layout.addWidget(self.excel_to_date)
        excel_date_range_layout.addLayout(excel_to_layout)
        excel_date_range_layout.addStretch()
        self.excel_date_selection_layout.addWidget(self.excel_date_range_group)
        
        self.excel_month_group = QtWidgets.QGroupBox("🗓️ Select Month and Year")
        self.excel_month_group.setMinimumHeight(150)
        self.excel_month_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        excel_month_layout = QtWidgets.QVBoxLayout(self.excel_month_group)
        excel_month_layout.setSpacing(15)
        
        excel_month_year_row_layout = QtWidgets.QHBoxLayout()
        excel_month_year_row_layout.setSpacing(15)
        
        excel_month_container = QtWidgets.QHBoxLayout()
        excel_month_label = QtWidgets.QLabel("Select Month:")
        excel_month_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        excel_month_container.addWidget(excel_month_label)
        self.excel_month_combo = QtWidgets.QComboBox()
        self.excel_month_combo.setFixedSize(200, 45)
        self.excel_month_combo.setStyleSheet("""
            QComboBox {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
            }
            QComboBox:hover { border-color: #3498db; }
        """)
        self.populate_months_excel()
        excel_month_container.addWidget(self.excel_month_combo)
        excel_month_year_row_layout.addLayout(excel_month_container)
        
        excel_year_container = QtWidgets.QHBoxLayout()
        excel_year_month_label = QtWidgets.QLabel("Select Year:")
        excel_year_month_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        excel_year_container.addWidget(excel_year_month_label)
        
        self.excel_year_edit_month = QtWidgets.QLineEdit(str(datetime.now().year))
        self.excel_year_edit_month.setFixedSize(150, 45)
        self.excel_year_edit_month.setReadOnly(True)
        self.excel_year_edit_month.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
                color: #2c3e50;
                font-weight: bold;
            }
        """)
        
        self.excel_year_calendar_btn_month = QtWidgets.QPushButton("📅")
        self.excel_year_calendar_btn_month.setFixedSize(50, 45)
        self.excel_year_calendar_btn_month.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.excel_year_calendar_btn_month.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: 2px solid #2980b9;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2980b9;
                border-color: #21618c;
            }
            QPushButton:pressed {
                background: #21618c;
            }
        """)
        self.excel_year_calendar_btn_month.clicked.connect(self.show_year_popup_for_month_excel)
        
        excel_year_container.addWidget(self.excel_year_edit_month)
        excel_year_container.addWidget(self.excel_year_calendar_btn_month)
        excel_month_year_row_layout.addLayout(excel_year_container)
        excel_month_year_row_layout.addStretch()
        excel_month_layout.addLayout(excel_month_year_row_layout)
        self.excel_date_selection_layout.addWidget(self.excel_month_group)
        
        self.excel_year_group = QtWidgets.QGroupBox("📊 Select Year")
        self.excel_year_group.setMinimumHeight(120)
        self.excel_year_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2c3e50;
            }
        """)
        excel_year_layout = QtWidgets.QVBoxLayout(self.excel_year_group)
        excel_year_layout.setSpacing(15)
        
        excel_year_row_layout = QtWidgets.QHBoxLayout()
        excel_year_label = QtWidgets.QLabel("Select Year:")
        excel_year_label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 13px;")
        excel_year_row_layout.addWidget(excel_year_label)
        
        self.excel_year_edit = QtWidgets.QLineEdit(str(datetime.now().year))
        self.excel_year_edit.setFixedSize(150, 45)
        self.excel_year_edit.setReadOnly(True)
        self.excel_year_edit.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                font-size: 14px;
                background-color: white;
                color: #2c3e50;
                font-weight: bold;
            }
        """)
        
        self.excel_year_calendar_btn = QtWidgets.QPushButton("📅")
        self.excel_year_calendar_btn.setFixedSize(50, 45)
        self.excel_year_calendar_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.excel_year_calendar_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: 2px solid #2980b9;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2980b9;
                border-color: #21618c;
            }
            QPushButton:pressed {
                background: #21618c;
            }
        """)
        self.excel_year_calendar_btn.clicked.connect(self.show_year_popup_excel)
        
        excel_year_row_layout.addWidget(self.excel_year_edit)
        excel_year_row_layout.addWidget(self.excel_year_calendar_btn)
        excel_year_row_layout.addStretch()
        excel_year_layout.addLayout(excel_year_row_layout)
        self.excel_date_selection_layout.addWidget(self.excel_year_group)
        
        layout.addWidget(self.excel_date_selection_container)
        
        self.excel_date_selection_container.setVisible(False)
        self.excel_date_range_group.setVisible(False)
        self.excel_month_group.setVisible(False)
        self.excel_year_group.setVisible(False)
        
        excel_preview_card = QtWidgets.QGroupBox("👁️ Excel Export Preview")
        excel_preview_card.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                border: 2px solid #e67e22;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        excel_preview_layout = QtWidgets.QVBoxLayout(excel_preview_card)
        
        self.excel_preview_label = QtWidgets.QLabel("Ready to export all invoices as Excel")
        self.excel_preview_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #7f8c8d;
                padding: 10px;
                background-color: #ecf0f1;
                border-radius: 5px;
            }
        """)
        self.excel_preview_label.setWordWrap(True)
        excel_preview_layout.addWidget(self.excel_preview_label)
        
        layout.addWidget(excel_preview_card)
        
        self.excel_from_date.dateChanged.connect(self.update_excel_preview)
        self.excel_to_date.dateChanged.connect(self.update_excel_preview)
        self.excel_month_combo.currentTextChanged.connect(self.update_excel_preview)
    
    def show_year_popup(self):
        try:
            current_year = int(self.year_edit.text())
        except:
            current_year = datetime.now().year
        
        self.year_calendar_popup = YearCalendarPopup(self, current_year)
        self.year_calendar_popup.year_selected.connect(self.on_year_selected)
        popup_rect = self.year_calendar_popup.geometry()
        main_rect = self.geometry()
        center_x = main_rect.x() + (main_rect.width() - popup_rect.width()) // 2
        center_y = main_rect.y() + (main_rect.height() - popup_rect.height()) // 2
        self.year_calendar_popup.move(center_x, center_y)
        self.year_calendar_popup.exec_()
    
    def show_year_popup_for_month(self):
        try:
            current_year = int(self.year_edit_month.text())
        except:
            current_year = datetime.now().year
        
        self.year_calendar_popup = YearCalendarPopup(self, current_year)
        self.year_calendar_popup.year_selected.connect(self.on_year_selected_for_month)
        popup_rect = self.year_calendar_popup.geometry()
        main_rect = self.geometry()
        center_x = main_rect.x() + (main_rect.width() - popup_rect.width()) // 2
        center_y = main_rect.y() + (main_rect.height() - popup_rect.height()) // 2
        self.year_calendar_popup.move(center_x, center_y)
        self.year_calendar_popup.exec_()
    
    def show_year_popup_excel(self):
        try:
            current_year = int(self.excel_year_edit.text())
        except:
            current_year = datetime.now().year
        
        self.year_calendar_popup = YearCalendarPopup(self, current_year)
        self.year_calendar_popup.year_selected.connect(self.on_year_selected_excel)
        popup_rect = self.year_calendar_popup.geometry()
        main_rect = self.geometry()
        center_x = main_rect.x() + (main_rect.width() - popup_rect.width()) // 2
        center_y = main_rect.y() + (main_rect.height() - popup_rect.height()) // 2
        self.year_calendar_popup.move(center_x, center_y)
        self.year_calendar_popup.exec_()
    
    def show_year_popup_for_month_excel(self):
        try:
            current_year = int(self.excel_year_edit_month.text())
        except:
            current_year = datetime.now().year
        
        self.year_calendar_popup = YearCalendarPopup(self, current_year)
        self.year_calendar_popup.year_selected.connect(self.on_year_selected_for_month_excel)
        popup_rect = self.year_calendar_popup.geometry()
        main_rect = self.geometry()
        center_x = main_rect.x() + (main_rect.width() - popup_rect.width()) // 2
        center_y = main_rect.y() + (main_rect.height() - popup_rect.height()) // 2
        self.year_calendar_popup.move(center_x, center_y)
        self.year_calendar_popup.exec_()
    
    def on_year_selected(self, year):
        self.year_edit.setText(str(year))
        self.year_calendar_popup = None
        self.update_preview()
    
    def on_year_selected_for_month(self, year):
        self.year_edit_month.setText(str(year))
        self.year_calendar_popup = None
        self.update_preview()
    
    def on_year_selected_excel(self, year):
        self.excel_year_edit.setText(str(year))
        self.year_calendar_popup = None
        self.update_excel_preview()
    
    def on_year_selected_for_month_excel(self, year):
        self.excel_year_edit_month.setText(str(year))
        self.year_calendar_popup = None
        self.update_excel_preview()
    
    def populate_months(self):
        months = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"]
        self.month_combo.addItems(months)
        self.month_combo.setCurrentIndex(datetime.now().month - 1)
    
    def populate_months_excel(self):
        months = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"]
        self.excel_month_combo.addItems(months)
        self.excel_month_combo.setCurrentIndex(datetime.now().month - 1)
    
    def on_tab_changed(self, index):
        if index == 0:
            self.export_type = "pdf"
            self.export_btn.setText("🚀 Export PDF")
            self.update_preview()
        elif index == 1:
            self.export_type = "excel"
            self.export_btn.setText("🚀 Export Excel")
            self.update_excel_preview()
    
    def on_range_changed(self, range_type):
        self.export_range = range_type
        date_range_visible = (range_type == "date_range")
        month_visible = (range_type == "month")
        year_visible = (range_type == "year")
        
        self.date_range_group.setVisible(date_range_visible)
        self.month_group.setVisible(month_visible)
        self.year_group.setVisible(year_visible)
        self.date_selection_container.setVisible(range_type != "all")
        self.update_preview()
    
    def on_excel_range_changed(self, range_type):
        self.excel_export_range = range_type
        date_range_visible = (range_type == "date_range")
        month_visible = (range_type == "month")
        year_visible = (range_type == "year")
        
        self.excel_date_range_group.setVisible(date_range_visible)
        self.excel_month_group.setVisible(month_visible)
        self.excel_year_group.setVisible(year_visible)
        self.excel_date_selection_container.setVisible(range_type != "all")
        self.update_excel_preview()
    
    def update_preview(self):
        if self.export_range == "all":
            self.preview_label.setText("📋 Will export ALL invoices for this client as PDF")
        elif self.export_range == "date_range":
            from_date = self.from_date.date().toString("MM-dd-yyyy")
            to_date = self.to_date.date().toString("MM-dd-yyyy")
            self.preview_label.setText(f"📅 Will export invoices from {from_date} to {to_date} as PDF")
        elif self.export_range == "month":
            month = self.month_combo.currentText()
            year = self.year_edit_month.text()
            self.preview_label.setText(f"🗓️ Will export invoices for {month} {year} as PDF")
        elif self.export_range == "year":
            year = self.year_edit.text()
            self.preview_label.setText(f"📊 Will export invoices for the year {year} as PDF")
    
    def update_excel_preview(self):
        if hasattr(self, 'excel_export_range'):
            range_type = self.excel_export_range
        else:
            range_type = "all"
        
        if range_type == "all":
            self.excel_preview_label.setText("📋 Will export ALL invoices for this client as Excel")
        elif range_type == "date_range":
            from_date = self.excel_from_date.date().toString("MM-dd-yyyy")
            to_date = self.excel_to_date.date().toString("MM-dd-yyyy")
            self.excel_preview_label.setText(f"📅 Will export invoices from {from_date} to {to_date} as Excel")
        elif range_type == "month":
            month = self.excel_month_combo.currentText()
            year = self.excel_year_edit_month.text()
            self.excel_preview_label.setText(f"🗓️ Will export invoices for {month} {year} as Excel")
        elif range_type == "year":
            year = self.excel_year_edit.text()
            self.excel_preview_label.setText(f"📊 Will export invoices for the year {year} as Excel")
    
    def get_export_parameters(self):
        if self.export_type == "pdf":
            if self.export_range == "all":
                return {"range": "all", "type": "pdf"}
            elif self.export_range == "date_range":
                from_date = self.from_date.date().toPyDate()
                to_date = self.to_date.date().toPyDate()
                return {"range": "date_range", "from_date": from_date, "to_date": to_date, "type": "pdf"}
            elif self.export_range == "month":
                month = self.month_combo.currentIndex() + 1
                year = int(self.year_edit_month.text())
                return {"range": "month", "month": month, "year": year, "type": "pdf"}
            elif self.export_range == "year":
                year = int(self.year_edit.text())
                return {"range": "year", "year": year, "type": "pdf"}
        elif self.export_type == "excel":
            if hasattr(self, 'excel_export_range'):
                range_type = self.excel_export_range
            else:
                range_type = "all"
            if range_type == "all":
                return {"range": "all", "type": "excel"}
            elif range_type == "date_range":
                from_date = self.excel_from_date.date().toPyDate()
                to_date = self.excel_to_date.date().toPyDate()
                return {"range": "date_range", "from_date": from_date, "to_date": to_date, "type": "excel"}
            elif range_type == "month":
                month = self.excel_month_combo.currentIndex() + 1
                year = int(self.excel_year_edit_month.text())
                return {"range": "month", "month": month, "year": year, "type": "excel"}
            elif range_type == "year":
                year = int(self.excel_year_edit.text())
                return {"range": "year", "year": year, "type": "excel"}
    
    def start_export(self):
        if hasattr(self, '_export_in_progress') and self._export_in_progress:
            return
        
        self._export_in_progress = True
        
        try:
            self.export_btn.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            export_params = self.get_export_parameters()
            
            for i in range(101):
                if not hasattr(self, '_export_in_progress'):
                    return
                QtWidgets.QApplication.processEvents()
                self.progress_bar.setValue(i)
                QtCore.QThread.msleep(10)
            
            self._export_params = export_params
            self.accept()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Error exporting: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)
            self.export_btn.setEnabled(True)
            self._export_in_progress = False


class DateRangeWidget(QtWidgets.QWidget):
    """Widget for selecting date range"""
    date_range_changed = pyqtSignal(datetime, datetime)
    date_range_cleared = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.is_date_range_applied = False
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet('* { font-family: "Inter", "Segoe UI", Arial, sans-serif; }')
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        self.calendar_btn = QtWidgets.QPushButton("📅")
        self.calendar_btn.setText("Date Range")
        self.calendar_btn.setFixedSize(112, 40)
        self.calendar_btn.setStyleSheet("""
            QPushButton {
                background-color: #f8fbfd;
                color: #0f172a;
                border: 1px solid #d8e2ec;
                border-radius: 7px;
                font-size: 13px;
                font-weight: 800;
            }
            QPushButton:hover { border-color: #00756f; color: #00756f; }
            QPushButton:pressed { background-color: #eefaf8; }
        """)
        self.calendar_btn.setToolTip("Toggle date range selector")
        self.calendar_btn.clicked.connect(self.toggle_date_range_visibility)
        layout.addWidget(self.calendar_btn)
        
        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText("Search invoices...")
        self.search_bar.setFixedHeight(40)
        self.search_bar.setFixedWidth(260)
        self.search_bar.setStyleSheet("""
            QLineEdit {
                padding: 8px 12px;
                border: 1px solid #d8e2ec;
                border-radius: 7px;
                font-size: 14px;
                background-color: white;
                color: #0f172a;
            }
            QLineEdit:focus { border-color: #00756f; }
        """)
        self.search_bar.textChanged.connect(self.on_search_changed)
        layout.addWidget(self.search_bar)
        
        self.date_range_container = QtWidgets.QWidget()
        self.date_range_container.setVisible(False)
        date_range_layout = QtWidgets.QHBoxLayout(self.date_range_container)
        date_range_layout.setContentsMargins(10, 5, 10, 5)
        date_range_layout.setSpacing(10)
        
        date_range_layout.addWidget(QtWidgets.QLabel("From:"))
        self.from_date = QtWidgets.QDateEdit()
        self.from_date.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("MM-dd-yyyy")
        self.from_date.setStyleSheet("""
            QDateEdit {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
                font-size: 12px;
                background-color: white;
            }
        """)
        self.from_date.dateChanged.connect(self.on_date_changed)
        date_range_layout.addWidget(self.from_date)
        
        date_range_layout.addWidget(QtWidgets.QLabel("To:"))
        self.to_date = QtWidgets.QDateEdit()
        self.to_date.setDate(QtCore.QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("MM-dd-yyyy")
        self.to_date.setStyleSheet("""
            QDateEdit {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
                font-size: 12px;
                background-color: white;
            }
        """)
        self.to_date.dateChanged.connect(self.on_date_changed)
        date_range_layout.addWidget(self.to_date)
        
        self.apply_clear_btn = QtWidgets.QPushButton("Apply")
        self.apply_clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #229954; }
        """)
        self.apply_clear_btn.clicked.connect(self.toggle_apply_clear)
        date_range_layout.addWidget(self.apply_clear_btn)
        
        layout.addWidget(self.date_range_container)
        layout.addStretch()
    
    def toggle_date_range_visibility(self):
        self.date_range_container.setVisible(not self.date_range_container.isVisible())
    
    def on_date_changed(self):
        if self.is_date_range_applied:
            self.is_date_range_applied = False
            self.apply_clear_btn.setText("Apply")
            self.apply_clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #229954; }
            """)
    
    def toggle_apply_clear(self):
        if self.is_date_range_applied:
            self.clear_date_range()
        else:
            self.apply_date_range()
    
    def apply_date_range(self):
        from_date_qdate = self.from_date.date()
        to_date_qdate = self.to_date.date()
        from_date_str = from_date_qdate.toString("MM-dd-yyyy")
        to_date_str = to_date_qdate.toString("MM-dd-yyyy")
        from_date = datetime.strptime(from_date_str, "%m-%d-%Y")
        to_date = datetime.strptime(to_date_str, "%m-%d-%Y")
        
        self.is_date_range_applied = True
        self.apply_clear_btn.setText("Clear")
        self.apply_clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #c0392b; }
        """)
        self.date_range_changed.emit(from_date, to_date)
    
    def clear_date_range(self):
        self.is_date_range_applied = False
        self.apply_clear_btn.setText("Apply")
        self.apply_clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #229954; }
        """)
        
        if hasattr(self.parent(), 'parent') and hasattr(self.parent().parent(), 'clear_quick_filter_highlighting'):
            self.parent().parent().clear_quick_filter_highlighting()
        
        self.date_range_cleared.emit()
    
    def set_date_range(self, from_date: datetime, to_date: datetime):
        from_date_str = from_date.strftime("%m-%d-%Y")
        to_date_str = to_date.strftime("%m-%d-%Y")
        self.from_date.setDate(QtCore.QDate.fromString(from_date_str, "MM-dd-yyyy"))
        self.to_date.setDate(QtCore.QDate.fromString(to_date_str, "MM-dd-yyyy"))
    
    def hide_date_range(self):
        self.date_range_container.setVisible(False)
    
    def on_search_changed(self, text):
        pass


class ClientListWidget(QtWidgets.QWidget):
    """Widget for displaying client list with professional styling"""
    client_selected = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)
        
        header_widget = QtWidgets.QWidget()
        header_widget.setFixedHeight(76)
        header_widget.setStyleSheet("""
            QWidget {
                background: #0f3b57;
                border-radius: 10px;
            }
        """)
        header_layout = QtWidgets.QVBoxLayout(header_widget)
        header_layout.setContentsMargins(22, 10, 22, 10)
        
        title = QtWidgets.QLabel("📊 INVOICE HISTORY")
        title.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: white;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
        """)
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setText("Invoice History")
        
        subtitle = QtWidgets.QLabel("Client & Invoice Management")
        subtitle.setStyleSheet("""
            QLabel {
                font-size: 13px;
                color: rgba(255,255,255,0.9);
                font-weight: normal;
            }
        """)
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setText("Client directory, invoice records, status tracking, and exports")
        
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header_widget)
        
        content_card = QtWidgets.QWidget()
        content_card.setStyleSheet("""
            QWidget {
                background: white;
                border-radius: 10px;
                border: 1px solid #d8e2ec;
            }
        """)
        content_layout = QtWidgets.QVBoxLayout(content_card)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(14)
        
        header_section = QtWidgets.QWidget()
        header_layout_inner = QtWidgets.QHBoxLayout(header_section)
        header_layout_inner.setContentsMargins(0, 0, 0, 0)
        
        section_title = QtWidgets.QLabel("🏢 Client Directory")
        section_title.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #2c3e50;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                padding: 8px 0;
                border: none;
            }
        """)
        
        section_title.setText("Client Directory")

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search clients...")
        self.search_edit.setPlaceholderText("Search clients...")
        self.search_edit.setFixedHeight(40)
        self.search_edit.setMinimumWidth(320)
        self.search_edit.setStyleSheet("""
            QLineEdit {
                background-color: white;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                color: #2c3e50;
            }
            QLineEdit:focus {
                border-color: #3498db;
                background-color: #f8fafc;
            }
        """)
        self.search_edit.textChanged.connect(self.filter_clients)
        
        self.export_all_btn = QtWidgets.QPushButton("📤 Export All")
        self.export_all_btn.setText("Export All")
        self.export_all_btn.setFixedHeight(40)
        self.export_all_btn.setMinimumWidth(150)
        self.export_all_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #e67e22, stop:1 #f39c12);
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 16px;
                min-width: 120px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #d35400, stop:1 #e67e22);
                border: 2px solid #f39c12;
            }
            QPushButton:pressed { background: #e67e22; }
            QPushButton:disabled {
                background: #bdc3c7;
                color: #7f8c8d;
            }
        """)
        self.export_all_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.export_all_btn.setToolTip("Export all clients' invoices in a single PDF")
        self.export_all_btn.clicked.connect(self.open_export_all_dialog)
        
        header_layout_inner.addWidget(section_title)
        header_layout_inner.addStretch()
        header_layout_inner.addWidget(self.search_edit)
        header_layout_inner.addWidget(self.export_all_btn)
        content_layout.addWidget(header_section)

        stats_row = QtWidgets.QWidget()
        stats_row.setStyleSheet("QWidget { background: transparent; border: none; }")
        stats_layout = QtWidgets.QHBoxLayout(stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(10)
        self.client_count_label = self.create_metric_card("Clients", "0")
        self.invoice_count_label = self.create_metric_card("Invoices", "0")
        self.revenue_total_label = self.create_metric_card("Revenue", "$0.00")
        stats_layout.addWidget(self.client_count_label)
        stats_layout.addWidget(self.invoice_count_label)
        stats_layout.addWidget(self.revenue_total_label)
        content_layout.addWidget(stats_row)
        
        list_container = QtWidgets.QWidget()
        list_container.setStyleSheet("""
            QWidget {
                background: #f8fafc;
                border: 1px solid #d8e2ec;
                border-radius: 10px;
                padding: 3px;
            }
        """)
        list_layout = QtWidgets.QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        
        self.client_list = QtWidgets.QListWidget()
        self.client_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.client_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.client_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                padding: 5px;
                outline: none;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
            QListWidget::item {
                padding: 0px;
                margin: 4px;
                border: none;
                background: transparent;
            }
            QListWidget::item:hover {
                background: transparent;
            }
            QListWidget::item:selected {
                background: transparent;
            }
            QListWidget::item:selected:hover {
                background: transparent;
            }
            QScrollBar:vertical {
                background: #f1f5f9;
                width: 12px;
                margin: 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #3498db;
                min-height: 30px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover { background: #2980b9; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        self.client_list.setAlternatingRowColors(False)
        self.client_list.itemClicked.connect(self.on_client_selected)
        self.client_list.itemDoubleClicked.connect(self.on_client_selected)
        self.client_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        list_layout.addWidget(self.client_list)
        content_layout.addWidget(list_container)
        
        self.empty_state_label = QtWidgets.QLabel("📁 No clients found. Create your first invoice to get started!")
        self.empty_state_label.setStyleSheet("""
            QLabel {
                color: #718096;
                font-size: 14px;
                font-style: italic;
                padding: 20px;
                text-align: center;
                background-color: #f7fafc;
                border-radius: 8px;
                border: 2px dashed #cbd5e0;
            }
        """)
        self.empty_state_label.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_state_label.setVisible(False)
        content_layout.addWidget(self.empty_state_label)
        
        layout.addWidget(content_card)
        
        actions_widget = QtWidgets.QWidget()
        self.actions_layout = QtWidgets.QHBoxLayout(actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(actions_widget)
        
        footer = QtWidgets.QLabel("💡 Click on any client to view detailed invoice history and analytics")
        footer.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #718096;
                font-weight: normal;
                padding: 10px;
                text-align: center;
                background: rgba(255,255,255,0.7);
                border-radius: 8px;
                border: 1px solid #e2e8f0;
            }
        """)
        footer.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(footer)

    def create_metric_card(self, label: str, value: str):
        card = QtWidgets.QLabel(
            f"<div style='font-size:18px; font-weight:800; color:#0f172a;'>{value}</div>"
            f"<div style='font-size:12px; font-weight:700; color:#64748b; margin-top:3px;'>{label}</div>"
        )
        card.setTextFormat(QtCore.Qt.RichText)
        card.setMinimumHeight(64)
        card.setAlignment(QtCore.Qt.AlignCenter)
        card.setStyleSheet("""
            QLabel {
                background: #f8fbfd;
                border: 1px solid #d8e2ec;
                border-radius: 8px;
                padding: 10px;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
        """)
        return card

    def update_metric_card(self, card, label: str, value: str):
        if card:
            card.setText(
                f"<div style='font-size:18px; font-weight:800; color:#0f172a;'>{value}</div>"
                f"<div style='font-size:12px; font-weight:700; color:#64748b; margin-top:3px;'>{label}</div>"
            )

    def create_client_card(self, client_name: str, invoices: List, item=None):
        invoice_count = len(invoices)
        revenue = sum((getattr(invoice, "total", Decimal("0")) for invoice in invoices), Decimal("0"))
        last_date = "No invoices"
        parsed_dates = []
        for invoice in invoices:
            raw_date = getattr(invoice, "date", "")
            try:
                parsed_dates.append(datetime.strptime(raw_date, "%m-%d-%Y"))
            except Exception:
                continue
        if parsed_dates:
            last_date = max(parsed_dates).strftime("%b %d, %Y")

        accents = [
            ("#00756f", "#eefaf8", "#9ddbd4"),
            ("#0f8bd6", "#eff8ff", "#b9e0fb"),
            ("#d97706", "#fff7ed", "#fed7aa"),
            ("#7c3aed", "#f5f3ff", "#ddd6fe"),
        ]
        accent, accent_bg, accent_border = accents[sum(ord(ch) for ch in client_name) % len(accents)]

        card = QtWidgets.QFrame()
        card.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent_bg}, stop:0.18 #ffffff, stop:1 #ffffff);
                border: 1px solid {accent_border};
                border-radius: 9px;
            }}
            QFrame:hover {{
                border-color: {accent};
            }}
            QLabel {{
                border: none;
                background: transparent;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }}
        """)

        layout = QtWidgets.QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        initials = "".join(part[:1] for part in client_name.split()[:2]).upper() or "C"
        badge = QtWidgets.QLabel(initials)
        badge.setFixedSize(44, 44)
        badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setStyleSheet("""
            QLabel {
                background: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: 22px;
                font-size: 15px;
                font-weight: 900;
            }
        """ % (accent_bg, accent, accent_border))

        name_block = QtWidgets.QWidget()
        name_layout = QtWidgets.QVBoxLayout(name_block)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(3)
        name_label = QtWidgets.QLabel(client_name)
        name_label.setStyleSheet("font-size: 16px; font-weight: 900; color: #0f172a;")
        hint_label = QtWidgets.QLabel("Click to view invoice details")
        hint_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #475569;")
        name_layout.addWidget(name_label)
        name_layout.addWidget(hint_label)

        def small_metric(title, value, width=92):
            widget = QtWidgets.QWidget()
            widget.setFixedWidth(width)
            widget.setMinimumHeight(54)
            widget.setStyleSheet(f"""
                QWidget {{
                    background: {accent_bg};
                    border: 1px solid {accent_border};
                    border-radius: 8px;
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)
            metric_layout = QtWidgets.QVBoxLayout(widget)
            metric_layout.setContentsMargins(8, 7, 8, 7)
            metric_layout.setSpacing(2)
            value_label = QtWidgets.QLabel(value)
            value_label.setAlignment(QtCore.Qt.AlignCenter)
            value_label.setWordWrap(False)
            value_label.setStyleSheet("font-size: 14px; font-weight: 900; color: #0f172a;")
            title_label = QtWidgets.QLabel(title)
            title_label.setAlignment(QtCore.Qt.AlignCenter)
            title_label.setStyleSheet("font-size: 12px; font-weight: 800; color: #475569;")
            metric_layout.addWidget(value_label)
            metric_layout.addWidget(title_label)
            return widget

        layout.addWidget(badge)
        layout.addWidget(name_block, 1)
        layout.addWidget(small_metric("Invoices", str(invoice_count), 82))
        layout.addWidget(small_metric("Revenue", Currency.format(revenue), 96))
        layout.addWidget(small_metric("Last Invoice", last_date, 120))

        def open_client(_event):
            if item is not None:
                self.client_list.setCurrentItem(item)
            self.client_selected.emit(client_name)

        card.mousePressEvent = open_client
        for child in card.findChildren(QtWidgets.QWidget):
            child.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            child.mousePressEvent = open_client
        return card
    
    def open_export_all_dialog(self):
        try:
            all_clients = self.get_all_clients()
            if not all_clients:
                QtWidgets.QMessageBox.warning(self, "No Clients", "No clients found to export.")
                return
            
            dialog = AllClientsExportDialog(self, all_clients)
            result = dialog.exec_()
            
            if result == QtWidgets.QDialog.Accepted and hasattr(dialog, '_export_params'):
                export_params = dialog._export_params
                if export_params["type"] == "pdf":
                    self.perform_all_clients_pdf_export(export_params, all_clients)
                elif export_params["type"] == "excel":
                    self.perform_all_clients_excel_export(export_params, all_clients)
        except Exception as e:
            _log.warning("Error opening export all dialog: %s", e)
    
    def get_all_clients(self):
        try:
            all_clients = set()
            invoices_data = FirebaseManager.load_invoices()
            if invoices_data:
                for invoice_data in invoices_data:
                    if invoice_data and 'meta' in invoice_data:
                        client_name = invoice_data['meta'].get('client_name', '')
                        if client_name:
                            all_clients.add(client_name)
            
            saved_clients = FirebaseManager.load_clients()
            if saved_clients:
                all_clients.update(saved_clients.keys())
            
            return sorted(list(all_clients))
        except Exception as e:
            _log.warning("Error getting all clients: %s", e)
            return []
    
    def perform_all_clients_pdf_export(self, export_params, clients):
        try:
            all_invoices_to_export = []
            for client_name in clients:
                client_invoices = self.load_client_invoices(client_name)
                filtered_invoices = self.filter_invoices_by_date_range(client_invoices, export_params)
                for invoice in filtered_invoices:
                    all_invoices_to_export.append((invoice, client_name))
            
            if not all_invoices_to_export:
                QtWidgets.QMessageBox.warning(self, "Export Warning", "No invoices found matching the selected criteria.")
                return
            
            self.generate_all_clients_pdf(all_invoices_to_export, export_params, clients)
        except Exception as e:
            _log.warning("Error performing all clients PDF export: %s", e)
    
    def perform_all_clients_excel_export(self, export_params, clients):
        try:
            all_invoices_to_export = []
            for client_name in clients:
                client_invoices = self.load_client_invoices(client_name)
                filtered_invoices = self.filter_invoices_by_date_range(client_invoices, export_params)
                for invoice in filtered_invoices:
                    all_invoices_to_export.append((invoice, client_name))
            
            if not all_invoices_to_export:
                QtWidgets.QMessageBox.warning(self, "Export Warning", "No invoices found matching the selected criteria.")
                return
            
            self.generate_all_clients_excel(all_invoices_to_export, export_params, clients)
        except Exception as e:
            _log.warning("Error performing all clients Excel export: %s", e)
    
    def load_client_invoices(self, client_name):
        try:
            invoices = []
            all_invoices_data = FirebaseManager.load_invoices()
            if not all_invoices_data:
                return invoices
            
            for invoice_data in all_invoices_data:
                try:
                    meta = invoice_data.get('meta', {})
                    if meta.get('client_name', '') == client_name:
                        invoice = Invoice.from_dict(invoice_data)
                        if 'meta' in invoice_data:
                            meta_data = invoice_data['meta']
                            invoice.date = meta_data.get('date', invoice.date)
                            invoice.due_date = meta_data.get('due_date', invoice.due_date)
                            invoice.invoice_number = meta_data.get('invoice_number', invoice.invoice_number)
                            invoice.status = meta_data.get('status', 'Pending')
                            invoice.client_name = meta_data.get('client_name', invoice.client_name)
                            _rd = meta_data.get('received_date', 'N/A') or 'N/A'
                            invoice.received_date = _normalize_date(_rd) if _rd not in ('N/A', '') else 'N/A'
                        invoices.append(invoice)
                except Exception as e:
                    _log.warning("Error processing invoice for %s: %s", client_name, e)
                    continue
            return invoices
        except Exception as e:
            _log.warning("Error loading invoices for %s: %s", client_name, e)
            return []
    
    def filter_invoices_by_date_range(self, invoices, export_params):
        filtered_invoices = []
        for invoice in invoices:
            try:
                invoice_date = None
                if hasattr(invoice, 'firebase_timestamp') and invoice.firebase_timestamp:
                    try:
                        if isinstance(invoice.firebase_timestamp, (int, float)):
                            invoice_date = datetime.fromtimestamp(invoice.firebase_timestamp)
                        elif isinstance(invoice.firebase_timestamp, str):
                            ts_str = invoice.firebase_timestamp.replace('Z', '+00:00')
                            invoice_date = datetime.fromisoformat(ts_str)
                    except:
                        pass
                
                if invoice_date is None:
                    invoice_date = self.parse_invoice_date(invoice.date)
                
                if invoice_date is None:
                    continue
                
                include_invoice = False
                if export_params["range"] == "all":
                    include_invoice = True
                elif export_params["range"] == "date_range":
                    from_date = export_params["from_date"]
                    to_date = export_params["to_date"]
                    invoice_date_only = invoice_date.date()
                    from_date_only = from_date.date() if isinstance(from_date, datetime) else from_date
                    to_date_only = to_date.date() if isinstance(to_date, datetime) else to_date
                    if from_date_only <= invoice_date_only <= to_date_only:
                        include_invoice = True
                elif export_params["range"] == "month":
                    month = export_params["month"]
                    year = export_params["year"]
                    if invoice_date.month == month and invoice_date.year == year:
                        include_invoice = True
                elif export_params["range"] == "year":
                    year = export_params["year"]
                    if invoice_date.year == year:
                        include_invoice = True
                
                if include_invoice:
                    filtered_invoices.append(invoice)
            except Exception as e:
                _log.warning("Error filtering invoice %s: %s", invoice.invoice_number, e)
                continue
        
        return filtered_invoices
    
    def parse_invoice_date(self, date_str):
        if not date_str:
            return None
        try:
            try:
                return datetime.strptime(date_str, "%m-%d-%Y")
            except ValueError:
                pass
            date_formats = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"]
            for date_format in date_formats:
                try:
                    return datetime.strptime(date_str, date_format)
                except ValueError:
                    continue
            return None
        except Exception as e:
            _log.info("(converted from print, see git history)")
            return None
    
    def generate_all_clients_pdf(self, all_invoices, export_params, clients):
        try:
            export_dir = Path.home() / "Downloads" / "Invoice_Exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if export_params["range"] == "all":
                filename = f"All_Clients_All_Invoices_{timestamp}.pdf"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%Y%m%d")
                to_date = export_params["to_date"].strftime("%Y%m%d")
                filename = f"All_Clients_Invoices_{from_date}_to_{to_date}.pdf"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                filename = f"All_Clients_Invoices_{year}_{month:02d}.pdf"
            elif export_params["range"] == "year":
                year = export_params["year"]
                filename = f"All_Clients_Invoices_{year}.pdf"
            
            pdf_path = export_dir / filename
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=landscape(A4),
                leftMargin=0.32*inch,
                rightMargin=0.32*inch,
                topMargin=0.25*inch,
                bottomMargin=0.3*inch,
            )
            elements = []
            styles = getSampleStyleSheet()
            
            header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#7f8c8d'), fontName='Helvetica', alignment=2)
            info_style = ParagraphStyle('InfoStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#2c3e50'), fontName='Helvetica-Bold')
            main_title_style = ParagraphStyle('MainTitle', parent=styles['Heading1'], fontSize=18, spaceAfter=30, textColor=colors.HexColor('#2c3e50'), alignment=1, fontName='Helvetica-Bold')
            stats_style = ParagraphStyle('StatsStyle', parent=styles['Normal'], fontSize=12, spaceAfter=20, textColor=colors.HexColor('#2c3e50'), alignment=1, fontName='Helvetica-Bold')
            
            generated_date = datetime.now().strftime("%m-%d-%Y")
            header_data = [[Paragraph(f"{generated_date}", header_style)]]
            header_table = Table(header_data, colWidths=[10.8*inch])
            header_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BOTTOMPADDING', (0,0), (-1,-1), 10), ('TOPPADDING', (0,0), (-1,-1), 10)]))
            elements.append(header_table)
            
            main_title = Paragraph("MABS ENGINEERING - INVOICE REPORT", main_title_style)
            elements.append(main_title)
            
            total_invoices = len(all_invoices)
            total_amount = sum(invoice.total for invoice, _ in all_invoices)
            total_clients = len(clients)
            stats_text = f"Total Clients: {total_clients}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Total Invoices: {total_invoices}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Total Revenue: {Currency.format(total_amount)}"
            stats_paragraph = Paragraph(stats_text, stats_style)
            elements.append(stats_paragraph)
            
            if export_params["range"] == "all":
                export_range_text = "All Invoices"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%m/%d/%y")
                to_date = export_params["to_date"].strftime("%m/%d/%y")
                export_range_text = f"{from_date} to {to_date}"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                month_name = datetime(2000, month, 1).strftime("%B")
                export_range_text = f"{month_name} {year}"
            elif export_params["range"] == "year":
                year = export_params["year"]
                export_range_text = f"Year {year}"
            
            period_para = Paragraph(f"<b>Period:</b> {export_range_text}", ParagraphStyle('PeriodLeft', parent=info_style, alignment=0, leftIndent=0, firstLineIndent=0, spaceBefore=4, spaceAfter=6))
            period_table = Table([[period_para]], colWidths=[10.8*inch])
            period_table.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),0), ('TOPPADDING',(0,0),(-1,-1),0), ('BOTTOMPADDING',(0,0),(-1,-1),0), ('ALIGN',(0,0),(-1,-1),'LEFT')]))
            elements.append(period_table)
            elements.append(Spacer(1, 12))
            
            if all_invoices:
                invoices_by_client = {}
                for invoice, client_name in all_invoices:
                    if client_name not in invoices_by_client:
                        invoices_by_client[client_name] = []
                    invoices_by_client[client_name].append(invoice)
                
                sorted_clients = sorted(invoices_by_client.keys())
                for client_name in sorted_clients:
                    client_header = Paragraph(f"<b>Client: {client_name}</b>", ParagraphStyle('ClientHeaderLeft', parent=info_style, alignment=0, leftIndent=0, firstLineIndent=0, spaceBefore=0, spaceAfter=0))
                    client_header_table = Table([[client_header]], colWidths=[10.8 * inch])
                    client_header_table.setStyle(TableStyle([('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0), ('TOPPADDING', (0,0), (-1,-1), 0), ('BOTTOMPADDING', (0,0), (-1,-1), 0), ('ALIGN', (0,0), (-1,-1), 'LEFT')]))
                    elements.append(client_header_table)
                    elements.append(Spacer(1, 6))
                    
                    header_style_center = ParagraphStyle(
                        'header_center',
                        alignment=1,
                        fontName='Helvetica-Bold',
                        fontSize=8,
                        leading=8,          # match font size
                        spaceBefore=-2,     # 👈 THIS FIX (push slightly down visually)
                        spaceAfter=0,
                        textColor=colors.whitesmoke
                    )

                    table_data = [[
                        Paragraph("Date", header_style_center),
                        Paragraph("Invoice No", header_style_center),
                        Paragraph("Project", header_style_center),
                        Paragraph("Subtotal", header_style_center),
                        Paragraph("Tax", header_style_center),
                        Paragraph("Down Payment", header_style_center),
                        Paragraph("Total", header_style_center),
                        Paragraph("Status", header_style_center),
                        Paragraph("Received Date", header_style_center),
                    ]]
                    cell_style = ParagraphStyle(
                        'InvoiceExportCell',
                        parent=styles['Normal'],
                        fontName='Helvetica',
                        fontSize=7.5,
                        leading=9,
                        alignment=1,
                        textColor=colors.HexColor('#2c3e50'),
                    )
                    for invoice in invoices_by_client[client_name]:
                        project_name = self.get_project_name(invoice)
                        total_down_payment = sum(item.down_payment for item in invoice.items)
                        status = invoice.status if hasattr(invoice, 'status') else "Pending"
                        received_date = getattr(invoice, 'received_date', 'N/A')
                        if not received_date or received_date == '':
                            received_date = 'N/A'
                        table_data.append([
                            Paragraph(str(invoice.date), cell_style),
                            Paragraph(str(invoice.invoice_number), cell_style),
                            Paragraph(str(project_name), cell_style),
                            Paragraph(Currency.format(invoice.subtotal), cell_style),
                            Paragraph(Currency.format(invoice.tax_amount), cell_style),
                            Paragraph(Currency.format(total_down_payment), cell_style),
                            Paragraph(Currency.format(invoice.total), cell_style),
                            Paragraph(str(status), cell_style),
                            Paragraph(str(received_date), cell_style),
                        ])
                    
                    invoice_table = Table(table_data, colWidths=[0.9*inch, 1.25*inch, 2.35*inch, 0.9*inch, 0.65*inch, 1.2*inch, 0.95*inch, 1.05*inch, 1.05*inch], repeatRows=1)
                    invoice_table.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#3498db')), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,0), 9), ('BOTTOMPADDING', (0,0), (-1,0), 10),
                        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff')), ('TEXTCOLOR', (0,1), (-1,-1), colors.HexColor('#2c3e50')),
                        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'), ('FONTSIZE', (0,1), (-1,-1), 8), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#bdc3c7')),
                        ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
                        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8f9fa'), colors.white]),
                    ]))
                    elements.append(invoice_table)
                    elements.append(Spacer(1, 20))
            else:
                no_data_style = ParagraphStyle('NoData', parent=styles['Normal'], fontSize=12, textColor=colors.HexColor('#7f8c8d'), alignment=1)
                elements.append(Paragraph("No invoices found for the selected criteria.", no_data_style))
            
            doc.build(elements)
            
            if FileManager.open_file(pdf_path):
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ PDF exported successfully!\n\nFile saved to: {pdf_path}\nThe PDF has been opened automatically.")
            else:
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ PDF exported successfully!\n\nFile saved to: {pdf_path}\nCould not open automatically. Please open manually.")
        except Exception as e:
            _log.warning("Error generating all clients PDF: %s", e)
            QtWidgets.QMessageBox.critical(self, "PDF Generation Error", f"Error generating PDF: {str(e)}")
    
    def generate_all_clients_excel(self, all_invoices, export_params, clients):
        try:
            export_dir = Path.home() / "Downloads" / "Invoice_Exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if export_params["range"] == "all":
                filename = f"All_Clients_All_Invoices_{timestamp}.xlsx"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%Y%m%d")
                to_date = export_params["to_date"].strftime("%Y%m%d")
                filename = f"All_Clients_Invoices_{from_date}_to_{to_date}.xlsx"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                filename = f"All_Clients_Invoices_{year}_{month:02d}.xlsx"
            elif export_params["range"] == "year":
                year = export_params["year"]
                filename = f"All_Clients_Invoices_{year}.xlsx"
            
            excel_path = export_dir / filename
            wb = openpyxl.Workbook()
            ws_summary = wb.active
            ws_summary.title = "Summary"
            
            ws_summary.merge_cells('A1:I1')
            ws_summary['A1'] = "MABS ENGINEERING - ALL CLIENTS INVOICE REPORT"
            ws_summary['A1'].font = Font(size=16, bold=True)
            ws_summary['A1'].alignment = Alignment(horizontal='center')
            
            if export_params["range"] == "all":
                export_range_text = "All Invoices"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%m/%d/%y")
                to_date = export_params["to_date"].strftime("%m/%d/%y")
                export_range_text = f"{from_date} to {to_date}"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                month_name = datetime(2000, month, 1).strftime("%B")
                export_range_text = f"{month_name} {year}"
            elif export_params["range"] == "year":
                year = export_params["year"]
                export_range_text = f"Year {year}"
            
            ws_summary['A2'] = f"Reporting Period: {export_range_text}"
            ws_summary['A2'].font = Font(bold=True)
            
            for client_name in sorted(clients):
                client_invoices = [(inv, cl) for inv, cl in all_invoices if cl == client_name]
                if not client_invoices:
                    continue
                
                ws_client = wb.create_sheet(title=client_name[:31])
                ws_client.merge_cells('A1:I1')
                ws_client['A1'] = f"Client: {client_name}"
                ws_client['A1'].font = Font(size=14, bold=True)
                ws_client['A1'].alignment = Alignment(horizontal='center')
                
                headers = ["Date", "Invoice Number", "Project Name", "Subtotal", "Tax", "Down Payment", "Total Due", "Status", "Received Date"]
                for col, header in enumerate(headers, 1):
                    cell = ws_client.cell(row=3, column=col, value=header)
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
                    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                
                for row, (invoice, _) in enumerate(client_invoices, 4):
                    project_name = self.get_project_name(invoice)
                    total_down_payment = sum(item.down_payment for item in invoice.items)
                    status = invoice.status if hasattr(invoice, 'status') else "Pending"
                    received_date = getattr(invoice, 'received_date', 'N/A')
                    if not received_date or received_date == '':
                        received_date = 'N/A'
                    
                    data = [invoice.date, invoice.invoice_number, project_name, float(invoice.subtotal), float(invoice.tax_amount), float(total_down_payment), float(invoice.total), status, received_date]
                    for col, value in enumerate(data, 1):
                        cell = ws_client.cell(row=row, column=col, value=value)
                        if col in [4,5,6,7]:
                            cell.number_format = '"$"#,##0.00'
                        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                
                column_widths = {1:14, 2:22, 3:34, 4:15, 5:12, 6:18, 7:16, 8:20, 9:18}
                for col_idx, width in column_widths.items():
                    column_letter = openpyxl.utils.get_column_letter(col_idx)
                    ws_client.column_dimensions[column_letter].width = width
                ws_client.freeze_panes = "A4"
            
            if len(wb.sheetnames) > 1 and ws_summary.max_row <= 10:
                default_sheet = wb["Summary"]
                if default_sheet.max_row <= 10:
                    wb.remove(default_sheet)
            
            wb.save(str(excel_path))
            
            if FileManager.open_file(excel_path):
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ Excel exported successfully!\n\nFile saved to: {excel_path}\nThe Excel file has been opened automatically.")
            else:
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ Excel exported successfully!\n\nFile saved to: {excel_path}\nCould not open automatically. Please open manually.")
        except Exception as e:
            _log.warning("Error generating all clients Excel: %s", e)
            QtWidgets.QMessageBox.critical(self, "Excel Generation Error", f"Error generating Excel: {str(e)}")
    
    def get_project_name(self, invoice):
        project_names = []
        for item in invoice.items:
            if hasattr(item, 'project_number') and item.project_number:
                project_names.append(item.project_number)
        if project_names:
            return ", ".join(project_names[:2])
        else:
            return "No Project Name"
    
    def load_clients(self):
        self.client_list.clear()
        try:
            all_clients = self.get_all_clients()
            clients_with_invoices = []
            total_invoice_count = 0
            total_revenue = Decimal("0")
            for client_name in all_clients:
                client_invoices = self.load_client_invoices(client_name)
                if client_invoices:
                    clients_with_invoices.append(client_name)
                    total_invoice_count += len(client_invoices)
                    for invoice in client_invoices:
                        total_revenue += getattr(invoice, "total", Decimal("0"))
            
            clients_with_invoices.sort()
            for client_name in clients_with_invoices:
                item = QtWidgets.QListWidgetItem(client_name)
                item.setData(QtCore.Qt.UserRole, client_name)
                item.setSizeHint(QtCore.QSize(0, 104))
                self.client_list.addItem(item)
                self.client_list.setItemWidget(item, self.create_client_card(client_name, self.load_client_invoices(client_name), item))
            
            has_clients = len(clients_with_invoices) > 0
            self.empty_state_label.setVisible(not has_clients)
            self.client_list.setVisible(has_clients)
            self.export_all_btn.setEnabled(has_clients)
            self.update_metric_card(self.client_count_label, "Clients", str(len(clients_with_invoices)))
            self.update_metric_card(self.invoice_count_label, "Invoices", str(total_invoice_count))
            self.update_metric_card(self.revenue_total_label, "Revenue", Currency.format(total_revenue))
        except Exception as e:
            _log.warning("Error loading clients from Firebase: %s", e)
            self.empty_state_label.setVisible(True)
            self.client_list.setVisible(False)
            self.export_all_btn.setEnabled(False)
    
    def filter_clients(self, search_text: str):
        search_text = search_text.lower().strip()
        for i in range(self.client_list.count()):
            item = self.client_list.item(i)
            item_text = item.text().lower()
            item.setHidden(search_text != "" and search_text not in item_text)
    
    def on_client_selected(self, item):
        if item and not item.isHidden():
            self.client_list.setCurrentItem(item)
            self.client_selected.emit(item.data(QtCore.Qt.UserRole) or item.text())


class AllClientsExportDialog(PDFExportDialog):
    """Dialog for exporting all clients' invoices"""
    
    def __init__(self, parent=None, all_clients=None):
        super().__init__(parent, "All Clients", [])
        self.all_clients = all_clients or []
        self.setWindowTitle("📊 Export All Clients")
    
    def init_ui(self):
        super().init_ui()
        self.setWindowTitle("📊 Export All Clients")
        client_card = self.findChild(QtWidgets.QWidget)
        if client_card:
            client_layout = client_card.layout()
            if client_layout and client_layout.itemAt(0):
                client_label = client_layout.itemAt(0).widget()
                if isinstance(client_label, QtWidgets.QLabel):
                    client_label.setText(f"🏢 Clients: {len(self.all_clients)} clients")
    
    def setup_pdf_tab(self):
        super().setup_pdf_tab()
        if hasattr(self, 'preview_label'):
            if self.export_range == "all":
                self.preview_label.setText("📋 Will export ALL invoices for ALL clients as PDF")
    
    def setup_excel_tab(self):
        super().setup_excel_tab()
        if hasattr(self, 'excel_preview_label'):
            if hasattr(self, 'excel_export_range'):
                range_type = self.excel_export_range
            else:
                range_type = "all"
            if range_type == "all":
                self.excel_preview_label.setText("📋 Will export ALL invoices for ALL clients as Excel")


class ReceivedDateDialog(QtWidgets.QDialog):
    """Dialog to capture received date when marking invoice as paid - OPTIMIZED"""
    
    def __init__(self, invoice, parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.setWindowTitle(f"Payment Received - {invoice.invoice_number}")
        self.setModal(True)
        self.setFixedSize(400, 250)
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowCloseButtonHint)
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        
        header = QtWidgets.QLabel(f"💰 Payment Received")
        header.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #27ae60;
                padding: 10px;
                background: #e8f5e9;
                border-radius: 8px;
                text-align: center;
            }
        """)
        header.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(header)
        
        info_text = f"""
        <b>Invoice:</b> {self.invoice.invoice_number}<br>
        <b>Client:</b> {self.invoice.client_name}<br>
        <b>Amount:</b> {Currency.format(self.invoice.total)}<br>
        <b>Due Date:</b> {self.invoice.due_date}
        """
        info_label = QtWidgets.QLabel(info_text)
        info_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                padding: 10px;
                background: #f8f9fa;
                border-radius: 5px;
            }
        """)
        info_label.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(info_label)
        
        date_layout = QtWidgets.QHBoxLayout()
        date_label = QtWidgets.QLabel("Received Date:")
        date_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        
        self.date_edit = QtWidgets.QDateEdit()
        self.date_edit.setDate(QtCore.QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM-dd-yyyy")
        # Disable scroll wheel
        self.date_edit.wheelEvent = lambda event: None
        # Disable arrow key changes
        def keyPressEvent(event, original=self.date_edit.keyPressEvent):
            if event.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
                return
            original(event)
        self.date_edit.keyPressEvent = keyPressEvent
        self.date_edit.stepBy = lambda x: None
        self.date_edit.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.date_edit.setStyleSheet("""
            QDateEdit {
                padding: 8px;
                border: 1px solid #bdc3c7;
                border-radius: 4px;
                font-size: 12px;
            }
        """)
        
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.date_edit)
        layout.addLayout(date_layout)
        
        note_label = QtWidgets.QLabel("Note: This date will be used to track when the payment was received.")
        note_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #7f8c8d;
                font-style: italic;
            }
        """)
        note_label.setWordWrap(True)
        layout.addWidget(note_label)
        
        btn_layout = QtWidgets.QHBoxLayout()
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #95a5a6;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #7f8c8d; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.save_btn = QtWidgets.QPushButton("✅ Mark as Paid")
        self.save_btn.setDefault(True)  # Allow Enter key to trigger
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #2ecc71; }
        """)
        self.save_btn.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)
        
        # Set focus to save button for quick Enter key press
        self.save_btn.setFocus()
    
    def get_received_date(self):
        """Always return received date in canonical MM-dd-YYYY format."""
        date = self.date_edit.date()
        return _normalize_date(date.toString("MM-dd-yyyy"))
class InvoiceHistoryViewWidget(QtWidgets.QWidget):
    """Main invoice history view with date range filter"""
    back_clicked = pyqtSignal()
    
    def __init__(self, client_name: str):
        super().__init__()
        self.client_name = client_name
        self.invoices = []
        self.filtered_invoices = []
        self.current_date_filter = None
        self.current_search_text = ""
        self.projects_data = {}
        self.status_cache = {}
        self._filtering = False
        self.init_ui()
        self.load_projects_data()
        self.load_status_cache()
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        header_widget = QtWidgets.QWidget()
        header_widget.setStyleSheet("""
            QWidget {
                background: #0f3b57;
                border-radius: 10px;
            }
        """)
        header_layout = QtWidgets.QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        self.back_btn = QtWidgets.QPushButton("🔙")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.12);
                color: white;
                border: 1px solid rgba(255,255,255,0.25);
                border-radius: 7px;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 14px;
            }
            QPushButton:hover {
                color: #f0f0f0;
                background-color: rgba(255,255,255,0.1);
                border-radius: 5px;
            }
        """)
        self.back_btn.setText("Back")
        self.back_btn.clicked.connect(self.back_clicked)
        self.back_btn.setFixedSize(92, 42)
        
        title = QtWidgets.QLabel(f"{self.client_name.upper()} - Invoice History")
        title_font = QtGui.QFont("Inter", 18, QtGui.QFont.Bold)
        title.setFont(title_font)
        title.setStyleSheet("""
            QLabel {
                font-size: 22px;
                font-weight: 800;
                color: white;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                padding: 8px;
            }
        """)
        title.setAlignment(QtCore.Qt.AlignCenter)
        
        self.pdf_export_btn = QtWidgets.QPushButton("📤 Export")
        self.pdf_export_btn.setFixedSize(120, 40)
        self.pdf_export_btn.setText("Export")
        self.pdf_export_btn.setFixedSize(130, 42)
        self.pdf_export_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #e67e22, stop:1 #f39c12);
                color: white;
                border: none;
                border-radius: 8px;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                font-weight: 800;
                font-size: 13px;
                padding: 8px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #d35400, stop:1 #e67e22);
                border: 2px solid #f39c12;
            }
        """)
        self.pdf_export_btn.setToolTip("Export PDFs for selected date range or all invoices")
        self.pdf_export_btn.clicked.connect(self.open_pdf_export_dialog)
        
        self.refresh_btn = QtWidgets.QPushButton("⟳ Refresh")
        self.refresh_btn.setFixedSize(110, 42)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.15);
                color: white;
                border: 1px solid rgba(255,255,255,0.35);
                border-radius: 8px;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-weight: 800;
                font-size: 13px;
                padding: 8px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.25);
                border-color: white;
            }
        """)
        self.refresh_btn.setToolTip("Reload invoices from Firebase")
        self.refresh_btn.clicked.connect(self._reload_invoices)

        header_layout.addWidget(self.back_btn)
        header_layout.addStretch()
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.refresh_btn)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.pdf_export_btn)
        layout.addWidget(header_widget)
        
        controls_card = QtWidgets.QFrame()
        controls_card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #d8e2ec;
                border-radius: 9px;
            }
        """)
        controls_layout = QtWidgets.QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setSpacing(12)
        
        self.date_range_widget = DateRangeWidget()
        self.date_range_widget.date_range_changed.connect(self.apply_date_range_filter)
        self.date_range_widget.date_range_cleared.connect(self.clear_date_range_filter)
        self.date_range_widget.search_bar.textChanged.connect(self.apply_search_filter)
        controls_layout.addWidget(self.date_range_widget)
        controls_layout.addStretch()
        
        quick_filter_layout = QtWidgets.QHBoxLayout()
        quick_filters_label = QtWidgets.QLabel("Quick Filters:")
        quick_filters_label.setStyleSheet('font-family: "Inter", "Segoe UI", Arial, sans-serif; font-size: 13px; font-weight: 800; color: #0f172a; padding: 5px;')
        quick_filter_layout.addWidget(quick_filters_label)
        
        self.last_7_days_btn = QtWidgets.QPushButton("Last 7 Days")
        self.last_30_days_btn = QtWidgets.QPushButton("Last 30 Days")
        self.this_month_btn = QtWidgets.QPushButton("This Month")
        self.this_year_btn = QtWidgets.QPushButton("This Year")
        self.all_time_btn = QtWidgets.QPushButton("All Time")
        
        quick_btn_style = """
            QPushButton {
                background-color: #f8fbfd;
                color: #0f172a;
                border: 1px solid #d8e2ec;
                padding: 0 14px;
                border-radius: 7px;
                font-size: 12px;
                font-weight: 800;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
            QPushButton:hover { border-color: #00756f; color: #00756f; }
            QPushButton:pressed { background-color: #eefaf8; }
        """
        
        for btn in [self.last_7_days_btn, self.last_30_days_btn, self.this_month_btn, self.this_year_btn, self.all_time_btn]:
            btn.setStyleSheet(quick_btn_style)
            btn.setFixedHeight(38)
        
        self.last_7_days_btn.clicked.connect(lambda: self.apply_quick_filter(7))
        self.last_30_days_btn.clicked.connect(lambda: self.apply_quick_filter(30))
        self.this_month_btn.clicked.connect(self.apply_this_month_filter)
        self.this_year_btn.clicked.connect(self.apply_this_year_filter)
        self.all_time_btn.clicked.connect(self.apply_all_time_filter)
        
        quick_filter_layout.addWidget(self.last_7_days_btn)
        quick_filter_layout.addWidget(self.last_30_days_btn)
        quick_filter_layout.addWidget(self.this_month_btn)
        quick_filter_layout.addWidget(self.this_year_btn)
        quick_filter_layout.addWidget(self.all_time_btn)
        controls_layout.addLayout(quick_filter_layout)
        layout.addWidget(controls_card)
        
        self.stats_widget = QtWidgets.QFrame()
        self.stats_widget.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #d8e2ec;
                border-radius: 9px;
            }
        """)
        self.stats_layout = QtWidgets.QHBoxLayout(self.stats_widget)
        self.stats_layout.setContentsMargins(16, 14, 16, 14)
        self.stats_layout.setSpacing(12)
        self.update_stats()
        layout.addWidget(self.stats_widget)

        table_card = QtWidgets.QFrame()
        table_card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #d8e2ec;
                border-radius: 9px;
            }
        """)
        table_layout = QtWidgets.QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        table_title = QtWidgets.QLabel("Invoice Records")
        table_title.setStyleSheet("""
            QLabel {
                color: #0f172a;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                font-size: 15px;
                font-weight: 900;
                padding: 14px 16px;
                border-bottom: 1px solid #e5edf5;
            }
        """)
        table_layout.addWidget(table_title)
        
        self.invoice_table = QtWidgets.QTableWidget()
        self.invoice_table.setColumnCount(11)
        self.invoice_table.setHorizontalHeaderLabels([
            "Date", "Invoice Number", "Project Name", "Total price", "Tax", "Down Payment", "Total Due", "Due Date", "Status", "Received Date", "Actions"
        ])
        self.invoice_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.invoice_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.invoice_table.setAlternatingRowColors(True)
        self.invoice_table.setSortingEnabled(False)
        self.invoice_table.setFont(QtGui.QFont("Inter", 10))
        self.invoice_table.verticalHeader().setVisible(False)
        self.invoice_table.verticalHeader().setDefaultSectionSize(54)
        
        self.invoice_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #d8e2ec;
                border-radius: 8px;
                font-size: 12px;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                gridline-color: #ecf0f1;
            }
            QTableWidget::item {
                padding: 10px;
                border-bottom: 1px solid #ecf0f1;
            }
            QTableWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QHeaderView::section {
                background-color: #34495e;
                color: white;
                padding: 12px 8px;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        
        header = self.invoice_table.horizontalHeader()
        header.setFont(QtGui.QFont("Inter", 10, QtGui.QFont.Bold))
        for i in range(self.invoice_table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)
        header.setMinimumSectionSize(96)
        header.setSectionResizeMode(8, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(10, QtWidgets.QHeaderView.Fixed)
        self.invoice_table.setColumnWidth(8, 150)
        self.invoice_table.setColumnWidth(10, 160)
        
        table_layout.addWidget(self.invoice_table)
        layout.addWidget(table_card, 1)
        self.load_all_invoices()
    
    def sync_invoice_to_revenue(self, invoice: Invoice):
        try:
            if not FIREBASE_AVAILABLE:
                return
            
            from firebase_admin import db
            revenue_ref = db.reference('revenue')
            all_revenue = revenue_ref.get()
            
            if not all_revenue:
                return
            
            revenue_to_update = None
            revenue_id = None
            
            for rev_id, revenue in all_revenue.items():
                if revenue and revenue.get('is_invoice') and revenue.get('invoice_number') == invoice.invoice_number:
                    revenue_to_update = revenue
                    revenue_id = rev_id
                    break
            
            if not revenue_to_update:
                return
            
            changed = False
            updates = {}
            
            new_due_date = getattr(invoice, 'due_date', 'N/A')
            if new_due_date != revenue_to_update.get('due_date', 'N/A'):
                updates['due_date'] = new_due_date
                changed = True
            
            new_status = invoice.status if hasattr(invoice, 'status') else 'Pending'
            if new_status != revenue_to_update.get('status', 'Pending'):
                updates['status'] = new_status
                changed = True
            
            new_received_date = getattr(invoice, 'received_date', 'N/A')
            if not new_received_date or new_received_date == '':
                new_received_date = 'N/A'
            
            if new_received_date != revenue_to_update.get('received_date', 'N/A'):
                updates['received_date'] = new_received_date
                changed = True
                if new_status == "Paid" and new_received_date not in ('N/A', 'N\\A', ''):
                    try:
                        updates['year'] = datetime.strptime(
                            _normalize_date(new_received_date), "%m-%d-%Y"
                        ).year
                    except Exception:
                        pass
            
            if changed:
                updates['updated_at'] = datetime.now().isoformat()
                revenue_ref.child(revenue_id).update(updates)
                self.refresh_balance_sheet()
        except Exception as e:
            _log.warning("Error syncing invoice to revenue: %s", e)
    
    def refresh_balance_sheet(self):
        try:
            main_window = self.window()
            if hasattr(main_window, 'balance_sheet_tab'):
                balance_tab = main_window.balance_sheet_tab
                if hasattr(balance_tab, 'refresh_invoice_revenues'):
                    balance_tab.refresh_invoice_revenues()
                else:
                    balance_tab.load_all_financial_data()
                    balance_tab.update_annual_summary()
                    balance_tab.on_category_changed(balance_tab.current_category)
                    balance_tab.update_stats_cards()
        except Exception as e:
            _log.warning("Error refreshing balance sheet: %s", e)
    
    def highlight_selected_quick_filter(self, selected_button):
        default_style = """
            QPushButton {
                background-color: #f8fbfd;
                color: #0f172a;
                border: 1px solid #d8e2ec;
                padding: 0 14px;
                border-radius: 7px;
                font-size: 12px;
                font-weight: 800;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
            QPushButton:hover { border-color: #00756f; color: #00756f; }
        """
        selected_style = """
            QPushButton {
                background-color: #00756f;
                color: white;
                border: 1px solid #00756f;
                padding: 0 14px;
                border-radius: 7px;
                font-size: 12px;
                font-weight: 800;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
            QPushButton:hover { background-color: #00645f; }
        """
        
        for btn in [self.last_7_days_btn, self.last_30_days_btn, self.this_month_btn, self.this_year_btn, self.all_time_btn]:
            btn.setStyleSheet(default_style)
        selected_button.setStyleSheet(selected_style)
    
    def get_invoice_parsed_date(self, invoice):
        if hasattr(invoice, "_parsed_date"):
            return invoice._parsed_date
        parsed = self.parse_invoice_date(invoice)
        invoice._parsed_date = parsed
        return parsed
    
    def perform_excel_export(self, export_params):
        try:
            invoices_to_export = []
            for invoice, json_file in self.invoices:
                try:
                    invoice_date = self.parse_invoice_date(invoice)
                    if invoice_date is None:
                        continue
                    
                    include_invoice = False
                    if export_params["range"] == "all":
                        include_invoice = True
                    elif export_params["range"] == "date_range":
                        from_date = export_params["from_date"]
                        to_date = export_params["to_date"]
                        invoice_date_only = invoice_date.date()
                        from_date_only = from_date.date() if isinstance(from_date, datetime) else from_date
                        to_date_only = to_date.date() if isinstance(to_date, datetime) else to_date
                        if from_date_only <= invoice_date_only <= to_date_only:
                            include_invoice = True
                    elif export_params["range"] == "month":
                        month = export_params["month"]
                        year = export_params["year"]
                        if invoice_date.month == month and invoice_date.year == year:
                            include_invoice = True
                    elif export_params["range"] == "year":
                        year = export_params["year"]
                        if invoice_date.year == year:
                            include_invoice = True
                    
                    if include_invoice:
                        invoices_to_export.append((invoice, json_file))
                        invoices_to_export.reverse()
                except Exception as e:
                    continue
            
            if not invoices_to_export:
                QtWidgets.QMessageBox.warning(self, "Export Warning", "No invoices found matching the selected criteria.")
                return
            
            self.generate_combined_excel(invoices_to_export, export_params)
        except Exception as e:
            _log.warning("Error performing Excel export: %s", e)
    
    def generate_combined_excel(self, invoices, export_params):
        try:
            export_dir = Path.home() / "Downloads" / "Invoice_Exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if export_params["range"] == "all":
                filename = f"{self.client_name}_All_Invoices_{timestamp}.xlsx"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%Y%m%d")
                to_date = export_params["to_date"].strftime("%Y%m%d")
                filename = f"{self.client_name}_Invoices_{from_date}_to_{to_date}.xlsx"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                filename = f"{self.client_name}_Invoices_{year}_{month:02d}.xlsx"
            elif export_params["range"] == "year":
                year = export_params["year"]
                filename = f"{self.client_name}_Invoices_{year}.xlsx"
            
            excel_path = export_dir / filename
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Invoice History"
            
            ws.merge_cells('A1:J1')
            ws['A1'] = f"MABS ENGINEERING - {self.client_name.upper()} INVOICES"
            ws['A1'].font = Font(size=16, bold=True)
            ws['A1'].alignment = Alignment(horizontal='center')
            
            if export_params["range"] == "all":
                export_range_text = "All Invoices"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%m/%d/%y")
                to_date = export_params["to_date"].strftime("%m/%d/%y")
                export_range_text = f"{from_date} to {to_date}"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                month_name = datetime(2000, month, 1).strftime("%B")
                export_range_text = f"{month_name} {year}"
            elif export_params["range"] == "year":
                year = export_params["year"]
                export_range_text = f"Year {year}"
            
            ws['A2'] = f"Period: {export_range_text}"
            ws['A2'].font = Font(bold=True)
            
            headers = ["Date", "Invoice Number", "Project Name", "Subtotal", "Tax", "Down Payment", "Total Due", "Due Date", "Status", "Received Date"]
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=4, column=col, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            
            for row, (invoice, _) in enumerate(invoices, 5):
                project_name = self.get_project_name(invoice)
                total_down_payment = sum(item.down_payment for item in invoice.items)
                status = invoice.status if hasattr(invoice, 'status') else self.get_invoice_status(invoice)
                due_date = getattr(invoice, 'due_date', 'N/A')
                if not due_date or due_date == '':
                    due_date = 'N/A'
                received_date = getattr(invoice, 'received_date', 'N/A')
                if not received_date or received_date == '':
                    received_date = 'N/A'
                
                data = [invoice.date, invoice.invoice_number, project_name, float(invoice.subtotal), float(invoice.tax_amount), float(total_down_payment), float(invoice.total), due_date, status, received_date]
                for col, value in enumerate(data, 1):
                    cell = ws.cell(row=row, column=col, value=value)
                    if col in [4,5,6,7]:
                        cell.number_format = '"$"#,##0.00'
                    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            
            column_widths = {1:14, 2:22, 3:34, 4:15, 5:12, 6:18, 7:16, 8:16, 9:20, 10:18}
            for col_idx, width in column_widths.items():
                column_letter = openpyxl.utils.get_column_letter(col_idx)
                ws.column_dimensions[column_letter].width = width
            ws.freeze_panes = "A5"
            
            wb.save(str(excel_path))
            
            if FileManager.open_file(excel_path):
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ Excel exported successfully!\n\nFile saved to: {excel_path}\nThe Excel file has been opened automatically.")
            else:
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ Excel exported successfully!\n\nFile saved to: {excel_path}\nCould not open automatically. Please open manually.")
        except Exception as e:
            _log.warning("Error generating combined Excel: %s", e)
            QtWidgets.QMessageBox.critical(self, "Excel Generation Error", f"Error generating Excel: {str(e)}")
    
    def load_status_cache(self):
        try:
            cache_file = Config.INVOICES_DIR / "status_cache.json"
            if cache_file.exists():
                self.status_cache = FileManager.load_json(cache_file, {})
            else:
                self.status_cache = {}
        except Exception as e:
            _log.warning("Error loading status cache: %s", e)
            self.status_cache = {}
    
    def save_status_cache(self):
        try:
            cache_file = Config.INVOICES_DIR / "status_cache.json"
            FileManager.save_json(cache_file, self.status_cache)
        except Exception as e:
            _log.warning("Error saving status cache: %s", e)
    
    def get_cached_status(self, invoice_number: str) -> str:
        return self.status_cache.get(invoice_number, "")
    
    def set_cached_status(self, invoice_number: str, status: str):
        self.status_cache[invoice_number] = status
        self.save_status_cache()
    
    def update_invoice_status_in_file(self, invoice_number: str, new_status: str):
        try:
            for invoice, json_file in self.invoices:
                if invoice.invoice_number == invoice_number:
                    invoice.status = new_status
                    if FIREBASE_AVAILABLE:
                        success = FirebaseManager.update_invoice_status(invoice_number, new_status)
                        if success:
                            self.sync_invoice_to_revenue(invoice)
                    break
        except Exception as e:
            _log.warning("Error updating invoice file status: %s", e)
    
    def open_pdf_export_dialog(self):
        try:
            available_dates = []
            for invoice, _ in self.invoices:
                try:
                    invoice_date = self.parse_invoice_date(invoice.date)
                    if invoice_date:
                        available_dates.append(invoice_date)
                except:
                    continue
            
            dialog = PDFExportDialog(self, self.client_name, available_dates)
            result = dialog.exec_()
            
            if result == QtWidgets.QDialog.Accepted and hasattr(dialog, '_export_params'):
                export_params = dialog._export_params
                if export_params["type"] == "pdf":
                    self.perform_pdf_export(export_params)
                elif export_params["type"] == "excel":
                    self.perform_excel_export(export_params)
        except Exception as e:
            _log.warning("Error opening PDF export dialog: %s", e)
    
    def perform_pdf_export(self, export_params):
        try:
            invoices_to_export = []
            for invoice, json_file in self.invoices:
                try:
                    invoice_date = None
                    if hasattr(invoice, 'firebase_timestamp') and invoice.firebase_timestamp:
                        try:
                            if isinstance(invoice.firebase_timestamp, (int, float)):
                                invoice_date = datetime.fromtimestamp(invoice.firebase_timestamp)
                            elif isinstance(invoice.firebase_timestamp, str):
                                ts_str = invoice.firebase_timestamp.replace('Z', '+00:00')
                                invoice_date = datetime.fromisoformat(ts_str)
                        except:
                            pass
                    
                    if invoice_date is None:
                        invoice_date = self.parse_invoice_date(invoice)
                    
                    if invoice_date is None:
                        continue
                    
                    include_invoice = False
                    if export_params["range"] == "all":
                        include_invoice = True
                    elif export_params["range"] == "date_range":
                        from_date = export_params["from_date"]
                        to_date = export_params["to_date"]
                        invoice_date_only = invoice_date.date()
                        from_date_only = from_date.date() if isinstance(from_date, datetime) else from_date
                        to_date_only = to_date.date() if isinstance(to_date, datetime) else to_date
                        if from_date_only <= invoice_date_only <= to_date_only:
                            include_invoice = True
                    elif export_params["range"] == "month":
                        month = export_params["month"]
                        year = export_params["year"]
                        if invoice_date.month == month and invoice_date.year == year:
                            include_invoice = True
                    elif export_params["range"] == "year":
                        year = export_params["year"]
                        if invoice_date.year == year:
                            include_invoice = True
                    
                    if include_invoice:
                        invoices_to_export.append((invoice, json_file))
                        invoices_to_export.reverse()

                except Exception as e:
                    continue
            
            if not invoices_to_export:
                QtWidgets.QMessageBox.warning(self, "Export Warning", "No invoices found matching the selected criteria.")
                return
            
            self.generate_combined_pdf(invoices_to_export, export_params)
        except Exception as e:
            _log.warning("Error performing PDF export: %s", e)
    
    def generate_combined_pdf(self, invoices, export_params):
        try:
            export_dir = Path.home() / "Downloads" / "Invoice_Exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if export_params["range"] == "all":
                filename = f"{self.client_name}_All_Invoices_{timestamp}.pdf"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%Y%m%d")
                to_date = export_params["to_date"].strftime("%Y%m%d")
                filename = f"{self.client_name}_Invoices_{from_date}_to_{to_date}.pdf"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                filename = f"{self.client_name}_Invoices_{year}_{month:02d}.pdf"
            elif export_params["range"] == "year":
                year = export_params["year"]
                filename = f"{self.client_name}_Invoices_{year}.pdf"
            
            pdf_path = export_dir / filename
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=landscape(A4),
                leftMargin=0.32*inch,
                rightMargin=0.32*inch,
                topMargin=0.25*inch,
                bottomMargin=0.3*inch,
            )
            elements = []
            styles = getSampleStyleSheet()
            
            header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#7f8c8d'), fontName='Helvetica', alignment=2)
            info_style = ParagraphStyle('InfoStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#2c3e50'), fontName='Helvetica-Bold')
            main_title_style = ParagraphStyle('MainTitle', parent=styles['Heading1'], fontSize=18, spaceAfter=30, textColor=colors.HexColor('#2c3e50'), alignment=1, fontName='Helvetica-Bold')
            stats_style = ParagraphStyle('StatsStyle', parent=styles['Normal'], fontSize=12, spaceAfter=20, textColor=colors.HexColor('#2c3e50'), alignment=1, fontName='Helvetica-Bold')
            
            generated_date = datetime.now().strftime("%m-%d-%Y")
            header_data = [['', Paragraph(f"{generated_date}", header_style)]]
            header_table = Table(header_data, colWidths=[8.8*inch, 2*inch])
            header_table.setStyle(TableStyle([
                ('ALIGN', (0,0), (0,0), 'LEFT'), ('ALIGN', (1,0), (1,0), 'RIGHT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 10)
            ]))
            elements.append(header_table)
            
            main_title = Paragraph("MABS ENGINEERING INVOICE HISTORY", main_title_style)
            elements.append(main_title)
            
            total_invoices = len(invoices)
            total_amount = sum(invoice.total for invoice, _ in invoices)
            stats_text = f"Total Invoices: {total_invoices}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Total Revenue: {Currency.format(total_amount)}"
            stats_paragraph = Paragraph(stats_text, stats_style)
            elements.append(stats_paragraph)
            
            if export_params["range"] == "all":
                export_range_text = "All Invoices"
            elif export_params["range"] == "date_range":
                from_date = export_params["from_date"].strftime("%m/%d/%y")
                to_date = export_params["to_date"].strftime("%m/%d/%y")
                export_range_text = f"{from_date} to {to_date}"
            elif export_params["range"] == "month":
                month = export_params["month"]
                year = export_params["year"]
                month_name = datetime(2000, month, 1).strftime("%B")
                export_range_text = f"{month_name} {year}"
            elif export_params["range"] == "year":
                year = export_params["year"]
                export_range_text = f"Year {year}"
            
            client_export_para = Paragraph(f"{self.client_name} - {export_range_text}", ParagraphStyle('ClientExportLeft', parent=info_style, alignment=0, leftIndent=0, firstLineIndent=0, spaceBefore=4, spaceAfter=12))
            client_export_table = Table([[client_export_para]], colWidths=[10.8 * inch])
            client_export_table.setStyle(TableStyle([
                ('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),0),
                ('TOPPADDING',(0,0),(-1,-1),0), ('BOTTOMPADDING',(0,0),(-1,-1),0),
                ('ALIGN',(0,0),(-1,-1),'LEFT')
            ]))
            elements.append(client_export_table)
            elements.append(Spacer(1, 10))
            
            if invoices:
                header_style_center = ParagraphStyle(
                    'header_center',
                    alignment=1,
                    fontName='Helvetica-Bold',
                    fontSize=8,
                    leading=8,          # ✅ important
                    spaceBefore=-2,     # ✅ visual vertical centering
                    spaceAfter=0,
                    textColor=colors.whitesmoke
                )

                table_data = [[
                    Paragraph("Date", header_style_center),
                    Paragraph("Invoice No", header_style_center),
                    Paragraph("Project", header_style_center),
                    Paragraph("Subtotal", header_style_center),
                    Paragraph("Tax", header_style_center),
                    Paragraph("Down Payment", header_style_center),
                    Paragraph("Total", header_style_center),
                    Paragraph("Status", header_style_center),
                    Paragraph("Received Date", header_style_center),
                ]]
                cell_style = ParagraphStyle(
                    'InvoiceClientExportCell',
                    parent=styles['Normal'],
                    fontName='Helvetica',
                    fontSize=7.5,
                    leading=9,
                    alignment=1,
                    textColor=colors.HexColor('#2c3e50'),
                )
                for invoice, _ in invoices:
                    project_name = self.get_project_name(invoice)
                    total_down_payment = sum(item.down_payment for item in invoice.items)
                    status = invoice.status if hasattr(invoice, 'status') else self.get_invoice_status(invoice)
                    received_date = getattr(invoice, 'received_date', 'N/A')
                    if not received_date or received_date == '':
                        received_date = 'N/A'
                    table_data.append([
                        Paragraph(str(invoice.date), cell_style),
                        Paragraph(str(invoice.invoice_number), cell_style),
                        Paragraph(str(project_name), cell_style),
                        Paragraph(Currency.format(invoice.subtotal), cell_style),
                        Paragraph(Currency.format(invoice.tax_amount), cell_style),
                        Paragraph(Currency.format(total_down_payment), cell_style),
                        Paragraph(Currency.format(invoice.total), cell_style),
                        Paragraph(str(status), cell_style),
                        Paragraph(str(received_date), cell_style),
                    ])
                
                invoice_table = Table(table_data, colWidths=[0.9*inch, 1.25*inch, 2.35*inch, 0.9*inch, 0.65*inch, 1.2*inch, 0.95*inch, 1.05*inch, 1.05*inch], repeatRows=1)
                invoice_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0,0), (-1,0), 9), ('BOTTOMPADDING', (0,0), (-1,0), 10),
                    ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff')), ('TEXTCOLOR', (0,1), (-1,-1), colors.HexColor('#2c3e50')),
                    ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
                    ('FONTNAME', (0,1), (-1,-1), 'Helvetica'), ('FONTSIZE', (0,1), (-1,-1), 8),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#bdc3c7')),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8f9fa'), colors.white]),
                ]))
                elements.append(invoice_table)
            else:
                no_data_style = ParagraphStyle('NoData', parent=styles['Normal'], fontSize=12, textColor=colors.HexColor('#7f8c8d'), alignment=1)
                elements.append(Paragraph("No invoices found for the selected criteria.", no_data_style))
            
            doc.build(elements)
            
            if FileManager.open_file(pdf_path):
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ PDF exported successfully!\n\nFile saved to: {pdf_path}\nThe PDF has been opened automatically.")
            else:
                QtWidgets.QMessageBox.information(self, "Export Success", f"✅ PDF exported successfully!\n\nFile saved to: {pdf_path}\nCould not open automatically. Please open manually.")
        except Exception as e:
            _log.warning("Error generating combined PDF: %s", e)
            QtWidgets.QMessageBox.critical(self, "PDF Generation Error", f"Error generating PDF: {str(e)}")
    
    def get_invoice_status(self, invoice: Invoice) -> str:
        cached_status = self.get_cached_status(invoice.invoice_number)
        if cached_status:
            return cached_status
        if hasattr(invoice, 'status') and invoice.status:
            self.set_cached_status(invoice.invoice_number, invoice.status)
            return invoice.status
        try:
            try:
                due_date = datetime.strptime(invoice.due_date, "%Y-%m-%d")
            except ValueError:
                try:
                    due_date = datetime.strptime(invoice.due_date, "%d/%m/%Y")
                except ValueError:
                    return "Pending"
            today = datetime.now().date()
            due_date_date = due_date.date()
            if due_date_date < today:
                return "Overdue"
            else:
                return "Pending"
        except Exception as e:
            _log.warning("Error determining invoice status: %s", e)
            return "Pending"
    
    def _reload_invoices(self):
        """Refresh button: reload invoices and re-render the table."""
        try:
            self.invoices = []
            self.load_invoices_from_firebase()
        except Exception as e:
            _log.warning("Error reloading invoices: %s", e)

    def load_projects_data(self):
        try:
            projects = FirebaseManager.load_projects()
            self.projects_data = {}
            for project in projects:
                if isinstance(project, dict):
                    project_number = project.get("project_number", "")
                    project_name = project.get("project_name", "")
                    if project_number and project_name:
                        self.projects_data[project_number] = project_name
        except Exception as e:
            _log.warning("Error loading projects data: %s", e)
            self.projects_data = {}
    
    def get_project_name(self, invoice: Invoice) -> str:
        project_names = []
        for item in invoice.items:
            project_number = item.project_number
            if project_number and project_number in self.projects_data:
                project_name = self.projects_data[project_number]
                if project_name and project_name not in project_names:
                    project_names.append(project_name)
        if project_names:
            return ", ".join(project_names[:2])
        else:
            if invoice.items:
                first_item = invoice.items[0]
                return first_item.description or "No Project Name"
            return "No Project Name"
    
    def parse_invoice_date(self, invoice_or_date):
        if hasattr(invoice_or_date, 'firebase_timestamp') and invoice_or_date.firebase_timestamp:
            try:
                if isinstance(invoice_or_date.firebase_timestamp, (int, float)):
                    return datetime.fromtimestamp(invoice_or_date.firebase_timestamp)
                elif isinstance(invoice_or_date.firebase_timestamp, str):
                    ts_str = invoice_or_date.firebase_timestamp.replace('Z', '+00:00')
                    return datetime.fromisoformat(ts_str)
            except:
                pass
        
        if hasattr(invoice_or_date, 'date'):
            date_str = invoice_or_date.date
        else:
            date_str = str(invoice_or_date)
        
        if not date_str:
            return datetime.min
        
        try:
            try:
                return datetime.strptime(date_str, "%m-%d-%Y")
            except ValueError:
                pass
            date_formats = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"]
            for date_format in date_formats:
                try:
                    return datetime.strptime(date_str, date_format)
                except ValueError:
                    continue
            return datetime.min
        except Exception as e:
            _log.info("(converted from print, see git history)")
            return datetime.min
    
    def load_all_invoices(self):
        self.invoices = []
        self.verify_firebase_connection()
        
        try:
            all_invoices_data = FirebaseManager.load_invoices()
            if not all_invoices_data:
                return
            
            invoices_with_timestamp = []
            for invoice_data in all_invoices_data:
                try:
                    meta = invoice_data.get('meta', {})
                    client_name = meta.get('client_name', '')
                    if client_name == self.client_name:
                        invoice = Invoice.from_dict(invoice_data)
                        if 'meta' in invoice_data:
                            meta_data = invoice_data['meta']
                            invoice.date = meta_data.get('date', invoice.date)
                            invoice.due_date = meta_data.get('due_date', invoice.due_date)
                            invoice.invoice_number = meta_data.get('invoice_number', invoice.invoice_number)
                            invoice.status = meta_data.get('status', 'Pending')
                            invoice.client_name = meta_data.get('client_name', invoice.client_name)
                            invoice.tax_rate = Decimal(str(meta_data.get('tax_rate', 0.0)))
                            invoice.notes = meta_data.get('notes', Config.DEFAULT_TERMS)
                            _rd = meta_data.get('received_date', 'N/A') or 'N/A'
                            invoice.received_date = _normalize_date(_rd) if _rd not in ('N/A', '') else 'N/A'
                        
                        timestamp = None
                        if 'meta' in invoice_data and 'created_at' in invoice_data['meta']:
                            created_at = invoice_data['meta']['created_at']
                            try:
                                if isinstance(created_at, (int, float)):
                                    timestamp = created_at
                                elif isinstance(created_at, str):
                                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                    timestamp = dt.timestamp()
                            except:
                                pass
                        
                        if timestamp is None and hasattr(invoice, 'firebase_timestamp') and invoice.firebase_timestamp:
                            try:
                                if isinstance(invoice.firebase_timestamp, (int, float)):
                                    timestamp = invoice.firebase_timestamp
                                elif isinstance(invoice.firebase_timestamp, str):
                                    dt = datetime.fromisoformat(invoice.firebase_timestamp.replace('Z', '+00:00'))
                                    timestamp = dt.timestamp()
                            except:
                                pass
                        
                        if timestamp is None:
                            parsed_date = self.parse_invoice_date(invoice)
                            if parsed_date:
                                timestamp = parsed_date.timestamp()
                            else:
                                timestamp = 0
                        
                        invoice.firebase_timestamp = timestamp
                        invoices_with_timestamp.append((timestamp, invoice, None))
                except Exception as e:
                    _log.warning("Error processing invoice data: %s", e)
                    continue
            
            invoices_with_timestamp.sort(key=lambda x: x[0] if x[0] else 0, reverse=True)
            self.invoices = [(inv, json_file) for timestamp, inv, json_file in invoices_with_timestamp]
            self.apply_all_time_filter()
        except Exception as e:
            _log.warning("Error loading invoices from Firebase: %s", e)
            QtWidgets.QMessageBox.warning(self, "Load Error", f"Error loading invoices from Firebase: {str(e)}")
    
    def clear_quick_filter_highlighting(self):
        default_style = """
            QPushButton {
                background-color: #f8fbfd;
                color: #0f172a;
                border: 1px solid #d8e2ec;
                padding: 0 14px;
                border-radius: 7px;
                font-size: 12px;
                font-weight: 800;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }
            QPushButton:hover { border-color: #00756f; color: #00756f; }
        """
        for btn in [self.last_7_days_btn, self.last_30_days_btn, self.this_month_btn, self.this_year_btn, self.all_time_btn]:
            btn.setStyleSheet(default_style)
    
    def apply_date_range_filter(self, from_date: datetime, to_date: datetime):
        try:
            self.current_date_filter = (from_date, to_date)
            self.clear_quick_filter_highlighting()
            self.apply_filters()
        except Exception as e:
            _log.warning("Error applying date range filter: %s", e)
    
    def clear_date_range_filter(self):
        try:
            self.current_date_filter = None
            self.apply_filters()
        except Exception as e:
            _log.warning("Error clearing date range filter: %s", e)
    
    def apply_search_filter(self, search_text: str):
        try:
            self.current_search_text = search_text.lower().strip()
            self.apply_filters()
        except Exception as e:
            _log.warning("Error applying search filter: %s", e)
    
    def apply_filters(self):
        if hasattr(self, "_filtering") and self._filtering:
            return
        self._filtering = True
        try:
            filtered_invoices = []
            for invoice, json_file in self.invoices:
                date_match = True
                if self.current_date_filter:
                    from_date, to_date = self.current_date_filter
                    try:
                        invoice_date = self.parse_invoice_date(invoice)
                        if invoice_date is None:
                            date_match = True
                        else:
                            invoice_date_only = invoice_date.date()
                            from_date_only = from_date.date()
                            to_date_only = to_date.date()
                            if not (from_date_only <= invoice_date_only <= to_date_only):
                                date_match = False
                    except Exception as e:
                        date_match = False
                
                search_match = True
                if self.current_search_text:
                    search_terms = []
                    search_terms.append(invoice.invoice_number.lower())
                    project_name = self.get_project_name(invoice).lower()
                    search_terms.append(project_name)
                    current_status = self.get_invoice_status(invoice).lower()
                    search_terms.append(current_status)
                    search_terms.append(invoice.date.lower())
                    search_terms.append(invoice.client_name.lower())
                    search_terms.append(str(invoice.subtotal))
                    search_terms.append(str(invoice.tax_amount))
                    search_terms.append(str(invoice.total))
                    for item in invoice.items:
                        search_terms.append(item.description.lower())
                        search_terms.append(item.project_number.lower())
                        search_terms.append(str(item.quantity))
                        search_terms.append(str(item.unit_price))
                        search_terms.append(str(item.down_payment))
                        search_terms.append(str(item.total))
                    search_match = any(self.current_search_text in term for term in search_terms)
                
                if date_match and search_match:
                    filtered_invoices.append((invoice, json_file))
            
            self.filtered_invoices = filtered_invoices
            self.display_invoices(self.filtered_invoices)
            self.update_stats(self.filtered_invoices)
        except Exception as e:
            _log.warning("Error in apply_filters: %s", e)
            QtWidgets.QMessageBox.warning(self, "Filter Error", f"Error applying filters: {e}")
        self._filtering = False
    
    def apply_quick_filter(self, days: int):
        try:
            if days == 7:
                self.highlight_selected_quick_filter(self.last_7_days_btn)
            elif days == 30:
                self.highlight_selected_quick_filter(self.last_30_days_btn)
            
            self.current_date_filter = None
            self.date_range_widget.is_date_range_applied = False
            self.date_range_widget.apply_clear_btn.setText("Apply")
            self.date_range_widget.apply_clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #229954; }
            """)
            self.date_range_widget.hide_date_range()
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)
            self.current_date_filter = (from_date, to_date)
            self.date_range_widget.set_date_range(from_date, to_date)
            self.apply_filters()
        except Exception as e:
            _log.warning("Error applying quick filter: %s", e)
    
    def apply_this_month_filter(self):
        try:
            self.highlight_selected_quick_filter(self.this_month_btn)
            self.date_range_widget.hide_date_range()
            self.current_date_filter = None
            self.date_range_widget.is_date_range_applied = False
            self.date_range_widget.apply_clear_btn.setText("Apply")
            self.date_range_widget.apply_clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #229954; }
            """)
            today = datetime.now()
            from_date = datetime(today.year, today.month, 1)
            to_date = today
            self.current_date_filter = (from_date, to_date)
            self.date_range_widget.set_date_range(from_date, to_date)
            self.apply_filters()
        except Exception as e:
            _log.warning("Error applying this month filter: %s", e)
    
    def apply_this_year_filter(self):
        try:
            self.highlight_selected_quick_filter(self.this_year_btn)
            self.date_range_widget.hide_date_range()
            self.current_date_filter = None
            self.date_range_widget.is_date_range_applied = False
            self.date_range_widget.apply_clear_btn.setText("Apply")
            self.date_range_widget.apply_clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #229954; }
            """)
            today = datetime.now()
            from_date = datetime(today.year, 1, 1)
            to_date = today
            self.current_date_filter = (from_date, to_date)
            self.date_range_widget.set_date_range(from_date, to_date)
            self.apply_filters()
        except Exception as e:
            _log.warning("Error applying this year filter: %s", e)
    
    def apply_all_time_filter(self):
        try:
            self.highlight_selected_quick_filter(self.all_time_btn)
            self.date_range_widget.hide_date_range()
            self.current_date_filter = None
            self.date_range_widget.is_date_range_applied = False
            self.date_range_widget.apply_clear_btn.setText("Apply")
            self.date_range_widget.apply_clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #229954; }
            """)
            
            if not self.invoices:
                # If no invoices, set a default range and return
                from_date = datetime(1970, 1, 1)
                to_date = datetime.now()
                self.current_date_filter = (from_date, to_date)
                self.date_range_widget.set_date_range(from_date, to_date)
                self.apply_filters()
                return
                
            dates = []
            for invoice, _ in self.invoices:
                try:
                    # Use the invoice object directly, not invoice.date string
                    invoice_date = self.parse_invoice_date(invoice)
                    if invoice_date and invoice_date != datetime.min:
                        dates.append(invoice_date)
                    else:
                        # Fallback: try parsing the date string directly
                        if hasattr(invoice, 'date') and invoice.date:
                            try:
                                parsed = datetime.strptime(invoice.date, "%m-%d-%Y")
                                dates.append(parsed)
                            except:
                                pass
                except Exception as e:
                    _log.warning("Error parsing date for invoice %s: %s", invoice.invoice_number, e)
                    continue
            
            if dates:
                from_date = min(dates)
                to_date = max(dates)
            else:
                from_date = datetime(1970, 1, 1)
                to_date = datetime.now()
                
            self.current_date_filter = (from_date, to_date)
            self.date_range_widget.set_date_range(from_date, to_date)
            self.apply_filters()
        except Exception as e:
            _log.warning("Error applying all time filter: %s", e)
        
    def display_invoices(self, invoices: List):
        """Display invoices in the table"""
        self.invoice_table.setSortingEnabled(False)
        try:
            self.invoice_table.clearContents()
            
            # Check if there are no invoices to display
            if not invoices or len(invoices) == 0:
                # Show "No invoices found" message instead of empty row
                self.invoice_table.setRowCount(1)
                self.invoice_table.setColumnCount(11)
                self.invoice_table.setHorizontalHeaderLabels([
                    "Date", "Invoice Number", "Project Name", "Total Price", "Tax", 
                    "Down Payment", "Total Due", "Due Date", "Status", "Received Date", "Actions"
                ])
                
                # Create a merged cell or just put a message in the first column
                no_data_item = QtWidgets.QTableWidgetItem("📭 No invoices found")
                no_data_item.setTextAlignment(QtCore.Qt.AlignCenter)
                
                # Span across all columns (optional - creates a nicer look)
                self.invoice_table.setSpan(0, 0, 1, 11)
                self.invoice_table.setItem(0, 0, no_data_item)
                
                # Style the empty state
                no_data_item.setForeground(QtGui.QColor(120, 120, 120))
                no_data_item.setFont(QtGui.QFont("Inter", 12))
                return
            
            # Normal case - we have invoices to display
            sorted_invoices = invoices
            self.invoice_table.setRowCount(len(sorted_invoices))
            self.invoice_table.setColumnCount(11)
            self.invoice_table.setHorizontalHeaderLabels([
                "Date", "Invoice Number", "Project Name", "Total Price", "Tax", 
                "Down Payment", "Total Due", "Due Date", "Status", "Received Date", "Actions"
            ])
            
            header = self.invoice_table.horizontalHeader()
            for i in range(self.invoice_table.columnCount()):
                header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)
            header.setMinimumSectionSize(96)
            header.setSectionResizeMode(8, QtWidgets.QHeaderView.Fixed)
            header.setSectionResizeMode(10, QtWidgets.QHeaderView.Fixed)
            self.invoice_table.setColumnWidth(8, 150)
            self.invoice_table.setColumnWidth(10, 160)
            
            # Populate rows with invoice data
            item_font = QtGui.QFont("Inter", 10)
            for row, (invoice, json_file) in enumerate(sorted_invoices):
                self.invoice_table.setRowHeight(row, 54)
                
                # Date
                date_item = QtWidgets.QTableWidgetItem(invoice.date)
                date_item.setFont(item_font)
                date_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 0, date_item)
                
                # Invoice Number
                invoice_item = QtWidgets.QTableWidgetItem(invoice.invoice_number)
                invoice_item.setFont(item_font)
                invoice_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 1, invoice_item)
                
                # Project Name
                project_name = self.get_project_name(invoice)
                project_item = QtWidgets.QTableWidgetItem(project_name)
                project_item.setFont(item_font)
                project_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 2, project_item)
                
                # Total price (subtotal)
                subtotal_item = QtWidgets.QTableWidgetItem(Currency.format(invoice.subtotal))
                subtotal_item.setFont(item_font)
                subtotal_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 3, subtotal_item)
                
                # Tax
                tax_item = QtWidgets.QTableWidgetItem(Currency.format(invoice.tax_amount))
                tax_item.setFont(item_font)
                tax_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 4, tax_item)
                
                # Down Payment
                total_down_payment = sum(item.down_payment for item in invoice.items)
                down_payment_item = QtWidgets.QTableWidgetItem(Currency.format(total_down_payment))
                down_payment_item.setFont(item_font)
                down_payment_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 5, down_payment_item)
                
                # Total Due
                total_item = QtWidgets.QTableWidgetItem(Currency.format(invoice.total))
                total_item.setFont(item_font)
                total_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 6, total_item)
                
                # Due Date
                due_date = getattr(invoice, 'due_date', 'N/A')
                if not due_date or due_date == '':
                    due_date = 'N/A'
                due_date_item = QtWidgets.QTableWidgetItem(due_date)
                due_date_item.setFont(item_font)
                due_date_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 7, due_date_item)
                
                # Status pill badge
                initial_status = self.get_invoice_status(invoice)
                inv_badge = self.create_invoice_status_badge(initial_status, invoice)
                self.invoice_table.setCellWidget(row, 8, inv_badge)
                
                # Received Date
                received_date = getattr(invoice, 'received_date', '')
                if not received_date or received_date == 'N/A':
                    received_date = "N/A"
                received_date_item = QtWidgets.QTableWidgetItem(received_date)
                received_date_item.setFont(item_font)
                received_date_item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setItem(row, 9, received_date_item)
                
                # Actions
                actions_widget = QtWidgets.QWidget()
                actions_layout = QtWidgets.QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(6, 4, 6, 4)
                actions_layout.setSpacing(8)
                
                open_pdf_btn = QtWidgets.QPushButton("PDF")
                open_pdf_btn.setFixedSize(58, 32)
                open_pdf_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #0f8bd6;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        padding: 0px;
                        font-size: 12px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #0b75b6; }
                """)
                open_pdf_btn.clicked.connect(lambda checked=False, inv=invoice: self.open_pdf(inv))
                
                more_btn = QtWidgets.QPushButton("⋮")
                more_btn.setText("More")
                more_btn.setFixedSize(66, 32)
                more_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #334155;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        padding: 0px;
                        font-size: 12px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #1f2937; }
                    QPushButton::menu-indicator { image: none; width: 0px; }
                """)
                
                more_menu = QtWidgets.QMenu(self)
                view_action   = QtWidgets.QAction("👁 View Details", self)
                email_action  = QtWidgets.QAction("📧 Send to Client", self)
                edit_action   = QtWidgets.QAction("✏️ Edit Invoice", self)
                delete_action = QtWidgets.QAction("🗑️ Delete Invoice", self)
                more_menu.addAction(view_action)
                more_menu.addAction(email_action)
                more_menu.addSeparator()
                more_menu.addAction(edit_action)
                more_menu.addSeparator()
                more_menu.addAction(delete_action)

                view_action.triggered.connect(lambda checked=False, inv=invoice: self.view_invoice_details(inv))
                email_action.triggered.connect(lambda checked=False, inv=invoice: self.send_invoice_email(inv))
                edit_action.triggered.connect(lambda checked=False, inv=invoice: self.edit_invoice(inv, json_file))
                delete_action.triggered.connect(lambda checked=False, inv=invoice, jf=json_file: self.delete_invoice(inv, jf))
                more_btn.setMenu(more_menu)
                
                actions_layout.addWidget(open_pdf_btn)
                actions_layout.addWidget(more_btn)
                actions_layout.setAlignment(QtCore.Qt.AlignCenter)
                self.invoice_table.setCellWidget(row, 10, actions_widget)
                
        except Exception as e:
            _log.warning("Error displaying invoices: %s", e)
            import traceback
            traceback.print_exc()
            
    
    def emit_balance_sheet_refresh(self, invoice_number=None):
        try:
            main_window = self.window()
            while main_window and not hasattr(main_window, 'balance_sheet_tab'):
                main_window = main_window.parent()
            if main_window and hasattr(main_window, 'balance_sheet_tab'):
                balance_tab = main_window.balance_sheet_tab
                if hasattr(balance_tab, 'refresh_invoice_revenues'):
                    balance_tab.refresh_invoice_revenues()
                else:
                    balance_tab.load_all_financial_data()
                    balance_tab.update_annual_summary()
                    balance_tab.on_category_changed(balance_tab.current_category)
                    balance_tab.update_stats_cards()
        except Exception as e:
            _log.warning("Error emitting balance sheet refresh: %s", e)
    
    def show_status_update_message(self, invoice_number: str, new_status: str):
        try:
            notification = QtWidgets.QLabel(self)
            notification.setText(f"✓ Invoice {invoice_number} marked as {new_status}")
            notification.setStyleSheet("""
                QLabel {
                    background-color: #27ae60;
                    color: white;
                    padding: 8px 15px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 12px;
                }
            """)
            notification.adjustSize()
            notification.move(self.width() - notification.width() - 20, 10)
            notification.show()
            QtCore.QTimer.singleShot(2000, notification.deleteLater)
        except:
            pass
    
    def on_status_changed_with_date(self, invoice: Invoice, new_status: str, combo: QtWidgets.QComboBox):
        """Handle status changes with received date handling - SUPPORTS ALL STATUS TYPES"""
        try:
            # Store old status for comparison
            old_status = getattr(invoice, 'status', 'Pending')
            
            # If no change, return immediately
            if new_status == old_status:
                return
            
            # Handle received date based on status
            if new_status == "Paid":
                # Only prompt for received date if changing TO Paid
                if old_status != "Paid":
                    dialog = ReceivedDateDialog(invoice, self)
                    if dialog.exec_() == QtWidgets.QDialog.Accepted:
                        received_date = _normalize_date(dialog.get_received_date())
                        invoice.received_date = received_date
                        self.update_received_date_in_table(invoice.invoice_number, received_date)
                    else:
                        # User cancelled, revert status
                        if combo is not None:
                            combo.blockSignals(True)
                            combo.setCurrentText(old_status)
                            combo.blockSignals(False)
                            self.style_status_combo(combo, old_status)
                        return
            else:
                # For any non-Paid status, set received_date to N/A
                invoice.received_date = "N/A"
                self.update_received_date_in_table(invoice.invoice_number, "N/A")

            # Update local cache immediately for instant UI response
            self.set_cached_status(invoice.invoice_number, new_status)

            # Style the combo box if provided (legacy path)
            if combo is not None:
                self.style_status_combo(combo, new_status)
            
            # Update the invoice object immediately
            invoice.status = new_status
            
            # Update local stats immediately
            self.update_stats_async()
            
            # Show success message instantly
            self.show_status_update_message(invoice.invoice_number, new_status)
            
            # ASYNC Firebase update - this will sync ALL statuses to balance sheet
            QtCore.QTimer.singleShot(10, lambda: self._async_update_firebase(invoice))
            
        except Exception as e:
            _log.warning("Error updating status: %s", e)
            import traceback
            traceback.print_exc()

    def _async_update_firebase(self, invoice: Invoice):
        """Background Firebase update - syncs ALL statuses to balance sheet"""
        try:
            # Update status in Firebase
            success = FirebaseManager.update_invoice_status(invoice.invoice_number, invoice.status)

            if success:
                # Update received date in Firebase
                if invoice.status == "Paid" and hasattr(invoice, 'received_date') and invoice.received_date:
                    self._update_received_date_async(invoice.invoice_number, invoice.received_date)
                else:
                    self._update_received_date_async(invoice.invoice_number, "N/A")

                # Sync to balance sheet for ANY status change (not just Paid)
                self._sync_to_balance_sheet_async(invoice)

                # If un-paid: remove any auto-recorded payments for this invoice
                if invoice.status != "Paid":
                    self._remove_auto_payments_for_invoice(invoice.invoice_number)

                # Auto-advance project stage THEN record payment, THEN refresh balance sheet
                if invoice.status == "Paid":
                    def _paid_chain(inv=invoice):
                        self._advance_then_record(inv)
                        self.emit_balance_sheet_refresh(inv.invoice_number)
                    QtCore.QTimer.singleShot(150, _paid_chain)
                else:
                    # Non-paid status change: just refresh balance sheet
                    QtCore.QTimer.singleShot(150, lambda: self.emit_balance_sheet_refresh(invoice.invoice_number))

        except Exception as e:
            _log.warning("Background Firebase update error: %s", e)

    def _advance_then_record(self, invoice: Invoice):
        """Advance project stages FIRST, then record payments — guaranteed order, no race condition."""
        self._advance_project_stages(invoice)
        self._record_invoice_payments(invoice)

    def _advance_project_stages(self, invoice: Invoice):
        """Advance each project in the invoice to the next payment stage after Paid."""
        try:
            raw = FirebaseManager.load_invoices() or []
            target = next(
                (inv for inv in raw
                 if (inv.get("meta") or {}).get("invoice_number") == invoice.invoice_number),
                None
            )
            if not target:
                return
            for item in target.get("items", []):
                pn = item.get("project_number", "").strip()
                if pn:
                    paid_stage = item.get("payment_category", "")
                    FirebaseManager.advance_project_payment_stage(pn, paid_stage)
                    _log.info("Auto-advanced payment stage for project %s (paid: %s)", pn, paid_stage)
        except Exception as e:
            _log.warning("Error advancing project stages: %s", e)

    def _record_invoice_payments(self, invoice: Invoice):
        """Auto-record a payment in the tracker for every project item when invoice is Paid."""
        try:
            from payment_tracker import get_payment_tracker
            tracker = get_payment_tracker()

            received_date = getattr(invoice, "received_date", "") or ""
            invoice_number = invoice.invoice_number

            raw = FirebaseManager.load_invoices() or []
            target = next(
                (inv for inv in raw
                 if (inv.get("meta") or {}).get("invoice_number") == invoice_number),
                None
            )
            if not target:
                return

            projects_in_invoice = []
            for item in target.get("items", []):
                pn = item.get("project_number", "").strip()
                if not pn:
                    continue
                projects_in_invoice.append(pn)

                # Determine the amount paid for this item/stage
                raw_amt = (
                    item.get("payment_due")
                    or item.get("total")
                    or item.get("unit_price")
                    or 0
                )
                try:
                    amount = float(str(raw_amt).replace("$", "").replace(",", "") or 0)
                except (ValueError, TypeError):
                    amount = 0.0
                if amount <= 0:
                    continue

                raw_stage = item.get("payment_category", "") or ""
                # Normalize stage to canonical name before comparing / storing
                payment_stage = _normalize_payment_stage(raw_stage)

                # Skip if already recorded for this invoice+stage OR if a manual
                # payment for the same stage and amount already exists (prevents
                # double-counting when "+ Payment" was used before the invoice was raised).
                existing = tracker.get_project_payments(pn)
                already_recorded = any(
                    p.invoice_number == invoice_number and
                    _normalize_payment_stage(p.payment_stage) == payment_stage
                    for p in existing
                )
                if not already_recorded:
                    # Also block if a manual payment (no invoice#) covers the same
                    # stage and amount — avoids duplicate when user paid before invoicing.
                    already_recorded = any(
                        not p.invoice_number and
                        _normalize_payment_stage(p.payment_stage) == payment_stage and
                        abs(float(p.amount) - amount) < 0.01
                        for p in existing
                    )
                if already_recorded:
                    _log.info("Payment already recorded for %s / %s — skipping", pn, invoice_number)
                    continue

                # Normalise date → always "MM-dd-YYYY"
                pay_date = _normalize_date(received_date)

                success = tracker.add_payment(
                    project_number=pn,
                    amount=amount,
                    payment_date=pay_date,
                    payment_method="Invoice",
                    notes=f"Auto-recorded from invoice {invoice_number}",
                    invoice_number=invoice_number,
                    payment_stage=payment_stage,
                    sync_balance_sheet=False,  # invoice already synced its own BS entry
                )
                if success:
                    _log.info(
                        "Auto-recorded payment $%.2f for project %s (invoice %s, stage: %s)",
                        amount, pn, invoice_number, payment_stage,
                    )

            # Check if any project is now fully paid → auto-set status to Paid
            self._auto_mark_fully_paid_projects(projects_in_invoice)

            # Refresh project list cell and all finance tabs
            self._refresh_project_payment_cells()

        except Exception as e:
            _log.warning("Error recording invoice payments: %s", e)

    def _auto_mark_fully_paid_projects(self, project_numbers: list):
        """Set status='Paid' for any project in the list that has reached 100% payment."""
        try:
            from payment_tracker import get_payment_tracker
            from project_number_generator import update_project_status_on_full_payment
            tracker = get_payment_tracker()
            raw_projects = FirebaseManager.load_projects() or []
            for pn in set(project_numbers):
                project = next((p for p in raw_projects
                                if p.get("project_number") == pn), None)
                if project:
                    total = float(project.get("project_amount", 0) or 0)
                    summary = tracker.get_payment_summary(pn, total)
                    if float(summary.get("payment_percentage", 0)) >= 100.0:
                        update_project_status_on_full_payment(pn, project)
        except Exception as e:
            _log.warning("Error auto-marking fully paid projects: %s", e)

    def _remove_auto_payments_for_invoice(self, invoice_number: str):
        """When an invoice is un-paid, delete the auto-recorded payments for it."""
        try:
            from payment_tracker import get_payment_tracker
            from balance_sheet_tab import BalanceSheetFirebaseManager
            tracker = get_payment_tracker()
            to_remove = [
                p for p in tracker.payments
                if p.invoice_number == invoice_number
                and p.payment_method == "Invoice"   # only auto-recorded ones
            ]
            for payment in to_remove:
                tracker.delete_payment(payment.payment_id)
                _log.info("Removed auto-payment %s for invoice %s (status reverted)",
                          payment.payment_id, invoice_number)
            if to_remove:
                self._refresh_project_payment_cells()
        except Exception as e:
            _log.warning("Error removing auto payments for invoice %s: %s", invoice_number, e)

    def _refresh_project_payment_cells(self):
        """Tell the project tab to refresh payment cells for all visible rows."""
        try:
            main_win = self.window()
            if not main_win:
                return
            project_tab = getattr(main_win, "project_tab", None)
            if project_tab and hasattr(project_tab, "filter_projects"):
                project_tab.filter_projects()
            for attr in ("balance_sheet_tab", "expenses_tab", "finance_overview_tab"):
                tab = getattr(main_win, attr, None)
                if tab and hasattr(tab, "refresh_data"):
                    try:
                        tab.refresh_data()
                    except Exception:
                        pass
        except Exception as e:
            _log.warning("Could not refresh project payment cells: %s", e)

    def _update_received_date_async(self, invoice_number: str, received_date: str):
        """Update received date in Firebase in background"""
        try:
            if not FIREBASE_AVAILABLE:
                return
            from firebase_admin import db
            invoices_ref = db.reference('/invoices')
            invoices_data = invoices_ref.get()
            if invoices_data:
                for invoice_id, invoice_data in invoices_data.items():
                    if invoice_data and 'meta' in invoice_data:
                        if invoice_data['meta'].get('invoice_number') == invoice_number:
                            invoice_ref = db.reference(f'/invoices/{invoice_id}')
                            invoice_ref.update({
                                'meta/received_date': received_date,
                                'meta/updated_at': datetime.now().isoformat()
                            })
                            return
        except Exception as e:
            _log.warning("Error updating received date: %s", e)

    def _sync_to_balance_sheet_async(self, invoice: Invoice):
        """Sync to balance sheet in background - NOW HANDLES ALL STATUS TYPES"""
        try:
            if not FIREBASE_AVAILABLE:
                return
            from firebase_admin import db
            revenue_ref = db.reference('revenue')
            all_revenue = revenue_ref.get()
            
            if not all_revenue:
                return
            
            for rev_id, revenue in all_revenue.items():
                if revenue and revenue.get('is_invoice') and revenue.get('invoice_number') == invoice.invoice_number:
                    updates = {}
                    
                    # Always sync status regardless of what it is
                    if invoice.status != revenue.get('status', 'Pending'):
                        updates['status'] = invoice.status
                    
                    # Always sync due date
                    if invoice.due_date != revenue.get('due_date', 'N/A'):
                        updates['due_date'] = invoice.due_date
                    
                    # Handle received_date based on status
                    if invoice.status == "Paid":
                        # For paid status, use the invoice's received_date
                        received_date = getattr(invoice, 'received_date', 'N/A')
                        if not received_date or received_date == '':
                            received_date = 'N/A'
                        updates['received_date'] = received_date
                        
                        # Update year based on received_date for paid invoices
                        if received_date != 'N/A':
                            try:
                                received_date_obj = datetime.strptime(received_date, "%m-%d-%Y")
                                updates['year'] = received_date_obj.year
                            except:
                                pass
                    else:
                        # For non-paid status, received_date should be N/A
                        updates['received_date'] = 'N/A'
                        # Keep year based on invoice date
                        try:
                            date_obj = datetime.strptime(invoice.date, "%m-%d-%Y")
                            updates['year'] = date_obj.year
                        except:
                            pass
                    
                    # Also sync the description/notes
                    project_names = []
                    for item in invoice.items:
                        if hasattr(item, 'project_name') and item.project_name:
                            project_names.append(item.project_name)
                        elif item.description:
                            project_names.append(item.description)
                    new_description = f"{invoice.client_name} - {', '.join(project_names[:2])}"
                    if len(project_names) > 2:
                        new_description += f" +{len(project_names)-2} more"
                    
                    if new_description != revenue.get('description', ''):
                        updates['description'] = new_description
                    
                    # Sync amount
                    new_amount = float(invoice.total)
                    old_amount = float(revenue.get('amount', 0))
                    if abs(new_amount - old_amount) > 0.01:
                        updates['amount'] = str(new_amount)
                    
                    # Apply all updates if any
                    if updates:
                        updates['updated_at'] = datetime.now().isoformat()
                        revenue_ref.child(rev_id).update(updates)
                        _log.info("Synced invoice %s to balance sheet with status: %s", invoice.invoice_number, invoice.status)
                    break
        except Exception as e:
            _log.warning("Error syncing to balance sheet: %s", e)
            

    def update_stats_async(self):
        """Update stats without blocking UI"""
        QtCore.QTimer.singleShot(10, lambda: self.update_stats(self.filtered_invoices))
        
    
    def update_received_date_in_table(self, invoice_number: str, received_date: str):
        for row in range(self.invoice_table.rowCount()):
            invoice_item = self.invoice_table.item(row, 1)
            if invoice_item and invoice_item.text() == invoice_number:
                # Create new item with proper alignment
                new_item = QtWidgets.QTableWidgetItem(received_date)
                new_item.setTextAlignment(QtCore.Qt.AlignCenter)  # Add this line
                self.invoice_table.setItem(row, 9, new_item)
                break
        
    def update_invoice_received_date_in_firebase(self, invoice_number: str, received_date: str):
        try:
            if not FIREBASE_AVAILABLE:
                return
            from firebase_admin import db
            invoices_ref = db.reference('/invoices')
            invoices_data = invoices_ref.get()
            if invoices_data:
                for invoice_id, invoice_data in invoices_data.items():
                    if invoice_data and 'meta' in invoice_data:
                        if invoice_data['meta'].get('invoice_number') == invoice_number:
                            invoice_ref = db.reference(f'/invoices/{invoice_id}')
                            invoice_ref.update({
                                'meta/received_date': received_date,
                                'meta/updated_at': datetime.now().isoformat()
                            })
                            revenue_ref = db.reference('revenue')
                            all_revenue = revenue_ref.get()
                            if all_revenue:
                                for rev_id, revenue in all_revenue.items():
                                    if revenue and revenue.get('is_invoice') and revenue.get('invoice_number') == invoice_number:
                                        try:
                                            received_date_obj = datetime.strptime(received_date, "%m-%d-%Y")
                                            revenue_ref.child(rev_id).update({
                                                'received_date': received_date,
                                                'year': received_date_obj.year,
                                                'updated_at': datetime.now().isoformat()
                                            })
                                        except:
                                            pass
                                        break
                            return
        except Exception as e:
            _log.warning("Error updating received date in Firebase: %s", e)
    
    def on_status_changed(self, invoice: Invoice, new_status: str, combo: QtWidgets.QComboBox):
        try:
            self.set_cached_status(invoice.invoice_number, new_status)
            self.style_status_combo(combo, new_status)
            invoice.status = new_status
            self.update_invoice_status_in_file(invoice.invoice_number, new_status)
            self.update_stats(self.filtered_invoices)
            if FIREBASE_AVAILABLE:
                success = FirebaseManager.update_invoice_status(invoice.invoice_number, new_status)
        except Exception as e:
            _log.warning("Error updating status: %s", e)
    
    INVOICE_STATUS_PALETTE = {
        "Paid":           ("#d1fae5", "#065f46", "#6ee7b7"),
        "Unpaid":         ("#fee2e2", "#991b1b", "#fca5a5"),
        "Pending":        ("#fef3c7", "#92400e", "#fcd34d"),
        "Overdue":        ("#fce7f3", "#9d174d", "#f9a8d4"),
        "Partially Paid": ("#dbeafe", "#1e40af", "#93c5fd"),
    }

    def create_invoice_status_badge(self, status: str, invoice) -> QtWidgets.QWidget:
        """Clickable pill badge for invoice status."""
        bg, fg, border = self.INVOICE_STATUS_PALETTE.get(
            status, ("#f9fafb", "#6b7280", "#e5e7eb"))

        container = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(container)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setAlignment(QtCore.Qt.AlignCenter)

        badge = QtWidgets.QPushButton(f"  {status}  ▾")
        badge.setFixedHeight(26)
        badge.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        badge.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 13px;
                font-size: 11px;
                font-weight: 700;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                padding: 0 10px;
            }}
            QPushButton:hover {{ border-width: 1.5px; }}
        """)

        def show_menu(checked=False, b=badge, inv=invoice):
            from PyQt5.QtWidgets import QMenu, QAction
            menu = QMenu(b)
            menu.setStyleSheet("""
                QMenu {
                    background:white; border:1px solid #d0d7de;
                    border-radius:8px; padding:4px 0;
                    font-family:'Inter','Segoe UI'; font-size:12px;
                }
                QMenu::item { padding:7px 20px; color:#24292f; }
                QMenu::item:selected { background:#f6f8fa; color:#0969da; }
            """)
            for s in ["Paid", "Unpaid", "Pending", "Overdue", "Partially Paid"]:
                a = QAction(s, menu)
                a.triggered.connect(
                    lambda _, st=s, bref=b, iref=inv:
                        self._apply_invoice_badge(st, bref, iref))
                menu.addAction(a)
            menu.exec_(b.mapToGlobal(QtCore.QPoint(0, b.height())))

        badge.clicked.connect(show_menu)
        lay.addWidget(badge)
        return container

    def _apply_invoice_badge(self, new_status: str,
                              badge_btn: QtWidgets.QPushButton, invoice):
        bg, fg, border = self.INVOICE_STATUS_PALETTE.get(
            new_status, ("#f9fafb", "#6b7280", "#e5e7eb"))
        badge_btn.setText(f"  {new_status}  ▾")
        badge_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg}; color: {fg};
                border: 1px solid {border}; border-radius: 13px;
                font-size: 11px; font-weight: 700;
                font-family: 'Inter', 'Segoe UI', sans-serif; padding: 0 10px;
            }}
            QPushButton:hover {{ border-width: 1.5px; }}
        """)
        self.on_status_changed_with_date(invoice, new_status, None)

    def style_status_combo(self, combo: QtWidgets.QComboBox, status: str):
        status_styles = {
            "Paid": """
                QComboBox {
                    background-color: #d4edda;
                    color: #155724;
                    border: 1px solid #c3e6cb;
                    border-radius: 4px;
                    padding: 4px;
                    font-weight: bold;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: white;
                    border: 1px solid #bdc3c7;
                    selection-background-color: #3498db;
                }
            """,
            "Unpaid": """
                QComboBox {
                    background-color: #f8d7da;
                    color: #white;
                    border: 1px solid #f5c6cb;
                    border-radius: 4px;
                    padding: 4px;
                    font-weight: bold;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: white;
                    border: 1px solid #bdc3c7;
                    selection-background-color: #3498db;
                }
            """,
            "Pending": """
                QComboBox {
                    background-color: #fff3cd;
                    color: #856404;
                    border: 1px solid #ffeaa7;
                    border-radius: 4px;
                    padding: 4px;
                    font-weight: bold;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: white;
                    border: 1px solid #bdc3c7;
                    selection-background-color: #3498db;
                }
            """,
            "Overdue": """
                QComboBox {
                    background-color: #ffe5d9;  /* Soft orange */
                    color: #a13700;             /* Burnt orange text */
                    border: 1px solid #ffb599;
                    border-radius: 4px;
                    padding: 4px;
                    font-weight: bold;
                }
                QComboBox::drop-down { border: none; width: 20px; }
                QComboBox::down-arrow { image: none; border: none; }
                QComboBox QAbstractItemView {
                    background-color: white;
                    border: 1px solid #bdc3c7;
                    selection-background-color: #ff7043; /* Highlight */
                }
            """,
            "Partially Paid": """
                QComboBox {
                    background-color: #ede7f6;  /* Light lavender */
                    color: #4a148c;             /* Deep purple text */
                    border: 1px solid #d1c4e9;
                    border-radius: 4px;
                    padding: 4px;
                    font-weight: bold;
                }
                QComboBox::drop-down { border: none; width: 20px; }
                QComboBox::down-arrow { image: none; border: none; }
                QComboBox QAbstractItemView {
                    background-color: white;
                    border: 1px solid #bdc3c7;
                    selection-background-color: #9575cd;
                }
                QComboBox::drop-down { border: none; width: 20px; }
                QComboBox::down-arrow { image: none; border: none; }
            """
        }
        combo.setStyleSheet(status_styles.get(status, status_styles["Pending"]))
    
    def update_stats(self, invoices=None):
        """Update statistics - OPTIMIZED for speed"""
        try:
            # Only update if there are actual changes
            if invoices is None:
                invoices = self.invoices
            
            # Calculate quickly without UI blocking
            total_invoices = len(invoices)
            total_amount = 0
            total_paid_amount = 0
            
            for invoice, _ in invoices:
                total_amount += invoice.total
                if self.get_invoice_status(invoice) == "Paid":
                    total_paid_amount += invoice.total
            
            # Update UI labels directly without recreating widgets if possible
            if hasattr(self, 'stats_labels'):
                # Update existing labels
                self.stats_labels['total_invoices'].setText(str(total_invoices))
                self.stats_labels['total_paid'].setText(Currency.format(total_paid_amount))
                self.stats_labels['total_revenue'].setText(Currency.format(total_amount))
            else:
                # First time - create stats widgets
                self.stats_labels = {}
                def clear_layout(layout):
                    while layout.count():
                        item = layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                        elif item.layout():
                            clear_layout(item.layout())
                clear_layout(self.stats_layout)
                
                stats_container = QtWidgets.QWidget()
                stats_container_layout = QtWidgets.QHBoxLayout(stats_container)
                stats_container_layout.setContentsMargins(0, 0, 0, 0)
                stats_container_layout.setSpacing(15)
                
                stats_data = [
                    ("Total Invoices", str(total_invoices), "#0f8bd6", 'total_invoices'),
                    ("Total Amount Paid", Currency.format(total_paid_amount), "#d97706", 'total_paid'),
                    ("Total Revenue", Currency.format(total_amount), "#16a34a", 'total_revenue'),
                ]
                
                for label, value, color, key in stats_data:
                    box, value_label = self.create_stat_box(label, value, color)
                    stats_container_layout.addWidget(box)
                    self.stats_labels[key] = value_label  # 👈 correct reference
    
                stats_container_layout.insertStretch(0)
                stats_container_layout.addStretch()
                self.stats_layout.addWidget(stats_container)
                
        except Exception as e:
            _log.warning("Error updating stats: %s", e)
                
    def verify_firebase_connection(self):
        if not FIREBASE_AVAILABLE:
            return
        try:
            from firebase_admin import db
            test_ref = db.reference('/test_connection')
            test_ref.set({'test_time': datetime.now().isoformat()})
        except Exception as e:
            _log.warning("Firebase verification failed: %s", e)
    
    def create_stat_box(self, label: str, value: str, color: str):
        widget = QtWidgets.QFrame()
        widget.setMinimumSize(170, 78)
        widget.setStyleSheet(f"""
            QFrame {{
                background: #f8fbfd;
                border: 1px solid #d8e2ec;
                border-left: 4px solid {color};
                border-radius: 8px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
            }}
        """)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        
        value_label = QtWidgets.QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                font-size: 19px;
                font-weight: 900;
                color: {color};
            }}
        """)
        value_label.setAlignment(QtCore.Qt.AlignCenter)

        desc_label = QtWidgets.QLabel(label)
        desc_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #64748b;
                font-weight: 800;
            }
        """)
        desc_label.setAlignment(QtCore.Qt.AlignCenter)

        layout.addWidget(value_label)
        layout.addWidget(desc_label)

        return widget, value_label   # 👈 return value_label directly

    def send_invoice_email(self, invoice: Invoice):
        """Email the invoice PDF to the client using configured SMTP settings."""
        try:
            from email_manager import EmailManager
        except ImportError:
            QtWidgets.QMessageBox.critical(self, "Error", "email_manager module not found.")
            return

        if not EmailManager.is_configured():
            QtWidgets.QMessageBox.warning(
                self, "Email Not Configured",
                "SMTP settings are not set up.\n\n"
                "Go to Settings → Email and fill in your SMTP host, username, and password."
            )
            return

        client_email = getattr(invoice, "client_email", "") or ""
        if not client_email.strip():
            QtWidgets.QMessageBox.warning(
                self, "No Client Email",
                f"Invoice {invoice.invoice_number} has no client email address.\n"
                "Edit the invoice to add one before sending."
            )
            return

        confirm = QtWidgets.QMessageBox.question(
            self, "Send Invoice",
            f"Send invoice {invoice.invoice_number} to {client_email}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        # Locate the PDF — prefer local file, fall back to regenerating
        pdf_path = Config.INVOICES_DIR / f"{invoice.invoice_number}.pdf"
        if not pdf_path.exists():
            QtWidgets.QMessageBox.warning(
                self, "PDF Not Found",
                f"Could not find PDF for {invoice.invoice_number}.\n"
                "Please open the invoice and regenerate the PDF first."
            )
            return

        ok = EmailManager.send_invoice(invoice, pdf_path)
        if ok:
            QtWidgets.QMessageBox.information(
                self, "Sent",
                f"Invoice {invoice.invoice_number} sent to {client_email}."
            )
        else:
            QtWidgets.QMessageBox.critical(
                self, "Send Failed",
                "Email could not be delivered. Check your SMTP settings and try again.\n"
                "See logs/pims.log for details."
            )

    def open_pdf(self, invoice: Invoice):
        try:
            current_status = self.get_invoice_status(invoice)
            if FIREBASE_AVAILABLE and hasattr(FirebaseManager, 'load_pdf_from_firebase'):
                loading_msg = QtWidgets.QMessageBox(self)
                loading_msg.setWindowTitle("Loading PDF")
                loading_msg.setText("📥 Downloading PDF from cloud...")
                loading_msg.setStandardButtons(QtWidgets.QMessageBox.Cancel)
                loading_msg.show()
                QtCore.QTimer.singleShot(100, lambda: self.download_and_open_pdf_with_watermark(invoice, current_status, loading_msg))
            else:
                QtWidgets.QMessageBox.warning(self, "PDF Open", "Firebase not available. Cannot open PDF.")
        except Exception as e:
            _log.warning("Error opening PDF: %s", e)
    
    def download_and_open_pdf_with_watermark(self, invoice: Invoice, status: str, loading_msg: QtWidgets.QMessageBox):
        try:
            temp_dir = Path(tempfile.gettempdir()) / "mabs_invoices_temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            original_pdf_path = temp_dir / f"{invoice.invoice_number}_original.pdf"
            pdf_path = FirebaseManager.load_pdf_from_firebase(invoice.invoice_number, original_pdf_path)
            loading_msg.close()
            if pdf_path and pdf_path.exists():
                watermarked_pdf_path = PDFWatermarker.add_watermark_simple(pdf_path, status)
                if watermarked_pdf_path.exists():
                    if FileManager.open_file(watermarked_pdf_path):
                        QtWidgets.QMessageBox.information(self, "PDF Open", f"✅ PDF opened successfully!\n\nInvoice: {invoice.invoice_number}\nStatus: {status}")
                        QtCore.QTimer.singleShot(10000, lambda: self.cleanup_temp_files([pdf_path, watermarked_pdf_path]))
                    else:
                        QtWidgets.QMessageBox.critical(self, "PDF Open", "Failed to open watermarked PDF file.")
                else:
                    if FileManager.open_file(pdf_path):
                        QtWidgets.QMessageBox.information(self, "PDF Open", f"✅ PDF opened (original version)\n\nInvoice: {invoice.invoice_number}\nStatus: {status}")
                        QtCore.QTimer.singleShot(10000, lambda: self.cleanup_temp_file(pdf_path))
                    else:
                        QtWidgets.QMessageBox.critical(self, "PDF Open", "Failed to open PDF file.")
            else:
                QtWidgets.QMessageBox.warning(self, "PDF Not Found", f"PDF not found in Firebase:\n{invoice.invoice_number}")
        except Exception as e:
            loading_msg.close()
            QtWidgets.QMessageBox.critical(self, "PDF Open Error", f"Error opening PDF: {str(e)}")
    
    def cleanup_temp_files(self, file_paths: List[Path]):
        for file_path in file_paths:
            self.cleanup_temp_file(file_path)
    
    def cleanup_temp_file(self, file_path: Path):
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            _log.info("Could not clean up temporary PDF: %s", e)
    
    def view_invoice_details(self, invoice: Invoice):
        try:
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle(f"Invoice Details - {invoice.invoice_number}")
            dialog.setFixedSize(700, 500)
            layout = QtWidgets.QVBoxLayout(dialog)
            details_text = QtWidgets.QTextEdit()
            details_text.setReadOnly(True)
            total_amount = sum(item.total for item in invoice.items)
            total_down_payment = sum(item.down_payment for item in invoice.items)
            payment_due_before_tax = sum(item.payment_due for item in invoice.items)
            project_names = []
            for item in invoice.items:
                project_number = item.project_number
                if project_number and project_number in self.projects_data:
                    project_name = self.projects_data[project_number]
                    if project_name and project_name not in project_names:
                        project_names.append(project_name)
            project_info = ", ".join(project_names) if project_names else "No Project Info"
            current_status = self.get_invoice_status(invoice)
            
            details_html = f"""
            <h2>Invoice Details</h2>
            <table border="0" cellspacing="5" cellpadding="5">
            <tr><td><b>Invoice Number:</b></td><td>{invoice.invoice_number}</td></tr>
            <tr><td><b>Date:</b></td><td>{invoice.date}</td></tr>
            <tr><td><b>Due Date:</b></td><td>{invoice.due_date}</td></tr>
            <tr><td><b>Client:</b></td><td>{invoice.client_name}</td></tr>
            <tr><td><b>Project(s):</b></td><td>{project_info}</td></tr>
            <tr><td><b>Status:</b></td><td><span style='color: {'#155724' if current_status == 'Paid' else '#721c24' if current_status == 'Overdue' else '#856404'}; font-weight: bold;'>{current_status}</span></td></tr>
            <tr><td><b>Subtotal:</b></td><td>{Currency.format(total_amount)}</td></tr>
            <tr><td><b>Deposit Received:</b></td><td>{Currency.format(total_down_payment)}</td></tr>
            <tr><td><b>Payment Due (before tax):</b></td><td>{Currency.format(payment_due_before_tax)}</td></tr>
            <tr><td><b>Tax ({invoice.tax_rate}% on total):</b></td><td>{Currency.format(invoice.tax_amount)}</td></tr>
            <tr><td><b>Total Amount Due:</b></td><td>{Currency.format(invoice.total)}</td></tr>
            </table>
                    
            <h3>Items</h3>
            <table border="1" cellspacing="0" cellpadding="5" style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #3498db; color: white;">
                <th>Project #</th>
                <th>Description</th>
                <th>Plant</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Down Payment</th>
                <th>Payment Due</th>
                <th>Total</th>
            </tr>
            """
            for item in invoice.items:
                item_project_name = self.projects_data.get(item.project_number, "No Project Info")
                details_html += f"""
                <tr>
                    <td>{item.project_number}</td>
                    <td>{item.description}<br><small><i>Project: {item_project_name}</i></small></td>
                    <td>{item.plant}</td>
                    <td>{item.quantity}</td>
                    <td>{Currency.format(item.unit_price)}</td>
                    <td>{Currency.format(item.down_payment)}</td>
                    <td>{Currency.format(item.payment_due)}</td>
                    <td>{Currency.format(item.total)}</td>
                </tr>
                """
            details_html += "</table>"
            if invoice.notes and invoice.notes.strip():
                details_html += f"<h3>Notes</h3><p>{invoice.notes}</p>"
            details_text.setHtml(details_html)
            layout.addWidget(details_text)
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            dialog.exec_()
        except Exception as e:
            _log.warning("Error viewing invoice details: %s", e)
            QtWidgets.QMessageBox.critical(self, "Error", f"Error viewing invoice details: {e}")

    def edit_invoice(self, invoice, json_file):
        """Navigate to Invoice Management tab and load the invoice for editing."""
        try:
            # Walk up the widget tree to find MainWindow
            main_window = None
            widget = self
            while widget is not None:
                if hasattr(widget, '_nav_to') and hasattr(widget, 'add_item_row'):
                    main_window = widget
                    break
                widget = widget.parent()

            if main_window is None:
                # Fallback: find via QApplication
                for w in QtWidgets.QApplication.topLevelWidgets():
                    if hasattr(w, '_nav_to') and hasattr(w, 'add_item_row'):
                        main_window = w
                        break

            if main_window is None:
                QtWidgets.QMessageBox.warning(self, "Edit Invoice",
                    "Cannot reach Invoice Management tab. Please use the Edit dialog instead.")
                dialog = EditInvoiceDialog(invoice, self)
                dialog.exec_()
                return

            # Navigate to Projects & Invoice → Invoice Management
            main_window._nav_to(2)
            if hasattr(main_window, 'project_invoice_inner_tabs'):
                main_window.project_invoice_inner_tabs.setCurrentIndex(1)

            # Clear current form
            main_window.clear_all_items()
            main_window.clear_client_information()

            # --- Populate client ---
            for combo in ('client_combo', 'line_items_client_combo'):
                if hasattr(main_window, combo):
                    c = getattr(main_window, combo)
                    c.blockSignals(True)
                    idx = c.findText(invoice.client_name)
                    if idx >= 0:
                        c.setCurrentIndex(idx)
                    else:
                        c.setEditText(invoice.client_name)
                    c.blockSignals(False)

            if hasattr(main_window, 'client_email_edit'):
                main_window.client_email_edit.setText(invoice.client_email)
            if hasattr(main_window, 'client_address_edit'):
                main_window.client_address_edit.setPlainText(invoice.client_address)
            main_window.update_invoice_client_summary(
                invoice.client_name, invoice.client_email, invoice.client_address)

            # --- Populate dates ---
            try:
                from PyQt5.QtCore import QDate
                inv_date = QDate.fromString(invoice.date, "MM-dd-yyyy")
                due_date = QDate.fromString(invoice.due_date, "MM-dd-yyyy")
                if inv_date.isValid():
                    main_window.date_edit.setDate(inv_date)
                if due_date.isValid():
                    main_window.due_date_edit.setDate(due_date)
            except Exception:
                pass

            # --- Preserve existing invoice number so save = update ---
            main_window.invoice.invoice_number = invoice.invoice_number
            main_window.invoice_no_edit.setText(invoice.invoice_number)

            # --- Tax rate ---
            if hasattr(main_window, 'tax_spin'):
                main_window.tax_spin.setValue(float(invoice.tax_rate))

            # --- Notes ---
            if hasattr(main_window, 'notes_edit'):
                main_window.notes_edit.setPlainText(invoice.notes or "")

            # --- Line items ---
            from main import InvoiceItem as MainInvoiceItem
            for item in invoice.items:
                inv_item = MainInvoiceItem(
                    project_number=item.project_number,
                    description=item.description,
                    plant=item.plant,
                    quantity=item.quantity,
                    unit_price=float(item.unit_price),
                    down_payment=float(item.down_payment),
                    payment_category=item.payment_category,
                )
                main_window.add_item_row(inv_item)

            main_window.update_totals()

            # Close the history window
            history_win = self.window()
            if history_win and history_win is not main_window:
                history_win.close()

            if hasattr(main_window, 'statusBar'):
                main_window.statusBar().showMessage(
                    f"Editing invoice {invoice.invoice_number} — modify and click Generate PDF or Save Invoice.", 8000)

        except Exception as e:
            _log.warning("Error opening invoice for editing: %s", e)
            QtWidgets.QMessageBox.critical(self, "Error", f"Error loading invoice for edit: {str(e)}")

    def update_invoice_in_firebase(self, invoice):
        try:
            if FIREBASE_AVAILABLE:
                invoice_dict = invoice.to_dict()
                invoice_dict['meta'] = {
                    'invoice_number': invoice.invoice_number,
                    'client_name': invoice.client_name,
                    'client_email': invoice.client_email,
                    'client_address': invoice.client_address,
                    'date': invoice.date,
                    'due_date': invoice.due_date,
                    'status': invoice.status if hasattr(invoice, 'status') else 'Pending',
                    'received_date': getattr(invoice, 'received_date', 'N/A'),
                    'tax_rate': float(invoice.tax_rate),
                    'notes': invoice.notes,
                    'updated_at': datetime.now().isoformat()
                }
                if hasattr(invoice, 'firebase_timestamp') and invoice.firebase_timestamp:
                    invoice_dict['meta']['created_at'] = invoice.firebase_timestamp
                return FirebaseManager.update_invoice(invoice.invoice_number, invoice_dict)
            else:
                return False
        except Exception as e:
            _log.warning("Error updating invoice in Firebase: %s", e)
            return False

    def delete_invoice(self, invoice, json_file):
        try:
            reply = QtWidgets.QMessageBox.question(
                self, "Confirm Delete",
                f"Are you sure you want to delete this invoice?\n\n"
                f"Invoice Number: {invoice.invoice_number}\n"
                f"Client: {invoice.client_name}\n"
                f"Date: {invoice.date}\n"
                f"Total: {Currency.format(invoice.total)}\n\n"
                f"This action cannot be undone!",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                search_text = self.date_range_widget.search_bar.text()
                success = False
                if FIREBASE_AVAILABLE:
                    success = FirebaseManager.delete_invoice(invoice.invoice_number)
                else:
                    if json_file and json_file.exists():
                        json_file.unlink()
                        success = True
                if success:
                    self.invoices = [(inv, file) for inv, file in self.invoices if inv.invoice_number != invoice.invoice_number]
                    self.filtered_invoices = [(inv, file) for inv, file in self.filtered_invoices if inv.invoice_number != invoice.invoice_number]
                    self.date_range_widget.search_bar.setText(search_text)
                    self.display_invoices(self.filtered_invoices)
                    self.update_stats(self.filtered_invoices)
                    QtWidgets.QMessageBox.information(self, "Success", f"Invoice {invoice.invoice_number} deleted successfully!")
                else:
                    QtWidgets.QMessageBox.critical(self, "Error", "Failed to delete invoice.")
        except Exception as e:
            _log.warning("Error deleting invoice: %s", e)
            QtWidgets.QMessageBox.critical(self, "Error", f"Error deleting invoice: {str(e)}")


class EditInvoiceDialog(QtWidgets.QDialog):
    """Dialog for editing existing invoices - FULLY EDITABLE ALL FIELDS"""
    
    def __init__(self, invoice, parent=None):
        super().__init__(parent)
        import copy
        self.invoice = invoice
        self.original_invoice = copy.deepcopy(self.invoice)
        self.item_rows = []
        self.setWindowTitle(f"Edit Invoice - {invoice.invoice_number}")
        self.setModal(True)
        self.resize(1200, 800)
        self.setStyleSheet("""
            QDialog {
                background: #f5f6fa;
            }
        """)
        self.init_ui()
        self.populate_form()
        self.setup_shortcuts()
    
    def is_invoice_changed(self):
        return self.invoice.to_dict() != self.original_invoice.to_dict()

    def setup_shortcuts(self):
        self.save_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.save_changes)
        self.installEventFilter(self)
    
    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Return:
            focus_widgets = self.findChildren(QtWidgets.QWidget)
            focusable_widgets = [w for w in focus_widgets if w.focusPolicy() != QtCore.Qt.NoFocus]
            for i, widget in enumerate(focusable_widgets):
                if widget == self.focusWidget():
                    next_index = (i + 1) % len(focusable_widgets)
                    focusable_widgets[next_index].setFocus()
                    if isinstance(focusable_widgets[next_index], (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QComboBox)):
                        if hasattr(focusable_widgets[next_index], 'showPopup'):
                            focusable_widgets[next_index].showPopup()
                        else:
                            focusable_widgets[next_index].selectAll()
                    return True
        return super().eventFilter(source, event)
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QFrame()
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2c3e50, stop:1 #3498db);
                color: white;
                padding: 15px 24px;
            }
        """)
        header_layout = QtWidgets.QVBoxLayout(header)
        
        title = QtWidgets.QLabel(f"Edit Invoice: {self.invoice.invoice_number}")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: white;")
        
        header_layout.addWidget(title)
        layout.addWidget(header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QVBoxLayout(scroll_widget)
        form_layout.setContentsMargins(30, 30, 30, 30)
        form_layout.setSpacing(20)
        
        self.add_section_title(form_layout, "📝 Invoice Information")

        self.invoice_number_edit = self.create_styled_line_edit("")
        self.invoice_number_edit.setReadOnly(True)
        self.invoice_number_edit.setStyleSheet("""
            QLineEdit {
                background-color: #e9ecef;
                color: #495057;
            }
        """)
        self.add_field(form_layout, "Invoice Number:", self.invoice_number_edit)

        self.date_edit = self.create_fixed_date_edit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM-dd-yyyy")
        self.date_edit.setStyleSheet(self.get_date_style())
        self.add_field(form_layout, "Date:", self.date_edit)
        
        self.due_date_edit = self.create_fixed_date_edit()       
        self.due_date_edit.setCalendarPopup(True)
        self.due_date_edit.setDisplayFormat("MM-dd-yyyy")
        self.due_date_edit.setStyleSheet(self.get_date_style())
        self.add_field(form_layout, "Due Date:", self.due_date_edit)
        
        self.tax_rate_edit = QtWidgets.QDoubleSpinBox()
        self.tax_rate_edit.valueChanged.connect(self.update_totals)
        self.tax_rate_edit.setRange(0, 100)
        self.tax_rate_edit.setDecimals(2)
        self.tax_rate_edit.setSuffix(" %")
        self.tax_rate_edit.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)


        # 🔥 Disable scroll
        self.tax_rate_edit.wheelEvent = lambda event: None
        self.add_field(form_layout, "Tax Rate (%):", self.tax_rate_edit)
        
        self.status_combo = QtWidgets.QComboBox()
        self.status_combo.addItems(["Unpaid", "Paid", "Pending", "Overdue", "Partially Paid"])
        self.status_combo.setStyleSheet("""
            QComboBox {
                padding: 8px 12px;
                border: 1px solid #bdc3c7;
                border-radius: 6px;
                background: white;
                font-size: 13px;
            }
            QComboBox:focus { border-color: #3498db; }
        """)
        self.add_field(form_layout, "Status:", self.status_combo)
        
        self.received_date_edit = self.create_fixed_date_edit()
        self.received_date_edit.setCalendarPopup(True)
        self.received_date_edit.setDisplayFormat("MM-dd-yyyy")
        self.received_date_edit.setStyleSheet(self.get_date_style())
        self.received_date_edit.setEnabled(False)
        self.add_field(form_layout, "Received Date:", self.received_date_edit)
        
        self.status_combo.currentTextChanged.connect(self.on_status_changed)
        
        self.add_section_title(form_layout, "📦 Invoice Items")
        
        header_frame = QtWidgets.QFrame()
        header_layout_inner = QtWidgets.QHBoxLayout(header_frame)
        header_layout_inner.setContentsMargins(5, 4, 5, 4)
        header_layout_inner.setSpacing(8)
        header_layout_inner.setAlignment(QtCore.Qt.AlignLeft)

        headers = ["Project Number", "Description", "Plant", "Quantity", "Unit Price", "Payment Category", "Payment Due", "Total", ""]
        widths = [140, 140, 180, 70, 120, 180, 100, 80, 40]

        for header, width in zip(headers, widths):
            label = QtWidgets.QLabel(header)
            label.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 12px;")
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setMinimumWidth(width)
            label.setMaximumWidth(width)
            label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            header_layout_inner.addWidget(label)
        
        items_scroll = QtWidgets.QScrollArea()
        items_scroll.setWidgetResizable(True)
        items_scroll.setMinimumHeight(250)
        items_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #bdc3c7;
                border-radius: 6px;
                background-color: white;
            }
        """)
        
        self.items_widget = QtWidgets.QWidget()
        self.items_layout = QtWidgets.QVBoxLayout(self.items_widget)
        self.items_layout.setSpacing(4)
        self.items_layout.setContentsMargins(5, 5, 5, 5)
        self.items_layout.addWidget(header_frame)
        items_scroll.setWidget(self.items_widget)
        
        form_layout.addWidget(items_scroll)
        
        totals_group = QtWidgets.QGroupBox("Invoice Totals")
        totals_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #bdc3c7;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        totals_layout = QtWidgets.QFormLayout(totals_group)
        
        self.total_label = QtWidgets.QLabel("$0.00")
        self.down_payments_label = QtWidgets.QLabel("$0.00")
        self.tax_label = QtWidgets.QLabel("$0.00")
        self.total_amount_due_label = QtWidgets.QLabel("$0.00")
        
        self.total_amount_due_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                background-color: #e8f4fd;
                border: 2px solid #3498db;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        
        totals_layout.addRow("Total:", self.total_label)
        totals_layout.addRow("Deposit Received:", self.down_payments_label)
        totals_layout.addRow("Tax Amount:", self.tax_label)
        totals_layout.addRow("Total Amount Due:", self.total_amount_due_label)
        
        form_layout.addWidget(totals_group)
        
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(20)
        
        self.save_btn = QtWidgets.QPushButton("💾 Save Changes")
        self.save_btn.setMinimumHeight(48)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 8px;
                padding: 10px 30px;
            }
            QPushButton:hover { background: #2ecc71; }
        """)
        self.save_btn.clicked.connect(self.save_changes)
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(48)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #95a5a6;
                color: white;
                font-weight: bold;
                border-radius: 8px;
                padding: 10px 30px;
            }
            QPushButton:hover { background: #7f8c8d; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        
        form_layout.addLayout(btn_layout)
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
    
    def on_status_changed(self, status):
        is_paid = (status == "Paid")
        self.received_date_edit.setEnabled(is_paid)
    
    def get_date_style(self):
        return """
            QDateEdit {
                padding: 10px 12px;
                border: 1px solid #bdc3c7;
                border-radius: 6px;
                background: white;
                font-size: 13px;
            }
            QDateEdit:focus { border-color: #3498db; }
        """
    
    def create_fixed_date_edit(self, date=None):
        d = QtWidgets.QDateEdit(date if date else QtCore.QDate.currentDate())
        d.setCalendarPopup(True)
        d.setDisplayFormat("MM-dd-yyyy")
        d.wheelEvent = lambda event: None
        def keyPressEvent(event, original=d.keyPressEvent):
            if event.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
                return
            original(event)
        d.keyPressEvent = keyPressEvent
        d.stepBy = lambda x: None
        d.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        d.setStyleSheet(self.get_date_style())
        return d

    
    def add_section_title(self, layout, text):
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #2c3e50;
                border-bottom: 2px solid #dfe6e9;
                padding-bottom: 6px;
                margin-top: 10px;
            }
        """)
        layout.addWidget(label)
    
    def add_field(self, layout, label_text, widget):
        field_layout = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(label_text)
        label.setStyleSheet("font-weight: 500; color: #2c3e50; min-width: 120px;")
        field_layout.addWidget(label)
        field_layout.addWidget(widget, 1)
        layout.addLayout(field_layout)
    
    def create_styled_line_edit(self, placeholder=""):
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet("""
            QLineEdit {
                padding: 10px 12px;
                border: 1px solid #bdc3c7;
                border-radius: 6px;
                background: white;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #3498db; }
        """)
        return edit
    
    def add_item_row(self, item=None):
        row = EditItemRowWidget(item)
        row.removed.connect(lambda: self.remove_item_row(row))
        row.valueChanged.connect(self.update_totals)
        self.items_layout.addWidget(row)
        self.item_rows.append(row)
        self.update_totals()
    
    def remove_item_row(self, row):
        if row in self.item_rows:
            self.item_rows.remove(row)
            row.setParent(None)
            self.update_totals()
    
    def clear_all_items(self):
        for row in self.item_rows[:]:
            self.remove_item_row(row)
    
    def update_totals(self):
        try:
            total_amount = Decimal('0.0')
            total_down_payments = Decimal('0.0')
            for row in self.item_rows:
                item = row.get_item()
                total_amount += item.total
                total_down_payments += item.down_payment
            total_payment_due = total_amount - total_down_payments
            tax_rate = Decimal(str(self.tax_rate_edit.value()))
            tax_amount = total_amount * (tax_rate / Decimal("100"))
            total_amount_due = total_payment_due + tax_amount
            self.total_label.setText(Currency.format(total_amount))
            self.down_payments_label.setText(Currency.format(total_down_payments))
            self.tax_label.setText(Currency.format(tax_amount))
            self.total_amount_due_label.setText(Currency.format(total_amount_due))
        except Exception as e:
            _log.warning("Error updating totals: %s", e)
    
    def populate_form(self):
        self.invoice_number_edit.setText(self.invoice.invoice_number)
        try:
            date = QtCore.QDate.fromString(self.invoice.date, "MM-dd-yyyy")
            if date.isValid():
                self.date_edit.setDate(date)
        except Exception as e:
            self.date_edit.setDate(QtCore.QDate.currentDate())
        try:
            due_date = QtCore.QDate.fromString(self.invoice.due_date, "MM-dd-yyyy")
            if due_date.isValid():
                self.due_date_edit.setDate(due_date)
        except Exception as e:
            self.due_date_edit.setDate(QtCore.QDate.currentDate().addDays(30))
        self.tax_rate_edit.setValue(float(self.invoice.tax_rate))
        status = getattr(self.invoice, 'status', 'Pending')
        index = self.status_combo.findText(status)
        if index >= 0:
            self.status_combo.setCurrentIndex(index)
        received_date = getattr(self.invoice, 'received_date', 'N/A')
        if received_date and received_date != 'N/A':
            try:
                rec_date = QtCore.QDate.fromString(received_date, "MM-dd-yyyy")
                if rec_date.isValid():
                    self.received_date_edit.setDate(rec_date)
            except:
                pass
        self.clear_all_items()
        for i, item in enumerate(self.invoice.items):
            self.add_item_row(item)
        self.update_totals()
    
    def update_invoice_in_firebase(self, invoice):
        try:
            if not FIREBASE_AVAILABLE:
                return False
            invoice_dict = invoice.to_dict()
            project_names = []
            for item in invoice.items:
                if hasattr(item, 'project_name') and item.project_name:
                    project_names.append(item.project_name)
                elif item.description:
                    project_names.append(item.description)
            description = f"{invoice.client_name} - {', '.join(project_names[:2])}"
            if len(project_names) > 2:
                description += f" +{len(project_names)-2} more"
            invoice_dict['meta'] = {
                'invoice_number': invoice.invoice_number,
                'client_name': invoice.client_name,
                'client_email': invoice.client_email,
                'client_address': invoice.client_address,
                'date': invoice.date,
                'due_date': invoice.due_date,
                'status': invoice.status if hasattr(invoice, 'status') else 'Pending',
                'received_date': getattr(invoice, 'received_date', 'N/A'),
                'tax_rate': float(invoice.tax_rate),
                'notes': invoice.notes,
                'description': description,
                'updated_at': datetime.now().isoformat()
            }
            if hasattr(invoice, 'firebase_timestamp') and invoice.firebase_timestamp:
                invoice_dict['meta']['created_at'] = invoice.firebase_timestamp
            return FirebaseManager.update_invoice(invoice.invoice_number, invoice_dict)
        except Exception as e:
            _log.warning("Error updating invoice in Firebase: %s", e)
            return False
    
    def sync_to_balance_sheet(self, invoice):
        """Sync invoice changes to balance sheet - FIXED to properly update received_date and year"""
        try:
            if not FIREBASE_AVAILABLE:
                return
            from firebase_admin import db
            revenue_ref = db.reference('revenue')
            all_revenue = revenue_ref.get()
            if not all_revenue:
                return
            
            for rev_id, revenue in all_revenue.items():
                if revenue and revenue.get('is_invoice') and revenue.get('invoice_number') == invoice.invoice_number:
                    project_names = []
                    for item in invoice.items:
                        if hasattr(item, 'project_name') and item.project_name:
                            project_names.append(item.project_name)
                        elif item.description:
                            project_names.append(item.description)
                    new_description = f"{invoice.client_name} - {', '.join(project_names[:2])}"
                    if len(project_names) > 2:
                        new_description += f" +{len(project_names)-2} more"
                    
                    updates = {}
                    if new_description != revenue.get('description', ''):
                        updates['description'] = new_description
                    if invoice.due_date != revenue.get('due_date', 'N/A'):
                        updates['due_date'] = invoice.due_date
                    new_amount = float(invoice.total)
                    old_amount = float(revenue.get('amount', 0))
                    if abs(new_amount - old_amount) > 0.01:
                        updates['amount'] = str(new_amount)
                    if invoice.date != revenue.get('date', ''):
                        updates['date'] = invoice.date
                        try:
                            date_obj = datetime.strptime(invoice.date, "%m-%d-%Y")
                            updates['year'] = date_obj.year
                        except:
                            pass
                    if invoice.status != revenue.get('status', 'Pending'):
                        updates['status'] = invoice.status
                    
                    # FIX: Always update received_date based on status
                    if invoice.status == "Paid":
                        # If status is Paid, use the invoice's received_date
                        received_date = getattr(invoice, 'received_date', 'N/A')
                        if not received_date or received_date == '':
                            received_date = 'N/A'
                        updates['received_date'] = received_date
                        
                        # Update year based on received_date for paid invoices
                        if received_date != 'N/A':
                            try:
                                received_date_obj = datetime.strptime(received_date, "%m-%d-%Y")
                                updates['year'] = received_date_obj.year
                            except:
                                pass
                    else:
                        # For non-paid status, received_date should be N/A
                        updates['received_date'] = 'N/A'
                        # Keep year based on invoice date
                        try:
                            date_obj = datetime.strptime(invoice.date, "%m-%d-%Y")
                            updates['year'] = date_obj.year
                        except:
                            pass
                    
                    if updates:
                        updates['updated_at'] = datetime.now().isoformat()
                        revenue_ref.child(rev_id).update(updates)
                        _log.info("(converted from print, see git history)")
                    break
        except Exception as e:
            _log.warning("Error syncing to balance sheet: %s", e)
            import traceback
            traceback.print_exc()
        
    def refresh_balance_sheet(self):
        try:
            main_window = self.window()
            while main_window and not hasattr(main_window, 'balance_sheet_tab'):
                main_window = main_window.parent()
            if main_window and hasattr(main_window, 'balance_sheet_tab'):
                balance_tab = main_window.balance_sheet_tab
                if hasattr(balance_tab, 'refresh_invoice_revenues'):
                    balance_tab.refresh_invoice_revenues()
                else:
                    balance_tab.load_all_financial_data()
                    balance_tab.update_annual_summary()
                    balance_tab.on_category_changed(balance_tab.current_category)
                    balance_tab.update_stats_cards()
        except Exception as e:
            _log.warning("Error refreshing balance sheet: %s", e)
    
    def refresh_invoice_history(self):
        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'refresh_invoices_immediately'):
                    parent.refresh_invoices_immediately()
                    break
                parent = parent.parent()
        except Exception as e:
            _log.warning("Error refreshing invoice history: %s", e)
    
    def regenerate_invoice_pdf(self, invoice):
        try:
            output_path = Config.INVOICES_DIR / f"{invoice.invoice_number}.pdf"
            logo_path = Config.LOGO_FILE if Config.LOGO_FILE.exists() else None
            success = PDFGenerator.generate(invoice, output_path, logo_path)
            if success and FIREBASE_AVAILABLE:
                FirebaseManager.save_pdf_to_firebase(invoice.invoice_number, output_path)
        except Exception as e:
            _log.warning("Error regenerating PDF: %s", e)
    
    def save_changes(self):
        try:
            self.invoice.invoice_number = self.invoice_number_edit.text().strip()
            self.invoice.date = self.date_edit.date().toString("MM-dd-yyyy")
            self.invoice.due_date = self.due_date_edit.date().toString("MM-dd-yyyy")
            self.invoice.tax_rate = Decimal(str(self.tax_rate_edit.value()))
            self.invoice.status = self.status_combo.currentText()
            
            # FIX: Set received_date based on status
            if self.invoice.status == "Paid":
                # Check if received_date_edit has a valid date
                if self.received_date_edit.isEnabled() and self.received_date_edit.date().isValid():
                    self.invoice.received_date = self.received_date_edit.date().toString("MM-dd-yyyy")
                else:
                    # If received_date_edit is disabled or no valid date, use current date
                    self.invoice.received_date = datetime.now().strftime("%m-%d-%Y")
            else:
                self.invoice.received_date = "N/A"
            
            self.invoice.items = []
            for row in self.item_rows:
                self.invoice.items.append(row.get_item())
            self.invoice.calculate_totals()
            self.regenerate_invoice_pdf(self.invoice)
            if self.update_invoice_in_firebase(self.invoice):
                self.sync_to_balance_sheet(self.invoice)  # This now has the updated method
            self.refresh_balance_sheet()
            self.refresh_invoice_history()
            QtWidgets.QMessageBox.information(self, "Success", f"Invoice {self.invoice.invoice_number} updated successfully!")
            self.accept()
        except Exception as e:
            _log.warning("Error saving changes: %s", e)
            QtWidgets.QMessageBox.critical(self, "Error", f"Error saving changes: {str(e)}")
            

class EditItemRowWidget(QtWidgets.QWidget):
    """Widget for a single invoice item row in edit dialog"""
    removed = pyqtSignal()
    valueChanged = pyqtSignal()
    
    def __init__(self, item=None):
        super().__init__()
        self.item = item or InvoiceItem()
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)
        
        self.project_number_edit = QtWidgets.QLineEdit(self.item.project_number)
        self.project_number_edit.setPlaceholderText("Project #")
        self.project_number_edit.setMinimumHeight(35)
        self.project_number_edit.setMaximumWidth(180)
        self.project_number_edit.setAlignment(QtCore.Qt.AlignCenter)
        self.project_number_edit.textChanged.connect(self.valueChanged.emit)
        
        self.desc_edit = QtWidgets.QLineEdit(self.item.description)
        self.desc_edit.setPlaceholderText("Description")
        self.desc_edit.setMinimumHeight(35)
        self.desc_edit.setMaximumWidth(180)
        self.desc_edit.setAlignment(QtCore.Qt.AlignCenter)
        self.desc_edit.textChanged.connect(self.valueChanged.emit)
        
        self.plant_edit = QtWidgets.QLineEdit(self.item.plant)
        self.plant_edit.setPlaceholderText("Plant")
        self.plant_edit.setMinimumHeight(35)
        self.plant_edit.setMaximumWidth(180)
        self.plant_edit.setAlignment(QtCore.Qt.AlignCenter)
        self.plant_edit.textChanged.connect(self.valueChanged.emit)
        
        self.qty_spin = QtWidgets.QSpinBox()
        self.qty_spin.setRange(1, 1000000)
        self.qty_spin.setValue(int(self.item.quantity))
        self.qty_spin.setMinimumHeight(35)
        self.qty_spin.setMinimumWidth(60)
        self.qty_spin.setAlignment(QtCore.Qt.AlignCenter)
        self.qty_spin.valueChanged.connect(self.update_total)
        self.qty_spin.valueChanged.connect(self.valueChanged.emit)
        
        initial_price = float(self.item.unit_price) if self.item.unit_price != Decimal('0') else 0.0
        self.price_edit = QtWidgets.QLineEdit(f"${initial_price:.2f}" if initial_price > 0 else "")
        self.price_edit.setPlaceholderText("$0.00")
        self.price_edit.setMinimumHeight(35)
        self.price_edit.setMinimumWidth(80)
        self.price_edit.setAlignment(QtCore.Qt.AlignCenter)
        self.price_edit.textChanged.connect(self.update_total)
        self.price_edit.textChanged.connect(self.valueChanged.emit)
        
        self.payment_combo = QtWidgets.QComboBox()
        self.payment_combo.addItems(["Deposit Received (50%)", "Final Payment Due", "Full Amount Due"])
        self.payment_combo.setMinimumHeight(35)
        self.payment_combo.setMinimumWidth(120)
        
        category_found = False
        if hasattr(self.item, 'payment_category') and self.item.payment_category:
            stored_category = self.item.payment_category
            if "Deposit" in stored_category or "Down Payment" in stored_category or stored_category == "50%" or "50%" in stored_category:
                self.payment_combo.setCurrentText("Deposit Received (50%)")
                category_found = True
            elif "Final Payment" in stored_category:
                self.payment_combo.setCurrentText("Final Payment Due")
                category_found = True
            elif "Full Amount" in stored_category or "Due Payment" in stored_category:
                self.payment_combo.setCurrentText("Full Amount Due")
                category_found = True
        
        if not category_found:
            self.detect_payment_category_from_amounts()
        
        self.payment_combo.currentTextChanged.connect(self.update_total)
        self.payment_combo.currentTextChanged.connect(self.valueChanged.emit)
        
        self.payment_due_label = QtWidgets.QLabel(f"${float(self.item.payment_due):.2f}")
        self.payment_due_label.setAlignment(QtCore.Qt.AlignCenter)
        self.payment_due_label.setMinimumWidth(100)
        self.payment_due_label.setMinimumHeight(35)
        self.payment_due_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
            }
        """)
        
        self.total_label = QtWidgets.QLabel(Currency.format(self.item.total))
        self.total_label.setAlignment(QtCore.Qt.AlignCenter)
        self.total_label.setMinimumWidth(80)
        self.total_label.setMinimumHeight(35)
        self.total_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        
        self.remove_btn = QtWidgets.QPushButton("✕")
        self.remove_btn.setMaximumWidth(40)
        self.remove_btn.setMinimumHeight(35)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #c82333; }
        """)
        self.remove_btn.clicked.connect(self.removed)
        
        layout.addWidget(self.project_number_edit)
        layout.addWidget(self.desc_edit)
        layout.addWidget(self.plant_edit)
        layout.addWidget(self.qty_spin)
        layout.addWidget(self.price_edit)
        layout.addWidget(self.payment_combo)
        layout.addWidget(self.payment_due_label)
        layout.addWidget(self.total_label)
        layout.addWidget(self.remove_btn)
        
        self.update_total()
    
    def detect_payment_category_from_amounts(self):
        total = Decimal(str(self.item.quantity)) * self.item.unit_price
        if total > 0:
            down = Decimal(str(self.item.down_payment))
            due = Decimal(str(self.item.payment_due))
            down_percentage = down / total if total > 0 else Decimal('0')
            if abs(down_percentage - Decimal('0.5')) < Decimal('0.01') and due > 0:
                self.payment_combo.setCurrentText("Deposit Received (50%)")
            elif due == 0:
                self.payment_combo.setCurrentText("Final Payment Due")
            elif down == 0:
                self.payment_combo.setCurrentText("Full Amount Due")
            else:
                self.payment_combo.setCurrentText("Full Amount Due")
        else:
            self.payment_combo.setCurrentText("Full Amount Due")
    
    def update_total(self):
        try:
            quantity = self.qty_spin.value()
            price_text = self.price_edit.text().replace("$", "").replace(",", "").strip()
            if price_text:
                unit_price = Decimal(str(float(price_text)))
            else:
                unit_price = Decimal('0.0')
            total = Decimal(str(quantity)) * unit_price
            payment_type = self.payment_combo.currentText()
            self.item.payment_category = payment_type
            if "Deposit" in payment_type or "Down Payment" in payment_type:
                down_payment = total * Decimal("0.5")
                payment_due = total - down_payment
            elif "Final Payment" in payment_type:
                down_payment = Decimal("0.0")
                payment_due = Decimal("0.0")
            else:
                down_payment = Decimal("0.0")
                payment_due = total
            self.item.quantity = quantity
            self.item.unit_price = unit_price
            self.item.down_payment = down_payment
            self.item.payment_due = payment_due
            self.payment_due_label.setText(f"${float(payment_due):.2f}")
            self.total_label.setText(Currency.format(total))
        except Exception as e:
            _log.warning("Error updating total: %s", e)
    
    def get_item(self):
        try:
            price_text = self.price_edit.text().replace("$", "").strip()
            unit_price = Decimal(str(float(price_text))) if price_text else Decimal("0.0")
            quantity = self.qty_spin.value()
            total = Decimal(str(quantity)) * unit_price
            payment_category = self.payment_combo.currentText()
            if "Deposit" in payment_category or "Down Payment" in payment_category:
                down_payment = total * Decimal("0.5")
                payment_due = total - down_payment
            elif "Final Payment" in payment_category:
                down_payment = Decimal("0.0")
                payment_due = Decimal("0.0")
            else:
                down_payment = Decimal("0.0")
                payment_due = total
            return InvoiceItem(
                project_number=self.project_number_edit.text(),
                description=self.desc_edit.text(),
                plant=self.plant_edit.text(),
                quantity=quantity,
                unit_price=float(unit_price),
                down_payment=float(down_payment),
                payment_due=float(payment_due),
                payment_category=payment_category
            )
        except Exception as e:
            _log.warning("Error in get_item: %s", e)
            return InvoiceItem()


class InvoiceHistoryTab(QtWidgets.QWidget):
    """Enhanced Invoice History Tab with direct invoice history view and Firebase sync"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.current_client = None
        self.init_ui()
    
    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.stacked_widget = QtWidgets.QStackedWidget()
        
        self.client_view = ClientListWidget()
        self.client_view.client_selected.connect(self.show_invoice_history)
        self.stacked_widget.addWidget(self.client_view)
        
        self.history_view_placeholder = QtWidgets.QWidget()
        self.stacked_widget.addWidget(self.history_view_placeholder)
        
        main_layout.addWidget(self.stacked_widget)
        self.show_client_view()
        self._auto_refresh_timer = QtCore.QTimer(self)
        self._auto_refresh_timer.setInterval(5000)
        self._auto_refresh_timer.timeout.connect(self.refresh_invoices_immediately)
        self._auto_refresh_timer.start()
        self._auto_refresh_timer = QtCore.QTimer(self)
        self._auto_refresh_timer.setInterval(5000)
        self._auto_refresh_timer.timeout.connect(self.refresh_invoices_immediately)
        self._auto_refresh_timer.start()
    
    def add_firebase_sync_button(self):
        if not FIREBASE_AVAILABLE:
            return
    
    def sync_to_firebase(self):
        if not FIREBASE_AVAILABLE:
            QtWidgets.QMessageBox.information(self, "Cloud Sync", "Firebase integration is not available.")
            return
        try:
            progress_dialog = QtWidgets.QProgressDialog("Syncing invoices to cloud...", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Cloud Sync")
            progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
            progress_dialog.show()
            QtWidgets.QMessageBox.information(self, "Cloud Sync", "✅ Invoices are automatically synced to Firebase!\n\nYour data is already backed up and accessible from anywhere.")
            progress_dialog.close()
        except Exception as e:
            progress_dialog.close()
            QtWidgets.QMessageBox.critical(self, "Sync Error", f"Error during cloud sync: {e}")
    
    def show_client_view(self):
        if self.stacked_widget.indexOf(self.history_view_placeholder) != -1:
            self.stacked_widget.removeWidget(self.history_view_placeholder)
        self.history_view_placeholder = QtWidgets.QWidget()
        self.stacked_widget.insertWidget(1, self.history_view_placeholder)
        self.stacked_widget.setCurrentIndex(0)
        self.client_view.load_clients()
    
    def show_invoice_history(self, client_name: str):
        self.current_client = client_name
        history_view = InvoiceHistoryViewWidget(client_name)
        history_view.back_clicked.connect(self.show_client_view)
        index = self.stacked_widget.indexOf(self.history_view_placeholder)
        self.stacked_widget.removeWidget(self.history_view_placeholder)
        self.stacked_widget.insertWidget(index, history_view)
        self.history_view_placeholder = QtWidgets.QWidget()
        self.stacked_widget.insertWidget(index + 1, self.history_view_placeholder)
        self.stacked_widget.setCurrentIndex(index)
    
    def refresh_data(self):
        current_widget = self.stacked_widget.currentWidget()
        if isinstance(current_widget, ClientListWidget):
            current_widget.load_clients()
        elif isinstance(current_widget, InvoiceHistoryViewWidget):
            self.show_invoice_history(self.current_client)
        QtWidgets.QMessageBox.information(self, "Refresh", "Data refreshed successfully!")
    
    def load_history(self):
        self.show_client_view()
    
    def refresh_invoices_immediately(self):
        current_widget = self.stacked_widget.currentWidget()
        if isinstance(current_widget, ClientListWidget):
            current_widget.load_clients()
        elif self.current_client and isinstance(current_widget, InvoiceHistoryViewWidget):
            search_text = current_widget.date_range_widget.search_bar.text() if hasattr(current_widget, "date_range_widget") else ""
            self.show_invoice_history(self.current_client)
            refreshed_widget = self.stacked_widget.currentWidget()
            if search_text and isinstance(refreshed_widget, InvoiceHistoryViewWidget):
                refreshed_widget.date_range_widget.search_bar.setText(search_text)
            

class InvoiceHistoryTab(QtWidgets.QWidget):
    """Enhanced Invoice History Tab with direct invoice history view and Firebase sync"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.current_client = None
        self.init_ui()
    
    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.stacked_widget = QtWidgets.QStackedWidget()
        
        self.client_view = ClientListWidget()
        self.client_view.client_selected.connect(self.show_invoice_history)
        self.stacked_widget.addWidget(self.client_view)
        
        self.history_view_placeholder = QtWidgets.QWidget()
        self.stacked_widget.addWidget(self.history_view_placeholder)
        
        main_layout.addWidget(self.stacked_widget)
        self.show_client_view()
    
    def add_firebase_sync_button(self):
        if not FIREBASE_AVAILABLE:
            return
    
    def sync_to_firebase(self):
        if not FIREBASE_AVAILABLE:
            QtWidgets.QMessageBox.information(self, "Cloud Sync", "Firebase integration is not available.")
            return
        try:
            progress_dialog = QtWidgets.QProgressDialog("Syncing invoices to cloud...", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Cloud Sync")
            progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
            progress_dialog.show()
            QtWidgets.QMessageBox.information(self, "Cloud Sync", "✅ Invoices are automatically synced to Firebase!\n\nYour data is already backed up and accessible from anywhere.")
            progress_dialog.close()
        except Exception as e:
            progress_dialog.close()
            QtWidgets.QMessageBox.critical(self, "Sync Error", f"Error during cloud sync: {e}")
    
    def show_client_view(self):
        if self.stacked_widget.indexOf(self.history_view_placeholder) != -1:
            self.stacked_widget.removeWidget(self.history_view_placeholder)
        self.history_view_placeholder = QtWidgets.QWidget()
        self.stacked_widget.insertWidget(1, self.history_view_placeholder)
        self.stacked_widget.setCurrentIndex(0)
        self.client_view.load_clients()
    
    def show_invoice_history(self, client_name: str):
        self.current_client = client_name
        history_view = InvoiceHistoryViewWidget(client_name)
        history_view.back_clicked.connect(self.show_client_view)
        index = self.stacked_widget.indexOf(self.history_view_placeholder)
        self.stacked_widget.removeWidget(self.history_view_placeholder)
        self.stacked_widget.insertWidget(index, history_view)
        self.history_view_placeholder = QtWidgets.QWidget()
        self.stacked_widget.insertWidget(index + 1, self.history_view_placeholder)
        self.stacked_widget.setCurrentIndex(index)
    
    def refresh_data(self):
        current_widget = self.stacked_widget.currentWidget()
        if isinstance(current_widget, ClientListWidget):
            current_widget.load_clients()
        elif isinstance(current_widget, InvoiceHistoryViewWidget):
            self.show_invoice_history(self.current_client)
        QtWidgets.QMessageBox.information(self, "Refresh", "Data refreshed successfully!")
    
    def load_history(self):
        self.show_client_view()
    
    def refresh_invoices_immediately(self):
        current_widget = self.stacked_widget.currentWidget()
        if isinstance(current_widget, ClientListWidget):
            current_widget.load_clients()
        elif self.current_client and isinstance(current_widget, InvoiceHistoryViewWidget):
            search_text = current_widget.date_range_widget.search_bar.text() if hasattr(current_widget, "date_range_widget") else ""
            self.show_invoice_history(self.current_client)
            refreshed_widget = self.stacked_widget.currentWidget()
            if search_text and isinstance(refreshed_widget, InvoiceHistoryViewWidget):
                refreshed_widget.date_range_widget.search_bar.setText(search_text)
