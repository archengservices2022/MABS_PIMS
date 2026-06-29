"""MABS PIMS - Flask Web Application"""
import os
import re
import json
import base64
import tempfile
import logging
import secrets
import hashlib
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
FIREBASE_API_KEY = "AIzaSyBZIG4Gj_ZRRCqI1DXcf8DSXpO_9PkTgeY"
FIREBASE_DB_URL  = "https://pims-955e3-default-rtdb.firebaseio.com"

FIREBASE_AVAILABLE = False
db = None

try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
    from firebase_admin.exceptions import FirebaseError

    # Cloud deployment: FIREBASE_SERVICE_ACCOUNT_JSON env var (full JSON string)
    _sa_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if _sa_json_str:
        if not firebase_admin._apps:
            _sa_dict = json.loads(_sa_json_str)
            cred = credentials.Certificate(_sa_dict)
            firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})
        db = firebase_db
        FIREBASE_AVAILABLE = True
        log.info("Firebase initialised from environment variable")
    else:
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
    "admin":    ["dashboard", "quotes", "projects", "invoicing", "payroll", "financial", "settings", "employees", "sales_dashboard", "timesheets"],
    "sales":    ["sales_dashboard", "quotes", "employees", "timesheets"],
    "projects": ["projects", "invoicing", "employees", "timesheets"],
    "finance":  ["financial", "employees", "timesheets"],
    "engineer": ["employees", "timesheets"],
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


def _ai_call_with_image(prompt: str, image_b64: str, media_type: str, max_tokens: int = 1024) -> str:
    """Run a single Claude vision call with an image; returns the text or raises RuntimeError."""
    client = _get_ai_client()
    if not client:
        raise RuntimeError("No Anthropic API key configured. Add it in Settings → AI.")
    msgs = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": prompt},
        ],
    }]
    resp = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=max_tokens, messages=msgs)
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
    uid  = session.get("user_uid", "")

    # Global "My Time Clock" widget (topbar) — every role has "employees" access,
    # so this is computed for every logged-in page view, not just /dashboard.
    clock_widget = {}
    if uid:
        my_entries = [e for e in _load_time_entries() if e.get("employee_uid") == uid]
        clock_widget = {
            "my_open_entry":         next((e for e in my_entries if e.get("status") == "open"), None),
            "last_project_number":   my_entries[0].get("project_number", "") if my_entries else "",
            "clock_active_projects": [p for p in _load_projects_list()
                                       if isinstance(p, dict) and p.get("status", "") not in ("Completed", "Cancelled")],
            "today_str":             datetime.now().strftime("%Y-%m-%d"),
        }

    return {
        "user_name":   session.get("user_name", ""),
        "user_email":  session.get("user_email", ""),
        "user_role":   role,
        "user_uid":    uid,
        "allowed_pages": ROLE_PAGES.get(normalize_role(role), []),
        "company":     company_info(),
        "now":         datetime.now(),
        "timedelta":   timedelta,
        **clock_widget,
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

def firebase_send_password_reset(email: str):
    """Send password reset email using Firebase. Returns (success, error_msg)"""
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={FIREBASE_API_KEY}"
        resp = requests.post(url, json={"email": email, "requestType": "PASSWORD_RESET"}, timeout=10)

        if resp.status_code == 200:
            return True, ""

        err = resp.json().get("error", {}).get("message", "Failed to send reset email")
        return False, err
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except Exception as exc:
        return False, str(exc)

@app.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    """AJAX endpoint for forgot password"""
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()

        if not email:
            return jsonify({"success": False, "error": "Please enter your email address."})

        if not FIREBASE_AVAILABLE:
            return jsonify({"success": False, "error": "Service unavailable. Please contact your administrator."})

        user_found = False
        user_data = None
        users = fb_get("/users") or {}

        for uid, u_data in users.items():
            if isinstance(u_data, dict) and u_data.get("email", "").lower() == email:
                user_found = True
                user_data = u_data
                break

        if not user_found:
            return jsonify({"success": False, "error": "Account does not exist. Please contact your administrator."})

        if not user_data.get("active", True):
            return jsonify({"success": False, "error": "Account does not exist. Please contact your administrator."})

        ok, err_msg = firebase_send_password_reset(email)

        if ok:
            log.info("Password reset email sent via Firebase for %s", email)
            return jsonify({"success": True, "message": f"Reset link sent to {email}. Please check your email to continue."})
        else:
            log.error("Firebase password reset failed for %s: %s", email, err_msg)
            return jsonify({"success": False, "error": "Failed to send reset email. Please try again later."})

    except Exception as e:
        log.error("API forgot password error: %s", str(e))
        return jsonify({"success": False, "error": "An error occurred. Please try again later."})

def firebase_reset_password_with_code(email: str, password: str, oob_code: str):
    """Reset password using Firebase OOB code. Returns (ok, error_msg)"""
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:resetPassword?key={FIREBASE_API_KEY}"
        resp = requests.post(url, json={
            "oobCode": oob_code,
            "newPassword": password
        }, timeout=10)

        if resp.status_code == 200:
            return True, ""

        err = resp.json().get("error", {}).get("message", "Failed to reset password")
        return False, err
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except Exception as exc:
        return False, str(exc)

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = request.args.get("email", "").strip().lower()
    oob_code = request.args.get("oobCode", "").strip()
    error = None
    message = None
    valid_token = False

    if not email or not oob_code:
        error = "Invalid reset link. Please request a new one."
    else:
        if not FIREBASE_AVAILABLE:
            error = "Password reset service unavailable. Please contact your administrator."
        else:
            try:
                valid_token = True

                if request.method == "POST":
                    password = request.form.get("password", "")
                    confirm = request.form.get("confirm_password", "")

                    if not password or not confirm:
                        error = "Please enter both password fields."
                    elif len(password) < 8:
                        error = "Password must be at least 8 characters long."
                    elif password != confirm:
                        error = "Passwords do not match."
                    else:
                        try:
                            ok, err_msg = firebase_reset_password_with_code(email, password, oob_code)
                            if not ok:
                                error = "Failed to reset password. " + err_msg
                                log.error("Password reset failed for %s: %s", email, err_msg)
                            else:
                                ok, uid, err_msg = firebase_sign_in(email, password)
                                if ok:
                                    profile = load_user_profile(uid)
                                    if profile and profile.get("active", True):
                                        role = normalize_role(profile.get("role", "sales"))
                                        session.permanent = True
                                        session["user_email"] = email
                                        session["user_uid"] = uid
                                        session["user_name"] = profile.get("username", email.split("@")[0])
                                        session["user_role"] = role
                                        log.info("Password reset and auto-login for %s", email)
                                        return redirect(url_for(first_page(role)))

                                message = "Password reset successfully. You can now sign in with your new password."
                                valid_token = False
                                log.info("Password reset successful for %s", email)
                        except Exception as e:
                            error = "An error occurred. Please try again later."
                            log.error("Password reset error: %s", str(e))
            except Exception as e:
                error = "An error occurred. Please try again later."
                log.error("Reset password error: %s", str(e))

    return render_template("reset_password.html", email=email, error=error, message=message, valid_token=valid_token)

# ── Routes: Dashboard ─────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return redirect(url_for(first_page(session.get("user_role", "sales"))))

@app.route("/portfolio")
def portfolio():
    github_username = "archengservices2022"
    featured_repo = "MABS_PIMS"
    return render_template(
        "portfolio.html",
        github_username=github_username,
        github_profile_url=f"https://github.com/{github_username}",
        github_repo_url=f"https://github.com/{github_username}/{featured_repo}",
        featured_repo=featured_repo,
    )

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

    # Dashboard totals include tax in both invoiced and paid amounts
    total_invoiced = sum(
        _safe_float(i.get("meta", {}).get("total", 0))
        for i in inv_list if isinstance(i, dict)
    )
    total_paid = sum(
        _safe_float(i.get("meta", {}).get("amount_paid", 0))
        for i in inv_list if isinstance(i, dict)
    )
    total_paid += sum(
        _safe_float(p.get("amount", 0)) for i in inv_list for p in i.get("tax_payments", [])
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
    today_str     = datetime.now().strftime("%Y-%m-%d")
    week_str      = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    three_day_str = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    overdue_count = sum(1 for i in inv_list
                        if isinstance(i, dict) and i.get("meta", {}).get("status", "") == "Overdue")
    _QTERMINAL = {"Approved", "Converted", "Invoiced", "Rejected", "Cancelled", "Expired"}
    expiring_count = sum(1 for q in quot_list
                         if isinstance(q, dict)
                         and q.get("status", "Not Started") not in _QTERMINAL
                         and q.get("valid_until", "")
                         and today_str <= q.get("valid_until", "") <= week_str)
    expiring_soon_quotes = sorted(
        [q for q in quot_list
         if isinstance(q, dict)
         and q.get("status", "Not Started") not in _QTERMINAL
         and q.get("valid_until", "")
         and today_str <= q.get("valid_until", "") <= three_day_str],
        key=lambda x: x.get("valid_until", "")
    )

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

    # ── Urgent alerts (overdue + due within 3 days only) ─────────────────────
    three_day_str = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

    # 1. Overdue invoices
    reminder_overdue_invoices = sorted(
        [i for i in inv_list if isinstance(i, dict)
         and i.get("meta", {}).get("status", "") == "Overdue"],
        key=lambda x: x.get("meta", {}).get("due_date", "")
    )[:5]

    # 2. Invoices due within 3 days (not yet overdue)
    reminder_due_soon = sorted(
        [i for i in inv_list if isinstance(i, dict)
         and i.get("meta", {}).get("status", "") not in ("Paid", "Overdue", "Cancelled")
         and i.get("meta", {}).get("due_date", "")
         and today_str <= i.get("meta", {}).get("due_date", "") <= three_day_str],
        key=lambda x: x.get("meta", {}).get("due_date", "")
    )[:5]

    reminder_proj_due = []
    reminder_stalled  = []
    reminder_total = len(reminder_overdue_invoices) + len(reminder_due_soon)

    # ── Projects ready to invoice (have Pending Invoice stages) ──────────────
    projects_ready_to_invoice = []
    for p in proj_list:
        if not isinstance(p, dict):
            continue
        if p.get("status", "") in ("Completed", "Cancelled"):
            continue
        stages = p.get("payment_stages", []) or []
        pending_stages = [s for s in stages if isinstance(s, dict) and s.get("status", "") == "Pending Invoice"]
        if pending_stages:
            pending_amt = sum(_safe_float(s.get("amount", 0)) for s in pending_stages)
            projects_ready_to_invoice.append({
                "firebase_id":    p.get("firebase_id", ""),
                "project_number": p.get("project_number", ""),
                "project_name":   p.get("project_name", ""),
                "client_name":    p.get("client_name", ""),
                "pending_stages": len(pending_stages),
                "pending_amount": pending_amt,
            })
    projects_ready_to_invoice = sorted(projects_ready_to_invoice, key=lambda x: x["project_number"], reverse=True)[:8]

    # ── This month vs last month collected ────────────────────────────────────
    this_month_str = datetime.now().strftime("%Y-%m")
    last_month_str = (datetime.now() - timedelta(days=30)).strftime("%Y-%m")
    this_month_collected = 0.0
    last_month_collected = 0.0
    for inv in inv_list:
        if not isinstance(inv, dict):
            continue
        for pay in (inv.get("payment_log", []) or []):
            ds = pay.get("date", "") or ""
            if ds[:7] == this_month_str:
                this_month_collected += _safe_float(pay.get("amount", 0))
            elif ds[:7] == last_month_str:
                last_month_collected += _safe_float(pay.get("amount", 0))
        for tp in (inv.get("tax_payments", []) or []):
            ds = tp.get("date", "") or ""
            if ds[:7] == this_month_str:
                this_month_collected += _safe_float(tp.get("amount", 0))
            elif ds[:7] == last_month_str:
                last_month_collected += _safe_float(tp.get("amount", 0))

    # ── Module overview stats ─────────────────────────────────────────────────
    _QTERMINAL_ALL = {"Approved", "Converted", "Invoiced", "Rejected", "Cancelled", "Expired"}
    quot_status_counts: Dict[str, int] = {}
    quotes_pipeline_value = 0.0
    quotes_converted = 0
    for _q in quot_list:
        if not isinstance(_q, dict): continue
        _st = _q.get("status", "Not Started")
        quot_status_counts[_st] = quot_status_counts.get(_st, 0) + 1
        if _st not in {"Rejected", "Cancelled", "Expired"}:
            quotes_pipeline_value += _safe_float(_q.get("total", 0))
        if _st in {"Converted", "Invoiced"}:
            quotes_converted += 1
    _total_quotes = len(quot_list)
    quotes_conversion_rate = int(quotes_converted / _total_quotes * 100) if _total_quotes > 0 else 0

    proj_contract_total  = sum(_safe_float(p.get("contract_value", 0)) for p in proj_list if isinstance(p, dict))
    proj_contract_active = sum(
        _safe_float(p.get("contract_value", 0)) for p in proj_list
        if isinstance(p, dict) and p.get("status", "") not in ("Completed", "Cancelled")
    )
    proj_completed_count = sum(1 for p in proj_list if isinstance(p, dict) and p.get("status", "") == "Completed")

    inv_overdue_amt = sum(
        _safe_float(i.get("meta", {}).get("total", 0)) - _safe_float(i.get("meta", {}).get("amount_paid", 0))
        for i in inv_list if isinstance(i, dict) and i.get("meta", {}).get("status", "") == "Overdue"
    )

    # ── Team status (Employees module) ─────────────────────────────────────
    all_time_entries = _load_time_entries()
    all_time_off     = _load_time_off_requests()
    clocked_in_now   = [e for e in all_time_entries if e.get("status") == "open"]
    pending_time_off = [r for r in all_time_off if r.get("status") == "Pending"]

    return render_template("dashboard.html",
        clocked_in_now=clocked_in_now,
        pending_time_off=pending_time_off,
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
        expiring_soon_quotes=expiring_soon_quotes,
        followup_quotes=followup_quotes,
        approved_quotes=approved_quotes,
        pipeline=pipeline,
        inv_status_labels=json.dumps(list(inv_status_counts.keys())),
        inv_status_data=json.dumps(list(inv_status_counts.values())),
        proj_status_labels=json.dumps(list(proj_status_counts.keys())),
        proj_status_data=json.dumps(list(proj_status_counts.values())),
        ai_enabled=bool(_get_ai_client()),
        reminder_overdue_invoices=reminder_overdue_invoices,
        reminder_due_soon=reminder_due_soon,
        reminder_proj_due=reminder_proj_due,
        reminder_stalled=reminder_stalled,
        reminder_total=reminder_total,
        projects_ready_to_invoice=projects_ready_to_invoice,
        this_month_collected=this_month_collected,
        last_month_collected=last_month_collected,
        inv_status_counts=inv_status_counts,
        quot_status_counts=quot_status_counts,
        quotes_approved_count=sum(quot_status_counts.get(s, 0) for s in ('Approved', 'Converted', 'Invoiced', 'Completed')),
        quotes_pipeline_value=quotes_pipeline_value,
        quotes_conversion_rate=quotes_conversion_rate,
        proj_contract_total=proj_contract_total,
        proj_contract_active=proj_contract_active,
        proj_completed_count=proj_completed_count,
        inv_overdue_amt=inv_overdue_amt,
    )

# ── Routes: Sales Dashboard ───────────────────────────────────────────────────
@app.route("/sales-dashboard")
@role_required("sales_dashboard")
def sales_dashboard():
    user_name  = session.get("user_name", "")
    raw        = fb_get("/job_forms") or {}
    today_str  = datetime.now().strftime("%Y-%m-%d")
    week_str   = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    _TERMINAL  = {"Approved", "Converted", "Invoiced", "Rejected", "Cancelled", "Expired"}

    all_quotes: list = []
    for fid, fdata in (raw.items() if isinstance(raw, dict) else []):
        if fdata and isinstance(fdata, dict):
            fdata["firebase_id"] = fid
            fdata.setdefault("status", "Not Started")
            all_quotes.append(fdata)

    # Filter to current salesperson's quotes when possible
    my_quotes = ([q for q in all_quotes if q.get("salesperson", "") == user_name]
                 if user_name else all_quotes) or all_quotes

    open_quotes     = [q for q in my_quotes if q.get("status") not in _TERMINAL]
    converted       = [q for q in my_quotes if q.get("status") in ("Converted", "Invoiced", "Approved")]
    pipeline_value  = sum(_safe_float(q.get("total", 0)) for q in open_quotes)
    total_value     = sum(_safe_float(q.get("total", 0)) for q in my_quotes)
    win_rate        = round(len(converted) / len(my_quotes) * 100) if my_quotes else 0

    next14_str = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    followups_due = sorted(
        [q for q in my_quotes
         if q.get("status") not in _TERMINAL
         and q.get("follow_up_date", "")
         and q.get("follow_up_date", "") <= next14_str],
        key=lambda x: x.get("follow_up_date", "")
    )

    expiring_soon = sorted(
        [q for q in my_quotes
         if q.get("status") not in _TERMINAL
         and q.get("valid_until", "")
         and today_str <= q.get("valid_until", "") <= week_str],
        key=lambda x: x.get("valid_until", "")
    )

    recent_quotes = sorted(
        my_quotes,
        key=lambda x: x.get("created_at", x.get("date", "")),
        reverse=True
    )[:8]

    return render_template("sales_dashboard.html",
        my_quotes=my_quotes,
        open_quotes=open_quotes,
        converted=converted,
        pipeline_value=pipeline_value,
        total_value=total_value,
        win_rate=win_rate,
        followups_due=followups_due,
        expiring_soon=expiring_soon,
        recent_quotes=recent_quotes,
        today_str=today_str,
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

    # KPI stats computed from all quotes (unfiltered)
    _OPEN_STATUSES      = {"Not Started", "In Progress"}
    _APPROVED_STATUSES  = {"Approved", "Completed"}
    _CONVERTED_STATUSES = {"Converted", "Invoiced"}
    q_total     = len(all_items_raw)
    q_open      = sum(1 for q in all_items_raw if q.get("status", "Not Started") in _OPEN_STATUSES)
    q_approved  = sum(1 for q in all_items_raw if q.get("status", "") in _APPROVED_STATUSES)
    q_converted = sum(1 for q in all_items_raw if q.get("status", "") in _CONVERTED_STATUSES)
    q_conv_rate = round(q_converted / q_total * 100) if q_total else 0
    q_pipeline  = sum(_safe_float(q.get("total", 0)) for q in all_items_raw if q.get("status", "Not Started") in _OPEN_STATUSES | _APPROVED_STATUSES)
    q_won_val   = sum(_safe_float(q.get("total", 0)) for q in all_items_raw if q.get("status", "") in _CONVERTED_STATUSES)

    return render_template("quotes.html", quotes=items, statuses=statuses,
                           search=search, status_filter=status_filter,
                           year_filter=year_filter, month_filter=month_filter,
                           date_from=date_from, date_to=date_to,
                           available_years=available_years,
                           follow_ups=follow_ups,
                           upcoming_followups=upcoming_followups,
                           clients=_load_clients(), sales_people=_load_sales_people(),
                           active_tab=active_tab, today_date=today_date,
                           next_num=_next_quote_number(),
                           q_total=q_total, q_open=q_open, q_approved=q_approved,
                           q_converted=q_converted, q_conv_rate=q_conv_rate,
                           q_pipeline=q_pipeline, q_won_val=q_won_val)

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

    # Linked project — via linked_project_id, or fall back to searching by source_quote
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
    raw_inv = fb_get("/invoices") or {}
    items = []
    _now_iso = datetime.now(timezone.utc).isoformat()
    for pid, pdata in (raw.items() if isinstance(raw, dict) else []):
        if pdata and isinstance(pdata, dict):
            pdata["firebase_id"] = pid
            pdata["_has_overdue"] = _project_has_overdue_stage(pdata.get("payment_stages"), raw_inv)
            # Repair status if amount_paid contradicts stored status
            _amt   = _safe_float(pdata.get("amount_paid", 0))
            _cv    = _safe_float(pdata.get("contract_value", 0))
            _st    = pdata.get("status") or "Not Started"
            if _st != "Cancelled":
                if _cv > 0 and _amt >= _cv - 0.01 and _st != "Completed":
                    pdata["status"] = "Completed"
                    fb_update(f"/projects/{pid}", {"status": "Completed", "updated_at": _now_iso})
                elif _amt > 0 and _st == "Not Started":
                    pdata["status"] = "In Progress"
                    fb_update(f"/projects/{pid}", {"status": "In Progress", "updated_at": _now_iso})
            items.append(pdata)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    search        = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "")
    overdue_filter = request.args.get("overdue", "")
    date_from     = request.args.get("from", "")
    date_to       = request.args.get("to", "")
    client_filter = request.args.get("client", "")
    if search:
        items = [i for i in items if search in str(i).lower()]
    if status_filter:
        items = [i for i in items if i.get("status", "") == status_filter]
    if overdue_filter:
        items = [i for i in items if i.get("_has_overdue")]
    if client_filter:
        items = [i for i in items if i.get("client_name", "") == client_filter]
    if date_from:
        items = [i for i in items if (i.get("start_date") or i.get("created_at","")[:10]) >= date_from]
    if date_to:
        items = [i for i in items if (i.get("start_date") or i.get("created_at","")[:10]) <= date_to]

    status_counts = {}
    for i in items:
        st = i.get("status") or "Not Started"
        status_counts[st] = status_counts.get(st, 0) + 1
    overdue_count = sum(1 for i in items if i.get("_has_overdue"))

    statuses = ["Not Started", "Active", "In Progress", "On Hold", "Completed", "Cancelled"]
    clients = _load_clients()
    next_project_num = _next_project_number()
    active_tab = request.args.get("tab", "all-projects")

    # KPI stats from filtered projects
    _ACTIVE_STATUSES = {"Active", "In Progress"}
    p_total_count = len(items)
    p_total_cv    = sum(_safe_float(p.get("contract_value", 0)) for p in items)
    p_active_cv   = sum(_safe_float(p.get("contract_value", 0)) for p in items if p.get("status", "") in _ACTIVE_STATUSES)

    # Calculate collected amount from filtered projects' invoices
    p_total_paid = 0.0
    for p in items:
        proj_num = p.get("project_number", "")
        if proj_num:
            for iid, idata in (raw_inv.items() if isinstance(raw_inv, dict) else []):
                if isinstance(idata, dict) and proj_num in _invoice_linked_projects(idata):
                    inv_meta = idata.get("meta", {}) or {}
                    p_total_paid += _safe_float(inv_meta.get("amount_paid", 0))
                    # Also include tax payments
                    tax_payments = idata.get("tax_payments", [])
                    if isinstance(tax_payments, list):
                        p_total_paid += sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments)

    p_outstanding = p_total_cv - p_total_paid

    return render_template("projects.html", projects=items, statuses=statuses,
                           search=search, status_filter=status_filter,
                           overdue_filter=overdue_filter, overdue_count=overdue_count,
                           date_from=date_from, date_to=date_to,
                           client_filter=client_filter,
                           clients=clients, next_project_num=next_project_num,
                           active_tab=active_tab, status_counts=status_counts,
                           p_total_count=p_total_count, p_total_cv=p_total_cv,
                           p_active_cv=p_active_cv, p_total_paid=p_total_paid,
                           p_outstanding=p_outstanding)

@app.route("/projects/new", methods=["GET", "POST"])
@role_required("projects")
def project_new():
    clients = _load_clients()
    if request.method == "POST":
        data = _parse_project_form(request.form)

        # If arriving from "Convert to Project", resolve the source quote and
        # guard against converting the same quote into a second project.
        source_quote_id = request.form.get("source_quote_id", "").strip()
        source_quote = fb_get(f"/job_forms/{source_quote_id}") if source_quote_id else None
        if source_quote and source_quote.get("linked_project_id"):
            flash(f"This quote was already converted to Project "
                  f"{source_quote.get('linked_project_num','')}.", "info")
            return redirect(url_for("project_detail", project_id=source_quote["linked_project_id"]))

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

        if source_quote:
            data["source_quote"]     = source_quote_id
            data["source_quote_num"] = source_quote.get("job_number", "")

        pid = fb_push("/projects", data)

        if source_quote:
            fb_update(f"/job_forms/{source_quote_id}", {
                "status":             "Converted",
                "linked_project_id":  pid,
                "linked_project_num": data["project_number"],
                "updated_at":         datetime.now(timezone.utc).isoformat(),
            })
            flash(f"Project {data['project_number']} created and linked to quote "
                  f"{source_quote.get('job_number','')}.", "success")
            return redirect(url_for("project_detail", project_id=pid))

        flash(f"Project {data['project_number']} created successfully.", "success")
        return redirect(url_for("projects", tab="all-projects"))
    sales_people = [p.get("name","") for p in _load_sales_people() if p.get("name","")]
    prefill_quote = request.args.get("from_quote", "")
    prefill_quote_id, prefill_quote_data = _find_quote_by_number(prefill_quote)
    if prefill_quote_data and prefill_quote_data.get("linked_project_id"):
        flash(f"Quote {prefill_quote} was already converted to Project "
              f"{prefill_quote_data.get('linked_project_num','')}.", "info")
        return redirect(url_for("project_detail", project_id=prefill_quote_data["linked_project_id"]))
    next_proj_num = _next_project_number()
    return render_template("project_form.html", project=None, clients=clients,
                           sales_people=sales_people, prefill_quote=prefill_quote,
                           prefill_quote_id=prefill_quote_id or "",
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

        # Recalculate payment stage statuses based on actual paid amounts from invoices
        # First, build a map of invoices by stage (supporting multi-project invoices)
        raw_inv = fb_get("/invoices") or {}
        stage_invoices = {}
        if isinstance(raw_inv, dict):
            for iid, inv in raw_inv.items():
                if not isinstance(inv, dict):
                    continue
                inv_meta = inv.get("meta", {}) or {}

                # Check if this project is linked to the invoice (supports multi-project)
                linked_projects = _invoice_linked_projects(inv)
                if proj_num not in linked_projects:
                    continue

                # For multi-project invoices, find the stage index from linked_projects
                stage_idx = -1
                lp_list = inv_meta.get("linked_projects") or []
                if isinstance(lp_list, list):
                    for lp in lp_list:
                        if isinstance(lp, dict) and lp.get("project_number") == proj_num:
                            stage_idx = lp.get("payment_stage_index", -1)
                            break

                # Fallback to old single-project format
                if stage_idx < 0:
                    stage_idx = inv_meta.get("payment_stage_index", -1)

                if stage_idx >= 0:
                    if stage_idx not in stage_invoices:
                        stage_invoices[stage_idx] = []
                    stage_invoices[stage_idx].append(inv)

        today_str = datetime.now().strftime("%Y-%m-%d")
        for idx, stage in enumerate(data["payment_stages"]):
            stage_amount = _safe_float(stage.get("amount", 0))

            # Calculate amount paid from all invoices for this stage
            amount_paid = 0
            due_date = ""
            invoice_id = ""
            invoice_number = ""
            if idx in stage_invoices:
                for inv in stage_invoices[idx]:
                    # Sum invoice payments using payment_log filtered by project_number (not share-based)
                    inv_meta = inv.get("meta", {}) or {}
                    proj_payments = sum(_safe_float(p.get("amount", 0)) for p in (inv.get("payment_log", []) or []) if p.get("project_number") == proj_num)
                    amount_paid += proj_payments
                    # Also add any tax payments for this project
                    tax_payments = inv.get("tax_payments", []) or []
                    project_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments if tp.get("project_number") == proj_num)
                    amount_paid += project_tax_paid
                    due_date = due_date or inv_meta.get("due_date", "")
                    # Capture invoice details (use first invoice for this stage)
                    if not invoice_id:
                        invoice_id = inv.get("firebase_id", "")
                        invoice_number = inv_meta.get("invoice_number", "")

            is_overdue = bool(due_date) and due_date < today_str

            # Store calculated amounts and invoice info on stage for template display
            stage["amount_paid"] = amount_paid
            stage["invoice_id"] = invoice_id
            stage["invoice_number"] = invoice_number

            # Calculate status based on actual paid vs total
            if amount_paid >= (stage_amount - 0.01):
                stage["_display_status"] = "Paid"
            elif amount_paid > 0:
                stage["_display_status"] = "Overdue" if is_overdue else "Partially Paid"
            else:
                # No payment yet - keep the stage's real status (e.g. "Pending
                # Invoice" if no invoice has been generated yet, or "Invoiced"
                # if it has but remains unpaid) - unless that invoice is now
                # past its due date, in which case flag it as Overdue.
                stage_status = stage.get("status") or "Pending Invoice"
                if stage_status == "Invoiced" and is_overdue:
                    stage["_display_status"] = "Overdue"
                else:
                    stage["_display_status"] = stage_status

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

    # Recalculate fresh statuses for display (based on actual payments)
    for invoice in project_invoices:
        # Calculate project-specific paid amount from payment_log (filtered by project_number)
        proj_payments = sum(_safe_float(p.get("amount", 0)) for p in (invoice.get("payment_log", []) or []) if p.get("project_number") == proj_num)

        # Calculate tax paid - allocate proportionally if not per-project
        tax_payments = invoice.get("tax_payments", []) or []
        total_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments)

        # If tax_payments have project_number, filter by it; otherwise use share
        project_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments if tp.get("project_number") == proj_num)
        if project_tax_paid == 0 and total_tax_paid > 0:
            # Tax payments don't have project_number, allocate by share
            project_share = invoice.get("_project_share", 1.0)
            project_tax_paid = project_share * total_tax_paid

        invoice["_project_paid"] = proj_payments + project_tax_paid

        # Calculate status based on this project's paid vs this project's total
        meta = invoice.get("meta", {}) or {}
        project_share = invoice.get("_project_share", 1.0)
        invoice_subtotal = _safe_float(meta.get("subtotal", 0)) or (_safe_float(meta.get("total", 0)) - _safe_float(meta.get("tax_amount", 0)))
        invoice_tax = _safe_float(meta.get("tax_amount", 0))

        # This project's portion of the invoice
        project_invoice_due = (invoice_subtotal + invoice_tax) * project_share
        project_paid = invoice["_project_paid"]

        # Status based on this project's amounts
        if project_paid >= (project_invoice_due - 0.01):
            invoice["_display_status"] = "Paid"
        elif project_paid > 0:
            invoice["_display_status"] = "Partial"
        else:
            # Check if overdue
            due_date = meta.get("due_date", "")
            today = datetime.now().strftime("%Y-%m-%d")
            if due_date and due_date < today:
                invoice["_display_status"] = "Overdue"
            else:
                invoice["_display_status"] = "Sent"

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
    # Include both invoice amount and tax in total invoiced (to match collected which includes tax payments)
    inv_total   = sum((_safe_float(i.get("meta",{}).get("total", 0)) or _safe_float(i.get("meta",{}).get("subtotal", 0)) + _safe_float(i.get("meta",{}).get("tax_amount", 0))) * i.get("_project_share", 1.0) for i in project_invoices)

    # For paid amount, use actual payment_log entries filtered by project_number (not share-based)
    inv_paid = 0
    for invoice in project_invoices:
        # Get actual payments from payment_log for this project
        proj_payments = sum(_safe_float(p.get("amount", 0)) for p in (invoice.get("payment_log", []) or []) if p.get("project_number") == proj_num)

        # Get tax payments - allocate proportionally to project's share if not per-project
        tax_payments = invoice.get("tax_payments", []) or []
        total_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments)

        # If tax_payments have project_number, filter by it; otherwise use share
        project_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments if tp.get("project_number") == proj_num)
        if project_tax_paid == 0 and total_tax_paid > 0:
            # Tax payments don't have project_number, allocate by share
            project_share = invoice.get("_project_share", 1.0)
            project_tax_paid = project_share * total_tax_paid

        inv_paid += proj_payments + project_tax_paid
    exp_total   = sum(_safe_float(e.get("amount", 0))                     for e in project_expenses)
    gross_profit = inv_paid - exp_total

    # Labor hours & cost logged against this project (Employees module)
    rate_by_uid = {u.get("firebase_uid"): _safe_float(u.get("hourly_rate", 0)) for u in _load_all_users()}
    labor_by_employee: Dict[str, dict] = {}
    labor_total_minutes = 0.0
    labor_total_cost = 0.0
    for e in _load_time_entries():
        if not proj_num or e.get("status") != "closed" or e.get("project_number") != proj_num:
            continue
        minutes = _safe_float(e.get("duration_minutes", 0))
        rate = rate_by_uid.get(e.get("employee_uid"), 0.0)
        bucket = labor_by_employee.setdefault(e.get("employee_name", "Unknown"), {"minutes": 0.0, "rate": rate, "cost": 0.0})
        bucket["minutes"] += minutes
        bucket["cost"]    += (minutes / 60.0) * rate
        labor_total_minutes += minutes
        labor_total_cost    += (minutes / 60.0) * rate
    net_profit = gross_profit - labor_total_cost

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

    # Change orders
    change_orders = data.get("change_orders") or []
    if not isinstance(change_orders, list):
        change_orders = list(change_orders.values()) if isinstance(change_orders, dict) else []
    co_approved_total = sum(_safe_float(co.get("amount", 0)) for co in change_orders if co.get("status") == "Approved")
    base_contract = _safe_float(data.get("base_contract_value") or data.get("contract_value", 0))

    return render_template("project_detail.html", project=data,
                           project_invoices=project_invoices,
                           project_expenses=project_expenses,
                           inv_total=inv_total, inv_paid=inv_paid,
                           exp_total=exp_total, gross_profit=gross_profit,
                           labor_by_employee=labor_by_employee,
                           labor_total_minutes=labor_total_minutes,
                           labor_total_cost=labor_total_cost,
                           net_profit=net_profit,
                           source_quote=source_quote,
                           has_pending_stage=has_pending_stage,
                           next_stage_idx=next_stage_idx,
                           next_stage_name=next_stage_name,
                           next_stage_amount=next_stage_amount,
                           change_orders=change_orders,
                           co_approved_total=co_approved_total,
                           base_contract=base_contract)

# ── Change Order Routes ───────────────────────────────────────────────────────

