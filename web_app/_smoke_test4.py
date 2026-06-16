import requests
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db

BASE = "http://127.0.0.1:5000"
s = requests.Session()
s.post(f"{BASE}/login", data={"email": "kotasridhar17@gmail.com", "password": "123456"})
try:
    cred = credentials.Certificate(r"C:\Users\skota\.mabs\servicekey.json")
    firebase_admin.initialize_app(cred, {"databaseURL": "https://invoice-7fe93-default-rtdb.firebaseio.com"})
except ValueError:
    pass

PROJ_A = "MABS-202606001"
PROJ_B = "MABS-202606-001"

def _share(inv, proj_num):
    items = inv.get("line_items", []) or []
    meta = inv.get("meta", {})
    main = meta.get("project_number", "")
    pairs = [(str(it.get("project_number","")).strip() or main, float(it.get("amount",0) or 0)) for it in items]
    total = sum(a for _, a in pairs)
    if total <= 0:
        return 1.0 if main == proj_num else 0.0
    return sum(a for pn, a in pairs if pn == proj_num) / total

def expected_amount_paid(proj_num):
    """Independently recompute what _sync_project_payment SHOULD produce right now."""
    total = 0.0
    for v in (db.reference("/invoices").get() or {}).values():
        m = v.get("meta", {})
        linked = set(m.get("linked_projects") or ([m.get("project_number")] if m.get("project_number") else []))
        if proj_num in linked:
            total += _share(v, proj_num) * float(m.get("amount_paid", 0) or 0)
    return total

def actual_amount_paid(proj_num):
    for v in (db.reference("/projects").get() or {}).values():
        if v.get("project_number") == proj_num:
            return float(v.get("amount_paid", 0) or 0)
    return None

def inv_by_num(num):
    for k, v in (db.reference("/invoices").get() or {}).items():
        if v.get("meta", {}).get("invoice_number") == num:
            v["_id"] = k
            return v
    return None

# 1. Create the multi-project invoice (25% Lonestar / 75% Solidworks)
form = {
    "invoice_number": "TEST-MULTI-002", "invoice_date": datetime.now().strftime("%Y-%m-%d"),
    "due_date": "", "client_name": "Arch Engineering Services,LLC", "project_number": PROJ_B,
    "status": "Draft", "payment_method": "", "amount_paid": "0",
    "item_description[]": ["Lonestar portion", "Solidworks portion"],
    "item_project_number[]": [PROJ_A, PROJ_B],
    "item_quantity[]": ["1", "1"], "item_unit_price[]": ["1000", "3000"],
    "subtotal": "4000", "tax_rate": "0", "tax_amount": "0", "total": "4000",
    "notes": "", "terms": "",
}
s.post(f"{BASE}/invoicing/new", data=form)
invoice = inv_by_num("TEST-MULTI-002")
inv_id = invoice["_id"]
print(f"Created invoice {inv_id}  linked_projects={invoice['meta'].get('linked_projects')}")

# 2. Record a $2000 payment -> should sync BOTH projects via prorated shares
s.post(f"{BASE}/invoicing/{inv_id}/payment/add", data={
    "amount": "2000", "date": datetime.now().strftime("%Y-%m-%d"),
    "method": "ACH", "reference": "T2", "notes": "",
})
print("\n-- After recording $2000 payment --")
all_pass = True
for label, num in [("Lonestar  (25% share)", PROJ_A), ("Solidworks (75% share)", PROJ_B)]:
    exp, act = expected_amount_paid(num), actual_amount_paid(num)
    match = abs(exp - act) < 0.01
    all_pass &= match
    print(f"  {label}: app value=${act:,.2f}   independently-recomputed expected=${exp:,.2f}   {'OK' if match else 'MISMATCH'}")
    if num == PROJ_A:
        print(f"      sanity check: 25% of $2000 = $500.00  -> app reports ${act:,.2f}  {'OK' if abs(act-500)<0.01 else 'MISMATCH'}")
    else:
        print(f"      sanity check: 75% of $2000 = $1500.00 -> app reports ${act:,.2f}  {'OK' if abs(act-1500)<0.01 else 'MISMATCH'}")

# 3. Delete the payment -> both projects should resync back down
s.post(f"{BASE}/invoicing/{inv_id}/payment/0/delete")
print("\n-- After deleting the payment --")
for label, num in [("Lonestar", PROJ_A), ("Solidworks", PROJ_B)]:
    exp, act = expected_amount_paid(num), actual_amount_paid(num)
    match = abs(exp - act) < 0.01
    all_pass &= match
    print(f"  {label}: app value=${act:,.2f}   independently-recomputed expected=${exp:,.2f}   {'OK' if match else 'MISMATCH'}")

print("\nOVERALL:", "PASS — proration & rollback both correct" if all_pass else "FAIL")

db.reference(f"/invoices/{inv_id}").delete()
print("Cleaned up TEST-MULTI-002")
