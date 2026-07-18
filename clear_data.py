"""
MABS PIMS — Data Wipe Script
Keeps: /users (logins), /company_info (settings)
Deletes: everything else (quotes, projects, invoices, timesheets, expenses, etc.)

Run: python clear_data.py
"""
import json
import sys
from pathlib import Path

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
except ImportError:
    print("ERROR: firebase-admin not installed. Run: pip install firebase-admin")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
FIREBASE_DB_URL = "https://pims-955e3-default-rtdb.firebaseio.com"

KEY_CANDIDATES = [
    Path(__file__).parent / "web_app" / "servicekey.json",
    Path(__file__).parent / "servicekey.json",
    Path.home() / ".mabs" / "servicekey.json",
]

# ── Paths to DELETE (test/operational data) ───────────────────────────────────
PATHS_TO_DELETE = [
    "/job_forms",           # Quotes
    "/projects",            # Projects
    "/invoices",            # Invoices
    "/clients",             # Clients
    "/timesheets",          # Timesheets
    "/time_entries",        # Time entries (clock-in)
    "/expenses",            # Expenses
    "/salaries",            # Salary records
    "/commission_payments", # Commission payment records
    "/revenue_entries",     # Revenue entries
    "/sales_persons",       # Sales persons list
    "/notifications",       # Notifications
    "/payroll",             # Payroll records
    "/balance_sheet_expenses",  # Balance sheet expense entries
    "/balance_sheet_revenue",   # Balance sheet revenue entries
    "/balance_sheet_salary",    # Balance sheet salary entries
    "/time_off_requests",       # Time off / leave requests
]

# ── Paths to KEEP ─────────────────────────────────────────────────────────────
PATHS_TO_KEEP = ["/users", "/company_info"]

# ── Connect ───────────────────────────────────────────────────────────────────
key_path = next((p for p in KEY_CANDIDATES if p.exists()), None)
if not key_path:
    print("ERROR: servicekey.json not found. Expected at web_app/servicekey.json")
    sys.exit(1)

print(f"Using key: {key_path}")
print(f"Database:  {FIREBASE_DB_URL}\n")

cred = credentials.Certificate(str(key_path))
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})

# ── Confirm ───────────────────────────────────────────────────────────────────
print("The following paths will be PERMANENTLY DELETED:")
for p in PATHS_TO_DELETE:
    print(f"  [DELETE]  {p}")
print()
print("The following paths will be KEPT:")
for p in PATHS_TO_KEEP:
    print(f"  [KEEP]    {p}")
print()

confirm = input("Type  YES  to proceed: ").strip()
if confirm != "YES":
    print("Aborted.")
    sys.exit(0)

# ── Wipe ──────────────────────────────────────────────────────────────────────
print()
errors = []
for path in PATHS_TO_DELETE:
    try:
        ref = firebase_db.reference(path)
        data = ref.get()
        if data is None:
            print(f"  (empty)  {path}")
        else:
            ref.delete()
            print(f"  DELETED  {path}")
    except Exception as e:
        errors.append((path, str(e)))
        print(f"  ERROR    {path} - {e}")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"Done with {len(errors)} error(s):")
    for path, err in errors:
        print(f"  • {path}: {err}")
else:
    print("All data wiped successfully.")
    print("Users and company settings are intact.")
    print("The app is now clean and ready for live use.")
