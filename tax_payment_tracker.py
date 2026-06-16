"""Tax Payment Tracker — stores tax entries in Firebase /tax_payments/ node,
completely separate from project payments."""
import threading
from datetime import datetime
from decimal import Decimal
from typing import List, Dict
from app_logger import get_logger

_log = get_logger(__name__)

_singleton = None
_singleton_lock = threading.Lock()


class TaxPayment:
    def __init__(self, tax_id: str = None, invoice_number: str = "",
                 project_number: str = "", amount: float = 0.0,
                 payment_date: str = "", payment_method: str = "",
                 notes: str = ""):
        self.tax_id = tax_id or f"TAX_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        self.invoice_number = invoice_number
        self.project_number = project_number
        self.amount = Decimal(str(amount))
        self.payment_date = payment_date or datetime.now().strftime("%Y-%m-%d")
        self.payment_method = payment_method
        self.notes = notes
        self.created_at = datetime.now().isoformat()
        self.balance_sheet_id = ""
        self.firebase_id = ""

    def to_dict(self) -> Dict:
        return {
            "tax_id": self.tax_id,
            "invoice_number": self.invoice_number,
            "project_number": self.project_number,
            "amount": float(self.amount),
            "payment_date": self.payment_date,
            "payment_method": self.payment_method,
            "notes": self.notes,
            "created_at": self.created_at,
            "balance_sheet_id": self.balance_sheet_id,
            "firebase_id": self.firebase_id,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TaxPayment":
        t = cls()
        t.tax_id = data.get("tax_id", t.tax_id)
        t.invoice_number = data.get("invoice_number", "")
        t.project_number = data.get("project_number", "")
        t.amount = Decimal(str(data.get("amount", 0)))
        t.payment_date = data.get("payment_date", "")
        t.payment_method = data.get("payment_method", "")
        t.notes = data.get("notes", "")
        t.created_at = data.get("created_at", t.created_at)
        t.balance_sheet_id = data.get("balance_sheet_id", "")
        t.firebase_id = data.get("firebase_id", "")
        return t


class TaxPaymentTracker:
    """Manages tax-only payment records, separate from project payments."""

    def __init__(self):
        self.tax_payments: List[TaxPayment] = []
        self._load_tax_payments()
        self._migrate_from_json()

    # ── Firebase storage ─────────────────────────────────────────────────────

    def _load_tax_payments(self):
        """Load all tax payments from Firebase /tax_payments/ node."""
        try:
            from firebase_admin import db
            data = db.reference('tax_payments').get() or {}
            if isinstance(data, dict):
                self.tax_payments = [
                    TaxPayment.from_dict(v) for v in data.values() if isinstance(v, dict)
                ]
            else:
                self.tax_payments = []
        except Exception as e:
            _log.error("Error loading tax_payments from Firebase: %s", e)
            self.tax_payments = []

    def _write_tax_to_firebase(self, tax: TaxPayment):
        """Write/overwrite a tax payment in Firebase /tax_payments/{tax_id}."""
        try:
            from firebase_admin import db
            db.reference('tax_payments').child(tax.tax_id).set(tax.to_dict())
            if not tax.firebase_id:
                tax.firebase_id = tax.tax_id
        except Exception as e:
            _log.warning("Could not write tax payment to Firebase: %s", e)

    def _update_tax_field_in_firebase(self, tax_id: str, fields: Dict):
        """Patch specific fields of a tax entry in Firebase."""
        try:
            from firebase_admin import db
            db.reference('tax_payments').child(tax_id).update(fields)
        except Exception as e:
            _log.warning("Could not patch tax in Firebase %s: %s", tax_id, e)

    def _migrate_from_json(self):
        """One-time: migrate data from tax_payments.json to Firebase then archive it."""
        try:
            import json
            from pathlib import Path
            import sys
            base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
            json_path = base / "data" / "tax_payments.json"
            if not json_path.exists():
                return
            with open(json_path, encoding="utf-8") as f:
                old_data = json.load(f)
            existing_ids = {t.tax_id for t in self.tax_payments}
            migrated = 0
            for item in old_data:
                if not isinstance(item, dict):
                    continue
                tid = item.get("tax_id", "")
                if tid and tid in existing_ids:
                    continue
                t = TaxPayment.from_dict(item)
                self.tax_payments.append(t)
                self._write_tax_to_firebase(t)
                existing_ids.add(t.tax_id)
                migrated += 1
            if migrated:
                _log.info("Migrated %d tax payments from JSON to Firebase", migrated)
            json_path.rename(json_path.with_suffix('.json.migrated'))
            _log.info("Archived tax_payments.json → tax_payments.json.migrated")
        except Exception as e:
            _log.warning("Tax JSON migration skipped: %s", e)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_invoice_taxes(self, invoice_number: str) -> List[TaxPayment]:
        """Return all tax entries for the given invoice number."""
        inv = (invoice_number or "").strip()
        return [t for t in self.tax_payments if (t.invoice_number or "").strip() == inv]

    def is_tax_paid_for_invoice(self, invoice_number: str, tax_amount: float) -> bool:
        """True if the full tax amount has been recorded for this invoice."""
        paid = sum(float(t.amount) for t in self.get_invoice_taxes(invoice_number))
        return paid >= tax_amount - 0.005

    # ── Mutations ─────────────────────────────────────────────────────────────

    def add_tax_payment(self, invoice_number: str, project_number: str,
                        amount: float, payment_date: str = "",
                        payment_method: str = "Invoice", notes: str = "") -> bool:
        """Record a tax payment and sync to Firebase."""
        try:
            tax = TaxPayment(
                invoice_number=invoice_number,
                project_number=project_number,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                notes=notes,
            )
            self.tax_payments.append(tax)

            def _bg(t=tax):
                # 1. Persist to Firebase /tax_payments/
                self._write_tax_to_firebase(t)
                # 2. Sync to balance sheet /revenue/
                try:
                    self._sync_to_balance_sheet(t)
                except Exception as _e:
                    _log.warning("Tax balance-sheet sync failed: %s", _e)

            threading.Thread(target=_bg, daemon=True).start()
            return True
        except Exception as e:
            _log.error("Error adding tax payment: %s", e)
            return False

    # ── Balance sheet sync ────────────────────────────────────────────────────

    def _sync_to_balance_sheet(self, tax: TaxPayment):
        """Write tax entry to Firebase /revenue/ so it appears in the balance sheet."""
        try:
            from balance_sheet_tab import BalanceSheetFirebaseManager
            pay_year = datetime.now().year
            for fmt in ("%Y-%m-%d", "%m-%d-%Y"):
                try:
                    pay_year = datetime.strptime(tax.payment_date, fmt).year
                    break
                except Exception:
                    pass
            revenue_data = {
                "source": f"Tax — Project {tax.project_number}",
                "amount": float(tax.amount),
                "date": tax.payment_date,
                "received_date": tax.payment_date,
                "status": "Paid",
                "year": pay_year,
                "description": f"Tax payment — Invoice {tax.invoice_number}",
                "payment_id": tax.tax_id,
                "project_number": tax.project_number,
                "invoice_number": tax.invoice_number,
                "payment_method": tax.payment_method,
                "category": "Tax Received",
                "is_payment": True,
                "is_tax": True,
            }
            if tax.balance_sheet_id:
                revenue_data["firebase_id"] = tax.balance_sheet_id
            BalanceSheetFirebaseManager.save_revenue(revenue_data)
            new_id = revenue_data.get("firebase_id", "")
            if new_id and not tax.balance_sheet_id:
                tax.balance_sheet_id = new_id
                self._update_tax_field_in_firebase(tax.tax_id, {'balance_sheet_id': new_id})
        except Exception as e:
            _log.warning("Could not sync tax to balance sheet: %s", e)


def get_tax_payment_tracker() -> TaxPaymentTracker:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = TaxPaymentTracker()
    return _singleton
