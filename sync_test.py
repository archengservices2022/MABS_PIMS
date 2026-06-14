import sys
sys.path.insert(0, 'web_app')
from app import fb_get, _sync_project_payment

print("Before sync:")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-005':
        print(f"  amount_paid: ${proj.get('amount_paid')}")
        break

print("\nCalling _sync_project_payment('MABS-202606-005')...")
_sync_project_payment('MABS-202606-005')

print("\nAfter sync:")
projects = fb_get('/projects') or {}
for pid, proj in projects.items():
    if proj.get('project_number') == 'MABS-202606-005':
        print(f"  amount_paid: ${proj.get('amount_paid')}")
        break
