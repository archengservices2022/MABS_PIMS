"""
Intelligent Reminders System
Automated notifications for quotes, projects, invoices, and payments
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from PyQt5 import QtWidgets, QtCore, QtGui
from collections import defaultdict

class ReminderSystem:
    """Intelligent reminder and notification system"""
    
    def __init__(self):
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.reminders_file = self.data_dir / "reminders.json"
        self.preferences_file = self.data_dir / "reminder_preferences.json"
        self.reminders = self._load_reminders()
        self.preferences = self._load_preferences()
        self.notification_queue = []
    
    def _load_reminders(self) -> Dict:
        """Load reminders from file"""
        if self.reminders_file.exists():
            try:
                with open(self.reminders_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading reminders: {e}")
        return {}
    
    def _save_reminders(self):
        """Save reminders to file"""
        try:
            with open(self.reminders_file, 'w', encoding='utf-8') as f:
                json.dump(self.reminders, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving reminders: {e}")
    
    def _load_preferences(self) -> Dict:
        """Load reminder preferences"""
        if self.preferences_file.exists():
            try:
                with open(self.preferences_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading preferences: {e}")
        
        # Default preferences
        return {
            'quote_expiration_days': [7, 3, 1],  # Days before expiration
            'payment_due_days': [7, 3, 1],  # Days before payment due
            'project_milestone_days': [7, 3, 1],  # Days before milestone
            'invoice_overdue_days': [1, 7, 14],  # Days after invoice overdue
            'follow_up_days': [30, 60, 90],  # Days since last contact
            'enabled_notifications': {
                'email': False,
                'popup': True,
                'sound': False
            }
        }
    
    def _save_preferences(self):
        """Save reminder preferences"""
        try:
            with open(self.preferences_file, 'w', encoding='utf-8') as f:
                json.dump(self.preferences, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving preferences: {e}")
    
    def create_reminder(self, reminder_type: str, target_id: str, title: str, 
                      description: str, due_date: str, priority: str = 'medium') -> str:
        """Create a new reminder"""
        reminder_id = f"rem_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        reminder = {
            'id': reminder_id,
            'type': reminder_type,
            'target_id': target_id,
            'title': title,
            'description': description,
            'due_date': due_date,
            'priority': priority,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'sent_notifications': []
        }
        
        self.reminders[reminder_id] = reminder
        self._save_reminders()
        return reminder_id
    
    def get_due_reminders(self) -> List[Dict]:
        """Get all reminders that are due"""
        today = datetime.now().date()
        due_reminders = []
        
        for reminder in self.reminders.values():
            if reminder['status'] != 'pending':
                continue
            
            try:
                due_date = datetime.strptime(reminder['due_date'], '%Y-%m-%d').date()
                if due_date <= today:
                    due_reminders.append(reminder)
            except:
                continue
        
        # Sort by priority and due date
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        due_reminders.sort(key=lambda x: (priority_order.get(x['priority'], 3), x['due_date']))
        
        return due_reminders
    
    def generate_quote_reminders(self, quotes: List[Dict]):
        """Generate reminders for quote expiration"""
        for quote in quotes:
            if quote.get('status') in ['Completed', 'Converted', 'Expired', 'Cancel']:
                continue
            
            valid_until = quote.get('valid_until')
            if not valid_until:
                continue
            
            try:
                due_date = datetime.strptime(valid_until, '%Y-%m-%d').date()
                today = datetime.now().date()
                
                for days_before in self.preferences['quote_expiration_days']:
                    reminder_date = due_date - timedelta(days=days_before)
                    
                    if reminder_date == today:
                        priority = 'high' if days_before <= 1 else 'medium' if days_before <= 3 else 'low'
                        
                        self.create_reminder(
                            'quote_expiration',
                            quote.get('job_number', ''),
                            f"Quote Expiring in {days_before} days",
                            f"Quote {quote.get('job_number', '')} for {quote.get('client', '')} expires on {valid_until}",
                            reminder_date.strftime('%Y-%m-%d'),
                            priority
                        )
            except:
                continue
    
    def generate_payment_reminders(self, projects: List[Dict]):
        """Generate reminders for payment due dates"""
        for project in projects:
            if project.get('status') in ['Paid', 'Cancelled']:
                continue
            
            due_date = project.get('due_date')
            if not due_date:
                continue
            
            try:
                due_dt = datetime.strptime(due_date, '%m-%d-%Y').date()
                today = datetime.now().date()
                
                for days_before in self.preferences['payment_due_days']:
                    reminder_date = due_dt - timedelta(days=days_before)
                    
                    if reminder_date == today:
                        # Check if there are outstanding payments
                        outstanding = self._get_outstanding_amount(project)
                        if outstanding > 0:
                            priority = 'high' if days_before <= 1 else 'medium'
                            
                            self.create_reminder(
                                'payment_due',
                                project.get('project_number', ''),
                                f"Payment Due in {days_before} days",
                                f"Project {project.get('project_number', '')} - ${outstanding:,.2f} due on {due_date}",
                                reminder_date.strftime('%Y-%m-%d'),
                                priority
                            )
            except:
                continue
    
    def generate_follow_up_reminders(self, clients: Dict):
        """Generate follow-up reminders for clients"""
        today = datetime.now().date()
        
        for client_name, client_data in clients.items():
            last_contact_str = client_data.get('last_contact')
            if not last_contact_str:
                continue
            
            try:
                last_contact = datetime.strptime(last_contact_str.split('T')[0], '%Y-%m-%d').date()
                
                for days_since in self.preferences['follow_up_days']:
                    follow_up_date = last_contact + timedelta(days=days_since)
                    
                    if follow_up_date == today:
                        priority = 'medium' if days_since <= 60 else 'low'
                        
                        self.create_reminder(
                            'follow_up',
                            client_name,
                            f"Client Follow-up ({days_since} days)",
                            f"Last contact with {client_name} was {days_since} days ago. Time to check in!",
                            follow_up_date.strftime('%Y-%m-%d'),
                            priority
                        )
            except:
                continue
    
    def _get_outstanding_amount(self, project: Dict) -> float:
        """Calculate outstanding amount for a project"""
        try:
            total_amount = float(project.get('project_amount', '0').replace('$', '').replace(',', ''))
            
            # Sum all payments
            payments = project.get('payments', [])
            paid_amount = sum(float(p.get('amount', '0').replace('$', '').replace(',', '')) for p in payments)
            
            return max(0, total_amount - paid_amount)
        except:
            return 0.0
    
    def mark_reminder_sent(self, reminder_id: str, notification_type: str):
        """Mark that a reminder notification has been sent"""
        if reminder_id in self.reminders:
            self.reminders[reminder_id]['sent_notifications'].append({
                'type': notification_type,
                'sent_at': datetime.now().isoformat()
            })
            self._save_reminders()
    
    def complete_reminder(self, reminder_id: str):
        """Mark a reminder as completed"""
        if reminder_id in self.reminders:
            self.reminders[reminder_id]['status'] = 'completed'
            self.reminders[reminder_id]['completed_at'] = datetime.now().isoformat()
            self._save_reminders()
    
    def get_reminder_summary(self) -> Dict:
        """Get summary of reminders by type and priority"""
        summary = {
            'total_pending': 0,
            'by_type': defaultdict(int),
            'by_priority': defaultdict(int),
            'overdue': 0
        }
        
        today = datetime.now().date()
        
        for reminder in self.reminders.values():
            if reminder['status'] == 'pending':
                summary['total_pending'] += 1
                summary['by_type'][reminder['type']] += 1
                summary['by_priority'][reminder['priority']] += 1
                
                try:
                    due_date = datetime.strptime(reminder['due_date'], '%Y-%m-%d').date()
                    if due_date < today:
                        summary['overdue'] += 1
                except:
                    pass
        
        return dict(summary)


class ReminderNotificationWidget(QtWidgets.QWidget):
    """Widget for displaying reminder notifications"""
    
    def __init__(self, reminder_system: ReminderSystem, parent=None):
        super().__init__(parent)
        self.reminder_system = reminder_system
        self.init_ui()
        self.refresh_reminders()
        
        # Set up timer for periodic refresh
        self.refresh_timer = QtCore.QTimer()
        self.refresh_timer.timeout.connect(self.refresh_reminders)
        self.refresh_timer.start(60000)  # Refresh every minute
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Header
        header_layout = QtWidgets.QHBoxLayout()
        
        title_label = QtWidgets.QLabel("🔔 Intelligent Reminders")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
            }
        """)
        header_layout.addWidget(title_label)
        
        self.refresh_btn = QtWidgets.QPushButton("🔄")
        self.refresh_btn.setFixedSize(30, 30)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #17a2b8;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #138496;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_reminders)
        header_layout.addWidget(self.refresh_btn)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Reminders area
        self.reminders_area = QtWidgets.QWidget()
        self.reminders_layout = QtWidgets.QVBoxLayout(self.reminders_area)
        self.reminders_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.reminders_area)
        
        # Initially hidden if no reminders
        self.setVisible(False)
    
    def refresh_reminders(self):
        """Refresh and display reminders"""
        due_reminders = self.reminder_system.get_due_reminders()
        
        # Clear existing reminders
        for i in reversed(range(self.reminders_layout.count())):
            child = self.reminders_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        if not due_reminders:
            self.setVisible(False)
            return
        
        # Show reminders
        self.setVisible(True)
        
        # Add summary
        summary = self.reminder_system.get_reminder_summary()
        summary_label = QtWidgets.QLabel(f"📊 {summary['total_pending']} pending reminders")
        summary_label.setStyleSheet("""
            QLabel {
                background: #f8f9fa;
                color: #2c3e50;
                padding: 8px;
                border-radius: 6px;
                font-weight: bold;
                margin-bottom: 5px;
            }
        """)
        self.reminders_layout.addWidget(summary_label)
        
        # Add reminder items
        for reminder in due_reminders[:5]:  # Show max 5 reminders
            self._add_reminder_widget(reminder)
        
        if len(due_reminders) > 5:
            more_label = QtWidgets.QLabel(f"... and {len(due_reminders) - 5} more")
            more_label.setStyleSheet("""
                QLabel {
                    color: #666;
                    font-style: italic;
                    font-size: 12px;
                    text-align: center;
                    padding: 5px;
                }
            """)
            self.reminders_layout.addWidget(more_label)
    
    def _add_reminder_widget(self, reminder: Dict):
        """Add a single reminder widget"""
        priority_colors = {
            'high': '#ffebee',
            'medium': '#fff3e0',
            'low': '#e8f5e8'
        }
        
        priority_text_colors = {
            'high': '#c62828',
            'medium': '#f57c00',
            'low': '#2e7d32'
        }
        
        priority = reminder.get('priority', 'medium')
        bg_color = priority_colors.get(priority, '#f5f5f5')
        text_color = priority_text_colors.get(priority, '#666')
        
        reminder_widget = QtWidgets.QWidget()
        reminder_widget.setStyleSheet(f"""
            QWidget {{
                background: {bg_color};
                border-radius: 6px;
                padding: 8px;
                margin: 2px 0;
            }}
        """)
        
        reminder_layout = QtWidgets.QHBoxLayout(reminder_widget)
        reminder_layout.setContentsMargins(8, 6, 8, 6)
        reminder_layout.setSpacing(8)
        
        # Priority indicator
        priority_label = QtWidgets.QLabel("🔴" if priority == 'high' else "🟡" if priority == 'medium' else "🟢")
        priority_label.setStyleSheet(f"color: {text_color}; font-size: 16px;")
        reminder_layout.addWidget(priority_label)
        
        # Content
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setSpacing(2)
        
        title_label = QtWidgets.QLabel(reminder.get('title', ''))
        title_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                color: {text_color};
                font-size: 12px;
            }}
        """)
        content_layout.addWidget(title_label)
        
        desc_label = QtWidgets.QLabel(reminder.get('description', ''))
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 11px;
            }}
        """)
        desc_label.setWordWrap(True)
        content_layout.addWidget(desc_label)
        
        reminder_layout.addLayout(content_layout, 1)
        
        # Action buttons
        action_layout = QtWidgets.QVBoxLayout()
        action_layout.setSpacing(2)
        
        complete_btn = QtWidgets.QPushButton("✓")
        complete_btn.setFixedSize(24, 24)
        complete_btn.setStyleSheet(f"""
            QPushButton {{
                background: {text_color};
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {text_color}dd;
            }}
        """)
        complete_btn.clicked.connect(lambda: self.complete_reminder(reminder['id']))
        action_layout.addWidget(complete_btn)
        
        reminder_layout.addLayout(action_layout)
        
        self.reminders_layout.addWidget(reminder_widget)
    
    def complete_reminder(self, reminder_id: str):
        """Complete a reminder"""
        self.reminder_system.complete_reminder(reminder_id)
        self.refresh_reminders()


