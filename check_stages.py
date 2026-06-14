import sys
sys.path.insert(0, 'web_app')
from app import fb_get

projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-005':
        print(f"Project: {proj.get('project_number')}")
        print(f"  contract_value: ${proj.get('contract_value')}")
        print(f"  amount_paid: ${proj.get('amount_paid')}")
        print(f"  Status: {proj.get('status')}")
        print("\nPayment Plan stages:")
        stages = proj.get('payment_stages', [])
        total = 0
        for i, stage in enumerate(stages):
            if isinstance(stage, dict):
                amt_paid = stage.get('amount_paid', 0)
                total += float(amt_paid) if amt_paid else 0
                print(f"  Stage {i+1}: {stage.get('name')} - amount_paid=${amt_paid}, status={stage.get('status')}")
        print(f"\nTotal from stages: ${total}")
        break
