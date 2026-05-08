"""
Client Intelligence System
Provides smart client suggestions based on historical data and patterns
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter
from PyQt5 import QtWidgets, QtCore, QtGui

class ClientIntelligence:
    """Intelligent client analysis and suggestion system"""
    
    def __init__(self):
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.client_history_file = self.data_dir / "client_history.json"
        self.client_history = self._load_client_history()
    
    def _load_client_history(self) -> Dict:
        """Load client history data"""
        if self.client_history_file.exists():
            try:
                with open(self.client_history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading client history: {e}")
        return {}
    
    def _save_client_history(self):
        """Save client history data"""
        try:
            with open(self.client_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.client_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving client history: {e}")
    
    def update_client_activity(self, client_name: str, activity_type: str, details: Dict):
        """Update client activity history"""
        if client_name not in self.client_history:
            self.client_history[client_name] = {
                'first_contact': datetime.now().isoformat(),
                'last_contact': datetime.now().isoformat(),
                'activities': [],
                'preferences': {},
                'stats': {
                    'total_quotes': 0,
                    'total_projects': 0,
                    'total_revenue': 0.0,
                    'conversion_rate': 0.0,
                    'avg_project_value': 0.0,
                    'payment_history': []
                }
            }
        
        # Add activity
        activity = {
            'type': activity_type,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
        self.client_history[client_name]['activities'].append(activity)
        self.client_history[client_name]['last_contact'] = datetime.now().isoformat()
        
        # Update stats
        self._update_client_stats(client_name)
        self._save_client_history()
    
    def _update_client_stats(self, client_name: str):
        """Update client statistics"""
        if client_name not in self.client_history:
            return
        
        client_data = self.client_history[client_name]
        activities = client_data.get('activities', [])
        
        # Count different activity types
        quotes = [a for a in activities if a['type'] == 'quote_created']
        projects = [a for a in activities if a['type'] == 'project_created']
        payments = [a for a in activities if a['type'] == 'payment_received']
        
        # Calculate stats
        total_quotes = len(quotes)
        total_projects = len(projects)
        total_revenue = sum(float(p.get('details', {}).get('amount', '0').replace('$', '').replace(',', '')) 
                           for p in payments)
        
        # Calculate conversion rate
        conversion_rate = (total_projects / total_quotes * 100) if total_quotes > 0 else 0.0
        
        # Calculate average project value
        avg_project_value = total_revenue / total_projects if total_projects > 0 else 0.0
        
        # Update stats
        client_data['stats'].update({
            'total_quotes': total_quotes,
            'total_projects': total_projects,
            'total_revenue': total_revenue,
            'conversion_rate': conversion_rate,
            'avg_project_value': avg_project_value,
            'payment_history': [p.get('details', {}) for p in payments]
        })
    
    def get_client_suggestions(self, client_name: str) -> List[Dict]:
        """Get intelligent suggestions for a client"""
        if client_name not in self.client_history:
            return []
        
        client_data = self.client_history[client_name]
        stats = client_data.get('stats', {})
        activities = client_data.get('activities', [])
        
        suggestions = []
        
        # Service suggestions based on history
        services_used = self._get_client_services(client_name)
        if services_used:
            suggestions.append({
                'type': 'service_suggestion',
                'title': 'Preferred Services',
                'description': f"This client typically requests: {', '.join(services_used[:3])}",
                'priority': 'high'
            })
        
        # Payment behavior suggestions
        avg_payment_time = self._get_avg_payment_time(client_name)
        if avg_payment_time > 30:
            suggestions.append({
                'type': 'payment_warning',
                'title': 'Payment Pattern',
                'description': f"Average payment time: {avg_payment_time} days. Consider stricter payment terms.",
                'priority': 'medium'
            })
        elif avg_payment_time < 15:
            suggestions.append({
                'type': 'payment_positive',
                'title': 'Excellent Payment History',
                'description': f"Average payment time: {avg_payment_time} days. Great client!",
                'priority': 'low'
            })
        
        # Value-based suggestions
        avg_value = stats.get('avg_project_value', 0)
        if avg_value > 20000:
            suggestions.append({
                'type': 'value_insight',
                'title': 'High-Value Client',
                'description': f"Average project value: ${avg_value:,.0f}. Consider priority service.",
                'priority': 'high'
            })
        
        # Frequency suggestions
        days_since_last_contact = self._get_days_since_last_contact(client_name)
        if days_since_last_contact > 90:
            suggestions.append({
                'type': 'follow_up',
                'title': 'Follow Up Needed',
                'description': f"Last contact was {days_since_last_contact} days ago. Time to check in!",
                'priority': 'medium'
            })
        
        # Conversion rate suggestions
        conversion_rate = stats.get('conversion_rate', 0)
        if conversion_rate > 80:
            suggestions.append({
                'type': 'conversion_positive',
                'title': 'High Conversion Rate',
                'description': f"Conversion rate: {conversion_rate:.1f}%. Very promising client!",
                'priority': 'low'
            })
        elif conversion_rate < 20 and stats.get('total_quotes', 0) > 3:
            suggestions.append({
                'type': 'conversion_warning',
                'title': 'Low Conversion Rate',
                'description': f"Conversion rate: {conversion_rate:.1f}%. Consider adjusting approach.",
                'priority': 'medium'
            })
        
        return suggestions
    
    def _get_client_services(self, client_name: str) -> List[str]:
        """Get services most used by client"""
        if client_name not in self.client_history:
            return []
        
        activities = self.client_history[client_name].get('activities', [])
        services = []
        
        for activity in activities:
            if activity['type'] in ['quote_created', 'project_created']:
                activity_services = activity.get('details', {}).get('services', [])
                services.extend(activity_services)
        
        # Return most common services
        service_counts = Counter(services)
        return [service for service, count in service_counts.most_common(5)]
    
    def _get_avg_payment_time(self, client_name: str) -> int:
        """Calculate average payment time in days"""
        if client_name not in self.client_history:
            return 30  # Default
        
        activities = self.client_history[client_name].get('activities', [])
        payment_times = []
        
        for activity in activities:
            if activity['type'] == 'payment_received':
                details = activity.get('details', {})
                if 'days_to_payment' in details:
                    payment_times.append(details['days_to_payment'])
        
        return sum(payment_times) // len(payment_times) if payment_times else 30
    
    def _get_days_since_last_contact(self, client_name: str) -> int:
        """Get days since last contact with client"""
        if client_name not in self.client_history:
            return 999
        
        last_contact_str = self.client_history[client_name].get('last_contact')
        if not last_contact_str:
            return 999
        
        try:
            last_contact = datetime.fromisoformat(last_contact_str)
            return (datetime.now() - last_contact).days
        except:
            return 999
    
    def get_similar_clients(self, client_name: str, limit: int = 3) -> List[Dict]:
        """Find clients with similar patterns"""
        if client_name not in self.client_history:
            return []
        
        target_client = self.client_history[client_name]
        target_services = set(self._get_client_services(client_name))
        target_avg_value = target_client.get('stats', {}).get('avg_project_value', 0)
        
        similar_clients = []
        
        for other_client, other_data in self.client_history.items():
            if other_client == client_name:
                continue
            
            other_services = set(self._get_client_services(other_client))
            other_avg_value = other_data.get('stats', {}).get('avg_project_value', 0)
            
            # Calculate similarity score
            service_similarity = len(target_services & other_services) / max(len(target_services | other_services), 1)
            value_similarity = 1 - abs(target_avg_value - other_avg_value) / max(target_avg_value + other_avg_value, 1)
            
            overall_similarity = (service_similarity * 0.7 + value_similarity * 0.3)
            
            if overall_similarity > 0.3:  # Threshold for similarity
                similar_clients.append({
                    'name': other_client,
                    'similarity_score': overall_similarity,
                    'shared_services': list(target_services & other_services),
                    'stats': other_data.get('stats', {})
                })
        
        # Sort by similarity and return top matches
        similar_clients.sort(key=lambda x: x['similarity_score'], reverse=True)
        return similar_clients[:limit]
    
    def get_client_recommendations(self, client_name: str) -> Dict:
        """Get comprehensive client recommendations"""
        if client_name not in self.client_history:
            return {
                'status': 'new_client',
                'recommendations': [
                    'This appears to be a new client',
                    'Start with standard pricing',
                    'Request 50% down payment for first project'
                ]
            }
        
        stats = self.client_history[client_name].get('stats', {})
        suggestions = self.get_client_suggestions(client_name)
        similar_clients = self.get_similar_clients(client_name)
        
        recommendations = {
            'status': 'existing_client',
            'stats': stats,
            'suggestions': suggestions,
            'similar_clients': similar_clients,
            'recommended_actions': self._generate_recommended_actions(client_name)
        }
        
        return recommendations
    
    def _generate_recommended_actions(self, client_name: str) -> List[str]:
        """Generate recommended actions for client"""
        actions = []
        stats = self.client_history[client_name].get('stats', {})
        
        # Based on conversion rate
        conversion_rate = stats.get('conversion_rate', 0)
        if conversion_rate > 80:
            actions.append("Offer priority service and expedited options")
        elif conversion_rate < 30:
            actions.append("Review pricing strategy and service offerings")
        
        # Based on payment history
        avg_payment_time = self._get_avg_payment_time(client_name)
        if avg_payment_time > 45:
            actions.append("Require advance payment for future projects")
        elif avg_payment_time < 15:
            actions.append("Offer flexible payment terms as reward")
        
        # Based on project value
        avg_value = stats.get('avg_project_value', 0)
        if avg_value > 50000:
            actions.append("Assign senior team members and priority support")
        
        # Based on activity frequency
        days_since_last = self._get_days_since_last_contact(client_name)
        if days_since_last > 60:
            actions.append("Schedule follow-up call or meeting")
        
        return actions


class ClientSuggestionWidget(QtWidgets.QWidget):
    """Widget for displaying client suggestions and intelligence"""
    
    def __init__(self, client_intelligence: ClientIntelligence, parent=None):
        super().__init__(parent)
        self.client_intelligence = client_intelligence
        self.current_client = None
        self.init_ui()
    
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Title
        self.title_label = QtWidgets.QLabel("🧠 Client Intelligence")
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 5px;
            }
        """)
        layout.addWidget(self.title_label)
        
        # Suggestions area
        self.suggestions_area = QtWidgets.QWidget()
        self.suggestions_layout = QtWidgets.QVBoxLayout(self.suggestions_area)
        self.suggestions_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.suggestions_area)
        
        # Initially hidden
        self.setVisible(False)
    
    def update_client(self, client_name: str):
        """Update widget with client information"""
        self.current_client = client_name
        
        if not client_name or client_name == "-- Select Client --":
            self.setVisible(False)
            return
        
        recommendations = self.client_intelligence.get_client_recommendations(client_name)
        
        # Clear existing suggestions
        for i in reversed(range(self.suggestions_layout.count())):
            child = self.suggestions_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        # Add new suggestions
        if recommendations['status'] == 'new_client':
            self._add_new_client_info()
        else:
            self._add_existing_client_info(recommendations)
        
        self.setVisible(True)
    
    def _add_new_client_info(self):
        """Add information for new clients"""
        info_label = QtWidgets.QLabel("🆕 New Client")
        info_label.setStyleSheet("""
            QLabel {
                background: #e3f2fd;
                color: #1976d2;
                padding: 8px;
                border-radius: 6px;
                font-weight: bold;
            }
        """)
        self.suggestions_layout.addWidget(info_label)
        
        tips = [
            "Start with standard pricing",
            "Request 50% down payment",
            "Establish clear communication expectations"
        ]
        
        for tip in tips:
            tip_label = QtWidgets.QLabel(f"• {tip}")
            tip_label.setStyleSheet("""
                QLabel {
                    color: #666;
                    font-size: 12px;
                    padding: 2px;
                }
            """)
            self.suggestions_layout.addWidget(tip_label)
    
    def _add_existing_client_info(self, recommendations):
        """Add information for existing clients"""
        stats = recommendations.get('stats', {})
        
        # Stats summary
        stats_text = f"📊 {stats.get('total_quotes', 0)} quotes, {stats.get('total_projects', 0)} projects"
        if stats.get('total_revenue', 0) > 0:
            stats_text += f", ${stats.get('total_revenue', 0):,.0f} revenue"
        
        stats_label = QtWidgets.QLabel(stats_text)
        stats_label.setStyleSheet("""
            QLabel {
                background: #f0f4f8;
                color: #2c3e50;
                padding: 8px;
                border-radius: 6px;
                font-weight: bold;
            }
        """)
        self.suggestions_layout.addWidget(stats_label)
        
        # Suggestions
        for suggestion in recommendations.get('suggestions', []):
            self._add_suggestion_widget(suggestion)
        
        # Similar clients
        similar_clients = recommendations.get('similar_clients', [])
        if similar_clients:
            similar_label = QtWidgets.QLabel("👥 Similar Clients:")
            similar_label.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    color: #2c3e50;
                    margin-top: 10px;
                }
            """)
            self.suggestions_layout.addWidget(similar_label)
            
            for client in similar_clients:
                client_text = f"• {client['name']} ({client['similarity_score']:.0%} match)"
                client_label = QtWidgets.QLabel(client_text)
                client_label.setStyleSheet("""
                    QLabel {
                        color: #666;
                        font-size: 12px;
                        padding: 2px;
                    }
                """)
                self.suggestions_layout.addWidget(client_label)
    
    def _add_suggestion_widget(self, suggestion: Dict):
        """Add a single suggestion widget"""
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
        
        priority = suggestion.get('priority', 'medium')
        bg_color = priority_colors.get(priority, '#f5f5f5')
        text_color = priority_text_colors.get(priority, '#666')
        
        suggestion_widget = QtWidgets.QWidget()
        suggestion_widget.setStyleSheet(f"""
            QWidget {{
                background: {bg_color};
                border-radius: 6px;
                padding: 8px;
                margin: 2px 0;
            }}
        """)
        
        suggestion_layout = QtWidgets.QVBoxLayout(suggestion_widget)
        suggestion_layout.setContentsMargins(8, 6, 8, 6)
        suggestion_layout.setSpacing(2)
        
        # Title
        title_label = QtWidgets.QLabel(suggestion.get('title', ''))
        title_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                color: {text_color};
                font-size: 12px;
            }}
        """)
        suggestion_layout.addWidget(title_label)
        
        # Description
        desc_label = QtWidgets.QLabel(suggestion.get('description', ''))
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 11px;
            }}
        """)
        desc_label.setWordWrap(True)
        suggestion_layout.addWidget(desc_label)
        
        self.suggestions_layout.addWidget(suggestion_widget)