class ReminderSettingsDialog(QtWidgets.QDialog):
    """Dialog for configuring reminder settings"""
    
    def __init__(self, reminder_system: ReminderSystem, parent=None):
        super().__init__(parent)
        self.reminder_system = reminder_system
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Reminder Settings")
        self.setFixedSize(500, 400)
        self.setModal(True)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Quote expiration settings
        quote_group = QtWidgets.QGroupBox("Quote Expiration Reminders")
        quote_layout = QtWidgets.QVBoxLayout(quote_group)
        
        self.quote_days_edit = QtWidgets.QLineEdit()
        self.quote_days_edit.setText(", ".join(map(str, self.reminder_system.preferences['quote_expiration_days'])))
        self.quote_days_edit.setPlaceholderText("Days before expiration (e.g., 7, 3, 1)")
        quote_layout.addWidget(QtWidgets.QLabel("Remind me days before quote expires:"))
        quote_layout.addWidget(self.quote_days_edit)
        
        layout.addWidget(quote_group)
        
        # Payment due settings
        payment_group = QtWidgets.QGroupBox("Payment Due Reminders")
        payment_layout = QtWidgets.QVBoxLayout(payment_group)
        
        self.payment_days_edit = QtWidgets.QLineEdit()
        self.payment_days_edit.setText(", ".join(map(str, self.reminder_system.preferences['payment_due_days'])))
        self.payment_days_edit.setPlaceholderText("Days before payment due (e.g., 7, 3, 1)")
        payment_layout.addWidget(QtWidgets.QLabel("Remind me days before payment due:"))
        payment_layout.addWidget(self.payment_days_edit)
        
        layout.addWidget(payment_group)
        
        # Follow-up settings
        followup_group = QtWidgets.QGroupBox("Client Follow-up Reminders")
        followup_layout = QtWidgets.QVBoxLayout(followup_group)
        
        self.followup_days_edit = QtWidgets.QLineEdit()
        self.followup_days_edit.setText(", ".join(map(str, self.reminder_system.preferences['follow_up_days'])))
        self.followup_days_edit.setPlaceholderText("Days since last contact (e.g., 30, 60, 90)")
        followup_layout.addWidget(QtWidgets.QLabel("Remind me to follow up after days:"))
        followup_layout.addWidget(self.followup_days_edit)
        
        layout.addWidget(followup_group)
        
        # Notification settings
        notification_group = QtWidgets.QGroupBox("Notification Settings")
        notification_layout = QtWidgets.QVBoxLayout(notification_group)
        
        self.popup_checkbox = QtWidgets.QCheckBox("Show popup notifications")
        self.popup_checkbox.setChecked(self.reminder_system.preferences['enabled_notifications']['popup'])
        notification_layout.addWidget(self.popup_checkbox)
        
        self.email_checkbox = QtWidgets.QCheckBox("Send email notifications")
        self.email_checkbox.setChecked(self.reminder_system.preferences['enabled_notifications']['email'])
        notification_layout.addWidget(self.email_checkbox)
        
        layout.addWidget(notification_group)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        save_btn = QtWidgets.QPushButton("Save Settings")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #28a745;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #218838;
            }
        """)
        save_btn.clicked.connect(self.save_settings)
        
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #5a6268;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
    
    def save_settings(self):
        """Save reminder settings"""
        try:
            # Parse days settings
            quote_days = [int(x.strip()) for x in self.quote_days_edit.text().split(',') if x.strip().isdigit()]
            payment_days = [int(x.strip()) for x in self.payment_days_edit.text().split(',') if x.strip().isdigit()]
            followup_days = [int(x.strip()) for x in self.followup_days_edit.text().split(',') if x.strip().isdigit()]
            
            # Update preferences
            self.reminder_system.preferences['quote_expiration_days'] = quote_days
            self.reminder_system.preferences['payment_due_days'] = payment_days
            self.reminder_system.preferences['follow_up_days'] = followup_days
            self.reminder_system.preferences['enabled_notifications']['popup'] = self.popup_checkbox.isChecked()
            self.reminder_system.preferences['enabled_notifications']['email'] = self.email_checkbox.isChecked()
            
            self.reminder_system._save_preferences()
            QtWidgets.QMessageBox.information(self, "Settings Saved", "Reminder settings have been saved successfully!")
            self.accept()
            
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Error saving settings: {str(e)}")
