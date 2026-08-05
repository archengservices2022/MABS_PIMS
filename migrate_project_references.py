#!/usr/bin/env python3
"""
Second migration: Update project number references in invoices, payment logs, and revenue entries.
This updates all occurrences of project numbers in related documents.

Usage:
    python migrate_project_references.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def migrate_project_references():
    """Update project_number references in invoices, revenue entries, and payment logs."""
    try:
        from web_app.app import fb_get, fb_update

        pattern = r"^(MABS)-(\d{6})(\d{3})(.*)$"

        # Build mapping of old to new project numbers
        print("Building project number mapping...")
        projects = fb_get("/projects") or {}
        number_map = {}  # old_number -> new_number

        for project_id, project_data in projects.items():
            if not isinstance(project_data, dict):
                continue
            old_number = project_data.get("project_number", "")
            if not old_number:
                continue
            match = re.match(pattern, str(old_number))
            if not match:
                continue
            prefix, date, sequence, suffix = match.groups()
            sequence_int = int(sequence)
            if sequence_int > 99:
                continue
            new_sequence = sequence_int + 100
            new_number = f"{prefix}-{date}{new_sequence:03d}{suffix}"
            number_map[old_number] = new_number

        if not number_map:
            print("No project numbers to migrate.")
            return True

        print(f"Found {len(number_map)} project numbers to migrate")

        # Migrate invoices
        print("\nUpdating invoices...")
        invoices = fb_get("/invoices") or {}
        invoice_updates = 0

        for invoice_id, invoice_data in invoices.items():
            if not isinstance(invoice_data, dict):
                continue

            updated = False

            # Update invoice-level project_number
            inv_proj = invoice_data.get("project_number", "")
            if inv_proj in number_map:
                invoice_data["project_number"] = number_map[inv_proj]
                print(f"  Invoice {invoice_id}: project_number {inv_proj} → {number_map[inv_proj]}")
                updated = True

            # Update payment_log entries
            payment_log = invoice_data.get("payment_log", [])
            if isinstance(payment_log, list):
                for payment in payment_log:
                    if isinstance(payment, dict):
                        pay_proj = payment.get("project_number", "")
                        if pay_proj in number_map:
                            payment["project_number"] = number_map[pay_proj]
                            updated = True

            if updated:
                fb_update(f"/invoices/{invoice_id}", invoice_data)
                invoice_updates += 1

        # Migrate revenue entries
        print("\nUpdating revenue entries (balance sheet)...")
        revenue = fb_get("/balance_sheet_revenue") or {}
        revenue_updates = 0

        for rev_id, rev_data in revenue.items():
            if not isinstance(rev_data, dict):
                continue

            rev_proj = rev_data.get("project_number", "")
            if rev_proj in number_map:
                rev_data["project_number"] = number_map[rev_proj]
                print(f"  Revenue {rev_id}: project_number {rev_proj} → {number_map[rev_proj]}")
                fb_update(f"/balance_sheet_revenue/{rev_id}", rev_data)
                revenue_updates += 1

        print("\n" + "="*60)
        print(f"Reference migration complete!")
        print(f"  ✓ Updated invoices: {invoice_updates}")
        print(f"  ✓ Updated revenue entries: {revenue_updates}")
        print("="*60)

        return True

    except Exception as e:
        print(f"Error during migration: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = migrate_project_references()
    sys.exit(0 if success else 1)