@app.route("/projects/<project_id>/change-orders/new", methods=["POST"])
@role_required("projects")
def co_new(project_id):
    project = fb_get(f"/projects/{project_id}") or {}
    if not project:
        abort(404)
    cos = project.get("change_orders") or []
    if not isinstance(cos, list):
        cos = list(cos.values()) if isinstance(cos, dict) else []
    co_num = f"CO-{len(cos)+1:03d}"
    now_str = datetime.now(timezone.utc).isoformat()
    new_co = {
        "co_number":    co_num,
        "title":        request.form.get("title", "").strip(),
        "description":  request.form.get("description", "").strip(),
        "amount":       _safe_float(request.form.get("amount", 0)),
        "status":       "Draft",
        "created_at":   now_str,
        "created_by":   session.get("user_email", ""),
        "submitted_at": "",
        "approved_at":  "",
        "notes":        request.form.get("notes", "").strip(),
    }
    cos.append(new_co)
    # Save base contract value on first CO creation
    if not project.get("base_contract_value"):
        fb_update(f"/projects/{project_id}", {"base_contract_value": project.get("contract_value", 0)})
    fb_update(f"/projects/{project_id}", {"change_orders": cos})
    flash(f"Change Order {co_num} created.", "success")
    return redirect(url_for("project_detail", project_id=project_id) + "#tab-change-orders")

@app.route("/projects/<project_id>/change-orders/<int:co_idx>/status", methods=["POST"])
@role_required("projects")
def co_status(project_id, co_idx):
    project = fb_get(f"/projects/{project_id}") or {}
    if not project:
        abort(404)
    cos = project.get("change_orders") or []
    if not isinstance(cos, list):
        cos = list(cos.values()) if isinstance(cos, dict) else []
    if co_idx >= len(cos):
        abort(404)
    new_status = request.form.get("status", "")
    valid = {"Draft", "Submitted", "Approved", "Rejected"}
    if new_status not in valid:
        abort(400)
    now_str = datetime.now(timezone.utc).isoformat()
    cos[co_idx]["status"] = new_status
    if new_status == "Submitted":
        cos[co_idx]["submitted_at"] = now_str
    if new_status == "Approved":
        cos[co_idx]["approved_at"] = now_str
        # Increase contract value and add payment stage
        co_amount = _safe_float(cos[co_idx].get("amount", 0))
        co_title  = cos[co_idx].get("title", cos[co_idx].get("co_number", ""))
        old_value = _safe_float(project.get("contract_value", 0))
        new_value = old_value + co_amount
        stages = project.get("payment_stages") or []
        if not isinstance(stages, list):
            stages = []
        stages.append({
            "name":   f"{cos[co_idx]['co_number']} – {co_title}",
            "amount": co_amount,
            "status": "Pending Invoice",
        })
        update_data = {
            "change_orders":  cos,
            "contract_value": new_value,
            "payment_stages": stages,
        }
        # Auto-update project status to "In Progress" if project is Completed and new CO payment is unpaid
        if project.get("status") == "Completed" and co_amount > 0:
            update_data["status"] = "In Progress"
            update_data["updated_at"] = now_str
        fb_update(f"/projects/{project_id}", update_data)
        flash(f"{cos[co_idx]['co_number']} approved — contract updated to ${new_value:,.0f} and new payment stage added.", "success")
        return redirect(url_for("project_detail", project_id=project_id) + "#tab-change-orders")
    fb_update(f"/projects/{project_id}", {"change_orders": cos})
    flash(f"{cos[co_idx]['co_number']} status updated to {new_status}.", "success")
    return redirect(url_for("project_detail", project_id=project_id) + "#tab-change-orders")

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
        amounts_updated = False
        if updated_stage_amounts_json:
            try:
                import json
                updated_stage_amounts = json.loads(updated_stage_amounts_json)
                # Update payment stages with updated amounts (preserving status and other fields)
                existing_stages = data.get("payment_stages") or []
                for i, amount_data in enumerate(updated_stage_amounts):
                    if i < len(existing_stages) and isinstance(existing_stages[i], dict):
                        existing_stages[i]["amount"] = _safe_float(amount_data.get("amount", 0))
                        # Preserve status and other fields
                        if "status" in amount_data:
                            existing_stages[i]["status"] = amount_data.get("status")

                updated["payment_stages"] = existing_stages
                amounts_updated = True
            except (json.JSONDecodeError, ValueError):
                flash("Error processing updated payment amounts.", "warning")

        # Handle custom stage amounts from frontend (for new customizations or preview stages)
        if not amounts_updated:
            custom_stage_amounts_json = request.form.get("custom_stage_amounts", "")
            if custom_stage_amounts_json and custom_stage_amounts_json != "[]":
                try:
                    import json
                    custom_stage_amounts = json.loads(custom_stage_amounts_json)
                    if custom_stage_amounts:  # Only process if list is not empty
                        # If custom amounts has name and amount fields (from preview),
                        # ensure they include status and invoice_id fields
                        if custom_stage_amounts and isinstance(custom_stage_amounts[0], dict) and "name" in custom_stage_amounts[0]:
                            # Ensure all required fields are present
                            enriched_stages = []
                            for stage in custom_stage_amounts:
                                enriched = {
                                    "name": stage.get("name", ""),
                                    "amount": _safe_float(stage.get("amount", 0)),
                                    "status": stage.get("status", "Pending Invoice"),
                                    "invoice_id": stage.get("invoice_id", "")
                                }
                                enriched_stages.append(enriched)
                            updated["payment_stages"] = enriched_stages
                        else:
                            # Update payment stages with custom amounts
                            existing_stages = data.get("payment_stages") or []
                            for i, amount_data in enumerate(custom_stage_amounts):
                                if i < len(existing_stages) and isinstance(existing_stages[i], dict):
                                    existing_stages[i]["amount"] = _safe_float(amount_data.get("amount", 0))
                            updated["payment_stages"] = existing_stages
                        amounts_updated = True
                except (json.JSONDecodeError, ValueError):
                    flash("Error processing custom payment amounts. Using default distribution.", "warning")

        # If amounts were not customized, use standard distribution logic
        if not amounts_updated:
            existing_stages = data.get("payment_stages") or []
            plan_in_progress = any(s.get("status") != "Pending Invoice" for s in existing_stages if isinstance(s, dict))

            # Check if down payment or installment count changed
            old_down_pct = _safe_float(data.get("down_payment_percent", 0))
            old_installments = _safe_float(data.get("installment_count", 1))
            payment_plan_changed = (down_pct != old_down_pct) or (installments != old_installments)

            if plan_in_progress:
                # Stages already have invoices/payments against them — keep the plan intact
                flash("Payment plan kept as-is because one or more stages are already invoiced.", "info")
            else:
                # Always recalculate if payment plan changed or if no existing stages
                updated["payment_stages"] = _compute_payment_stages(
                    _safe_float(updated["contract_value"]), down_pct, installments, custom_amounts=custom_amounts)

        updated["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Guard: if the project already has payments, don't let a form submission silently
        # downgrade its status to "Not Started". Preserve any manually-set status above "Not Started"
        # for paid/partially-paid projects; _sync_project_payment below will then correct it upward.
        existing_status = data.get("status", "Not Started")
        existing_paid   = _safe_float(data.get("amount_paid", 0))
        new_status       = updated.get("status", "Not Started")
        if existing_paid > 0 and new_status == "Not Started" and existing_status not in ("Not Started", "Cancelled"):
            updated["status"] = existing_status

        fb_update(f"/projects/{project_id}", updated)

        # Re-sync payment-derived status so that a fully-paid project always shows Completed.
        proj_num = updated.get("project_number", data.get("project_number", ""))
        if proj_num:
            _sync_project_payment(proj_num)
            _auto_complete_project_if_paid(proj_num)

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
            "linked_projects":     [{"project_number": proj_num, "payment_stage_index": stage_idx}],
            "created_at":          now_str,
            "updated_at":          now_str,
            "created_by":          session.get("user_email", ""),
        },
        "line_items": [{
            "description": stage.get("name", f"Payment Stage {stage_idx + 1}"),
            "quantity":    "1",
            "unit_price":  str(amount),
            "amount":      str(amount),
            "project_number": proj_num,
        }],
    }
    iid = fb_push("/invoices", invoice_data)
    stage_status = "Paid" if mark_paid else "Invoiced"
    _mark_project_stage(proj_num, stage_idx, stage_status, invoice_id=iid, amount=_safe_float(amount))
    if project.get("status", "Not Started") == "Not Started":
        fb_update(f"/projects/{project_id}", {"status": "In Progress"})
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

    # Build project_number → plant lookup from projects
    raw_proj = fb_get("/projects") or {}
    proj_plant_map = {}
    if isinstance(raw_proj, dict):
        for pdata in raw_proj.values():
            if isinstance(pdata, dict):
                pnum = pdata.get("project_number", "")
                plt  = (pdata.get("plant") or "").strip().upper()
                if pnum and plt:
                    proj_plant_map[pnum] = plt

    items = []
    for iid, idata in (raw.items() if isinstance(raw, dict) else []):
        if idata and isinstance(idata, dict):
            idata["firebase_id"] = iid
            # Attach plant from the linked project
            meta = idata.get("meta", {}) or {}
            proj_num = meta.get("project_number", "")
            if not proj_num:
                # Try to get from first line item
                for li in (idata.get("line_items") or []):
                    if isinstance(li, dict) and li.get("project_number"):
                        proj_num = li["project_number"]
                        break
            idata["plant_state"] = proj_plant_map.get(proj_num, "")
            items.append(idata)
    items.sort(key=lambda x: x.get("meta", {}).get("created_at", ""), reverse=True)
    all_invoices_raw = list(items)

    # Calculate status for all invoices BEFORE filtering (so filter uses calculated status, not stored status)
    today_str = datetime.now().strftime("%Y-%m-%d")
    for inv in items:
        m = inv.get("meta", {})
        calculated_status = _calculate_invoice_status(inv)
        m["status"] = calculated_status
        due = m.get("due_date", "") or ""
        if calculated_status in ("Sent", "Viewed", "Partial") and due and due < today_str:
            m["status"] = "Overdue"

    search        = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "")
    date_from     = request.args.get("from", "")
    date_to       = request.args.get("to", "")
    client_filter = request.args.get("client", "")
    plant_filter  = request.args.get("plant", "").strip().upper()

    if search:
        items = [i for i in items if search in str(i).lower()]
    if status_filter:
        items = [i for i in items if i.get("meta", {}).get("status", "") == status_filter]
    if client_filter:
        items = [i for i in items if i.get("meta", {}).get("client_name", "") == client_filter]
    if plant_filter:
        items = [i for i in items if i.get("plant_state", "") == plant_filter]
    if date_from:
        items = [i for i in items if (i.get("meta", {}).get("invoice_date") or "") >= date_from]
    if date_to:
        items = [i for i in items if (i.get("meta", {}).get("invoice_date") or "") <= date_to]

    # Build filter dropdown lists - show all options (like projects tab) so you can always filter by any value
    # All clients from database
    inv_clients = _load_clients()
    # All plants from all invoices (before filtering)
    all_plants = sorted({i.get("plant_state", "") for i in all_invoices_raw if i.get("plant_state", "")})

    statuses = ["Draft", "Sent", "Viewed", "Paid", "Partial", "Overdue", "Cancelled"]
    active_tab = request.args.get("tab", "all-invoices")

    # KPI stats from filtered invoices (matching projects tab behavior)
    _kpi_rows = []
    for inv in items:
        m  = inv.get("meta", {}) or {}
        st = _calculate_invoice_status(inv)
        due = m.get("due_date", "") or ""
        if st in ("Sent", "Viewed", "Partial") and due and due < today_str:
            st = "Overdue"
        total_val = _safe_float(m.get("total", 0))
        amount_paid = _safe_float(m.get("amount_paid", 0))
        # Include tax payments in total paid (same as projects tab)
        tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in inv.get("tax_payments", []))
        total_paid = amount_paid + tax_paid
        _kpi_rows.append((st, total_val, total_paid))

    i_total       = len(_kpi_rows)
    i_draft_count = sum(1 for st, _, __ in _kpi_rows if st == "Draft")
    i_sent_count  = sum(1 for st, _, __ in _kpi_rows if st in ("Sent", "Viewed"))
    i_paid_count  = sum(1 for st, _, __ in _kpi_rows if st == "Paid")
    i_over_count  = sum(1 for st, _, __ in _kpi_rows if st == "Overdue")
    i_total_val   = sum(total for _, total, __ in _kpi_rows)
    i_total_paid  = sum(paid for _, __, paid in _kpi_rows)
    i_outstanding = i_total_val - i_total_paid
    i_coll_rate   = round(i_total_paid / i_total_val * 100) if i_total_val else 0
    i_overdue_amt = sum(total for st, total, __ in _kpi_rows if st == "Overdue")

    # Ensure all invoices have amount_paid and tax_paid in meta for template compatibility
    for inv in items:
        if "meta" not in inv:
            inv["meta"] = {}
        if "amount_paid" not in inv["meta"]:
            # Calculate from payment_log if missing
            payment_log = inv.get("payment_log", []) or []
            total_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log)
            inv["meta"]["amount_paid"] = str(total_paid) if total_paid > 0 else "0"
        if "tax_paid" not in inv["meta"]:
            # Calculate from tax_payments if missing
            tax_log = inv.get("tax_payments", []) or []
            tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
            inv["meta"]["tax_paid"] = str(tax_paid) if tax_paid > 0 else "0"

    return render_template("invoicing.html", invoices=items, statuses=statuses,
                           search=search, status_filter=status_filter,
                           date_from=date_from, date_to=date_to,
                           client_filter=client_filter, inv_clients=inv_clients,
                           plant_filter=plant_filter, inv_plants=all_plants,
                           active_tab=active_tab,
                           i_total=i_total, i_draft_count=i_draft_count,
                           i_sent_count=i_sent_count, i_paid_count=i_paid_count,
                           i_over_count=i_over_count, i_total_val=i_total_val,
                           i_total_paid=i_total_paid, i_outstanding=i_outstanding,
                           i_coll_rate=i_coll_rate, i_overdue_amt=i_overdue_amt)

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

            # Mark stage as Invoiced with the actual stage amount
            _mark_project_stage(proj_num, next_stage_idx, "Invoiced", invoice_id=inv_id, amount=stage_amount)

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
        # Use status from form if provided, otherwise default to "Draft"
        form_status = request.form.get("status", "Draft").strip()
        valid_statuses = {"Draft", "Sent", "Viewed", "Paid", "Partial", "Overdue", "Cancelled"}
        data["meta"]["status"] = form_status if form_status in valid_statuses else "Draft"
        # Initialize amount_paid and tax_paid to 0 for new invoices
        data["meta"]["amount_paid"] = "0"
        data["meta"]["tax_paid"] = "0"

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
            # Single project with single stage - use only the subtotal (without tax)
            # Payment stages should show only the project amount, not including tax
            invoice_subtotal = _safe_float(data["meta"].get("subtotal", 0))
            _mark_project_stage(data["meta"].get("project_number", ""),
                                int(stage_idx_raw), "Invoiced", invoice_id=inv_id, invoice_number=invoice_number, amount=invoice_subtotal)
        else:
            # Multiple projects - check if line items have stage indices
            item_projects = request.form.getlist("item_project[]")
            item_stage_indices = request.form.getlist("item_stage_index[]")

            # Store linked projects info for multi-project invoice detection
            linked_projects = []

            # Mark each stage from line items - use project's actual line item amount (without tax)
            invoice_subtotal = _safe_float(data["meta"].get("subtotal", 0))
            for i, proj_num in enumerate(item_projects):
                if i < len(item_stage_indices):
                    stage_idx_str = item_stage_indices[i].strip() if item_stage_indices[i] else ""
                    if stage_idx_str:
                        try:
                            stage_idx = int(stage_idx_str)
                            # Get project's actual line item amount (not including tax)
                            line_items = data.get("line_items", []) or []
                            project_line_amount = sum(_safe_float(item.get("amount", 0)) for item in line_items if isinstance(item, dict) and item.get("project_number", "") == proj_num)
                            _mark_project_stage(proj_num, stage_idx, "Invoiced", invoice_id=inv_id, invoice_number=invoice_number, amount=project_line_amount)
                            linked_projects.append({"project_number": proj_num, "payment_stage_index": stage_idx})
                        except (ValueError, IndexError):
                            pass

            # Update invoice metadata with linked projects for multi-project invoices
            # SORT by project number (extract last digits, sort numerically) so 005 comes before 006
            if linked_projects:
                linked_projects.sort(key=lambda x: int(x.get("project_number", "")[-3:]) if x.get("project_number", "")[-3:].isdigit() else x.get("project_number", ""))
                fb_update(f"/invoices/{inv_id}", {"meta/linked_projects": linked_projects})

        # Auto-advance project status: Not Started → In Progress when first invoice created
        proj_nums_to_update = set()
        if stage_idx_raw != "":
            pn = data["meta"].get("project_number", "")
            if pn:
                proj_nums_to_update.add(pn)
        else:
            for pn in request.form.getlist("item_project[]"):
                if pn:
                    proj_nums_to_update.add(pn)
        if proj_nums_to_update:
            all_proj = fb_get("/projects") or {}
            for pid, pdata in (all_proj.items() if isinstance(all_proj, dict) else []):
                if isinstance(pdata, dict) and pdata.get("project_number", "") in proj_nums_to_update:
                    if pdata.get("status", "Not Started") == "Not Started":
                        fb_update(f"/projects/{pid}", {"status": "In Progress"})

        # Handle payment entry if provided when creating invoice
        payment_amount = data.pop("_payment_amount", "").strip()
        payment_date = data.pop("_payment_date", "").strip()
        payment_reference = data.pop("_payment_reference", "").strip()

        if payment_amount and _safe_float(payment_amount) > 0:
            # Use sequential distribution: allocate to projects first, then tax
            amount = _safe_float(payment_amount)
            payment_log = data.get("payment_log", []) or []
            if not isinstance(payment_log, list):
                payment_log = []

            tax_log = data.get("tax_payments", []) or []
            if not isinstance(tax_log, list):
                tax_log = []

            main_project = data["meta"].get("project_number", "")
            line_items = data.get("line_items", []) or []
            tax_amount = _safe_float(data["meta"].get("tax_amount", 0))
            linked_projects = data["meta"].get("linked_projects", [])

            remaining = amount

            # Step 1: Allocate to project(s)
            if not linked_projects and main_project:
                linked_projects = [main_project]

            for proj_num in linked_projects:
                if remaining <= 0:
                    break

                # Calculate project's invoice amount from line items
                proj_amount = sum(_safe_float(item.get("amount", 0))
                                for item in line_items
                                if isinstance(item, dict) and
                                (item.get("project_number") == proj_num or not item.get("project_number")))

                # Calculate already received
                proj_received = sum(_safe_float(p.get("amount", 0))
                                  for p in payment_log
                                  if p.get("project_number") == proj_num)

                proj_needs = max(0, proj_amount - proj_received)

                if proj_needs > 0:
                    allocate = min(proj_needs, remaining)
                    payment_log.append({
                        "amount": str(allocate),
                        "date": payment_date or datetime.now().strftime("%Y-%m-%d"),
                        "method": data["meta"].get("payment_method", ""),
                        "reference": payment_reference,
                        "project_number": proj_num,
                    })
                    remaining -= allocate

            # Step 2: Allocate remaining to tax
            if remaining > 0 and tax_amount > 0:
                tax_received = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
                tax_needs = max(0, tax_amount - tax_received)

                if tax_needs > 0:
                    allocate_tax = min(tax_needs, remaining)
                    tax_log.append({
                        "amount": str(allocate_tax),
                        "date": payment_date or datetime.now().strftime("%Y-%m-%d"),
                        "method": data["meta"].get("payment_method", ""),
                        "reference": payment_reference,
                    })
                    remaining -= allocate_tax

            # Update invoice with payment data
            payment_log_data = payment_log
            tax_log_data = tax_log

            # Calculate total amount_paid and tax_paid
            total_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log_data)
            tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log_data)

            fb_update(f"/invoices/{inv_id}", {
                "payment_log": payment_log_data,
                "tax_payments": tax_log_data,
                "meta/amount_paid": str(total_paid),
                "meta/tax_paid": str(tax_paid),
            })

            # Update project stage payment amounts and status
            _update_project_stage_payment_status(inv_id)

            # Sync project-level payments
            for proj_num in proj_nums_to_update:
                _sync_project_payment(proj_num)
                _auto_complete_project_if_paid(proj_num)

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

        # Auto-populate Project Number field if only one project selected
        if len(project_ids) == 1 and project_ids[0] in all_projects_data:
            single_proj_data = all_projects_data[project_ids[0]]
            if isinstance(single_proj_data, dict):
                prefill_proj = single_proj_data.get("project_number", "")

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

    projects = _enrich_projects_with_next_stage(projects, raw_inv)

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

    # Enrich payment_log with project names, firebase_id, and stage names
    raw_proj = fb_get("/projects") or {}
    enriched_payment_log = []
    for payment in payment_log:
        payment_copy = dict(payment)
        proj_num = payment_copy.get("project_number", "")

        if proj_num:
            # Find project data to get name, firebase_id and stage
            for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
                if not isinstance(pdata, dict):
                    continue
                if pdata.get("project_number") == proj_num:
                    payment_copy["project_name"] = pdata.get("project_name", "")
                    payment_copy["project_firebase_id"] = pid  # Add firebase_id for link
                    # Find the stage name and status from payment_stages
                    stages = pdata.get("payment_stages", [])
                    if isinstance(stages, list):
                        for stage in stages:
                            if isinstance(stage, dict) and stage.get("invoice_id") == invoice_id:
                                payment_copy["stage_name"] = stage.get("name", "Invoice Payment")
                                payment_copy["stage_status"] = stage.get("status", "Invoiced")
                                break
                    break
        enriched_payment_log.append(payment_copy)

    # Tax payments kept separate from projects (no enrichment with project data)
    tax_log = data.get("tax_payments", [])
    if not isinstance(tax_log, list):
        tax_log = []
    enriched_tax_payments = [dict(payment) for payment in tax_log]

    # Calculate current status based on actual payments (not stored status)
    calculated_status = _calculate_invoice_status(data)
    # Update the invoice data with calculated status for display
    data["meta"]["status"] = calculated_status

    # Ensure tax_paid is set in meta for template compatibility
    if "tax_paid" not in data["meta"]:
        tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
        data["meta"]["tax_paid"] = str(tax_paid) if tax_paid > 0 else "0"

    # Refresh project payment stage amounts to ensure they're always current
    _update_project_stage_payment_status(invoice_id)

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

        # Handle payment entry if provided - use sequential distribution like invoice_detail
        payment_amount = updated.pop("_payment_amount", "").strip()
        payment_date = updated.pop("_payment_date", "").strip()
        payment_reference = updated.pop("_payment_reference", "").strip()

        if payment_amount and _safe_float(payment_amount) > 0:
            # Use sequential distribution: allocate to projects first, then tax
            amount = _safe_float(payment_amount)
            payment_log = updated.get("payment_log", []) or []
            if not isinstance(payment_log, list):
                payment_log = []

            tax_log = updated.get("tax_payments", []) or []
            if not isinstance(tax_log, list):
                tax_log = []

            main_project = updated["meta"].get("project_number", "")
            line_items = updated.get("line_items", []) or []
            tax_amount = _safe_float(updated["meta"].get("tax_amount", 0))
            linked_projects = updated["meta"].get("linked_projects", [])

            remaining = amount

            # Step 1: Allocate to project(s)
            if not linked_projects and main_project:
                linked_projects = [main_project]

            for proj_num in linked_projects:
                if remaining <= 0:
                    break

                # Calculate project's invoice amount from line items
                proj_amount = sum(_safe_float(item.get("amount", 0))
                                for item in line_items
                                if isinstance(item, dict) and
                                (item.get("project_number") == proj_num or not item.get("project_number")))

                # Calculate already received
                proj_received = sum(_safe_float(p.get("amount", 0))
                                  for p in payment_log
                                  if p.get("project_number") == proj_num)

                proj_needs = max(0, proj_amount - proj_received)

                if proj_needs > 0:
                    allocate = min(proj_needs, remaining)
                    payment_log.append({
                        "amount": str(allocate),
                        "date": payment_date or datetime.now().strftime("%Y-%m-%d"),
                        "method": updated["meta"].get("payment_method", ""),
                        "reference": payment_reference,
                        "project_number": proj_num,
                    })
                    remaining -= allocate

            # Step 2: Allocate remaining to tax
            if remaining > 0 and tax_amount > 0:
                tax_received = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
                tax_needs = max(0, tax_amount - tax_received)

                if tax_needs > 0:
                    allocate_tax = min(tax_needs, remaining)
                    tax_log.append({
                        "amount": str(allocate_tax),
                        "date": payment_date or datetime.now().strftime("%Y-%m-%d"),
                        "method": updated["meta"].get("payment_method", ""),
                        "reference": payment_reference,
                    })
                    remaining -= allocate_tax

            updated["payment_log"] = payment_log
            updated["tax_payments"] = tax_log

        # Calculate total amount_paid from payment_log and tax_paid from tax_payments for meta
        payment_log = updated.get("payment_log", []) or []
        tax_log = updated.get("tax_payments", []) or []
        if isinstance(payment_log, list):
            total_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log)
            updated["meta"]["amount_paid"] = str(total_paid)
        if isinstance(tax_log, list):
            tax_paid = sum(_safe_float(p.get("amount", 0)) for p in tax_log)
            updated["meta"]["tax_paid"] = str(tax_paid)

        fb_update(f"/invoices/{invoice_id}", updated)

        # Use sequential allocation for multi-project invoices
        linked_projects = _invoice_linked_projects(updated)
        if len(linked_projects) > 1:
            _allocate_invoice_payment_sequential(invoice_id)

        # Update project stage payment amounts (same as payment_sequential endpoint)
        # This ensures payment stages show the correct paid amounts
        _update_project_stage_payment_status(invoice_id)

        # Sync project-level amount_paid and status for all linked projects
        for proj_num in linked_projects:
            _sync_project_payment(proj_num)
            _auto_complete_project_if_paid(proj_num)
            # Refresh all stages for this project from remaining invoices
            proj_id, pdata = _find_project_by_number(proj_num)
            if proj_id and pdata:
                stages = pdata.get("payment_stages", [])
                if isinstance(stages, list):
                    for stage_idx, stage in enumerate(stages):
                        if isinstance(stage, dict):
                            # Recalculate this stage's amount_paid from invoices linked to it
                            stage_paid = 0.0
                            found_invoice_id = None
                            found_invoice_number = None

                            # Method 1: Look for invoices by invoice_id stored in the stage
                            stage_invoice_id = stage.get("invoice_id")
                            if stage_invoice_id:
                                inv_data = fb_get(f"/invoices/{stage_invoice_id}") or {}
                                payment_log = inv_data.get("payment_log", [])
                                if isinstance(payment_log, list):
                                    stage_paid = sum(_safe_float(p.get("amount", 0)) for p in payment_log)
                                if stage_paid > 0:
                                    found_invoice_id = stage_invoice_id
                                    found_invoice_number = inv_data.get("meta", {}).get("invoice_number", "")
                            else:
                                # Method 2: Look for invoices by payment_stage_index (fallback)
                                all_invoices = fb_get("/invoices") or {}
                                if isinstance(all_invoices, dict):
                                    for inv_id, inv_data in all_invoices.items():
                                        if isinstance(inv_data, dict):
                                            inv_meta = inv_data.get("meta", {}) or {}
                                            # Check if this invoice covers this project and stage
                                            if (inv_meta.get("project_number") == proj_num and
                                                inv_meta.get("payment_stage_index") == stage_idx):
                                                # Sum payments for this invoice
                                                payment_log = inv_data.get("payment_log", [])
                                                if isinstance(payment_log, list):
                                                    stage_paid += sum(_safe_float(p.get("amount", 0)) for p in payment_log)
                                                if stage_paid > 0:
                                                    found_invoice_id = inv_id
                                                    found_invoice_number = inv_meta.get("invoice_number", "")

                            # Update stage with current amount_paid and invoice tracking info
                            stage["amount_paid"] = str(stage_paid)
                            if found_invoice_id:
                                stage["invoice_id"] = found_invoice_id
                            if found_invoice_number:
                                stage["invoice_number"] = found_invoice_number

                    # Save updated stages back to project
                    fb_update(f"/projects/{proj_id}", {
                        "payment_stages": stages,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })

        if updated["meta"].get("status") in ("Paid", "Partial"):
            _upsert_revenue_entry(invoice_id, updated["meta"])
        flash("Invoice updated.", "success")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))
    # Lock unit price if invoice has linked projects (created from payment stages)
    linked_projects = data.get("meta", {}).get("linked_projects", [])
    lock_unit_price = isinstance(linked_projects, list) and len(linked_projects) > 0

    projects = _enrich_projects_with_next_stage(projects)

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
        elif new_status in ("Sent", "Viewed", "Overdue"):
            _advance_project_to_in_progress(proj_num)
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
                # Update the stage with current invoice total
                invoice_total = _safe_float(m.get("total", 0))
                _mark_project_stage(main_proj_num, int(stage_idx_meta), stage_status, invoice_id=invoice_id, amount=invoice_total)
    if new_status in ("Paid", "Partial"):
        _upsert_revenue_entry(invoice_id, m)

    flash(f"Invoice updated to {new_status}. Project & balance sheet synced.", "success")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))

