"""Payment Tracker Module - Handles partial payments for projects"""
import json
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from app_logger import get_logger

_log = get_logger(__name__)


class Payment:
    """Represents a single payment transaction"""
    
    def __init__(self, payment_id: str = None, project_number: str = "", 
                 amount: float = 0.0, payment_date: str = "", 
                 payment_method: str = "", notes: str = "",
                 invoice_number: str = "", payment_stage: str = ""):
        self.payment_id = payment_id or f"PAY_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.project_number = project_number
        self.invoice_number = invoice_number
        self.payment_stage = payment_stage
        self.amount = Decimal(str(amount))
        self.payment_date = payment_date or datetime.now().strftime("%Y-%m-%d")
        self.payment_method = payment_method  # Cash, Check, Bank Transfer, etc.
        self.notes = notes
        self.created_at = datetime.now().isoformat()
        self.balance_sheet_id = ""  # Firebase ID of linked balance sheet revenue entry

    def to_dict(self) -> Dict:
        return {
            "payment_id": self.payment_id,
            "project_number": self.project_number,
            "invoice_number": self.invoice_number,
            "payment_stage": self.payment_stage,
            "amount": float(self.amount),
            "payment_date": self.payment_date,
            "payment_method": self.payment_method,
            "notes": self.notes,
            "created_at": self.created_at,
            "balance_sheet_id": self.balance_sheet_id,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Payment':
        payment = cls()
        payment.payment_id = data.get("payment_id", payment.payment_id)
        payment.project_number = data.get("project_number", "")
        payment.invoice_number = data.get("invoice_number", "")
        payment.payment_stage = data.get("payment_stage", "")
        payment.amount = Decimal(str(data.get("amount", 0)))
        payment.payment_date = data.get("payment_date", "")
        payment.payment_method = data.get("payment_method", "")
        payment.notes = data.get("notes", "")
        payment.created_at = data.get("created_at", payment.created_at)
        payment.balance_sheet_id = data.get("balance_sheet_id", "")
        return payment


class ProjectPaymentTracker:
    """Manages payment tracking for projects"""
    
    def __init__(self):
        self.payments_file = self._resolve_payments_path()
        self.payments: List[Payment] = []
        self._load_payments()

    @staticmethod
    def _resolve_payments_path() -> Path:
        """Return a stable path for payments.json that survives PyInstaller builds."""
        import sys
        if getattr(sys, "frozen", False):
            # Running as a PyInstaller bundle — use the directory of the executable
            base = Path(sys.executable).parent
        else:
            # Normal Python run — use the source directory
            base = Path(__file__).parent
        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "payments.json"
    
    def _load_payments(self):
        """Load all payments from file"""
        try:
            if self.payments_file.exists():
                with open(self.payments_file, encoding="utf-8") as f:
                    data = json.load(f)
                self.payments = [Payment.from_dict(p) for p in data if isinstance(p, dict)]
            else:
                self.payments = []
        except Exception as e:
            _log.error(f"Error loading payments: {e}")
            self.payments = []
    
    def _save_payments(self) -> bool:
        """Save all payments to file"""
        try:
            self.payments_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.payments_file, "w", encoding="utf-8") as f:
                json.dump([p.to_dict() for p in self.payments], f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            _log.error(f"Error saving payments: {e}")
            return False
    
    def _sync_payment_to_balance_sheet(self, payment: Payment) -> str:
        """Save or update a payment as a revenue entry in the balance sheet. Returns firebase_id or ''."""
        try:
            from balance_sheet_tab import BalanceSheetFirebaseManager
            desc = f"Payment received - Project {payment.project_number}"
            if payment.payment_stage:
                desc += f" ({payment.payment_stage})"
            revenue_data = {
                "source": f"Project {payment.project_number}",
                "amount": float(payment.amount),
                "date": payment.payment_date,
                "description": desc,
                "payment_id": payment.payment_id,
                "project_number": payment.project_number,
                "payment_method": payment.payment_method,
                "category": "Payment Received",
                "is_payment": True,
            }
            if payment.balance_sheet_id:
                revenue_data["firebase_id"] = payment.balance_sheet_id
            BalanceSheetFirebaseManager.save_revenue(revenue_data)
            return revenue_data.get("firebase_id", "")
        except Exception as e:
            _log.warning("Could not sync payment to balance sheet: %s", e)
            return ""

    def add_payment(self, project_number: str, amount: float,
                   payment_date: str = "", payment_method: str = "",
                   notes: str = "", invoice_number: str = "",
                   payment_stage: str = "",
                   sync_balance_sheet: bool = True) -> bool:
        """Add a new payment for a project.
        sync_balance_sheet=False when the caller (e.g. invoice auto-record) already
        handles the balance sheet entry, preventing duplicate revenue rows."""
        try:
            payment = Payment(
                project_number=project_number,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                notes=notes,
                invoice_number=invoice_number,
                payment_stage=payment_stage
            )
            self.payments.append(payment)
            success = self._save_payments()
            if success and sync_balance_sheet:
                bs_id = self._sync_payment_to_balance_sheet(payment)
                if bs_id:
                    payment.balance_sheet_id = bs_id
                    self._save_payments()
            return success
        except Exception as e:
            _log.error(f"Error adding payment: {e}")
            return False
    
    def get_project_payments(self, project_number: str) -> List[Payment]:
        """Get all payments for a specific project"""
        return [p for p in self.payments if p.project_number == project_number]
    
    def get_payment_summary(self, project_number: str, total_amount: float) -> Dict:
        """Get payment summary for a project"""
        project_payments = self.get_project_payments(project_number)
        total_paid = sum(p.amount for p in project_payments)
        remaining = Decimal(str(total_amount)) - total_paid
        
        return {
            "total_amount": Decimal(str(total_amount)),
            "total_paid": total_paid,
            "remaining": remaining,
            "payment_count": len(project_payments),
            "payments": project_payments,
            "payment_percentage": float(total_paid / Decimal(str(total_amount)) * 100) if total_amount > 0 else 0
        }
    
    def delete_payment(self, payment_id: str) -> bool:
        """Delete a payment by ID"""
        try:
            for payment in self.payments:
                if payment.payment_id == payment_id and payment.balance_sheet_id:
                    try:
                        from balance_sheet_tab import BalanceSheetFirebaseManager
                        BalanceSheetFirebaseManager.delete_entry('revenue', payment.balance_sheet_id)
                    except Exception as e:
                        _log.warning("Could not delete balance sheet entry: %s", e)
            self.payments = [p for p in self.payments if p.payment_id != payment_id]
            return self._save_payments()
        except Exception as e:
            _log.error(f"Error deleting payment: {e}")
            return False

    def update_payment(self, payment_id: str, **kwargs) -> bool:
        """Update payment details"""
        try:
            for payment in self.payments:
                if payment.payment_id == payment_id:
                    for key, value in kwargs.items():
                        if hasattr(payment, key):
                            if key == "amount":
                                setattr(payment, key, Decimal(str(value)))
                            else:
                                setattr(payment, key, value)
                    payment.created_at = datetime.now().isoformat()
                    success = self._save_payments()
                    if success:
                        self._sync_payment_to_balance_sheet(payment)
                    return success
            return False
        except Exception as e:
            _log.error(f"Error updating payment: {e}")
            return False
    
    def get_all_payments_summary(self) -> Dict:
        """Get summary of all payments across all projects"""
        if not self.payments:
            return {
                "total_payments": 0,
                "total_amount_paid": 0.0,
                "projects_with_payments": 0,
                "recent_payments": []
            }
        
        total_amount = sum(p.amount for p in self.payments)
        unique_projects = len(set(p.project_number for p in self.payments))
        
        # Get recent payments (last 10)
        recent_payments = sorted(self.payments, 
                               key=lambda p: p.payment_date, 
                               reverse=True)[:10]
        
        return {
            "total_payments": len(self.payments),
            "total_amount_paid": float(total_amount),
            "projects_with_payments": unique_projects,
            "recent_payments": [p.to_dict() for p in recent_payments]
        }
    
    def get_overdue_projects(self, projects_data: List[Dict]) -> List[Dict]:
        """Get projects with overdue or incomplete payments"""
        overdue_projects = []
        
        for project in projects_data:
            project_number = project.get("project_number", "")
            total_amount = float(project.get("project_amount", 0))
            due_date = project.get("due_date", "")
            
            if not project_number or total_amount <= 0:
                continue
            
            summary = self.get_payment_summary(project_number, total_amount)
            
            # Check if project is overdue (due date passed and not fully paid)
            if due_date and summary["remaining"] > 0:
                try:
                    due_dt = datetime.strptime(due_date, "%Y-%m-%d").date()
                    if due_dt < date.today():
                        overdue_projects.append({
                            "project": project,
                            "payment_summary": summary,
                            "days_overdue": (date.today() - due_dt).days
                        })
                except ValueError:
                    pass
            
            # Also include projects with significant remaining balance
            elif summary["payment_percentage"] < 100:
                overdue_projects.append({
                    "project": project,
                    "payment_summary": summary,
                    "days_overdue": 0
                })
        
        return overdue_projects


# Global payment tracker instance
_payment_tracker = None

def get_payment_tracker() -> ProjectPaymentTracker:
    """Get the global payment tracker instance"""
    global _payment_tracker
    if _payment_tracker is None:
        _payment_tracker = ProjectPaymentTracker()
    return _payment_tracker
