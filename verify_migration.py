#!/usr/bin/env python3
"""
Verify that the migration was complete and check for any old project number references.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def verify_migration():
    """Check for any remaining old project number references."""
    try:
        from web_app.app import fb_get

        pattern = r"^(MABS)-(\d{6})(\d{3})(.*)$"

        print("="*60)
        print("Migration Verification Report")
        print("="*60)

        # Check projects
        print("\n1. Checking PROJECTS collection...")
        projects = fb_get("/projects") or {}
        old_seqs = []
        new_seqs = []

        for project_id, project_data in projects.items():
            if not isinstance(project_data, dict):
                continue
            proj_num = project_data.get("project_number", "")
            if not proj_num:
                continue
            match = re.match(pattern, str(proj_num))
            if not match:
                continue
            prefix, date, sequence, suffix = match.groups()
            seq_int = int(sequence)
            if seq_int < 100:
                old_seqs.append((proj_num, project_id))
            elif seq_int >= 100:
                new_seqs.append(proj_num)

        print(f"   New sequence (101+): {len(new_seqs)} projects")
        print(f"   Old sequence (001-099): {len(old_seqs)} projects")
        if old_seqs:
            print("   ⚠ WARNING: Found old sequences!")
            for pnum, pid in old_seqs[:5]:
                print(f"     - {pnum} (ID: {pid})")

        # Check invoices for project_number references
        print("\n2. Checking INVOICES for project_number references...")
        invoices = fb_get("/invoices") or {}
        inv_old = []
        inv_new = []

        for inv_id, inv_data in invoices.items():
            if not isinstance(inv_data, dict):
                continue
            inv_proj = inv_data.get("project_number", "")
            if not inv_proj:
                continue
            match = re.match(pattern, str(inv_proj))
            if not match:
                continue
            seq_int = int(match.group(3))
            if seq_int < 100:
                inv_old.append((inv_proj, inv_id))
            elif seq_int >= 100:
                inv_new.append(inv_proj)

            # Check payment_log
            payment_log = inv_data.get("payment_log", [])
            if isinstance(payment_log, list):
                for payment in payment_log:
                    if isinstance(payment, dict):
                        pay_proj = payment.get("project_number", "")
                        if pay_proj and re.match(pattern, str(pay_proj)):
                            seq_int = int(re.match(pattern, str(pay_proj)).group(3))
                            if seq_int < 100:
                                inv_old.append((pay_proj, f"{inv_id} (payment_log)"))

        print(f"   References to new sequences (101+): {len(inv_new)}")
        print(f"   References to old sequences (001-099): {len(inv_old)}")
        if inv_old:
            print("   ⚠ WARNING: Found old references in invoices!")
            for pnum, iid in inv_old[:5]:
                print(f"     - {pnum} (Invoice ID: {iid})")

        # Check revenue entries
        print("\n3. Checking REVENUE entries for project_number references...")
        revenue = fb_get("/balance_sheet_revenue") or {}
        rev_old = []
        rev_new = []

        for rev_id, rev_data in revenue.items():
            if not isinstance(rev_data, dict):
                continue
            rev_proj = rev_data.get("project_number", "")
            if not rev_proj:
                continue
            match = re.match(pattern, str(rev_proj))
            if not match:
                continue
            seq_int = int(match.group(3))
            if seq_int < 100:
                rev_old.append((rev_proj, rev_id))
            elif seq_int >= 100:
                rev_new.append(rev_proj)

        print(f"   References to new sequences (101+): {len(rev_new)}")
        print(f"   References to old sequences (001-099): {len(rev_old)}")
        if rev_old:
            print("   ⚠ WARNING: Found old references in revenue entries!")
            for pnum, rid in rev_old[:5]:
                print(f"     - {pnum} (Revenue ID: {rid})")

        print("\n" + "="*60)
        if not old_seqs and not inv_old and not rev_old:
            print("✓ Migration complete and verified!")
        else:
            print("⚠ Found old project number references that need updating.")
        print("="*60)

        return not (old_seqs or inv_old or rev_old)

    except Exception as e:
        print(f"Error during verification: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = verify_migration()
    sys.exit(0 if success else 1)
