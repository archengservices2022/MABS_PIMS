"""
Template Manager for Quotes, Projects, and Invoices
Provides intelligent template-based automation for business processes
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from PyQt5 import QtWidgets, QtCore, QtGui

class TemplateManager:
    """Manages templates for quotes, projects, and invoices"""
    
    def __init__(self):
        self.templates_dir = Path("data/templates")
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict:
        """Load all templates from files"""
        templates = {
            'quotes': {},
            'projects': {},
            'invoices': {}
        }
        
        for template_type in templates.keys():
            template_file = self.templates_dir / f"{template_type}_templates.json"
            if template_file.exists():
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
                        templates[template_type] = json.load(f)
                except Exception as e:
                    print(f"Error loading {template_type} templates: {e}")
        
        return templates
    
    def _save_templates(self):
        """Save all templates to files"""
        for template_type, templates in self.templates.items():
            template_file = self.templates_dir / f"{template_type}_templates.json"
            try:
                with open(template_file, 'w', encoding='utf-8') as f:
                    json.dump(templates, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error saving {template_type} templates: {e}")
    
    def get_templates(self, template_type: str) -> List[Dict]:
        """Get all templates of a specific type"""
        return list(self.templates.get(template_type, {}).values())
    
    def get_template(self, template_type: str, template_id: str) -> Optional[Dict]:
        """Get a specific template by ID"""
        return self.templates.get(template_type, {}).get(template_id)
    
    def add_template(self, template_type: str, template_data: Dict) -> str:
        """Add a new template"""
        template_id = f"{template_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        template_data['id'] = template_id
        template_data['created_at'] = datetime.now().isoformat()
        template_data['updated_at'] = datetime.now().isoformat()
        
        self.templates[template_type][template_id] = template_data
        self._save_templates()
        return template_id
    
    def update_template(self, template_type: str, template_id: str, template_data: Dict):
        """Update an existing template"""
        if template_id in self.templates.get(template_type, {}):
            template_data['id'] = template_id
            template_data['updated_at'] = datetime.now().isoformat()
            self.templates[template_type][template_id] = template_data
            self._save_templates()
    
    def delete_template(self, template_type: str, template_id: str):
        """Delete a template"""
        if template_id in self.templates.get(template_type, {}):
            del self.templates[template_type][template_id]
            self._save_templates()
    
    def initialize_default_templates(self):
        """Initialize default templates if none exist"""
        if not self.templates['quotes']:
            self._create_default_quote_templates()
        if not self.templates['projects']:
            self._create_default_project_templates()
        if not self.templates['invoices']:
            self._create_default_invoice_templates()
    
    def _create_default_quote_templates(self):
        """Create default quote templates"""
        templates = {
            'structural_engineering': {
                'name': 'Structural Engineering Services',
                'description': 'Complete structural engineering package',
                'scope_of_work': '''Complete structural engineering services including:
- Structural analysis and design
- Foundation design and recommendations
- Steel structure design
- Load calculations and specifications
- Construction drawings and details
- Engineering reports and documentation''',
                'services': ['Structural', 'Foundation', 'Anchor Calculations'],
                'default_price_range': '$10,000 - $50,000',
                'estimated_duration': '30-45 days',
                'payment_terms': 'Net 30'
            },
            'civil_engineering': {
                'name': 'Civil Engineering Services',
                'description': 'Comprehensive civil engineering package',
                'scope_of_work': '''Complete civil engineering services including:
- Site planning and grading
- Drainage design and calculations
- Utility planning and coordination
- Road and parking design
- Erosion control plans
- Land development documentation''',
                'services': ['Civil', 'Plumbing Design'],
                'default_price_range': '$8,000 - $35,000',
                'estimated_duration': '25-40 days',
                'payment_terms': 'Net 30'
            },
            'multi_discipline': {
                'name': 'Multi-Discipline Engineering',
                'description': 'Full engineering services package',
                'scope_of_work': '''Complete multi-discipline engineering services including:
- Structural engineering and design
- Civil engineering and site work
- Electrical system design
- Mechanical system design
- Plumbing design and calculations
- Coordination between all disciplines
- Complete construction documentation''',
                'services': ['Structural', 'Civil', 'Electrical', 'Mechanical', 'Plumbing Design'],
                'default_price_range': '$25,000 - $100,000',
                'estimated_duration': '45-60 days',
                'payment_terms': '50% Advance, 50% on Completion'
            }
        }
        
        for template_id, template_data in templates.items():
            self.add_template('quotes', template_data)
    
    def _create_default_project_templates(self):
        """Create default project templates"""
        templates = {
            'small_project': {
                'name': 'Small Project Template',
                'description': 'Template for projects under $10,000',
                'payment_category': 'Small Project',
                'status_workflow': ['Not Started', 'In Progress', 'Completed Not Invoiced', 'Completed & Invoiced'],
                'milestones': [
                    {'name': 'Project Kickoff', 'duration_days': 0},
                    {'name': 'Design Phase', 'duration_days': 7},
                    {'name': 'Review Phase', 'duration_days': 14},
                    {'name': 'Final Deliverables', 'duration_days': 21}
                ],
                'payment_stages': ['Down Payment', 'Due Payment'],
                'estimated_duration': '21 days'
            },
            'medium_project': {
                'name': 'Medium Project Template',
                'description': 'Template for projects $10,000 - $50,000',
                'payment_category': 'Medium Project',
                'status_workflow': ['Not Started', 'In Progress', 'On Hold', 'Completed Not Invoiced', 'Completed & Invoiced'],
                'milestones': [
                    {'name': 'Project Kickoff', 'duration_days': 0},
                    {'name': 'Preliminary Design', 'duration_days': 10},
                    {'name': 'Detailed Design', 'duration_days': 20},
                    {'name': 'Review Phase', 'duration_days': 30},
                    {'name': 'Construction Documents', 'duration_days': 40},
                    {'name': 'Final Deliverables', 'duration_days': 45}
                ],
                'payment_stages': ['Down Payment', 'Due Payment', 'Final Payment'],
                'estimated_duration': '45 days'
            },
            'large_project': {
                'name': 'Large Project Template',
                'description': 'Template for projects over $50,000',
                'payment_category': 'Large Project',
                'status_workflow': ['Not Started', 'In Progress', 'On Hold', 'Completed Not Invoiced', 'Completed & Invoiced', 'Paid'],
                'milestones': [
                    {'name': 'Project Kickoff', 'duration_days': 0},
                    {'name': 'Conceptual Design', 'duration_days': 15},
                    {'name': 'Schematic Design', 'duration_days': 30},
                    {'name': 'Design Development', 'duration_days': 45},
                    {'name': 'Construction Documents', 'duration_days': 60},
                    {'name': 'Review Phase', 'duration_days': 75},
                    {'name': 'Final Deliverables', 'duration_days': 90}
                ],
                'payment_stages': ['Down Payment', 'Due Payment', 'Final Payment'],
                'estimated_duration': '90 days'
            }
        }
        
        for template_id, template_data in templates.items():
            self.add_template('projects', template_data)
    
    def _create_default_invoice_templates(self):
        """Create default invoice templates"""
        templates = {
            'standard_invoice': {
                'name': 'Standard Invoice',
                'description': 'Standard invoice with payment terms',
                'payment_terms': 'Net 30',
                'payment_structure': 'Full Amount Due',
                'down_payment_percentage': 0,
                'notes_template': 'Payment due within 30 days of invoice date. Thank you for your business.',
                'footer_text': 'MABS Engineering LLC\nLicensed Professional Engineers\nState License #12345'
            },
            'down_payment_invoice': {
                'name': 'Down Payment Invoice',
                'description': 'Invoice with down payment requirement',
                'payment_terms': '50% Advance, 50% on Completion',
                'payment_structure': 'Down Payment + Final Payment',
                'down_payment_percentage': 50,
                'notes_template': '50% down payment required to begin work. Remaining 50% due upon project completion.',
                'footer_text': 'MABS Engineering LLC\nLicensed Professional Engineers\nState License #12345'
            },
            'milestone_invoice': {
                'name': 'Milestone Invoice',
                'description': 'Invoice with milestone-based payments',
                'payment_terms': 'Progress Payments',
                'payment_structure': 'Milestone Payments',
                'down_payment_percentage': 33,
                'notes_template': 'Payments tied to project milestones. See project schedule for details.',
                'footer_text': 'MABS Engineering LLC\nLicensed Professional Engineers\nState License #12345'
            }
        }
        
        for template_id, template_data in templates.items():
            self.add_template('invoices', template_data)


class TemplateDialog(QtWidgets.QDialog):
    """Dialog for selecting and applying templates"""
    
    def __init__(self, template_manager: TemplateManager, template_type: str, parent=None):
        super().__init__(parent)
        self.template_manager = template_manager
        self.template_type = template_type
        self.selected_template = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f"Select {self.template_type.title()} Template")
        self.setFixedSize(600, 500)
        self.setModal(True)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Header
        header = QtWidgets.QLabel(f"Choose a {self.template_type} template:")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50; margin-bottom: 10px;")
        layout.addWidget(header)
        
        # Template list
        self.template_list = QtWidgets.QListWidget()
        self.template_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 5px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
                border-radius: 4px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background: #3498db;
                color: white;
            }
        """)
        layout.addWidget(self.template_list)
        
        # Template details
        self.details_label = QtWidgets.QLabel("Select a template to view details")
        self.details_label.setStyleSheet("""
            QLabel {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 10px;
                font-size: 11px;
                color: #495057;
            }
        """)
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.apply_btn = QtWidgets.QPushButton("Apply Template")
        self.apply_btn.setStyleSheet("""
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
        self.apply_btn.setEnabled(False)
        
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
        
        button_layout.addWidget(self.apply_btn)
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Load templates
        self._load_templates()
        
        # Connect signals
        self.template_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.apply_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
    
    def _load_templates(self):
        """Load templates into the list"""
        templates = self.template_manager.get_templates(self.template_type)
        
        for template in templates:
            item = QtWidgets.QListWidgetItem(template['name'])
            item.setData(QtCore.Qt.UserRole, template)
            self.template_list.addItem(item)
    
    def _on_selection_changed(self):
        """Handle template selection"""
        current_item = self.template_list.currentItem()
        if current_item:
            template = current_item.data(QtCore.Qt.UserRole)
            self.selected_template = template
            self.apply_btn.setEnabled(True)
            
            # Show template details
            details = f"""
<strong>Name:</strong> {template['name']}
<strong>Description:</strong> {template.get('description', 'No description')}

"""
            
            if 'scope_of_work' in template:
                details += f"<strong>Scope:</strong>\n{template['scope_of_work']}\n\n"
            
            if 'services' in template:
                details += f"<strong>Services:</strong> {', '.join(template['services'])}\n\n"
            
            if 'estimated_duration' in template:
                details += f"<strong>Duration:</strong> {template['estimated_duration']}\n\n"
            
            if 'payment_terms' in template:
                details += f"<strong>Payment Terms:</strong> {template['payment_terms']}"
            
            self.details_label.setText(details)
        else:
            self.selected_template = None
            self.apply_btn.setEnabled(False)
            self.details_label.setText("Select a template to view details")
    
    def get_selected_template(self):
        """Get the selected template"""
        return self.selected_template
