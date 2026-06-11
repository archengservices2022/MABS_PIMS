"""MABS PIMS - Flask Web Application"""
import os
import json
import base64
import tempfile
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from functools import wraps
from typing import Dict, List, Optional

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file, abort
)

try:
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from pypdf import PdfReader as _PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pims.web")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent   # project root
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"

# ── Firebase config ───────────────────────────────────────────────────────────
FIREBASE_API_KEY = "AIzaSyD6F6T_KIZ90TkCOL03-jSXTeuPM5WVwJY"
FIREBASE_DB_URL  = "https://invoice-7fe93-default-rtdb.firebaseio.com"

FIREBASE_AVAILABLE = False
db = None

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
    from firebase_admin.exceptions import FirebaseError

    _service_key_candidates = [
        Path.home() / ".mabs" / "servicekey.json",
        DATA_DIR / "servicekey.json",
        BASE_DIR / "servicekey.json",
    ]
    _key_path = next((p for p in _service_key_candidates if p.exists()), None)

    if _key_path:
        if not firebase_admin._apps:
            cred = credentials.Certificate(str(_key_path))
            firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})
        db = firebase_db
        FIREBASE_AVAILABLE = True
        log.info("Firebase initialised from %s", _key_path)
    else:
        log.warning("No Firebase service key found — Firebase disabled")
except ImportError:
    log.warning("firebase-admin not installed — Firebase disabled")
except Exception as exc:
    log.error("Firebase init error: %s", exc)

# ── Role helpers ──────────────────────────────────────────────────────────────
ROLE_PAGES = {
    "admin":    ["dashboard", "quotes", "projects", "invoicing", "financial", "settings"],
    "sales":    ["quotes"],
    "projects": ["projects", "invoicing"],
    "finance":  ["financial"],
}

def normalize_role(role: str) -> str:
    r = str(role or "sales").strip().lower()
    return r if r in ROLE_PAGES else "sales"

def can_access(role: str, page: str) -> bool:
    return page in ROLE_PAGES.get(normalize_role(role), [])

def first_page(role: str) -> str:
    pages = ROLE_PAGES.get(normalize_role(role), ["quotes"])
    return pages[0]

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "mabs-pims-secret-2025-change-in-prod")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# ── Auth decorators ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_email" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def role_required(page_key):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_email" not in session:
                return redirect(url_for("login"))
            if not can_access(session.get("user_role", ""), page_key):
                flash("You don't have permission to access this page.", "danger")
                return redirect(url_for(first_page(session.get("user_role", "sales"))))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ── Firebase helpers ──────────────────────────────────────────────────────────
def fb_ref(path: str):
    if not FIREBASE_AVAILABLE:
        return None
    return db.reference(path)

def fb_get(path: str):
    ref = fb_ref(path)
    return ref.get() if ref else None

def fb_push(path: str, data: dict) -> Optional[str]:
    ref = fb_ref(path)
    if not ref:
        return None
    new_ref = ref.push()
    data["firebase_id"] = new_ref.key
    new_ref.set(data)
    return new_ref.key

def fb_update(path: str, data: dict) -> bool:
    ref = fb_ref(path)
    if not ref:
        return False
    ref.update(data)
    return True

def fb_delete(path: str) -> bool:
    ref = fb_ref(path)
    if not ref:
        return False
    ref.delete()
    return True

