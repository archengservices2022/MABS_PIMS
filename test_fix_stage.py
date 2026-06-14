import sys
sys.path.insert(0, 'web_app')
from app import fb_get, _update_project_stage_payment_status

# Find invoice INV-202606-017
print("=== Before Fix ===")
invoices = fb_get('/invoices') or {}
invoice_id = None
for inv_id, inv in invoices.items():
    meta = inv.get('meta', {})
    if meta.get('invoice_number') == 'INV-202606-017':
        invoice_id = inv_id
        break

projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-003':
        stages = proj.get('payment_stages', [])
        print(f"Stage 2: {stages[2].get('name')} - amount_paid=${stages[2].get('amount_paid')}, status={stages[2].get('status')}")
        break

print(f"\nCalling _update_project_stage_payment_status('{invoice_id}')...")
_update_project_stage_payment_status(invoice_id)

print("\n=== After Fix ===")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-003':
        stages = proj.get('payment_stages', [])
        print(f"Stage 2: {stages[2].get('name')} - amount_paid=${stages[2].get('amount_paid')}, status={stages[2].get('status')}")
        break
