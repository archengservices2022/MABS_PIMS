import sys
sys.path.insert(0, 'web_app')
from app import fb_get, _safe_float

# Manually trace through _update_project_stage_payment_status for stage 2
invoice_id = "-Ov1pVRTqvlWB3zP6WQr"
inv_data = fb_get(f"/invoices/{invoice_id}") or {}
meta = inv_data.get("meta", {}) or {}

print("=== Invoice Data ===")
print(f"Invoice Number: {meta.get('invoice_number')}")
print(f"Project: {meta.get('project_number')}")
print(f"Stage Index: {meta.get('payment_stage_index')}")
print(f"Linked Projects: {meta.get('linked_projects')}")

project_number = "MABS-202606-003"
stage_index = 2

print(f"\n=== Checking for Stage {stage_index} ===")
all_invoices = fb_get("/invoices") or {}

project_paid = 0
if isinstance(all_invoices, dict):
    for inv_id, inv in all_invoices.items():
        if not isinstance(inv, dict):
            continue
        inv_meta = inv.get("meta", {}) or {}

        # Check condition 1: single-project
        if (inv_meta.get("project_number") == project_number and
            inv_meta.get("payment_stage_index") == stage_index):
            print(f"  Found via single-project match: {inv_meta.get('invoice_number')}")

            inv_payment_log = inv.get("payment_log", [])
            if isinstance(inv_payment_log, list):
                amount = sum(_safe_float(p.get("amount", 0)) for p in inv_payment_log)
                print(f"    Payment log: ${amount}")
                project_paid += amount
        else:
            if inv_meta.get("invoice_number") == "INV-202606-017":
                print(f"  NOT MATCHED: {inv_meta.get('invoice_number')}")
                print(f"    Condition 1: project={inv_meta.get('project_number')} == {project_number}? {inv_meta.get('project_number') == project_number}")
                print(f"    Condition 1: stage={inv_meta.get('payment_stage_index')} == {stage_index}? {inv_meta.get('payment_stage_index') == stage_index}")

print(f"\nTotal Calculated: ${project_paid}")