def load_settings() -> dict:
    try:
        data = fb_get("/settings") or {}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        sf = DATA_DIR / "settings.json"
        if sf.exists():
            with open(sf, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _get_ai_client():
    """Return an Anthropic client using the API key stored in settings, or None."""
    if not ANTHROPIC_AVAILABLE:
        return None
    key = load_settings().get("ai", {}).get("anthropic_key", "").strip()
    if not key:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    return _anthropic.Anthropic(api_key=key)


def _ai_call(prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    """Run a single Claude call; returns the text or raises RuntimeError."""
    client = _get_ai_client()
    if not client:
        raise RuntimeError("No Anthropic API key configured. Add it in Settings → AI.")
    msgs = [{"role": "user", "content": prompt}]
    kwargs = {"model": "claude-haiku-4-5-20251001", "max_tokens": max_tokens, "messages": msgs}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return resp.content[0].text.strip()


def company_info() -> dict:
    settings = load_settings()
    defaults = {
        "name":    "MABS Engineering LLC",
        "address": "15455 Manchester Rd, PO Box 1144\nManchester, MO 63011",
        "email":   "admin@habbengineering.com",
        "phone":   "314-303-0004",
        "website": "www.mabs-engineeringg.com",
    }
    defaults.update(settings.get("company", {}))
    return defaults

# ── Authentication ────────────────────────────────────────────────────────────
def firebase_sign_in(email: str, password: str):
    """Returns (ok, uid, error_msg)"""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    try:
        resp = requests.post(url, json={"email": email, "password": password,
                                        "returnSecureToken": True}, timeout=10)
        if resp.status_code == 200:
            return True, resp.json().get("localId", ""), ""
        err = resp.json().get("error", {}).get("message", "Invalid credentials")
        return False, "", err
    except requests.exceptions.Timeout:
        return False, "", "Connection timed out. Please try again."
    except Exception as exc:
        return False, "", str(exc)

def load_user_profile(uid: str) -> Optional[dict]:
    if not FIREBASE_AVAILABLE:
        return None
    data = fb_get(f"/users/{uid}")
    if data and isinstance(data, dict):
        data["firebase_uid"] = uid
        return data
    return None

# ── Context processor ─────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    role = session.get("user_role", "")
    return {
        "user_name":   session.get("user_name", ""),
        "user_email":  session.get("user_email", ""),
        "user_role":   role,
        "allowed_pages": ROLE_PAGES.get(normalize_role(role), []),
        "company":     company_info(),
        "now":         datetime.now(),
        "timedelta":   timedelta,
    }

# ── Routes: Auth ──────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_email" in session:
        return redirect(url_for(first_page(session.get("user_role", "sales"))))

    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            error = "Please enter your email and password."
        elif not FIREBASE_AVAILABLE:
            error = "Authentication service unavailable. Please check server configuration."
        else:
            ok, uid, err_msg = firebase_sign_in(email, password)
            if not ok:
                error = "Invalid email or password. Please try again."
                log.warning("Login failed for %s: %s", email, err_msg)
            else:
                profile = load_user_profile(uid)
                if not profile:
                    error = "No app profile found. Contact your administrator."
                elif not profile.get("active", True):
                    error = "Your account is inactive. Contact your administrator."
                else:
                    role = normalize_role(profile.get("role", "sales"))
                    session.permanent = True
                    session["user_email"] = email
                    session["user_uid"]   = uid
                    session["user_name"]  = profile.get("username", email.split("@")[0])
                    session["user_role"]  = role
                    log.info("Login: %s (%s)", email, role)
                    return redirect(url_for(first_page(role)))

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Routes: Dashboard ─────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return redirect(url_for(first_page(session.get("user_role", "sales"))))

@app.route("/dashboard")
@role_required("dashboard")
def dashboard():
    _auto_flag_overdue()
    invoices = fb_get("/invoices") or {}
    projects = fb_get("/projects") or {}
    quotes   = fb_get("/job_forms") or {}
    expenses = fb_get("/balance_sheet_expenses") or {}

    # ── Stats ──────────────────────────────────────────────────────────────
    inv_list  = [dict(v, firebase_id=k) for k, v in invoices.items()
                 if isinstance(v, dict)] if isinstance(invoices, dict) else []
    proj_list = [dict(v, firebase_id=k) for k, v in projects.items()
                 if isinstance(v, dict)] if isinstance(projects, dict) else []
    quot_list = list(quotes.values())   if isinstance(quotes, dict)   else []

    total_invoiced = sum(
        float(str(i.get("meta", {}).get("total", 0) or 0).replace(",", ""))
        for i in inv_list if isinstance(i, dict)
    )
    total_paid = sum(
        float(str(i.get("meta", {}).get("amount_paid", 0) or 0).replace(",", ""))
        for i in inv_list if isinstance(i, dict)
    )
    total_outstanding = total_invoiced - total_paid

    active_projects = sum(1 for p in proj_list
                          if isinstance(p, dict) and p.get("status", "") not in ("Completed", "Cancelled"))
    open_quotes     = sum(1 for q in quot_list
                          if isinstance(q, dict) and q.get("status", "Not Started") not in ("Completed", "Cancelled", "Invoiced"))

    # ── Recent invoices ────────────────────────────────────────────────────
    recent_invoices = sorted(
        [i for i in inv_list if isinstance(i, dict)],
        key=lambda x: x.get("meta", {}).get("created_at", ""),
        reverse=True
    )[:5]

    # ── Recent projects ────────────────────────────────────────────────────
    recent_projects = sorted(
        [p for p in proj_list if isinstance(p, dict)],
        key=lambda x: x.get("created_at", ""),
        reverse=True
    )[:5]

    # ── Monthly revenue for chart — always show last 6 calendar months ────────
    monthly = {}
    for inv in inv_list:
        if not isinstance(inv, dict):
            continue
        date_str = inv.get("meta", {}).get("invoice_date", "") or ""
        try:
            dt  = datetime.fromisoformat(date_str[:10])
            key = dt.strftime("%b %Y")
            amt = float(str(inv.get("meta", {}).get("total", 0) or 0).replace(",", ""))
            monthly[key] = monthly.get(key, 0) + amt
        except Exception:
            pass

    # Build a full 6-month window ending this month (zero-fill gaps)
    from dateutil.relativedelta import relativedelta
    now = datetime.now()
    chart_labels = [(now - relativedelta(months=i)).strftime("%b %Y") for i in range(5, -1, -1)]
    chart_data   = [monthly.get(m, 0) for m in chart_labels]

    # ── Status distribution for donut charts ──────────────────────────────────
    inv_status_counts = {}
    for i in inv_list:
        if isinstance(i, dict):
            st = i.get("meta", {}).get("status") or "Draft"
            inv_status_counts[st] = inv_status_counts.get(st, 0) + 1

    proj_status_counts = {}
    for p in proj_list:
        if isinstance(p, dict):
            st = p.get("status") or "Not Started"
            proj_status_counts[st] = proj_status_counts.get(st, 0) + 1

    # ── Alert counts ──────────────────────────────────────────────────────────
    today_str = datetime.now().strftime("%Y-%m-%d")
    week_str  = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    overdue_count = sum(1 for i in inv_list
                        if isinstance(i, dict) and i.get("meta", {}).get("status", "") == "Overdue")
    _QTERMINAL = {"Approved", "Converted", "Invoiced", "Rejected", "Cancelled", "Expired"}
    expiring_count = sum(1 for q in quot_list
                         if isinstance(q, dict)
                         and q.get("status", "Not Started") not in _QTERMINAL
                         and q.get("valid_until", "")
                         and today_str <= q.get("valid_until", "") <= week_str)

    # ── Action queue ──────────────────────────────────────────────────────────
    followup_quotes = sorted(
        [q for q in quot_list
         if isinstance(q, dict)
         and q.get("status", "") not in _QTERMINAL
         and q.get("follow_up_date", "")
         and q.get("follow_up_date", "") <= today_str],
        key=lambda x: x.get("follow_up_date", "")
    )[:8]

    approved_quotes = sorted(
        [q for q in quot_list
         if isinstance(q, dict)
         and q.get("status", "") == "Approved"],
        key=lambda x: x.get("date", x.get("created_at", "")),
        reverse=True
    )[:6]

    # Active projects by status for pipeline view
    pipeline_statuses = ["Not Started", "In Progress", "On Hold"]
    pipeline = {st: [p for p in proj_list if isinstance(p, dict) and p.get("status", "Not Started") == st]
                for st in pipeline_statuses}

    return render_template("dashboard.html",
        total_invoiced=total_invoiced,
        total_paid=total_paid,
        total_outstanding=total_outstanding,
        active_projects=active_projects,
        open_quotes=open_quotes,
        total_invoices=len(inv_list),
        recent_invoices=recent_invoices,
        recent_projects=recent_projects,
        chart_labels=json.dumps(chart_labels),
        chart_data=json.dumps(chart_data),
        overdue_count=overdue_count,
        expiring_count=expiring_count,
        followup_quotes=followup_quotes,
        approved_quotes=approved_quotes,
        pipeline=pipeline,
        inv_status_labels=json.dumps(list(inv_status_counts.keys())),
        inv_status_data=json.dumps(list(inv_status_counts.values())),
        proj_status_labels=json.dumps(list(proj_status_counts.keys())),
        proj_status_data=json.dumps(list(proj_status_counts.values())),
        ai_enabled=bool(_get_ai_client()),
    )

# ── Routes: Quotes ────────────────────────────────────────────────────────────
@app.route("/quotes")
@role_required("quotes")
def quotes():
    raw = fb_get("/job_forms") or {}
    _QUOTE_TERMINAL = {"Approved", "Converted", "Invoiced", "Rejected", "Cancelled", "Expired"}
    today_str = datetime.now().strftime("%Y-%m-%d")
    items = []
    for fid, fdata in (raw.items() if isinstance(raw, dict) else []):
        if fdata and isinstance(fdata, dict):
            fdata["firebase_id"] = fid
            fdata.setdefault("status", "Not Started")
            # Auto-expire quotes past valid_until date
            valid_until = fdata.get("valid_until", "")
            if (valid_until and valid_until < today_str
                    and fdata["status"] not in _QUOTE_TERMINAL):
                fb_update(f"/job_forms/{fid}", {
                    "status": "Expired",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                fdata["status"] = "Expired"
            # Expiry warning: days remaining for active quotes
            if valid_until and fdata["status"] not in _QUOTE_TERMINAL:
                try:
                    from datetime import date as _date
                    delta = (_date.fromisoformat(valid_until[:10]) - _date.today()).days
                    fdata["_days_until_expiry"] = delta
                except Exception:
                    pass
            items.append(fdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    search        = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "")
    year_filter   = request.args.get("year", "")
    month_filter  = request.args.get("month", "")
    date_from     = request.args.get("from", "")
    date_to       = request.args.get("to", "")

    if search:
        items = [i for i in items if search in str(i).lower()]
    if status_filter:
        items = [i for i in items if i.get("status", "") == status_filter]
    if year_filter:
        items = [i for i in items if (i.get("date") or "").startswith(year_filter)]
    if year_filter and month_filter:
        prefix = f"{year_filter}-{month_filter.zfill(2)}"
        items = [i for i in items if (i.get("date") or "").startswith(prefix)]
    if date_from:
        items = [i for i in items if (i.get("date") or "") >= date_from]
    if date_to:
        items = [i for i in items if (i.get("date") or "") <= date_to]

    # Build available years from all quote dates (before filtering)
    all_items_raw = []
    for fid, fdata in (fb_get("/job_forms") or {}).items() if isinstance(fb_get("/job_forms") or {}, dict) else []:
        if fdata and isinstance(fdata, dict):
            all_items_raw.append(fdata)
    available_years = sorted(
        {(d.get("date") or "")[:4] for d in all_items_raw if len((d.get("date") or "")) >= 4},
        reverse=True
    )

    # Build follow-ups lists from ALL items (unaffected by list filters)
    from datetime import date as _date, timedelta as _td
    _today     = datetime.now().strftime("%Y-%m-%d")
    _today_d   = _date.today()
    _in14      = (_today_d + _td(days=14)).isoformat()
    follow_ups = []       # due today or overdue
    upcoming_followups = []  # due tomorrow → +14 days
    for q in all_items_raw:
        fu = q.get("follow_up_date", "")
        if not fu or q.get("status", "") in _QUOTE_TERMINAL:
            continue
        q_copy = dict(q)
        if fu <= _today:
            try:
                q_copy["_fu_days_overdue"] = (_today_d - _date.fromisoformat(fu[:10])).days
            except Exception:
                q_copy["_fu_days_overdue"] = 0
            follow_ups.append(q_copy)
        elif fu <= _in14:
            try:
                q_copy["_fu_days_ahead"] = (_date.fromisoformat(fu[:10]) - _today_d).days
            except Exception:
                q_copy["_fu_days_ahead"] = 0
            upcoming_followups.append(q_copy)
    follow_ups.sort(key=lambda x: x.get("follow_up_date", ""))
    upcoming_followups.sort(key=lambda x: x.get("follow_up_date", ""))

    statuses   = ["Not Started", "In Progress", "Completed", "Invoiced", "Cancelled", "Expired"]
    active_tab = request.args.get("tab", "all")
    today_date = datetime.now().strftime("%Y-%m-%d")
    return render_template("quotes.html", quotes=items, statuses=statuses,
                           search=search, status_filter=status_filter,
                           year_filter=year_filter, month_filter=month_filter,
                           date_from=date_from, date_to=date_to,
                           available_years=available_years,
                           follow_ups=follow_ups,
                           upcoming_followups=upcoming_followups,
                           clients=_load_clients(), sales_people=_load_sales_people(),
                           active_tab=active_tab, today_date=today_date,
                           next_num=_next_quote_number())

@app.route("/quotes/export")
@role_required("quotes")
def quotes_export():
    import csv, io
    raw = fb_get("/job_forms") or {}
    items = []
    for fid, fdata in (raw.items() if isinstance(raw, dict) else []):
        if fdata and isinstance(fdata, dict):
            fdata["firebase_id"] = fid
            items.append(fdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    status_filter = request.args.get("status", "")
    date_from     = request.args.get("from", "")
    date_to       = request.args.get("to", "")
    if status_filter:
        items = [i for i in items if i.get("status", "") == status_filter]
    if date_from:
        items = [i for i in items if (i.get("date") or "") >= date_from]
    if date_to:
        items = [i for i in items if (i.get("date") or "") <= date_to]

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Quote #","Client","Project/Scope","Salesperson","Date","Valid Until",
                "Status","Subtotal","Tax","Total","Notes"])
    for q in items:
        w.writerow([q.get("job_number",""), q.get("client_name",""), q.get("project_name",""),
                    q.get("salesperson",""), q.get("date",""), q.get("valid_until",""),
                    q.get("status",""), q.get("subtotal","0"), q.get("tax_amount","0"),
                    q.get("total","0"), q.get("notes","")])
    output.seek(0)
    from flask import Response
    fname = f"quotes_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/quotes/export/excel")
@role_required("quotes")
def quotes_export_excel():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    import io as _io

    raw = fb_get("/job_forms") or {}
    items = []
    for fid, fdata in (raw.items() if isinstance(raw, dict) else []):
        if fdata and isinstance(fdata, dict):
            items.append(fdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    if request.args.get("status"):
        items = [i for i in items if i.get("status","") == request.args["status"]]
    if request.args.get("from"):
        items = [i for i in items if (i.get("date") or "") >= request.args["from"]]
    if request.args.get("to"):
        items = [i for i in items if (i.get("date") or "") <= request.args["to"]]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quotes"

    hdr_fill = PatternFill(start_color="FF0F172A", end_color="FF0F172A", fill_type="solid")
    hdr_font = Font(color="FFFFFFFF", bold=True, size=11)
    alt_fill = PatternFill(start_color="FFF8FAFC", end_color="FFF8FAFC", fill_type="solid")
    ctr = Alignment(horizontal="center", vertical="center")
    rgt = Alignment(horizontal="right",  vertical="center")

    headers = ["Quote #","Client","Project / Scope","Salesperson","Date","Valid Until",
               "Status","Subtotal ($)","Tax ($)","Total ($)","Notes"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill; cell.font = hdr_font; cell.alignment = ctr

    for ri, q in enumerate(items, 2):
        row = [q.get("job_number",""), q.get("client_name",""), q.get("project_name",""),
               q.get("salesperson",""), q.get("date",""), q.get("valid_until",""),
               q.get("status",""), _safe_float(q.get("subtotal",0)),
               _safe_float(q.get("tax_amount",0)), _safe_float(q.get("total",0)),
               q.get("notes","")]
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            if ri % 2 == 0:
                cell.fill = alt_fill
            if ci in (8, 9, 10):
                cell.number_format = '"$"#,##0.00'
                cell.alignment = rgt

    for ci, w in enumerate([14,22,32,18,12,12,14,13,10,13,30], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"

    buf = _io.BytesIO()
    wb.save(buf); buf.seek(0)
    from flask import Response
    fname = f"quotes_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/quotes/export/pdf")
@role_required("quotes")
def quotes_export_pdf():
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError:
        flash("reportlab is not installed. Run: pip install reportlab", "danger")
        return redirect(url_for("quotes", tab="export"))

    import io as _io
    raw = fb_get("/job_forms") or {}
    items = []
    for fid, fdata in (raw.items() if isinstance(raw, dict) else []):
        if fdata and isinstance(fdata, dict):
            items.append(fdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    if request.args.get("status"):
        items = [i for i in items if i.get("status","") == request.args["status"]]
    if request.args.get("from"):
        items = [i for i in items if (i.get("date") or "") >= request.args["from"]]
    if request.args.get("to"):
        items = [i for i in items if (i.get("date") or "") <= request.args["to"]]

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=0.5*inch, rightMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    co = company_info()
    elems = []

    title_s = ParagraphStyle("T", parent=styles["Normal"], fontSize=15,
                              fontName="Helvetica-Bold",
                              textColor=colors.HexColor("#0F766E"), spaceAfter=3)
    sub_s   = ParagraphStyle("S", parent=styles["Normal"], fontSize=9,
                              textColor=colors.HexColor("#64748B"), spaceAfter=14)
    elems.append(Paragraph(f"{co.get('name','')} — Quote Report", title_s))
    _pdf_from = request.args.get("from", "")
    _pdf_to   = request.args.get("to", "")
    _date_range = ""
    if _pdf_from and _pdf_to:
        _date_range = f"  ·  {_pdf_from} to {_pdf_to}"
    elif _pdf_from:
        _date_range = f"  ·  From {_pdf_from}"
    elif _pdf_to:
        _date_range = f"  ·  Up to {_pdf_to}"
    elems.append(Paragraph(
        f"Generated {datetime.now().strftime('%B %d, %Y')}  ·  {len(items)} record{'s' if len(items)!=1 else ''}{_date_range}",
        sub_s))

    hdrs = ["Quote #","Client","Project / Scope","Salesperson","Date","Status","Total"]
    data = [hdrs]
    for q in items:
        data.append([
            q.get("job_number","—"),
            q.get("client_name","—"),
            (q.get("project_name") or "—")[:38],
            q.get("salesperson","—"),
            q.get("date","—"),
            q.get("status","—"),
            f"${_safe_float(q.get('total',0)):,.2f}",
        ])

    cw = [1.1*inch, 1.8*inch, 2.9*inch, 1.5*inch, 1.0*inch, 1.2*inch, 1.0*inch]
    tbl = Table(data, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 9),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,0), 8),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID",          (0,0), (-1,-1), 0.4, colors.HexColor("#E2E8F0")),
        ("TOPPADDING",    (0,1), (-1,-1), 5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
        ("ALIGN",         (-1,1),(-1,-1), "RIGHT"),
        ("FONTNAME",      (-1,1),(-1,-1), "Helvetica-Bold"),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buf.seek(0)

    from flask import Response
    fname = f"quotes_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/sales-people/new", methods=["POST"])
@role_required("quotes")
def sales_person_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "danger")
    else:
        person = {
            "name":       name,
            "phone":      request.form.get("phone", "").strip(),
            "email":      request.form.get("email", "").strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        fb_push("/sales_persons", person)
        # Keep local file in sync for desktop compatibility
        try:
            lp = DATA_DIR / "sales_persons.json"
            existing = []
            if lp.exists():
                with open(lp, encoding="utf-8") as f:
                    existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
            existing.append(person)
            with open(lp, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            log.warning("Could not update local sales_persons.json: %s", exc)
        flash(f"Sales person '{name}' added.", "success")
    return redirect(url_for("quotes", tab="salespeople"))

@app.route("/sales-people/<person_id>/delete", methods=["POST"])
@role_required("quotes")
def sales_person_delete(person_id):
    fb_delete(f"/sales_persons/{person_id}")
    flash("Sales person removed.", "success")
    return redirect(url_for("quotes", tab="salespeople"))

@app.route("/quotes/new", methods=["GET", "POST"])
@role_required("quotes")
def quotes_new():
    clients   = _load_clients()
    sales_ppl = _load_sales_people()
    if request.method == "POST":
        data = _parse_quote_form(request.form)
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["created_by"] = session.get("user_email", "")
        key = fb_push("/job_forms", data)
        if key:
            flash("Quote created successfully.", "success")
        else:
            flash("Quote saved locally (Firebase offline).", "warning")
        return redirect(url_for("quotes"))
    return render_template("quote_form.html", quote=None, clients=clients,
                           sales_people=sales_ppl, is_new=True,
                           next_num=_next_quote_number())

@app.route("/quotes/<quote_id>", methods=["GET"])
@role_required("quotes")
def quote_detail(quote_id):
    data = fb_get(f"/job_forms/{quote_id}")
    if not data:
        abort(404)
    data["firebase_id"] = quote_id

    # Linked project — stored by quote_win, or fall back to searching by source_quote
    linked_project = None
    lpid = data.get("linked_project_id")
    if lpid:
        linked_project = fb_get(f"/projects/{lpid}") or None
        if linked_project:
            linked_project["firebase_id"] = lpid
    if not linked_project:
        raw_proj = fb_get("/projects") or {}
        for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
            if isinstance(pdata, dict) and pdata.get("source_quote") == quote_id:
                pdata["firebase_id"] = pid
                linked_project = pdata
                break

    # Linked invoice
    linked_invoice = None
    liid = data.get("linked_invoice_id")
    if liid:
        linked_invoice = fb_get(f"/invoices/{liid}") or None
        if linked_invoice:
            linked_invoice["firebase_id"] = liid
    if not linked_invoice:
        raw_inv = fb_get("/invoices") or {}
        for iid, idata in (raw_inv.items() if isinstance(raw_inv, dict) else []):
            if isinstance(idata, dict) and idata.get("meta", {}).get("source_quote") == quote_id:
                idata["firebase_id"] = iid
                linked_invoice = idata
                break

    return render_template("quote_detail.html", quote=data,
                           linked_project=linked_project, linked_invoice=linked_invoice,
                           ai_enabled=bool(_get_ai_client()))

@app.route("/quotes/<quote_id>/followup-done", methods=["POST"])
@role_required("quotes")
def quote_followup_done(quote_id):
    fb_update(f"/job_forms/{quote_id}", {
        "follow_up_date": "",
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    flash("Follow-up marked as done.", "success")
    return redirect(url_for("quotes", tab="followups"))

@app.route("/quotes/<quote_id>/followup-snooze", methods=["POST"])
@role_required("quotes")
def quote_followup_snooze(quote_id):
    from datetime import timedelta
    days = int(request.form.get("days", 7))
    new_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    fb_update(f"/job_forms/{quote_id}", {
        "follow_up_date": new_date,
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    flash(f"Follow-up snoozed — rescheduled to {new_date}.", "success")
    return redirect(url_for("quotes", tab="followups"))

@app.route("/quotes/<quote_id>/duplicate", methods=["POST"])
@role_required("quotes")
def quote_duplicate(quote_id):
    original = fb_get(f"/job_forms/{quote_id}")
    if not original or not isinstance(original, dict):
        flash("Quote not found.", "danger")
        return redirect(url_for("quotes"))
    new_q = {k: v for k, v in original.items() if not k.startswith("firebase_")}
    new_q["job_number"]   = _next_quote_number()
    new_q["status"]       = "Not Started"
    new_q["date"]         = datetime.now().strftime("%Y-%m-%d")
    new_q["valid_until"]  = ""
    new_q["created_at"]   = datetime.now(timezone.utc).isoformat()
    new_q["updated_at"]   = datetime.now(timezone.utc).isoformat()
    new_q["created_by"]   = session.get("user_email", "")
    # Clear linked records — duplicate is a fresh quote
    new_q.pop("linked_project_id", None)
    new_q.pop("linked_invoice_id", None)
    key = fb_push("/job_forms", new_q)
    if key:
        flash(f"Quote duplicated as {new_q['job_number']}.", "success")
        return redirect(url_for("quote_detail", quote_id=key))
    flash("Failed to duplicate quote.", "danger")
    return redirect(url_for("quote_detail", quote_id=quote_id))

@app.route("/quotes/<quote_id>/edit", methods=["GET", "POST"])
@role_required("quotes")
def quote_edit(quote_id):
    data = fb_get(f"/job_forms/{quote_id}") or {}
    data["firebase_id"] = quote_id
    clients   = _load_clients()
    sales_ppl = _load_sales_people()
    if request.method == "POST":
        updated = _parse_quote_form(request.form)
        updated["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/job_forms/{quote_id}", updated)
        flash("Quote updated.", "success")
        return redirect(url_for("quote_detail", quote_id=quote_id))
    return render_template("quote_form.html", quote=data, clients=clients,
                           sales_people=sales_ppl, is_new=False)

@app.route("/quotes/<quote_id>/delete", methods=["POST"])
@role_required("quotes")
def quote_delete(quote_id):
    fb_delete(f"/job_forms/{quote_id}")
    flash("Quote deleted.", "success")
    return redirect(url_for("quotes"))

@app.route("/quotes/<quote_id>/status", methods=["POST"])
@role_required("quotes")
def quote_status(quote_id):
    new_status = request.form.get("status", "Not Started")
    fb_update(f"/job_forms/{quote_id}", {
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    flash(f"Status updated to {new_status}.", "success")
    return redirect(url_for("quote_detail", quote_id=quote_id))

@app.route("/projects/<project_id>/quote", methods=["GET", "POST"])
@role_required("quotes")
def project_to_quote(project_id):
    project = fb_get(f"/projects/{project_id}") or {}
    project["firebase_id"] = project_id
    clients   = _load_clients()
    sales_ppl = _load_sales_people()
    if request.method == "POST":
        data = _parse_quote_form(request.form)
        data["source_project"]     = project_id
        data["source_project_num"] = project.get("project_number", "")
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["created_by"] = session.get("user_email", "")
        key = fb_push("/job_forms", data)
        flash("Quote created from project.", "success")
        return redirect(url_for("quote_detail", quote_id=key))
    prefill = {
        "client_name":  project.get("client_name", ""),
        "project_name": project.get("project_name", ""),
        "description":  project.get("description", ""),
        "salesperson":  project.get("assigned_to", ""),
        "job_number":   "",
    }
    return render_template("quote_form.html", quote=prefill, clients=clients,
                           sales_people=sales_ppl, is_new=True,
                           next_num=_next_quote_number(),
                           from_project=project)

# ── Routes: Projects ──────────────────────────────────────────────────────────
@app.route("/projects")
@role_required("projects")
def projects():
    raw = fb_get("/projects") or {}
    items = []
    for pid, pdata in (raw.items() if isinstance(raw, dict) else []):
        if pdata and isinstance(pdata, dict):
            pdata["firebase_id"] = pid
            items.append(pdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    status_counts = {}
    for i in items:
        st = i.get("status") or "Not Started"
        status_counts[st] = status_counts.get(st, 0) + 1

    search        = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "")
    date_from     = request.args.get("from", "")
    date_to       = request.args.get("to", "")
    client_filter = request.args.get("client", "")
    if search:
        items = [i for i in items if search in str(i).lower()]
    if status_filter:
        items = [i for i in items if i.get("status", "") == status_filter]
    if client_filter:
        items = [i for i in items if i.get("client_name", "") == client_filter]
    if date_from:
        items = [i for i in items if (i.get("start_date") or i.get("created_at","")[:10]) >= date_from]
    if date_to:
        items = [i for i in items if (i.get("start_date") or i.get("created_at","")[:10]) <= date_to]

    statuses = ["Not Started", "Active", "In Progress", "On Hold", "Completed", "Cancelled"]
    clients = _load_clients()
    next_project_num = _next_project_number()
    active_tab = request.args.get("tab", "all-projects")
    return render_template("projects.html", projects=items, statuses=statuses,
                           search=search, status_filter=status_filter,
                           date_from=date_from, date_to=date_to,
                           client_filter=client_filter,
                           clients=clients, next_project_num=next_project_num,
                           active_tab=active_tab, status_counts=status_counts)

@app.route("/projects/new", methods=["GET", "POST"])
@role_required("projects")
def project_new():
    clients = _load_clients()
    if request.method == "POST":
        data = _parse_project_form(request.form)

        # Check for custom stage amounts from frontend
        custom_stage_amounts = None
        custom_stage_amounts_json = request.form.get("custom_stage_amounts", "")
        if custom_stage_amounts_json:
            try:
                import json
                custom_stage_amounts = json.loads(custom_stage_amounts_json)
                total_amount = sum(_safe_float(s.get("amount", 0)) for s in custom_stage_amounts)
                contract_value = _safe_float(data.get("contract_value", 0))

                if abs(total_amount - contract_value) > 0.01:
                    flash(f"❌ Error: Payment plan total (${total_amount:.2f}) does not match contract value (${contract_value:.2f}). Please adjust amounts and try again.", "danger")
                    return redirect(url_for("project_new"))
            except (json.JSONDecodeError, ValueError):
                custom_stage_amounts = None

        # Always generate project number server-side to prevent duplicates
        data["project_number"] = _next_project_number()
        down_pct = _safe_float(data.get("down_payment_percent", 0))
        mode, installments, custom_amounts = _resolve_installment_plan(data)
        data["down_payment_percent"]       = down_pct
        data["installment_count"]          = installments
        data["installment_mode"]           = mode
        data["custom_installment_amounts"] = custom_amounts or []

        # If custom amounts provided from frontend, use them directly
        if custom_stage_amounts:
            # Create payment stages from custom amounts
            payment_stages = []
            for idx, amount_data in enumerate(custom_stage_amounts):
                payment_stages.append({
                    "name": amount_data.get("name", f"Stage {idx+1}"),
                    "amount": _safe_float(amount_data.get("amount", 0)),
                    "status": "Pending Invoice",
                    "invoice_id": "",
                    "invoice_number": ""
                })
            data["payment_stages"] = payment_stages
        else:
            # Otherwise compute stages based on down payment and installments
            data["payment_stages"] = _compute_payment_stages(
                _safe_float(data["contract_value"]), down_pct, installments, custom_amounts=custom_amounts)
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["created_by"] = session.get("user_email", "")
        fb_push("/projects", data)
        flash(f"Project {data['project_number']} created successfully.", "success")
        return redirect(url_for("projects", tab="all-projects"))
    sales_people = [p.get("name","") for p in _load_sales_people() if p.get("name","")]
    prefill_quote = request.args.get("from_quote", "")
    next_proj_num = _next_project_number()
    return render_template("project_form.html", project=None, clients=clients,
                           sales_people=sales_people, prefill_quote=prefill_quote,
                           is_new=True, next_proj_num=next_proj_num)

@app.route("/projects/<project_id>", methods=["GET"])
@role_required("projects")
def project_detail(project_id):
    data = fb_get(f"/projects/{project_id}")
    if not data:
        abort(404)
    data["firebase_id"] = project_id
    proj_num = data.get("project_number", "")

    # Older projects stored "payment_stages" as a flat list of stage-name
    # strings (no per-stage amount/status tracking). Only the structured
    # list-of-dicts format produced by _compute_payment_stages should drive
    # the Payment Plan card — otherwise hide it rather than erroring.
    raw_stages = data.get("payment_stages")
    if not (isinstance(raw_stages, list) and raw_stages and all(isinstance(s, dict) for s in raw_stages)):
        data["payment_stages"] = []
    else:
        # Normalize old "Not Invoiced" status to "Pending Invoice"
        for stage in data["payment_stages"]:
            if stage.get("status") == "Not Invoiced":
                stage["status"] = "Pending Invoice"

    # Load invoices linked to this project (directly, or via per-line-item
    # project overrides on invoices that span multiple projects)
    raw_inv = fb_get("/invoices") or {}
    project_invoices = []
    if isinstance(raw_inv, dict):
        for iid, idata in raw_inv.items():
            if isinstance(idata, dict) and proj_num in _invoice_linked_projects(idata):
                idata["firebase_id"] = iid
                idata["_project_share"] = _invoice_project_share(idata, proj_num)
                project_invoices.append(idata)
    project_invoices.sort(key=lambda x: x.get("meta", {}).get("invoice_date", ""), reverse=True)

    # Load expenses linked to this project
    raw_exp = fb_get("/balance_sheet_expenses") or {}
    project_expenses = []
    if isinstance(raw_exp, dict):
        for eid, edata in raw_exp.items():
            if isinstance(edata, dict) and edata.get("project_number", "") == proj_num:
                edata["firebase_id"] = eid
                project_expenses.append(edata)
    project_expenses.sort(key=lambda x: x.get("date", ""), reverse=True)

    # P&L totals — invoices spanning multiple projects only count their prorated share here
    inv_total   = sum(_safe_float(i.get("meta",{}).get("total", 0))       * i.get("_project_share", 1.0) for i in project_invoices)
    inv_paid    = sum(_safe_float(i.get("meta",{}).get("amount_paid", 0)) * i.get("_project_share", 1.0) for i in project_invoices)
    exp_total   = sum(_safe_float(e.get("amount", 0))                     for e in project_expenses)
    gross_profit = inv_paid - exp_total

    # Source quote that generated this project
    source_quote = None
    sq_id = data.get("source_quote")
    if sq_id:
        source_quote = fb_get(f"/job_forms/{sq_id}") or None
        if source_quote:
            source_quote["firebase_id"] = sq_id

    # Check if project has pending stages (using desktop workflow logic)
    all_invoices = fb_get("/invoices") or {}
    detection = _get_next_payment_stage(data, all_invoices)
    has_pending_stage = detection.get("stage_name") is not None
    next_stage_idx = detection.get("stage_idx")
    next_stage_name = detection.get("stage_name", "")
    next_stage_amount = detection.get("amount", 0)

    return render_template("project_detail.html", project=data,
                           project_invoices=project_invoices,
                           project_expenses=project_expenses,
                           inv_total=inv_total, inv_paid=inv_paid,
                           exp_total=exp_total, gross_profit=gross_profit,
                           source_quote=source_quote,
                           has_pending_stage=has_pending_stage,
                           next_stage_idx=next_stage_idx,
                           next_stage_name=next_stage_name,
                           next_stage_amount=next_stage_amount)

@app.route("/projects/<project_id>/edit", methods=["GET", "POST"])
@role_required("projects")
def project_edit(project_id):
    data = fb_get(f"/projects/{project_id}") or {}
    data["firebase_id"] = project_id
    clients = _load_clients()

    # Older projects stored "payment_stages" as a flat list of stage-name
    # strings (no per-stage amount/status tracking) — normalize so the form's
    # saved-plan preview and lock check (which expect dicts) don't choke on them.
    raw_stages = data.get("payment_stages")
    if not (isinstance(raw_stages, list) and raw_stages and all(isinstance(s, dict) for s in raw_stages)):
        data["payment_stages"] = []
    else:
        # Normalize old "Not Invoiced" status to "Pending Invoice"
        for stage in data["payment_stages"]:
            if stage.get("status") == "Not Invoiced":
                stage["status"] = "Pending Invoice"
    if request.method == "POST":
        updated = _parse_project_form(request.form)
        down_pct = _safe_float(updated.get("down_payment_percent", 0))
        mode, installments, custom_amounts = _resolve_installment_plan(updated)
        updated["down_payment_percent"]       = down_pct
        updated["installment_count"]          = installments
        updated["installment_mode"]           = mode
        updated["custom_installment_amounts"] = custom_amounts or []

        # Handle updated stage amounts from contract value auto-adjustment
        updated_stage_amounts_json = request.form.get("updated_stage_amounts", "")
        if updated_stage_amounts_json:
            try:
                import json
                updated_stage_amounts = json.loads(updated_stage_amounts_json)
                # Validate that total matches contract value
                total_amount = sum(_safe_float(s.get("amount", 0)) for s in updated_stage_amounts)
                contract_value = _safe_float(updated.get("contract_value", 0))

                if abs(total_amount - contract_value) > 0.01:  # Allow 0.01 cent rounding
                    flash(f"❌ Error: Payment plan total (${total_amount:.2f}) does not match contract value (${contract_value:.2f}). Please adjust amounts and try again.", "danger")
                    return redirect(url_for("project_edit", project_id=project_id))

                # Update payment stages with updated amounts (preserving status and other fields)
                existing_stages = data.get("payment_stages") or []
                for i, amount_data in enumerate(updated_stage_amounts):
                    if i < len(existing_stages) and isinstance(existing_stages[i], dict):
                        existing_stages[i]["amount"] = _safe_float(amount_data.get("amount", 0))
                        # Preserve status and other fields
                        if "status" in amount_data:
                            existing_stages[i]["status"] = amount_data.get("status")

                updated["payment_stages"] = existing_stages
            except (json.JSONDecodeError, ValueError):
                flash("Error processing updated payment amounts.", "warning")

        # Handle custom stage amounts from frontend (for new customizations)
        custom_stage_amounts_json = request.form.get("custom_stage_amounts", "")
        if custom_stage_amounts_json and not updated_stage_amounts_json:
            try:
                import json
                custom_stage_amounts = json.loads(custom_stage_amounts_json)
                # Validate that total matches contract value
                total_amount = sum(_safe_float(s.get("amount", 0)) for s in custom_stage_amounts)
                contract_value = _safe_float(updated.get("contract_value", 0))

                if abs(total_amount - contract_value) > 0.01:  # Allow 0.01 cent rounding
                    flash(f"❌ Error: Payment plan total (${total_amount:.2f}) does not match contract value (${contract_value:.2f}). Please adjust amounts and try again.", "danger")
                    return redirect(url_for("project_edit", project_id=project_id))

                # Update payment stages with custom amounts
                existing_stages = data.get("payment_stages") or []
                for i, amount_data in enumerate(custom_stage_amounts):
                    if i < len(existing_stages) and isinstance(existing_stages[i], dict):
                        existing_stages[i]["amount"] = _safe_float(amount_data.get("amount", 0))

                updated["payment_stages"] = existing_stages
            except (json.JSONDecodeError, ValueError):
                flash("Error processing custom payment amounts. Using default distribution.", "warning")

                existing_stages = data.get("payment_stages") or []
                plan_in_progress = any(s.get("status") != "Pending Invoice" for s in existing_stages if isinstance(s, dict))
                if not plan_in_progress:
                    updated["payment_stages"] = _compute_payment_stages(
                        _safe_float(updated["contract_value"]), down_pct, installments, custom_amounts=custom_amounts)
        else:
            # No custom amounts provided, use standard logic
            existing_stages = data.get("payment_stages") or []
            plan_in_progress = any(s.get("status") != "Pending Invoice" for s in existing_stages if isinstance(s, dict))
            if plan_in_progress:
                # Stages already have invoices/payments against them — keep the plan intact
                flash("Payment plan kept as-is because one or more stages are already invoiced.", "info")
            else:
                updated["payment_stages"] = _compute_payment_stages(
                    _safe_float(updated["contract_value"]), down_pct, installments, custom_amounts=custom_amounts)

        updated["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/projects/{project_id}", updated)
        flash("Project updated successfully.", "success")
        return redirect(url_for("project_detail", project_id=project_id))
    sales_people = [p.get("name","") for p in _load_sales_people() if p.get("name","")]
    return render_template("project_form.html", project=data, clients=clients,
                           sales_people=sales_people, prefill_quote="", is_new=False)

@app.route("/projects/<project_id>/status", methods=["POST"])
@role_required("projects")
def project_status(project_id):
    new_status = request.form.get("status", "In Progress")
    fb_update(f"/projects/{project_id}", {
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    flash(f"Status updated to {new_status}.", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/projects/<project_id>/stage/<int:stage_idx>/invoice", methods=["GET"])
@role_required("projects")
def project_stage_invoice(project_id, stage_idx):
    """Kept for backwards compatibility — redirects to the old form flow."""
    project = fb_get(f"/projects/{project_id}") or {}
    stages = project.get("payment_stages") or []
    if not (0 <= stage_idx < len(stages)) or not isinstance(stages[stage_idx], dict):
        abort(404)
    stage = stages[stage_idx]
    return redirect(url_for("invoice_new",
                            project=project.get("project_number", ""),
                            client=project.get("client_name", ""),
                            stage_idx=stage_idx,
                            stage_name=stage.get("name", ""),
                            stage_amount=stage.get("amount", 0)))

def _create_stage_invoice(project_id: str, stage_idx: int, mark_paid: bool = False):
    """Create an invoice for a payment stage instantly — no form needed.
    Returns (invoice_id, error_message). If mark_paid=True, also marks it Paid
    and syncs the project payment totals.
    """
    project = fb_get(f"/projects/{project_id}") or {}
    stages  = project.get("payment_stages") or []
    if not (0 <= stage_idx < len(stages)) or not isinstance(stages[stage_idx], dict):
        return None, "Stage not found."
    first_pending = next((i for i, s in enumerate(stages) if s.get("status") == "Pending Invoice"), None)
    if first_pending is None or stage_idx != first_pending:
        return None, "That stage isn't ready yet — complete earlier stages first."

    stage      = stages[stage_idx]
    amount     = _safe_float(stage.get("amount", 0))
    proj_num   = project.get("project_number", "")
    client     = project.get("client_name", "")
    now_str    = datetime.now(timezone.utc).isoformat()
    today      = datetime.now().strftime("%Y-%m-%d")
    due_date   = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    inv_num    = _next_invoice_number()
    inv_status = "Paid" if mark_paid else "Draft"
    amt_paid   = str(amount) if mark_paid else "0"

    invoice_data = {
        "meta": {
            "invoice_number":      inv_num,
            "invoice_date":        today,
            "due_date":            due_date,
            "client_name":         client,
            "project_number":      proj_num,
            "status":              inv_status,
            "subtotal":            str(amount),
            "tax_rate":            "0",
            "tax_amount":          "0",
            "total":               str(amount),
            "amount_paid":         amt_paid,
            "notes":               "",
            "terms":               "",
            "payment_method":      "",
            "payment_stage_index": stage_idx,
            "payment_stage":       stage.get("name", ""),
            "created_at":          now_str,
            "updated_at":          now_str,
            "created_by":          session.get("user_email", ""),
        },
        "line_items": [{
            "description": stage.get("name", f"Payment Stage {stage_idx + 1}"),
            "quantity":    "1",
            "unit_price":  str(amount),
            "amount":      str(amount),
        }],
    }
    iid = fb_push("/invoices", invoice_data)
    stage_status = "Paid" if mark_paid else "Invoiced"
    _mark_project_stage(proj_num, stage_idx, stage_status, invoice_id=iid)
    if mark_paid:
        _sync_project_payment(proj_num)
        _auto_complete_project_if_paid(proj_num)
        _upsert_revenue_entry(iid, invoice_data["meta"])
    return iid, None

@app.route("/projects/<project_id>/stage/<int:stage_idx>/create-invoice", methods=["POST"])
@role_required("projects")
def project_stage_create_invoice(project_id, stage_idx):
    """One-click: create invoice for a stage instantly and go straight to it."""
    iid, err = _create_stage_invoice(project_id, stage_idx, mark_paid=False)
    if err:
        flash(err, "warning")
        return redirect(url_for("project_detail", project_id=project_id))
    flash("Invoice created.", "success")
    return redirect(url_for("invoice_detail", invoice_id=iid))

@app.route("/projects/<project_id>/stage/<int:stage_idx>/mark-paid", methods=["POST"])
@role_required("projects")
def project_stage_mark_paid(project_id, stage_idx):
    """One-click: create invoice + mark Paid immediately."""
    iid, err = _create_stage_invoice(project_id, stage_idx, mark_paid=True)
    if err:
        flash(err, "warning")
        return redirect(url_for("project_detail", project_id=project_id))
    flash("Stage marked as paid and invoice created.", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/projects/<project_id>/stage/<int:stage_idx>/set-amount", methods=["POST"])
@role_required("projects")
def project_stage_set_amount(project_id, stage_idx):
    data = fb_get(f"/projects/{project_id}")
    if not data:
        abort(404)
    stages = data.get("payment_stages") or []
    if not (0 <= stage_idx < len(stages)) or not isinstance(stages[stage_idx], dict):
        flash("Stage not found.", "danger")
        return redirect(url_for("project_detail", project_id=project_id))
    if stages[stage_idx].get("status") != "Pending":
        flash("Cannot edit amount on an already-invoiced stage.", "warning")
        return redirect(url_for("project_detail", project_id=project_id))
    try:
        new_amount = round(float(str(request.form.get("amount", "0")).replace(",", "")), 2)
    except (ValueError, TypeError):
        flash("Invalid amount.", "danger")
        return redirect(url_for("project_detail", project_id=project_id))
    stages[stage_idx]["amount"] = new_amount

    # Auto-balance: spread remaining balance equally across all OTHER pending stages
    contract_value = _safe_float(data.get("contract_value", 0))
    locked_sum = sum(
        _safe_float(s.get("amount", 0))
        for i, s in enumerate(stages)
        if i != stage_idx and isinstance(s, dict) and s.get("status") != "Pending"
    )
    other_pending = [
        i for i, s in enumerate(stages)
        if i != stage_idx and isinstance(s, dict) and s.get("status") == "Pending Invoice"
    ]
    if other_pending and contract_value > 0:
        remaining = round(contract_value - locked_sum - new_amount, 2)
        per = round(remaining / len(other_pending), 2)
        allocated = 0
        for j, idx in enumerate(other_pending):
            if j < len(other_pending) - 1:
                stages[idx]["amount"] = per
                allocated += per
            else:
                stages[idx]["amount"] = round(remaining - allocated, 2)

    fb_update(f"/projects/{project_id}", {
        "payment_stages": stages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    flash(f"Stage updated to ${new_amount:,.2f} — remaining stages adjusted to balance.", "success")
    return redirect(url_for("project_detail", project_id=project_id))

@app.route("/projects/<project_id>/delete", methods=["POST"])
@role_required("projects")
def project_delete(project_id):
    fb_delete(f"/projects/{project_id}")
    flash("Project deleted.", "success")
    return redirect(url_for("projects"))

@app.route("/projects/<project_id>/notes/add", methods=["POST"])
@role_required("projects")
def project_note_add(project_id):
    text = request.form.get("note_text", "").strip()
    if not text:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("project_detail", project_id=project_id) + "#tab-notes")
    project = fb_get(f"/projects/{project_id}") or {}
    log = project.get("activity_log") or []
    if not isinstance(log, list):
        log = []
    log.append({
        "text":       text,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": session.get("user_name") or session.get("user_email", ""),
    })
    fb_update(f"/projects/{project_id}", {
        "activity_log": log,
        "updated_at":   datetime.now(timezone.utc).isoformat(),
    })
    return redirect(url_for("project_detail", project_id=project_id) + "#tab-notes")

@app.route("/projects/<project_id>/notes/<int:idx>/delete", methods=["POST"])
@role_required("projects")
def project_note_delete(project_id, idx):
    project = fb_get(f"/projects/{project_id}") or {}
    log = project.get("activity_log") or []
    if isinstance(log, list) and 0 <= idx < len(log):
        log.pop(idx)
        fb_update(f"/projects/{project_id}", {
            "activity_log": log,
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
    return redirect(url_for("project_detail", project_id=project_id) + "#tab-notes")

# ── Routes: Projects Export ───────────────────────────────────────────────────
def _filter_projects_export(items):
    if request.args.get("status"):
        items = [i for i in items if i.get("status","") == request.args["status"]]
    if request.args.get("client"):
        items = [i for i in items if i.get("client_name","") == request.args["client"]]
    date_from = request.args.get("from","")
    date_to   = request.args.get("to","")
    if date_from:
        items = [i for i in items if (i.get("start_date") or i.get("created_at","")[:10]) >= date_from]
    if date_to:
        items = [i for i in items if (i.get("start_date") or i.get("created_at","")[:10]) <= date_to]
    return items

@app.route("/projects/export/csv")
@role_required("projects")
def projects_export_csv():
    import csv, io
    raw = fb_get("/projects") or {}
    items = []
    for pid, pdata in (raw.items() if isinstance(raw, dict) else []):
        if pdata and isinstance(pdata, dict):
            items.append(pdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = _filter_projects_export(items)
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Project #","Name","Client","Start Date","End Date","Status",
                "Contract Value","Amount Paid","Outstanding","Payment Stage","Assigned To"])
    for p in items:
        cv   = _safe_float(p.get("contract_value", 0))
        paid = _safe_float(p.get("amount_paid", 0))
        w.writerow([p.get("project_number",""), p.get("project_name",""),
                    p.get("client_name",""), p.get("start_date",""), p.get("end_date",""),
                    p.get("status",""), f"{cv:.2f}", f"{paid:.2f}", f"{cv-paid:.2f}",
                    p.get("payment_category",""), p.get("assigned_to","")])
    output.seek(0)
    from flask import Response
    fname = f"projects_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/projects/export/excel")
@role_required("projects")
def projects_export_excel():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    import io as _io
    raw = fb_get("/projects") or {}
    items = []
    for pid, pdata in (raw.items() if isinstance(raw, dict) else []):
        if pdata and isinstance(pdata, dict):
            items.append(pdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = _filter_projects_export(items)
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Projects"
    hdr_fill = PatternFill(start_color="FF0F172A", end_color="FF0F172A", fill_type="solid")
    hdr_font = Font(color="FFFFFFFF", bold=True, size=11)
    alt_fill = PatternFill(start_color="FFF8FAFC", end_color="FFF8FAFC", fill_type="solid")
    ctr = Alignment(horizontal="center", vertical="center")
    rgt = Alignment(horizontal="right",  vertical="center")
    headers = ["Project #","Name","Client","Start Date","End Date","Status",
               "Contract Value ($)","Amount Paid ($)","Outstanding ($)","Payment Stage","Assigned To"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill; cell.font = hdr_font; cell.alignment = ctr
    for ri, p in enumerate(items, 2):
        cv   = _safe_float(p.get("contract_value", 0))
        paid = _safe_float(p.get("amount_paid", 0))
        row = [p.get("project_number",""), p.get("project_name",""),
               p.get("client_name",""), p.get("start_date",""), p.get("end_date",""),
               p.get("status",""), cv, paid, cv - paid,
               p.get("payment_category",""), p.get("assigned_to","")]
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            if ri % 2 == 0: cell.fill = alt_fill
            if ci in (7, 8, 9):
                cell.number_format = '"$"#,##0.00'; cell.alignment = rgt
    for ci, w in enumerate([16, 30, 22, 12, 12, 14, 16, 14, 14, 16, 18], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"
    buf = _io.BytesIO()
    wb.save(buf); buf.seek(0)
    from flask import Response
    fname = f"projects_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/projects/export/pdf")
@role_required("projects")
def projects_export_pdf():
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("projects", tab="export"))
    import io as _io
    raw = fb_get("/projects") or {}
    items = []
    for pid, pdata in (raw.items() if isinstance(raw, dict) else []):
        if pdata and isinstance(pdata, dict):
            items.append(pdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = _filter_projects_export(items)
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=0.5*inch, rightMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    co = company_info()
    elems = []
    title_s = ParagraphStyle("T", parent=styles["Normal"], fontSize=15,
                              fontName="Helvetica-Bold",
                              textColor=colors.HexColor("#0F766E"), spaceAfter=3)
    sub_s   = ParagraphStyle("S", parent=styles["Normal"], fontSize=9,
                              textColor=colors.HexColor("#64748B"), spaceAfter=14)
    elems.append(Paragraph(f"{co.get('name','')} — Projects Report", title_s))
    elems.append(Paragraph(
        f"Generated {datetime.now().strftime('%B %d, %Y')}  ·  {len(items)} record{'s' if len(items)!=1 else ''}",
        sub_s))
    hdrs = ["Project #", "Name", "Client", "Status", "Start Date", "Contract Value", "Paid", "Outstanding"]
    data = [hdrs]
    for p in items:
        cv   = _safe_float(p.get("contract_value", 0))
        paid = _safe_float(p.get("amount_paid", 0))
        data.append([
            p.get("project_number","—"),
            (p.get("project_name","—") or "—")[:30],
            (p.get("client_name","—") or "—")[:22],
            p.get("status","—"),
            p.get("start_date","—") or "—",
            f"${cv:,.0f}",
            f"${paid:,.0f}",
            f"${cv-paid:,.0f}",
        ])
    cw = [1.4*inch, 2.4*inch, 1.8*inch, 1.2*inch, 1.0*inch, 1.2*inch, 1.0*inch, 1.0*inch]
    tbl = Table(data, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 9),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,0), 8),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID",          (0,0), (-1,-1), 0.4, colors.HexColor("#E2E8F0")),
        ("TOPPADDING",    (0,1), (-1,-1), 5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
        ("ALIGN",         (-3,1),(-1,-1), "RIGHT"),
        ("FONTNAME",      (-3,1),(-1,-1), "Helvetica-Bold"),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buf.seek(0)
    from flask import Response
    fname = f"projects_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

# ── Routes: Invoicing ─────────────────────────────────────────────────────────
@app.route("/invoicing")
@role_required("invoicing")
def invoicing():
    _auto_flag_overdue()
    raw = fb_get("/invoices") or {}
    items = []
    for iid, idata in (raw.items() if isinstance(raw, dict) else []):
        if idata and isinstance(idata, dict):
            idata["firebase_id"] = iid
            items.append(idata)
    items.sort(key=lambda x: x.get("meta", {}).get("created_at", ""), reverse=True)

    search        = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "")
    date_from     = request.args.get("from", "")
    date_to       = request.args.get("to", "")
    client_filter = request.args.get("client", "")
    if search:
        items = [i for i in items if search in str(i).lower()]
    if status_filter:
        items = [i for i in items if i.get("meta", {}).get("status", "") == status_filter]
    if client_filter:
        items = [i for i in items if i.get("meta", {}).get("client_name", "") == client_filter]
    if date_from:
        items = [i for i in items if (i.get("meta", {}).get("invoice_date") or "") >= date_from]
    if date_to:
        items = [i for i in items if (i.get("meta", {}).get("invoice_date") or "") <= date_to]

    # Build client list for filter dropdown
    inv_clients = sorted({i.get("meta", {}).get("client_name", "") for i in items if i.get("meta", {}).get("client_name", "")})

    # Auto-mark overdue: any Sent/Viewed invoice past its due date
    today_str = datetime.now().strftime("%Y-%m-%d")
    for inv in items:
        m = inv.get("meta", {})
        due = m.get("due_date", "") or ""
        if m.get("status") in ("Sent", "Viewed") and due and due < today_str:
            fb_update(f"/invoices/{inv['firebase_id']}", {
                "meta/status": "Overdue",
                "meta/updated_at": datetime.now(timezone.utc).isoformat()
            })
            m["status"] = "Overdue"

    statuses = ["Draft", "Sent", "Viewed", "Paid", "Partial", "Overdue", "Cancelled"]
    active_tab = request.args.get("tab", "all-invoices")
    return render_template("invoicing.html", invoices=items, statuses=statuses,
                           search=search, status_filter=status_filter,
                           date_from=date_from, date_to=date_to,
                           client_filter=client_filter, inv_clients=inv_clients,
                           active_tab=active_tab)

@app.route("/api/projects/<project_ids>", methods=["GET"])
@role_required("projects")
def api_get_projects(project_ids):
    """API endpoint to get project data with payment stage detection (desktop workflow logic)"""
    ids = [pid.strip() for pid in project_ids.split(",") if pid.strip()]
    all_projects = fb_get("/projects") or {}
    all_invoices = fb_get("/invoices") or {}

    projects = []
    for proj_id in ids:
        if proj_id in all_projects:
            proj = all_projects[proj_id]
            if isinstance(proj, dict):
                proj["firebase_id"] = proj_id

                # Use new detection logic (works with payment_stages, applies desktop workflow)
                try:
                    detection = _get_next_payment_stage(proj, all_invoices)
                    if detection.get("stage_name"):
                        proj["next_stage"] = detection.get("stage_name")
                        proj["next_stage_amount"] = detection.get("amount", 0)
                    else:
                        proj["next_stage"] = "Fully Invoiced"
                        proj["next_stage_amount"] = 0
                    proj["stage_blocked"] = detection.get("blocked", False)
                    proj["stage_reason"] = detection.get("reason", "")
                except Exception as e:
                    log.error(f"Error detecting stage for {proj_id}: {e}")
                    proj["next_stage"] = "Error"
                    proj["next_stage_amount"] = 0
                    proj["stage_blocked"] = True
                    proj["stage_reason"] = str(e)

                projects.append(proj)

    return jsonify(projects)

@app.route("/invoicing/create-bulk", methods=["POST"])
@role_required("invoicing")
def create_bulk_invoices():
    """Create invoices for multiple projects' next stages."""
    project_ids = request.form.get("project_ids", "").split(",")
    project_ids = [pid.strip() for pid in project_ids if pid.strip()]

    if not project_ids:
        return jsonify({"success": False, "error": "No projects selected"}), 400

    all_projects = fb_get("/projects") or {}
    all_invoices = fb_get("/invoices") or {}
    created_invoice_ids = []

    try:
        for proj_id in project_ids:
            if proj_id not in all_projects:
                continue

            proj_data = all_projects[proj_id]
            if not isinstance(proj_data, dict):
                continue

            proj_num = proj_data.get("project_number", "")
            proj_name = proj_data.get("project_name", "")
            client_name = proj_data.get("client_name", "") or proj_data.get("company", "")
            stages = proj_data.get("payment_stages", [])

            if not isinstance(stages, list) or not stages:
                continue

            # Find which stages have been invoiced
            invoiced_stages = set()
            if isinstance(all_invoices, dict):
                for inv_data in all_invoices.values():
                    if isinstance(inv_data, dict) and inv_data.get("meta", {}).get("project_number", "") == proj_num:
                        stage_idx = inv_data.get("meta", {}).get("payment_stage_index")
                        if stage_idx is not None:
                            invoiced_stages.add(int(stage_idx))

            # Find first stage NOT invoiced
            next_stage_idx = None
            next_stage = None
            for idx, stage in enumerate(stages):
                if isinstance(stage, dict) and idx not in invoiced_stages:
                    next_stage_idx = idx
                    next_stage = stage
                    break

            if next_stage_idx is None or next_stage is None:
                # All stages already invoiced, skip this project
                continue

            # Build invoice data
            stage_name = next_stage.get("name", f"Stage {next_stage_idx + 1}")
            stage_amount = _safe_float(next_stage.get("amount", 0))

            invoice_data = {
                "meta": {
                    "invoice_number": _next_invoice_number(),
                    "project_number": proj_num,
                    "client_name": client_name,
                    "invoice_date": datetime.now().strftime("%Y-%m-%d"),
                    "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                    "status": "Draft",
                    "payment_stage_index": next_stage_idx,
                    "payment_stage": stage_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "created_by": session.get("user_email", "")
                },
                "line_items": [
                    {
                        "description": f"{proj_name} — {stage_name}",
                        "project_number": proj_num,
                        "quantity": 1,
                        "unit_price": stage_amount,
                        "amount": stage_amount
                    }
                ]
            }

            # Create the invoice
            inv_id = fb_push("/invoices", invoice_data)
            created_invoice_ids.append(inv_id)

            # Mark stage as Invoiced
            _mark_project_stage(proj_num, next_stage_idx, "Invoiced", invoice_id=inv_id)

        if created_invoice_ids:
            flash(f"Created {len(created_invoice_ids)} invoice(s) successfully.", "success")
            return jsonify({"success": True, "invoice_ids": created_invoice_ids})
        else:
            return jsonify({"success": False, "error": "No invoices created. All selected projects may be fully invoiced."}), 400

    except Exception as e:
        import traceback
        log.error("Bulk invoice creation error: %s", traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/invoicing/new", methods=["GET", "POST"])
@role_required("invoicing")
def invoice_new():
    clients  = _load_clients()
    projects = _load_projects_list()
    if request.method == "POST":
        data = _parse_invoice_form(request.form)
        project_number = data["meta"].get("project_number", "")

        # Get all projects and invoices for validation
        all_projects = fb_get("/projects") or {}
        raw_invoices = fb_get("/invoices") or {}

        # Check line items for duplicate stage invoicing
        item_projects = request.form.getlist("item_project[]")
        item_stage_indices = request.form.getlist("item_stage_index[]")

        # Find which stages are already invoiced
        invoiced_stages_map = {}  # {project_number: {stage_idx}}
        if isinstance(raw_invoices, dict):
            for inv_data in raw_invoices.values():
                if isinstance(inv_data, dict):
                    inv_proj = inv_data.get("meta", {}).get("project_number", "")
                    stage_idx = inv_data.get("meta", {}).get("payment_stage_index")
                    if inv_proj and stage_idx is not None:
                        if inv_proj not in invoiced_stages_map:
                            invoiced_stages_map[inv_proj] = set()
                        invoiced_stages_map[inv_proj].add(int(stage_idx))

        # Check if any line item's stage is already invoiced
        duplicate_stages = []
        for i, proj_num in enumerate(item_projects):
            if i < len(item_stage_indices) and item_stage_indices[i]:
                try:
                    stage_idx = int(item_stage_indices[i])
                    if proj_num in invoiced_stages_map and stage_idx in invoiced_stages_map[proj_num]:
                        duplicate_stages.append(f"{proj_num} - Stage {stage_idx + 1}")
                except (ValueError, IndexError):
                    pass

        if duplicate_stages:
            flash(f"Cannot create invoice. The following stages are already invoiced: {', '.join(duplicate_stages)}", "danger")
            return redirect(url_for("invoice_new"))

        # Check if project is fully invoiced
        if project_number:
            for pid, pdata in (all_projects.items() if isinstance(all_projects, dict) else []):
                if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
                    stages = pdata.get("payment_stages", [])
                    if isinstance(stages, list) and stages:
                        # Count how many stages have invoices
                        stages_with_invoices = set()
                        if isinstance(raw_invoices, dict):
                            for iid, idata in raw_invoices.items():
                                if isinstance(idata, dict):
                                    inv_proj = idata.get("meta", {}).get("project_number", "")
                                    if inv_proj == project_number:
                                        stage_idx = idata.get("meta", {}).get("payment_stage_index")
                                        if stage_idx is not None:
                                            stages_with_invoices.add(int(stage_idx))

                        # Check if all stages have invoices
                        total_stages = len([s for s in stages if isinstance(s, dict)])
                        if total_stages > 0 and len(stages_with_invoices) >= total_stages:
                            flash("This project has already been fully invoiced. All payment stages have invoices created.", "warning")
                            return redirect(url_for("project_detail", project_id=pid))
                    break

        data["meta"]["created_at"] = datetime.now(timezone.utc).isoformat()
        data["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["meta"]["created_by"] = session.get("user_email", "")

        stage_idx_raw = request.form.get("payment_stage_index", "")
        stage_name    = request.form.get("payment_stage", "")

        # If no stage was explicitly selected, auto-detect the first pending stage
        if stage_idx_raw == "":
            proj_num = data["meta"].get("project_number", "")
            if proj_num:
                all_projects = fb_get("/projects") or {}
                for pid, pdata in (all_projects.items() if isinstance(all_projects, dict) else []):
                    if isinstance(pdata, dict) and pdata.get("project_number", "") == proj_num:
                        stages = pdata.get("payment_stages", [])
                        if isinstance(stages, list) and stages:
                            # Find first pending stage
                            found_pending = False
                            for idx, stage in enumerate(stages):
                                if isinstance(stage, dict) and stage.get("status") == "Pending Invoice":
                                    stage_idx_raw = str(idx)
                                    stage_name = stage.get("name", f"Stage {idx + 1}")
                                    found_pending = True
                                    break

                            # If no pending stage found, all stages are already invoiced
                            if not found_pending:
                                flash("This project has already been fully invoiced. All payment stages have been invoiced.", "warning")
                                return redirect(url_for("project_detail", project_id=pid))
                        break

        if stage_idx_raw != "":
            data["meta"]["payment_stage_index"] = int(stage_idx_raw)
            data["meta"]["payment_stage"]       = stage_name

        inv_id = fb_push("/invoices", data)
        invoice_number = data["meta"].get("invoice_number", "")

        # Mark stages as invoiced
        if stage_idx_raw != "":
            # Single project with single stage
            _mark_project_stage(data["meta"].get("project_number", ""),
                                int(stage_idx_raw), "Invoiced", invoice_id=inv_id, invoice_number=invoice_number)
        else:
            # Multiple projects - check if line items have stage indices
            item_projects = request.form.getlist("item_project[]")
            item_stage_indices = request.form.getlist("item_stage_index[]")

            # Store linked projects info for multi-project invoice detection
            linked_projects = []

            # Mark each stage from line items
            for i, proj_num in enumerate(item_projects):
                if i < len(item_stage_indices):
                    stage_idx_str = item_stage_indices[i].strip() if item_stage_indices[i] else ""
                    if stage_idx_str:
                        try:
                            stage_idx = int(stage_idx_str)
                            _mark_project_stage(proj_num, stage_idx, "Invoiced", invoice_id=inv_id, invoice_number=invoice_number)
                            linked_projects.append({"project_number": proj_num, "payment_stage_index": stage_idx})
                        except (ValueError, IndexError):
                            pass

            # Update invoice metadata with linked projects for multi-project invoices
            if linked_projects:
                fb_update(f"/invoices/{inv_id}", {"meta/linked_projects": linked_projects})

        flash("Invoice created successfully.", "success")
        return redirect(url_for("invoicing", tab="all-invoices"))
    next_num     = _next_invoice_number()
    prefill_proj = request.args.get("project", "")
    prefill_client = request.args.get("client", "")
    stage_idx    = request.args.get("stage_idx", "")
    stage_name   = request.args.get("stage_name", "")
    stage_amount = request.args.get("stage_amount", "")
    multiple_projects = request.args.get("projects", "")  # Comma-separated firebase IDs

    print(f"\n=== INVOICE_NEW GET REQUEST ===", flush=True)
    print(f"All args: {dict(request.args)}", flush=True)
    print(f"multiple_projects value: '{multiple_projects}'", flush=True)

    prefill_name   = ""
    prefill_amount = ""
    prefill_items  = []

    # Handle multiple projects from modal (one line item per project, matching desktop software)
    if multiple_projects:
        project_ids = [pid.strip() for pid in multiple_projects.split(",") if pid.strip()]
        all_projects_data = fb_get("/projects") or {}
        raw_invoices = fb_get("/invoices") or {}

        for proj_id in project_ids:
            if proj_id in all_projects_data:
                proj_data = all_projects_data[proj_id]
                if isinstance(proj_data, dict):
                    proj_num = proj_data.get("project_number", "")
                    proj_name = proj_data.get("project_name", "")

                    # Detect next payment stage for this project
                    detection = _get_next_payment_stage(proj_data, raw_invoices)
                    next_stage_idx = detection.get("stage_idx")
                    next_stage_name = detection.get("stage_name")
                    stage_amount = detection.get("amount", 0)

                    # Use stage amount if available, otherwise use outstanding balance
                    if stage_amount > 0 and next_stage_idx is not None:
                        amount_to_invoice = stage_amount
                    else:
                        contract_value = _safe_float(proj_data.get("contract_value", 0))
                        amount_paid = _safe_float(proj_data.get("amount_paid", 0))
                        outstanding = contract_value - amount_paid
                        amount_to_invoice = outstanding if outstanding > 0 else contract_value

                    if amount_to_invoice > 0:
                        # Include stage name in description if available
                        description = proj_name
                        if next_stage_name:
                            description = f"{proj_name} — {next_stage_name}"

                        prefill_items.append({
                            "description": description,
                            "project": proj_num,
                            "amount": f"{amount_to_invoice:.2f}",
                            "stage_index": next_stage_idx  # Store the detected stage index
                        })

                    # Use first project for client field
                    if not prefill_client:
                        prefill_client = proj_data.get("client_name", "") or proj_data.get("company", "")

    # Set prefill_name and prefill_amount when single project is selected (with or without stage_idx)
    if prefill_proj:
        for p in projects:
            if p.get("project_number", "") == prefill_proj:
                prefill_name = p.get("project_name", "")
                if not stage_idx:  # Only set amount if no stage is specified
                    outstanding  = _safe_float(p.get("contract_value", 0)) - _safe_float(p.get("amount_paid", 0))
                    prefill_amount = f"{outstanding:.2f}" if outstanding > 0 else f"{_safe_float(p.get('contract_value', 0)):.2f}"
                break

    # Build invoiced stages map for display
    invoiced_stages_map = {}
    raw_inv = fb_get("/invoices") or {}
    if isinstance(raw_inv, dict):
        for inv_data in raw_inv.values():
            if isinstance(inv_data, dict):
                inv_proj = inv_data.get("meta", {}).get("project_number", "")
                inv_stage_idx = inv_data.get("meta", {}).get("payment_stage_index")
                if inv_proj and inv_stage_idx is not None:
                    if inv_proj not in invoiced_stages_map:
                        invoiced_stages_map[inv_proj] = set()
                    invoiced_stages_map[inv_proj].add(int(inv_stage_idx))

    print(f"\n=== RENDERING TEMPLATE ===", flush=True)
    print(f"stage_idx='{stage_idx}', stage_idx != '' = {stage_idx != ''}", flush=True)
    print(f"prefill_items type: {type(prefill_items)}, length: {len(prefill_items) if isinstance(prefill_items, list) else 'N/A'}", flush=True)
    print(f"prefill_proj='{prefill_proj}'", flush=True)
    print(f"Condition check: stage_idx != '' = {stage_idx != ''}, prefill_items length = {len(prefill_items) if isinstance(prefill_items, list) else 0}", flush=True)

    # Lock unit price if loading from project payment stages
    lock_unit_price = isinstance(prefill_items, list) and len(prefill_items) > 0

    return render_template("invoice_form.html", invoice=None, clients=clients,
                           projects=projects, next_num=next_num, is_new=True,
                           prefill_proj=prefill_proj, prefill_client=prefill_client,
                           prefill_name=prefill_name, prefill_amount=prefill_amount,
                           prefill_items=prefill_items,
                           stage_idx=stage_idx, stage_name=stage_name, stage_amount=stage_amount,
                           invoiced_stages_map=invoiced_stages_map, lock_unit_price=lock_unit_price)

@app.route("/invoicing/<invoice_id>", methods=["GET"])
@role_required("invoicing")
def invoice_detail(invoice_id):
    data = fb_get(f"/invoices/{invoice_id}")
    if not data:
        abort(404)
    data["firebase_id"] = invoice_id

    # Linked project(s) — an invoice can bill multiple projects via per-line-item overrides
    linked_project = None
    linked_projects = []
    proj_num = data.get("meta", {}).get("project_number", "")
    all_proj_nums = _invoice_linked_projects(data)

    # Calculate amount paid per project from payment_log
    payment_log = data.get("payment_log", [])
    if not isinstance(payment_log, list):
        payment_log = []

    if proj_num or all_proj_nums:
        raw_proj = fb_get("/projects") or {}
        for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
            if not isinstance(pdata, dict):
                continue
            num = pdata.get("project_number")
            if num == proj_num or num in all_proj_nums:
                pdata = dict(pdata)
                pdata["firebase_id"] = pid
                pdata["_share"] = _invoice_project_share(data, num)
                # Calculate amount paid to this specific project
                proj_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log if p.get("project_number") == num)
                pdata["_paid"] = proj_paid
                if num == proj_num:
                    linked_project = pdata
                linked_projects.append(pdata)

    # Enrich payment_log with project names and stage names
    raw_proj = fb_get("/projects") or {}
    enriched_payment_log = []
    for payment in payment_log:
        payment_copy = dict(payment)
        proj_num = payment_copy.get("project_number", "")

        if proj_num:
            # Find project data to get name and stage
            for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
                if not isinstance(pdata, dict):
                    continue
                if pdata.get("project_number") == proj_num:
                    payment_copy["project_name"] = pdata.get("project_name", "")
                    # Find the stage name from payment_stages
                    stages = pdata.get("payment_stages", [])
                    if isinstance(stages, list):
                        for stage in stages:
                            if isinstance(stage, dict) and stage.get("invoice_id") == invoice_id:
                                payment_copy["stage_name"] = stage.get("name", "Invoice Payment")
                                break
                    break
        enriched_payment_log.append(payment_copy)

    # Tax payments kept separate from projects (no enrichment with project data)
    tax_log = data.get("tax_payments", [])
    if not isinstance(tax_log, list):
        tax_log = []
    enriched_tax_payments = [dict(payment) for payment in tax_log]

    # Source quote — via the linked project's source_quote field
    source_quote = None
    if linked_project:
        sq_id = linked_project.get("source_quote")
        if sq_id:
            source_quote = fb_get(f"/job_forms/{sq_id}") or None
            if source_quote:
                source_quote["firebase_id"] = sq_id

    return render_template("invoice_detail.html", invoice=data, company=company_info(),
                           today_date=datetime.now().strftime("%Y-%m-%d"),
                           linked_project=linked_project, linked_projects=linked_projects,
                           source_quote=source_quote, enriched_payment_log=enriched_payment_log,
                           enriched_tax_payments=enriched_tax_payments)

@app.route("/invoicing/<invoice_id>/edit", methods=["GET", "POST"])
@role_required("invoicing")
def invoice_edit(invoice_id):
    data = fb_get(f"/invoices/{invoice_id}") or {}
    data["firebase_id"] = invoice_id
    clients  = _load_clients()
    projects = _load_projects_list()
    if request.method == "POST":
        updated = _parse_invoice_form(request.form)
        updated["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/invoices/{invoice_id}", updated)
        for proj_num in _invoice_linked_projects(updated):
            _sync_project_payment(proj_num)
            if updated["meta"].get("status") == "Paid":
                _auto_complete_project_if_paid(proj_num)
        if updated["meta"].get("status") in ("Paid", "Partial"):
            _upsert_revenue_entry(invoice_id, updated["meta"])
        flash("Invoice updated.", "success")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))
    # Lock unit price if invoice has linked projects (created from payment stages)
    linked_projects = data.get("meta", {}).get("linked_projects", [])
    lock_unit_price = isinstance(linked_projects, list) and len(linked_projects) > 0

    return render_template("invoice_form.html", invoice=data, clients=clients,
                           projects=projects, next_num=None, is_new=False, lock_unit_price=lock_unit_price)

@app.route("/invoicing/<invoice_id>/status", methods=["POST"])
@role_required("invoicing")
def invoice_status(invoice_id):
    new_status       = request.form.get("status", "Draft")
    amount_paid      = request.form.get("amount_paid", "")
    payment_method   = request.form.get("payment_method", "")
    payment_ref      = request.form.get("payment_reference", "")
    updates = {
        "meta/status":     new_status,
        "meta/updated_at": datetime.now(timezone.utc).isoformat()
    }
    if amount_paid:
        updates["meta/amount_paid"] = amount_paid
    if payment_method:
        updates["meta/payment_method"] = payment_method
    if payment_ref:
        updates["meta/payment_reference"] = payment_ref
    fb_update(f"/invoices/{invoice_id}", updates)

    # ── Auto-sync: re-read fresh meta then sync project + balance sheet ──────
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    m = inv_data.get("meta", {})
    main_proj_num = m.get("project_number", "")
    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)
        if new_status == "Paid":
            _auto_complete_project_if_paid(proj_num)
    if main_proj_num:
        # Roll the linked payment-plan stage's status forward with the invoice
        # (stages live on the invoice's main project only)
        stage_idx_meta = m.get("payment_stage_index")
        if stage_idx_meta is not None and stage_idx_meta != "":
            stage_status = {
                "Paid": "Paid",
                "Partial": "Partially Paid",
                "Draft": "Invoiced",
                "Sent": "Invoiced",
                "Viewed": "Invoiced",
                "Overdue": "Invoiced",
            }.get(new_status)
            if stage_status:
                _mark_project_stage(main_proj_num, int(stage_idx_meta), stage_status, invoice_id=invoice_id)
    if new_status in ("Paid", "Partial"):
        _upsert_revenue_entry(invoice_id, m)

    flash(f"Invoice updated to {new_status}. Project & balance sheet synced.", "success")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))

@app.route("/invoicing/<invoice_id>/delete", methods=["POST"])
@role_required("invoicing")
def invoice_delete(invoice_id):
    # Get invoice data before deleting
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    meta = inv_data.get("meta", {})

    print(f"\n=== INVOICE DELETE DEBUG ===", flush=True)
    print(f"Invoice ID: {invoice_id}", flush=True)
    print(f"Meta data: {meta}", flush=True)

    # Revert payment stages back to "Pending"
    project_number = meta.get("project_number", "")
    payment_stage_index = meta.get("payment_stage_index")

    print(f"project_number: '{project_number}', payment_stage_index: {payment_stage_index}", flush=True)

    if project_number and payment_stage_index is not None:
        # Single project with single stage
        print(f"Reverting single stage: {project_number} stage {payment_stage_index}", flush=True)
        _mark_project_stage(project_number, payment_stage_index, "Pending Invoice")
    else:
        # Multiple projects - check linked_projects first, then line items
        linked_projects = meta.get("linked_projects", [])
        print(f"Linked projects: {linked_projects}", flush=True)
        if isinstance(linked_projects, list) and linked_projects:
            for lp in linked_projects:
                if isinstance(lp, dict):
                    proj_num = lp.get("project_number", "")
                    stage_idx = lp.get("payment_stage_index")
                    print(f"Processing linked project: proj_num={proj_num}, stage_idx={stage_idx}", flush=True)
                    if proj_num and stage_idx is not None:
                        _mark_project_stage(proj_num, stage_idx, "Pending Invoice")
        else:
            # Fallback: check line items for older invoices
            line_items = inv_data.get("line_items", [])
            print(f"Line items: {line_items}", flush=True)
            if isinstance(line_items, list):
                for item in line_items:
                    if isinstance(item, dict):
                        proj_num = item.get("project_number", "") or item.get("project", "")
                        stage_idx = item.get("stage_index")
                        print(f"Processing line item: proj_num={proj_num}, stage_idx={stage_idx}", flush=True)
                        if proj_num and stage_idx is not None:
                            _mark_project_stage(proj_num, stage_idx, "Pending Invoice")

    # Delete associated revenue entries
    all_revenue = fb_get("/balance_sheet_revenue") or {}
    if isinstance(all_revenue, dict):
        for rev_id, rev_data in list(all_revenue.items()):
            if isinstance(rev_data, dict) and rev_data.get("invoice_id") == invoice_id:
                fb_delete(f"/balance_sheet_revenue/{rev_id}")
                print(f"Deleted revenue entry: {rev_id}", flush=True)

    # Delete the invoice
    fb_delete(f"/invoices/{invoice_id}")
    print(f"=== INVOICE DELETE COMPLETE ===\n", flush=True)
    flash("Invoice deleted. Payment stages and revenue reverted to Not Invoiced.", "success")
    return redirect(url_for("invoicing"))

# ── Routes: Invoicing Export ──────────────────────────────────────────────────
def _filter_invoices_export(items):
    if request.args.get("status"):
        items = [i for i in items if i.get("meta",{}).get("status","") == request.args["status"]]
    if request.args.get("client"):
        items = [i for i in items if i.get("meta",{}).get("client_name","") == request.args["client"]]
    date_from = request.args.get("from","")
    date_to   = request.args.get("to","")
    if date_from:
        items = [i for i in items if (i.get("meta",{}).get("invoice_date") or "") >= date_from]
    if date_to:
        items = [i for i in items if (i.get("meta",{}).get("invoice_date") or "") <= date_to]
    return items

@app.route("/invoicing/export/csv")
@role_required("invoicing")
def invoicing_export_csv():
    import csv, io
    raw = fb_get("/invoices") or {}
    items = []
    for iid, idata in (raw.items() if isinstance(raw, dict) else []):
        if idata and isinstance(idata, dict):
            items.append(idata)
    items.sort(key=lambda x: x.get("meta", {}).get("created_at", ""), reverse=True)
    items = _filter_invoices_export(items)
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Invoice #","Client","Project","Date","Due Date","Status",
                "Subtotal","Tax","Total","Amount Paid","Outstanding"])
    for inv in items:
        m = inv.get("meta", {})
        total = _safe_float(m.get("total", 0))
        paid  = _safe_float(m.get("amount_paid", 0))
        w.writerow([m.get("invoice_number",""), m.get("client_name",""),
                    m.get("project_number",""), m.get("invoice_date",""), m.get("due_date",""),
                    m.get("status",""), m.get("subtotal","0"), m.get("tax_amount","0"),
                    f"{total:.2f}", f"{paid:.2f}", f"{total-paid:.2f}"])
    output.seek(0)
    from flask import Response
    fname = f"invoices_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/invoicing/export/excel")
@role_required("invoicing")
def invoicing_export_excel():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    import io as _io
    raw = fb_get("/invoices") or {}
    items = []
    for iid, idata in (raw.items() if isinstance(raw, dict) else []):
        if idata and isinstance(idata, dict):
            items.append(idata)
    items.sort(key=lambda x: x.get("meta", {}).get("created_at", ""), reverse=True)
    items = _filter_invoices_export(items)
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Invoices"
    hdr_fill = PatternFill(start_color="FF0F172A", end_color="FF0F172A", fill_type="solid")
    hdr_font = Font(color="FFFFFFFF", bold=True, size=11)
    alt_fill = PatternFill(start_color="FFF8FAFC", end_color="FFF8FAFC", fill_type="solid")
    ctr = Alignment(horizontal="center", vertical="center")
    rgt = Alignment(horizontal="right",  vertical="center")
    headers = ["Invoice #","Client","Project","Date","Due Date","Status",
               "Subtotal ($)","Tax ($)","Total ($)","Paid ($)","Outstanding ($)"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill; cell.font = hdr_font; cell.alignment = ctr
    for ri, inv in enumerate(items, 2):
        m = inv.get("meta", {})
        total = _safe_float(m.get("total", 0))
        paid  = _safe_float(m.get("amount_paid", 0))
        row = [m.get("invoice_number",""), m.get("client_name",""),
               m.get("project_number",""), m.get("invoice_date",""), m.get("due_date",""),
               m.get("status",""), _safe_float(m.get("subtotal",0)),
               _safe_float(m.get("tax_amount",0)), total, paid, total - paid]
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            if ri % 2 == 0: cell.fill = alt_fill
            if ci in (7, 8, 9, 10, 11):
                cell.number_format = '"$"#,##0.00'; cell.alignment = rgt
    for ci, w in enumerate([16,22,14,12,12,12,13,10,13,12,14], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"
    buf = _io.BytesIO()
    wb.save(buf); buf.seek(0)
    from flask import Response
    fname = f"invoices_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment;filename={fname}"})

@app.route("/invoicing/export/pdf")
@role_required("invoicing")
def invoicing_export_pdf():
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("invoicing", tab="export"))
    import io as _io
    raw = fb_get("/invoices") or {}
    items = []
    for iid, idata in (raw.items() if isinstance(raw, dict) else []):
        if idata and isinstance(idata, dict):
            items.append(idata)
    items.sort(key=lambda x: x.get("meta", {}).get("created_at", ""), reverse=True)
    items = _filter_invoices_export(items)
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=0.5*inch, rightMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    co = company_info()
    elems = []
    title_s = ParagraphStyle("T", parent=styles["Normal"], fontSize=15,
                              fontName="Helvetica-Bold",
                              textColor=colors.HexColor("#0F766E"), spaceAfter=3)
    sub_s   = ParagraphStyle("S", parent=styles["Normal"], fontSize=9,
                              textColor=colors.HexColor("#64748B"), spaceAfter=14)
    elems.append(Paragraph(f"{co.get('name','')} — Invoice Report", title_s))
    elems.append(Paragraph(
        f"Generated {datetime.now().strftime('%B %d, %Y')}  ·  {len(items)} record{'s' if len(items)!=1 else ''}",
        sub_s))
    hdrs = ["Invoice #", "Client", "Project", "Date", "Due Date", "Status", "Total", "Paid", "Outstanding"]
    data = [hdrs]
    for inv in items:
        m = inv.get("meta", {})
        total = _safe_float(m.get("total", 0))
        paid  = _safe_float(m.get("amount_paid", 0))
        data.append([
            m.get("invoice_number","—"),
            (m.get("client_name","—") or "—")[:20],
            (m.get("project_number","") or "—")[:14],
            m.get("invoice_date","—") or "—",
            m.get("due_date","—") or "—",
            m.get("status","—"),
            f"${total:,.0f}",
            f"${paid:,.0f}",
            f"${total-paid:,.0f}",
        ])
    cw = [1.2*inch, 1.8*inch, 1.3*inch, 1.0*inch, 1.0*inch, 1.0*inch, 1.0*inch, 1.0*inch, 1.0*inch]
    tbl = Table(data, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 9),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,0), 8),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID",          (0,0), (-1,-1), 0.4, colors.HexColor("#E2E8F0")),
        ("TOPPADDING",    (0,1), (-1,-1), 5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
        ("ALIGN",         (-3,1),(-1,-1), "RIGHT"),
        ("FONTNAME",      (-3,1),(-1,-1), "Helvetica-Bold"),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buf.seek(0)
    from flask import Response
    fname = f"invoices_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

# ── Routes: Clients ───────────────────────────────────────────────────────────
@app.route("/clients")
@role_required("invoicing")
def clients():
    raw = fb_get("/clients") or {}
    items = []
    if isinstance(raw, dict):
        for name, cdata in raw.items():
            if cdata and isinstance(cdata, dict):
                cdata["client_name"] = name
                items.append(cdata)
    items.sort(key=lambda x: x.get("client_name", "").lower())
    search = request.args.get("q", "").strip().lower()
    tag_filter = request.args.get("tag", "")
    # Collect all tags from full list before filtering so chips always show
    all_tags = sorted({t for i in items for t in (i.get("tags") or []) if t})
    if search:
        items = [i for i in items if search in (
            (i.get("client_name","") + " " + i.get("company","") + " " +
             i.get("email","") + " " + i.get("phone",""))).lower()]
    if tag_filter:
        items = [i for i in items if tag_filter in (i.get("tags") or [])]
    active_tab = request.args.get("tab", "all-clients")
    return render_template("clients.html", clients=items, active_tab=active_tab,
                           search=search, tag_filter=tag_filter, all_tags=all_tags)

@app.route("/clients/new", methods=["GET", "POST"])
@role_required("invoicing")
def client_new():
    if request.method == "POST":
        name = request.form.get("client_name", "").strip()
        if not name:
            flash("Client name is required.", "danger")
            return render_template("client_form.html", client=None, is_new=True)
        raw_tags = request.form.get("tags", "")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        data = {
            "company":  request.form.get("company", ""),
            "email":    request.form.get("email", ""),
            "phone":    request.form.get("phone", ""),
            "address":  request.form.get("address", ""),
            "notes":    request.form.get("notes", ""),
            "tags":     tags,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        fb_update(f"/clients/{name}", data)
        flash("Client saved.", "success")
        return redirect(url_for("clients", tab="all-clients"))
    return render_template("client_form.html", client=None, is_new=True)

@app.route("/clients/<client_name>/edit", methods=["GET", "POST"])
@role_required("invoicing")
def client_edit(client_name):
    data = fb_get(f"/clients/{client_name}") or {}
    data["client_name"] = client_name
    if request.method == "POST":
        new_name = request.form.get("client_name", client_name).strip()
        raw_tags = request.form.get("tags", "")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        updated = {
            "company":  request.form.get("company", ""),
            "email":    request.form.get("email", ""),
            "phone":    request.form.get("phone", ""),
            "address":  request.form.get("address", ""),
            "notes":    request.form.get("notes", ""),
            "tags":     tags,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if new_name != client_name:
            fb_delete(f"/clients/{client_name}")
        fb_update(f"/clients/{new_name}", updated)
        flash("Client updated.", "success")
        return redirect(url_for("clients"))
    return render_template("client_form.html", client=data, is_new=False)

# ── Client Statement PDF ──────────────────────────────────────────────────────
@app.route("/clients/<client_name>/statement")
@role_required("invoicing")
def client_statement(client_name):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("clients"))
    import io as _io

    co = company_info()
    client_data = fb_get(f"/clients/{client_name}") or {}

    # Load all invoices for this client
    raw_inv = fb_get("/invoices") or {}
    inv_list = []
    if isinstance(raw_inv, dict):
        for iid, idata in raw_inv.items():
            if isinstance(idata, dict) and idata.get("meta", {}).get("client_name", "") == client_name:
                idata["firebase_id"] = iid
                inv_list.append(idata)
    inv_list.sort(key=lambda x: x.get("meta", {}).get("invoice_date", ""))

    total_invoiced = sum(_safe_float(i.get("meta",{}).get("total", 0)) for i in inv_list)
    total_paid     = sum(_safe_float(i.get("meta",{}).get("amount_paid", 0)) for i in inv_list)
    balance_due    = total_invoiced - total_paid

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    teal   = colors.HexColor("#0F766E")
    dark   = colors.HexColor("#0F172A")
    muted  = colors.HexColor("#64748B")
    light  = colors.HexColor("#F8FAFC")
    border = colors.HexColor("#E2E8F0")
    lbl = ParagraphStyle("lbl", parent=styles["Normal"], fontSize=8,  fontName="Helvetica-Bold", textColor=muted)
    val = ParagraphStyle("val", parent=styles["Normal"], fontSize=10, fontName="Helvetica",       textColor=dark, spaceAfter=6)
    sm  = ParagraphStyle("sm",  parent=styles["Normal"], fontSize=9,  fontName="Helvetica",       textColor=muted)
    h2  = ParagraphStyle("h2",  parent=styles["Normal"], fontSize=11, fontName="Helvetica-Bold",  textColor=dark, spaceBefore=10, spaceAfter=6)
    elems = []

    # Header
    hdr_data = [[
        Paragraph(f"<b>{co.get('name','')}</b>",
                  ParagraphStyle("cn", parent=styles["Normal"], fontSize=14, fontName="Helvetica-Bold", textColor=dark)),
        Paragraph("CLIENT STATEMENT",
                  ParagraphStyle("cs", parent=styles["Normal"], fontSize=18, fontName="Helvetica-Bold", textColor=teal, alignment=2)),
    ],[
        Paragraph(f"{co.get('address','').replace(chr(10),' | ')}  |  {co.get('phone','')}  |  {co.get('email','')}", sm),
        Paragraph(f"As of {datetime.now().strftime('%B %d, %Y')}",
                  ParagraphStyle("dt", parent=styles["Normal"], fontSize=10, textColor=muted, alignment=2)),
    ]]
    hdr = Table(hdr_data, colWidths=[3.5*inch, 3.5*inch])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    elems.extend([hdr, HRFlowable(width="100%", thickness=2, color=teal, spaceAfter=12)])

    # Client info
    elems.append(Paragraph("BILL TO", lbl))
    elems.append(Paragraph(f"<b>{client_name}</b>", val))
    if client_data.get("company"):
        elems.append(Paragraph(client_data["company"], sm))
    if client_data.get("email"):
        elems.append(Paragraph(client_data["email"], sm))
    if client_data.get("phone"):
        elems.append(Paragraph(client_data["phone"], sm))
    elems.append(Spacer(1, 12))

    # Invoice table
    elems.append(Paragraph("INVOICE HISTORY", h2))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=border, spaceAfter=6))
    tbl_data = [["Invoice #", "Project", "Date", "Due Date", "Status", "Total", "Paid", "Balance"]]
    for inv in inv_list:
        m = inv.get("meta", {})
        total = _safe_float(m.get("total", 0))
        paid  = _safe_float(m.get("amount_paid", 0))
        tbl_data.append([
            m.get("invoice_number", "—"),
            m.get("project_number", "—") or "—",
            m.get("invoice_date", "—") or "—",
            m.get("due_date", "—") or "—",
            m.get("status", "—"),
            f"${total:,.2f}",
            f"${paid:,.2f}",
            f"${total-paid:,.2f}",
        ])
    if not inv_list:
        tbl_data.append(["No invoices found.", "", "", "", "", "", "", ""])

    cw = [1.0*inch, 1.0*inch, 0.85*inch, 0.85*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch]
    tbl = Table(tbl_data, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), dark),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 8),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,0), 6), ("BOTTOMPADDING",(0,0),(-1,0),6),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, light]),
        ("GRID",          (0,0), (-1,-1), 0.4, border),
        ("TOPPADDING",    (0,1), (-1,-1), 5), ("BOTTOMPADDING",(0,1),(-1,-1),5),
        ("ALIGN",         (-3,1),(-1,-1), "RIGHT"),
    ]))
    elems.append(tbl)

    # Summary
    elems.append(Spacer(1, 16))
    sum_data = [
        ["Total Invoiced",  f"${total_invoiced:,.2f}"],
        ["Total Paid",      f"${total_paid:,.2f}"],
        ["Balance Due",     f"${balance_due:,.2f}"],
    ]
    sum_tbl = Table(sum_data, colWidths=[2.5*inch, 1.5*inch])
    sum_tbl.setStyle(TableStyle([
        ("FONTNAME",  (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",  (0,0), (-1,-1), 10),
        ("FONTNAME",  (0,2), (-1,2),  "Helvetica-Bold"),
        ("TEXTCOLOR", (0,0), (0,-1),  muted),
        ("FONTNAME",  (1,0), (1,-1),  "Helvetica-Bold"),
        ("TEXTCOLOR", (1,2), (1,2),   colors.HexColor("#DC2626") if balance_due > 0 else teal),
        ("TEXTCOLOR", (1,0), (1,0),   teal),
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.white, light]),
        ("GRID",      (0,0), (-1,-1), 0.4, border),
        ("TOPPADDING",(0,0), (-1,-1), 6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1), 8),
        ("ALIGN",     (1,0), (1,-1),  "RIGHT"),
    ]))
    elems.append(sum_tbl)

    doc.build(elems)
    buf.seek(0)
    from flask import Response
    safe_name = client_name.replace(" ", "_")
    fname = f"statement_{safe_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment;filename={fname}"})