@app.route("/api/invoices/<invoice_id>/update-amount", methods=["POST"])
@role_required("invoicing")
def invoice_update_amount(invoice_id):
    """Update invoice line item amount from payment stage edit - handles multi-project invoices"""
    try:
        new_amount = _safe_float(request.form.get("new_amount", 0))
        project_number = request.form.get("project_number", "").strip()
        invoice = fb_get(f"/invoices/{invoice_id}") or {}
        meta = invoice.get("meta", {})
        tax_rate = _safe_float(meta.get("tax_rate", 0))

        # Update line items if they exist
        line_items = invoice.get("line_items", [])
        if line_items:
            # Find the correct line item to update
            line_item_idx = 0

            if project_number:
                # For multi-project invoices: find line item by project_number
                # This matches the payment_log approach where payments are tracked by project_number
                for idx, item in enumerate(line_items):
                    if isinstance(item, dict) and item.get("project_number", "").strip() == project_number:
                        line_item_idx = idx
                        break

            # Update only the identified line item's amount and unit_price
            line_items[line_item_idx]["amount"] = str(new_amount)
            line_items[line_item_idx]["unit_price"] = str(new_amount)

            # Recalculate Down Payment percentage if it's a down payment item
            if "Down Payment" in line_items[line_item_idx].get("description", ""):
                # Get contract value from project data
                contract_value = 0
                if project_number:
                    proj_data = fb_get(f"/projects/{project_number}") or {}
                    contract_value = _safe_float(proj_data.get("contract_value", 0))
                else:
                    # Fallback: get from main project_number
                    proj_num = meta.get("project_number", "")
                    if proj_num:
                        proj_data = fb_get(f"/projects/{proj_num}") or {}
                        contract_value = _safe_float(proj_data.get("contract_value", 0))

                # Calculate correct percentage
                if contract_value > 0:
                    dp_pct = int(round((new_amount / contract_value) * 100))
                    # Update description with correct percentage
                    desc = line_items[line_item_idx].get("description", "Down Payment")
                    base_desc = desc.split("(")[0].strip() if "(" in desc else desc
                    line_items[line_item_idx]["description"] = f"{base_desc} ({dp_pct}%)"

            invoice["line_items"] = line_items

            # Recalculate subtotal and total as sum of ALL line items (critical for multi-project!)
            # Same approach as payment_sequential: sum actual line item amounts
            invoice_subtotal = sum(_safe_float(item.get("amount", 0)) for item in line_items if isinstance(item, dict))
            meta["subtotal"] = str(invoice_subtotal)

            # Recalculate tax based on new subtotal and tax rate (same as payment_sequential process)
            new_tax_amount = invoice_subtotal * (tax_rate / 100.0) if tax_rate > 0 else 0
            meta["tax_amount"] = str(new_tax_amount)
            meta["total"] = str(invoice_subtotal + new_tax_amount)

            # For multi-project invoices: update linked_projects metadata to match current line items
            # This ensures _allocate_invoice_payment_sequential knows about all projects
            projects_in_items = set()
            for item in line_items:
                if isinstance(item, dict):
                    proj_num = item.get("project_number", "")
                    if proj_num:
                        projects_in_items.add(proj_num)

            # If multiple projects in line items, update linked_projects metadata
            if len(projects_in_items) > 1:
                main_stage_idx = meta.get("payment_stage_index", 0)
                meta["linked_projects"] = [
                    {"project_number": proj_num, "payment_stage_index": main_stage_idx}
                    for proj_num in sorted(projects_in_items)
                ]

        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        invoice["meta"] = meta
        invoice["updated_at"] = datetime.now(timezone.utc).isoformat()
        fb_update(f"/invoices/{invoice_id}", invoice)

        # When editing amounts, redistribute payments the SAME WAY as payment_sequential
        # This ensures both work identically - payments distributed sequentially across projects then tax
        # Use the locally updated invoice object (not fresh from DB) to get updated line_items and metadata
        amount_paid = _safe_float(meta.get("amount_paid", 0))
        tax_amount = _safe_float(meta.get("tax_amount", 0))
        line_items = invoice.get("line_items", []) or []  # Use local updated line_items
        main_project = meta.get("project_number", "")
        linked_projects = meta.get("linked_projects", [])  # Use updated linked_projects from meta

        # Only redistribute if there's an amount paid (otherwise no payment history to redistribute)
        if amount_paid > 0:
            # Clear existing payment logs and rebuild them sequentially (same as payment_sequential)
            new_payment_log = []
            new_tax_log = []
            remaining_to_distribute = amount_paid

            # Extract ALL projects from BOTH line_items AND linked_projects metadata
            # This handles invoices where some projects might not have line items
            projects_from_items = set()
            for item in line_items:
                if isinstance(item, dict):
                    proj_num = item.get("project_number", "")
                    if proj_num:
                        projects_from_items.add(proj_num)

            # Also get projects from linked_projects metadata (might have projects without line items)
            projects_from_meta = set()
            for proj_info in (meta.get("linked_projects") or []):
                if isinstance(proj_info, dict):
                    proj_num = proj_info.get("project_number", "")
                    if proj_num:
                        projects_from_meta.add(proj_num)

            # Merge both sets - include projects from BOTH line_items AND metadata
            all_projects = projects_from_items | projects_from_meta

            # Build linked_projects from merged project list
            if all_projects:
                linked_projects = [
                    {"project_number": proj_num, "payment_stage_index": meta.get("payment_stage_index", 0)}
                    for proj_num in sorted(all_projects)
                ]
            elif not linked_projects and main_project:
                linked_projects = [{"project_number": main_project, "payment_stage_index": meta.get("payment_stage_index", 0)}]

            # Step 1: Distribute to projects sequentially (sorted by project number)
            if linked_projects:
                # Sort projects by number
                def get_sort_key(x):
                    proj_num = x.get("project_number", "") if isinstance(x, dict) else x
                    if proj_num and proj_num[-3:].isdigit():
                        return int(proj_num[-3:])
                    return proj_num
                sorted_projects = sorted(linked_projects, key=get_sort_key)

                for proj_info in sorted_projects:
                    if remaining_to_distribute <= 0:
                        break

                    proj_num = proj_info.get("project_number", "") if isinstance(proj_info, dict) else proj_info
                    if not proj_num:
                        continue

                    # Get this project's line item amount
                    proj_amount = sum(_safe_float(item.get("amount", 0)) for item in line_items
                                    if isinstance(item, dict) and item.get("project_number", "").strip() == proj_num)

                    if proj_amount > 0:
                        # Allocate up to this project's amount
                        distribute_to_proj = min(proj_amount, remaining_to_distribute)

                        # Get stage info for payment entry
                        _stage_name = meta.get("payment_stage", "")
                        _stage_idx = meta.get("payment_stage_index")
                        if _stage_idx is not None:
                            try:
                                _stage_idx = int(_stage_idx) if not isinstance(_stage_idx, int) else _stage_idx
                            except (ValueError, TypeError):
                                _stage_idx = None

                        if not _stage_name and _stage_idx is not None:
                            _stage_name = f"Stage {_stage_idx + 1}"

                        new_payment_log.append({
                            "amount": str(distribute_to_proj),
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "project_number": proj_num,
                            "invoice_number": meta.get("invoice_number", ""),
                            "stage_name": _stage_name,
                            "stage_index": _stage_idx or "",
                        })
                        remaining_to_distribute -= distribute_to_proj

            # Step 2: Distribute remaining to tax
            if remaining_to_distribute > 0 and tax_amount > 0:
                tax_needs = min(tax_amount, remaining_to_distribute)
                new_tax_log.append({
                    "amount": str(tax_needs),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                remaining_to_distribute -= tax_needs

            # Update Firebase with redistributed payment logs (same structure as payment_sequential)
            fb_update(f"/invoices/{invoice_id}", {
                "payment_log": new_payment_log,
                "tax_payments": new_tax_log if new_tax_log else []
            })

        return jsonify({"success": True, "message": "Invoice updated"})
    except Exception as e:
        log.error("Invoice update error: %s", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/invoicing/<invoice_id>/delete", methods=["POST"])
@role_required("invoicing")
def invoice_delete(invoice_id):
    # Get invoice data before deleting
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    meta = inv_data.get("meta", {})

    print(f"\n=== INVOICE DELETE DEBUG ===", flush=True)
    print(f"Invoice ID: {invoice_id}", flush=True)
    print(f"Meta data: {meta}", flush=True)

    # Revert payment stages back to "Pending" and collect projects to sync
    project_numbers_to_sync = set()

    project_number = meta.get("project_number", "")
    payment_stage_index = meta.get("payment_stage_index")

    print(f"project_number: '{project_number}', payment_stage_index: {payment_stage_index}", flush=True)

    # Get payment amounts to subtract from stages
    payment_log = inv_data.get("payment_log", []) or []
    total_payments_deleted = sum(_safe_float(p.get("amount", 0)) for p in payment_log if isinstance(p, dict))
    print(f"Total payments in deleted invoice: {total_payments_deleted}", flush=True)

    if project_number and payment_stage_index is not None:
        # Single project with single stage - clear its amount_paid since this invoice is deleted
        print(f"Reverting single stage: {project_number} stage {payment_stage_index}", flush=True)
        _mark_project_stage(project_number, payment_stage_index, "Pending Invoice", amount_paid=0)
        project_numbers_to_sync.add(project_number)
    elif project_number and not payment_stage_index:
        # Invoice without explicit stage - find the stage by invoice_id
        print("Invoice without payment_stage_index - finding by invoice_id", flush=True)
        all_proj = fb_get("/projects") or {}
        for pid, pdata in (all_proj.items() if isinstance(all_proj, dict) else []):
            if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
                stages = pdata.get("payment_stages", [])
                if isinstance(stages, list):
                    for idx, stage in enumerate(stages):
                        if isinstance(stage, dict) and stage.get("invoice_id") == invoice_id:
                            print(f"Found stage {idx} with this invoice_id, reverting", flush=True)
                            _mark_project_stage(project_number, idx, "Pending Invoice", amount_paid=0)
                            project_numbers_to_sync.add(project_number)
                            break
                break
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
                        _mark_project_stage(proj_num, stage_idx, "Pending Invoice", amount_paid=0)
                        project_numbers_to_sync.add(proj_num)
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
                            _mark_project_stage(proj_num, stage_idx, "Pending Invoice", amount_paid=0)
                            project_numbers_to_sync.add(proj_num)

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

    # Recalculate stage amounts_paid for all affected projects based on remaining invoices
    for proj_num in project_numbers_to_sync:
        if proj_num:
            # Find all invoices linked to this project and update their stage amounts_paid
            all_invoices = fb_get("/invoices") or {}
            for inv_id, inv_data in (all_invoices.items() if isinstance(all_invoices, dict) else []):
                if isinstance(inv_data, dict):
                    inv_meta = inv_data.get("meta", {}) or {}
                    # Check if this invoice is linked to the project we're updating
                    linked_projects = inv_meta.get("linked_projects", [])
                    is_linked = False

                    # Check if project is in linked_projects
                    if isinstance(linked_projects, list):
                        for lp in linked_projects:
                            if isinstance(lp, dict) and lp.get("project_number") == proj_num:
                                is_linked = True
                                break
                            elif isinstance(lp, str) and lp == proj_num:
                                is_linked = True
                                break

                    # Also check if it's the main project_number
                    if inv_meta.get("project_number") == proj_num:
                        is_linked = True

                    if is_linked:
                        _update_project_stage_payment_status(inv_id)
                        print(f"Updated stage amounts_paid for invoice {inv_id}", flush=True)

    # Sync payment amounts for all affected projects
    for proj_num in project_numbers_to_sync:
        if proj_num:
            # Recalculate all stages for this project from remaining invoices
            _sync_project_payment(proj_num)
            print(f"Synced payment for project: {proj_num}", flush=True)

            # Update project status based on remaining payments
            proj_id, pdata = _find_project_by_number(proj_num)
            if proj_id and pdata:
                amount_paid = _safe_float(pdata.get("amount_paid", 0))
                current_status = pdata.get("status", "Not Started")

                # If still has payments, change to In Progress
                if amount_paid > 0 and current_status == "Completed":
                    fb_update(f"/projects/{proj_id}", {
                        "status": "In Progress",
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })
                # If no payments left, change to Not Started
                elif amount_paid == 0 and current_status != "Not Started":
                    fb_update(f"/projects/{proj_id}", {
                        "status": "Not Started",
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })

                # Recalculate all payment stage amounts for this project from remaining invoices
                stages = pdata.get("payment_stages", [])
                if isinstance(stages, list):
                    for stage_idx, stage in enumerate(stages):
                        if isinstance(stage, dict):
                            # Recalculate this stage's amount_paid from remaining invoices
                            all_invoices = fb_get("/invoices") or {}
                            stage_paid = 0.0
                            if isinstance(all_invoices, dict):
                                for inv_id, inv_data in all_invoices.items():
                                    if isinstance(inv_data, dict):
                                        inv_meta = inv_data.get("meta", {}) or {}
                                        # Check if this invoice covers this project and stage
                                        if (inv_meta.get("project_number") == proj_num and
                                            inv_meta.get("payment_stage_index") == stage_idx):
                                            # Sum payments for this invoice
                                            payment_log = inv_data.get("payment_log", [])
                                            if isinstance(payment_log, list):
                                                stage_paid += sum(_safe_float(p.get("amount", 0)) for p in payment_log)

                            # Update stage with recalculated amount_paid
                            stage["amount_paid"] = str(stage_paid)
                            print(f"[DELETE] Recalculated stage {stage_idx} amount_paid: {stage_paid}")

                    # Save updated stages
                    fb_update(f"/projects/{proj_id}", {
                        "payment_stages": stages,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })

    flash("Invoice deleted successfully", "success")
    return redirect(url_for("invoicing"))

@app.route("/invoicing/<invoice_id>/pdf")
@role_required("invoicing")
def invoice_pdf(invoice_id):
    try:
        from reportlab.lib.pagesizes import A4
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))

    pdf_bytes = _generate_invoice_pdf_bytes(invoice_id)
    if not pdf_bytes:
        abort(404)

    invoice = fb_get(f"/invoices/{invoice_id}")
    meta = invoice.get("meta", {}) if invoice else {}

    from flask import Response
    fname = f"Invoice_{meta.get('invoice_number','')}.pdf"
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline;filename={fname}"})

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

@app.route("/clients/<client_name>/delete", methods=["POST"])
@role_required("invoicing")
def delete_client(client_name):
    fb_delete(f"/clients/{client_name}")
    flash(f"Client '{client_name}' deleted.", "success")
    return redirect(url_for("clients"))

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
    total_paid    += sum(_safe_float(p.get("amount", 0)) for i in inv_list for p in i.get("tax_payments", []))
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

    # Invoice table - one row per invoice with all projects listed vertically
    elems.append(Paragraph("INVOICE HISTORY", h2))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=border, spaceAfter=6))
    tbl_data = [["Invoice #", "Project", "Date", "Due Date", "Status", "Total", "Paid", "Balance"]]

    for inv in inv_list:
        m = inv.get("meta", {})
        total = _safe_float(m.get("total", 0))
        paid  = _safe_float(m.get("amount_paid", 0))
        tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in inv.get("tax_payments", []))
        total_paid_with_tax = paid + tax_paid
        balance = total - total_paid_with_tax

        # Get all linked projects
        linked_projects = _invoice_linked_projects(inv)
        projects_list = sorted(list(linked_projects)) if linked_projects else ["—"]

        # Create project column with all projects listed vertically (separated by newlines)
        projects_text = "\n".join(projects_list)

        # Add single row with invoice info and all projects stacked in one cell
        tbl_data.append([
            m.get("invoice_number", "—"),
            projects_text,
            m.get("invoice_date", "—") or "—",
            m.get("due_date", "—") or "—",
            m.get("status", "—"),
            f"${total:,.2f}",
            f"${total_paid_with_tax:,.2f}",
            f"${balance:,.2f}",
        ])

    if not inv_list:
        tbl_data.append(["No invoices found.", "", "", "", "", "", "", ""])

    cw = [1.0*inch, 1.2*inch, 0.85*inch, 0.85*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch]
    tbl = Table(tbl_data, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), dark),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 8),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("VALIGN",        (0,0), (-1,0), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,0), 3), ("BOTTOMPADDING",(0,0),(-1,0),3),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, light]),
        ("GRID",          (0,0), (-1,-1), 0.4, border),
        ("TOPPADDING",    (0,1), (-1,-1), 6), ("BOTTOMPADDING",(0,1),(-1,-1),6),
        ("LEFTPADDING",   (0,1), (-1,-1), 4), ("RIGHTPADDING",(0,1),(-1,-1),4),
        ("VALIGN",        (0,1), (-1,-1), "MIDDLE"),
        ("ALIGN",         (0,1), (-1,-1), "CENTER"),
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
    import re
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '', client_name.replace(" ", "_"))
    fname = f"statement_{safe_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment;filename="{fname}"'})

# ── Routes: Payroll ───────────────────────────────────────────────────────────
def _load_employee_profiles() -> list:
    raw = fb_get("/employee_profiles") or {}
    profiles = []
    if isinstance(raw, dict):
        for pid, pdata in raw.items():
            if isinstance(pdata, dict):
                pdata["firebase_id"] = pid
                profiles.append(pdata)
    profiles.sort(key=lambda x: x.get("name", "").lower())
    return profiles

def _auto_generate_monthly_salaries() -> int:
    """Create payroll entries for users with monthly_salary > 0 (Settings-based employees).
    Runs once per calendar month per employee — skipped if an entry for the
    current YYYY-MM already exists in /balance_sheet_salary.
    Returns the number of new entries created.
    """
    users = _load_all_users()
    if not users:
        return 0
    now         = datetime.now()
    month_key   = now.strftime("%Y-%m")
    month_label = now.strftime("%B %Y")
    raw_sal     = fb_get("/balance_sheet_salary") or {}
    existing    = set()
    if isinstance(raw_sal, dict):
        for entry in raw_sal.values():
            if isinstance(entry, dict):
                name = (entry.get("employee_name") or entry.get("employee", "")).strip().lower()
                date = (entry.get("date") or "")[:7]
                if name and date == month_key:
                    existing.add(name)
    created = 0
    for u in users:
        monthly = _safe_float(u.get("monthly_salary", 0))
        if monthly <= 0:
            continue
        name = (u.get("username") or "").strip()
        if not name or name.lower() in existing:
            continue
        fb_push("/balance_sheet_salary", {
            "employee_name":  name,
            "employee":       name,
            "amount":         monthly,
            "date":           now.strftime("%Y-%m-01"),
            "description":    f"Monthly salary — {month_label}",
            "type":           "salary",
            "region":         u.get("region", ""),
            "auto_generated": True,
            "created_at":     datetime.now(timezone.utc).isoformat(),
        })
        created += 1
    return created

@app.route("/payroll")
@role_required("payroll")
def payroll():
    _auto_generate_monthly_salaries()
    employee_filter = request.args.get("employee", "")
    year_filter     = request.args.get("year", "")
    region_filter   = request.args.get("region", "")

    # Load salary records server-side so the table renders without relying on JS fetch
    raw_sal = fb_get("/balance_sheet_salary") or {}
    salaries = []
    if isinstance(raw_sal, dict):
        for sid, sdata in raw_sal.items():
            if isinstance(sdata, dict):
                sdata["firebase_id"] = sid
                salaries.append(sdata)
    salaries.sort(key=lambda s: s.get("date", ""), reverse=True)

    # Build employee list from /users (Settings) — normalize 'username' → 'name' for template compatibility
    raw_users = _load_all_users()
    employee_profiles = [
        dict(u, name=u.get("username", ""))
        for u in raw_users
        if u.get("active", True)
    ]
    return render_template("payroll.html",
        employee_filter=employee_filter,
        year_filter=year_filter,
        region_filter=region_filter,
        employee_profiles=employee_profiles,
        salaries=salaries)

# ── Employee Profile API ──────────────────────────────────────────────────────
@app.route("/api/employee-profiles", methods=["GET"])
@login_required
def api_employee_profiles_get():
    return jsonify({"profiles": _load_employee_profiles()})

