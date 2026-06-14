import sys
sys.path.insert(0, 'web_app')
from app import fb_get, _sync_project_payment

print("=== MABS-202606-006 Before Sync ===")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-006':
        print(f"project.amount_paid: ${proj.get('amount_paid')}")
        stages = proj.get('payment_stages', [])
        total = 0
        for i, s in enumerate(stages):
            if isinstance(s, dict):
                amt = s.get('amount_paid', 0)
                total += float(amt) if amt else 0
                print(f"  Stage {i+1}: {s.get('name')} = ${amt}")
        print(f"Sum of all stages: ${total}")
        break

print("\n=== Calling _sync_project_payment ===")
_sync_project_payment('MABS-202606-006')

print("\n=== MABS-202606-006 After Sync ===")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-006':
        print(f"project.amount_paid: ${proj.get('amount_paid')}")
        stages = proj.get('payment_stages', [])
        total = 0
        for i, s in enumerate(stages):
            if isinstance(s, dict):
                amt = s.get('amount_paid', 0)
                total += float(amt) if amt else 0
                print(f"  Stage {i+1}: {s.get('name')} = ${amt}")
        print(f"Sum of all stages: ${total}")
        break
