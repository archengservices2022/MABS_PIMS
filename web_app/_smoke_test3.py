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

PROJ_A = "MABS-202606001"     # Lonestar  -> 25% share of the test invoice
PROJ_B = "MABS-202606-001"    # Solidworks -> 75% share

def _safe(p): return float(p.get("amount_paid", 0) or 0)

def proj(num):
    for k, v in (db.reference("/projects").get() or {}).items():
        if v.get("project_number") == num:
            v["_id"] = k
            return v
    return None

def inv(num):
    for k, v in (db.reference("/invoices").get() or {}).items():
        if v.get("meta", {}).get("invoice_number") == num:
            v["_id"] = k
            return v
    return None

before_a, before_b = _safe(proj(PROJ_A)), _safe(proj(PROJ_B))
print(f"Before payment — {PROJ_A} amount_paid={before_a}   {PROJ_B} amount_paid={before_b}")

invoice = inv("TEST-MULTI-001")
inv_id = invoice["_id"]

r = s.post(f"{BASE}/invoicing/{inv_id}/payment/add", data={
    "amount": "2000", "date": datetime.now().strftime("%Y-%m-%d"),
    "method": "Wire Transfer", "reference": "TEST-PMT-1", "notes": "smoke test payment",
}, allow_redirects=True)
print("payment_add ->", r.status_code, r.url)

after_a, after_b = _safe(proj(PROJ_A)), _safe(proj(PROJ_B))
delta_a, delta_b = after_a - before_a, after_b - before_b
print(f"\nAfter $2000 payment (invoice share: {PROJ_A}=25%, {PROJ_B}=75%):")
print(f"  {PROJ_A}: {before_a} -> {after_a}  (delta={delta_a}, expected ~500)")
print(f"  {PROJ_B}: {before_b} -> {after_b}  (delta={delta_b}, expected ~1500)")
ok = abs(delta_a - 500) < 0.01 and abs(delta_b - 1500) < 0.01
print("\nPRORATION RESULT:", "PASS" if ok else "FAIL")

# Now delete the payment and confirm it rolls back cleanly
r = s.post(f"{BASE}/invoicing/{inv_id}/payment/0/delete", allow_redirects=True)
print("\npayment_delete ->", r.status_code)
final_a, final_b = _safe(proj(PROJ_A)), _safe(proj(PROJ_B))
print(f"  {PROJ_A}: back to {final_a} (was {before_a})")
print(f"  {PROJ_B}: back to {final_b} (was {before_b})")
print("ROLLBACK RESULT:", "PASS" if abs(final_a-before_a) < 0.01 and abs(final_b-before_b) < 0.01 else "FAIL")

# cleanup test invoice
db.reference(f"/invoices/{inv_id}").delete()
print("\nCleaned up test invoice TEST-MULTI-001")