# ── Routes: Financial ─────────────────────────────────────────────────────────
@app.route("/financial")
@role_required("financial")
def financial():
    invoices = fb_get("/invoices") or {}
    expenses = fb_get("/balance_sheet_expenses") or {}
    revenue  = fb_get("/balance_sheet_revenue") or {}

    inv_list  = [v for v in invoices.values() if isinstance(v, dict)] if isinstance(invoices, dict) else []
    exp_list  = []
    if isinstance(expenses, dict):
        for eid, edata in expenses.items():
            if isinstance(edata, dict):
                edata["firebase_id"] = eid
                exp_list.append(edata)
    rev_list = []
    if isinstance(revenue, dict):
        for rid, rdata in revenue.items():
            if isinstance(rdata, dict):
                rdata["firebase_id"] = rid
                # Older entries (and ones written by the desktop app) only carry
                # 'amount'/'client' rather than 'amount_paid'/'total'/'client_name' —
                # normalize so the template can rely on a consistent field set.
                rdata.setdefault("amount_paid", rdata.get("amount", 0))
                rdata.setdefault("total", rdata.get("amount", 0))
                rdata.setdefault("client_name", rdata.get("client", ""))
                rdata.setdefault("status", "Paid")
                rev_list.append(rdata)
    rev_list.sort(key=lambda x: x.get("date", ""), reverse=True)
    total_collected = sum(_safe_float(r.get("amount_paid", 0)) for r in rev_list)

    total_invoiced    = sum(_safe_float(i.get("meta", {}).get("total", 0)) for i in inv_list)
    total_paid        = sum(_safe_float(i.get("meta", {}).get("amount_paid", 0)) for i in inv_list)
    total_outstanding = total_invoiced - total_paid
    total_expenses    = sum(_safe_float(e.get("amount", 0)) for e in exp_list)
    net_profit        = total_paid - total_expenses

    # Monthly breakdown for chart
    monthly_revenue  = {}
    monthly_expenses = {}
    for inv in inv_list:
        ds = inv.get("meta", {}).get("invoice_date", "") or ""
        try:
            key = datetime.fromisoformat(ds[:10]).strftime("%b %Y")
            monthly_revenue[key] = monthly_revenue.get(key, 0) + _safe_float(inv.get("meta", {}).get("amount_paid", 0))
        except Exception:
            pass
    for exp in exp_list:
        ds = exp.get("date", "") or ""
        try:
            key = datetime.fromisoformat(ds[:10]).strftime("%b %Y")
            monthly_expenses[key] = monthly_expenses.get(key, 0) + _safe_float(exp.get("amount", 0))
        except Exception:
            pass

    from dateutil.relativedelta import relativedelta as _rd
    _now = datetime.now()
    all_months = [(_now - _rd(months=i)).strftime("%b %Y") for i in range(5, -1, -1)]
    rev_data   = [monthly_revenue.get(m, 0) for m in all_months]
    exp_data   = [monthly_expenses.get(m, 0) for m in all_months]

    # Per-project P&L
    projects_list = _load_projects_list()
    project_pnl = []
    for p in projects_list:
        pnum = p.get("project_number", "")
        p_invoiced = sum(_safe_float(i.get("meta",{}).get("total",0))       for i in inv_list if i.get("meta",{}).get("project_number","") == pnum)
        p_paid     = sum(_safe_float(i.get("meta",{}).get("amount_paid",0)) for i in inv_list if i.get("meta",{}).get("project_number","") == pnum)
        p_expenses = sum(_safe_float(e.get("amount",0))                     for e in exp_list if e.get("project_number","") == pnum)
        project_pnl.append({
            "project_number": pnum,
            "project_name":   p.get("project_name",""),
            "client_name":    p.get("client_name",""),
            "status":         p.get("status",""),
            "contract_value": _safe_float(p.get("contract_value",0)),
            "invoiced":       p_invoiced,
            "paid":           p_paid,
            "expenses":       p_expenses,
            "gross_profit":   p_paid - p_expenses,
            "firebase_id":    p.get("firebase_id",""),
        })
    project_pnl.sort(key=lambda x: x["project_number"], reverse=True)

    # ── Chart data for overview pie charts ────────────────────────────────────
    inv_status_counts = {}
    for i in inv_list:
        st = i.get("meta", {}).get("status") or "Draft"
        inv_status_counts[st] = inv_status_counts.get(st, 0) + 1

    exp_cats = {}
    for e in exp_list:
        cat = e.get("category", "Other") or "Other"
        exp_cats[cat] = exp_cats.get(cat, 0) + _safe_float(e.get("amount", 0))

    today_date = datetime.now().strftime("%Y-%m-%d")
    active_tab = request.args.get("tab", "overview")
    return render_template("financial.html",
        total_invoiced=total_invoiced,
        total_paid=total_paid,
        total_outstanding=total_outstanding,
        total_expenses=total_expenses,
        net_profit=net_profit,
        chart_labels=json.dumps(all_months),
        chart_revenue=json.dumps(rev_data),
        chart_expenses=json.dumps(exp_data),
        expenses=exp_list,
        rev_list=rev_list,
        total_collected=total_collected,
        projects=projects_list,
        project_pnl=project_pnl,
        today_date=today_date,
        active_tab=active_tab,
        inv_status_labels=json.dumps(list(inv_status_counts.keys())),
        inv_status_data=json.dumps(list(inv_status_counts.values())),
        exp_cat_labels=json.dumps(list(exp_cats.keys())),
        exp_cat_data=json.dumps(list(exp_cats.values())),
        ai_enabled=bool(_get_ai_client()),
    )

