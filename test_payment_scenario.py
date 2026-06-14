import sys
sys.path.insert(0, 'web_app')
from app import fb_get, _sync_project_payment

print("=== Current State ===")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-005':
        print(f"\nProject: {proj.get('project_number')}")
        print(f"  amount_paid: ${proj.get('amount_paid')}")
        print(f"\nPayment Plan stages:")
        stages = proj.get('payment_stages', [])
        total = 0
        for i, stage in enumerate(stages):
            if isinstance(stage, dict):
                amt = stage.get('amount_paid', 0)
                total += float(amt) if amt else 0
                print(f"    Stage {i+1}: {stage.get('name')} - amount_paid=${amt}, status={stage.get('status')}")
        print(f"\n  Total from stages: ${total}")

print("\n=== All Invoices Linked to MABS-202606-005 ===")
invoices = fb_get('/invoices') or {}
for inv_id, inv in invoices.items():
    meta = inv.get('meta', {})
    linked = meta.get('linked_projects', [])

    # Check if linked to MABS-202606-005
    found = False
    for lp in linked:
        if isinstance(lp, dict) and lp.get('project_number') == 'MABS-202606-005':
            found = True
            break

    if found or meta.get('project_number') == 'MABS-202606-005':
        inv_num = meta.get('invoice_number', '')
        log = inv.get('payment_log', [])
        total_log = sum(float(p.get('amount', 0)) for p in log)
        print(f"\n{inv_num}:")
        print(f"  linked_projects: {linked}")
        print(f"  payment_log total: ${total_log}")
        print(f"  payment_log: {log}")
