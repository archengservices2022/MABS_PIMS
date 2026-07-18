"""
ARCH PIMS -- Data Wipe Script
Keeps: /users (logins), /company_info (settings)
Deletes: everything else (quotes, projects, invoices, timesheets, expenses, etc.)

Run: python arch_clear_data.py
"""
import sys
from pathlib import Path

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
except ImportError:
    print("ERROR: firebase-admin not installed. Run: pip install firebase-admin")
    sys.exit(1)

# -- ARCH Firebase Config ------------------------------------------------------
FIREBASE_DB_URL = "https://invoice-7fe93-default-rtdb.firebaseio.com"
KEY_PATH = Path(__file__).parent / "arch_servicekey.json"

# -- Paths to DELETE -----------------------------------------------------------
PATHS_TO_DELETE = [
    "/job_forms",
    "/projects",
    "/invoices",
    "/clients",
    "/timesheets",
    "/time_entries",
    "/expenses",
    "/salaries",
    "/commission_payments",
    "/revenue_entries",
    "/sales_persons",
    "/notifications",
    "/payroll",
    "/balance_sheet_expenses",
    "/balance_sheet_revenue",
    "/balance_sheet_salary",
    "/time_off_requests",
]

# -- Paths to KEEP -------------------------------------------------------------
PATHS_TO_KEEP = ["/users", "/company_info"]

# -- Connect -------------------------------------------------------------------
if not KEY_PATH.exists():
    print(f"ERROR: arch_servicekey.json not found at {KEY_PATH}")
    sys.exit(1)

print(f"Using key: {KEY_PATH}")
print(f"Database:  {FIREBASE_DB_URL}\n")

cred = credentials.Certificate(str(KEY_PATH))
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})

# -- Confirm -------------------------------------------------------------------
print("The following paths will be PERMANENTLY DELETED from ARCH Firebase:")
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

# -- Wipe ----------------------------------------------------------------------
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

# -- Summary -------------------------------------------------------------------
print()
if errors:
    print(f"Done with {len(errors)} error(s):")
    for path, err in errors:
        print(f"  - {path}: {err}")
else:
    print("ARCH data wiped successfully.")
    print("Users and company settings are intact.")
    print("The ARCH app is now clean and ready for live use.")