@app.route("/financial/expense/new", methods=["POST"])
@role_required("financial")
def expense_new():
    data = {
        "description":    request.form.get("description", ""),
        "amount":         request.form.get("amount", "0"),
        "category":       request.form.get("category", ""),
        "date":           request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
        "vendor":         request.form.get("vendor", ""),
        "project_number": request.form.get("project_number", ""),
        "notes":          request.form.get("notes", ""),
        "created_by":     session.get("user_email", ""),
        "created_at":     datetime.now(timezone.utc).isoformat(),
    }
    fb_push("/balance_sheet_expenses", data)
    flash("Expense added.", "success")
    return redirect(url_for("financial", tab="expenses"))

@app.route("/financial/expense/<exp_id>/delete", methods=["POST"])
@role_required("financial")
def expense_delete(exp_id):
    fb_delete(f"/balance_sheet_expenses/{exp_id}")
    flash("Expense deleted.", "success")
    return redirect(url_for("financial", tab="expenses"))

# ── Routes: Settings ──────────────────────────────────────────────────────────
@app.route("/settings")
@role_required("settings")
def settings():
    all_users = _load_all_users()
    settings_data = load_settings()
    return render_template("settings.html", users=all_users, settings=settings_data)

@app.route("/settings/company", methods=["POST"])
@role_required("settings")
def settings_company():
    existing = load_settings()
    co = existing.get("company", {})
    co.update({
        "name":             request.form.get("name", ""),
        "address":          request.form.get("address", ""),
        "email":            request.form.get("email", ""),
        "phone":            request.form.get("phone", ""),
        "website":          request.form.get("website", ""),
        "default_tax_rate": _safe_float(request.form.get("default_tax_rate", "0")),
        "default_terms":    request.form.get("default_terms", ""),
    })
    # Save to Firebase and local settings.json
    fb_update("/settings", {"company": co})
    _save_local_settings_key("company", co)
    flash("Company settings saved.", "success")
    return redirect(url_for("settings"))

