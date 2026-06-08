"""Payment Tracker Module - Handles partial payments for projects (Firebase-only storage)"""
import threading
import uuid as _uuid
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict
from app_logger import get_logger

_log = get_logger(__name__)

_DATE_FORMATS = ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y")


def _parse_pdate(s: str) -> datetime:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            pass
    return datetime.min


def _latest_payment_date_str(payments) -> str:
    """Return the date string of the most-recent payment, using proper date parsing."""
    best_dt = datetime.min
    best_str = ""
    for p in payments:
        d = getattr(p, "payment_date", None) or ""
        if not d:
            continue
        dt = _parse_pdate(d)
        if dt > best_dt:
            best_dt = dt
            best_str = d
    return best_str


class Payment:
    """Represents a single payment transaction"""

    def __init__(self, payment_id: str = None, project_number: str = "",
                 amount: float = 0.0, payment_date: str = "",
                 payment_method: str = "", notes: str = "",
                 invoice_number: str = "", payment_stage: str = ""):
        self.payment_id = payment_id or f"PAY_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:8]}"
        self.project_number = project_number
        self.invoice_number = invoice_number
        self.payment_stage = payment_stage
        self.amount = Decimal(str(amount))
        self.payment_date = payment_date or datetime.now().strftime("%Y-%m-%d")
        self.payment_method = payment_method
        self.notes = notes
        self.created_at = datetime.now().isoformat()
        self.balance_sheet_id = ""

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
        self.payments: List[Payment] = []
        self._load_payments()
        self._migrate_from_json()
        # Add real-time listener for payments
        self._setup_payment_listener()

    # ── Firebase storage ─────────────────────────────────────────────────────

    def _setup_payment_listener(self):
        """Set up real-time listener for payment changes"""
        try:
            from main import FirebaseManager
            FirebaseManager.add_realtime_listener('/payments', self._on_payments_updated, 'payments')
        except Exception:
            pass

    def _on_payments_updated(self, payments_data):
        """Called when payments are updated in Firebase"""
        try:
            self._load_payments()
        except Exception as e:
            _log.warning("Error updating payments in real-time: %s", e)

    def _load_payments(self):
        """Load all payments from Firebase /payments/ node."""
        try:
            from firebase_admin import db
            data = db.reference('payments').get() or {}
            if isinstance(data, dict):
                self.payments = [
                    Payment.from_dict(v) for v in data.values() if isinstance(v, dict)
                ]
            else:
                self.payments = []
        except Exception as e:
            _log.error("Error loading payments from Firebase: %s", e)
            self.payments = []

    def _write_payment_to_firebase(self, payment: Payment):
        """Write/overwrite a payment in Firebase /payments/{payment_id}."""
        try:
            from firebase_admin import db
            db.reference('payments').child(payment.payment_id).set(payment.to_dict())
        except Exception as e:
            _log.warning("Could not write payment to Firebase: %s", e)

    def _update_payment_field_in_firebase(self, payment_id: str, fields: Dict):
        """Patch specific fields of a payment entry in Firebase."""
        try:
            from firebase_admin import db
            db.reference('payments').child(payment_id).update(fields)
        except Exception as e:
            _log.warning("Could not patch payment in Firebase %s: %s", payment_id, e)

    def _delete_payment_from_firebase(self, payment_id: str):
        """Delete a payment from Firebase /payments/{payment_id}."""
        try:
            from firebase_admin import db
            db.reference('payments').child(payment_id).delete()
        except Exception as e:
            _log.warning("Could not delete payment from Firebase: %s", e)

    def _migrate_from_json(self):
        """One-time: migrate data from payments.json to Firebase then archive the file."""
        try:
            import json
            from pathlib import Path
            import sys
            base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
            json_path = base / "data" / "payments.json"
            if not json_path.exists():
                return
            with open(json_path, encoding="utf-8") as f:
                old_data = json.load(f)
            existing_ids = {p.payment_id for p in self.payments}
            migrated = 0
            for item in old_data:
                if not isinstance(item, dict):
                    continue
                pid = item.get("payment_id", "")
                if pid and pid in existing_ids:
                    continue
                p = Payment.from_dict(item)
                self.payments.append(p)
                self._write_payment_to_firebase(p)
                existing_ids.add(p.payment_id)
                migrated += 1
            if migrated:
                _log.info("Migrated %d payments from JSON to Firebase", migrated)
            json_path.rename(json_path.with_suffix('.json.migrated'))
            _log.info("Archived payments.json → payments.json.migrated")
        except Exception as e:
            _log.warning("JSON migration skipped: %s", e)

    # ── Balance sheet sync ────────────────────────────────────────────────────

    def _sync_payment_to_balance_sheet(self, payment: Payment) -> str:
        """Save or update a payment as a revenue entry in the balance sheet. Returns firebase_id or ''.
        Only syncs when the payment is linked to an invoice; bare project payments are not
        written to the balance sheet."""
        if not payment.invoice_number:
            return ''
        try:
            from balance_sheet_tab import BalanceSheetFirebaseManager
            desc = f"Payment received - Project {payment.project_number}"
            if payment.payment_stage:
                desc += f" ({payment.payment_stage})"
            pay_year = datetime.now().year
            try:
                pay_year = datetime.strptime(payment.payment_date, "%Y-%m-%d").year
            except Exception:
                try:
                    pay_year = datetime.strptime(payment.payment_date, "%m-%d-%Y").year
                except Exception:
                    pass
            revenue_data = {
                "source": f"Project {payment.project_number}",
                "amount": float(payment.amount),
                "date": payment.payment_date,
                "received_date": payment.payment_date,
                "status": "Paid",
                "year": pay_year,
                "description": desc,
                "payment_id": payment.payment_id,
                "project_number": payment.project_number,
                "invoice_number": payment.invoice_number,
                "payment_method": payment.payment_method,
                "category": "Payment Received",
                "is_payment": True,
            }
            if payment.balance_sheet_id:
                revenue_data["firebase_id"] = payment.balance_sheet_id
            else:
                try:
                    from firebase_admin import db as _fdb
                    all_rev = _fdb.reference('revenue').get() or {}
                    for _rid, _rev in all_rev.items():
                        if (isinstance(_rev, dict)
                                and _rev.get('payment_id') == payment.payment_id
                                and _rev.get('is_payment')):
                            revenue_data["firebase_id"] = _rid
                            break
                except Exception:
                    pass
            BalanceSheetFirebaseManager.save_revenue(revenue_data)
            return revenue_data.get("firebase_id", "")
        except Exception as e:
            _log.warning("Could not sync payment to balance sheet: %s", e)
            return ""

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_payment(self, project_number: str, amount: float,
                    payment_date: str = "", payment_method: str = "",
                    notes: str = "", invoice_number: str = "",
                    payment_stage: str = "",
                    sync_balance_sheet: bool = True) -> bool:
        """Add a new payment for a project.
        sync_balance_sheet=False when the caller already handles the balance sheet entry."""
        try:
            payment = Payment(
                project_number=project_number,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                notes=notes,
                invoice_number=invoice_number,
                payment_stage=payment_stage,
            )
            self.payments.append(payment)

            inv_num = invoice_number
            proj_num = project_number
            do_sync = sync_balance_sheet

            def _bg(p=payment, inv=inv_num, proj=proj_num, sync=do_sync):
                # 1. Persist to Firebase /payments/
                self._write_payment_to_firebase(p)
                # 2. Sync to balance sheet /revenue/
                if sync:
                    try:
                        bs_id = self._sync_payment_to_balance_sheet(p)
                        if bs_id and not p.balance_sheet_id:
                            p.balance_sheet_id = bs_id
                            self._update_payment_field_in_firebase(
                                p.payment_id, {'balance_sheet_id': bs_id}
                            )
                    except Exception as _e:
                        _log.warning("Background balance-sheet sync failed: %s", _e)
                # 3. Refresh annual summary
                self._trigger_annual_summary_refresh()
                # 4. Recompute invoice status
                if inv:
                    try:
                        self._recompute_invoice_status(inv, proj)
                    except Exception as _e:
                        _log.warning("Background recompute failed: %s", _e)

            threading.Thread(target=_bg, daemon=True).start()
            return True
        except Exception as e:
            _log.error("Error adding payment: %s", e)
            return False

    def get_project_payments(self, project_number: str) -> List[Payment]:
        """Get all payments for a specific project"""
        return [p for p in self.payments if p.project_number == project_number]

    def get_payment_summary(self, project_number: str, total_amount: float) -> Dict:
        """Get payment summary for a project"""
        project_payments = self.get_project_payments(project_number)
        project_payments = [p for p in project_payments
                            if (p.payment_stage or "").strip().lower() != "tax"]
        total_paid = sum(p.amount for p in project_payments)
        remaining = Decimal(str(total_amount)) - total_paid

        return {
            "total_amount": Decimal(str(total_amount)),
            "total_paid": total_paid,
            "remaining": remaining,
            "payment_count": len(project_payments),
            "payments": project_payments,
            "payment_percentage": float(total_paid / Decimal(str(total_amount)) * 100) if total_amount > 0 else 0,
        }

    def delete_payment(self, payment_id: str) -> bool:
        """Delete a payment by ID.

        Also removes any linked balance-sheet revenue entry and recomputes the
        invoice status so invoice history reflects the deletion."""
        try:
            deleted_payment = next(
                (p for p in self.payments if p.payment_id == payment_id), None
            )
            invoice_number_affected = deleted_payment.invoice_number if deleted_payment else ""
            project_number_affected = deleted_payment.project_number if deleted_payment else ""

            self.payments = [p for p in self.payments if p.payment_id != payment_id]

            _dp = deleted_payment
            _inv = invoice_number_affected
            _pn = project_number_affected

            def _bg_delete(dp=_dp, inv=_inv, pn=_pn):
                # 1. Delete from Firebase /payments/
                self._delete_payment_from_firebase(payment_id)
                # 2. Remove linked balance-sheet revenue entry
                if dp:
                    try:
                        from balance_sheet_tab import BalanceSheetFirebaseManager
                        if dp.balance_sheet_id:
                            BalanceSheetFirebaseManager.delete_entry(
                                'revenue', dp.balance_sheet_id
                            )
                        else:
                            self._delete_bs_entry_by_payment_id(dp.payment_id)
                    except Exception as _e:
                        _log.warning("Could not delete balance sheet entry: %s", _e)
                # 3. Refresh annual summary
                self._trigger_annual_summary_refresh()
                # 4. Recompute invoice status
                if inv:
                    try:
                        self._recompute_invoice_status(inv, pn)
                    except Exception as _e:
                        _log.warning("Background recompute (delete) failed: %s", _e)

            threading.Thread(target=_bg_delete, daemon=True).start()
            return True
        except Exception as e:
            _log.error("Error deleting payment: %s", e)
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

                    _p = payment

                    def _bg_update(p=_p):
                        # 1. Persist updated payment to Firebase /payments/
                        self._write_payment_to_firebase(p)
                        # 2. Sync to balance sheet /revenue/
                        try:
                            bs_id = self._sync_payment_to_balance_sheet(p)
                            if bs_id and not p.balance_sheet_id:
                                p.balance_sheet_id = bs_id
                                self._update_payment_field_in_firebase(
                                    p.payment_id, {'balance_sheet_id': bs_id}
                                )
                            final_id = p.balance_sheet_id or bs_id
                            if final_id and p.payment_id:
                                self._delete_orphan_bs_entries(p.payment_id, keep_id=final_id)
                            # 3. Refresh annual summary
                            self._trigger_annual_summary_refresh()
                        except Exception as _e:
                            _log.warning("Background BS update failed: %s", _e)
                        # 4. Recompute invoice status
                        if p.invoice_number:
                            try:
                                self._recompute_invoice_status(
                                    p.invoice_number, p.project_number)
                            except Exception as _e:
                                _log.warning("Background recompute (update) failed: %s", _e)

                    threading.Thread(target=_bg_update, daemon=True).start()
                    return True
            return False
        except Exception as e:
            _log.error("Error updating payment: %s", e)
            return False

    # ── Status / invoice helpers ──────────────────────────────────────────────

    def _recompute_invoice_status(self, invoice_number: str, project_number: str):
        """After a payment change, recalculate remaining paid amount for the
        invoice and update its status to Unpaid / Partially Paid / Paid."""
        try:
            from main import FirebaseManager
            raw_invoices = FirebaseManager.load_invoices() or []
            target = next(
                (inv for inv in raw_invoices
                 if (inv.get("meta") or {}).get("invoice_number") == invoice_number),
                None,
            )
            if not target:
                return

            invoice_total = 0.0
            for item in target.get("items", []):
                try:
                    invoice_total += float(
                        item.get("payment_due") or item.get("total") or item.get("unit_price") or 0
                    )
                except (TypeError, ValueError):
                    pass
            try:
                tax_amount = float((target.get("meta") or {}).get("tax_amount") or 0)
                invoice_total += tax_amount
            except (TypeError, ValueError):
                pass

            total_paid = sum(
                float(p.amount)
                for p in self.payments
                if p.invoice_number == invoice_number
            )
            try:
                from tax_payment_tracker import get_tax_payment_tracker as _get_tt
                _tt = _get_tt()
                total_paid += sum(float(t.amount) for t in _tt.get_invoice_taxes(invoice_number))
            except Exception:
                pass

            if invoice_total <= 0:
                new_status = "Unpaid"
            elif total_paid >= invoice_total - 0.005:
                new_status = "Paid"
            elif total_paid > 0:
                new_status = "Partially Paid"
            else:
                new_status = "Unpaid"

            # Overdue: no payments + due date has passed
            if new_status == "Unpaid":
                due_str = (target.get("meta") or {}).get("due_date") or ""
                if due_str:
                    for _dfmt in _DATE_FORMATS:
                        try:
                            if datetime.strptime(due_str, _dfmt).date() < date.today():
                                new_status = "Overdue"
                            break
                        except (ValueError, TypeError):
                            pass

            FirebaseManager.update_invoice_status(invoice_number, new_status)
            _log.info(
                "Recomputed invoice %s status → %s (paid=%.2f, total=%.2f)",
                invoice_number, new_status, total_paid, invoice_total,
            )

            # Single atomic write to /revenue/ covering status + received_date together
            # so the real-time listener never sees a half-updated state.
            new_rd = 'N/A'
            if new_status in ("Unpaid", "Overdue"):
                self._reset_received_date(invoice_number, new_status)
            elif new_status in ("Partially Paid", "Paid"):
                remaining = [p for p in self.payments if p.invoice_number == invoice_number]
                if remaining:
                    latest_date = _latest_payment_date_str(remaining)
                else:
                    # No project payments — check tax payments for the received date
                    latest_date = ''
                    try:
                        from tax_payment_tracker import get_tax_payment_tracker as _get_tt2
                        tax_pmts = _get_tt2().get_invoice_taxes(invoice_number)
                        if tax_pmts:
                            latest_date = _latest_payment_date_str(tax_pmts)
                    except Exception:
                        pass
                new_rd = latest_date or 'N/A'
                self._update_received_date_to_latest(
                    invoice_number, new_rd, total_paid, new_status
                )

            try:
                import invoice_history_tab as _iht
                sig = _iht._invoice_status_signaler
                if sig is not None:
                    sig.invoice_status_changed.emit(invoice_number, new_status, new_rd)
            except Exception as _e:
                _log.warning("Could not notify invoice history of status change: %s", _e)

        except Exception as e:
            _log.warning("Error recomputing invoice status: %s", e)

    def _reset_received_date(self, invoice_number: str, status: str = "Unpaid"):
        """Reset received_date to N/A in invoice meta and balance-sheet revenue when
        all payments for an invoice are deleted."""
        try:
            from firebase_admin import db as _db
            from datetime import timezone as _tz

            now_iso = datetime.now(_tz.utc).isoformat()

            inv_ref = _db.reference('invoices')
            all_inv = inv_ref.get() or {}
            for inv_id, inv_data in all_inv.items():
                if not isinstance(inv_data, dict):
                    continue
                meta = inv_data.get('meta') or {}
                if meta.get('invoice_number') == invoice_number:
                    _db.reference(f'invoices/{inv_id}/meta').update({
                        'received_date': 'N/A',
                        'updated_at': now_iso,
                    })
                    _log.info("Reset received_date to N/A for invoice %s", invoice_number)
                    break

            rev_ref = _db.reference('revenue')
            all_rev = rev_ref.get() or {}
            for rev_id, rev in all_rev.items():
                if not isinstance(rev, dict):
                    continue
                if rev.get('is_payment'):
                    continue
                rev_inv = (rev.get('invoice_number') or '').strip()
                if rev_inv != (invoice_number or '').strip():
                    continue
                rev_ref.child(rev_id).update({
                    'received_date': 'N/A',
                    'down_payment_received_date': 'N/A',
                    'status': status,
                    'paid_amount': '0.00',
                    'has_payment_entries': False,
                    'updated_at': now_iso,
                })
                _log.info("Reset revenue entry for invoice %s to Unpaid/N/A", invoice_number)
                break

        except Exception as e:
            _log.warning("Error resetting received_date for %s: %s", invoice_number, e)

    def _update_received_date_to_latest(self, invoice_number: str, latest_date: str,
                                         total_paid: float, status: str = ""):
        """Set received_date (and optionally status) atomically in invoice meta and
        the balance-sheet revenue node — single write so the real-time listener
        always sees a consistent state."""
        try:
            from firebase_admin import db as _db
            from datetime import timezone as _tz

            now_iso = datetime.now(_tz.utc).isoformat()

            inv_ref = _db.reference('invoices')
            all_inv = inv_ref.get() or {}
            for inv_id, inv_data in all_inv.items():
                if not isinstance(inv_data, dict):
                    continue
                meta = inv_data.get('meta') or {}
                if meta.get('invoice_number') == invoice_number:
                    _db.reference(f'invoices/{inv_id}/meta').update({
                        'received_date': latest_date,
                        'updated_at': now_iso,
                    })
                    _log.info(
                        "Updated received_date to %s for invoice %s",
                        latest_date, invoice_number,
                    )
                    break

            rev_ref = _db.reference('revenue')
            all_rev = rev_ref.get() or {}
            for rev_id, rev in all_rev.items():
                if not isinstance(rev, dict):
                    continue
                # Skip is_payment entries (those are per-payment rows, not per-invoice)
                if rev.get('is_payment'):
                    continue
                rev_inv = (rev.get('invoice_number') or '').strip()
                if rev_inv != (invoice_number or '').strip():
                    continue
                update_payload = {
                    'received_date': latest_date,
                    'down_payment_received_date': latest_date,
                    'paid_amount': f'{total_paid:.2f}',
                    'updated_at': now_iso,
                }
                if status:
                    update_payload['status'] = status
                rev_ref.child(rev_id).update(update_payload)
                _log.info(
                    "Updated revenue entry for invoice %s: status=%s received_date=%s paid=%.2f",
                    invoice_number, status or '(unchanged)', latest_date, total_paid,
                )
                break

        except Exception as e:
            _log.warning("Error updating received_date to latest for %s: %s", invoice_number, e)

    def _delete_bs_entry_by_payment_id(self, payment_id: str):
        """Fallback: search Firebase revenue node for an is_payment entry whose
        payment_id field matches and delete it."""
        try:
            from firebase_admin import db as _db
            rev_ref = _db.reference('revenue')
            all_rev = rev_ref.get() or {}
            for rev_id, rev in all_rev.items():
                if isinstance(rev, dict) and rev.get('payment_id') == payment_id:
                    rev_ref.child(rev_id).delete()
                    _log.info("Deleted orphan bs entry %s (matched payment_id)", rev_id)
                    return
        except Exception as e:
            _log.warning("Error deleting bs entry by payment_id %s: %s", payment_id, e)

    def _delete_orphan_bs_entries(self, payment_id: str, keep_id: str):
        """Delete every is_payment /revenue/ entry whose payment_id matches but whose
        Firebase key is NOT keep_id. Cleans up stale duplicates from race conditions."""
        try:
            from firebase_admin import db as _fdb
            from balance_sheet_tab import BalanceSheetFirebaseManager
            all_rev = _fdb.reference('revenue').get() or {}
            for rev_id, rev in all_rev.items():
                if (isinstance(rev, dict)
                        and rev.get('payment_id') == payment_id
                        and rev.get('is_payment')
                        and rev_id != keep_id):
                    BalanceSheetFirebaseManager.delete_entry('revenue', rev_id)
                    _log.info("Deleted orphan bs entry %s (payment_id=%s)", rev_id, payment_id)
        except Exception as e:
            _log.warning("Error deleting orphan bs entries for %s: %s", payment_id, e)

    @staticmethod
    def _trigger_annual_summary_refresh():
        """Schedule annual summary refresh on the GUI thread via pyqtSignal."""
        try:
            import balance_sheet_tab as _bst
            sig = _bst._annual_refresh_signaler
            if sig is not None:
                sig.do_refresh.emit()
        except Exception as _e:
            _log.warning("Could not trigger annual summary refresh: %s", _e)

    # ── Summaries ─────────────────────────────────────────────────────────────

    def get_all_payments_summary(self) -> Dict:
        """Get summary of all payments across all projects"""
        if not self.payments:
            return {
                "total_payments": 0,
                "total_amount_paid": 0.0,
                "projects_with_payments": 0,
                "recent_payments": [],
            }

        total_amount = sum(p.amount for p in self.payments)
        unique_projects = len(set(p.project_number for p in self.payments))

        recent_payments = sorted(self.payments,
                                 key=lambda p: p.payment_date,
                                 reverse=True)[:10]

        return {
            "total_payments": len(self.payments),
            "total_amount_paid": float(total_amount),
            "projects_with_payments": unique_projects,
            "recent_payments": [p.to_dict() for p in recent_payments],
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

            if due_date and summary["remaining"] > 0:
                try:
                    due_dt = datetime.strptime(due_date, "%Y-%m-%d").date()
                    if due_dt < date.today():
                        overdue_projects.append({
                            "project": project,
                            "payment_summary": summary,
                            "days_overdue": (date.today() - due_dt).days,
                        })
                except ValueError:
                    pass
            elif summary["payment_percentage"] < 100:
                overdue_projects.append({
                    "project": project,
                    "payment_summary": summary,
                    "days_overdue": 0,
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