@app.route("/api/employee-profiles", methods=["POST"])
@login_required
def api_employee_profiles_post():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    profile = {
        "name":         name,
        "title":        (data.get("title") or "").strip(),
        "region":       data.get("region", "Inside America"),
        "hourly_rate":  float(data.get("hourly_rate") or 0),
        "email":        (data.get("email") or "").strip(),
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    pid = fb_push("/employee_profiles", profile)
    profile["firebase_id"] = pid
    return jsonify({"success": True, "profile": profile}), 201

@app.route("/api/employee-profiles/<profile_id>", methods=["PATCH"])
@login_required
def api_employee_profiles_patch(profile_id):
    data = request.get_json() or {}
    updates = {}
    for field in ("name", "title", "region", "email"):
        if field in data:
            updates[field] = (data[field] or "").strip()
    if "hourly_rate" in data:
        updates["hourly_rate"] = float(data.get("hourly_rate") or 0)
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    fb_update(f"/employee_profiles/{profile_id}", updates)
    return jsonify({"success": True})

@app.route("/api/employee-profiles/<profile_id>", methods=["DELETE"])
@login_required
def api_employee_profiles_delete(profile_id):
    fb_delete(f"/employee_profiles/{profile_id}")
    return jsonify({"success": True})

@app.route("/api/payroll/salaries", methods=["GET"])
@login_required
def get_salaries():
    salaries_data = fb_get("/balance_sheet_salary") or {}
    salaries = []
    if isinstance(salaries_data, dict):
        for sid, sdata in salaries_data.items():
            if isinstance(sdata, dict):
                sdata["firebase_id"] = sid
                salaries.append(sdata)

    search    = request.args.get("search", "").lower()
    region    = request.args.get("region", "")
    date_from = request.args.get("date_from", "")
    date_to   = request.args.get("date_to", "")

    filtered = salaries
    if search:
        filtered = [s for s in filtered if search in s.get("employee_name", "").lower()]
    if region:
        filtered = [s for s in filtered if s.get("region", "") == region]
    if date_from:
        filtered = [s for s in filtered if s.get("date", "") >= date_from]
    if date_to:
        filtered = [s for s in filtered if s.get("date", "") <= date_to]

    return jsonify({"salaries": filtered})

@app.route("/api/payroll/salaries", methods=["POST"])
@login_required
def create_salary():
    data = request.json
    date_str = data.get("date", "")
    try:
        year = int(date_str[:4]) if date_str else datetime.now().year
    except (ValueError, IndexError):
        year = datetime.now().year

    region = data.get("region", "Inside America")
    if region == "USA":
        region = "Inside America"
    elif region == "International":
        region = "Outside America"

    sal_data = {
        "employee_name": data.get("employee_name"),
        "date":          date_str,
        "amount":        float(data.get("amount", 0)),
        "notes":         data.get("notes", ""),
        "region":        region,
        "year":          year,
        "created_at":    datetime.now(timezone.utc).isoformat(),
    }
    fb_push("/balance_sheet_salary", sal_data)
    return jsonify({"success": True})

@app.route("/api/payroll/salaries/<sal_id>", methods=["PUT"])
@login_required
def update_salary(sal_id):
    data = request.json
    date_str = data.get("date", "")
    try:
        year = int(date_str[:4]) if date_str else datetime.now().year
    except (ValueError, IndexError):
        year = datetime.now().year
    region = data.get("region", "Inside America")
    if region == "USA":
        region = "Inside America"
    elif region == "International":
        region = "Outside America"
    sal_data = {
        "employee_name": data.get("employee_name"),
        "date":          date_str,
        "amount":        float(data.get("amount", 0)),
        "notes":         data.get("notes", ""),
        "region":        region,
        "year":          year,
        "updated_at":    datetime.now(timezone.utc).isoformat(),
    }
    fb_update(f"/balance_sheet_salary/{sal_id}", sal_data)
    return jsonify({"success": True})

@app.route("/api/payroll/salaries/<sal_id>", methods=["DELETE"])
@login_required
def delete_salary(sal_id):
    fb_delete(f"/balance_sheet_salary/{sal_id}")
    return jsonify({"success": True})

# ── Routes: Financial ─────────────────────────────────────────────────────────
@app.route("/financial")
@role_required("financial")
def financial():
    invoices = fb_get("/invoices") or {}
    expenses = fb_get("/balance_sheet_expenses") or {}
    revenue  = fb_get("/balance_sheet_revenue") or {}

    # Get filter parameters from URL
    filter_expense = request.args.get("filter_expense", "")
    selected_year = request.args.get("year", str(datetime.now().year))
    try:
        selected_year = int(selected_year)
    except (ValueError, TypeError):
        selected_year = datetime.now().year

    inv_list  = [v for v in invoices.values() if isinstance(v, dict)] if isinstance(invoices, dict) else []
    exp_list_raw  = []
    if isinstance(expenses, dict):
        for eid, edata in expenses.items():
            if isinstance(edata, dict):
                edata["firebase_id"] = eid
                exp_list_raw.append(edata)

    # Group expenses by name and sum amounts
    def group_expenses_by_name(items):
        """Group expenses by name and sum amounts, preserving expense_type and category"""
        grouped = {}
        for item in items:
            exp_name = item.get("expense_name", "") or item.get("description", "—")
            amount = _safe_float(item.get("amount", 0))
            if exp_name not in grouped:
                grouped[exp_name] = {
                    "expense_name": exp_name,
                    "description": exp_name,
                    "expense_type": item.get("expense_type", "—"),
                    "category": item.get("category", "—"),
                    "amount": 0,
                    "firebase_id": item.get("firebase_id", ""),
                    "date": item.get("date", ""),
                    "vendor": item.get("vendor", ""),
                    "project_number": item.get("project_number", ""),
                    "notes": item.get("notes", ""),
                    "receipt_filename": item.get("receipt_filename", "")
                }
            grouped[exp_name]["amount"] += amount
        return list(grouped.values())

    # Keep BOTH versions: raw for expense tab (all individual entries), grouped for balance sheet
    exp_list_all = sorted(exp_list_raw, key=lambda x: x.get("created_at", "") or x.get("date", ""), reverse=True)  # Sort by creation date (newest first)
    exp_list_grouped_all = group_expenses_by_name(exp_list_raw)  # Consolidated for reference

    # Filter expenses by selected year for balance sheet
    def filter_by_year(items, year_val):
        """Filter items by year from date field"""
        filtered = []
        for item in items:
            date_str = item.get("date", "")
            if date_str:
                try:
                    year = int(date_str[:4])
                    if year == year_val:
                        filtered.append(item)
                except (ValueError, IndexError):
                    pass
        return filtered

    # Filter for balance sheet (only selected year)
    exp_list_raw_filtered = filter_by_year(exp_list_raw, selected_year)
    exp_list_filtered = group_expenses_by_name(exp_list_raw_filtered)

    # Filter expenses if filter_expense parameter provided (apply to both raw and grouped lists)
    if filter_expense:
        exp_list_all = [e for e in exp_list_all if (e.get("expense_name", "") or e.get("description", "—")).lower() == filter_expense.lower()]
        # Also filter the grouped list for summary cards
        exp_list_filtered = [e for e in exp_list_filtered if (e.get("expense_name", "") or e.get("description", "—")).lower() == filter_expense.lower()]

    # For balance sheet, use filtered list
    exp_list = exp_list_filtered

    # Collect all unique vendors for dropdown
    all_vendors = sorted(set(e.get("vendor", "") for e in exp_list_all if e.get("vendor", "").strip()))

    rev_list = []
    if isinstance(revenue, dict):
        for rid, rdata in revenue.items():
            if isinstance(rdata, dict):
                # Check if the invoice still exists (not deleted)
                invoice_id = rdata.get("invoice_id")
                if invoice_id and invoice_id not in invoices:
                    # Skip deleted invoices - their revenue entries should not display
                    continue

                rdata["firebase_id"] = rid
                # Older entries (and ones written by the desktop app) only carry
                # 'amount'/'client' rather than 'amount_paid'/'total'/'client_name' —
                # normalize so the template can rely on a consistent field set.
                rdata.setdefault("amount_paid", rdata.get("amount", 0))
                rdata.setdefault("total", rdata.get("amount", 0))
                rdata.setdefault("client_name", rdata.get("client", ""))
                rdata.setdefault("status", "Paid")
                rdata.setdefault("tax_amount", rdata.get("tax_amount", 0))

                # Get linked projects and tax info from actual invoice
                if invoice_id and invoice_id in invoices:
                    inv_data = invoices[invoice_id]
                    if isinstance(inv_data, dict):
                        inv_meta = inv_data.get("meta", {}) or {}
                        # Get all linked projects for multi-project invoices
                        linked = _invoice_linked_projects(inv_data)
                        rdata["linked_projects"] = linked
                        # Update tax_amount and total from invoice meta
                        rdata["tax_amount"] = _safe_float(inv_meta.get("tax_amount", 0))
                        rdata["total"] = _safe_float(inv_meta.get("total", 0))

                rev_list.append(rdata)
    rev_list.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Filter to show only Paid and Partial invoices (present/active invoices only)
    # This matches the Invoicing tab display
    rev_list = [r for r in rev_list if r.get("status") in ["Paid", "Partial"]]

    # Enrich rev_list with current amount_paid from invoice meta (fixes stale revenue entries)
    updated_rev_list = []
    for r in rev_list:
        inv_id = r.get("invoice_id")
        if not inv_id or inv_id not in invoices:
            continue
        inv_data = invoices[inv_id]
        if not isinstance(inv_data, dict):
            continue
        inv_meta = inv_data.get("meta", {}) or {}
        inv_total = _safe_float(inv_meta.get("total", 0))
        amount_paid = _safe_float(inv_meta.get("amount_paid", 0))
        tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in (inv_data.get("tax_payments", []) or []))
        total_paid_for_inv = amount_paid + tax_paid

        r["amount_paid"] = amount_paid
        r["total"] = inv_total
        r["tax_amount"] = _safe_float(inv_meta.get("tax_amount", 0))

        # Calculate status based on total vs amount_paid for this P&L invoice
        if total_paid_for_inv >= (inv_total - 0.01):
            r["status"] = "Paid"
        elif total_paid_for_inv > 0:
            r["status"] = "Partial"
        else:
            r["status"] = "Unpaid"

        # Only include in P&L if invoice has been paid or is being tracked
        if r["status"] in ["Paid", "Partial", "Unpaid"]:
            updated_rev_list.append(r)
    rev_list = updated_rev_list

    # Helper to extract year from date string
    def _extract_year_from_date(date_str):
        """Extract year from date string"""
        try:
            return int(date_str[:4])
        except (ValueError, IndexError, TypeError):
            return None

    # Get selected year for stat cards filtering
    selected_year = request.args.get("year", str(datetime.now().year))
    try:
        stat_card_year = int(selected_year)
    except (ValueError, TypeError):
        stat_card_year = datetime.now().year

    # Total collected = amount_paid + tax_paid (matches Invoicing tab display)
    total_collected = 0.0
    for r in rev_list:
        if _extract_year_from_date(r.get("date", "")) == stat_card_year and r.get("invoice_id") in invoices:
            total_collected += _safe_float(r.get("amount_paid", 0))
            inv_id = r.get("invoice_id")
            if inv_id and inv_id in invoices:
                inv_data_r = invoices[inv_id]
                if isinstance(inv_data_r, dict):
                    tax_collected = sum(_safe_float(tp.get("amount", 0))
                                       for tp in (inv_data_r.get("tax_payments", []) or [])
                                       if _extract_year_from_date(tp.get("date", "")) == stat_card_year)
                    total_collected += tax_collected

    # Recalculate statuses based on actual payments
    for inv in inv_list:
        inv["meta"]["status"] = _calculate_invoice_status(inv)

    # Filter invoices by selected year for stat cards
    inv_list_filtered = [i for i in inv_list
                        if _extract_year_from_date(i.get("meta", {}).get("invoice_date", "")) == stat_card_year]

    total_invoiced    = sum(_safe_float(i.get("meta", {}).get("total", 0)) for i in inv_list_filtered)
    total_paid        = sum(_safe_float(i.get("meta", {}).get("amount_paid", 0)) for i in inv_list_filtered)
    # Include tax paid in total paid
    total_tax_paid    = sum(_safe_float(p.get("amount", 0)) for inv in inv_list_filtered for p in inv.get("tax_payments", []))
    total_paid        += total_tax_paid
    total_outstanding = total_invoiced - total_paid
    exp_list_year_filtered = [e for e in exp_list if _extract_year_from_date(e.get("date", "")) == stat_card_year]
    total_expenses    = sum(_safe_float(e.get("amount", 0)) for e in exp_list_year_filtered)
    exp_list_year_filtered_count = len(exp_list_year_filtered)
    net_profit        = total_paid - total_expenses

    # Monthly breakdown for chart (last 6 months)
    monthly_revenue  = {}
    monthly_expenses = {}
    for inv in inv_list:
        ds = inv.get("meta", {}).get("invoice_date", "") or ""
        try:
            key = datetime.fromisoformat(ds[:10]).strftime("%b %Y")
            line_paid = _safe_float(inv.get("meta", {}).get("amount_paid", 0))
            tax_paid = sum(_safe_float(p.get("amount", 0)) for p in inv.get("tax_payments", []))
            monthly_revenue[key] = monthly_revenue.get(key, 0) + line_paid + tax_paid
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

    # Annual breakdown for Balance Sheet (selected year or current year)
    selected_year = request.args.get("year", None)
    if selected_year:
        try:
            current_year = int(selected_year)
        except (ValueError, TypeError):
            current_year = _now.year
    else:
        current_year = _now.year
    selected_year = current_year
    annual_revenue = {i: 0.0 for i in range(1, 13)}  # Months 1-12
    annual_expenses = {i: 0.0 for i in range(1, 13)}

    for inv in inv_list:
        for pay in (inv.get("payment_log", []) or []):
            pay_ds = pay.get("date", "") or ""
            try:
                pay_date = datetime.fromisoformat(pay_ds[:10])
                if pay_date.year == current_year:
                    annual_revenue[pay_date.month] += _safe_float(pay.get("amount", 0))
            except Exception:
                pass
        for tax_pay in (inv.get("tax_payments", []) or []):
            tax_ds = tax_pay.get("date", "") or ""
            try:
                tax_date = datetime.fromisoformat(tax_ds[:10])
                if tax_date.year == current_year:
                    annual_revenue[tax_date.month] += _safe_float(tax_pay.get("amount", 0))
            except Exception:
                pass

    for exp in exp_list:
        ds = exp.get("date", "") or ""
        try:
            exp_date = datetime.fromisoformat(ds[:10])
            if exp_date.year == current_year:
                month = exp_date.month
                annual_expenses[month] += _safe_float(exp.get("amount", 0))
        except Exception:
            pass

    # Calculate annual net P/L per month
    annual_netpl = {i: annual_revenue[i] - annual_expenses[i] for i in range(1, 13)}

    # Labor cost (Employees module) — additive figures, do not affect total_expenses/net_profit above
    # Build uid→rate map from /users; Employee Directory rates override when names match
    _all_users        = _load_all_users()
    _dir_rate_by_name = {p.get("name", "").strip().lower(): _safe_float(p.get("hourly_rate", 0))
                         for p in _load_employee_profiles()
                         if _safe_float(p.get("hourly_rate", 0)) > 0}
    rate_by_uid: Dict[str, float] = {}
    for _u in _all_users:
        _uid   = _u.get("firebase_uid")
        _uname = (_u.get("name") or _u.get("display_name") or "").strip().lower()
        _rate  = _safe_float(_u.get("hourly_rate", 0))
        if _uid:
            rate_by_uid[_uid] = _dir_rate_by_name.get(_uname, _rate)
    labor_cost_by_project: Dict[str, float] = {}
    total_labor_cost = 0.0
    for e in _load_time_entries():
        if e.get("status") != "closed":
            continue
        minutes = _safe_float(e.get("duration_minutes", 0))
        cost = (minutes / 60.0) * rate_by_uid.get(e.get("employee_uid"), 0.0)
        total_labor_cost += cost
        pnum_e = e.get("project_number", "")
        if pnum_e:
            labor_cost_by_project[pnum_e] = labor_cost_by_project.get(pnum_e, 0.0) + cost
    net_profit_after_labor = net_profit - total_labor_cost

    # Per-project P&L
    projects_list = _load_projects_list()
    project_pnl = []
    for p in projects_list:
        pnum = p.get("project_number", "")

        # Calculate INVOICED and COLLECTED based on line items and payment_log (not equal split!)
        p_invoiced = 0
        p_collected = 0

        raw_inv = fb_get("/invoices") or {}
        if isinstance(raw_inv, dict):
            for inv_id, inv_data in raw_inv.items():
                if not isinstance(inv_data, dict):
                    continue
                if pnum not in _invoice_linked_projects(inv_data):
                    continue
                inv_meta = inv_data.get("meta", {}) or {}
                inv_subtotal = _safe_float(inv_meta.get("subtotal", 0))
                inv_tax = _safe_float(inv_meta.get("tax_amount", 0))

                # Calculate project's portion from actual line items
                line_items = inv_data.get("line_items", []) or []
                project_line_total = 0
                for item in line_items:
                    if isinstance(item, dict):
                        item_proj = str(item.get("project_number", "")).strip()
                        if item_proj == pnum:
                            project_line_total += _safe_float(item.get("amount", 0))

                # Get project's actual payments from payment_log (filtered by project_number)
                payment_log = inv_data.get("payment_log", []) or []
                project_payments = sum(_safe_float(p.get("amount", 0)) for p in payment_log if p.get("project_number", "") == pnum)

                # Calculate share based on line items (for invoiced amount calculation only)
                if inv_subtotal > 0 and project_line_total > 0:
                    share = project_line_total / inv_subtotal
                else:
                    # Fallback: use linked_projects metadata for invoiced tax allocation
                    linked = _invoice_linked_projects(inv_data)
                    if len(linked) > 1:
                        share = 1.0 / len(linked)
                    else:
                        share = 1.0

                # Project's tax allocation (proportional to share, for invoiced amount)
                project_tax = share * inv_tax

                # Get project's tax payments - allocate proportionally if not per-project
                tax_payments = inv_data.get("tax_payments", []) or []
                total_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments)

                # If tax_payments have project_number, filter by it; otherwise use share
                project_tax_paid = sum(_safe_float(tp.get("amount", 0)) for tp in tax_payments if tp.get("project_number") == pnum)
                if project_tax_paid == 0 and total_tax_paid > 0:
                    # Tax payments don't have project_number, allocate by share
                    project_tax_paid = share * total_tax_paid

                # Add to P&L: invoiced = line items + tax, collected = actual payments + actual tax paid
                p_invoiced += project_line_total + project_tax
                p_collected += project_payments + project_tax_paid

        p_contract = _safe_float(p.get("contract_value",0))
        p_not_invoiced = p_contract - p_invoiced
        p_expenses = sum(_safe_float(e.get("amount",0))                     for e in exp_list if e.get("project_number","") == pnum)
        p_gross_profit = p_collected - p_expenses
        p_labor_cost = labor_cost_by_project.get(pnum, 0.0)
        project_pnl.append({
            "project_number": pnum,
            "project_name":   p.get("project_name",""),
            "client_name":    p.get("client_name",""),
            "status":         p.get("status",""),
            "contract_value": p_contract,
            "invoiced":       p_invoiced,
            "not_invoiced":   p_not_invoiced,
            "paid":           p_collected,
            "expenses":       p_expenses,
            "gross_profit":   p_gross_profit,
            "labor_cost":     p_labor_cost,
            "net_profit":     p_gross_profit - p_labor_cost,
            "firebase_id":    p.get("firebase_id",""),
        })
    project_pnl.sort(key=lambda x: x["project_number"], reverse=True)

    # ── Monthly payment drill-down for Balance Sheet ──────────────────────────
    _proj_num_to_id = {p.get("project_number", ""): p.get("firebase_id", "") for p in projects_list}
    _proj_num_to_data = {p.get("project_number", ""): p for p in projects_list}
    monthly_payment_details = {str(i): [] for i in range(1, 13)}
    for _inv in inv_list:
        _inv_id   = _inv.get("firebase_id", "")
        _inv_meta = _inv.get("meta", {}) or {}
        _inv_num  = _inv_meta.get("invoice_number", "")
        _inv_total = _safe_float(_inv_meta.get("total", 0))
        for _pay in (_inv.get("payment_log", []) or []):
            _pay_ds = _pay.get("date", "") or ""
            try:
                _pay_dt = datetime.fromisoformat(_pay_ds[:10])
                if _pay_dt.year == current_year:
                    _mkey = str(_pay_dt.month)
                    _proj_num = _pay.get("project_number", "") or _inv_meta.get("project_number", "")
                    _stage = _pay.get("stage_name", "") or _inv_meta.get("payment_stage", "")

                    # If stage still empty, try to look it up from project payment_stages
                    if not _stage:
                        _stage_idx = _pay.get("stage_index")
                        if _stage_idx is None:
                            _stage_idx = _inv_meta.get("payment_stage_index")
                        if _stage_idx is not None:
                            try:
                                _stage_idx = int(_stage_idx) if not isinstance(_stage_idx, int) else _stage_idx
                                _proj_data = _proj_num_to_data.get(_proj_num, {})
                                _p_stages = _proj_data.get("payment_stages", [])
                                if isinstance(_p_stages, list) and 0 <= _stage_idx < len(_p_stages):
                                    _stage = _p_stages[_stage_idx].get("name", f"Stage {_stage_idx + 1}")
                            except (ValueError, TypeError, IndexError):
                                if _stage_idx is not None:
                                    try:
                                        _stage_idx = int(_stage_idx)
                                        _stage = f"Stage {_stage_idx + 1}"
                                    except (ValueError, TypeError):
                                        pass

                    # Final fallback: extract stage from invoice line items description
                    if not _stage:
                        for _li in (_inv.get("line_items", []) or []):
                            if not isinstance(_li, dict):
                                continue
                            _li_proj = _li.get("project_number", "")
                            if _li_proj and _li_proj != _proj_num:
                                continue
                            _li_desc = _li.get("description", "") or ""
                            if " — " in _li_desc:
                                _stage = _li_desc.split(" — ", 1)[1].strip()
                            elif _li_desc:
                                _stage = _li_desc
                            if _stage:
                                break

                    # If stage is generic "Stage N", upgrade to "Installment N of Total"
                    _stage_label = _stage or "—"
                    if _stage_label and re.match(r'^Stage\s+\d+$', _stage_label, re.IGNORECASE):
                        _proj_data_s = _proj_num_to_data.get(_proj_num, {})
                        _all_stages  = _proj_data_s.get("payment_stages", [])
                        if isinstance(_all_stages, list) and len(_all_stages) > 0:
                            try:
                                _snum = int(_stage_label.split()[-1])
                                if 1 <= _snum <= len(_all_stages):
                                    _sname = (_all_stages[_snum - 1].get("name", "") or "").strip()
                                    _stage_label = _sname if _sname else f"Installment {_snum} of {len(_all_stages)}"
                                else:
                                    _stage_label = f"Installment {_snum} of {len(_all_stages)}"
                            except (ValueError, TypeError):
                                pass

                    monthly_payment_details[_mkey].append({
                        "project_number": _proj_num,
                        "project_id":     _proj_num_to_id.get(_proj_num, ""),
                        "invoice_id":     _inv_id,
                        "invoice_number": _inv_num,
                        "stage":          _stage_label,
                        "total_amount":   _inv_total,
                        "paid_amount":    _safe_float(_pay.get("amount", 0)),
                        "paid_date":      _pay_ds,
                    })
            except Exception:
                pass
        for _tpay in (_inv.get("tax_payments", []) or []):
            _tpay_ds = _tpay.get("date", "") or ""
            try:
                _tpay_dt = datetime.fromisoformat(_tpay_ds[:10])
                if _tpay_dt.year == current_year:
                    monthly_payment_details[str(_tpay_dt.month)].append({
                        "project_number": "TAX",
                        "project_id":     "",
                        "invoice_id":     _inv_id,
                        "invoice_number": _inv_num,
                        "stage":          "Tax Payment",
                        "total_amount":   _safe_float(_inv_meta.get("tax_amount", 0)),
                        "paid_amount":    _safe_float(_tpay.get("amount", 0)),
                        "paid_date":      _tpay_ds,
                    })
            except Exception:
                pass
    # Merge multiple partial payments for the same invoice+project into one row
    for _mk in monthly_payment_details:
        _merged: dict = {}
        for _row in monthly_payment_details[_mk]:
            _key = (_row["invoice_id"], _row["project_number"])
            if _key in _merged:
                _merged[_key]["paid_amount"] += _row["paid_amount"]
                # keep latest payment date
                if _row["paid_date"] > _merged[_key]["paid_date"]:
                    _merged[_key]["paid_date"] = _row["paid_date"]
            else:
                _merged[_key] = dict(_row)
        monthly_payment_details[_mk] = sorted(_merged.values(), key=lambda x: x.get("paid_date", ""))

    # ── Chart data for overview pie charts ────────────────────────────────────
    inv_status_counts = {}
    for i in inv_list:
        st = i.get("meta", {}).get("status") or "Draft"
        inv_status_counts[st] = inv_status_counts.get(st, 0) + 1

    exp_cats = {}
    for e in exp_list:
        cat = e.get("category", "Other") or "Other"
        exp_cats[cat] = exp_cats.get(cat, 0) + _safe_float(e.get("amount", 0))

    # Load salaries data for Balance Sheet
    salaries = fb_get("/balance_sheet_salary") or {}
    salaries_domestic_raw = []
    salaries_international_raw = []
    total_salaries = 0.0

    if isinstance(salaries, dict):
        for sid, sdata in salaries.items():
            if isinstance(sdata, dict):
                sdata["firebase_id"] = sid
                sal_amount = _safe_float(sdata.get("amount", 0))
                total_salaries += sal_amount
                region = sdata.get("region", "").lower()
                if "international" in region or "outside" in region:
                    salaries_international_raw.append(sdata)
                else:
                    salaries_domestic_raw.append(sdata)

    # Filter salaries by selected year (must recompute total_salaries AFTER filtering)
    salaries_domestic_raw = filter_by_year(salaries_domestic_raw, selected_year)
    salaries_international_raw = filter_by_year(salaries_international_raw, selected_year)
    total_salaries = sum(_safe_float(s.get("amount", 0)) for s in salaries_domestic_raw + salaries_international_raw)

    # Group salaries by name, sum amounts, track latest date; sort by date desc
    def group_by_name(items, entries_tracking=None):
        grouped = {}
        if entries_tracking is None:
            entries_tracking = {}
        for item in items:
            name = item.get("employee_name") or item.get("name", "—")
            amount = _safe_float(item.get("amount", 0))
            date = item.get("date", "")
            if name not in grouped:
                grouped[name] = {"name": name, "amount": 0, "date": date}
                entries_tracking[name] = []
            else:
                if date > grouped[name].get("date", ""):
                    grouped[name]["date"] = date
            grouped[name]["amount"] += amount
            entries_tracking[name].append({
                "date": date,
                "amount": amount,
                "notes": item.get("notes", "")
            })
        return sorted(grouped.values(), key=lambda x: x.get("date", ""), reverse=True), entries_tracking

    salary_entries_domestic = {}
    salary_entries_international = {}
    salaries_domestic, salary_entries_domestic = group_by_name(salaries_domestic_raw, salary_entries_domestic)
    salaries_international, salary_entries_international = group_by_name(salaries_international_raw, salary_entries_international)

    # ── Monthly salary details for drill-down (needs salaries_domestic/international) ──
    monthly_salary_details = {str(i): [] for i in range(1, 13)}
    for _sal in list(salaries_domestic) + list(salaries_international):
        _ds = (_sal.get("date") or "")[:10]
        try:
            _d = datetime.fromisoformat(_ds)
            if _d.year == current_year:
                monthly_salary_details[str(_d.month)].append({
                    "name":   _sal.get("name") or "—",
                    "region": "Inside America" if _sal in salaries_domestic else "Outside America",
                    "amount": _safe_float(_sal.get("amount", 0)),
                    "date":   _ds,
                })
        except Exception:
            pass

    # Calculate totals for Balance Sheet
    total_revenue = total_paid

    # Load custom expense categories from Firebase
    custom_categories = fb_get("/custom_categories") or {}
    expense_types = custom_categories.get("expense_type", []) if isinstance(custom_categories.get("expense_type"), list) else []
    categories_by_type = custom_categories.get("Categories", {}) if isinstance(custom_categories.get("Categories"), dict) else {}
    expense_names_by_category = custom_categories.get("expense_names", {}) if isinstance(custom_categories.get("expense_names"), dict) else {}

    # Provide default values if empty (matching reference structure)
    if not expense_types:
        expense_types = [
            "O & M (Operations & Maintenance)",
            "Capital Expenses",
            "Other Expenses"
        ]

    if not categories_by_type:
        categories_by_type = {
            "O & M (Operations & Maintenance)": [
                "Facilities & Utilities",
                "Office & Admin Overhead",
                "Engineering Software & IT",
                "Salaries, Labor & Related Costs",
                "Professional Services",
                "Insurance & Compliance",
                "Travel, Site Visits & Vehicles",
                "Marketing & Business Development",
                "Training, Licensure & Development",
                "Safety & Field Supplies",
                "Miscellaneous O & M"
            ],
            "Capital Expenses": [
                "Computer & Office Equipment",
                "Field & Inspection Equipment",
                "Furniture & Fixtures",
                "Vehicles",
                "Software (Capitalized)",
                "Leasehold Improvements",
                "Accumulated Depreciation"
            ],
            "Other Expenses": [
                "Salary/Bonuses",
                "Tax Expenses/Tax Deductions",
                "Medical/Benefits",
                "Meals & Entertainment",
                "Donations",
                "Bank Charges",
                "Contingency Funds",
                "Unexpected Costs"
            ]
        }

    if not expense_names_by_category:
        expense_names_by_category = {
            "Facilities & Utilities": ["Office rent or co-working space fees","Utilities (electricity, water, gas)","Internet service","Trash & cleaning services","Property taxes (for office, if applicable)","Office repairs & maintenance (HVAC, lights, minor repairs)"],
            "Office & Admin Overhead": ["Office supplies (paper, pens, notebooks, printer ink)","Printer/plotter maintenance & paper","Postage & shipping (documents, contracts, samples)","Bank fees & merchant processing fees","Software: Microsoft 365 / Google Workspace","Software: PDF tools (Bluebeam, Adobe, etc.)","Software: Password manager","Software: Others","Cloud storage (Dropbox, Google Drive, OneDrive)"],
            "Engineering Software & IT": ["Engineering software: SAP2000 / ETABS / STAAD / RAM / RISA","Engineering software: Others","CAD/BIM tools: AutoCAD, Civil 3D, Revit","License/maintenance fees for all software","IT support services","Computer maintenance & small repairs","Antivirus, backup services, security tools"],
            "Salaries, Labor & Related Costs": ["Owner draw/salary","Employee salaries & wages","Overtime or temporary staff","Payroll taxes paid by the company","Employee benefits: Health insurance","Employee benefits: Retirement plan contributions","Employee benefits: Paid time off costs","Payments to subcontract engineers, drafters"],
            "Professional Services": ["Accounting & bookkeeping fees","Tax preparation and consulting","Legal services (contracts, company setup)","Business consulting or coaching services","Registered agent fees (if applicable)"],
            "Insurance & Compliance": ["Professional liability / Errors & Omissions (E&O) insurance","General liability insurance","Business owner's policy (BOP)","Workers' comp insurance","Commercial auto insurance","License renewals (PE license, SE license)","Business license renewals","Memberships"],
            "Travel, Site Visits & Vehicles": ["Mileage (personal vehicle for business)","Fuel costs (company vehicles)","Parking fees & tolls","Vehicle maintenance","Airfare, hotels for out-of-town site visits","Rental cars or rideshare for business trips","Meals while traveling for business"],
            "Marketing & Business Development": ["Website hosting and domain expenses","Website maintenance & updates","Graphic design (logo, templates, brochures)","Online ads (Google, LinkedIn, Facebook)","Printing of business cards, brochures, banners","Sponsorships of events","Client entertainment (dinners, coffee meetings)"],
            "Training, Licensure & Development": ["Continuing education (PDH hours, webinars)","Training courses (technical or business)","Books, codes, and standards","Exam fees for additional licenses"],
            "Safety & Field Supplies": ["PPE: hard hats, safety vests, glasses, gloves, boots","Field tools for inspections","Calibration of field instruments","First-aid kits and safety equipment"],
            "Miscellaneous O & M": ["Subscriptions: LinkedIn Premium","Subscriptions: Industry journals","Project management tools","Document management tools or e-signature services"],
            "Computer & Office Equipment": ["Laptops","Desktops","Monitors","Printers/Scanners","Servers","Networking Equipment"],
            "Field & Inspection Equipment": ["Survey Equipment","Testing Equipment","Measurement Tools","Safety Equipment","Inspection Devices"],
            "Furniture & Fixtures": ["Office Desks","Chairs","Filing Cabinets","Shelving Units","Conference Room Furniture"],
            "Vehicles": ["Company Cars","Trucks","Vans","Heavy Equipment","Vehicle Accessories"],
            "Software (Capitalized)": ["Engineering Software License","ERP System","CRM System","Database Software","Custom Software Development"],
            "Leasehold Improvements": ["Office Renovations","Electrical Work","Plumbing Improvements","HVAC Installation","Security Systems"],
            "Accumulated Depreciation": ["Depreciation Expense - Computers","Depreciation Expense - Office Equipment","Depreciation Expense - Vehicles","Accumulated Depreciation"],
            "Salary/Bonuses": ["Employee Salary","Manager Salary","Executive Salary","Performance Bonus","Year-end Bonus","Commission Payments","Incentive Payments"],
            "Tax Expenses/Tax Deductions": ["Federal Income Tax","Tax Deduction","Payroll Tax","Sales Tax","Property Tax","Business Tax"],
            "Medical/Benefits": ["Health Insurance Premiums","Dental Insurance","Vision Insurance","Retirement Contributions","Life Insurance","Disability Insurance","Wellness Programs"],
            "Meals & Entertainment": ["Client Meals","Business Lunches","Team Dinners","Conference Meals","Entertainment Expenses","Team Building Events"],
            "Donations": ["Charitable Donations","Community Sponsorships","Educational Donations","Non-profit Contributions","Event Sponsorships"],
            "Bank Charges": ["Monthly Account Fees","Transaction Fees","Wire Transfer Fees","Credit Card Processing Fees","Check Printing Fees","Overdraft Fees"],
            "Contingency Funds": ["Emergency Funds","Reserve Funds","Project Contingency","Operational Reserve","Risk Management Fund"],
            "Unexpected Costs": ["Emergency Repairs","Unplanned Maintenance","Price Increases","Regulatory Changes","Market Fluctuations"]
        }

    # Flat list of all categories for expense filter dropdown
    all_categories = []
    for cats in categories_by_type.values():
        for cat in cats:
            if cat not in all_categories:
                all_categories.append(cat)

    # exp_list is already grouped by group_expenses_by_name(), use it directly
    # Build expense_entries_by_name for drill-down from raw filtered data
    expense_entries_by_name = {}
    for e in exp_list_raw_filtered:
        name = e.get("expense_name", "") or e.get("description", "—") or "—"
        if name not in expense_entries_by_name:
            expense_entries_by_name[name] = []
        expense_entries_by_name[name].append({
            "date": e.get("date", ""),
            "amount": _safe_float(e.get("amount", 0)),
            "category": e.get("category", ""),
            "vendor": e.get("vendor", ""),
            "notes": e.get("notes", "")
        })
    # Use the already-grouped exp_list as expenses_grouped, sorted by date
    expenses_grouped = sorted(exp_list, key=lambda x: x.get("date", ""), reverse=True)

    # Get list of available years from invoices and expenses
    available_years = set()
    for inv in inv_list:
        ds = inv.get("meta", {}).get("invoice_date", "") or ""
        try:
            year = datetime.fromisoformat(ds[:10]).year
            available_years.add(year)
        except Exception:
            pass
    for exp in exp_list:
        ds = exp.get("date", "") or ""
        try:
            year = datetime.fromisoformat(ds[:10]).year
            available_years.add(year)
        except Exception:
            pass

    # Add a broader range of years (past 15 years + future 10 years)
    _real_now_year = _now.year
    for year in range(_real_now_year - 15, _real_now_year + 11):
        available_years.add(year)

    available_years = sorted(list(available_years), reverse=True)

    # ── Accounts Receivable Aging ─────────────────────────────────────────────
    today_d = datetime.now().date()
    aging_buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90plus": []}
    for inv in inv_list:
        m = inv.get("meta", {}) or {}
        status = m.get("status", "Draft")
        if status not in ("Sent", "Viewed", "Partial", "Overdue"):
            continue
        total   = _safe_float(m.get("total", 0))
        paid    = _safe_float(m.get("amount_paid", 0))
        balance = total - paid
        if balance <= 0.01:
            continue
        due_str = m.get("due_date", "")
        try:
            due_d = datetime.fromisoformat(due_str[:10]).date()
            days_overdue = (today_d - due_d).days
        except Exception:
            days_overdue = 0
        entry = {
            "invoice_number": m.get("invoice_number", ""),
            "client_name":    m.get("client_name", ""),
            "invoice_date":   m.get("invoice_date", ""),
            "due_date":       due_str,
            "net_terms":      m.get("net_terms", ""),
            "days_overdue":   days_overdue,
            "balance":        balance,
            "status":         status,
            "firebase_id":    inv.get("firebase_id", ""),
        }
        if days_overdue <= 0:
            aging_buckets["current"].append(entry)
        elif days_overdue <= 30:
            aging_buckets["1_30"].append(entry)
        elif days_overdue <= 60:
            aging_buckets["31_60"].append(entry)
        elif days_overdue <= 90:
            aging_buckets["61_90"].append(entry)
        else:
            aging_buckets["90plus"].append(entry)

    aging_totals = {k: sum(e["balance"] for e in v) for k, v in aging_buckets.items()}
    aging_total_outstanding = sum(aging_totals.values())

    # ── Year-filtered A/R for Balance Sheet (only invoices from selected_year) ──
    bs_aging_buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90plus": []}
    for _inv in inv_list:
        _m = _inv.get("meta", {}) or {}
        _inv_date = _m.get("invoice_date", "") or ""
        try:
            if int(_inv_date[:4]) != current_year:
                continue
        except (ValueError, TypeError):
            continue
        _status = _m.get("status", "Draft")
        if _status not in ("Sent", "Viewed", "Partial", "Overdue"):
            continue
        _balance = _safe_float(_m.get("total", 0)) - _safe_float(_m.get("amount_paid", 0))
        if _balance <= 0.01:
            continue
        _due_str = _m.get("due_date", "")
        try:
            _days_ov = (today_d - datetime.fromisoformat(_due_str[:10]).date()).days
        except Exception:
            _days_ov = 0
        _entry = {
            "invoice_number": _m.get("invoice_number", ""),
            "client_name":    _m.get("client_name", ""),
            "invoice_date":   _inv_date,
            "due_date":       _due_str,
            "net_terms":      _m.get("net_terms", ""),
            "days_overdue":   _days_ov,
            "balance":        _balance,
            "status":         _status,
            "firebase_id":    _inv.get("firebase_id", ""),
        }
        if _days_ov <= 0:       bs_aging_buckets["current"].append(_entry)
        elif _days_ov <= 30:    bs_aging_buckets["1_30"].append(_entry)
        elif _days_ov <= 60:    bs_aging_buckets["31_60"].append(_entry)
        elif _days_ov <= 90:    bs_aging_buckets["61_90"].append(_entry)
        else:                   bs_aging_buckets["90plus"].append(_entry)
    bs_aging_totals = {k: sum(e["balance"] for e in v) for k, v in bs_aging_buckets.items()}
    bs_aging_total_outstanding = sum(bs_aging_totals.values())

    # ── Monthly drill-down detail blocks (needs aging_buckets + salaries_domestic) ──
    monthly_expense_details = {str(i): [] for i in range(1, 13)}
    for _exp in exp_list_all:
        _ds = (_exp.get("date") or "")[:10]
        try:
            _d = datetime.fromisoformat(_ds)
            if _d.year == current_year:
                monthly_expense_details[str(_d.month)].append({
                    "name":     _exp.get("expense_name") or _exp.get("description") or "—",
                    "category": _exp.get("category") or _exp.get("expense_type") or "—",
                    "amount":   _safe_float(_exp.get("amount", 0)),
                    "date":     _ds,
                })
        except Exception:
            pass

    # Group outstanding by invoice_date month (invoices issued that month)
    monthly_outstanding_details = {str(i): [] for i in range(1, 13)}
    # Group outstanding by due_date month (invoices DUE that month)
    monthly_due_details = {str(i): [] for i in range(1, 13)}
    for _bucket in aging_buckets.values():
        for _entry in _bucket:
            # By invoice date
            _ds = (_entry.get("invoice_date") or "")[:10]
            try:
                _d = datetime.fromisoformat(_ds)
                if _d.year == current_year:
                    monthly_outstanding_details[str(_d.month)].append(_entry)
            except Exception:
                pass
            # By due date
            _ds2 = (_entry.get("due_date") or "")[:10]
            try:
                _d2 = datetime.fromisoformat(_ds2)
                if _d2.year == current_year:
                    monthly_due_details[str(_d2.month)].append(_entry)
            except Exception:
                pass

    today_date = datetime.now().strftime("%Y-%m-%d")
    active_tab = request.args.get("tab", "overview")
    return render_template("financial.html",
        total_invoiced=total_invoiced,
        total_paid=total_paid,
        total_outstanding=total_outstanding,
        total_expenses=total_expenses,
        exp_list_year_filtered_count=exp_list_year_filtered_count,
        total_revenue=total_revenue,
        total_salaries=total_salaries,
        net_profit=net_profit,
        total_labor_cost=total_labor_cost,
        net_profit_after_labor=net_profit_after_labor,
        chart_labels=json.dumps(all_months),
        chart_revenue=json.dumps(rev_data),
        chart_expenses=json.dumps(exp_data),
        annual_revenue=annual_revenue,
        annual_expenses=annual_expenses,
        annual_netpl=annual_netpl,
        expenses=exp_list_all,
        expenses_filtered=exp_list,
        filter_expense=filter_expense,
        selected_year=selected_year,
        rev_list=rev_list,
        total_collected=total_collected,
        projects=projects_list,
        project_pnl=project_pnl,
        salaries_domestic=salaries_domestic,
        salaries_international=salaries_international,
        salary_entries_domestic=json.dumps(salary_entries_domestic),
        salary_entries_international=json.dumps(salary_entries_international),
        available_years=available_years,
        expense_types=expense_types,
        all_categories=all_categories,
        expenses_grouped=expenses_grouped,
        expense_entries=json.dumps(expense_entries_by_name),
        categories_by_type=json.dumps(categories_by_type),
        expense_names_by_category=json.dumps(expense_names_by_category),
        all_vendors=all_vendors,
        today_date=today_date,
        active_tab=active_tab,
        inv_status_labels=json.dumps(list(inv_status_counts.keys())),
        inv_status_data=json.dumps(list(inv_status_counts.values())),
        exp_cat_labels=json.dumps(list(exp_cats.keys())),
        exp_cat_data=json.dumps(list(exp_cats.values())),
        ai_enabled=bool(_get_ai_client()),
        monthly_payment_details=json.dumps(monthly_payment_details),
        monthly_expense_details=json.dumps(monthly_expense_details),
        monthly_salary_details=json.dumps(monthly_salary_details),
        monthly_outstanding_details=json.dumps(monthly_outstanding_details),
        monthly_due_details=json.dumps(monthly_due_details),
        aging_buckets=aging_buckets,
        aging_totals=aging_totals,
        aging_total_outstanding=aging_total_outstanding,
        bs_aging_buckets=bs_aging_buckets,
        bs_aging_totals=bs_aging_totals,
        bs_aging_total_outstanding=bs_aging_total_outstanding,
    )

@app.route("/financial/expense/new", methods=["POST"])
@role_required("financial")
def expense_new():
    data = {
        "expense_type":   request.form.get("expense_type", ""),
        "expense_name":   request.form.get("expense_name", ""),
        "description":    request.form.get("description", "") or request.form.get("expense_name", ""),
        "amount":         request.form.get("amount", "0"),
        "category":       request.form.get("category", ""),
        "date":           request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
        "vendor":         request.form.get("vendor", ""),
        "project_number": request.form.get("project_number", ""),
        "notes":          request.form.get("notes", ""),
        "created_by":     session.get("user_email", ""),
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }
    # Handle receipt upload (base64 encoding)
    if 'receipt' in request.files:
        file = request.files['receipt']
        if file and file.filename:
            try:
                file_content = file.read()
                base64_content = base64.b64encode(file_content).decode('utf-8')
                data['receipt_base64'] = base64_content
                data['receipt_filename'] = file.filename
                data['receipt_type'] = file.content_type
            except Exception as e:
                app.logger.error(f"Receipt upload error: {e}")
    # Save to both locations: main /expenses and /balance_sheet_expenses for backwards compatibility
    exp_id = fb_push("/expenses", data)
    fb_push("/balance_sheet_expenses", {**data, "firebase_id": exp_id})
    return jsonify({"success": True, "expense_id": exp_id})

@app.route("/financial/expense/<exp_id>/delete", methods=["POST"])
@role_required("financial")
def expense_delete(exp_id):
    fb_delete(f"/balance_sheet_expenses/{exp_id}")
    flash("Expense deleted.", "success")
    return redirect(url_for("financial", tab="expenses"))