@app.route("/settings/logo", methods=["POST"])
@role_required("settings")
def settings_logo():
    from werkzeug.utils import secure_filename
    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        ext = Path(logo_file.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".bmp"):
            flash("Unsupported file type. Use PNG or JPG.", "danger")
            return redirect(url_for("settings"))
        save_path = ASSETS_DIR / f"company_logo{ext}"
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        logo_file.save(str(save_path))
        existing = load_settings()
        co = existing.get("company", {})
        co["logo_path"] = str(save_path)
        fb_update("/settings", {"company": co})
        _save_local_settings_key("company", co)
        flash("Logo uploaded successfully.", "success")
    else:
        flash("No file selected.", "warning")
    return redirect(url_for("settings"))

@app.route("/settings/email", methods=["POST"])
@role_required("settings")
def settings_email():
    email_cfg = {
        "enabled":              request.form.get("enabled") == "on",
        "smtp_host":            request.form.get("smtp_host", "smtp.gmail.com"),
        "smtp_port":            int(request.form.get("smtp_port", 587) or 587),
        "smtp_user":            request.form.get("smtp_user", ""),
        "smtp_password":        request.form.get("smtp_password", ""),
        "from_name":            request.form.get("from_name", ""),
        "reminder_days_before": int(request.form.get("reminder_days_before", 3) or 3),
    }
    fb_update("/settings", {"email": email_cfg})
    _save_local_settings_key("email", email_cfg)
    flash("Email settings saved.", "success")
    return redirect(url_for("settings"))

@app.route("/settings/app", methods=["POST"])
@role_required("settings")
def settings_app():
    app_cfg = {
        "theme":               request.form.get("theme", "light"),
        "log_level":           request.form.get("log_level", "INFO"),
        "auto_check_updates":  request.form.get("auto_check_updates") == "on",
    }
    fb_update("/settings", {"app": app_cfg})
    _save_local_settings_key("app", app_cfg)
    flash("App preferences saved.", "success")
    return redirect(url_for("settings"))

@app.route("/settings/ai", methods=["POST"])
@role_required("settings")
def settings_ai():
    ai_cfg = {"anthropic_key": request.form.get("anthropic_key", "").strip()}
    fb_update("/settings", {"ai": ai_cfg})
    _save_local_settings_key("ai", ai_cfg)
    flash("AI settings saved.", "success")
    return redirect(url_for("settings") + "?tab=ai")


# ── AI Routes ─────────────────────────────────────────────────────────────────

@app.route("/ai/extract-pdf", methods=["POST"])
@role_required("financial")
def ai_extract_pdf():
    """Extract expense fields from an uploaded PDF using Claude."""
    if not PYPDF_AVAILABLE:
        return jsonify({"error": "pypdf not installed on server"}), 500
    f = request.files.get("pdf")
    if not f:
        return jsonify({"error": "No file uploaded"}), 400
    try:
        reader = _PdfReader(f)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)[:4000]
    except Exception as e:
        return jsonify({"error": f"Could not read PDF: {e}"}), 400
    prompt = f"""Extract expense information from this document text and return ONLY valid JSON with these fields:
description, amount (number, no currency symbol), date (YYYY-MM-DD or blank), category (one of: Labor, Materials, Equipment, Subcontractor, Overhead, Travel, Other), vendor.
If a field is not found leave it blank. Return only the JSON object, nothing else.

Document text:
{text}"""
    try:
        result = _ai_call(prompt)
        data = json.loads(result)
        return jsonify(data)
    except json.JSONDecodeError:
        import re
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m:
            return jsonify(json.loads(m.group(0)))
        return jsonify({"error": "AI returned unexpected format", "raw": result}), 500
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/draft-reminder/<invoice_id>", methods=["POST"])
@role_required("invoicing")
def ai_draft_reminder(invoice_id):
    """Draft a professional overdue reminder email for an invoice."""
    inv_data = fb_get(f"/invoices/{invoice_id}")
    if not inv_data:
        return jsonify({"error": "Invoice not found"}), 404
    meta = inv_data.get("meta", {})
    today = datetime.now().strftime("%Y-%m-%d")
    due   = meta.get("due_date", "")
    try:
        days_overdue = (datetime.fromisoformat(today) - datetime.fromisoformat(due)).days if due else 0
    except Exception:
        days_overdue = 0
    prompt = f"""Write a professional but friendly overdue payment reminder email.
Invoice: {meta.get('invoice_number')}
Client: {meta.get('client_name')}
Amount outstanding: ${_safe_float(meta.get('total',0)) - _safe_float(meta.get('amount_paid',0)):,.2f}
Due date: {due}
Days overdue: {days_overdue}
Company sending this: {company_info().get('name','MABS Engineering')}

Keep it concise (3-4 short paragraphs), professional, and include a clear call to action.
Use placeholders like [Your Name] for signature. Do not use asterisks for formatting."""
    try:
        email_text = _ai_call(prompt, max_tokens=512)
        subject = f"Payment Reminder — {meta.get('invoice_number')} (${_safe_float(meta.get('total',0)):,.0f})"
        return jsonify({"subject": subject, "body": email_text})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/draft-quote-email/<quote_id>", methods=["POST"])
@role_required("quotes")
def ai_draft_quote_email(quote_id):
    """Generate a professional covering email for sending a quote PDF to the client."""
    ai_client = _get_ai_client()
    if not ai_client:
        return jsonify({"error": "AI not configured. Add your Anthropic API key in Settings → AI."})
    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        return jsonify({"error": "Quote not found."}), 404
    co       = company_info()
    services = ", ".join(quote.get("service_types") or []) or "engineering services"
    total    = _safe_float(quote.get("total", 0))
    prompt   = f"""Write a concise professional email to accompany a quote PDF sent to a client.

Sender company : {co.get('name', 'Our Company')}
Client         : {quote.get('client_name', 'Client')}
Quote number   : {quote.get('job_number', '')}
Project / Scope: {quote.get('project_name', '')}
Services       : {services}
Quote total    : ${total:,.2f}
Valid until    : {quote.get('valid_until', 'N/A')}
Salesperson    : {quote.get('salesperson', '')}

Write 3-4 short paragraphs:
1. Greeting + purpose of the email
2. Brief summary of the scope and quote total
3. Validity period + invitation to discuss or ask questions
4. Professional closing with [Your Name] placeholder

Return JSON only: {{"subject": "...", "body": "..."}}
No markdown, no asterisks in the body."""
    try:
        raw    = _ai_call(prompt, max_tokens=600)
        import re as _re
        match  = _re.search(r'\{.*\}', raw, _re.DOTALL)
        parsed = json.loads(match.group()) if match else {}
        subject = parsed.get("subject") or f"Quote {quote.get('job_number','')} — {quote.get('project_name','')}"
        body    = parsed.get("body") or raw
        return jsonify({"subject": subject, "body": body})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ai/cash-flow-summary", methods=["POST"])
@role_required("financial")
def ai_cash_flow_summary():
    """Generate a plain-English cash flow narrative from upcoming payment data."""
    data = request.get_json(force=True) or {}
    upcoming = data.get("upcoming", [])
    total_expected = sum(float(u.get("amount", 0)) for u in upcoming)
    items_text = "\n".join(
        f"- {u.get('date','?')}: {u.get('label','?')} — ${float(u.get('amount',0)):,.0f}"
        for u in upcoming[:20]
    )
    prompt = f"""Based on these upcoming expected payments for the next 90 days, write a brief 2-3 sentence cash flow summary. Be specific about amounts and timing. No bullet points.

Total expected: ${total_expected:,.0f}
Upcoming items:
{items_text or 'No upcoming payments found.'}"""
    try:
        summary = _ai_call(prompt, max_tokens=200)
        return jsonify({"summary": summary})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai/project-health", methods=["POST"])
