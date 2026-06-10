# update_indicator.py (or add to update_checker.py)
from PyQt5 import QtWidgets, QtCore, QtGui
from update_checker import UpdateChecker

class UpdateIndicator(QtWidgets.QWidget):
    """Update indicator widget for the tab bar"""
    
    update_available = QtCore.pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.update_checker = UpdateChecker(self)
        self.update_available_flag = False
        self.init_ui()
        
        # Auto-check removed — startup check is handled by UpdateChecker.check_on_startup()
    
    def init_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Update button
        self.update_btn = QtWidgets.QPushButton()
        self.update_btn.setFixedSize(32, 32)
        self.update_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.update_btn.setToolTip("Check for updates")
        self.update_btn.clicked.connect(self.on_update_clicked)
        
        # Set initial icon
        self.set_normal_icon()
        
        layout.addWidget(self.update_btn)
    
    def set_normal_icon(self):
        """Set normal icon (no updates)"""
        self.update_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 25px;
                font-weight: bold;
                color: #2c3e50;
                padding: 0px;
            }
            QPushButton:hover {
                color: #3498db;
            }
        """)
        self.update_btn.setText("🔄")
    
    def set_update_available_icon(self):
        """Set update available icon"""
        self.update_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 25px;
                font-weight: bold;
                color: #2c3e50;
                padding: 0px;
            }
            QPushButton:hover {
                color: #3498db;
            }
        """)
        self.update_btn.setText("📥")
        self.update_btn.setToolTip("Update available! Click to download")
    
    def check_updates_background(self):
        """Check for updates in background"""
        has_update = self.update_checker.check_for_updates(silent=True)
        
        if has_update:
            self.update_available_flag = True
            self.set_update_available_icon()
            self.update_available.emit()
    
    def on_update_clicked(self):
        """Handle update button click"""
        if self.update_available_flag:
            # Show update available dialog
            self.update_checker.show_update_available_dialog()
        else:
            # Check for updates manually
            self.update_checker.check_for_updates(silent=False)