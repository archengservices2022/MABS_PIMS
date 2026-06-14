import sys
sys.path.insert(0, 'web_app')
from app import fb_get, _sync_project_payment

print("Before _sync_project_payment:")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-005':
        print(f"  amount_paid: ${proj.get('amount_paid')}")
        stages = proj.get('payment_stages', [])
        total_stages = sum(float(s.get('amount_paid', 0)) if s.get('amount_paid') else 0 for s in stages)
        print(f"  sum of stages: ${total_stages}")
        break

print("\nCalling _sync_project_payment('MABS-202606-005')...")
_sync_project_payment('MABS-202606-005')

print("\nAfter _sync_project_payment:")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-005':
        print(f"  amount_paid: ${proj.get('amount_paid')}")
        stages = proj.get('payment_stages', [])
        total_stages = sum(float(s.get('amount_paid', 0)) if s.get('amount_paid') else 0 for s in stages)
        print(f"  sum of stages: ${total_stages}")
        break