@role_required("projects")
def ai_project_health():
    """Return one-line health summaries for all projects."""
    projects_list = _load_projects_list()
    invoices_raw  = fb_get("/invoices") or {}
    inv_list = [v for v in invoices_raw.values() if isinstance(v, dict)] if isinstance(invoices_raw, dict) else []

    summaries = {}
    for p in projects_list:
        pnum   = p.get("project_number", "")
        paid   = _safe_float(p.get("amount_paid", 0))
        cv     = _safe_float(p.get("contract_value", 0))
        status = p.get("status", "Not Started")
        pct    = int(paid / cv * 100) if cv > 0 else 0
        stages = p.get("payment_stages", [])
        pending_stages = [s for s in stages if isinstance(s, dict) and s.get("status") in ("Pending", "Invoiced")]
        next_stage_amt = _safe_float(pending_stages[0].get("amount", 0)) if pending_stages else 0
        summary_input = (
            f"Project: {p.get('project_name','')} ({pnum}), Status: {status}, "
            f"Contract: ${cv:,.0f}, Paid: ${paid:,.0f} ({pct}%), "
            f"Pending installments: {len(pending_stages)}, Next due: ${next_stage_amt:,.0f}"
        )
        summaries[pnum] = summary_input

    if not summaries:
        return jsonify({"summaries": {}})

    bulk = "\n".join(f"{k}: {v}" for k, v in summaries.items())
    prompt = f"""For each project below, write exactly ONE short sentence (max 15 words) summarizing its health and next action. Return ONLY valid JSON like {{"PROJ-001": "sentence", "PROJ-002": "sentence"}}.

{bulk}"""
    try:
        result = _ai_call(prompt, max_tokens=600)
        import re
        m = re.search(r'\{.*\}', result, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
        return jsonify({"summaries": parsed})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/settings/user/new", methods=["POST"])
@role_required("settings")
def user_new():
    username = request.form.get("username", "").strip()
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role     = normalize_role(request.form.get("role", "sales"))

    if not all([username, email, password]):
        flash("All fields are required.", "danger")
        return redirect(url_for("settings"))

    if not FIREBASE_AVAILABLE:
        flash("Firebase not available.", "danger")
        return redirect(url_for("settings"))

    try:
        from firebase_admin import auth as fb_auth
        user = fb_auth.create_user(email=email, password=password,
                                   display_name=username, email_verified=False)
        user_data = {
            "username":   username,
            "email":      email,
            "role":       role,
            "active":     True,
            "firebase_uid": user.uid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        fb_update(f"/users/{user.uid}", user_data)
        flash(f"User {username} created.", "success")
    except Exception as exc:
        flash(f"Error creating user: {exc}", "danger")

    return redirect(url_for("settings"))

@app.route("/settings/user/<uid>/toggle", methods=["POST"])
@role_required("settings")
def user_toggle(uid):
    profile = fb_get(f"/users/{uid}") or {}
    current = profile.get("active", True)
    fb_update(f"/users/{uid}", {"active": not current,
                                "updated_at": datetime.now(timezone.utc).isoformat()})
    flash("User status updated.", "success")
    return redirect(url_for("settings"))

@app.route("/settings/user/<uid>/role", methods=["POST"])
@role_required("settings")
def user_role_update(uid):
    new_role = normalize_role(request.form.get("role", "sales"))
    fb_update(f"/users/{uid}", {"role": new_role,
                                "updated_at": datetime.now(timezone.utc).isoformat()})
    flash("User role updated.", "success")
    return redirect(url_for("settings"))

@app.route("/settings/user/<uid>/delete", methods=["POST"])
@role_required("settings")
def user_delete(uid):
    if uid == session.get("user_uid"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("settings"))
    try:
        if FIREBASE_AVAILABLE:
            from firebase_admin import auth as fb_auth
            try:
                fb_auth.delete_user(uid)
            except Exception:
                pass
        fb_delete(f"/users/{uid}")
        flash("User deleted.", "success")
    except Exception as exc:
        flash(f"Error: {exc}", "danger")
    return redirect(url_for("settings"))

# ── Route: serve company logo ─────────────────────────────────────────────────
@app.route("/logo")
def company_logo():
    """Serve the company logo from its configured path."""
    settings = load_settings()
    logo_path = settings.get("company", {}).get("logo_path", "")
    candidates = [
        Path(logo_path) if logo_path else None,
        DATA_DIR / "company_logo.png",
        DATA_DIR / "company_logo.jpg",
        DATA_DIR / "logo.png",
        ASSETS_DIR / "logo.png",
        ASSETS_DIR / "logo.jpg",
    ]
    for p in candidates:
        if p and p.exists():
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            return send_file(str(p), mimetype=mime)
    abort(404)

# ── API: invoice number ───────────────────────────────────────────────────────
@app.route("/api/next-invoice-number")
@login_required
def api_next_invoice():
    return jsonify({"number": _next_invoice_number()})

@app.route("/api/client/<client_name>")
@login_required
def api_client(client_name):
    data = fb_get(f"/clients/{client_name}") or {}
    return jsonify(data)

@app.route("/api/quote-by-number/<quote_number>")
@login_required
def api_quote_by_number(quote_number):
    """Return quote data for a given job_number so the project form can auto-fill."""
    raw = fb_get("/job_forms") or {}
    if isinstance(raw, dict):
        for qid, qdata in raw.items():
            if isinstance(qdata, dict) and qdata.get("job_number", "").strip() == quote_number.strip():
                # Map quote fields → project field names
                def _parse_date(raw_d):
                    if not raw_d:
                        return ""
                    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
                        try:
                            from datetime import datetime as _dt
                            return _dt.strptime(raw_d, fmt).strftime("%Y-%m-%d")
                        except ValueError:
                            continue
                    return ""
                cost_raw = qdata.get("engineering_costs", "") or "0"
                try:
                    cost_val = float(str(cost_raw).replace("$","").replace(",","").strip() or 0)
                except ValueError:
                    cost_val = 0.0
                return jsonify({
                    "found":          True,
                    "project_name":   qdata.get("project_name", ""),
                    "client_name":    qdata.get("client", ""),
                    "sales":          qdata.get("sales", "") or qdata.get("sales_person", ""),
                    "site_address":   qdata.get("project_site_address", ""),
                    "mail_address":   qdata.get("client_address", ""),
                    "plant":          qdata.get("plant", ""),
                    "job_type":       qdata.get("job_type", ""),
                    "scope_of_work":  qdata.get("scope_of_work", ""),
                    "expedite":       "Yes" if qdata.get("expedite") else "No",
                    "contract_value": f"{cost_val:.2f}",
                    "start_date":     _parse_date(qdata.get("start_date", "")),
                    "end_date":       _parse_date(qdata.get("due_date", "")),
                })
    return jsonify({"found": False})

# ── Helpers ───────────────────────────────────────────────────────────────────
def _save_local_settings_key(key: str, value) -> None:
    """Persist a single top-level key in data/settings.json."""
    try:
        sf = DATA_DIR / "settings.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {}
        if sf.exists():
            with open(sf, encoding="utf-8") as f:
                data = json.load(f)
        data[key] = value
        with open(sf, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        log.warning("Could not save settings.json: %s", exc)

def _safe_float(val) -> float:
    try:
        return float(str(val or 0).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0

def _get_next_payment_stage(project: dict, all_invoices: dict = None) -> dict:
    """Get next uninvoiced payment stage.
    Returns: {stage_idx, stage_name, amount, blocked, reason}
    """
    if all_invoices is None:
        all_invoices = fb_get("/invoices") or {}

    proj_num = project.get("project_number", "")
    payment_stages = project.get("payment_stages", [])

    if not isinstance(payment_stages, list) or not payment_stages:
        return {"stage_idx": None, "stage_name": None, "amount": 0, "blocked": True, "reason": "No payment stages defined"}

    # Find which stages have been invoiced
    invoiced_stages = set()
    if isinstance(all_invoices, dict):
        for inv_id, inv_data in all_invoices.items():
            if isinstance(inv_data, dict):
                # Check single-project invoices
                inv_proj = inv_data.get("meta", {}).get("project_number", "")
                if inv_proj == proj_num:
                    stage_idx = inv_data.get("meta", {}).get("payment_stage_index")
                    if stage_idx is not None:
                        invoiced_stages.add(int(stage_idx))
                        print(f"[DETECT] Single-project invoice {inv_id}: proj={proj_num}, stage={stage_idx}", flush=True)

                # Check multi-project invoices (linked_projects field)
                linked_projects = inv_data.get("meta", {}).get("linked_projects", [])
                if isinstance(linked_projects, list) and len(linked_projects) > 0:
                    for linked in linked_projects:
                        if isinstance(linked, dict) and linked.get("project_number") == proj_num:
                            stage_idx = linked.get("payment_stage_index")
                            if stage_idx is not None:
                                invoiced_stages.add(int(stage_idx))
                                print(f"[DETECT] Multi-project invoice {inv_id}: proj={proj_num}, stage={stage_idx}, linked_projects={linked_projects}", flush=True)

    # Find first stage NOT invoiced
    print(f"[DETECT] Project {proj_num}: total_stages={len(payment_stages)}, invoiced_stages={invoiced_stages}", flush=True)
    for idx, stage in enumerate(payment_stages):
        if isinstance(stage, dict) and idx not in invoiced_stages:
            stage_name = stage.get("name", f"Stage {idx + 1}")
            amount = _safe_float(stage.get("amount", 0))
            blocked = False
            reason = "Ready to invoice"

            # Check if previous stages are invoiced
            if idx > 0:
                # All previous stages must be invoiced
                for prev_idx in range(idx):
                    if prev_idx not in invoiced_stages:
                        blocked = True
                        reason = f"Previous stage(s) not yet invoiced"
                        break

            print(f"[DETECT] Returning stage {idx} for {proj_num}: {stage_name}", flush=True)
            return {
                "stage_idx": idx,
                "stage_name": stage_name,
                "amount": amount,
                "blocked": blocked,
                "reason": reason
            }

    print(f"[DETECT] Project {proj_num} is fully invoiced", flush=True)
    return {"stage_idx": None, "stage_name": None, "amount": 0, "blocked": True, "reason": "All payment stages already invoiced"}

def _find_project_by_number(project_number: str):
    """Return (firebase_id, project_dict) for the project with this number, or (None, None)."""
    raw_proj = fb_get("/projects") or {}
    if isinstance(raw_proj, dict):
        for pid, pdata in raw_proj.items():
            if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
                return pid, pdata
    return None, None

def _mark_project_stage(project_number: str, stage_index: int, status: str, invoice_id: str = None, invoice_number: str = None) -> None:
    """Update one stage's status (and optionally its linked invoice id/number) within a project's payment plan."""
    pid, pdata = _find_project_by_number(project_number)
    print(f"[MARK_STAGE] project_number={project_number}, stage_idx={stage_index}, status={status}, pid={pid}", flush=True)
    if not pid:
        print(f"[MARK_STAGE] Project not found!", flush=True)
        return
    stages = pdata.get("payment_stages") or []
    if not (0 <= stage_index < len(stages)) or not isinstance(stages[stage_index], dict):
        print(f"[MARK_STAGE] Stage index out of range! stages_count={len(stages)}, idx={stage_index}", flush=True)
        return
    stages[stage_index]["status"] = status
    if invoice_id is not None:
        stages[stage_index]["invoice_id"] = invoice_id
    if invoice_number is not None:
        stages[stage_index]["invoice_number"] = invoice_number
    # When reverting to "Pending Invoice", clear the invoice tracking fields
    if status == "Pending Invoice":
        print(f"[MARK_STAGE] Clearing invoice_id and invoice_number", flush=True)
        stages[stage_index].pop("invoice_id", None)
        stages[stage_index].pop("invoice_number", None)
    print(f"[MARK_STAGE] Updated stage: {stages[stage_index]}", flush=True)
    fb_update(f"/projects/{pid}", {"payment_stages": stages,
                                   "updated_at": datetime.now(timezone.utc).isoformat()})

def _calculate_invoice_status(inv_data: dict) -> str:
    """Calculate invoice status based on payments vs total (including tax).

    Returns: "Paid", "Partial", or "Overdue" based on actual payments, regardless of manual status
    """
    meta = inv_data.get("meta", {}) or {}

    # Always calculate from actual payments, not from stored status
    invoice_total = _safe_float(meta.get("total", 0))
    tax_amount = _safe_float(meta.get("tax_amount", 0))
    invoice_subtotal = invoice_total - tax_amount  # Subtract tax from total to get line items amount

    # Get invoice payments (line items)
    payment_log = inv_data.get("payment_log", [])
    if not isinstance(payment_log, list):
        payment_log = []
    invoice_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log)

    # Get tax payments
    tax_log = inv_data.get("tax_payments", [])
    if not isinstance(tax_log, list):
        tax_log = []
    tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)

    # Check due date for Overdue
    due_date = meta.get("due_date", "")
    today = datetime.now().strftime("%Y-%m-%d")
    is_overdue = due_date and due_date < today

    # Determine status based on actual amounts
    invoice_paid_enough = invoice_paid >= (invoice_subtotal - 0.01)
    tax_paid_enough = tax_amount <= 0.01 or tax_paid >= (tax_amount - 0.01)

    if invoice_paid_enough and tax_paid_enough:
        return "Paid"
    elif invoice_paid > 0 or tax_paid > 0:
        return "Partial"
    elif is_overdue:
        return "Overdue"
    else:
        return "Sent"

def _update_project_stage_payment_status(invoice_id: str) -> None:
    """Update project stage statuses based on invoice payments.

    For each project linked to the invoice, sum payments made FOR THAT PROJECT
    and update the stage status to Paid/Partially Paid/Invoiced.
    """
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    meta = inv_data.get("meta", {}) or {}

    # Get linked projects from invoice
    linked_projects = meta.get("linked_projects", [])
    if not linked_projects:
        return

    # Get payment log
    payment_log = inv_data.get("payment_log", [])
    if not isinstance(payment_log, list):
        payment_log = []

    # Update each project's stage status based on payments FOR THAT PROJECT
    for proj_info in linked_projects:
        if not isinstance(proj_info, dict):
            continue

        project_number = proj_info.get("project_number", "")
        stage_index = proj_info.get("payment_stage_index", -1)

        if not project_number or stage_index < 0:
            continue

        # Get project and stage info
        pid, pdata = _find_project_by_number(project_number)
        if not pid:
            continue

        stages = pdata.get("payment_stages") or []
        if not (0 <= stage_index < len(stages)):
            continue

        stage = stages[stage_index]
        stage_amount = _safe_float(stage.get("amount", 0))

        if stage_amount <= 0:
            continue

        # Sum payments made FOR THIS SPECIFIC PROJECT (not proportional split)
        project_paid = sum(
            _safe_float(p.get("amount", 0))
            for p in payment_log
            if p.get("project_number") == project_number
        )

        # Determine stage status based on actual payments for this project
        if project_paid >= (stage_amount - 0.01):
            new_status = "Paid"
        elif project_paid > 0:
            new_status = "Partially Paid"
        else:
            new_status = "Invoiced"

        # Update stage status with actual paid amount for this project
        stage["status"] = new_status
        stage["amount_paid"] = str(project_paid)

        fb_update(f"/projects/{pid}", {
            "payment_stages": stages,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

def _sync_project_payment(project_number: str) -> None:
    """Sum this project's share of every linked invoice's paid amount and write back to project.amount_paid.

    Most invoices bill a single project, so their full amount_paid counts. For
    invoices that span multiple projects (mixed line items), each project only
    gets its proportional share — see _invoice_project_share().
    """
    if not project_number:
        return
    raw_inv = fb_get("/invoices") or {}
    total_paid = 0.0
    if isinstance(raw_inv, dict):
        for inv in raw_inv.values():
            if isinstance(inv, dict):
                m = inv.get("meta", {})
                if project_number in _invoice_linked_projects(inv):
                    share = _invoice_project_share(inv, project_number)
                    total_paid += share * _safe_float(m.get("amount_paid", 0))
    raw_proj = fb_get("/projects") or {}
    if isinstance(raw_proj, dict):
        for pid, pdata in raw_proj.items():
            if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
                updates = {
                    "amount_paid": total_paid,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                # Multi-project invoices prorate payment to every linked project,
                # but the stage-rollforward in invoice_status only marks the
                # invoice's single "main" project. Promote any stage that's still
                # "Pending" once the synced total now covers its cumulative amount,
                # so secondary projects don't show 100% paid with a Pending stage.
                stages = pdata.get("payment_stages")
                if isinstance(stages, list) and stages and all(isinstance(s, dict) for s in stages):
                    cumulative = 0.0
                    changed = False
                    for st in stages:
                        cumulative += _safe_float(st.get("amount", 0))
                        if st.get("status") in ("Pending", "Invoiced", "Partially Paid") \
                                and total_paid + 0.01 >= cumulative:
                            st["status"] = "Paid"
                            changed = True
                    if changed:
                        updates["payment_stages"] = stages
                # Auto-advance project status based on payment received
                contract_val   = _safe_float(pdata.get("contract_value", 0))
                current_status = pdata.get("status", "Not Started")
                if current_status not in ("Completed", "Cancelled"):
                    if contract_val > 0 and total_paid >= contract_val - 0.01:
                        updates["status"] = "Completed"
                    elif total_paid > 0 and current_status == "Not Started":
                        updates["status"] = "In Progress"

                fb_update(f"/projects/{pid}", updates)
                break

def _auto_flag_overdue() -> int:
    """Flip any Sent/Viewed/Partial invoice whose due_date < today to Overdue.
    Returns the number of invoices updated.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    raw = fb_get("/invoices") or {}
    count = 0
    if not isinstance(raw, dict):
        return 0
    for iid, inv in raw.items():
        if not isinstance(inv, dict):
            continue
        m = inv.get("meta", {})
        status   = m.get("status", "")
        due_date = m.get("due_date", "")
        if status in ("Sent", "Viewed", "Partial") and due_date and due_date < today:
            fb_update(f"/invoices/{iid}", {
                "meta/status":     "Overdue",
                "meta/updated_at": datetime.now(timezone.utc).isoformat(),
            })
            count += 1
    return count

def _upsert_revenue_entry(invoice_id: str, inv_meta: dict) -> None:
    """Create or update a balance-sheet revenue entry for a paid/partial invoice."""
    paid_val = _safe_float(inv_meta.get("amount_paid", 0))
    if paid_val <= 0:
        return
    proj_num = inv_meta.get("project_number", "")
    entry = {
        "description":    f"Invoice {inv_meta.get('invoice_number','')}",
        "invoice_number": inv_meta.get("invoice_number", ""),
        "client_name":    inv_meta.get("client_name", ""),
        "status":         inv_meta.get("status", "Paid"),
        "total":          _safe_float(inv_meta.get("total", 0)),
        "amount_paid":    paid_val,
        "amount":         paid_val,
        "client":         inv_meta.get("client_name", ""),
        "invoice_id":     invoice_id,
        "project_number": proj_num,
        "date":           inv_meta.get("invoice_date", datetime.now().strftime("%Y-%m-%d")),
        "created_at":     datetime.now(timezone.utc).isoformat(),
    }
    raw_rev = fb_get("/balance_sheet_revenue") or {}
    existing_key = None
    if isinstance(raw_rev, dict):
        for rk, rv in raw_rev.items():
            if isinstance(rv, dict) and rv.get("invoice_id") == invoice_id:
                existing_key = rk
                break
    if existing_key:
        fb_update(f"/balance_sheet_revenue/{existing_key}", entry)
    else:
        fb_push("/balance_sheet_revenue", entry)

def _auto_complete_project_if_paid(project_number: str) -> None:
    """Mark project Completed if every invoice linked to it is now Paid."""
    if not project_number:
        return
    raw_inv = fb_get("/invoices") or {}
    linked = [v.get("meta", {}) for v in raw_inv.values()
              if isinstance(v, dict) and project_number in _invoice_linked_projects(v)]
    if not linked:
        return
    if not all(m.get("status", "") == "Paid" for m in linked):
        return
    raw_proj = fb_get("/projects") or {}
    for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
        if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
            if pdata.get("status", "") not in ("Completed", "Cancelled"):
                fb_update(f"/projects/{pid}", {
                    "status": "Completed",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
            break

def _load_clients() -> List[str]:
    raw = fb_get("/clients") or {}
    if isinstance(raw, dict):
        return sorted(raw.keys())
    return []

def _load_sales_people() -> List[dict]:
    # Load from Firebase
    raw = fb_get("/sales_persons") or {}
    fb_names = set()
    people = []
    if isinstance(raw, dict):
        for pid, pdata in raw.items():
            if pdata and isinstance(pdata, dict):
                pdata["firebase_id"] = pid
                people.append(pdata)
                fb_names.add(str(pdata.get("name", "")).strip().lower())

    # Merge from local data/sales_persons.json (desktop compatibility)
    local_path = DATA_DIR / "sales_persons.json"
    if local_path.exists():
        try:
            with open(local_path, encoding="utf-8") as f:
                local = json.load(f)
            if isinstance(local, list):
                for p in local:
                    if isinstance(p, dict) and p.get("name"):
                        if str(p["name"]).strip().lower() not in fb_names:
                            people.append(p)
        except Exception:
            pass

    return sorted(people, key=lambda x: str(x.get("name", "")).lower())

def _load_projects_list() -> List[dict]:
    raw = fb_get("/projects") or {}
    if isinstance(raw, dict):
        items = []
        for pid, pdata in raw.items():
            if pdata and isinstance(pdata, dict):
                pdata["firebase_id"] = pid
                items.append(pdata)
        return sorted(items, key=lambda x: x.get("project_number", ""), reverse=True)
    return []

def _load_all_users() -> List[dict]:
    raw = fb_get("/users") or {}
    if isinstance(raw, dict):
        users = []
        for uid, udata in raw.items():
            if udata and isinstance(udata, dict):
                udata["firebase_uid"] = uid
                users.append(udata)
        return sorted(users, key=lambda x: x.get("username", "").lower())
    return []

def _next_quote_number() -> str:
    now = datetime.now()
    prefix = f"QT-{now.strftime('%Y%m')}-"
    raw = fb_get("/job_forms") or {}
    nums = []
    for q in (raw.values() if isinstance(raw, dict) else []):
        if isinstance(q, dict):
            num = q.get("job_number", "") or ""
            if num.startswith(prefix):
                try:
                    nums.append(int(num[len(prefix):]))
                except ValueError:
                    pass
    next_n = (max(nums) + 1) if nums else 1
    return f"{prefix}{next_n:03d}"

def _next_invoice_number() -> str:
    now = datetime.now()
    prefix = f"INV-{now.strftime('%Y%m')}-"
    raw = fb_get("/invoices") or {}
    nums = []
    for inv in (raw.values() if isinstance(raw, dict) else []):
        if isinstance(inv, dict):
            num = inv.get("meta", {}).get("invoice_number", "") or ""
            if num.startswith(prefix):
                try:
                    nums.append(int(num[len(prefix):]))
                except ValueError:
                    pass
    next_n = (max(nums) + 1) if nums else 1
    return f"{prefix}{next_n:03d}"

def _next_project_number() -> str:
    now = datetime.now()
    prefix = f"MABS-{now.strftime('%Y%m')}-"
    raw = fb_get("/projects") or {}
    nums = []
    for p in (raw.values() if isinstance(raw, dict) else []):
        if isinstance(p, dict):
            num = p.get("project_number", "") or ""
            if num.startswith(prefix):
                try:
                    nums.append(int(num[len(prefix):]))
                except ValueError:
                    pass
    next_n = (max(nums) + 1) if nums else 1
    return f"{prefix}{next_n:03d}"

def _parse_service_types(form) -> list:
    """Return service_types list, substituting 'Other' with 'Other: {specify}' when filled."""
    types = form.getlist("service_types[]")
    if not types:
        return None
    specify = form.get("other_specify", "").strip()
    if "Other" in types and specify:
        idx = types.index("Other")
        types[idx] = f"Other: {specify}"
    return types

def _parse_quote_form(form) -> dict:
    line_items = []
    descriptions = form.getlist("item_description[]")
    quantities   = form.getlist("item_quantity[]")
    unit_prices  = form.getlist("item_unit_price[]")
    for desc, qty, price in zip(descriptions, quantities, unit_prices):
        if desc.strip():
            line_items.append({
                "description": desc,
                "quantity":    qty,
                "unit_price":  price,
                "total":       str(_safe_float(qty) * _safe_float(price)),
            })
    return {
        "job_number":           form.get("job_number", ""),
        "client_name":          form.get("client_name", ""),
        "project_name":         form.get("project_name", ""),
        "description":          form.get("description", ""),
        "status":               form.get("status", "Not Started"),
        "salesperson":          form.get("salesperson", ""),
        "date":                 form.get("date", datetime.now().strftime("%Y-%m-%d")),
        "valid_until":          form.get("valid_until", ""),
        "expected_completion":  form.get("expected_completion", ""),
        "job_type":             form.get("job_type", ""),
        "service_types":        _parse_service_types(form),
        "priority":             form.get("priority", "Normal"),
        "is_expedited":         form.get("is_expedited") == "on",
        "rush_rate":            form.get("rush_rate", "0"),
        "rush_fee":             form.get("rush_fee", "0"),
        "line_items":           line_items,
        "subtotal":             form.get("subtotal", "0"),
        "tax_rate":             form.get("tax_rate", "0"),
        "tax_amount":           form.get("tax_amount", "0"),
        "total":                form.get("total", "0"),
        "notes":                form.get("notes", ""),
        "terms":                form.get("terms", ""),
        "follow_up_date":       form.get("follow_up_date", ""),
    }

def _resolve_installment_plan(data: dict) -> tuple:
    """Interpret the submitted installment selection into (mode, count, custom_amounts).

    Returns ('custom', n, [amounts]) when the user typed in their own irregular
    installment amounts (for clients who pay negotiated/random amounts rather than
    even splits), otherwise ('equal', n, None) for the standard equal-split plan.
    """
    raw = str(data.get("installment_count", "1")).strip().lower()
    if raw == "custom":
        amounts = [a for a in (_safe_float(x) for x in data.get("custom_installment_amounts", [])) if a > 0]
        if amounts:
            return "custom", len(amounts), amounts
        return "equal", 1, None
    return "equal", max(1, min(int(_safe_float(raw or 1)), 6)), None

def _compute_payment_stages(contract_value: float, down_pct: float, installments: int,
                            custom_amounts: list = None) -> list:
    """Build an ordered payment-stage plan from a contract value, down-payment %, and installment count.

    Mirrors the desktop app's down-payment + installment model: an optional down-payment
    stage up front, then the remaining balance either as one final payment, split evenly
    across 2-6 installments (the last absorbs any rounding remainder), or — when
    `custom_amounts` is given — billed out exactly as the user typed those amounts
    (for clients who pay irregular, negotiated amounts rather than equal splits).
    """
    contract_value = max(0.0, contract_value)
    down_pct = max(0.0, min(100.0, down_pct))

    stages = []
    remaining = contract_value
    if down_pct > 0:
        down_amt = round(contract_value * down_pct / 100.0, 2)
        stages.append({"name": f"Down Payment ({down_pct:.0f}%)", "amount": down_amt,
                       "status": "Pending Invoice", "invoice_id": ""})
        remaining = round(contract_value - down_amt, 2)

    custom_amounts = [round(max(0.0, a), 2) for a in (custom_amounts or []) if a > 0]
    if custom_amounts:
        for i, amt in enumerate(custom_amounts):
            stages.append({"name": f"Installment {i+1} of {len(custom_amounts)}", "amount": amt,
                           "status": "Pending Invoice", "invoice_id": ""})
        return stages

    installments = max(1, min(int(installments or 1), 6))
    if installments <= 1:
        label = "Final Payment" if down_pct > 0 else "Full Payment"
        stages.append({"name": label, "amount": remaining, "status": "Pending Invoice", "invoice_id": ""})
    else:
        per_installment = round(remaining / installments, 2)
        running = 0.0
        for i in range(installments):
            amt = per_installment if i < installments - 1 else round(remaining - running, 2)
            running += amt
            stages.append({"name": f"Installment {i+1} of {installments}", "amount": amt,
                           "status": "Pending Invoice", "invoice_id": ""})
    return stages

def _parse_project_form(form) -> dict:
    return {
        # ── identifiers (match desktop field names exactly) ──────────────────
        "project_number":  form.get("project_number", ""),
        "quote_number":    form.get("quote_number", ""),
        "po_wo_number":    form.get("po_wo_number", ""),
        # ── project info ─────────────────────────────────────────────────────
        "project_name":    form.get("project_name", ""),
        "company":         form.get("client_name", ""),   # desktop key = company
        "client_name":     form.get("client_name", ""),   # keep for web queries
        "site_address":    form.get("site_address", ""),
        "mail_address":    form.get("mail_address", ""),
        "date_received":   form.get("date_received", ""),
        "plant":           form.get("plant", ""),          # 2-letter state code
        "sales":           form.get("sales", ""),
        "job_type":        form.get("job_type", ""),
        "scope_of_work":   form.get("scope_of_work", ""),
        "expedite":        form.get("expedite", "No"),
        "description":     form.get("description", ""),
        "notes":           form.get("notes", ""),
        # ── dates ────────────────────────────────────────────────────────────
        "status":          form.get("status", "Not Started"),
        "start_date":      form.get("start_date", ""),
        "end_date":        form.get("end_date", ""),
        # ── financials ───────────────────────────────────────────────────────
        "contract_value":       form.get("contract_value", "0"),
        "project_amount":       form.get("contract_value", "0"),  # desktop key
        "payment_category":     form.get("payment_category", "Down Payment"),
        "amount_paid":          form.get("amount_paid", "0"),
        "down_payment_percent": form.get("down_payment_percent", "0"),
        "installment_count":    form.get("installment_count", "1"),
        "custom_installment_amounts": [a for a in form.getlist("custom_installment_amount[]") if str(a).strip()],
    }

def _parse_invoice_form(form) -> dict:
    line_items = []
    descriptions    = form.getlist("item_description[]")
    quantities      = form.getlist("item_quantity[]")
    unit_prices     = form.getlist("item_unit_price[]")
    item_projects   = form.getlist("item_project[]")  # Form field name is "item_project[]" not "item_project_number[]"
    main_project    = form.get("project_number", "").strip()
    for i, (desc, qty, price) in enumerate(zip(descriptions, quantities, unit_prices)):
        if desc.strip():
            item_proj = (item_projects[i].strip() if i < len(item_projects) else "")
            line_items.append({
                "description":    desc,
                "quantity":       qty,
                "unit_price":     price,
                "amount":         str(_safe_float(qty) * _safe_float(price)),
                # Empty = "bill under the invoice's main project" (the common case).
                # Set explicitly when an item belongs to a *different* project than
                # the one selected above, so one invoice can span multiple projects.
                "project_number": item_proj,
            })

    # Every distinct project referenced anywhere on this invoice (main selection +
    # any per-item overrides) — used to link this invoice on each project's detail
    # page and to prorate payments across projects when the invoice spans more than one.
    linked_projects = sorted({p for p in
                              ([main_project] + [li["project_number"] for li in line_items])
                              if p})

    return {
        "meta": {
            "invoice_number": form.get("invoice_number", ""),
            "invoice_date":   form.get("invoice_date", datetime.now().strftime("%Y-%m-%d")),
            "due_date":       form.get("due_date", ""),
            "client_name":    form.get("client_name", ""),
            "project_number": main_project,
            "linked_projects": linked_projects,
            "status":         form.get("status", "Draft"),
            "subtotal":       form.get("subtotal", "0"),
            "tax_rate":       form.get("tax_rate", "0"),
            "tax_amount":     form.get("tax_amount", "0"),
            "total":          form.get("total", "0"),
            "amount_paid":    form.get("amount_paid", "0"),
            "notes":          form.get("notes", ""),
            "terms":          form.get("terms", ""),
            "payment_method": form.get("payment_method", ""),
        },
        "line_items": line_items,
    }

def _invoice_project_share(invoice_data: dict, project_number: str) -> float:
    """Fraction (0-1) of an invoice's billed total attributable to one project.

    Single-project invoices (the common case) return 1.0. Multi-project invoices
    prorate by each project's share of the line-item subtotal, so payments and
    P&L roll up fairly across every project an invoice spans.
    """
    items = invoice_data.get("line_items", []) or []
    meta = invoice_data.get("meta", {}) or {}
    main_project = meta.get("project_number", "")

    item_amounts = [(str(it.get("project_number", "")).strip() or main_project,
                     _safe_float(it.get("amount", 0))) for it in items]
    total = sum(a for _, a in item_amounts)

    # Debug: print what we're calculating
    inv_num = meta.get("invoice_number", "?")
    print(f"[SHARE] Invoice {inv_num}, project={project_number}: item_amounts={item_amounts}, total={total}", flush=True)

    if total <= 0:
        # No usable line-item amounts — check if this project is in linked_projects
        # (for multi-project invoices where project_number isn't set in line items)
        linked_projects = meta.get("linked_projects", [])
        print(f"[SHARE] Total<=0, checking linked_projects={linked_projects}", flush=True)
        if isinstance(linked_projects, list):
            if any(isinstance(lp, dict) and lp.get("project_number") == project_number for lp in linked_projects):
                # This project is part of the multi-project invoice - equal share
                share = 1.0 / len(linked_projects) if linked_projects else 1.0
                print(f"[SHARE] Found in linked_projects, share={share}", flush=True)
                return share
        # Fall back to whole-invoice attribution for the (single) project this invoice names
        fallback = 1.0 if main_project == project_number else 0.0
        print(f"[SHARE] Fallback share={fallback}", flush=True)
        return fallback

    project_amount = sum(a for pn, a in item_amounts if pn == project_number)
    share = project_amount / total
    print(f"[SHARE] Calculated share={share} (project_amount={project_amount})", flush=True)
    return share

def _invoice_linked_projects(invoice_data: dict) -> set:
    """All project numbers an invoice is linked to (main selection + per-item overrides)."""
    meta = invoice_data.get("meta", {}) or {}
    linked = set()

    # Extract project numbers from linked_projects (list of dicts with {project_number, payment_stage_index})
    linked_projects = meta.get("linked_projects") or []
    if isinstance(linked_projects, list):
        for item in linked_projects:
            if isinstance(item, dict):
                pn = item.get("project_number", "")
                if pn:
                    linked.add(pn)

    if not linked:
        main_project = meta.get("project_number", "")
        if main_project:
            linked.add(main_project)
        for it in (invoice_data.get("line_items", []) or []):
            pn = str(it.get("project_number", "")).strip()
            if pn:
                linked.add(pn)
    return linked

# ── Routes: Workflow conversions ─────────────────────────────────────────────
@app.route("/quotes/<quote_id>/to-project", methods=["POST"])
@role_required("projects")
def quote_to_project(quote_id):
    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        abort(404)
    proj_num = _next_project_number()
    project_data = {
        "project_number":   proj_num,
        "project_name":     quote.get("project_name", quote.get("description", "")),
        "client_name":      quote.get("client_name", ""),
        "description":      quote.get("description", ""),
        "status":           "In Progress",
        "start_date":       datetime.now().strftime("%Y-%m-%d"),
        "end_date":         "",
        "contract_value":   str(quote.get("total", "0")),
        "payment_category": "Down Payment",
        "down_payment_percent":       0.0,
        "installment_count":          1,
        "installment_mode":           "equal",
        "custom_installment_amounts": [],
        "payment_stages":   _compute_payment_stages(_safe_float(quote.get("total", "0")), 0.0, 1),
        "amount_paid":      "0",
        "notes":            quote.get("notes", ""),
        "assigned_to":      quote.get("salesperson", ""),
        "source_quote":     quote_id,
        "source_quote_num": quote.get("job_number", ""),
        "created_at":       datetime.now(timezone.utc).isoformat(),
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        "created_by":       session.get("user_email", ""),
    }
    pid = fb_push("/projects", project_data)
    fb_update(f"/job_forms/{quote_id}", {
        "status":     "Converted",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    flash(f"Quote converted to Project {proj_num}.", "success")
    return redirect(url_for("project_detail", project_id=pid))

@app.route("/quotes/<quote_id>/to-invoice", methods=["POST"])
@role_required("invoicing")
def quote_to_invoice(quote_id):
    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        abort(404)
    inv_num = _next_invoice_number()
    # Find the project linked to this quote (if any)
    linked_proj_num = ""
    raw_proj = fb_get("/projects") or {}
    if isinstance(raw_proj, dict):
        for p in raw_proj.values():
            if isinstance(p, dict) and p.get("source_quote") == quote_id:
                linked_proj_num = p.get("project_number", "")
                break
    # Map quote line items → invoice line items
    inv_items = []
    for item in quote.get("line_items", []):
        inv_items.append({
            "description": item.get("description", ""),
            "quantity":    item.get("quantity", "1"),
            "unit_price":  item.get("unit_price", "0"),
            "amount":      item.get("total", item.get("amount", "0")),
        })
    invoice_data = {
        "meta": {
            "invoice_number": inv_num,
            "invoice_date":   datetime.now().strftime("%Y-%m-%d"),
            "due_date":       (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "client_name":    quote.get("client_name", ""),
            "project_number": linked_proj_num,
            "status":         "Draft",
            "subtotal":       str(quote.get("subtotal", "0")),
            "tax_rate":       str(quote.get("tax_rate", "0")),
            "tax_amount":     str(quote.get("tax_amount", "0")),
            "total":          str(quote.get("total", "0")),
            "amount_paid":    "0",
            "notes":          quote.get("notes", ""),
            "terms":          quote.get("terms", ""),
            "payment_method": "",
            "source_quote":   quote_id,
            "created_at":     datetime.now(timezone.utc).isoformat(),
            "updated_at":     datetime.now(timezone.utc).isoformat(),
            "created_by":     session.get("user_email", ""),
        },
        "line_items": inv_items,
    }
    iid = fb_push("/invoices", invoice_data)
    fb_update(f"/job_forms/{quote_id}", {
        "status":     "Invoiced",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    flash(f"Invoice {inv_num} created from quote.", "success")
    return redirect(url_for("invoice_detail", invoice_id=iid))

@app.route("/quotes/<quote_id>/win", methods=["POST"])
@role_required("quotes")
def quote_win(quote_id):
    """Win a quote in one click: creates Project + Invoice simultaneously."""
    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        abort(404)

    now_str  = datetime.now(timezone.utc).isoformat()
    today    = datetime.now().strftime("%Y-%m-%d")
    user     = session.get("user_email", "")

    # ── 1. Create Project ─────────────────────────────────────────────────────
    proj_num = _next_project_number()
    project_data = {
        "project_number":   proj_num,
        "project_name":     quote.get("project_name", quote.get("description", "")),
        "client_name":      quote.get("client_name", ""),
        "description":      quote.get("description", ""),
        "status":           "In Progress",
        "start_date":       today,
        "end_date":         quote.get("expected_completion", ""),
        "contract_value":   str(quote.get("total", "0")),
        "payment_category": "Down Payment",
        "down_payment_percent":       0.0,
        "installment_count":          1,
        "installment_mode":           "equal",
        "custom_installment_amounts": [],
        "payment_stages":   _compute_payment_stages(_safe_float(quote.get("total", "0")), 0.0, 1),
        "amount_paid":      "0",
        "notes":            quote.get("notes", ""),
        "assigned_to":      quote.get("salesperson", ""),
        "source_quote":     quote_id,
        "source_quote_num": quote.get("job_number", ""),
        "created_at":       now_str,
        "updated_at":       now_str,
        "created_by":       user,
    }
    pid = fb_push("/projects", project_data)

    # ── 2. Mark quote as Converted + store back-link to project only ─────────
    fb_update(f"/job_forms/{quote_id}", {
        "status":              "Converted",
        "linked_project_id":   pid,
        "linked_project_num":  proj_num,
        "updated_at":          now_str,
    })

    flash(f"Quote won! Project {proj_num} created. Generate invoices from the project page.", "success")
    return redirect(url_for("project_detail", project_id=pid))

@app.route("/quotes/<quote_id>/pdf")
@role_required("quotes")
def quote_pdf(quote_id):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch, mm
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("quote_detail", quote_id=quote_id))

    import io as _io
    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        abort(404)

    co = company_info()
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    elems = []

    teal   = colors.HexColor("#0F766E")
    dark   = colors.HexColor("#0F172A")
    muted  = colors.HexColor("#64748B")
    light  = colors.HexColor("#F8FAFC")
    border = colors.HexColor("#E2E8F0")

    h1  = ParagraphStyle("h1",  parent=styles["Normal"], fontSize=20, fontName="Helvetica-Bold", textColor=teal)
    h2  = ParagraphStyle("h2",  parent=styles["Normal"], fontSize=11, fontName="Helvetica-Bold", textColor=dark, spaceBefore=10, spaceAfter=4)
    lbl = ParagraphStyle("lbl", parent=styles["Normal"], fontSize=8,  fontName="Helvetica-Bold", textColor=muted, spaceAfter=1)
    val = ParagraphStyle("val", parent=styles["Normal"], fontSize=10, fontName="Helvetica",       textColor=dark, spaceAfter=6)
    sm  = ParagraphStyle("sm",  parent=styles["Normal"], fontSize=9,  fontName="Helvetica",       textColor=muted)

    # ── Header ──
    addr = (co.get("address","") or "").replace("\n", " | ")
    hdr_data = [[
        Paragraph(f"<b>{co.get('name','')}</b>", ParagraphStyle("cn", parent=styles["Normal"], fontSize=14, fontName="Helvetica-Bold", textColor=dark)),
        Paragraph("QUOTE", ParagraphStyle("qt", parent=styles["Normal"], fontSize=24, fontName="Helvetica-Bold", textColor=teal, alignment=2)),
    ],[
        Paragraph(f"{addr}<br/>{co.get('phone','')}  |  {co.get('email','')}", sm),
        Paragraph(f"<b>#{quote.get('job_number','')}</b>", ParagraphStyle("qn", parent=styles["Normal"], fontSize=12, fontName="Helvetica-Bold", textColor=dark, alignment=2)),
    ]]
    hdr = Table(hdr_data, colWidths=[3.5*inch, 3.5*inch])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elems.append(hdr)
    elems.append(HRFlowable(width="100%", thickness=2, color=teal, spaceAfter=12))

    # ── Meta row ──
    meta_data = [[
        Paragraph("PREPARED FOR", lbl),
        Paragraph("DATE", lbl),
        Paragraph("VALID UNTIL", lbl),
        Paragraph("STATUS", lbl),
    ],[
        Paragraph(quote.get("client_name","—"), val),
        Paragraph(quote.get("date","—"), val),
        Paragraph(quote.get("valid_until","—"), val),
        Paragraph(quote.get("status","—"), val),
    ]]
    mt = Table(meta_data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    mt.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0)]))
    elems.append(mt)

    # ── Scope ──
    if quote.get("project_name"):
        elems.append(Spacer(1, 8))
        elems.append(Paragraph("PROJECT / SCOPE", lbl))
        elems.append(Paragraph(quote.get("project_name",""), val))
    if quote.get("description"):
        elems.append(Paragraph("DESCRIPTION", lbl))
        elems.append(Paragraph(quote.get("description",""), sm))

    # ── Line items ──
    elems.append(Spacer(1, 10))
    elems.append(Paragraph("LINE ITEMS", h2))
    li_hdr = [["Description", "Qty", "Unit Price", "Amount"]]
    li_rows = []
    for item in quote.get("line_items", []):
        li_rows.append([
            item.get("description",""),
            str(item.get("quantity","")),
            f"${_safe_float(item.get('unit_price',0)):,.2f}",
            f"${_safe_float(item.get('total',item.get('amount',0))):,.2f}",
        ])
    if not li_rows:
        li_rows = [["No line items", "", "", ""]]
    li_data = li_hdr + li_rows
    li_cw = [3.4*inch, 0.7*inch, 1.2*inch, 1.2*inch]
    li_tbl = Table(li_data, colWidths=li_cw, repeatRows=1)
    li_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), dark),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,0), 9),
        ("ALIGN",      (1,0), (-1,-1), "RIGHT"),
        ("FONTNAME",   (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",   (0,1), (-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, light]),
        ("GRID",       (0,0), (-1,-1), 0.4, border),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    elems.append(li_tbl)

    # ── Totals ──
    tax_rate = _safe_float(quote.get("tax_rate", 0))
    totals = [
        ["Subtotal", f"${_safe_float(quote.get('subtotal',0)):,.2f}"],
        [f"Tax ({tax_rate:.2g}%)", f"${_safe_float(quote.get('tax_amount',0)):,.2f}"],
        ["TOTAL DUE", f"${_safe_float(quote.get('total',0)):,.2f}"],
    ]
    tot_tbl = Table(totals, colWidths=[5.9*inch, 0.6*inch])
    tot_tbl.setStyle(TableStyle([
        ("ALIGN",      (0,0), (-1,-1), "RIGHT"),
        ("FONTNAME",   (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("FONTNAME",   (0,2), (-1,2),  "Helvetica-Bold"),
        ("FONTSIZE",   (0,2), (-1,2),  11),
        ("TEXTCOLOR",  (0,2), (-1,2),  teal),
        ("LINEABOVE",  (0,2), (-1,2),  1, teal),
        ("TOPPADDING", (0,0), (-1,-1), 4),
    ]))
    elems.append(tot_tbl)

    # ── Notes / Terms ──
    if quote.get("notes"):
        elems.append(Spacer(1, 10))
        elems.append(Paragraph("NOTES", lbl))
        elems.append(Paragraph(quote.get("notes",""), sm))
    if quote.get("terms"):
        elems.append(Spacer(1, 6))
        elems.append(Paragraph("TERMS & CONDITIONS", lbl))
        elems.append(Paragraph(quote.get("terms",""), sm))

    doc.build(elems)
    buf.seek(0)
    from flask import Response
    fname = f"Quote_{quote.get('job_number','')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline;filename={fname}"})

@app.route("/projects/<project_id>/pdf")
@role_required("projects")
def project_pdf(project_id):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("project_detail", project_id=project_id))

    import io as _io
    project = fb_get(f"/projects/{project_id}")
    if not project:
        abort(404)

    co = company_info()
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    elems = []

    teal   = colors.HexColor("#0F766E")
    dark   = colors.HexColor("#0F172A")
    muted  = colors.HexColor("#64748B")
    light  = colors.HexColor("#F8FAFC")
    border = colors.HexColor("#E2E8F0")

    lbl = ParagraphStyle("lbl", parent=styles["Normal"], fontSize=8,  fontName="Helvetica-Bold", textColor=muted, spaceAfter=1)
    val = ParagraphStyle("val", parent=styles["Normal"], fontSize=10, fontName="Helvetica",       textColor=dark, spaceAfter=8)
    sm  = ParagraphStyle("sm",  parent=styles["Normal"], fontSize=9,  fontName="Helvetica",       textColor=muted)
    h2  = ParagraphStyle("h2",  parent=styles["Normal"], fontSize=11, fontName="Helvetica-Bold",  textColor=dark, spaceBefore=12, spaceAfter=6)

    # ── Header ──
    addr = (co.get("address","") or "").replace("\n", " | ")
    hdr_data = [[
        Paragraph(f"<b>{co.get('name','')}</b>", ParagraphStyle("cn", parent=styles["Normal"], fontSize=14, fontName="Helvetica-Bold", textColor=dark)),
        Paragraph("PROJECT DOCUMENT", ParagraphStyle("pd", parent=styles["Normal"], fontSize=18, fontName="Helvetica-Bold", textColor=teal, alignment=2)),
    ],[
        Paragraph(f"{addr}<br/>{co.get('phone','')}  |  {co.get('email','')}", sm),
        Paragraph(f"<b>{project.get('project_number','')}</b>", ParagraphStyle("pn", parent=styles["Normal"], fontSize=12, fontName="Helvetica-Bold", textColor=dark, alignment=2)),
    ]]
    hdr = Table(hdr_data, colWidths=[3.5*inch, 3.5*inch])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    elems.append(hdr)
    elems.append(HRFlowable(width="100%", thickness=2, color=teal, spaceAfter=12))

    # ── Project meta ──
    meta = [
        [Paragraph("CLIENT", lbl),       Paragraph("STATUS", lbl),          Paragraph("START DATE", lbl),       Paragraph("END DATE", lbl)],
        [Paragraph(project.get("client_name","—"), val), Paragraph(project.get("status","—"), val), Paragraph(project.get("start_date","—"), val), Paragraph(project.get("end_date","—") or "—", val)],
        [Paragraph("PROJECT NAME", lbl), Paragraph("", lbl), Paragraph("ASSIGNED TO", lbl), Paragraph("PAYMENT STAGE", lbl)],
        [Paragraph(project.get("project_name","—"), val), Paragraph("", val), Paragraph(project.get("assigned_to","—") or "—", val), Paragraph(project.get("payment_category","—") or "—", val)],
    ]
    mt = Table(meta, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    mt.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("SPAN",(0,2),(1,2)), ("SPAN",(0,3),(1,3))]))
    elems.append(mt)

    # ── Scope ──
    if project.get("description"):
        elems.append(Paragraph("SCOPE OF WORK", h2))
        elems.append(HRFlowable(width="100%", thickness=0.5, color=border, spaceAfter=6))
        elems.append(Paragraph(project.get("description",""), sm))

    # ── Financial summary ──
    cv   = _safe_float(project.get("contract_value", 0))
    paid = _safe_float(project.get("amount_paid",    0))
    outstanding = cv - paid
    pct  = int(paid / cv * 100) if cv > 0 else 0

    elems.append(Paragraph("FINANCIAL SUMMARY", h2))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=border, spaceAfter=6))
    fin_data = [
        ["Contract Value",  f"${cv:,.2f}"],
        ["Amount Paid",     f"${paid:,.2f}"],
        ["Outstanding",     f"${outstanding:,.2f}"],
        ["Collection Rate", f"{pct}%"],
        ["Payment Stage",   project.get("payment_category","—") or "—"],
    ]
    fin_tbl = Table(fin_data, colWidths=[2.5*inch, 2*inch])
    fin_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0), (-1,-1), 10),
        ("TEXTCOLOR",     (0,0), (0,-1),  muted),
        ("FONTNAME",      (1,0), (1,-1),  "Helvetica-Bold"),
        ("TEXTCOLOR",     (1,2), (1,2),   colors.HexColor("#DC2626") if outstanding > 0 else teal),
        ("TEXTCOLOR",     (1,0), (1,0),   teal),
        ("ROWBACKGROUNDS",(0,0), (-1,-1), [colors.white, light]),
        ("GRID",          (0,0), (-1,-1), 0.4, border),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ]))
    elems.append(fin_tbl)

    # ── Notes ──
    if project.get("notes"):
        elems.append(Paragraph("NOTES", h2))
        elems.append(HRFlowable(width="100%", thickness=0.5, color=border, spaceAfter=6))
        elems.append(Paragraph(project.get("notes",""), sm))

    # ── Signature block ──
    elems.append(Spacer(1, 30))
    sig_data = [[
        Paragraph("_" * 35, ParagraphStyle("sig", parent=styles["Normal"], fontSize=10)),
        Paragraph("_" * 35, ParagraphStyle("sig2", parent=styles["Normal"], fontSize=10)),
    ],[
        Paragraph(f"Client Signature — {project.get('client_name','')}", sm),
        Paragraph(f"Authorized — {co.get('name','')}", sm),
    ],[
        Paragraph("Date: _______________", sm),
        Paragraph("Date: _______________", sm),
    ]]
    sig = Table(sig_data, colWidths=[3.5*inch, 3.5*inch])
    sig.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("TOPPADDING",(0,0),(-1,-1),4)]))
    elems.append(sig)

    # ── Footer ──
    elems.append(Spacer(1, 20))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=border, spaceAfter=4))
    gen_date = datetime.now().strftime("%B %d, %Y")
    elems.append(Paragraph(f"Document generated {gen_date}  ·  {co.get('name','')}  ·  {co.get('phone','')}  ·  {co.get('email','')}", sm))

    doc.build(elems)
    buf.seek(0)
    from flask import Response
    fname = f"Project_{project.get('project_number','doc')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline;filename={fname}"})

# ── Email helper ─────────────────────────────────────────────────────────────
def _send_invoice_email(invoice_id: str):
    """Send invoice HTML email to the client. Returns (ok: bool, message: str)."""
    settings = load_settings()
    em = settings.get("email", {})

    if not em.get("enabled"):
        return False, "Email sending is disabled. Enable it in Settings → Email/SMTP."

    invoice = fb_get(f"/invoices/{invoice_id}")
    if not invoice:
        return False, "Invoice not found."

    meta        = invoice.get("meta", {})
    client_name = meta.get("client_name", "")
    client_data = fb_get(f"/clients/{client_name}") or {}
    client_email = client_data.get("email", "")
    if not client_email:
        return False, f"No email on file for '{client_name}'. Add it in Clients."

    co = company_info()

    # Build line-items HTML rows
    rows_html = ""
    for item in invoice.get("line_items", []):
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e5e7eb;'>{item.get('description','')}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:right;'>{item.get('quantity','')}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:right;'>"
            f"${_safe_float(item.get('unit_price',0)):,.2f}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:right;'>"
            f"${_safe_float(item.get('amount',0)):,.2f}</td>"
            f"</tr>"
        )

    notes_block = (f"<p style='margin:8px 0;'><strong>Notes:</strong> {meta.get('notes')}</p>"
                   if meta.get("notes") else "")
    terms_block = (f"<p style='margin:8px 0;'><strong>Terms:</strong> {meta.get('terms')}</p>"
                   if meta.get("terms") else "")

    html_body = f"""
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:640px;margin:auto;">
<div style="background:#0F766E;color:white;padding:24px;border-radius:8px 8px 0 0;">
  <h2 style="margin:0 0 4px;">{co.get('name','')}</h2>
  <div style="opacity:.8;font-size:12px;">{co.get('address','').replace(chr(10),', ')} &nbsp;|&nbsp;
    {co.get('phone','')} &nbsp;|&nbsp; {co.get('email','')}</div>
</div>
<div style="padding:24px;background:#fff;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
  <h3 style="color:#0F766E;margin:0 0 4px;">INVOICE #{meta.get('invoice_number','')}</h3>
  <table style="width:100%;margin-bottom:16px;font-size:13px;">
    <tr>
      <td><strong>Bill To:</strong> {client_name}</td>
      <td style="text-align:right;"><strong>Date:</strong> {meta.get('invoice_date','—')}</td>
    </tr>
    <tr>
      <td></td>
      <td style="text-align:right;"><strong>Due:</strong> {meta.get('due_date','—')}</td>
    </tr>
  </table>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <thead>
      <tr style="background:#0F172A;color:white;">
        <th style="padding:8px;text-align:left;">Description</th>
        <th style="padding:8px;text-align:right;">Qty</th>
        <th style="padding:8px;text-align:right;">Unit Price</th>
        <th style="padding:8px;text-align:right;">Amount</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
    <tfoot>
      <tr>
        <td colspan="3" style="padding:8px;text-align:right;">Subtotal</td>
        <td style="padding:8px;text-align:right;">${_safe_float(meta.get('subtotal',0)):,.2f}</td>
      </tr>
      <tr style="font-size:15px;font-weight:bold;color:#0F766E;">
        <td colspan="3" style="padding:8px;text-align:right;">Total Due</td>
        <td style="padding:8px;text-align:right;">${_safe_float(meta.get('total',0)):,.2f}</td>
      </tr>
    </tfoot>
  </table>
  {notes_block}{terms_block}
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Invoice #{meta.get('invoice_number','')} from {co.get('name','')}"
        msg["From"]    = f"{em.get('from_name', co.get('name',''))} <{em.get('smtp_user','')}>"
        msg["To"]      = client_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(em.get("smtp_host", "smtp.gmail.com"),
                          int(em.get("smtp_port", 587))) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(em.get("smtp_user", ""), em.get("smtp_password", ""))
            srv.sendmail(em.get("smtp_user", ""), [client_email], msg.as_string())

        return True, f"Invoice emailed to {client_email}."
    except Exception as exc:
        log.error("Email send error: %s", exc)
        return False, f"Failed to send email: {exc}"

@app.route("/invoicing/<invoice_id>/send", methods=["POST"])
@role_required("invoicing")
def invoice_send(invoice_id):
    ok, msg = _send_invoice_email(invoice_id)
    if ok:
        fb_update(f"/invoices/{invoice_id}", {
            "meta/status": "Sent",
            "meta/updated_at": datetime.now(timezone.utc).isoformat(),
        })
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))

@app.route("/invoicing/<invoice_id>/payment/add", methods=["POST"])
@role_required("invoicing")
def payment_add(invoice_id):
    """Record a payment received against an invoice (for line items, not tax)."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    log = inv_data.get("payment_log", [])
    if not isinstance(log, list):
        log = []

    amount = _safe_float(request.form.get("amount", 0))
    if amount <= 0:
        return jsonify({"error": "Invalid payment amount"}), 400

    # For multi-project invoices, store which project this payment applies to
    # For single-project invoices, auto-fill from invoice metadata
    project_number = request.form.get("project_number", "") or inv_data.get("meta", {}).get("project_number", "")

    payment_entry = {
        "amount":     str(amount),
        "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
        "method":     request.form.get("method", ""),
        "reference":  request.form.get("reference", ""),
        "notes":      request.form.get("notes", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if project_number:
        payment_entry["project_number"] = project_number

    log.append(payment_entry)

    amount_paid = sum(_safe_float(p.get("amount", 0)) for p in log)
    fresh_inv = dict(inv_data)
    fresh_inv["payment_log"] = log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "payment_log":      log,
        "meta/amount_paid": str(amount_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })
    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)
        if new_status == "Paid":
            _auto_complete_project_if_paid(proj_num)
    fresh_meta = (fb_get(f"/invoices/{invoice_id}") or {}).get("meta", {})
    _upsert_revenue_entry(invoice_id, fresh_meta)

    return jsonify({"success": True, "amount": amount}), 200

@app.route("/invoicing/<invoice_id>/tax/add", methods=["POST"])
@role_required("invoicing")
def tax_payment_add(invoice_id):
    """Record a tax payment against an invoice."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    tax_log = inv_data.get("tax_payments", [])
    if not isinstance(tax_log, list):
        tax_log = []

    amount = _safe_float(request.form.get("amount") or request.form.get("tax_amount", 0))
    if amount <= 0:
        return jsonify({"error": "Invalid tax payment amount"}), 400

    tax_log.append({
        "amount":     str(amount),
        "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
        "method":     request.form.get("method", ""),
        "reference":  request.form.get("reference", ""),
        "notes":      request.form.get("notes", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
    fresh_inv = dict(inv_data)
    fresh_inv["tax_payments"] = tax_log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "tax_payments":     tax_log,
        "meta/tax_paid":    str(tax_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })
    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    fresh_meta = (fb_get(f"/invoices/{invoice_id}") or {}).get("meta", {})
    _upsert_revenue_entry(invoice_id, fresh_meta)

    return jsonify({"success": True, "amount": amount}), 200

@app.route("/invoicing/<invoice_id>/payment/full", methods=["POST"])
@role_required("invoicing")
def payment_full(invoice_id):
    """Record a full invoice payment distributed proportionally across projects."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    log = inv_data.get("payment_log", [])
    if not isinstance(log, list):
        log = []

    amount = _safe_float(request.form.get("amount", 0))
    if amount <= 0:
        return jsonify({"error": "Invalid payment amount"}), 400

    # Get all linked projects
    linked_projects = inv_data.get("meta", {}).get("linked_projects", [])
    invoice_total = _safe_float(inv_data.get("meta", {}).get("total", 0))
    tax_amount = _safe_float(inv_data.get("meta", {}).get("tax_amount", 0))
    project_subtotal = invoice_total - tax_amount

    # Distribute payment proportionally across projects (based on REMAINING amounts)
    payment_date = request.form.get("date", datetime.now().strftime("%Y-%m-%d"))
    payment_method = request.form.get("method", "")
    payment_reference = request.form.get("reference", "")
    payment_notes = request.form.get("notes", "")

    if project_subtotal > 0 and linked_projects:
        # Calculate each project's remaining amount from invoice items and payments
        meta_items = inv_data.get("meta", {}).get("items", [])
        project_remainings = {}
        total_remaining = 0

        if isinstance(meta_items, list):
            for proj_info in linked_projects:
                if not isinstance(proj_info, dict):
                    continue

                project_number = proj_info.get("project_number", "")
                if not project_number:
                    continue

                # Find this project's original amount from invoice items
                proj_amount = 0
                for item in meta_items:
                    if isinstance(item, dict) and item.get("project_number") == project_number:
                        proj_amount = _safe_float(item.get("amount", 0))
                        break

                if proj_amount <= 0:
                    continue

                # Calculate how much this project has already been paid
                proj_paid = sum(
                    _safe_float(p.get("amount", 0))
                    for p in log
                    if p.get("project_number") == project_number
                )

                # Calculate remaining amount for this project
                proj_remaining = max(0, proj_amount - proj_paid)
                if proj_remaining > 0:
                    project_remainings[project_number] = proj_remaining
                    total_remaining += proj_remaining

        # Distribute payment proportionally across remaining amounts
        if total_remaining > 0:
            for project_number, remaining in project_remainings.items():
                # Calculate this project's share of the payment based on remaining amount
                project_share = (remaining / total_remaining) * amount

                # Create payment entry for this project
                payment_entry = {
                    "amount":     str(project_share),
                    "date":       payment_date,
                    "method":     payment_method,
                    "reference":  payment_reference,
                    "notes":      payment_notes,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project_number": project_number,
                }
                log.append(payment_entry)
    else:
        # Single project or no projects - just add the amount
        payment_entry = {
            "amount":     str(amount),
            "date":       payment_date,
            "method":     payment_method,
            "reference":  payment_reference,
            "notes":      payment_notes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        proj_num = inv_data.get("meta", {}).get("project_number", "")
        if proj_num:
            payment_entry["project_number"] = proj_num
        log.append(payment_entry)

    amount_paid = sum(_safe_float(p.get("amount", 0)) for p in log)
    fresh_inv = dict(inv_data)
    fresh_inv["payment_log"] = log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "payment_log":      log,
        "meta/amount_paid": str(amount_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })

    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)
        if new_status == "Paid":
            _auto_complete_project_if_paid(proj_num)

    fresh_meta = (fb_get(f"/invoices/{invoice_id}") or {}).get("meta", {})
    _upsert_revenue_entry(invoice_id, fresh_meta)

    return jsonify({"success": True, "amount": amount}), 200

@app.route("/invoicing/<invoice_id>/payment/sequential", methods=["POST"])
@role_required("invoicing")
def payment_sequential(invoice_id):
    """Record payment distributed sequentially across projects then tax."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    meta = inv_data.get("meta", {}) or {}

    amount = _safe_float(request.form.get("amount", 0))
    status = request.form.get("status", "Partial")

    if amount <= 0:
        return jsonify({"error": "Invalid payment amount"}), 400

    payment_log = inv_data.get("payment_log", [])
    if not isinstance(payment_log, list):
        payment_log = []

    # Get invoice details
    linked_projects = meta.get("linked_projects", [])
    # Items are in line_items, not meta.items
    line_items = inv_data.get("line_items", []) or []
    tax_amount = _safe_float(meta.get("tax_amount", 0))
    main_project = meta.get("project_number", "")

    remaining_to_distribute = amount

    # Initialize tax_log - will be updated in Step 2 if needed
    tax_log = inv_data.get("tax_payments", [])
    if not isinstance(tax_log, list):
        tax_log = []

    # Step 1: Distribute sequentially to projects
    if remaining_to_distribute > 0 and linked_projects:
        for proj_info in linked_projects:
            if not isinstance(proj_info, dict) or remaining_to_distribute <= 0:
                continue

            project_number = proj_info.get("project_number", "")
            if not project_number:
                continue

            # Find project amount from line items
            proj_amount = 0
            for item in line_items:
                if isinstance(item, dict):
                    item_proj = item.get("project_number", "").strip() or main_project
                    if item_proj == project_number:
                        proj_amount += _safe_float(item.get("amount", 0))

            if proj_amount <= 0:
                continue

            # Calculate how much this project has already received
            proj_received = sum(
                _safe_float(p.get("amount", 0))
                for p in payment_log
                if p.get("project_number") == project_number
            )

            # How much more does this project need?
            proj_needs = max(0, proj_amount - proj_received)

            if proj_needs > 0:
                # Distribute amount to this project
                distribute_to_proj = min(proj_needs, remaining_to_distribute)

                payment_entry = {
                    "amount":     str(distribute_to_proj),
                    "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "method":     request.form.get("method", ""),
                    "reference":  request.form.get("reference", ""),
                    "notes":      request.form.get("notes", ""),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project_number": project_number,
                }
                payment_log.append(payment_entry)
                remaining_to_distribute -= distribute_to_proj

    # Step 2: Distribute remaining to tax
    if remaining_to_distribute > 0 and tax_amount > 0:
        tax_received = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
        tax_needs = max(0, tax_amount - tax_received)

        if tax_needs > 0:
            distribute_to_tax = min(tax_needs, remaining_to_distribute)
            tax_log.append({
                "amount":     str(distribute_to_tax),
                "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
                "method":     request.form.get("method", ""),
                "reference":  request.form.get("reference", ""),
                "notes":      request.form.get("notes", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            remaining_to_distribute -= distribute_to_tax

        fb_update(f"/invoices/{invoice_id}", {"tax_payments": tax_log})

    # Calculate totals and update invoice
    amount_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log)
    tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)

    fresh_inv = dict(inv_data)
    fresh_inv["payment_log"] = payment_log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "payment_log":      payment_log,
        "meta/amount_paid": str(amount_paid),
        "meta/tax_paid":    str(tax_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })

    # Update project stage payment statuses
    _update_project_stage_payment_status(invoice_id)

    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)
        if new_status == "Paid":
            _auto_complete_project_if_paid(proj_num)

    fresh_meta = (fb_get(f"/invoices/{invoice_id}") or {}).get("meta", {})
    _upsert_revenue_entry(invoice_id, fresh_meta)

    return jsonify({"success": True, "amount": amount}), 200

@app.route("/invoicing/<invoice_id>/payment/delete/<int:idx>", methods=["POST"])
@role_required("invoicing")
def payment_delete(invoice_id, idx):
    """Remove a payment entry from the log."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    log = inv_data.get("payment_log", [])
    if not isinstance(log, list) or idx >= len(log):
        return jsonify({"error": "Payment not found"}), 404

    log.pop(idx)
    total       = _safe_float(inv_data.get("meta", {}).get("total", 0))
    amount_paid = sum(_safe_float(p["amount"]) for p in log)
    any_paid    = amount_paid > 0
    fresh_inv = dict(inv_data)
    fresh_inv["payment_log"] = log
    new_status  = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "payment_log":      log,
        "meta/amount_paid": str(amount_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })
    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)
    return jsonify({"success": True}), 200

@app.route("/invoicing/<invoice_id>/tax/payment/delete/<int:idx>", methods=["POST"])
@role_required("invoicing")
def tax_payment_delete(invoice_id, idx):
    """Remove a tax payment entry from the log."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    tax_log = inv_data.get("tax_payments", [])
    if not isinstance(tax_log, list) or idx >= len(tax_log):
        return jsonify({"error": "Tax payment not found"}), 404

    tax_log.pop(idx)
    tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
    fresh_inv = dict(inv_data)
    fresh_inv["tax_payments"] = tax_log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "tax_payments":     tax_log,
        "meta/tax_paid":    str(tax_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })
    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    return jsonify({"success": True}), 200

@app.route("/invoicing/<invoice_id>/payment/<int:idx>/edit", methods=["POST"])
@role_required("invoicing")
def payment_edit(invoice_id, idx):
    """Update a payment entry in the log."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    log = inv_data.get("payment_log", [])
    if not isinstance(log, list) or idx >= len(log):
        return jsonify({"error": "Payment not found"}), 404

    amount = _safe_float(request.form.get("amount", 0))
    if amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    log[idx].update({
        "amount": str(amount),
        "date": request.form.get("date", ""),
        "method": request.form.get("method", ""),
        "reference": request.form.get("reference", ""),
        "notes": request.form.get("notes", ""),
    })

    invoice_paid = sum(_safe_float(p.get("amount", 0)) for p in log)
    fresh_inv = dict(inv_data)
    fresh_inv["payment_log"] = log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "payment_log":          log,
        "meta/amount_paid":     str(invoice_paid),
        "meta/status":          new_status,
        "meta/updated_at":      datetime.now(timezone.utc).isoformat(),
    })
    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    # Sync project payments for all linked projects
    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)

    return jsonify({"success": True}), 200

@app.route("/invoicing/<invoice_id>/tax/payment/edit/<int:idx>", methods=["POST"])
@role_required("invoicing")
def tax_payment_edit(invoice_id, idx):
    """Update a tax payment entry in the log."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    log = inv_data.get("tax_payments", [])
    if not isinstance(log, list) or idx >= len(log):
        return jsonify({"error": "Tax payment not found"}), 404

    amount = _safe_float(request.form.get("amount", 0))
    if amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    log[idx].update({
        "amount": str(amount),
        "date": request.form.get("date", ""),
        "method": request.form.get("method", ""),
        "reference": request.form.get("reference", ""),
        "notes": request.form.get("notes", ""),
    })

    tax_paid = sum(_safe_float(p.get("amount", 0)) for p in log)
    fresh_inv = dict(inv_data)
    fresh_inv["tax_payments"] = log
    new_status = _calculate_invoice_status(fresh_inv)

    fb_update(f"/invoices/{invoice_id}", {
        "tax_payments":         log,
        "meta/tax_paid":        str(tax_paid),
        "meta/status":          new_status,
        "meta/updated_at":      datetime.now(timezone.utc).isoformat(),
    })
    # Update project stage payment statuses based on payments
    _update_project_stage_payment_status(invoice_id)

    # Sync project payments for all linked projects
    for proj_num in _invoice_linked_projects(inv_data):
        _sync_project_payment(proj_num)

    return jsonify({"success": True}), 200

@app.route("/invoicing/send-reminders", methods=["POST"])
@role_required("invoicing")
def send_overdue_reminders():
    raw = fb_get("/invoices") or {}
    sent = 0
    errors = []
    for iid, idata in (raw.items() if isinstance(raw, dict) else []):
        if isinstance(idata, dict) and idata.get("meta", {}).get("status", "") == "Overdue":
            ok, msg = _send_overdue_reminder_email(iid, idata)
            if ok:
                sent += 1
            else:
                errors.append(msg)
    if sent:
        flash(f"Sent {sent} overdue reminder email{'s' if sent != 1 else ''}.", "success")
    if errors:
        flash(f"Some failed: {'; '.join(set(errors[:3]))}", "warning")
    if not sent and not errors:
        flash("No overdue invoices to send reminders for.", "info")
    return redirect(url_for("invoicing"))

def _send_overdue_reminder_email(invoice_id: str, invoice: dict):
    """Send overdue payment reminder to client. Returns (ok, message)."""
    settings = load_settings()
    em = settings.get("email", {})
    if not em.get("enabled"):
        return False, "Email sending disabled."
    meta = invoice.get("meta", {})
    client_name = meta.get("client_name", "")
    if not client_name:
        return False, f"No client on invoice {invoice_id}."
    raw_clients = fb_get("/clients") or {}
    client_email = ""
    if isinstance(raw_clients, dict):
        for cd in raw_clients.values():
            if isinstance(cd, dict) and cd.get("name", "") == client_name:
                client_email = cd.get("email", "")
                break
    if not client_email:
        return False, f"No email for {client_name}."
    co = settings.get("company", {})
    inv_num = meta.get("invoice_number", "")
    total   = _safe_float(meta.get("total", 0))
    paid    = _safe_float(meta.get("amount_paid", 0))
    balance = total - paid
    html_body = f"""<html><body style="font-family:Arial,sans-serif;color:#1a1a1a;">
<div style="max-width:600px;margin:0 auto;padding:24px;">
  <h2 style="color:#DC2626;">Payment Reminder — Invoice #{inv_num}</h2>
  <p>Dear {client_name},</p>
  <p>This is a reminder that invoice <strong>#{inv_num}</strong> is now
     <strong style="color:#DC2626;">overdue</strong>.</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0;">
    <tr><td style="padding:8px;border-bottom:1px solid #eee;">Invoice #</td>
        <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{inv_num}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;">Due Date</td>
        <td style="padding:8px;border-bottom:1px solid #eee;color:#DC2626;">{meta.get('due_date','—')}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;">Invoice Total</td>
        <td style="padding:8px;border-bottom:1px solid #eee;">${total:,.2f}</td></tr>
    <tr><td style="padding:8px;">Balance Due</td>
        <td style="padding:8px;font-weight:bold;font-size:18px;color:#DC2626;">${balance:,.2f}</td></tr>
  </table>
  <p>Please arrange payment at your earliest convenience. Contact us at
     <a href="mailto:{em.get('smtp_user','')}">{em.get('smtp_user','')}</a> with any questions.</p>
  <p style="margin-top:24px;">Best regards,<br><strong>{co.get('name','')}</strong></p>
</div></body></html>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Payment Reminder — Invoice #{inv_num} OVERDUE"
        msg["From"]    = f"{em.get('from_name', co.get('name',''))} <{em.get('smtp_user','')}>"
        msg["To"]      = client_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(em.get("smtp_host", "smtp.gmail.com"),
                          int(em.get("smtp_port", 587))) as srv:
            srv.ehlo(); srv.starttls()
            srv.login(em.get("smtp_user", ""), em.get("smtp_password", ""))
            srv.sendmail(em.get("smtp_user", ""), [client_email], msg.as_string())
        return True, f"Reminder sent to {client_email}."
    except Exception as exc:
        return False, str(exc)

# ── Payment Plan Management API ────────────────────────────────────────────────
@app.route("/api/projects/<project_id>/payment-plan", methods=["POST"])
@role_required("projects")
def update_project_payment_plan(project_id):
    """Update payment plan amounts and redistribute to stages"""
    try:
        data = request.get_json()
        amounts = data.get("amounts", [])
        invoice_id = data.get("invoiceId", "")
        original_amount = _safe_float(data.get("originalAmount", 0))
        new_amount = _safe_float(data.get("newAmount", 0))

        project = fb_get(f"/projects/{project_id}") or {}
        stages = project.get("payment_stages", [])
        contract_value = _safe_float(project.get("contract_value", 0))

        # Validate total equals contract value
        total = sum(_safe_float(a.get("amount", 0)) for a in amounts)
        if abs(total - contract_value) > 0.01:
            return {"success": False, "error": f"Total ({total:.2f}) must equal contract value ({contract_value:.2f})"}

        # Update all stages with new amounts
        for amount_data in amounts:
            idx = amount_data.get("index", 0)
            if idx < len(stages):
                stages[idx]["amount"] = _safe_float(amount_data.get("amount", 0))

        project["payment_stages"] = stages
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/projects/{project_id}", project)

        # Update invoice if this was an invoiced stage
        if invoice_id:
            invoice = fb_get(f"/invoices/{invoice_id}") or {}
            meta = invoice.get("meta", {})

            # Update invoice amount
            amount_diff = new_amount - original_amount
            old_invoice_total = _safe_float(meta.get("total", 0))
            new_invoice_total = old_invoice_total + amount_diff

            meta["total"] = str(new_invoice_total)
            meta["subtotal"] = str(new_invoice_total - _safe_float(meta.get("tax_amount", 0)))
            invoice["meta"] = meta

            # Update line items if they exist
            line_items = invoice.get("line_items", [])
            if line_items:
                line_items[0]["amount"] = str(new_amount)
                line_items[0]["unit_price"] = str(new_amount)
                invoice["line_items"] = line_items

            invoice["updated_at"] = datetime.now(timezone.utc).isoformat()
            fb_update(f"/invoices/{invoice_id}", invoice)

        return {"success": True, "message": "Payment plan updated"}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

@app.route("/api/projects/<project_id>/stage/<int:stage_idx>/update", methods=["POST"])
@role_required("projects")
def update_project_stage(project_id, stage_idx):
    """Update a single stage payment amount"""
    try:
        data = request.get_json()
        new_amount = _safe_float(data.get("newAmount", 0))
        original_amount = _safe_float(data.get("originalAmount", 0))
        paid_amount = _safe_float(data.get("paidAmount", 0))

        project = fb_get(f"/projects/{project_id}") or {}
        stages = project.get("payment_stages", [])

        if stage_idx >= len(stages):
            return {"success": False, "error": "Invalid stage index"}, 400

        # Update the stage amount
        old_amount = stages[stage_idx].get("amount", 0)
        stages[stage_idx]["amount"] = new_amount

        # If there's an invoice for this stage, update it
        invoice_id = stages[stage_idx].get("invoice_id", "")
        if invoice_id:
            invoice = fb_get(f"/invoices/{invoice_id}") or {}
            meta = invoice.get("meta", {})

            # Update the invoice total
            old_invoice_total = _safe_float(meta.get("total", 0))
            amount_diff = new_amount - original_amount
            new_invoice_total = old_invoice_total + amount_diff

            meta["total"] = str(new_invoice_total)
            meta["subtotal"] = str(new_invoice_total - _safe_float(meta.get("tax_amount", 0)))
            invoice["meta"] = meta
            fb_update(f"/invoices/{invoice_id}", invoice)

        # Redistribute remaining amounts to uninvoiced stages
        amount_diff = new_amount - original_amount
        remaining_uninvoiced = [i for i in range(len(stages))
                               if i > stage_idx and stages[i].get("status") == "Pending Invoice"]

        if remaining_uninvoiced and abs(amount_diff) > 0.01:
            per_stage = amount_diff / len(remaining_uninvoiced)
            for idx in remaining_uninvoiced:
                stages[idx]["amount"] = _safe_float(stages[idx].get("amount", 0)) + per_stage

        project["payment_stages"] = stages
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/projects/{project_id}", project)

        return {"success": True, "message": "Stage updated"}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

@app.route("/api/projects/<project_id>/stage/<int:stage_idx>/update-invoiced", methods=["POST"])
@role_required("projects")
def update_invoiced_stage(project_id, stage_idx):
    """Update an invoiced stage amount and redistribute remaining to non-invoiced stages"""
    try:
        data = request.get_json()
        invoice_id = data.get("invoiceId", "")
        new_amount = _safe_float(data.get("newAmount", 0))
        original_amount = _safe_float(data.get("originalAmount", 0))
        updated_stages = data.get("stages", [])

        project = fb_get(f"/projects/{project_id}") or {}
        stages = project.get("payment_stages", [])

        if stage_idx >= len(stages):
            return {"success": False, "error": "Invalid stage index"}, 400

        # Update all stages with redistributed amounts
        for stage_data in updated_stages:
            idx = stage_data.get("index", 0)
            if idx < len(stages):
                stages[idx]["amount"] = _safe_float(stage_data.get("amount", 0))

        project["payment_stages"] = stages
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/projects/{project_id}", project)

        # Update the invoice if it exists
        if invoice_id:
            invoice = fb_get(f"/invoices/{invoice_id}") or {}
            meta = invoice.get("meta", {})

            # Update invoice amount
            old_invoice_total = _safe_float(meta.get("total", 0))
            amount_diff = original_amount - new_amount
            new_invoice_total = old_invoice_total - amount_diff

            meta["total"] = str(new_invoice_total)
            meta["subtotal"] = str(new_invoice_total - _safe_float(meta.get("tax_amount", 0)))
            invoice["meta"] = meta

            # Update line items if they exist
            line_items = invoice.get("line_items", [])
            if line_items:
                line_items[0]["amount"] = str(new_amount)
                line_items[0]["unit_price"] = str(new_amount)
                invoice["line_items"] = line_items

            invoice["updated_at"] = datetime.now(timezone.utc).isoformat()
            fb_update(f"/invoices/{invoice_id}", invoice)

        return {"success": True, "message": "Invoiced amount updated and redistributed"}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

@app.route("/api/projects/<project_id>/stage/<int:stage_idx>/invoice", methods=["POST"])
@role_required("projects")
def quick_invoice_stage(project_id, stage_idx):
    """Quickly create an invoice for a specific payment stage"""
    try:
        data = request.get_json()
        stage_name = data.get("stageName", "")
        amount = _safe_float(data.get("amount", 0))

        project = fb_get(f"/projects/{project_id}") or {}
        stages = project.get("payment_stages", [])

        if stage_idx >= len(stages):
            return {"success": False, "error": "Invalid stage index"}, 400

        stage = stages[stage_idx]

        # Create invoice data
        invoice_number = _next_invoice_number()
        tax_rate = _safe_float(project.get("tax_rate", 0))
        tax_amount = (amount * tax_rate) / 100
        total = amount + tax_amount

        invoice_data = {
            "meta": {
                "invoice_number": invoice_number,
                "invoice_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "due_date": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d"),
                "client_name": project.get("client_name", ""),
                "project_number": project.get("project_number", ""),
                "payment_stage_index": stage_idx,
                "linked_projects": [project_id],
                "subtotal": str(amount),
                "tax_rate": str(tax_rate),
                "tax_amount": str(tax_amount),
                "total": str(total),
                "amount_paid": "0",
                "status": "Issued",
                "terms": project.get("invoice_terms", "Thank you for your business!"),
                "notes": f"Payment for: {stage_name}"
            },
            "line_items": [
                {
                    "project": project_id,
                    "description": stage_name,
                    "qty": 1,
                    "unit_price": str(amount),
                    "amount": str(amount)
                }
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        # Save invoice
        invoice_id = fb_push("/invoices", invoice_data)

        # Update project stage with invoice reference
        stage["status"] = "Invoiced"
        stage["invoice_id"] = invoice_id
        stage["invoice_number"] = invoice_number
        stages[stage_idx] = stage
        project["payment_stages"] = stages
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/projects/{project_id}", project)

        return {"success": True, "invoice_id": invoice_id, "invoice_number": invoice_number}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="0.0.0.0", port=5000)
