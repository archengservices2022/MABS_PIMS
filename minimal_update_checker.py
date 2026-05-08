# minimal_update_checker.py
from PyQt5 import QtWidgets, QtCore, QtGui
import webbrowser

class UpdateChecker(QtWidgets.QWidget):
    """Simple update checker widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Simple update button
        self.update_btn = QtWidgets.QPushButton("↻")
        self.update_btn.setFixedSize(32, 32)
        self.update_btn.setToolTip("Check for updates")
        self.update_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2980b9;
            }
        """)
        self.update_btn.clicked.connect(self.check_for_updates)
        
        layout.addWidget(self.update_btn)
    
    def check_for_updates(self):
        """Simple update check"""
        reply = QtWidgets.QMessageBox.information(
            self.parent,
            "Check for Updates",
            "Update checking feature will be available in the next version.\n\n"
            "For now, please visit the GitHub repository for updates.",
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
        )
        
        if reply == QtWidgets.QMessageBox.Ok:
            # Open GitHub repo (replace with your actual repo URL)
            webbrowser.open("https://github.com/MABS-Engineering/ArchInvoiceGenerator")