@app.route("/financial/expense/<exp_id>/remove-receipt", methods=["POST"])
@role_required("financial")
def remove_expense_receipt(exp_id):
    try:
        exp_data = fb_get(f"/balance_sheet_expenses/{exp_id}") or {}
        if isinstance(exp_data, dict):
            exp_data.pop("receipt_base64", None)
            exp_data.pop("receipt_filename", None)
            exp_data.pop("receipt_type", None)
            fb_update(f"/balance_sheet_expenses/{exp_id}", {
                "receipt_base64": "",
                "receipt_filename": "",
                "receipt_type": ""
            })
            return jsonify({"success": True})
        return jsonify({"success": False}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/financial/expense/<exp_id>/edit", methods=["POST"])
@role_required("financial")
def expense_edit(exp_id):
    try:
        data = {
            "expense_type":   request.form.get("expense_type", ""),
            "expense_name":   request.form.get("expense_name", ""),
            "description":    request.form.get("description", "") or request.form.get("expense_name", ""),
            "amount":         request.form.get("amount", "0"),
            "category":       request.form.get("category", ""),
            "date":           request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
            "vendor":         request.form.get("vendor", ""),
            "project_number": request.form.get("project_number", ""),
            "notes":          request.form.get("notes", ""),
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }
        if 'receipt' in request.files:
            file = request.files['receipt']
            if file and file.filename:
                try:
                    file_content = file.read()
                    data['receipt_base64'] = base64.b64encode(file_content).decode('utf-8')
                    data['receipt_filename'] = file.filename
                    data['receipt_type'] = file.content_type
                except Exception as e:
                    app.logger.error(f"Receipt upload error: {e}")
        fb_update(f"/balance_sheet_expenses/{exp_id}", data)
        return jsonify({"success": True, "expense_id": exp_id})
    except Exception as e:
        app.logger.error(f"Expense edit error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/expense/<exp_id>/receipt", methods=["GET"])
@role_required("financial")
def get_expense_receipt(exp_id):
    """Retrieve receipt from Firebase"""
    expenses = fb_get("/balance_sheet_expenses") or {}
    if isinstance(expenses, dict) and exp_id in expenses:
        exp = expenses[exp_id]
        if isinstance(exp, dict) and 'receipt_base64' in exp:
            return jsonify({
                "success": True,
                "receipt": exp.get('receipt_base64'),
                "fileType": exp.get('receipt_type', 'image/jpeg'),
                "filename": exp.get('receipt_filename', 'receipt')
            })
    return jsonify({"success": False, "error": "Receipt not found"})

@app.route("/export/balance-sheet", methods=["GET"])
@role_required("financial")
def export_balance_sheet():
    """Export Balance Sheet to Excel - PIMS Format"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.worksheet.pagebreak import Break
        from io import BytesIO

        year_param = request.args.get("year", str(datetime.now().year))
        try:
            year = int(year_param)
        except (ValueError, TypeError):
            year = datetime.now().year

        # Get financial data
        invoices_data = fb_get("/invoices") or {}
        expenses_data = fb_get("/balance_sheet_expenses") or {}
        salaries_data = fb_get("/balance_sheet_salary") or {}

        # Calculate monthly data
        monthly_revenue = [0] * 12
        monthly_expenses = [0] * 12
        salary_inside = {}
        salary_outside = {}
        expense_breakdown = {}

        # Build revenue data from invoices based on PAYMENT DATES (not invoice dates)
        if isinstance(invoices_data, dict):
            for iid, inv_data in invoices_data.items():
                if isinstance(inv_data, dict):
                    for pay in (inv_data.get("payment_log", []) or []):
                        pay_ds = pay.get("date", "") or ""
                        try:
                            pay_date = datetime.fromisoformat(pay_ds[:10])
                            if pay_date.year == year:
                                monthly_revenue[pay_date.month - 1] += _safe_float(pay.get("amount", 0))
                        except Exception:
                            pass
                    for tax_pay in (inv_data.get("tax_payments", []) or []):
                        tax_ds = tax_pay.get("date", "") or ""
                        try:
                            tax_date = datetime.fromisoformat(tax_ds[:10])
                            if tax_date.year == year:
                                monthly_revenue[tax_date.month - 1] += _safe_float(tax_pay.get("amount", 0))
                        except Exception:
                            pass

        # Build expense data
        if isinstance(expenses_data, dict):
            for eid, edata in expenses_data.items():
                if isinstance(edata, dict):
                    date_str = edata.get("date", "")
                    try:
                        e_year = int(date_str[:4])
                        e_month = int(date_str[5:7])
                        if e_year == year and 1 <= e_month <= 12:
                            amt = _safe_float(edata.get("amount", 0))
                            monthly_expenses[e_month-1] += amt
                            exp_name = edata.get("expense_name", "") or edata.get("description", "—")
                            expense_breakdown[exp_name] = expense_breakdown.get(exp_name, 0) + amt
                    except (ValueError, IndexError):
                        pass

        # Build salary data
        if isinstance(salaries_data, dict):
            for salary_id, sal_data in salaries_data.items():
                if isinstance(sal_data, dict):
                    date_str = sal_data.get("date", "")
                    try:
                        s_year = int(date_str[:4])
                        if s_year == year:
                            name = sal_data.get("name") or sal_data.get("employee_name", "—")
                            amt = _safe_float(sal_data.get("amount", 0))
                            region = sal_data.get("region", "").lower()
                            target_dict = salary_inside if "inside" in region or "usa" in region else salary_outside
                            target_dict[name] = target_dict.get(name, 0) + amt
                    except (ValueError, IndexError, TypeError):
                        pass

        total_revenue = sum(monthly_revenue)
        total_expenses = sum(monthly_expenses)
        total_salaries = sum(salary_inside.values()) + sum(salary_outside.values())
        net_profit = total_revenue - total_expenses

        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Annual Summary"

        # Hide gridlines
        ws.sheet_view.showGridLines = False

        # Set page break and print area
        ws.row_breaks.append(Break(id=35))
        ws.print_area = 'A1:O68'
        ws.print_title_rows = '1:5'

        # Professional colors matching PIMS
        dark_blue_fill = PatternFill(start_color="FF1F4E79", end_color="FF1F4E79", fill_type="solid")
        light_blue_fill = PatternFill(start_color="FFD9E1F2", end_color="FFD9E1F2", fill_type="solid")
        light_gray_fill = PatternFill(start_color="FFF2F2F2", end_color="FFF2F2F2", fill_type="solid")
        white_fill = PatternFill(start_color="FFFFFFFF", end_color="FFFFFFFF", fill_type="solid")
        green_fill = PatternFill(start_color="FFC6EFCE", end_color="FFC6EFCE", fill_type="solid")

        # Fonts
        title_font = Font(name='Calibri', size=24, bold=True, color="FF1F4E79")
        subtitle_font = Font(name='Calibri', size=16, bold=True, color="FF1F4E79")
        header_font = Font(name='Calibri', size=12, bold=True, color="FFFFFFFF")
        bold_font = Font(name='Calibri', size=10, bold=True)
        normal_font = Font(name='Calibri', size=10)

        # Alignments
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left_align = Alignment(horizontal="left", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")

        # Borders
        thin_border = Border(
            left=Side(style='thin', color='FF000000'),
            right=Side(style='thin', color='FF000000'),
            top=Side(style='thin', color='FF000000'),
            bottom=Side(style='thin', color='FF000000')
        )

        # Column widths
        ws.column_dimensions['A'].width = 2
        ws.column_dimensions['B'].width = 15
        for col in ['C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']:
            ws.column_dimensions[col].width = 12
        ws.column_dimensions['O'].width = 18

        # PAGE 1 - ANNUAL FINANCIAL SUMMARY
        # Add top spacing
        ws.row_dimensions[1].height = 15
        ws.row_dimensions[2].height = 30

        ws.merge_cells('B2:O2')
        title = ws['B2']
        title.value = "MABS ENGINEERING LLC"
        title.font = title_font
        title.alignment = center_align
        title.fill = white_fill

        ws.row_dimensions[3].height = 10
        ws.row_dimensions[4].height = 10

        ws.merge_cells('B5:O5')
        subtitle = ws['B5']
        subtitle.value = f"ANNUAL FINANCIAL SUMMARY - {year}"
        subtitle.font = subtitle_font
        subtitle.alignment = center_align
        subtitle.fill = white_fill

        # Month headers
        ws['B12'] = "Months"
        ws['B12'].font = header_font
        ws['B12'].fill = dark_blue_fill
        ws['B12'].alignment = center_align
        ws['B12'].border = thin_border

        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        for i, month in enumerate(months, 3):
            cell = ws.cell(row=12, column=i, value=month)
            cell.font = header_font
            cell.fill = dark_blue_fill
            cell.alignment = center_align
            cell.border = thin_border

        # Revenue row
        ws['B13'] = "Revenue"
        ws['B13'].font = bold_font
        ws['B13'].fill = light_gray_fill
        ws['B13'].alignment = center_align
        ws['B13'].border = thin_border

        for i, val in enumerate(monthly_revenue, 3):
            cell = ws.cell(row=13, column=i, value=val)
            cell.number_format = '"$"#,##0.00'
            cell.alignment = center_align
            cell.border = thin_border
            cell.font = normal_font

        # Expense row
        ws['B14'] = "Expense"
        ws['B14'].font = bold_font
        ws['B14'].fill = light_gray_fill
        ws['B14'].alignment = center_align
        ws['B14'].border = thin_border

        for i, val in enumerate(monthly_expenses, 3):
            cell = ws.cell(row=14, column=i, value=val)
            cell.number_format = '"$"#,##0.00'
            cell.alignment = center_align
            cell.border = thin_border
            cell.font = normal_font

        # Summary section
        ws['G20'] = "Revenue"
        ws['G20'].font = bold_font
        ws['H20'] = "="
        ws['H20'].font = bold_font
        ws['H20'].alignment = center_align
        ws.merge_cells('I20:J20')
        ws['I20'].value = total_revenue
        ws['I20'].number_format = '"$"#,##0.00'
        ws['I20'].font = bold_font
        ws['I20'].alignment = left_align

        ws['G21'] = "Total Expense"
        ws['G21'].font = bold_font
        ws['H21'] = "="
        ws['H21'].font = bold_font
        ws['H21'].alignment = center_align
        ws.merge_cells('I21:J21')
        ws['I21'].value = total_expenses
        ws['I21'].number_format = '"$"#,##0.00'
        ws['I21'].font = bold_font
        ws['I21'].alignment = left_align

        ws['G22'] = "Net Profit"
        ws['G22'].font = bold_font
        ws['H22'] = "="
        ws['H22'].font = bold_font
        ws['H22'].alignment = center_align
        ws.merge_cells('I22:J22')
        ws['I22'].value = net_profit
        ws['I22'].number_format = '"$"#,##0.00'
        ws['I22'].font = bold_font
        ws['I22'].fill = green_fill if net_profit > 0 else light_gray_fill
        ws['I22'].alignment = left_align

        ws['H34'] = "Page : 01"
        ws['H34'].font = Font(size=10, italic=True)
        ws['H34'].alignment = right_align

        for row in range(1, 35):
            for col in range(1, 16):
                if ws.cell(row=row, column=col).value is None:
                    ws.cell(row=row, column=col).fill = white_fill

        # PAGE 2 - SALARY & EXPENSE BREAKDOWN
        start_row = 35

        # Salary title
        ws.merge_cells(f"B{start_row}:E{start_row}")
        ws[f"B{start_row}"].value = "SALARY"
        ws[f"B{start_row}"].font = Font(name='Calibri', size=14, bold=True)
        ws[f"B{start_row}"].alignment = center_align

        # Inside America
        row = start_row + 2
        ws.merge_cells(f"B{row}:E{row}")
        ws[f"B{row}"].value = "Inside America"
        ws[f"B{row}"].fill = light_blue_fill
        ws[f"B{row}"].font = bold_font
        ws[f"B{row}"].alignment = center_align
        for col in range(2, 6):
            ws.cell(row, col).border = thin_border

        row += 1
        ws.merge_cells(f"B{row}:C{row}")
        ws[f"B{row}"].value = "Emp. Nm"
        ws[f"B{row}"].font = bold_font
        ws[f"B{row}"].fill = light_gray_fill
        ws[f"B{row}"].alignment = center_align

        ws.merge_cells(f"D{row}:E{row}")
        ws[f"D{row}"].value = "Amount"
        ws[f"D{row}"].font = bold_font
        ws[f"D{row}"].fill = light_gray_fill
        ws[f"D{row}"].alignment = center_align

        for col in range(2, 6):
            ws.cell(row, col).border = thin_border

        row += 1
        total_inside = 0
        for name in sorted(salary_inside.keys()):
            amt = salary_inside[name]
            ws.merge_cells(f"B{row}:C{row}")
            ws[f"B{row}"].value = name
            ws[f"B{row}"].alignment = left_align

            ws.merge_cells(f"D{row}:E{row}")
            ws[f"D{row}"].value = amt
            ws[f"D{row}"].number_format = '"$"#,##0.00'
            ws[f"D{row}"].alignment = center_align

            for col in range(2, 6):
                ws.cell(row, col).border = thin_border

            total_inside += amt
            row += 1

        ws.merge_cells(f"B{row}:C{row}")
        ws[f"B{row}"].value = "Total"
        ws[f"B{row}"].font = bold_font
        ws[f"B{row}"].alignment = center_align

        ws.merge_cells(f"D{row}:E{row}")
        ws[f"D{row}"].value = total_inside
        ws[f"D{row}"].number_format = '"$"#,##0.00'
        ws[f"D{row}"].fill = green_fill
        ws[f"D{row}"].font = bold_font
        ws[f"D{row}"].alignment = center_align

        for col in range(2, 6):
            ws.cell(row, col).border = thin_border

        # Outside America
        row += 2
        ws.merge_cells(f"B{row}:E{row}")
        ws[f"B{row}"].value = "Outside America"
        ws[f"B{row}"].fill = light_blue_fill
        ws[f"B{row}"].font = bold_font
        ws[f"B{row}"].alignment = center_align

        for col in range(2, 6):
            ws.cell(row, col).border = thin_border

        row += 1
        ws.merge_cells(f"B{row}:C{row}")
        ws[f"B{row}"].value = "Emp. Nm"
        ws[f"B{row}"].font = bold_font
        ws[f"B{row}"].fill = light_gray_fill
        ws[f"B{row}"].alignment = center_align

        ws.merge_cells(f"D{row}:E{row}")
        ws[f"D{row}"].value = "Amount"
        ws[f"D{row}"].font = bold_font
        ws[f"D{row}"].fill = light_gray_fill
        ws[f"D{row}"].alignment = center_align

        for col in range(2, 6):
            ws.cell(row, col).border = thin_border

        row += 1
        total_outside = 0
        for name in sorted(salary_outside.keys()):
            amt = salary_outside[name]
            ws.merge_cells(f"B{row}:C{row}")
            ws[f"B{row}"].value = name
            ws[f"B{row}"].alignment = left_align

            ws.merge_cells(f"D{row}:E{row}")
            ws[f"D{row}"].value = amt
            ws[f"D{row}"].number_format = '"$"#,##0.00'
            ws[f"D{row}"].alignment = center_align

            for col in range(2, 6):
                ws.cell(row, col).border = thin_border

            total_outside += amt
            row += 1

        ws.merge_cells(f"B{row}:C{row}")
        ws[f"B{row}"].value = "Total"
        ws[f"B{row}"].font = bold_font
        ws[f"B{row}"].alignment = center_align

        ws.merge_cells(f"D{row}:E{row}")
        ws[f"D{row}"].value = total_outside
        ws[f"D{row}"].number_format = '"$"#,##0.00'
        ws[f"D{row}"].fill = green_fill
        ws[f"D{row}"].font = bold_font
        ws[f"D{row}"].alignment = center_align

        for col in range(2, 6):
            ws.cell(row, col).border = thin_border

        # Expense Breakdown
        ws.merge_cells("G35:K35")
        ws["G35"].value = "EXPENSE BREAK-DOWN"
        ws["G35"].font = Font(name='Calibri', size=14, bold=True)
        ws["G35"].alignment = center_align

        ws.merge_cells("G37:I37")
        ws["G37"].value = "Expense Item"
        ws["G37"].font = bold_font
        ws["G37"].fill = light_blue_fill
        ws["G37"].alignment = center_align

        ws.merge_cells("J37:K37")
        ws["J37"].value = "Amount"
        ws["J37"].font = bold_font
        ws["J37"].fill = light_blue_fill
        ws["J37"].alignment = center_align

        for col in range(7, 12):
            ws.cell(37, col).border = thin_border

        row = 38
        for exp_name in sorted(expense_breakdown.keys(), key=lambda x: expense_breakdown[x], reverse=True):
            amt = expense_breakdown[exp_name]

            ws.merge_cells(f"G{row}:I{row}")
            ws[f"G{row}"].value = exp_name
            ws[f"G{row}"].alignment = left_align

            ws.merge_cells(f"J{row}:K{row}")
            ws[f"J{row}"].value = amt
            ws[f"J{row}"].number_format = '"$"#,##0.00'
            ws[f"J{row}"].alignment = center_align

            for col in range(7, 12):
                ws.cell(row, col).border = thin_border

            row += 1

        ws.merge_cells(f"G{row}:I{row}")
        ws[f"G{row}"].value = "Total"
        ws[f"G{row}"].font = bold_font
        ws[f"G{row}"].alignment = center_align

        ws.merge_cells(f"J{row}:K{row}")
        ws[f"J{row}"].value = total_expenses
        ws[f"J{row}"].number_format = '"$"#,##0.00'
        ws[f"J{row}"].fill = green_fill
        ws[f"J{row}"].font = bold_font
        ws[f"J{row}"].alignment = center_align

        for col in range(7, 12):
            ws.cell(row, col).border = thin_border

        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'Balance_Sheet_Annual_{year}.xlsx'
        )

    except Exception as e:
        log.error(f"Export error: {e}")
        flash(f"Export failed: {str(e)}", "danger")
        return redirect(url_for("financial", tab="balance-sheet"))

# ── Routes: Employees ─────────────────────────────────────────────────────────
@app.route("/employees")
@role_required("employees")
def employees():
    uid        = session.get("user_uid", "")
    _role      = normalize_role(session.get("user_role", ""))
    is_admin   = _role == "admin"
    is_finance = _role == "finance"

    all_entries = _load_time_entries()
    all_time_off = _load_time_off_requests()
    active_projects = [p for p in _load_projects_list()
                       if p.get("status", "") not in ("Completed", "Cancelled")]

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    month_start = now.strftime("%Y-%m-01")
    year_start = now.strftime("%Y-01-01")

    my_entries = [e for e in all_entries if e.get("employee_uid") == uid]
    my_open_entry = next((e for e in my_entries if e.get("status") == "open"), None)
    # Most recently used project — pre-selected as the default for the next clock-in
    last_project_number = my_entries[0].get("project_number", "") if my_entries else ""
    my_today_entries = [e for e in my_entries if e.get("status") == "closed" and e.get("date") == today_str]
    my_week_entries = [e for e in my_entries if e.get("status") == "closed" and e.get("date", "") >= week_start]
    my_month_entries = [e for e in my_entries if e.get("status") == "closed" and e.get("date", "") >= month_start]
    my_year_entries = [e for e in my_entries if e.get("status") == "closed" and e.get("date", "") >= year_start]
    my_today_minutes = _sum_minutes(my_today_entries)
    my_week_minutes = _sum_minutes(my_week_entries)
    my_month_minutes = _sum_minutes(my_month_entries)
    my_year_minutes = _sum_minutes(my_year_entries)
    my_time_off = [r for r in all_time_off if r.get("employee_uid") == uid]
    my_time_off_balance = _time_off_balance(all_time_off, uid, now.year)

    # "Hours by Project" breakdown for My Time Clock tab, with its own period selector
    my_period = request.args.get("myperiod", "week")
    my_period_start, my_period_end, my_period_label = _period_range(
        my_period, request.args.get("mystart", ""), request.args.get("myend", ""))
    my_period_entries = [e for e in my_entries
                          if e.get("status") == "closed" and my_period_start <= e.get("date", "") <= my_period_end]
    my_period_by_project = _sum_minutes_by_project(my_period_entries)
    my_period_minutes = _sum_minutes(my_period_entries)

    context = {
        "active_projects":  active_projects,
        "today_str":        today_str,
        "profile_user":     fb_get(f"/users/{uid}") or {},
        "last_project_number": last_project_number,
        "my_open_entry":    my_open_entry,
        "my_today_entries": my_today_entries,
        "my_today_minutes": my_today_minutes,
        "my_week_minutes":  my_week_minutes,
        "my_month_minutes": my_month_minutes,
        "my_year_minutes":  my_year_minutes,
        "my_period":            my_period,
        "my_period_start":      my_period_start,
        "my_period_end":        my_period_end,
        "my_period_label":      my_period_label,
        "my_period_by_project": my_period_by_project,
        "my_period_minutes":    my_period_minutes,
        "my_time_off":         my_time_off,
        "my_time_off_balance": my_time_off_balance,
        "current_year":        now.year,
    }

    if is_admin:
        period = request.args.get("period", "week")
        custom_start = request.args.get("start", "")
        custom_end = request.args.get("end", "")
        period_start, period_end, period_label = _period_range(period, custom_start, custom_end)
        period_entries = [e for e in all_entries if period_start <= e.get("date", "") <= period_end]

        stale_open_entries = [e for e in all_entries
                               if e.get("status") == "open" and e.get("date", "") < today_str]
        for e in stale_open_entries:
            e["_suggested_close"] = f"{e.get('date', today_str)}T17:00"

        context.update({
            "all_users":           _load_all_users(),
            "open_entries_by_uid": {e["employee_uid"]: e for e in all_entries if e.get("status") == "open"},
            "pending_time_off":    [r for r in all_time_off if r.get("status") == "Pending"],
            "all_time_off_balances": {
                u["firebase_uid"]: _time_off_balance(all_time_off, u["firebase_uid"], now.year)
                for u in _load_all_users() if u.get("firebase_uid")
            },
            "hours_by_project":    _aggregate_hours_by_project(period_entries),
            "stale_open_entries":  stale_open_entries,
            "period":              period,
            "period_start":        period_start,
            "period_end":          period_end,
            "period_label":        period_label,
        })
    return render_template("employees.html", **context)

@app.route("/employees/clock-in", methods=["POST"])
@role_required("employees")
def employee_clock_in():
    uid  = session.get("user_uid", "")
    name = session.get("user_name", "")
    project_number = request.form.get("project_number", "").strip()

    if any(e.get("employee_uid") == uid and e.get("status") == "open" for e in _load_time_entries()):
        flash("You're already clocked in. Clock out first.", "warning")
        return redirect(url_for("employees"))

    project_name = ""
    if project_number:
        proj = next((p for p in _load_projects_list() if p.get("project_number") == project_number), None)
        if proj:
            project_name = proj.get("project_name", "")

    now = datetime.now()
    fb_push("/time_entries", {
        "employee_uid":   uid,
        "employee_name":  name,
        "project_number": project_number,
        "project_name":   project_name,
        "clock_in":       now.isoformat(),
        "clock_out":      None,
        "duration_minutes": 0,
        "date":           now.strftime("%Y-%m-%d"),
        "status":         "open",
    })
    flash(f"Clocked in{' to ' + project_name if project_name else ''}.", "success")
    return redirect(url_for("employees"))

@app.route("/employees/switch-project", methods=["POST"])
@role_required("employees")
def employee_switch_project():
    uid  = session.get("user_uid", "")
    name = session.get("user_name", "")
    new_project_number = request.form.get("project_number", "").strip()

    open_entry = next((e for e in _load_time_entries()
                        if e.get("employee_uid") == uid and e.get("status") == "open"), None)
    if not open_entry:
        flash("You're not currently clocked in.", "warning")
        return redirect(url_for("employees"))

    if new_project_number == open_entry.get("project_number", ""):
        flash("You're already clocked into that project.", "warning")
        return redirect(url_for("employees"))

    now = datetime.now()
    clock_in = datetime.fromisoformat(open_entry["clock_in"])
    duration = round((now - clock_in).total_seconds() / 60.0, 1)
    fb_update(f"/time_entries/{open_entry['firebase_id']}", {
        "clock_out":        now.isoformat(),
        "duration_minutes": duration,
        "status":           "closed",
    })

    project_name = ""
    if new_project_number:
        proj = next((p for p in _load_projects_list() if p.get("project_number") == new_project_number), None)
        if proj:
            project_name = proj.get("project_name", "")

    fb_push("/time_entries", {
        "employee_uid":   uid,
        "employee_name":  name,
        "project_number": new_project_number,
        "project_name":   project_name,
        "clock_in":       now.isoformat(),
        "clock_out":      None,
        "duration_minutes": 0,
        "date":           now.strftime("%Y-%m-%d"),
        "status":         "open",
    })
    flash(f"Switched to {project_name or 'General / Admin'}.", "success")
    return redirect(url_for("employees"))

@app.route("/employees/clock-out", methods=["POST"])
@role_required("employees")
def employee_clock_out():
    uid = session.get("user_uid", "")
    open_entry = next((e for e in _load_time_entries()
                        if e.get("employee_uid") == uid and e.get("status") == "open"), None)
    if not open_entry:
        flash("You're not currently clocked in.", "warning")
        return redirect(url_for("employees"))

    clock_in = datetime.fromisoformat(open_entry["clock_in"])
    now = datetime.now()
    duration = round((now - clock_in).total_seconds() / 60.0, 1)
    fb_update(f"/time_entries/{open_entry['firebase_id']}", {
        "clock_out":        now.isoformat(),
        "duration_minutes": duration,
        "status":           "closed",
        "notes":            request.form.get("notes", "").strip(),
    })
    flash("Clocked out.", "success")
    return redirect(url_for("employees"))

@app.route("/employees/log-time", methods=["POST"])
@role_required("employees")
def employee_log_time():
    uid  = session.get("user_uid", "")
    name = session.get("user_name", "")
    date_str = request.form.get("date", "").strip()
    project_number = request.form.get("project_number", "").strip()
    hours = _safe_float(request.form.get("hours", 0))
    notes = request.form.get("notes", "").strip()

    today_str = datetime.now().strftime("%Y-%m-%d")
    if not date_str or date_str > today_str or hours <= 0:
        flash("Enter a valid date (not in the future) and number of hours.", "danger")
        return redirect(url_for("employees"))

    project_name = ""
    if project_number:
        proj = next((p for p in _load_projects_list() if p.get("project_number") == project_number), None)
        if proj:
            project_name = proj.get("project_name", "")

    fb_push("/time_entries", {
        "employee_uid":     uid,
        "employee_name":    name,
        "project_number":   project_number,
        "project_name":     project_name,
        "clock_in":         "",
        "clock_out":        "",
        "duration_minutes": round(hours * 60, 1),
        "date":             date_str,
        "status":           "closed",
        "notes":            notes,
        "source":           "manual",
    })
    flash(f"Logged {hours:g}h to {project_name or 'General / Admin'}.", "success")
    return redirect(url_for("employees"))

@app.route("/employees/time-off/new", methods=["POST"])
@role_required("employees")
def employee_time_off_new():
    start_date = request.form.get("start_date", "")
    end_date   = request.form.get("end_date", "")

    if not start_date or not end_date:
        flash("Start and end dates are required.", "danger")
        return redirect(url_for("employees"))

    req_type = request.form.get("type", "Vacation")
    working_days = _count_working_days(start_date, end_date) if req_type != "Unpaid" else 0
    fb_push("/time_off_requests", {
        "employee_uid":  session.get("user_uid", ""),
        "employee_name": session.get("user_name", ""),
        "type":          req_type,
        "start_date":    start_date,
        "end_date":      end_date,
        "working_days":  working_days,
        "reason":        request.form.get("reason", "").strip(),
        "status":        "Pending",
        "requested_at":  datetime.now(timezone.utc).isoformat(),
        "reviewed_by":   "",
        "reviewed_at":   "",
        "review_note":   "",
    })
    flash("Time off request submitted.", "success")
    return redirect(url_for("employees") + "#time-off")

@app.route("/employees/time-off/<request_id>/<action>", methods=["POST"])
@role_required("employees")
def employee_time_off_action(request_id, action):
    if normalize_role(session.get("user_role", "")) != "admin":
        flash("You don't have permission to do that.", "danger")
        return redirect(url_for("employees"))

    if action not in ("approve", "reject"):
        flash("Invalid action.", "danger")
        return redirect(url_for("employees"))

    new_status = "Approved" if action == "approve" else "Rejected"
    fb_update(f"/time_off_requests/{request_id}", {
        "status":      new_status,
        "reviewed_by": session.get("user_name", ""),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    flash(f"Time off request {new_status.lower()}.", "success")
    return redirect(url_for("employees") + "#time-off")

@app.route("/employees/<uid>/update", methods=["POST"])
@role_required("employees")
def employee_update(uid):
    if normalize_role(session.get("user_role", "")) != "admin":
        flash("You don't have permission to do that.", "danger")
        return redirect(url_for("employees"))

    updates = {
        "hourly_rate":     _safe_float(request.form.get("hourly_rate", 0)),
        "department":      request.form.get("department", "").strip(),
        "hire_date":       request.form.get("hire_date", "").strip(),
        "employee_status": request.form.get("employee_status", "Active"),
        "updated_at":      datetime.now(timezone.utc).isoformat(),
    }
    if request.form.get("title") is not None:
        updates["title"] = request.form.get("title", "").strip()
    if request.form.get("region") is not None:
        updates["region"] = request.form.get("region", "").strip()
    if request.form.get("monthly_salary") is not None:
        updates["monthly_salary"] = _safe_float(request.form.get("monthly_salary", 0))
    fb_update(f"/users/{uid}", updates)
    flash("Employee details updated.", "success")
    return redirect(url_for("employees") + "#team")

@app.route("/api/users/<uid>/details", methods=["PATCH"])
@role_required("settings")
def user_details_update(uid):
    """Update employee profile fields (title, region, rates) from Settings or Directory."""
    if normalize_role(session.get("user_role", "")) != "admin":
        return jsonify({"error": "Admin access required"}), 403
    data = request.get_json() or {}
    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for field in ("title", "region"):
        if field in data:
            updates[field] = str(data[field]).strip()
    for field in ("hourly_rate", "monthly_salary"):
        if field in data:
            updates[field] = _safe_float(data[field])
    fb_update(f"/users/{uid}", updates)
    return jsonify({"ok": True})

@app.route("/employees/export-hours")
@role_required("employees")
def employee_export_hours():
    if normalize_role(session.get("user_role", "")) != "admin":
        flash("You don't have permission to do that.", "danger")
        return redirect(url_for("employees") + "#team")

    import csv
    import io as _io

    period = request.args.get("period", "week")
    custom_start = request.args.get("start", "")
    custom_end = request.args.get("end", "")
    period_start, period_end, period_label = _period_range(period, custom_start, custom_end)

    all_entries = _load_time_entries()
    period_entries = [e for e in all_entries if period_start <= e.get("date", "") <= period_end]
    hours_by_project = _aggregate_hours_by_project(period_entries)

    output = _io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Hours by Project — {period_label}"])
    writer.writerow(["Project", "Employee", "Hours"])
    grand_total = 0.0
    for proj, data in hours_by_project.items():
        for emp, minutes in data.items():
            if emp == "_total":
                continue
            writer.writerow([proj, emp, round(minutes / 60, 2)])
        writer.writerow([proj, "TOTAL", round(data["_total"] / 60, 2)])
        grand_total += data["_total"]
    writer.writerow([])
    writer.writerow(["Grand Total", "", round(grand_total / 60, 2)])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return send_file(
        _io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"hours_by_project_{period_start}_to_{period_end}.csv"
    )

@app.route("/employees/time-entries/<entry_id>/close", methods=["POST"])
@role_required("employees")
def employee_close_entry(entry_id):
    entry = fb_get(f"/time_entries/{entry_id}")
    if not entry or entry.get("status") != "open":
        flash("Time entry not found or already closed.", "danger")
        return redirect(url_for("employees") + "#team")

    is_owner = entry.get("employee_uid") == session.get("user_uid", "")
    is_admin = normalize_role(session.get("user_role", "")) == "admin"
    if not (is_owner or is_admin):
        flash("You don't have permission to do that.", "danger")
        return redirect(url_for("employees"))

    redirect_tab = "#clock" if is_owner else "#team"

    try:
        clock_out = datetime.fromisoformat(request.form.get("clock_out", ""))
        clock_in = datetime.fromisoformat(entry["clock_in"])
        duration = round((clock_out - clock_in).total_seconds() / 60.0, 1)
    except ValueError:
        duration = -1

    if duration < 0:
        flash("Invalid clock-out time — it must be after the clock-in time.", "danger")
        return redirect(url_for("employees") + redirect_tab)

    fb_update(f"/time_entries/{entry_id}", {
        "clock_out":        clock_out.isoformat(),
        "duration_minutes": duration,
        "status":           "closed",
        "closed_by":        session.get("user_name", ""),
    })
    flash(f"Closed {entry.get('employee_name','')}'s entry — {round(duration/60, 1)}h logged.", "success")
    return redirect(url_for("employees") + redirect_tab)

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
    """Extract expense fields from an uploaded receipt (PDF or image) using Claude."""
    f = request.files.get("pdf")
    if not f:
        return jsonify({"error": "No file uploaded"}), 400

    custom_categories = fb_get("/custom_categories") or {}
    expense_types = custom_categories.get("expense_type", []) if isinstance(custom_categories.get("expense_type"), list) else []
    categories_by_type = custom_categories.get("Categories", {}) if isinstance(custom_categories.get("Categories"), dict) else {}

    # Provide default values if empty (matching reference structure)
    if not expense_types:
        expense_types = [
            "O & M (Operations & Maintenance)",
            "Capital Expenses",
            "Other Expenses"
        ]

    if not categories_by_type:
        categories_by_type = {
            "O & M (Operations & Maintenance)": [
                "Facilities & Utilities",
                "Office & Admin Overhead",
                "Engineering Software & IT",
                "Salaries, Labor & Related Costs",
                "Professional Services",
                "Insurance & Compliance",
                "Travel, Site Visits & Vehicles",
                "Marketing & Business Development",
                "Training, Licensure & Development",
                "Safety & Field Supplies",
                "Miscellaneous O & M"
            ],
            "Capital Expenses": [
                "Computer & Office Equipment",
                "Field & Inspection Equipment",
                "Furniture & Fixtures",
                "Vehicles",
                "Software (Capitalized)",
                "Leasehold Improvements",
                "Accumulated Depreciation"
            ],
            "Other Expenses": [
                "Salary/Bonuses",
                "Tax Expenses/Tax Deductions",
                "Medical/Benefits",
                "Meals & Entertainment",
                "Donations",
                "Bank Charges",
                "Contingency Funds",
                "Unexpected Costs"
            ]
        }

    type_hint = f"Pick from these expense types if one fits: {expense_types}. " if expense_types else ""
    cat_hint = f"Pick from these categories if one fits: {sorted(set(c for cats in categories_by_type.values() for c in cats))}. " if categories_by_type else ""

    fields_prompt = f"""Return ONLY valid JSON with these fields:
expense_name (short description of the expense), expense_type (a general type/department for this expense; {type_hint}otherwise make a reasonable guess), category (a specific category for this expense; {cat_hint}otherwise pick one of: Labor, Materials, Equipment, Subcontractor, Overhead, Travel, Other), amount (number, no currency symbol), date (YYYY-MM-DD or blank), vendor.
If a field is not found leave it blank. Return only the JSON object, nothing else."""

    content_type = (f.content_type or "").lower()

    if content_type.startswith("image/"):
        try:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return jsonify({"error": f"Could not read image: {e}"}), 400
        prompt = f"This image is a receipt or invoice. {fields_prompt}"
        try:
            result = _ai_call_with_image(prompt, image_b64, content_type)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        if not PYPDF_AVAILABLE:
            return jsonify({"error": "pypdf not installed on server"}), 500
        try:
            reader = _PdfReader(f)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)[:4000]
        except Exception as e:
            return jsonify({"error": f"Could not read PDF: {e}"}), 400
        prompt = f"""Extract expense information from this document text. {fields_prompt}

Document text:
{text}"""
        try:
            result = _ai_call(prompt)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        return jsonify(json.loads(result))
    except json.JSONDecodeError:
        import re
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m:
            return jsonify(json.loads(m.group(0)))
        return jsonify({"error": "AI returned unexpected format", "raw": result}), 500


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
        return redirect(url_for("settings") + "?tab=users")

    if not FIREBASE_AVAILABLE:
        flash("Firebase not available.", "danger")
        return redirect(url_for("settings") + "?tab=users")

    try:
        from firebase_admin import auth as fb_auth
        user = fb_auth.create_user(email=email, password=password,
                                   display_name=username, email_verified=False)
        user_data = {
            "username":       username,
            "email":          email,
            "role":           role,
            "active":         True,
            "firebase_uid":   user.uid,
            "title":          request.form.get("title", "").strip(),
            "region":         request.form.get("region", "").strip(),
            "hourly_rate":    _safe_float(request.form.get("hourly_rate", 0)),
            "monthly_salary": _safe_float(request.form.get("monthly_salary", 0)),
            "created_at":     datetime.now(timezone.utc).isoformat(),
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }
        fb_update(f"/users/{user.uid}", user_data)
        flash(f"User {username} created.", "success")
    except Exception as exc:
        flash(f"Error creating user: {exc}", "danger")

    return redirect(url_for("settings") + "?tab=users")

@app.route("/settings/user/<uid>/toggle", methods=["POST"])
@role_required("settings")
def user_toggle(uid):
    profile = fb_get(f"/users/{uid}") or {}
    current = profile.get("active", True)
    fb_update(f"/users/{uid}", {"active": not current,
                                "updated_at": datetime.now(timezone.utc).isoformat()})
    flash("User status updated.", "success")
    return redirect(url_for("settings") + "?tab=users")

@app.route("/settings/user/<uid>/role", methods=["POST"])
@role_required("settings")
def user_role_update(uid):
    new_role = normalize_role(request.form.get("role", "sales"))
    fb_update(f"/users/{uid}", {"role": new_role,
                                "updated_at": datetime.now(timezone.utc).isoformat()})
    flash("User role updated.", "success")
    return redirect(url_for("settings") + "?tab=users")

@app.route("/settings/user/<uid>/delete", methods=["POST"])
@role_required("settings")
def user_delete(uid):
    if uid == session.get("user_uid"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("settings") + "?tab=users")
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
    return redirect(url_for("settings") + "?tab=users")

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

def _find_quote_by_number(job_number: str):
    """Look up a /job_forms quote by its job_number. Returns (firebase_id, data) or (None, None)."""
    job_number = (job_number or "").strip()
    if not job_number:
        return None, None
    raw = fb_get("/job_forms") or {}
    if isinstance(raw, dict):
        for qid, qdata in raw.items():
            if isinstance(qdata, dict) and qdata.get("job_number", "").strip() == job_number:
                return qid, qdata
    return None, None

def _quote_to_project_fields(quote: dict) -> dict:
    """Map a /job_forms quote record onto the New Project form's field names."""
    service_costs = {}
    for item in quote.get("line_items", []) or []:
        if isinstance(item, dict):
            desc = (item.get("description") or "").strip()
            if desc:
                service_costs[desc] = item.get("total") or item.get("unit_price") or "0"
    return {
        "project_name":   quote.get("project_name", "") or quote.get("description", ""),
        "client_name":    quote.get("client_name", ""),
        "sales":          quote.get("salesperson", ""),
        "site_address":   "",
        "mail_address":   "",
        "plant":          "",
        "service_types":  quote.get("service_types") or [],
        "service_costs":  service_costs,
        "scope_of_work":  quote.get("description", ""),
        "expedite":       "Yes" if quote.get("is_expedited") else "No",
        "rush_rate":      quote.get("rush_rate", "50"),
        "contract_value": f"{_safe_float(quote.get('total', 0)):.2f}",
        "start_date":     "",
        "end_date":       quote.get("expected_completion", ""),
    }

@app.route("/api/quote-by-number/<quote_number>")
@login_required
def api_quote_by_number(quote_number):
    """Return quote data for a given job_number so the project form can auto-fill."""
    _, qdata = _find_quote_by_number(quote_number)
    if qdata:
        fields = _quote_to_project_fields(qdata)
        fields["found"] = True
        return jsonify(fields)
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

def _enrich_projects_with_next_stage(projects: list, all_invoices: dict = None) -> list:
    """Annotate each project dict with its next-pending-payment-stage info
    (used by the invoice form's "Active projects for this client" picker so
    it bills the next installment instead of the full outstanding balance)."""
    if all_invoices is None:
        all_invoices = fb_get("/invoices") or {}
    for p in projects:
        if isinstance(p, dict):
            detection = _get_next_payment_stage(p, all_invoices)
            p["next_stage_idx"]    = detection.get("stage_idx")
            p["next_stage_name"]   = detection.get("stage_name") or ""
            p["next_stage_amount"] = detection.get("amount", 0)
    return projects

def _find_project_by_number(project_number: str):
    """Return (firebase_id, project_dict) for the project with this number, or (None, None)."""
    raw_proj = fb_get("/projects") or {}
    if isinstance(raw_proj, dict):
        for pid, pdata in raw_proj.items():
            if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
                return pid, pdata
    return None, None

def _mark_project_stage(project_number: str, stage_index: int, status: str, invoice_id: str = None, invoice_number: str = None, amount: float = None, amount_paid: float = None) -> None:
    """Update one stage's status (and optionally its linked invoice id/number/amount/amount_paid) within a project's payment plan."""
    pid, pdata = _find_project_by_number(project_number)
    print(f"[MARK_STAGE] project_number={project_number}, stage_idx={stage_index}, status={status}, amount={amount}, amount_paid={amount_paid}, pid={pid}", flush=True)
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
    if amount is not None:
        stages[stage_index]["amount"] = amount
    if amount_paid is not None:
        stages[stage_index]["amount_paid"] = str(amount_paid)
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

    Returns: "Paid", "Partial", or "Overdue" based on actual payments.
    If no payments, returns the stored status (user-selected).
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

    # If invoice_paid covers both line items and tax (overpayment towards tax), credit it
    if invoice_paid > invoice_subtotal:
        tax_paid += (invoice_paid - invoice_subtotal)
        invoice_paid = invoice_subtotal

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
        return meta.get("status", "Draft")

def _derive_stage_index_from_line_items(project_number: str, line_items: list) -> int:
    """Try to find stage_index from line items by looking for paid stage references."""
    if not isinstance(line_items, list):
        return -1

    # Look for stage name patterns in line item descriptions
    # e.g., "Testing1 — Installment 2 of 3" -> find stage named "Installment 2 of 3"
    pid, pdata = _find_project_by_number(project_number)
    if not pid:
        return -1

    stages = pdata.get("payment_stages", []) or []
    if not isinstance(stages, list):
        return -1

    # Build a map of generated stage names to indices
    # Stage names are generated the same way as in project_form.html:
    # "Installment 1 of N", "Installment 2 of N", etc.
    num_stages = len(stages)
    stage_name_map = {}
    for idx in range(num_stages):
        if num_stages == 1:
            stage_name = "Balance Payment"
        else:
            stage_name = f"Installment {idx + 1} of {num_stages}"
        stage_name_map[stage_name.lower()] = idx

    # Search line items for stage references
    for item in line_items:
        if not isinstance(item, dict):
            continue
        desc = item.get("description", "").lower()
        # Look for stage name in description (e.g., "installment 2 of 3")
        for stage_name, stage_idx in stage_name_map.items():
            if stage_name in desc:
                print(f"[DERIVE] Found stage {stage_idx} from line item: {desc}", flush=True)
                return stage_idx

    print(f"[DERIVE] Could not derive stage from line items for project {project_number}", flush=True)
    return -1

def _update_project_stage_payment_status(invoice_id: str) -> None:
    """Update project stage statuses based on invoice payments.

    For each project linked to the invoice, sum payments made FOR THAT PROJECT
    and update the stage status to Paid/Partially Paid/Invoiced.
    """
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    meta = inv_data.get("meta", {}) or {}

    # Get linked projects from invoice
    linked_projects = meta.get("linked_projects", [])

    # Convert string format to dict format if needed
    # Handles both ['MABS-202606-003'] and [{"project_number": "...", "payment_stage_index": ...}]
    normalized_projects = []
    if linked_projects:
        for item in linked_projects:
            if isinstance(item, dict):
                normalized_projects.append(item)
            elif isinstance(item, str):
                # Legacy string format: use main invoice's stage index
                stage_idx = meta.get("payment_stage_index", -1)
                if stage_idx >= 0:
                    normalized_projects.append({"project_number": item, "payment_stage_index": stage_idx})

    # Fallback: if no linked_projects, build from main project
    if not normalized_projects:
        main_project = meta.get("project_number", "")
        stage_index = meta.get("payment_stage_index", -1)

        # If no stage_index in meta, try to derive from line items
        if stage_index < 0:
            line_items = inv_data.get("line_items", [])
            stage_index = _derive_stage_index_from_line_items(main_project, line_items)

        if main_project and stage_index >= 0:
            normalized_projects = [{"project_number": main_project, "payment_stage_index": stage_index}]
        elif main_project and stage_index < 0:
            # Invoice doesn't have payment_stage_index - we'll search for it by invoice_id later
            normalized_projects = [{"project_number": main_project, "payment_stage_index": -1, "invoice_id": invoice_id}]
        else:
            return

    # Get ALL invoices to sum payments for each stage
    all_invoices = fb_get("/invoices") or {}

    # Update each project's stage status based on payments FOR THAT PROJECT
    for proj_info in normalized_projects:
        if not isinstance(proj_info, dict):
            continue

        project_number = proj_info.get("project_number", "")
        stage_index = proj_info.get("payment_stage_index", -1)
        inv_id_for_lookup = proj_info.get("invoice_id")

        if not project_number:
            continue

        # Get project and stage info
        pid, pdata = _find_project_by_number(project_number)
        if not pid:
            continue

        stages = pdata.get("payment_stages") or []

        # If stage_index not available, search for stage by invoice_id
        if stage_index < 0:
            if inv_id_for_lookup:
                # Find the stage that has this invoice_id
                for idx, s in enumerate(stages):
                    if isinstance(s, dict) and s.get("invoice_id") == inv_id_for_lookup:
                        stage_index = idx
                        break
            if stage_index < 0:
                # Still not found
                continue

        if not (0 <= stage_index < len(stages)):
            continue

        stage = stages[stage_index]
        stage_amount = _safe_float(stage.get("amount", 0))

        if stage_amount <= 0:
            continue

        # For multi-project invoices, use the amount_paid that was set by sequential allocation
        # For single-project invoices, sum payments from the invoice
        is_multi_project = len(linked_projects) > 1

        project_paid = 0
        linked_invoice_id = None
        linked_invoice_number = None

        if is_multi_project:
            # Use the amount already allocated by sequential allocation
            project_paid = _safe_float(pdata.get("amount_paid", 0))
        else:
            # Sum payments from ALL invoices linked to this stage for this project
            if isinstance(all_invoices, dict):
                for inv_id, inv in all_invoices.items():
                    if not isinstance(inv, dict):
                        continue
                    inv_meta = inv.get("meta", {}) or {}

                    # Check if invoice covers this project and stage
                    # Works for both single-project (project_number) and multi-project (linked_projects)
                    is_for_this_project = False

                    # First, check if this is the current invoice being updated (most direct match)
                    if inv_id == invoice_id:
                        # For the current invoice, if it's linked to this project, include it
                        if inv_meta.get("project_number") == project_number:
                            is_for_this_project = True
                    else:
                        # For other invoices, use the standard matching logic
                        # Single-project invoices use project_number
                        if (inv_meta.get("project_number") == project_number and
                            inv_meta.get("payment_stage_index") == stage_index):
                            is_for_this_project = True
                        else:
                            # Multi-project invoices use linked_projects array
                            # Handles both dict format [{"project_number": "...", "payment_stage_index": ...}]
                            # and legacy string format ['MABS-202606-003']
                            linked_projs = inv_meta.get("linked_projects", [])
                            if isinstance(linked_projs, list):
                                for lp in linked_projs:
                                    if isinstance(lp, dict):
                                        # Dict format: full metadata
                                        if lp.get("project_number") == project_number and lp.get("payment_stage_index") == stage_index:
                                            is_for_this_project = True
                                            break
                                    elif isinstance(lp, str) and lp == project_number:
                                        # Legacy string format: only has project number
                                        # For this case, use the invoice's payment_stage_index
                                        if inv_meta.get("payment_stage_index") == stage_index:
                                            is_for_this_project = True
                                            break

                    if is_for_this_project:
                        # Sum payments for this invoice (filter by project_number if available)
                        inv_payment_log = inv.get("payment_log", [])
                        if isinstance(inv_payment_log, list):
                            # Sum only payments for this project
                            inv_payments = sum(
                                _safe_float(p.get("amount", 0))
                                for p in inv_payment_log
                                if p.get("project_number") == project_number or not p.get("project_number")
                            )
                            project_paid += inv_payments
                            # Track invoice_id and invoice_number if this invoice has actual payments
                            # Prioritize the current invoice being updated (inv_id == invoice_id)
                            if inv_payments > 0:
                                if inv_id == invoice_id or not linked_invoice_id:
                                    linked_invoice_id = inv_id
                                    linked_invoice_number = inv_meta.get("invoice_number", "")
                            print(f"[PAYMENT_CALC] Invoice {inv_id}: project={project_number}, payments={inv_payments}, total_paid={project_paid}, current={inv_id == invoice_id}", flush=True)

        # Determine stage status based on actual payments for this project
        if project_paid >= (stage_amount - 0.01):
            new_status = "Paid"
        elif project_paid > 0:
            new_status = "Partially Paid"
        else:
            new_status = "Invoiced"

        log.info(f"[STATUS] Project {project_number} stage {stage_index}: amount={stage_amount}, paid={project_paid}, threshold={stage_amount - 0.01}, status={new_status}")

        # Update stage status with actual paid amount for this project, and track invoice_id and invoice_number
        stage["status"] = new_status
        stage["amount_paid"] = str(project_paid)
        if linked_invoice_id:
            stage["invoice_id"] = linked_invoice_id
        if linked_invoice_number:
            stage["invoice_number"] = linked_invoice_number

        log.info(f"[SAVE_STATUS] Saving stage {stage_index} status={new_status} to project {pid}")
        log.info(f"[SAVE_STAGE] Full stage data: {stage}")

        fb_update(f"/projects/{pid}", {
            "payment_stages": stages,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

def _allocate_invoice_payment_sequential(invoice_id: str) -> None:
    """Allocate invoice payment SEQUENTIALLY across linked projects (sorted by project number).

    When invoice with multiple projects receives payment, allocate in strict order:
    - Sort projects by project_number alphabetically
    - Project 005 gets filled first up to its stage amount
    - Then Project 006 gets remaining amount
    - Continue until all projects allocated or payment exhausted

    Each project updated with ONLY its allocated amount, not invoice total.
    """
    invoice = fb_get(f"/invoices/{invoice_id}") or {}
    if not isinstance(invoice, dict):
        return

    meta = invoice.get("meta", {}) or {}
    total_paid = _safe_float(meta.get("amount_paid", 0))

    log.info(f"[SEQ_ALLOC] Starting sequential allocation for invoice {invoice_id}, total_paid={total_paid}")

    # If total_paid is $0, we need to CLEAR all project amounts, not skip
    # This handles the case when all payments are deleted
    if total_paid <= 0.01 and total_paid > 0:
        # Very small payment (rounding), skip
        return

    # Get linked projects with their stage indices
    linked_projects_meta = meta.get("linked_projects", [])
    if not isinstance(linked_projects_meta, list):
        linked_projects_meta = []

    log.info(f"[SEQ_ALLOC] linked_projects_meta from metadata: {linked_projects_meta}")

    # If no linked_projects metadata, try to build from line_items
    # (Works even when payment_log is empty after deletion)
    if len(linked_projects_meta) < 2:
        line_items = invoice.get("line_items", [])
        if isinstance(line_items, list) and len(line_items) > 0:
            # Extract unique project numbers from line_items
            projects_in_items = set()
            for item in line_items:
                if isinstance(item, dict):
                    proj_num = item.get("project_number", "")
                    if proj_num:
                        projects_in_items.add(proj_num)

            # If line_items has 2+ projects, build linked_projects from them
            if len(projects_in_items) >= 2:
                log.info(f"[SEQ_ALLOC] Found {len(projects_in_items)} projects in line_items, building linked_projects")
                # For each project found, use the main invoice's stage index
                main_stage_idx = meta.get("payment_stage_index", 0)
                linked_projects_meta = [
                    {"project_number": proj_num, "payment_stage_index": main_stage_idx}
                    for proj_num in sorted(projects_in_items)
                ]

        if len(linked_projects_meta) < 1:
            log.info(f"[SEQ_ALLOC] NO projects found, skipping sequential allocation")
            return

    log.info(f"[SEQ_ALLOC] Found {len(linked_projects_meta)} linked projects, starting allocation")

    # Load all projects once
    all_projects = fb_get("/projects") or {}

    # Track which projects we'll update (to reset and recalculate)
    projects_to_update = {}  # pid -> (pdata, stage_idx)

    # Build list AND reset stages in-memory (don't wait for Firebase)
    projects_data = []
    for proj_info in linked_projects_meta:
        if not isinstance(proj_info, dict):
            continue
        proj_num = proj_info.get("project_number", "")
        stage_idx = proj_info.get("payment_stage_index", -1)

        if not proj_num or stage_idx < 0:
            log.warning(f"[SEQ_ALLOC] Skipping invalid proj_info: {proj_info}")
            continue

        # Find project in all_projects
        proj_id = None
        proj_data = None
        if isinstance(all_projects, dict):
            for pid, pdata in all_projects.items():
                if isinstance(pdata, dict) and pdata.get("project_number") == proj_num:
                    proj_id = pid
                    proj_data = pdata
                    break

        if not proj_id or not proj_data:
            log.warning(f"[SEQ_ALLOC] Project {proj_num} not found in database")
            continue

        projects_data.append((proj_num, stage_idx, proj_id, proj_data))

    # SORT BY PROJECT NUMBER (extract last digits and sort numerically)
    # e.g., "MABS-202606-005" -> extract "005" and sort as 5, "MABS-202606-006" -> 6
    projects_data.sort(key=lambda x: int(x[0][-3:]) if x[0][-3:].isdigit() else x[0])
    log.info(f"[SEQ_ALLOC] Sorted projects: {[p[0] for p in projects_data]}")

    # Allocate sequentially
    remaining = total_paid
    allocations = {}  # proj_num -> amount

    for proj_num, stage_idx, proj_id, proj_data in projects_data:
        stages = proj_data.get("payment_stages") or []
        if not (0 <= stage_idx < len(stages)):
            log.warning(f"[SEQ_ALLOC] Invalid stage_idx {stage_idx} for {proj_num}")
            continue

        # RESET this project's stage to $0 in-memory
        stage = stages[stage_idx]
        stage["amount_paid"] = "0"
        log.info(f"[SEQ_ALLOC] Reset {proj_num} stage {stage_idx} amount_paid to 0")

        stage_amount = _safe_float(stage.get("amount", 0))

        if remaining <= 0.01:
            # No more payment to allocate, but still need to save reset
            allocations[proj_num] = 0
            log.info(f"[SEQ_ALLOC] No remaining amount for {proj_num}")
            continue

        if stage_amount <= 0:
            log.info(f"[SEQ_ALLOC] Skipping {proj_num} - stage amount is 0")
            continue

        # Since we reset all amounts to 0 above, just allocate based on stage_amount
        allocated = min(remaining, stage_amount)
        allocations[proj_num] = allocated
        remaining -= allocated
        log.info(f"[SEQ_ALLOC] {proj_num}: stage_amount=${stage_amount}, allocated=${allocated}, remaining=${remaining}")

    # Update each project with its allocated amount
    for proj_num, stage_idx, proj_id, proj_data in projects_data:
        allocated = allocations.get(proj_num, 0)

        stages = proj_data.get("payment_stages") or []

        # Update the stage if valid
        if 0 <= stage_idx < len(stages):
            stage = stages[stage_idx]
            stage_amount = _safe_float(stage.get("amount", 0))
            stage["amount_paid"] = str(allocated)

            # Set stage status based on allocated amount
            if allocated >= (stage_amount - 0.01):
                stage["status"] = "Paid"
            elif allocated > 0:
                stage["status"] = "Partially Paid"
            else:
                stage["status"] = "Pending Invoice"

            log.info(f"[SEQ_ALLOC] {proj_num}: allocated=${allocated}, status={stage['status']}")
        else:
            log.warning(f"[SEQ_ALLOC] Invalid stage_idx {stage_idx} for {proj_num}, still updating amount_paid")

        # Update project amount_paid — but never zero-out a Completed project
        contract_val = _safe_float(proj_data.get("contract_value", 0))
        current_status = proj_data.get("status", "Not Started")
        existing_paid = _safe_float(proj_data.get("amount_paid", 0))

        # Skip writing amount_paid=0 for a Completed project — it would corrupt the record
        if current_status == "Completed" and allocated <= 0.01 and existing_paid > 0:
            updates = {
                "payment_stages": stages,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            updates = {
                "amount_paid": allocated,
                "payment_stages": stages,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

        # Update project status if needed (never downgrade Completed/Cancelled)
        if current_status not in ("Completed", "Cancelled"):
            if contract_val > 0 and allocated >= contract_val - 0.01:
                updates["status"] = "Completed"
            elif allocated > 0 and current_status == "Not Started":
                updates["status"] = "In Progress"

        fb_update(f"/projects/{proj_id}", updates)
        log.info(f"[SEQ_ALLOC] Updated project {proj_num}: amount_paid={allocated}")

def _sync_project_payment(project_number: str) -> None:
    """Recalculate project.amount_paid from invoice payment_logs (ground truth)
    and set project status based on that total.

    Using invoice payment_logs avoids corruption from stage.amount_paid resets
    that can occur during sequential allocation.
    """
    if not project_number:
        return

    raw_proj = fb_get("/projects") or {}
    pid = None
    pdata = None
    if isinstance(raw_proj, dict):
        for k, v in raw_proj.items():
            if isinstance(v, dict) and v.get("project_number", "") == project_number:
                pid, pdata = k, v
                break
    if not pid:
        return

    # Ground-truth: sum all invoice payments that belong to this project
    all_invoices = fb_get("/invoices") or {}
    total_paid = 0.0
    if isinstance(all_invoices, dict):
        for iid, inv in all_invoices.items():
            if not isinstance(inv, dict):
                continue
            meta = inv.get("meta", {}) or {}
            # Check if this invoice covers this project (single or multi-project)
            covers = (meta.get("project_number") == project_number)
            if not covers:
                linked = meta.get("linked_projects", [])
                if isinstance(linked, list):
                    for lp in linked:
                        if isinstance(lp, dict) and lp.get("project_number") == project_number:
                            covers = True
                            break
                        elif isinstance(lp, str) and lp == project_number:
                            covers = True
                            break
            if not covers:
                continue
            # Sum invoice line payments for this project
            payment_log = inv.get("payment_log", [])
            if isinstance(payment_log, list):
                for p in payment_log:
                    if isinstance(p, dict):
                        if p.get("project_number", project_number) == project_number:
                            total_paid += _safe_float(p.get("amount", 0))
                        elif not p.get("project_number"):
                            total_paid += _safe_float(p.get("amount", 0))

    updates = {
        "amount_paid": total_paid,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    contract_val   = _safe_float(pdata.get("contract_value", 0))
    current_status = pdata.get("status", "Not Started")

    # Never downgrade a cancelled project; always correct everything else.
    if current_status != "Cancelled":
        if contract_val > 0 and total_paid >= contract_val - 0.01:
            updates["status"] = "Completed"
        elif total_paid > 0:
            if current_status not in ("In Progress", "On Hold", "Completed"):
                updates["status"] = "In Progress"
        # Do NOT downgrade Completed when total_paid == 0 — payment_log may be incomplete

    fb_update(f"/projects/{pid}", updates)

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
            # Auto-send overdue reminder — only once per invoice
            if not m.get("reminder_sent_at"):
                ok, _ = _send_overdue_reminder_email(iid, inv)
                if ok:
                    fb_update(f"/invoices/{iid}", {
                        "meta/reminder_sent_at": datetime.now(timezone.utc).isoformat()
                    })
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

def _advance_project_to_in_progress(project_number: str) -> None:
    """Promote a project from Not Started to In Progress when an invoice is sent."""
    if not project_number:
        return
    raw_proj = fb_get("/projects") or {}
    for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
        if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
            if pdata.get("status", "Not Started") == "Not Started":
                fb_update(f"/projects/{pid}", {
                    "status": "In Progress",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
            break

def _auto_complete_project_if_paid(project_number: str) -> None:
    """Mark project Completed once its amount paid covers the full contract value.

    Paying off a single installment (out of several) must not flip the whole
    project to Completed - only do so when total paid >= contract value.
    Call _sync_project_payment(project_number) first so amount_paid is current.
    """
    if not project_number:
        return
    raw_proj = fb_get("/projects") or {}
    for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
        if isinstance(pdata, dict) and pdata.get("project_number", "") == project_number:
            if pdata.get("status", "") not in ("Completed", "Cancelled"):
                contract_val = _safe_float(pdata.get("contract_value", 0))
                total_paid   = _safe_float(pdata.get("amount_paid", 0))
                if contract_val > 0 and total_paid >= contract_val - 0.01:
                    fb_update(f"/projects/{pid}", {
                        "status": "Completed",
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })
                    if not pdata.get("completion_email_sent"):
                        _send_project_completion_email(project_number, pdata)
                        fb_update(f"/projects/{pid}", {"completion_email_sent": True})
            break

def _send_project_completion_email(project_number: str, project_data: dict) -> None:
    """Email client when project is marked Completed / fully paid."""
    try:
        settings = load_settings()
        em = settings.get("email", {})
        if not em.get("enabled"):
            return
        co          = settings.get("company", {})
        client_name = (project_data.get("client_name") or project_data.get("client") or "").strip()
        if not client_name:
            return
        raw_clients  = fb_get("/clients") or {}
        client_email = ""
        if isinstance(raw_clients, dict):
            for cd in raw_clients.values():
                if isinstance(cd, dict) and cd.get("name", "") == client_name:
                    client_email = cd.get("email", "")
                    break
        if not client_email:
            return
        proj_name    = (project_data.get("project_name") or project_data.get("name") or project_number)
        contract_val = _safe_float(project_data.get("contract_value", 0))
        html_body = f"""<html><body style="font-family:Arial,sans-serif;color:#1a1a1a;">
<div style="max-width:600px;margin:0 auto;padding:24px;">
  <h2 style="color:#0D9488;">Project Complete — {proj_name}</h2>
  <p>Dear {client_name},</p>
  <p>We are pleased to confirm that project <strong>{proj_name}</strong>
     (#{project_number}) has been marked
     <strong style="color:#10B981;">Completed</strong>.
     All payments have been received in full — thank you!</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0;">
    <tr><td style="padding:8px;border-bottom:1px solid #eee;">Project</td>
        <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{proj_name}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;">Project #</td>
        <td style="padding:8px;border-bottom:1px solid #eee;">{project_number}</td></tr>
    <tr><td style="padding:8px;">Contract Value</td>
        <td style="padding:8px;font-weight:bold;">${contract_val:,.2f}</td></tr>
  </table>
  <p>We appreciate your business and look forward to working with you again.</p>
  <p style="margin-top:24px;">Best regards,<br><strong>{co.get('name','')}</strong></p>
</div></body></html>"""
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = f"Project Completed — {proj_name} (#{project_number})"
        msg["From"]    = f"{em.get('from_name', co.get('name',''))} <{em.get('smtp_user','')}>"
        msg["To"]      = client_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(em.get("smtp_host", "smtp.gmail.com"),
                          int(em.get("smtp_port", 587))) as srv:
            srv.ehlo(); srv.starttls()
            srv.login(em.get("smtp_user", ""), em.get("smtp_password", ""))
            srv.sendmail(em.get("smtp_user", ""), [client_email], msg.as_string())
    except Exception as exc:
        log.error("Completion email error (project %s): %s", project_number, exc)

def _project_has_overdue_stage(payment_stages, raw_inv: dict) -> bool:
    """True if any payment stage is Invoiced/Partially Paid and its linked
    invoice's due date has passed without being fully paid."""
    if not isinstance(payment_stages, list):
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    for stage in payment_stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("status") not in ("Invoiced", "Partially Paid"):
            continue
        inv = raw_inv.get(stage.get("invoice_id", ""))
        if not isinstance(inv, dict):
            continue
        due_date = inv.get("meta", {}).get("due_date", "")
        if due_date and due_date < today:
            return True
    return False

def _load_clients() -> List[str]:
    raw = fb_get("/clients") or {}
    if isinstance(raw, dict):
        return sorted(raw.keys())
    return []

def _load_sales_people() -> List[dict]:
    """Return salesperson list sourced primarily from Settings /users (sales role only).
    Legacy /sales_persons entries are merged in as fallback so existing quote data
    that references old names is not orphaned.
    """
    seen_names: set = set()
    people: List[dict] = []

    # Primary source: Settings users with sales role only
    for u in _load_all_users():
        role = normalize_role(u.get("role", ""))
        if role != "sales":
            continue
        name = (u.get("username") or "").strip()
        if not name:
            continue
        people.append({
            "name":        name,
            "email":       u.get("email", ""),
            "phone":       u.get("phone", ""),
            "title":       u.get("title", ""),
            "firebase_id": u.get("firebase_uid", ""),
            "from_users":  True,
        })
        seen_names.add(name.lower())

    # Legacy fallback: /sales_persons (keeps old quote references valid)
    raw = fb_get("/sales_persons") or {}
    if isinstance(raw, dict):
        for pid, pdata in raw.items():
            if pdata and isinstance(pdata, dict):
                name = str(pdata.get("name", "")).strip()
                if name and name.lower() not in seen_names:
                    pdata["firebase_id"] = pid
                    people.append(pdata)
                    seen_names.add(name.lower())

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

def _load_time_entries() -> List[dict]:
    raw = fb_get("/time_entries") or {}
    if isinstance(raw, dict):
        items = []
        for tid, tdata in raw.items():
            if tdata and isinstance(tdata, dict):
                tdata["firebase_id"] = tid
                items.append(tdata)
        return sorted(items, key=lambda x: x.get("clock_in", ""), reverse=True)
    return []

def _load_time_off_requests() -> List[dict]:
    raw = fb_get("/time_off_requests") or {}
    if isinstance(raw, dict):
        items = []
        for rid, rdata in raw.items():
            if rdata and isinstance(rdata, dict):
                rdata["firebase_id"] = rid
                items.append(rdata)
        return sorted(items, key=lambda x: x.get("requested_at", ""), reverse=True)
    return []

DEFAULT_TIME_OFF_DAYS = 15

def _count_working_days(start_str: str, end_str: str) -> int:
    """Count Mon–Fri working days between start and end dates (inclusive)."""
    from datetime import date as _date
    try:
        s = _date.fromisoformat(start_str[:10])
        e = _date.fromisoformat(end_str[:10])
        if e < s:
            return 0
        count = 0
        cur = s
        while cur <= e:
            if cur.weekday() < 5:
                count += 1
            cur += timedelta(days=1)
        return count
    except Exception:
        return 0

def _time_off_balance(all_requests: list, uid: str, year: int) -> dict:
    """Return {allotment, used, remaining} working days for a user in a given year."""
    year_str = str(year)
    used = 0
    for r in all_requests:
        if r.get("employee_uid") != uid:
            continue
        if r.get("status") != "Approved":
            continue
        if r.get("type") == "Unpaid":
            continue
        start = r.get("start_date", "")
        if not start or not start.startswith(year_str):
            continue
        used += _count_working_days(start, r.get("end_date", start))
    remaining = max(0, DEFAULT_TIME_OFF_DAYS - used)
    return {"allotment": DEFAULT_TIME_OFF_DAYS, "used": used, "remaining": remaining}

def _sum_minutes_by_project(entries: List[dict]) -> dict:
    """Sum closed time-entry minutes grouped by project label."""
    totals: dict = {}
    for e in entries:
        if e.get("status") != "closed":
            continue
        minutes = _safe_float(e.get("duration_minutes", 0))
        proj = e.get("project_name") or e.get("project_number") or "General / Admin"
        totals[proj] = totals.get(proj, 0.0) + minutes
    return totals

def _sum_minutes(entries: List[dict]) -> float:
    """Total closed time-entry minutes."""
    return sum(_safe_float(e.get("duration_minutes", 0)) for e in entries if e.get("status") == "closed")

def _period_range(period: str, custom_start: str = "", custom_end: str = "") -> tuple:
    """Return (start_date, end_date, label) as YYYY-MM-DD strings for a named reporting period."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    if period == "month":
        return now.strftime("%Y-%m-01"), today_str, f"Month of {now.strftime('%B %Y')}"
    if period == "year":
        return now.strftime("%Y-01-01"), today_str, f"Year {now.year}"
    if period == "custom" and custom_start and custom_end:
        return custom_start, custom_end, f"{custom_start} → {custom_end}"
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    return week_start, today_str, f"Week of {week_start}"

def _aggregate_hours_by_project(entries: List[dict]) -> dict:
    """Group closed time-entry minutes into {project_label: {"_total": minutes, employee_name: minutes}}."""
    agg: dict = {}
    for e in entries:
        if e.get("status") != "closed":
            continue
        minutes = _safe_float(e.get("duration_minutes", 0))
        if minutes <= 0:
            continue
        proj = e.get("project_name") or e.get("project_number") or "General / Admin"
        emp = e.get("employee_name", "Unknown")
        bucket = agg.setdefault(proj, {"_total": 0.0})
        bucket["_total"] += minutes
        bucket[emp] = bucket.get(emp, 0.0) + minutes
    return agg

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
    # Extract service costs from form (service_cost_<service_name>)
    service_costs = {}
    service_types = _parse_service_types(form)
    for svc in service_types:
        # Remove "Other: " prefix if present to get the key
        svc_key = svc.replace("Other: ", "Other") if svc.startswith("Other:") else svc
        cost_val = form.get(f"service_cost_{svc_key}", "0")
        try:
            service_costs[svc] = float(cost_val) if cost_val else 0.0
        except (ValueError, TypeError):
            service_costs[svc] = 0.0

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
        "service_types":   service_types,
        "service_costs":   service_costs,
        "scope_of_work":   form.get("scope_of_work", ""),
        "expedite":        form.get("expedite", "No"),
        "rush_rate":       form.get("rush_rate", "0"),
        "rush_fee":        form.get("rush_fee", "0"),
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
            "net_terms":      form.get("net_terms", ""),
            "client_name":    form.get("client_name", ""),
            "project_number": main_project,
            "linked_projects": linked_projects,
            "status":         form.get("status", "Draft"),
            "subtotal":       form.get("subtotal", "0"),
            "tax_rate":       form.get("tax_rate", "0"),
            "tax_amount":     form.get("tax_amount", "0"),
            "total":          form.get("total", "0"),
            "notes":          form.get("notes", ""),
            "terms":          form.get("terms", ""),
            "payment_method": form.get("payment_method", ""),
        },
        "line_items": line_items,
        # Payment details (handled separately in invoice_edit to add to payment_log)
        "_payment_amount": form.get("payment_amount", ""),
        "_payment_date": form.get("payment_date", ""),
        "_payment_reference": form.get("payment_reference", ""),
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

@app.route("/quotes/<quote_id>/pdf")
@role_required("quotes")
def quote_pdf(quote_id):
    try:
        from reportlab.lib.pagesizes import letter
    except ImportError:
        flash("reportlab not installed.", "danger")
        return redirect(url_for("quote_detail", quote_id=quote_id))

    pdf_bytes = _generate_quote_pdf_bytes(quote_id)
    if not pdf_bytes:
        abort(404)

    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        abort(404)

    from flask import Response
    fname = f"Quote_{quote.get('job_number','')}.pdf"
    return Response(pdf_bytes, mimetype="application/pdf",
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
def _generate_invoice_pdf_bytes(invoice_id: str):
    """Generate invoice PDF and return as bytes. Returns None on error."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import mm, inch
    except ImportError:
        return None

    import io as _io
    from pathlib import Path
    invoice = fb_get(f"/invoices/{invoice_id}")
    if not invoice:
        return None

    meta = invoice.get("meta", {})
    co = company_info()
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=5*mm, bottomMargin=5*mm)
    styles = getSampleStyleSheet()
    story = []

    styles.add(ParagraphStyle(name='CenteredBold20', alignment=1, fontName='Helvetica-Bold', fontSize=20, leading=24))
    styles.add(ParagraphStyle(name='Centered10', alignment=1, fontName='Helvetica', fontSize=10, leading=12))
    styles.add(ParagraphStyle(name='LeftBold16', alignment=0, fontName='Helvetica-Bold', fontSize=16, leading=18))
    styles.add(ParagraphStyle(name='LeftBold12', alignment=0, fontName='Helvetica-Bold', fontSize=12, leading=14))
    styles.add(ParagraphStyle(name='Left10', alignment=0, fontName='Helvetica', fontSize=10, leading=12))
    styles.add(ParagraphStyle(name='LeftBold10', alignment=0, fontName='Helvetica-Bold', fontSize=10, leading=12))
    styles.add(ParagraphStyle(name='Right10', alignment=2, fontName='Helvetica', fontSize=10, leading=12))
    styles.add(ParagraphStyle(name='RightBold10', alignment=2, fontName='Helvetica-Bold', fontSize=10, leading=12))
    styles.add(ParagraphStyle(name='Left9', alignment=0, fontName='Helvetica', fontSize=9, leading=11))

    logo_path = Path(__file__).parent / "static" / "logo.png"
    logo_img = None
    if logo_path.exists():
        try:
            logo_img = Image(str(logo_path), width=0.95*inch, height=0.95*inch)
        except (IOError, OSError):
            pass

    company_name = co.get('name', 'MABS Engineering LLC')
    address_text = ""
    for line in co.get('address', '').split('\n'):
        if line.strip():
            address_text += f"{line.strip()}<br/>"
    contact_text = f"Phone: {co.get('phone','')} • Email: {co.get('email','')} • {co.get('website','')}"
    header_html = f"<b><font size=16>{company_name}</font></b><br/><font size=9>{address_text}{contact_text}</font>"

    if logo_img:
        hdr_table_data = [[logo_img, Paragraph(header_html, ParagraphStyle("cn", parent=styles["Normal"], fontName="Helvetica", textColor=colors.black, alignment=1))]]
        hdr_table = Table(hdr_table_data, colWidths=[0.95*inch, doc.width - 0.95*inch])
        hdr_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (1,0), (1,0), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 0), ("TOPPADDING", (0,0), (-1,-1), 0), ("LINEBELOW", (0,0), (-1,-1), 1, colors.black)]))
        story.append(hdr_table)
    else:
        story.append(Paragraph(header_html, ParagraphStyle("cn", parent=styles["Normal"], fontName="Helvetica", textColor=colors.black, alignment=1)))
        story.append(Table([['']], colWidths=[doc.width], style=[('LINEBELOW', (0,0), (-1,-1), 1, colors.black)]))

    story.append(Spacer(1, 2*mm))

    client_name = meta.get('client_name', '')
    client_email = ""
    client_address = ""
    if client_name:
        try:
            client_data = fb_get(f"/clients/{client_name}") or {}
            client_email = client_data.get("email", "")
            client_address = client_data.get("address", "")
        except Exception:
            pass

    bill_to_lines = []
    if client_name:
        bill_to_lines.append(client_name)
    if client_email:
        bill_to_lines.append(client_email)
    if client_address:
        for line in client_address.split('\n'):
            if line.strip():
                bill_to_lines.append(line.strip())
    bill_to_text = "<br/>".join(bill_to_lines) if bill_to_lines else ""

    invoice_info = f"Invoice Number: {meta.get('invoice_number','')}<br/>Date: {meta.get('invoice_date','')}<br/>Due Date: {meta.get('due_date','')}"
    header_data = [
        [Paragraph("<b>Invoice:</b>", styles['Left10']), Paragraph("<b>Bill To:</b>", styles['Left10'])],
        [Paragraph(invoice_info, styles['Left9']), Paragraph(bill_to_text, styles['Left9']) if bill_to_text else Paragraph("", styles['Left9'])],
    ]
    header_table = Table(header_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0), ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
    story.append(header_table)
    story.append(Spacer(1, 8*mm))

    story.append(Paragraph("ITEMS", ParagraphStyle("items_title", parent=styles["Normal"], fontSize=12, fontName="Helvetica-Bold", textColor=colors.black, alignment=0)))
    story.append(Spacer(1, 3*mm))

    center_bold_style = ParagraphStyle("center_bold10", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold", textColor=colors.black, alignment=1)
    center_style = ParagraphStyle("center10", parent=styles["Normal"], fontSize=10, fontName="Helvetica", textColor=colors.black, alignment=1)
    item_data = [[Paragraph(h, center_bold_style) for h in ["Project", "Project Name", "Plant", "Qty", "Unit Price", "Payment Stage", "Payment Due"]]]

    linked_projects = meta.get("linked_projects", [])
    if isinstance(linked_projects, str):
        linked_projects = [{"project_number": linked_projects}]
    elif not isinstance(linked_projects, list):
        linked_projects = []

    for idx, item in enumerate(invoice.get("line_items", [])):
        qty_val = _safe_float(item.get("quantity", 1))
        qty = str(int(qty_val)) if qty_val == int(qty_val) else str(qty_val)
        unit_price_val = _safe_float(item.get('unit_price', 0))
        unit_price = f"${unit_price_val:,.2f}"
        project_number = ""
        project_name = ""
        plant = ""
        if idx < len(linked_projects) and isinstance(linked_projects[idx], dict):
            project_number = linked_projects[idx].get("project_number", "")
            project_name = linked_projects[idx].get("project_name", "")
        if not project_number:
            project_number = meta.get("project_number", "")
        if not project_name and project_number:
            try:
                raw_proj = fb_get("/projects") or {}
                for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
                    if isinstance(pdata, dict) and pdata.get("project_number") == project_number:
                        project_name = pdata.get("project_name", "")
                        plant = pdata.get("plant", "")
                        break
            except Exception:
                pass
        if not plant:
            plant = meta.get("plant", "")
        if not project_name:
            description = item.get("description", "")
            project_name = description.split("—")[0].strip() if "—" in description else description

        payment_stage = ""
        if idx < len(linked_projects) and isinstance(linked_projects[idx], dict):
            payment_stage_index = linked_projects[idx].get("payment_stage_index")
            if payment_stage_index is not None and project_number:
                try:
                    raw_proj = fb_get("/projects") or {}
                    for pid, pdata in (raw_proj.items() if isinstance(raw_proj, dict) else []):
                        if isinstance(pdata, dict) and pdata.get("project_number") == project_number:
                            payment_stages = pdata.get("payment_stages", [])
                            if isinstance(payment_stages, list) and int(payment_stage_index) < len(payment_stages):
                                stage_data = payment_stages[int(payment_stage_index)]
                                if isinstance(stage_data, dict):
                                    payment_stage = stage_data.get("name", "")
                            break
                except Exception:
                    pass
        if not payment_stage:
            payment_stage = meta.get("payment_stage", "")
        if payment_stage and " of " in payment_stage:
            payment_stage = payment_stage.split(" of ")[0].strip()
        if not payment_stage:
            payment_stage = "Final Payment"

        payment_due_val = qty_val * unit_price_val
        payment_due = f"${payment_due_val:,.2f}"
        item_data.append([
            Paragraph(project_number, center_style),
            Paragraph(project_name, center_style),
            Paragraph(plant or "", center_style),
            Paragraph(qty, center_style),
            Paragraph(unit_price, center_style),
            Paragraph(payment_stage, center_style),
            Paragraph(payment_due, center_style)
        ])

    if len(item_data) == 1:
        item_data.append([Paragraph("", center_style) for _ in range(7)])

    item_table = Table(item_data, colWidths=[doc.width * 0.18, doc.width * 0.21, doc.width * 0.11, doc.width * 0.08, doc.width * 0.12, doc.width * 0.15, doc.width * 0.15])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#CCCCCC")),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 5*mm))

    subtotal = _safe_float(meta.get('subtotal', 0))
    tax_amount = _safe_float(meta.get('tax_amount', 0))
    tax_rate = _safe_float(meta.get('tax_rate', 0))
    total_amount = _safe_float(meta.get('total', 0))
    totals_data = [
        [Paragraph("Total", styles['Right10']), Paragraph(f"${subtotal:,.2f}", styles['Right10'])],
        [Paragraph(f"Tax ({tax_rate}%)", styles['Right10']), Paragraph(f"${tax_amount:,.2f}", styles['Right10'])],
        [Paragraph("TOTAL AMOUNT DUE:", styles['RightBold10']), Paragraph(f"${total_amount:,.2f}", styles['RightBold10'])],
    ]
    totals_table = Table(totals_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#CCCCCC")),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BACKGROUND', (0, len(totals_data)-1), (-1, len(totals_data)-1), colors.lightgrey),
        ('FONTNAME', (0, len(totals_data)-1), (-1, len(totals_data)-1), 'Helvetica-Bold'),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("PAYMENT OPTIONS", styles['LeftBold12']))
    story.append(Spacer(1, 3*mm))

    InvLabel = ParagraphStyle("InvLabel", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold", textColor=colors.black, leading=12)
    InvValue = ParagraphStyle("InvValue", parent=styles["Normal"], fontSize=9, fontName="Helvetica", textColor=colors.black, leading=11, leftIndent=3, spaceAfter=3)
    TableCenter = ParagraphStyle("TableCenter", parent=styles["Normal"], fontSize=8, fontName="Helvetica", textColor=colors.black, alignment=1)

    qr_path = Path(__file__).parent / "static" / "venmo.png"
    qr_img = None
    if qr_path.exists():
        try:
            qr_img = Image(str(qr_path), width=1.0*inch, height=1.0*inch)
        except (IOError, OSError):
            qr_img = None

    right_section = [
        Table([[Paragraph("<b>Option 2: Zelle QR code</b>", InvLabel)]], colWidths=[doc.width * 0.40], rowHeights=[8*mm],
              style=TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#B6D7A8")), ("BOX", (0,0), (-1,-1), 0.8, colors.black), ("ALIGN", (0,0), (-1,-1), "LEFT"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2), ("LEFTPADDING", (0,0), (-1,-1), 3)])),
        Spacer(1, 1*mm),
    ]
    if qr_img:
        right_section.append(Table([[qr_img]], colWidths=[doc.width * 0.40],
                                   style=TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 1*mm), ("BOTTOMPADDING", (0,0), (-1,-1), 1*mm)])))
    right_section.append(Paragraph("Scan to pay with Zelle", TableCenter))

    left_section = [
        Table([[Paragraph("<b>Option 1: Check</b>", InvLabel)]], colWidths=[doc.width * 0.55], rowHeights=[7*mm],
              style=TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#B6DDE8")), ("BOX", (0,0), (-1,-1), 0.8, colors.black), ("ALIGN", (0,0), (-1,-1), "LEFT"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2), ("LEFTPADDING", (0,0), (-1,-1), 3)])),
        Spacer(1, 1*mm),
        Paragraph("<b>Payable to:</b> MABS Engineering LLC<br/><b>Mailing Address:</b> 15455 Manchester Rd, PO Box 1144 Manchester, MO 63011", InvValue),
        Spacer(1, 4*mm),
        Table([[Paragraph("<b>Option 3: Bank ACH Transfer</b>", InvLabel)]], colWidths=[doc.width * 0.55], rowHeights=[7*mm],
              style=TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#EA9999")), ("BOX", (0,0), (-1,-1), 0.8, colors.black), ("ALIGN", (0,0), (-1,-1), "LEFT"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 2), ("BOTTOMPADDING", (0,0), (-1,-1), 2), ("LEFTPADDING", (0,0), (-1,-1), 3)])),
        Spacer(1, 1*mm),
        Paragraph("Please contact MABS Admin to get our bank information for ACH transfers", InvValue),
    ]

    payment_table = Table([[left_section, right_section]], colWidths=[doc.width * 0.55, doc.width * 0.40])
    payment_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0), ('TOPPADDING', (0,0), (-1,-1), 0), ('BOTTOMPADDING', (0,0), (-1,-1), 0), ('BOX', (0,0), (-1,-1), 1, colors.black), ('INNERGRID', (0,0), (-1,-1), 0.5, colors.black)]))
    story.append(payment_table)

    story.append(Spacer(1, 3*mm))
    default_terms = co.get('default_terms', 'Thank you for your business! Best regards, MABS Engineering LLC')
    notes_text = default_terms if default_terms else meta.get('notes', 'Thank you for your business!')
    story.append(Paragraph(f"<b>Note:</b> {notes_text}", styles['Left9']))

    calculated_status = _calculate_invoice_status(invoice)
    if (calculated_status or "").lower() == 'paid':
        def add_paid_watermark(canvas_obj, doc_obj):
            canvas_obj.saveState()
            center_x = A4[0] / 2
            center_y = A4[1] / 2
            canvas_obj.setFont("Helvetica-Bold", 130)
            canvas_obj.setFillColor(colors.HexColor("#00B050"))
            canvas_obj.setFillAlpha(0.25)
            canvas_obj.translate(center_x, center_y)
            canvas_obj.rotate(45)
            canvas_obj.drawCentredString(0, 0, "PAID")
            canvas_obj.restoreState()
        doc.build(story, onFirstPage=add_paid_watermark, onLaterPages=add_paid_watermark)
    else:
        doc.build(story)

    buf.seek(0)
    return buf.getvalue()

def _send_invoice_email(invoice_id: str):
    """Send invoice professional text email + PDF attachment to the client. Returns (ok: bool, message: str)."""
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

    # Company info for signature
    company_name = co.get('name', 'MABS Engineering LLC')
    company_address = co.get('address', '15455 Manchester Rd, PO Box 1144, Manchester, MO 63011')
    company_email = co.get('email', 'info@mabs-engineering.com')
    company_phone = co.get('phone', '(314) 585-2003')

    signature = f"""{company_name}
{company_address}
{company_email}
{company_phone}"""

    # Professional text email
    invoice_number = meta.get('invoice_number', '')
    invoice_status = str(meta.get('status', 'Draft')).strip()  # Status values: Draft, Sent, Viewed, Paid, Partial, Overdue, Cancelled
    total_due = _safe_float(meta.get('total', 0))
    due_date = meta.get('due_date', '')
    paid_date = meta.get('paid_date', '')

    company_name = co.get('name', 'MABS Engineering LLC')
    company_address = co.get('address', '15455 Manchester Rd, PO Box 1144, Manchester, MO 63011')
    company_email = co.get('email', 'info@mabs-engineering.com')
    company_phone = co.get('phone', '(314) 585-2003')

    # Check if invoice is paid (handle capitalization and spacing)
    is_paid = invoice_status.lower() == 'paid'
    log.info(f"Invoice {invoice_number} status: '{invoice_status}' → is_paid: {is_paid}")

    if is_paid:
        # PAID INVOICE EMAIL
        text_body = f"""Hi {client_name},

Please find the attached paid invoice for your records.

Invoice Details:
Invoice Number: {invoice_number}
Amount Paid: ${total_due:,.2f}
Payment Date: {paid_date or 'Received'}

Thank you for your payment. If you require any additional information, please let us know.

Best regards,
{company_name}
{company_address}
{company_email}
{company_phone}
"""
        subject = f"{invoice_number} – Payment Received"
    else:
        # UNPAID INVOICE EMAIL
        text_body = f"""Hi {client_name},

Please find the attached invoice for your review.

Invoice Details:
Invoice Number: {invoice_number}
Amount Due: ${total_due:,.2f}
Due Date: {due_date}

Please review the attached invoice at your convenience. If you have any questions or require additional information, please feel free to contact us.

Thank you for your business. We appreciate your continued trust and support.

Best regards,
{company_name}
{company_address}
{company_email}
{company_phone}
"""
        subject = f"You have a new invoice from {company_name} ({invoice_number})"

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"]    = f"{em.get('from_name', co.get('name',''))} <{em.get('smtp_user','')}>"
        msg["To"]      = client_email

        msg.attach(MIMEText(text_body, "plain"))

        try:
            pdf_bytes = _generate_invoice_pdf_bytes(invoice_id)
            if pdf_bytes:
                from email.mime.base import MIMEBase
                from email import encoders
                pdf_part = MIMEBase("application", "octet-stream")
                pdf_part.set_payload(pdf_bytes)
                encoders.encode_base64(pdf_part)
                pdf_part.add_header("Content-Disposition", "attachment",
                                   filename=f"Invoice_{meta.get('invoice_number','')}.pdf")
                msg.attach(pdf_part)
        except Exception as pdf_err:
            log.warning("Could not attach PDF to invoice email: %s", pdf_err)

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

def _generate_quote_pdf_bytes(quote_id: str):
    """Generate quote PDF and return as bytes. Returns None on error."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch, mm
        from pathlib import Path
    except ImportError:
        return None

    import io as _io
    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        return None

    co = company_info()
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.35*inch, rightMargin=0.35*inch,
                            topMargin=0.08*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elems = []

    dark_gray = colors.HexColor("#333333")
    light_blue = colors.HexColor("#B6DDE8")
    light_green = colors.HexColor("#B6D7A8")
    light_red = colors.HexColor("#EA9999")
    border_col = colors.HexColor("#000000")
    teal_line = colors.HexColor("#0D9488")

    form_label = ParagraphStyle("fl", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold", textColor=dark_gray)
    form_value = ParagraphStyle("fv", parent=styles["Normal"], fontSize=9, fontName="Helvetica", textColor=dark_gray)
    section_title = ParagraphStyle("st", parent=styles["Normal"], fontSize=11, fontName="Helvetica-Bold", textColor=dark_gray)
    checkbox_style = ParagraphStyle("cs", parent=styles["Normal"], fontSize=8, fontName="Helvetica", textColor=dark_gray)

    logo_path = Path(__file__).parent / "static" / "logo.png"
    if logo_path.exists():
        try:
            logo = Image(str(logo_path), width=1.0*inch, height=0.85*inch)
            hdr_data = [[logo, Paragraph(f"<b>{co.get('name','MABS Engineering LLC')}</b>", ParagraphStyle("cn", parent=styles["Normal"], fontSize=22, fontName="Helvetica-Bold", textColor=dark_gray, alignment=1))]]
            hdr = Table(hdr_data, colWidths=[1.0*inch, doc.width - 1.0*inch])
            hdr.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ALIGN", (1,0), (1,0), "CENTER"), ("LINEBELOW", (0,0), (-1,-1), 2, teal_line), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (1,0), (1,0), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0)]))
            elems.append(hdr)
        except (IOError, OSError):
            elems.append(Paragraph(co.get('name','MABS Engineering LLC'), ParagraphStyle("cn", parent=styles["Normal"], fontSize=16, fontName="Helvetica-Bold", textColor=dark_gray)))

    elems.append(Spacer(1, 0.08*inch))

    sales_person = quote.get('salesperson', '')
    fixed_sales_width = 2.0*inch
    center_width = (doc.width - fixed_sales_width) / 2
    right_width = (doc.width - fixed_sales_width) / 2

    title_data = [
        [
            Paragraph(f"<b>Sales: {sales_person}</b>" if sales_person else "", ParagraphStyle("sp", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold", textColor=dark_gray, alignment=1)),
            Paragraph("<u>New Job Request Form</u>", ParagraphStyle("title", parent=styles["Normal"], fontSize=12, fontName="Helvetica-Bold", textColor=dark_gray, alignment=1)),
            Paragraph("", ParagraphStyle("title", parent=styles["Normal"]))
        ]
    ]

    title_table = Table(title_data, colWidths=[fixed_sales_width, center_width, right_width])

    table_style = [
        ('ALIGN', (1,0), (1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]

    if sales_person:
        table_style.extend([
            ('BACKGROUND', (0,0), (0,0), colors.HexColor("#D9EEF7")),
            ('BORDER', (0,0), (0,0), 1, colors.HexColor("#5B9DBE")),
            ('ALIGN', (0,0), (0,0), 'CENTER'),
            ('LEFTPADDING', (0,0), (0,0), 3),
            ('RIGHTPADDING', (0,0), (0,0), 3),
            ('TOPPADDING', (0,0), (0,0), 2),
            ('BOTTOMPADDING', (0,0), (0,0), 2),
        ])

    title_table.setStyle(TableStyle(table_style))
    elems.append(title_table)
    elems.append(Spacer(1, 0.05*inch))
    elems.append(Spacer(1, 0.15*inch))

    def add_form_field(label, value):
        field_table = Table(
            [[Paragraph(f"<b>{label}</b>", form_label), Paragraph(":", form_label), Paragraph(value, form_value)]],
            colWidths=[55*mm, 5*mm, doc.width - 60*mm]
        )
        field_table.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,-1), 2),
        ]))
        elems.append(field_table)

    add_form_field("Quote Number", quote.get('job_number',''))
    add_form_field("Client / Company Name", quote.get('client_name',''))
    add_form_field("Project Name", quote.get('project_name',''))
    add_form_field("Scope of Work", quote.get('description',''))

    elems.append(Spacer(1, 1*mm))

    eng_rows = [
        [Paragraph("<b>Engineering Costs:</b>", section_title)]
    ]
    eng_cost_style = ParagraphStyle("ec", parent=styles["Normal"], fontSize=9, fontName="Helvetica", textColor=dark_gray, leftIndent=8*mm)

    agreed_cost = quote.get('subtotal', '')
    expedite = quote.get('is_expedited', False)
    expedite_amount = quote.get('rush_fee', '') or quote.get('rushFee', '')
    total_amount = quote.get('total', '')

    if agreed_cost:
        agreed_cost_val = str(agreed_cost).replace('$', '').strip()
        expedite_checkbox = "[✓]" if expedite else "[ ]"
        if expedite and expedite_amount and str(expedite_amount).strip():
            expedite_val = str(expedite_amount).replace('$', '').strip()
        else:
            expedite_val = "________"
        cost_line = f"Agreed Cost: {agreed_cost_val}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>Expedite? {expedite_checkbox} Yes, 50% Extra ( ) No:</b> {expedite_val}"
    else:
        cost_line = "Agreed Cost: ________&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>Expedite? ( ) Yes, 50% Extra ( ) No:</b> ________"

    eng_rows.append([Paragraph(cost_line, eng_cost_style)])

    if total_amount:
        try:
            total_val = float(str(total_amount).replace('$', '').strip())
            total_line = f"<b>TOTAL: ${total_val:,.2f}</b>"
        except (ValueError, TypeError):
            total_line = "TOTAL: ________"
    else:
        total_line = "TOTAL: ________"

    eng_rows.append([Paragraph(total_line, eng_cost_style)])

    eng_table = Table(eng_rows, colWidths=[doc.width])
    eng_table.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 1.5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    elems.append(eng_table)
    elems.append(Spacer(1, 1.5*mm))

    elems.append(Paragraph("<b>In the case of Court Appearance or Disposition:</b> N/A", form_value))
    elems.append(Paragraph("Rate: $250/hour (portal-to-portal)", form_value))
    elems.append(Spacer(1, 0.12*inch))

    def add_section_title(label):
        title_para = Paragraph(f"<b>{label}</b>", section_title)
        title_table = Table([[title_para]], colWidths=[doc.width])
        title_table.setStyle(TableStyle([
            ("TEXTCOLOR", (0,0), (-1,-1), dark_gray),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,-1), 1),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ]))
        elems.append(title_table)
        elems.append(Spacer(1, 0.5*mm))

    add_section_title("Services Required :")

    all_services = ["Mechanical", "Electrical", "Civil", "Structural", "Plumbing", "HVAC", "Fire Protection", "Geotechnical", "Environmental", "Other"]

    selected_services = quote.get('service_types', [])

    custom_services = [svc for svc in selected_services if svc not in all_services]

    svc_items = []
    for svc in all_services:
        if svc == "Other" and custom_services:
            continue

        if svc in selected_services:
            svc_items.append(f"[✓] {svc}")
        else:
            svc_items.append(f"[ ] {svc}")

    for svc in custom_services:
        svc_items.append(f"[✓] {svc}")

    svc_grid = []
    for i in range(0, len(svc_items), 3):
        row = []
        for j in range(3):
            if i+j < len(svc_items):
                row.append(Paragraph(svc_items[i+j], checkbox_style))
            else:
                row.append(Paragraph("", checkbox_style))
        svc_grid.append(row)

    if not svc_grid:
        svc_grid = [[Paragraph("[ ] Mechanical", checkbox_style), Paragraph("[ ] Electrical", checkbox_style), Paragraph("[ ] Civil", checkbox_style)],
                    [Paragraph("[ ] Structural", checkbox_style), Paragraph("[ ] Plumbing", checkbox_style), Paragraph("[ ] HVAC", checkbox_style)],
                    [Paragraph("[ ] Fire Protection", checkbox_style), Paragraph("[ ] Geotechnical", checkbox_style), Paragraph("[ ] Environmental", checkbox_style)],
                    [Paragraph("[ ] Other", checkbox_style), Paragraph("", checkbox_style), Paragraph("", checkbox_style)]]

    svc_table = Table(svc_grid, colWidths=[doc.width/3, doc.width/3, doc.width/3])
    svc_table.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING", (0,0), (-1,-1), 1),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    elems.append(svc_table)
    elems.append(Spacer(1, 1.5*mm))

    elems.append(Spacer(1, 1.5*mm))
    add_section_title("Payment Information")

    pay_warning_table = Table([
        [Paragraph("<b>A 50% DOWN PAYMENT IS REQUIRED TO INITIATE</b>", ParagraphStyle("warning", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold", textColor=colors.red, alignment=1))]
    ], colWidths=[doc.width])
    pay_warning_table.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 1, border_col),
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 1*mm),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1*mm),
    ]))
    elems.append(pay_warning_table)

    qr_path = Path(__file__).parent / "static" / "venmo.png"
    qr_image = None
    if qr_path.exists():
        try:
            qr_image = Image(str(qr_path), width=35*mm, height=35*mm)
        except:
            pass

    available_width = doc.width

    left_section = [
        Table(
            [[Paragraph("<b>Option 1: Check</b>", form_label)]],
            colWidths=[available_width * 0.60],
            rowHeights=[7*mm],
            style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), light_blue),
                ("BOX", (0,0), (-1,-1), 0.7, colors.black),
                ("ALIGN", (0,0), (-1,-1), "LEFT"),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ])
        ),
        Table(
            [[Paragraph(f"<b>Payable to:</b> {co.get('name','MABS Engineering LLC')}<br/><b>Mailing Address:</b> 15455 Manchester Rd, PO Box 1144 Manchester, MO 63011", form_value)]],
            colWidths=[available_width * 0.60],
            style=TableStyle([
                ("ALIGN", (0,0), (-1,-1), "LEFT"),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 4*mm),
            ])
        ),
        Table(
            [[Paragraph("<b>Option 3: Bank ACH Transfer</b>", form_label)]],
            colWidths=[available_width * 0.60],
            rowHeights=[7*mm],
            style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), light_red),
                ("BOX", (0,0), (-1,-1), 0.7, colors.black),
                ("ALIGN", (0,0), (-1,-1), "LEFT"),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ])
        ),
        Table(
            [[Paragraph("<b>Account Type:</b> Checking<br/><b>Bank Name:</b> BMO Harris Bank<br/><b>Routing Number:</b> 071025661<br/><b>Acct. Number:</b> 4834994317", form_value)]],
            colWidths=[available_width * 0.60],
            style=TableStyle([
                ("ALIGN", (0,0), (-1,-1), "LEFT"),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 4*mm),
            ])
        ),
    ]

    right_section = [
        Table(
            [[Paragraph("<b>Option 2: Zelle QR code</b>", form_label)]],
            colWidths=[available_width * 0.40],
            rowHeights=[7*mm],
            style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), light_green),
                ("BOX", (0,0), (-1,-1), 0.8, colors.black),
                ("ALIGN", (0,0), (-1,-1), "LEFT"),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ])
        ),
        Spacer(1, 1*mm),
    ]

    if qr_image:
        right_section.append(
            Table(
                [[qr_image]],
                style=TableStyle([
                    ("ALIGN", (0,0), (-1,-1), "CENTER"),
                    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                    ("TOPPADDING", (0,0), (-1,-1), 1*mm),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 1*mm),
                ])
            )
        )

    right_section.append(
        Paragraph(
            "Scan to pay with Zelle",
            ParagraphStyle("qr_text", parent=styles["Normal"], fontSize=8, alignment=1)
        )
    )

    payment_data = [[left_section, right_section]]
    pay_table = Table(
        payment_data,
        colWidths=[available_width * 0.60, available_width * 0.40]
    )

    pay_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.black),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))

    elems.append(pay_table)
    elems.append(Spacer(1, 1*mm))

    elems.append(Spacer(1, 1.5*mm))

    agreement_title = Paragraph("<b>Client Agreement :</b>", section_title)
    agreement_title_table = Table([[agreement_title]], colWidths=[doc.width])
    agreement_title_table.setStyle(TableStyle([
        ("TEXTCOLOR", (0,0), (-1,-1), dark_gray),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1),
        ("TOPPADDING", (0,0), (-1,-1), 1),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
    ]))
    elems.append(agreement_title_table)
    elems.append(Spacer(1, 0.6*mm))

    agreement_style = ParagraphStyle(
        "agreement",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=dark_gray,
        leftIndent=20,
    )

    elems.append(Spacer(1, 0.5*mm))
    elems.append(Paragraph(
        "By signing below, the client agrees to provide necessary documents, respond to RFIs within 3 business days, "
        "and acknowledges that deliverables will be considered final if no response is received within 10 business days.",
        agreement_style
    ))

    elems.append(Spacer(1, 1.5*mm))

    sig_table = Table([
        [Paragraph("Client Signature :", form_value), Paragraph("Date :", form_value)]
    ], colWidths=[doc.width * 0.75, doc.width * 0.25])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
    ]))
    elems.append(sig_table)
    elems.append(Spacer(1, -2*mm))

    def quote_footer(canvas, doc_obj):
        canvas.saveState()

        footer_blue = colors.HexColor("#003D82")

        canvas.setLineWidth(0.5)
        canvas.setStrokeColor(footer_blue)
        canvas.line(doc_obj.leftMargin, 0.72*inch, doc_obj.width + doc_obj.leftMargin, 0.72*inch)

        footer_style = ParagraphStyle(
            name="FooterStyle",
            alignment=1,
            fontName="Helvetica",
            fontSize=7,
            textColor=footer_blue,
            leading=9
        )

        footer_lines = [
            "Note: As the CEO of MABS Engineering LLC, Dr. Ashiq reserves the right to change or cancel this policy at any time, at his discretion.",
            f"Address: {co.get('address','15455 Manchester Rd, PO Box 1144, Ballwin, MO 63011')}",
            f"Telephone: {co.get('phone','(314) 585-2003')} • {co.get('email','info@mabs-engineering.com')}",
            co.get('website','www.mabs-engineering.com')
        ]

        y_position = 0.55*inch

        for line in footer_lines:
            p = Paragraph(line, footer_style)
            w, h = p.wrap(doc_obj.width - 1*inch, 12*mm)
            p.drawOn(canvas, doc_obj.leftMargin + 0.5*inch, y_position)
            y_position -= 3*mm

        canvas.restoreState()

    doc.build(elems, onFirstPage=quote_footer, onLaterPages=quote_footer)
    buf.seek(0)
    return buf.getvalue()

def _send_quote_email(quote_id: str):
    """Send quote professional text email + PDF attachment to the client. Returns (ok: bool, message: str)."""
    settings = load_settings()
    em = settings.get("email", {})

    if not em.get("enabled"):
        return False, "Email sending is disabled. Enable it in Settings → Email/SMTP."

    quote = fb_get(f"/job_forms/{quote_id}")
    if not quote:
        return False, "Quote not found."

    client_name = quote.get("client_name", "")
    client_data = fb_get(f"/clients/{client_name}") or {}
    client_email = client_data.get("email", "")
    if not client_email:
        return False, f"No email on file for '{client_name}'. Add it in Clients."

    co = company_info()

    # Get scope/description
    scope = quote.get('description', '').strip() or quote.get('scope', '').strip()
    project_name = quote.get('project_name', '').strip()

    # Company info for signature
    company_name = co.get('name', 'MABS Engineering LLC')
    company_address = co.get('address', '15455 Manchester Rd, PO Box 1144, Manchester, MO 63011')
    company_email = co.get('email', 'info@mabs-engineering.com')
    company_phone = co.get('phone', '(314) 585-2003')

    signature = f"""{company_name}
{company_address}
{company_email}
{company_phone}"""

    # Determine conditions
    has_project = bool(project_name)
    has_scope = bool(scope)

    # Build email based on conditions
    if has_project and has_scope:
        # Case 1: Project + Services
        text_body = f"""Hi {client_name},

Thank you for considering us for your {project_name} project. We've prepared a detailed quote for the {scope}.

The attached PDF shows the complete breakdown. Please let me know if you have any questions.

Best regards,

{signature}
"""
    elif has_project and not has_scope:
        # Case 2: Project + NO Services
        text_body = f"""Hi {client_name},

Thank you for considering us for your {project_name} project. We've prepared a detailed quote.

The attached PDF shows the complete breakdown. Please let me know if you have any questions.

Best regards,

{signature}
"""
    elif not has_project and has_scope:
        # Case 3: NO Project + Services
        text_body = f"""Hi {client_name},

Thank you for considering us for your project. We've prepared a detailed quote for the {scope}.

The attached PDF shows the complete breakdown. Please let me know if you have any questions.

Best regards,

{signature}
"""
    else:
        # Case 4: NO Project + NO Services
        text_body = f"""Hi {client_name},

Thank you for considering us for your project. We've prepared a detailed quote.

The attached PDF shows the complete breakdown. Please let me know if you have any questions.

Best regards,

{signature}
"""

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"Quote from {co.get('name','')} - {quote.get('job_number','')}"
        msg["From"]    = f"{em.get('from_name', co.get('name',''))} <{em.get('smtp_user','')}>"
        msg["To"]      = client_email

        msg.attach(MIMEText(text_body, "plain"))

        try:
            pdf_bytes = _generate_quote_pdf_bytes(quote_id)
            if pdf_bytes:
                from email.mime.base import MIMEBase
                from email import encoders
                pdf_part = MIMEBase("application", "octet-stream")
                pdf_part.set_payload(pdf_bytes)
                encoders.encode_base64(pdf_part)
                pdf_part.add_header("Content-Disposition", "attachment",
                                   filename=f"Quote_{quote.get('job_number','')}.pdf")
                msg.attach(pdf_part)
        except Exception as pdf_err:
            log.warning("Could not attach PDF to quote email: %s", pdf_err)

        with smtplib.SMTP(em.get("smtp_host", "smtp.gmail.com"),
                          int(em.get("smtp_port", 587))) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(em.get("smtp_user", ""), em.get("smtp_password", ""))
            srv.sendmail(em.get("smtp_user", ""), [client_email], msg.as_string())

        return True, f"Quote emailed to {client_email}."
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
        inv_data = fb_get(f"/invoices/{invoice_id}") or {}
        for proj_num in _invoice_linked_projects(inv_data):
            _advance_project_to_in_progress(proj_num)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("invoice_detail", invoice_id=invoice_id))

@app.route("/quotes/<quote_id>/send", methods=["POST"])
@role_required("quotes")
def quote_send(quote_id):
    ok, msg = _send_quote_email(quote_id)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("quote_detail", quote_id=quote_id))

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

    # Get invoice metadata for additional context
    inv_meta = inv_data.get("meta", {}) or {}

    payment_entry = {
        "amount":     str(amount),
        "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
        "method":     request.form.get("method", ""),
        "reference":  request.form.get("reference", ""),
        "notes":      request.form.get("notes", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Metadata for tracking
        "invoice_number": inv_meta.get("invoice_number", ""),
        "stage_name": inv_meta.get("payment_stage", ""),
        "stage_index": inv_meta.get("payment_stage_index", ""),
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

    # Use sequential allocation for ALL invoices - it handles both single and multi-project
    # This ensures stage.amount_paid is always updated the same way
    _allocate_invoice_payment_sequential(invoice_id)

    # Update project stage payment statuses based on payments (after allocation)
    # Must do this BEFORE _sync_project_payment since it updates payment_stages
    _update_project_stage_payment_status(invoice_id)

    # Sync project-level amount_paid (sum of all stages for each project)
    # This MUST run AFTER _update_project_stage_payment_status to override its data
    # Get fresh invoice data to ensure we have correct metadata after Firebase updates
    fresh_inv = fb_get(f"/invoices/{invoice_id}") or inv_data
    linked_projects = _invoice_linked_projects(fresh_inv)
    for proj_num in linked_projects:
        _sync_project_payment(proj_num)
        # Complete the project once its own amount_paid covers its contract value
        # (checked per-project, so this also fires for multi-project invoices)
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

    # Use sequential allocation for ALL invoices - it handles both single and multi-project
    # This ensures stage.amount_paid is always updated the same way
    _allocate_invoice_payment_sequential(invoice_id)

    # Update project stage payment statuses based on payments (after allocation)
    # Must do this BEFORE _sync_project_payment since it updates payment_stages
    _update_project_stage_payment_status(invoice_id)

    # Sync project-level amount_paid (sum of all stages for each project)
    # This MUST run AFTER _update_project_stage_payment_status to override its data
    # Get fresh invoice data to ensure we have correct metadata after Firebase updates
    fresh_inv = fb_get(f"/invoices/{invoice_id}") or inv_data
    linked_projects = _invoice_linked_projects(fresh_inv)
    for proj_num in linked_projects:
        _sync_project_payment(proj_num)
        # Complete the project once its own amount_paid covers its contract value
        # (checked per-project, so this also fires for multi-project invoices)
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

    # If no linked_projects, build from main_project
    if not linked_projects and main_project:
        linked_projects = [{"project_number": main_project, "payment_stage_index": meta.get("payment_stage_index", 0)}]

    # Step 1: For multi-project invoices, skip single primary_project allocation
    # Go straight to sequential distribution across all linked_projects (sorted)
    # For single-project invoices, handle main_project normally
    is_multi = len(linked_projects) > 1

    if not is_multi and remaining_to_distribute > 0 and main_project:
        # Single-project invoice: allocate to main_project
        # Calculate total project invoice amount from line items (excluding tax)
        proj_amount = 0
        for item in line_items:
            if isinstance(item, dict):
                proj_amount += _safe_float(item.get("amount", 0))

        if proj_amount > 0:
            # Calculate how much this project has already received
            proj_received = sum(
                _safe_float(p.get("amount", 0))
                for p in payment_log
                if p.get("project_number") == main_project
            )

            # How much more does this project need?
            proj_needs = max(0, proj_amount - proj_received)

            if proj_needs > 0:
                # Distribute amount to this project
                distribute_to_proj = min(proj_needs, remaining_to_distribute)

                # Determine stage name - try multiple sources
                _stage_name = meta.get("payment_stage", "")
                _stage_idx = meta.get("payment_stage_index")

                # Convert stage_index to int if available
                if _stage_idx is not None:
                    try:
                        _stage_idx = int(_stage_idx) if not isinstance(_stage_idx, int) else _stage_idx
                    except (ValueError, TypeError):
                        _stage_idx = None

                # If stage_name is empty but we have stage_index, generate a fallback
                if not _stage_name and _stage_idx is not None:
                    _stage_name = f"Stage {_stage_idx + 1}"

                payment_entry = {
                    "amount":     str(distribute_to_proj),
                    "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "method":     request.form.get("method", ""),
                    "reference":  request.form.get("reference", ""),
                    "notes":      request.form.get("notes", ""),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project_number": main_project,
                    # Metadata for tracking
                    "invoice_number": meta.get("invoice_number", ""),
                    "stage_name": _stage_name,
                    "stage_index": _stage_idx or "",
                }
                payment_log.append(payment_entry)
                remaining_to_distribute -= distribute_to_proj
                log.info(f"[PAYMENT_DIST] Recorded ${distribute_to_proj} payment for project {main_project}")

    # Fallback: if still have remaining_to_distribute and linked_projects, distribute there too
    elif remaining_to_distribute > 0 and linked_projects:
        # SORT linked_projects by project number (001, 002, 003...) before distributing
        # Handle both dict and string formats
        def get_sort_key(x):
            proj_num = x.get("project_number", "") if isinstance(x, dict) else x
            if proj_num and proj_num[-3:].isdigit():
                return int(proj_num[-3:])
            return proj_num
        sorted_projects = sorted(linked_projects, key=get_sort_key)
        for proj_info in sorted_projects:
            if remaining_to_distribute <= 0:
                continue

            # Handle both dict and string formats for project_info
            if isinstance(proj_info, dict):
                project_number = proj_info.get("project_number", "")
            else:
                project_number = proj_info
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

                # Determine stage name - try multiple sources
                _stage_name = meta.get("payment_stage", "")
                _stage_idx = meta.get("payment_stage_index")

                # Convert stage_index to int if available
                if _stage_idx is not None:
                    try:
                        _stage_idx = int(_stage_idx) if not isinstance(_stage_idx, int) else _stage_idx
                    except (ValueError, TypeError):
                        _stage_idx = None

                # If stage_name is empty but we have stage_index, generate a fallback
                if not _stage_name and _stage_idx is not None:
                    _stage_name = f"Stage {_stage_idx + 1}"

                payment_entry = {
                    "amount":     str(distribute_to_proj),
                    "date":       request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "method":     request.form.get("method", ""),
                    "reference":  request.form.get("reference", ""),
                    "notes":      request.form.get("notes", ""),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project_number": project_number,
                    # Metadata for tracking
                    "invoice_number": meta.get("invoice_number", ""),
                    "stage_name": _stage_name,
                    "stage_index": _stage_idx or "",
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

    log.info(f"[FIREBASE_SAVE] Saving payment_log with {len(payment_log)} entries for invoice {invoice_id}")
    log.info(f"[STATUS_UPDATE] Setting invoice status to: {new_status}")
    fb_update(f"/invoices/{invoice_id}", {
        "payment_log":      payment_log,
        "meta/amount_paid": str(amount_paid),
        "meta/tax_paid":    str(tax_paid),
        "meta/status":      new_status,
        "meta/updated_at":  datetime.now(timezone.utc).isoformat(),
    })
    log.info(f"[FIREBASE_SAVED] Invoice updated successfully with status={new_status}")

    # Use sequential allocation for multi-project invoices FIRST
    # Then update stage statuses using the allocated amounts
    log.info(f"[PAYMENT] Recording ${amount} for invoice {invoice_id}, updating stage statuses")
    fresh_inv = fb_get(f"/invoices/{invoice_id}") or inv_data
    linked_projects = _invoice_linked_projects(fresh_inv)
    if len(linked_projects) > 1:
        _allocate_invoice_payment_sequential(invoice_id)

    # Update project stage payment statuses (after allocation)
    _update_project_stage_payment_status(invoice_id)

    # Sync project-level amount_paid (sum of all stages for each project)
    # This MUST run AFTER both allocation and status update
    # This ensures Financial Summary shows TOTAL of all stages, not just this invoice
    for proj_num in linked_projects:
        _sync_project_payment(proj_num)
        # Complete the project once its own amount_paid covers its contract value
        # (checked per-project, so this also fires for multi-project invoices)
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
    # Use sequential allocation for ALL invoices - ensures both project.amount_paid and stage.amount_paid are updated
    _allocate_invoice_payment_sequential(invoice_id)

    # Sync project-level amount_paid (sum of all invoices for each project)
    # Use fresh invoice data after sequential allocation
    fresh_inv = fb_get(f"/invoices/{invoice_id}") or inv_data
    linked_projects = _invoice_linked_projects(fresh_inv)
    for proj_num in linked_projects:
        _sync_project_payment(proj_num)

    # Update project stage payment statuses based on payments (after allocation)
    _update_project_stage_payment_status(invoice_id)

    # Update project status based on remaining payments
    linked_projects = _invoice_linked_projects(fresh_inv)
    for proj_num in linked_projects:
        proj_id, pdata = _find_project_by_number(proj_num)
        if proj_id and pdata:
            amount_paid = _safe_float(pdata.get("amount_paid", 0))
            current_status = pdata.get("status", "Not Started")
            # If still has payments, change to In Progress
            if amount_paid > 0 and current_status == "Completed":
                fb_update(f"/projects/{proj_id}", {
                    "status": "In Progress",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
            # If no payments left, change to Not Started
            elif amount_paid == 0 and current_status != "Not Started":
                fb_update(f"/projects/{proj_id}", {
                    "status": "Not Started",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })

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

    # Update project status based on remaining payments
    linked_projects = _invoice_linked_projects(fresh_inv)
    for proj_num in linked_projects:
        proj_id, pdata = _find_project_by_number(proj_num)
        if proj_id and pdata:
            amount_paid = _safe_float(pdata.get("amount_paid", 0))
            current_status = pdata.get("status", "Not Started")
            # If still has payments, change to In Progress
            if amount_paid > 0 and current_status == "Completed":
                fb_update(f"/projects/{proj_id}", {
                    "status": "In Progress",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
            # If no payments left, change to Not Started
            elif amount_paid == 0 and current_status != "Not Started":
                fb_update(f"/projects/{proj_id}", {
                    "status": "Not Started",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })

    return jsonify({"success": True}), 200

@app.route("/invoicing/<invoice_id>/payment/<int:idx>/edit", methods=["POST"])
@role_required("invoicing")
def payment_edit(invoice_id, idx):
    """Update a payment entry in the log."""
    inv_data = fb_get(f"/invoices/{invoice_id}") or {}
    meta = inv_data.get("meta", {})
    log = inv_data.get("payment_log", [])

    if not isinstance(log, list) or idx >= len(log):
        return jsonify({"error": "Payment not found"}), 404

    # New amount being set
    new_amount = _safe_float(request.form.get("amount", 0))
    if new_amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    # Old amount at this index
    old_amount = _safe_float(log[idx].get("amount", 0))
    amount_changed = abs(new_amount - old_amount) > 0.01

    # If only updating fields (date, method, etc.) without amount change, do simple update
    if not amount_changed:
        # Just update the single payment entry's fields
        log[idx].update({
            "amount": str(new_amount),
            "date": request.form.get("date", log[idx].get("date", "")),
            "method": request.form.get("method", ""),
            "reference": request.form.get("reference", ""),
            "notes": request.form.get("notes", ""),
        })

        invoice_paid = sum(_safe_float(p.get("amount", 0)) for p in log)
        fresh_inv = dict(inv_data)
        fresh_inv["payment_log"] = log
        fresh_inv["meta"] = meta
        new_status = _calculate_invoice_status(fresh_inv)

        meta["amount_paid"] = str(invoice_paid)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        fb_update(f"/invoices/{invoice_id}", {
            "payment_log": log,
            "meta/amount_paid": str(invoice_paid),
            "meta/status": new_status,
            "meta/updated_at": meta.get("updated_at"),
        })

        # Update project stages
        _update_project_stage_payment_status(invoice_id)
        return jsonify({"success": True}), 200

    # Amount changed - need to rebuild payment_log with sequential distribution
    # New total paid = (old total - old_amount) + new_amount
    old_total = sum(_safe_float(p.get("amount", 0)) for p in log)
    new_total_paid = old_total - old_amount + new_amount

    # Update meta.amount_paid
    meta["amount_paid"] = str(new_total_paid)
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Get invoice details for redistribution
    tax_amount = _safe_float(meta.get("tax_amount", 0))
    line_items = inv_data.get("line_items", []) or []
    main_project = meta.get("project_number", "")

    # Rebuild payment_log sequentially (same logic as invoice_update_amount)
    new_payment_log = []
    new_tax_log = []
    remaining_to_distribute = new_total_paid

    # Extract ALL projects from both line_items AND linked_projects metadata
    projects_from_items = set()
    for item in line_items:
        if isinstance(item, dict):
            proj_num = item.get("project_number", "")
            if proj_num:
                projects_from_items.add(proj_num)

    projects_from_meta = set()
    for proj_info in (meta.get("linked_projects") or []):
        if isinstance(proj_info, dict):
            proj_num = proj_info.get("project_number", "")
            if proj_num:
                projects_from_meta.add(proj_num)

    # Merge both sets
    all_projects = projects_from_items | projects_from_meta

    # Build linked_projects from merged list
    linked_projects = []
    if all_projects:
        linked_projects = [
            {"project_number": proj_num, "payment_stage_index": meta.get("payment_stage_index", 0)}
            for proj_num in sorted(all_projects)
        ]
    elif not linked_projects and main_project:
        linked_projects = [{"project_number": main_project, "payment_stage_index": meta.get("payment_stage_index", 0)}]

    # Get the project of the payment being edited (to apply form fields only to that project)
    old_project = log[idx].get("project_number", "") if idx < len(log) else ""

    # Step 1: Distribute to projects sequentially (same as invoice_update_amount)
    if linked_projects:
        def get_sort_key(x):
            proj_num = x.get("project_number", "") if isinstance(x, dict) else x
            if proj_num and proj_num[-3:].isdigit():
                return int(proj_num[-3:])
            return proj_num
        sorted_projects = sorted(linked_projects, key=get_sort_key)

        for proj_info in sorted_projects:
            if remaining_to_distribute <= 0:
                break

            proj_num = proj_info.get("project_number", "") if isinstance(proj_info, dict) else proj_info
            if not proj_num:
                continue

            # Get this project's line item amount
            proj_amount = sum(_safe_float(item.get("amount", 0)) for item in line_items
                            if isinstance(item, dict) and item.get("project_number", "").strip() == proj_num)

            if proj_amount > 0:
                distribute_to_proj = min(proj_amount, remaining_to_distribute)

                # Get stage info
                _stage_name = meta.get("payment_stage", "")
                _stage_idx = meta.get("payment_stage_index")
                if _stage_idx is not None:
                    try:
                        _stage_idx = int(_stage_idx) if not isinstance(_stage_idx, int) else _stage_idx
                    except (ValueError, TypeError):
                        _stage_idx = None

                if not _stage_name and _stage_idx is not None:
                    _stage_name = f"Stage {_stage_idx + 1}"

                # Only apply form fields (date, method, etc.) to the project being edited
                # Other projects get default values
                is_edited_project = (proj_num == old_project)

                new_payment_log.append({
                    "amount": str(distribute_to_proj),
                    "date": request.form.get("date", datetime.now().strftime("%Y-%m-%d")) if is_edited_project else datetime.now().strftime("%Y-%m-%d"),
                    "method": request.form.get("method", "") if is_edited_project else "",
                    "reference": request.form.get("reference", "") if is_edited_project else "",
                    "notes": request.form.get("notes", "") if is_edited_project else "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project_number": proj_num,
                    "invoice_number": meta.get("invoice_number", ""),
                    "stage_name": _stage_name,
                    "stage_index": _stage_idx or "",
                })
                remaining_to_distribute -= distribute_to_proj

    # Step 2: Preserve existing tax payments and only add new ones if remainder
    old_tax_log = inv_data.get("tax_payments", []) or []
    if isinstance(old_tax_log, list):
        new_tax_log = list(old_tax_log)  # Preserve existing tax payments

    # Only add new tax allocation if there's remainder to distribute
    if remaining_to_distribute > 0 and tax_amount > 0:
        tax_needs = min(tax_amount, remaining_to_distribute)
        new_tax_log.append({
            "amount": str(tax_needs),
            "date": request.form.get("date", datetime.now().strftime("%Y-%m-%d")),
            "method": request.form.get("method", ""),
            "reference": request.form.get("reference", ""),
            "notes": request.form.get("notes", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        remaining_to_distribute -= tax_needs

    # Calculate new status
    fresh_inv = dict(inv_data)
    fresh_inv["payment_log"] = new_payment_log
    fresh_inv["meta"] = meta
    new_status = _calculate_invoice_status(fresh_inv)

    # Update Firebase with rebuilt payment logs
    fb_update(f"/invoices/{invoice_id}", {
        "payment_log": new_payment_log,
        "tax_payments": new_tax_log if new_tax_log else [],
        "meta/amount_paid": str(new_total_paid),
        "meta/status": new_status,
        "meta/updated_at": meta.get("updated_at"),
    })

    # Update project stage payment statuses
    _allocate_invoice_payment_sequential(invoice_id)
    _update_project_stage_payment_status(invoice_id)

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

    # For tax payments, just update project stage statuses (tax doesn't use sequential allocation)
    _update_project_stage_payment_status(invoice_id)

    return jsonify({"success": True}), 200

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
    """Update payment plan amounts with smart auto-adjustment and permission controls"""
    try:
        data = request.get_json()
        amounts = data.get("amounts", [])
        invoice_id = data.get("invoiceId", "")
        original_amount = _safe_float(data.get("originalAmount", 0))
        new_amount = _safe_float(data.get("newAmount", 0))
        permission_granted = data.get("permissionGranted", False)
        skip_auto_adjust = data.get("skipAutoAdjust", False)

        project = fb_get(f"/projects/{project_id}") or {}
        stages = project.get("payment_stages", [])
        old_contract_value = _safe_float(project.get("contract_value", 0))

        # Find which stage was edited (by comparing sent amounts with current)
        edited_idx = -1
        old_amount = 0
        new_amount = 0
        for idx, amount_data in enumerate(amounts):
            if idx < len(stages):
                current_stage_amount = _safe_float(stages[idx].get("amount", 0))
                new_amt = _safe_float(amount_data.get("amount", 0))
                if abs(current_stage_amount - new_amt) > 0.01:
                    edited_idx = idx
                    old_amount = current_stage_amount
                    new_amount = new_amt
                    break

        if edited_idx < 0:
            return {"success": False, "error": "No stage changed detected"}, 400

        # Count invoiced and non-invoiced stages
        invoiced_count = sum(1 for s in stages if s.get("status") in ["Invoiced", "Paid", "Partially Paid", "Overdue"])
        non_invoiced_count = sum(1 for s in stages if s.get("status") == "Pending Invoice")

        # Check if edited stage is invoiced
        edited_stage_invoiced = stages[edited_idx].get("status") in ["Invoiced", "Paid", "Partially Paid", "Overdue"]

        # Find non-invoiced stages (excluding the one being edited)
        uninvoiced_indices = [i for i in range(len(stages))
                             if i != edited_idx and stages[i].get("status") == "Pending Invoice"]

        # Determine if permission is needed
        # Never ask if user is manually editing all amounts (they balance themselves)
        needs_permission = False
        if not skip_auto_adjust:
            # Case 1: All stages are invoiced and user is editing one
            if non_invoiced_count == 0 and edited_stage_invoiced:
                needs_permission = True
            # Case 2: Editing a non-invoiced stage but all other stages are invoiced (no other stages to auto-adjust to)
            elif not edited_stage_invoiced and len(uninvoiced_indices) == 0:
                needs_permission = True

        # If permission needed and not granted, return request for permission
        if needs_permission and not permission_granted:
            new_contract_value = old_contract_value + (new_amount - old_amount)
            return {
                "success": False,
                "needs_permission": True,
                "message": f"This will change the contract value from ${old_contract_value:,.2f} to ${new_contract_value:,.2f}. Continue?",
                "new_contract_value": new_contract_value
            }, 400

        # Auto-adjust logic: ONLY adjust non-invoiced stages (never adjust invoiced)
        # Skip auto-adjust if user manually edited all amounts
        if not skip_auto_adjust:
            difference = new_amount - old_amount

            # If there are non-invoiced stages, distribute the difference to them
            if uninvoiced_indices:
                per_stage = difference / len(uninvoiced_indices)
                for idx in uninvoiced_indices:
                    current_amt = _safe_float(amounts[idx].get("amount", 0)) if idx < len(amounts) else _safe_float(stages[idx].get("amount", 0))
                    amounts[idx] = {"index": idx, "amount": max(0, current_amt - per_stage)}

        # Calculate total from (possibly adjusted) amounts
        total = sum(_safe_float(a.get("amount", 0)) for a in amounts)

        # Update contract value only if:
        # - NOT manually editing all amounts (skipAutoAdjust = user keeps CV stable)
        # - AND permission was granted OR no permission was needed
        if not skip_auto_adjust and abs(total - old_contract_value) > 0.01:
            if needs_permission or non_invoiced_count > 0 or invoiced_count > 0:
                project["contract_value"] = str(total)

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

        # Redistribute remaining amounts to uninvoiced stages (all except the one being edited)
        amount_diff = new_amount - original_amount
        remaining_uninvoiced = [i for i in range(len(stages))
                               if i != stage_idx and stages[i].get("status") == "Pending Invoice"]

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
    """Quickly create an invoice for a specific payment stage - using invoice_new logic."""
    try:
        project = fb_get(f"/projects/{project_id}") or {}
        stages = project.get("payment_stages", [])

        # Validate stage
        if stage_idx >= len(stages) or not isinstance(stages[stage_idx], dict):
            return {"success": False, "error": "Invalid stage index"}, 400

        stage = stages[stage_idx]
        if stage.get("status") != "Pending Invoice":
            return {"success": False, "error": "Stage is not pending"}, 400

        # Get project details
        proj_num = project.get("project_number", "")
        client_name = project.get("client_name", "")
        stage_name = stage.get("name", f"Stage {stage_idx + 1}")
        stage_amount = _safe_float(stage.get("amount", 0))

        # Create invoice using invoice_new logic (with ALL proper fields)
        invoice_data = {
            "meta": {
                "invoice_number": _next_invoice_number(),
                "project_number": proj_num,
                "client_name": client_name,
                "invoice_date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "created_by": session.get("user_email", ""),
                "status": "Draft",
                "subtotal": str(stage_amount),
                "tax_rate": "0",
                "tax_amount": "0",
                "total": str(stage_amount),
                "amount_paid": "0",
                "notes": "",
                "terms": "",
                "payment_method": "",
                "payment_stage_index": stage_idx,
                "payment_stage": stage_name,
                "linked_projects": [{"project_number": proj_num, "payment_stage_index": stage_idx}],
            },
            "line_items": [{
                "description": stage_name,
                "project_number": proj_num,
                "quantity": "1",
                "unit_price": str(stage_amount),
                "amount": str(stage_amount),
            }],
        }

        # Create invoice
        invoice_id = fb_push("/invoices", invoice_data)
        invoice_number = invoice_data["meta"].get("invoice_number", "")

        # Mark stage as invoiced with the stage amount
        _mark_project_stage(proj_num, stage_idx, "Invoiced", invoice_id=invoice_id, invoice_number=invoice_number, amount=stage_amount)

        return {"success": True, "invoice_id": invoice_id, "invoice_number": invoice_number}, 200
    except Exception as e:
        import traceback
        log.error(f"Quick invoice error: {str(e)}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}, 500

# ── Timesheet helpers ─────────────────────────────────────────────────────────
def _fmt_time_12(t: str) -> str:
    """Convert HH:MM to '9:00 AM' format (cross-platform)."""
    if not t:
        return ""
    try:
        h, m = t.split(":")
        h = int(h)
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m} {ampm}"
    except Exception:
        return t

def _week_monday(date_str: str = "") -> str:
    """Return Monday ISO date for given week (or current week if blank)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        d = datetime.now().date()
    return (d - timedelta(days=d.weekday())).isoformat()

def _load_timesheets(week_of: str = "", employee_uid: str = "") -> list:
    raw = fb_get("/timesheets") or {}
    sheets = []
    if not isinstance(raw, dict):
        return sheets
    for tsid, tsdata in raw.items():
        if not isinstance(tsdata, dict):
            continue
        if week_of and tsdata.get("week_of") != week_of:
            continue
        if employee_uid and tsdata.get("employee_uid") != employee_uid:
            continue
        tsdata = dict(tsdata)
        tsdata["firebase_id"] = tsid
        entries = tsdata.get("entries")
        if isinstance(entries, dict):
            tsdata["entries"] = list(entries.values())
        elif not isinstance(entries, list):
            tsdata["entries"] = []
        sheets.append(tsdata)
    return sheets

# ── Routes: Timesheets ────────────────────────────────────────────────────────
@app.route("/timesheets")
@role_required("timesheets")
def timesheets():
    is_admin = normalize_role(session.get("user_role", "")) == "admin"
    uid = session.get("user_uid", "")

    week_of    = _week_monday(request.args.get("week", ""))
    week_start = datetime.strptime(week_of, "%Y-%m-%d").date()
    week_end   = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%b %d')} — {week_end.strftime('%b %d, %Y')}"
    week_dates = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
    DAY_ABBRS  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_labels = [
        {"abbr": DAY_ABBRS[i],
         "date": week_dates[i],
         "display": (week_start + timedelta(days=i)).strftime("%m/%d")}
        for i in range(7)
    ]
    prev_week = (week_start - timedelta(days=7)).isoformat()
    next_week = (week_start + timedelta(days=7)).isoformat()

    if is_admin:
        week_sheets    = _load_timesheets(week_of=week_of)
        all_users      = _load_all_users()
        employees      = [u for u in all_users if u.get("active", True)]
        sheets_by_uid  = {s["employee_uid"]: s for s in week_sheets if s.get("employee_uid")}

        grid_rows = []
        for emp in employees:
            emp_uid  = emp.get("firebase_uid", "")
            emp_name = emp.get("username") or emp.get("email", "Unknown")
            sheet    = sheets_by_uid.get(emp_uid)
            cells       = {}
            total_hours = 0.0
            if sheet:
                for entry in (sheet.get("entries") or []):
                    d   = entry.get("date", "")
                    hrs = _safe_float(entry.get("total_hours", 0))
                    if d in week_dates:
                        total_hours += hrs
                        if d in cells:
                            cells[d]["hours"]    += hrs
                            pn = entry.get("project_name", "")
                            if pn:
                                cells[d]["projects"].append(pn)
                        else:
                            st = entry.get("start_time", "")
                            et = entry.get("end_time", "")
                            cells[d] = {
                                "time_range": f"{_fmt_time_12(st)} – {_fmt_time_12(et)}" if st and et else "",
                                "hours":      hrs,
                                "projects":   [entry.get("project_name", "")] if entry.get("project_name") else [],
                                "status":     sheet.get("status", "Draft"),
                                "sheet_id":   sheet.get("firebase_id", ""),
                            }
            grid_rows.append({"uid": emp_uid, "name": emp_name,
                               "cells": cells, "total_hours": total_hours, "sheet": sheet})

        kpi_submitted = sum(1 for s in week_sheets if s.get("status") in ("Submitted", "Approved", "Rejected"))
        kpi_pending   = sum(1 for s in week_sheets if s.get("status") == "Submitted")
        kpi_approved  = sum(1 for s in week_sheets if s.get("status") == "Approved")
        kpi_hours     = sum(_safe_float(s.get("total_hours", 0)) for s in week_sheets)

        return render_template("timesheets.html",
            view="admin", week_of=week_of, week_label=week_label,
            week_dates=week_dates, day_labels=day_labels,
            prev_week=prev_week, next_week=next_week,
            grid_rows=grid_rows,
            kpi_employees=len(employees), kpi_submitted=kpi_submitted,
            kpi_pending=kpi_pending, kpi_approved=kpi_approved, kpi_hours=kpi_hours)
    else:
        # Load ALL sheets for this employee (history + current week)
        my_sheets = _load_timesheets(employee_uid=uid)
        my_sheets.sort(key=lambda x: x.get("week_of", ""), reverse=True)

        # Build personal grid cells for the selected week
        week_sheet = next((s for s in my_sheets if s.get("week_of") == week_of), None)
        emp_cells  = {}
        week_total = 0.0
        if week_sheet:
            for entry in (week_sheet.get("entries") or []):
                d   = entry.get("date", "")
                hrs = _safe_float(entry.get("total_hours", 0))
                if d in week_dates:
                    week_total += hrs
                    if d in emp_cells:
                        emp_cells[d]["hours"] += hrs
                        pn = entry.get("project_name", "")
                        if pn:
                            emp_cells[d]["projects"].append(pn)
                    else:
                        st = entry.get("start_time", "")
                        et = entry.get("end_time", "")
                        emp_cells[d] = {
                            "time_range": f"{_fmt_time_12(st)} – {_fmt_time_12(et)}" if st and et else "",
                            "hours":      hrs,
                            "projects":   [entry.get("project_name", "")] if entry.get("project_name") else [],
                            "status":     week_sheet.get("status", "Draft"),
                            "sheet_id":   week_sheet.get("firebase_id", ""),
                        }

        # Monthly stats (current calendar month)
        current_month = datetime.now().strftime("%Y-%m")
        month_sheets  = [s for s in my_sheets if s.get("week_of", "")[:7] == current_month]
        stat_month_hours   = sum(_safe_float(s.get("total_hours", 0)) for s in month_sheets)
        stat_month_ot      = sum(_safe_float(s.get("total_overtime_hours", 0)) for s in month_sheets)
        stat_approved      = sum(1 for s in my_sheets if s.get("status") == "Approved")
        stat_pending       = sum(1 for s in my_sheets if s.get("status") == "Submitted")

        current_week = _week_monday()
        return render_template("timesheets.html",
            view="my", my_sheets=my_sheets,
            week_of=week_of, week_label=week_label,
            week_dates=week_dates, day_labels=day_labels,
            prev_week=prev_week, next_week=next_week,
            week_sheet=week_sheet, emp_cells=emp_cells, week_total=week_total,
            current_week=current_week,
            stat_month_hours=stat_month_hours, stat_month_ot=stat_month_ot,
            stat_approved=stat_approved, stat_pending=stat_pending)


@app.route("/timesheets/submit")
@login_required
def timesheets_submit():
    week_of    = _week_monday(request.args.get("week", ""))
    uid        = session.get("user_uid", "")
    all_projs  = _load_projects_list()
    active_projects = [p for p in all_projs
                       if p.get("status", "") not in ("Completed", "Cancelled")]
    existing   = _load_timesheets(week_of=week_of, employee_uid=uid)
    existing_sheet = existing[0] if existing else None

    week_start = datetime.strptime(week_of, "%Y-%m-%d").date()
    week_end   = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%b %d')} — {week_end.strftime('%b %d, %Y')}"
    DAY_NAMES  = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    week_days  = [
        {"name": DAY_NAMES[i],
         "abbr": DAY_NAMES[i][:3],
         "date": (week_start + timedelta(days=i)).isoformat()}
        for i in range(7)
    ]
    return render_template("timesheet_submit.html",
        week_of=week_of, week_label=week_label,
        week_days=week_days, active_projects=active_projects,
        existing_sheet=existing_sheet)


@app.route("/timesheets/<sheet_id>")
@login_required
def timesheet_detail(sheet_id):
    sheet = fb_get(f"/timesheets/{sheet_id}")
    if not sheet or not isinstance(sheet, dict):
        abort(404)
    sheet = dict(sheet)
    sheet["firebase_id"] = sheet_id
    entries = sheet.get("entries")
    if isinstance(entries, dict):
        entries = list(entries.values())
    elif not isinstance(entries, list):
        entries = []
    sheet["entries"] = sorted(entries, key=lambda e: (e.get("date", ""), e.get("start_time", "")))

    uid      = session.get("user_uid", "")
    is_admin = normalize_role(session.get("user_role", "")) == "admin"
    if not is_admin and sheet.get("employee_uid") != uid:
        flash("You don't have permission to view this timesheet.", "danger")
        return redirect(url_for("timesheets"))

    by_date = {}
    for entry in sheet["entries"]:
        d = entry.get("date", "")
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(entry)

    return render_template("timesheet_detail.html",
        sheet=sheet, by_date=by_date, is_admin=is_admin)


@app.route("/api/timesheets", methods=["POST"])
@login_required
def api_timesheets_save():
    data    = request.get_json(force=True) or {}
    uid     = session.get("user_uid", "")
    name    = session.get("user_name", "")
    week_of = (data.get("week_of") or "").strip()
    action  = data.get("action", "draft")
    entries = data.get("entries") or []

    if not week_of:
        return jsonify({"error": "week_of is required"}), 400

    total_reg = sum(_safe_float(e.get("regular_hours", 0)) for e in entries)
    total_ot  = sum(_safe_float(e.get("overtime_hours", 0)) for e in entries)
    now_iso   = datetime.now(timezone.utc).isoformat()

    sheet_data = {
        "employee_uid":         uid,
        "employee_name":        name,
        "week_of":              week_of,
        "status":               "Submitted" if action == "submit" else "Draft",
        "entries":              entries,
        "total_regular_hours":  total_reg,
        "total_overtime_hours": total_ot,
        "total_hours":          total_reg + total_ot,
        "updated_at":           now_iso,
    }
    if action == "submit":
        sheet_data["submitted_at"] = now_iso

    existing = _load_timesheets(week_of=week_of, employee_uid=uid)
    if existing:
        sheet_id = existing[0]["firebase_id"]
        fb_update(f"/timesheets/{sheet_id}", sheet_data)
    else:
        sheet_data["created_at"] = now_iso
        sheet_id = fb_push("/timesheets", sheet_data)

    return jsonify({"success": True, "sheet_id": sheet_id, "status": sheet_data["status"]})


@app.route("/api/timesheets/<sheet_id>/approve", methods=["POST"])
@role_required("timesheets")
def api_timesheets_approve(sheet_id):
    if normalize_role(session.get("user_role", "")) != "admin":
        return jsonify({"error": "Admin access required"}), 403
    data   = request.get_json(force=True) or {}
    action = data.get("action", "approve")
    notes  = (data.get("notes") or "").strip()
    status = "Approved" if action == "approve" else "Rejected"
    fb_update(f"/timesheets/{sheet_id}", {
        "status":          status,
        "approved_by":     session.get("user_name", ""),
        "approved_at":     datetime.now(timezone.utc).isoformat(),
        "rejection_notes": notes,
    })
    return jsonify({"success": True, "status": status})


@app.route("/api/admin/reset-timesheets", methods=["POST"])
@login_required
def api_admin_reset_timesheets():
    if normalize_role(session.get("user_role", "")) != "admin":
        return jsonify({"error": "Admin access required"}), 403
    fb_delete("/timesheets")
    return jsonify({"success": True, "message": "All timesheets deleted."})


@app.route("/api/timesheets/<sheet_id>/delete", methods=["POST"])
@login_required
def api_timesheet_delete(sheet_id):
    if normalize_role(session.get("user_role", "")) != "admin":
        return jsonify({"error": "Admin access required"}), 403
    sheet = fb_get(f"/timesheets/{sheet_id}")
    if not sheet:
        return jsonify({"error": "Timesheet not found"}), 404
    fb_delete(f"/timesheets/{sheet_id}")
    return jsonify({"success": True})


@app.route("/api/timesheets/export")
@role_required("timesheets")
def api_timesheets_export():
    import csv
    import io as _io
    if normalize_role(session.get("user_role", "")) != "admin":
        flash("Admin access required.", "danger")
        return redirect(url_for("timesheets"))
    week_of = request.args.get("week", _week_monday())
    sheets  = _load_timesheets(week_of=week_of)
    output  = _io.StringIO()
    writer  = csv.writer(output)
    writer.writerow(["Week Of", "Employee", "Status", "Date", "Day", "Project",
                     "Project #", "Start", "Lunch Mins", "End",
                     "Regular Hrs", "OT Hrs", "Total Hrs", "Notes"])
    for sheet in sheets:
        for entry in (sheet.get("entries") or []):
            dt = entry.get("date", "")
            try:
                day_name = datetime.strptime(dt, "%Y-%m-%d").strftime("%A")
            except Exception:
                day_name = ""
            writer.writerow([
                sheet.get("week_of", ""), sheet.get("employee_name", ""),
                sheet.get("status", ""), dt, day_name,
                entry.get("project_name", ""), entry.get("project_number", ""),
                entry.get("start_time", ""), entry.get("lunch_break_mins", ""),
                entry.get("end_time", ""),
                entry.get("regular_hours", 0), entry.get("overtime_hours", 0),
                entry.get("total_hours", 0), entry.get("notes", ""),
            ])
    csv_bytes = output.getvalue().encode("utf-8-sig")
    return send_file(
        _io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"timesheets_{week_of}.csv",
    )

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host=os.environ.get("FLASK_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
    )
