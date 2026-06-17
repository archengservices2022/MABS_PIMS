import requests
from datetime import datetime

BASE = "http://127.0.0.1:5000"
s = requests.Session()
s.post(f"{BASE}/login", data={"email": "kotasridhar17@gmail.com", "password": "123456"})

PROJ_A = "MABS-202606001"    # Lonestar Project   -> item amount 1000
PROJ_B = "MABS-202606-001"   # Solidworks Drawings -> item amount 3000   (main project)

form = {
    "invoice_number": "TEST-MULTI-001",
    "invoice_date": datetime.now().strftime("%Y-%m-%d"),
    "due_date": "",
    "client_name": "Arch Engineering Services,LLC",
    "project_number": PROJ_B,            # main / default project
    "status": "Draft",
    "payment_method": "",
    "amount_paid": "0",
    "item_description[]": ["Work for Lonestar", "Work for Solidworks"],
    "item_project_number[]": [PROJ_A, PROJ_B],   # per-line overrides — the new feature
    "item_quantity[]": ["1", "1"],
    "item_unit_price[]": ["1000", "3000"],
    "subtotal": "4000",
    "tax_rate": "0",
    "tax_amount": "0",
    "total": "4000",
    "notes": "",
    "terms": "",
}
r = s.post(f"{BASE}/invoicing/new", data=form, allow_redirects=True)
print("POST status:", r.status_code, "final url:", r.url)

# Find the new invoice
import firebase_admin
from firebase_admin import credentials, db
try:
    cred = credentials.Certificate(r"C:\Users\skota\.mabs\servicekey.json")
    firebase_admin.initialize_app(cred, {"databaseURL": "https://invoice-7fe93-default-rtdb.firebaseio.com"})
except ValueError:
    pass
invoices = db.reference("/invoices").get() or {}
inv_id, inv = None, None
for k, v in invoices.items():
    if v.get("meta", {}).get("invoice_number") == "TEST-MULTI-001":
        inv_id, inv = k, v
        break

assert inv_id, "Invoice not found — creation failed"
print("\nCreated invoice:", inv_id)
print("meta.project_number :", inv["meta"].get("project_number"))
print("meta.linked_projects:", inv["meta"].get("linked_projects"))
print("line_items          :", [(li["description"], li["amount"], li["project_number"]) for li in inv["line_items"]])

# Now hit the rendered pages
r = s.get(f"{BASE}/invoicing/{inv_id}")
print("\ninvoice_detail status:", r.status_code)
print("  has 'Shared across 2'      :", "Shared across 2" in r.text)
print("  shows MABS-202606001       :", "MABS-202606001" in r.text)
print("  shows MABS-202606-001      :", "MABS-202606-001" in r.text)

# project shares
def proj_id_for(num):
    projs = db.reference("/projects").get() or {}
    for k, v in projs.items():
        if v.get("project_number") == num:
            return k
    return None

for num, expect_share in [(PROJ_A, 0.25), (PROJ_B, 0.75)]:
    pid = proj_id_for(num)
    rr = s.get(f"{BASE}/projects/{pid}")
    has_badge = "% share" in rr.text
    print(f"\nproject {num} detail -> {rr.status_code}  has-share-badge={has_badge}")
    import re
    m = re.search(r"(\d+)% share", rr.text)
    print(f"   share badge value: {m.group(1) + '%' if m else 'NOT FOUND'}  (expected ~{int(expect_share*100)}%)")
