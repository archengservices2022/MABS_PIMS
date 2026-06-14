import requests, re
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

# Create a project: $5000 contract, 20% down payment, then CUSTOM irregular installments
# (e.g. client pays random amounts: $1500, $2000, $500 — sums to remaining $4000)
form = {
    "project_name": "SMOKE-TEST Custom Plan Project",
    "client_name": "Arch Engineering Services,LLC",
    "description": "smoke test", "status": "Not Started",
    "start_date": "", "end_date": "",
    "contract_value": "5000",
    "payment_category": "Down Payment",
    "amount_paid": "0",
    "down_payment_percent": "20",
    "installment_count": "custom",
    "custom_installment_amount[]": ["1500", "2000", "500"],
    "notes": "", "assigned_to": "",
}
r = s.post(f"{BASE}/projects/new", data=form, allow_redirects=True)
print("create project ->", r.status_code, r.url)

raw_proj = db.reference("/projects").get() or {}
pid, pdata = None, None
for k, v in raw_proj.items():
    if v.get("project_name") == "SMOKE-TEST Custom Plan Project":
        pid, pdata = k, v
        break
assert pid, "project not found"
print(f"\nproject {pdata.get('project_number')} ({pid})")
print("  installment_mode  :", pdata.get("installment_mode"))
print("  installment_count :", pdata.get("installment_count"))
print("  custom_amounts    :", pdata.get("custom_installment_amounts"))
print("  payment_stages    :")
for st in pdata.get("payment_stages", []):
    print("   -", st)

expected_names_amts = [("Down Payment (20%)", 1000.0), ("Installment 1 of 3", 1500.0),
                       ("Installment 2 of 3", 2000.0), ("Installment 3 of 3", 500.0)]
actual = [(s["name"], float(s["amount"])) for s in pdata.get("payment_stages", [])]
print("\nStage check:", "PASS" if actual == expected_names_amts else f"FAIL — got {actual}")

# Render project_detail -> Payment Plan card should show all 4 stages + Generate Invoice on first Pending
rr = s.get(f"{BASE}/projects/{pid}")
print(f"\nproject_detail -> {rr.status_code}")
print("  has Payment Plan card      :", "Payment Plan" in rr.text)
print("  shows all 4 stage names    :", all(n in rr.text for n,_ in expected_names_amts))
print("  has Generate Invoice link  :", "Generate Invoice" in rr.text)
m = re.search(r"stage_idx=(\d+)", rr.text)
print("  first Generate-Invoice idx :", m.group(1) if m else None, "(expected 0)")

# Render edit form -> should show existing custom amounts + status badges
rr = s.get(f"{BASE}/projects/{pid}/edit")
print(f"\nproject_edit (GET) -> {rr.status_code}")
print("  shows 'Custom amounts'     :", "Custom amounts" in rr.text)
print("  existingCustomAmounts JSON :", re.search(r'existingCustomAmounts\s*=\s*(\[[^\]]*\])', rr.text).group(1) if re.search(r'existingCustomAmounts\s*=\s*(\[[^\]]*\])', rr.text) else None)

# Click "Generate Invoice" for stage 0 -> should land on prefilled invoice form
rr = s.get(f"{BASE}/projects/{pid}/stage/0/invoice", allow_redirects=True)
print(f"\nstage invoice prefill -> {rr.status_code}  url={rr.url}")
print("  banner mentions stage name :", "Down Payment (20%)" in rr.text)
print("  prefilled amount 1000.00   :", 'value="1000.00"' in rr.text)

db.reference(f"/projects/{pid}").delete()
print("\nCleaned up SMOKE-TEST project")
