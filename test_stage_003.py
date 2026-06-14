import sys
sys.path.insert(0, 'web_app')
from app import fb_get

# Find invoice INV-202606-017
invoices = fb_get('/invoices') or {}
print("=== Searching for INV-202606-017 ===")
for inv_id, inv in invoices.items():
    meta = inv.get('meta', {})
    if meta.get('invoice_number') == 'INV-202606-017':
        print(f"\nInvoice ID: {inv_id}")
        print(f"Invoice Number: {meta.get('invoice_number')}")
        print(f"Project: {meta.get('project_number')}")
        print(f"Stage Index: {meta.get('payment_stage_index')}")
        print(f"Linked Projects: {meta.get('linked_projects')}")

        log = inv.get('payment_log', [])
        total = sum(float(p.get('amount', 0)) for p in log)
        print(f"Payment Log Total: ${total}")
        print(f"Payment Log Entries: {log}")
        break

# Check project stages
print("\n=== Project MABS-202606-003 Stages ===")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-003':
        stages = proj.get('payment_stages', [])
        for i, s in enumerate(stages):
            if isinstance(s, dict):
                print(f"Stage {i}: {s.get('name')} - amount_paid=${s.get('amount_paid')}, status={s.get('status')}")
        break
