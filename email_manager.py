"""Email delivery for invoices and payment reminders.

SMTP credentials are read from data/settings.json under the "email" key:
{
  "email": {
    "enabled": true,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "you@gmail.com",
    "smtp_password": "app-password-here",
    "from_name": "MABS Engineering LLC"
  }
}

For Gmail: use an App Password (not your regular password).
For Outlook/Office365: use smtp.office365.com port 587.
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from datetime import datetime, timedelta

from app_logger import get_logger

_log = get_logger("email")


def _load_email_config() -> dict:
    try:
        import json
        settings_path = Path(__file__).resolve().parent / "data" / "settings.json"
        if settings_path.exists():
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("email", {})
    except Exception as exc:
        _log.warning("Could not load email config: %s", exc)
    return {}


class EmailManager:
    # ------------------------------------------------------------------ #
    #  Config helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_configured() -> bool:
        cfg = _load_email_config()
        return bool(
            cfg.get("enabled")
            and cfg.get("smtp_host")
            and cfg.get("smtp_user")
            and cfg.get("smtp_password")
        )

    # ------------------------------------------------------------------ #
    #  Core send                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def send_email(to_address: str, subject: str, body_html: str,
                   attachment_path: Path = None) -> bool:
        """Send an email via SMTP. Returns True on success."""
        cfg = _load_email_config()
        if not EmailManager.is_configured():
            _log.warning("Email not configured — skipping send to %s", to_address)
            return False

        host     = cfg["smtp_host"]
        port     = int(cfg.get("smtp_port", 587))
        user     = cfg["smtp_user"]
        password = cfg["smtp_password"]
        from_name = cfg.get("from_name", "MABS Engineering LLC")
        from_addr = f"{from_name} <{user}>"

        msg = MIMEMultipart("mixed")
        msg["From"]    = from_addr
        msg["To"]      = to_address
        msg["Subject"] = subject

        msg.attach(MIMEText(body_html, "html", "utf-8"))

        if attachment_path and Path(attachment_path).exists():
            with open(attachment_path, "rb") as fh:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(fh.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{Path(attachment_path).name}"',
            )
            msg.attach(part)

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(user, password)
                server.sendmail(user, to_address, msg.as_string())
            _log.info("Email sent to %s — %s", to_address, subject)
            return True
        except Exception as exc:
            _log.error("Failed to send email to %s: %s", to_address, exc)
            return False

    # ------------------------------------------------------------------ #
    #  Invoice email                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def send_invoice(invoice, pdf_path: Path) -> bool:
        """Email an invoice PDF to the client."""
        to_addr = getattr(invoice, "client_email", "") or ""
        if not to_addr.strip():
            _log.warning("Invoice %s has no client email — skipping", invoice.invoice_number)
            return False

        company_name = _load_company_name()
        subject = f"Invoice {invoice.invoice_number} from {company_name}"
        due_line = f"<p><b>Due Date:</b> {getattr(invoice, 'due_date', 'N/A')}</p>" if getattr(invoice, "due_date", "") else ""

        body = f"""
        <html><body style="font-family: Arial, sans-serif; color: #2c3e50;">
        <p>Dear {invoice.client_name},</p>
        <p>Please find attached invoice <b>{invoice.invoice_number}</b>
           for the amount of <b>${float(invoice.total):,.2f}</b>.</p>
        {due_line}
        <p>If you have any questions, please don't hesitate to reach out.</p>
        <br>
        <p>Best regards,<br><b>{company_name}</b></p>
        </body></html>
        """
        return EmailManager.send_email(to_addr, subject, body, pdf_path)

    # ------------------------------------------------------------------ #
    #  Payment reminders                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def send_payment_reminders(invoices: list, days_before: int = 3) -> int:
        """Email clients whose invoice is due in exactly `days_before` days.

        Returns count of reminders sent.
        """
        if not EmailManager.is_configured():
            return 0

        target_date = (datetime.now() + timedelta(days=days_before)).date()
        sent = 0

        for inv in invoices:
            meta = inv.get("meta", inv)
            status = meta.get("status", "Unpaid")
            if status in ("Paid", "Cancelled"):
                continue

            due_raw = meta.get("due_date", "")
            if not due_raw or due_raw == "N/A":
                continue

            try:
                due_date = datetime.strptime(due_raw, "%m-%d-%Y").date()
            except ValueError:
                continue

            if due_date != target_date:
                continue

            to_addr = meta.get("client_email", "")
            if not to_addr:
                continue

            company_name = _load_company_name()
            invoice_number = meta.get("invoice_number", "")
            total = meta.get("total_amount", 0)
            subject = f"Reminder: Invoice {invoice_number} due in {days_before} days"
            body = f"""
            <html><body style="font-family: Arial, sans-serif; color: #2c3e50;">
            <p>Dear {meta.get('client_name', 'Valued Client')},</p>
            <p>This is a friendly reminder that invoice <b>{invoice_number}</b>
               for <b>${float(total):,.2f}</b> is due on <b>{due_raw}</b>
               ({days_before} day{'s' if days_before != 1 else ''} from today).</p>
            <p>Please arrange payment at your earliest convenience.</p>
            <br>
            <p>Best regards,<br><b>{company_name}</b></p>
            </body></html>
            """
            if EmailManager.send_email(to_addr, subject, body):
                sent += 1

        if sent:
            _log.info("Payment reminders sent: %d", sent)
        return sent


def _load_company_name() -> str:
    try:
        import json
        settings_path = Path(__file__).resolve().parent / "data" / "settings.json"
        with open(settings_path, encoding="utf-8") as f:
            return json.load(f).get("company", {}).get("name", "MABS Engineering LLC")
    except Exception:
        return "MABS Engineering LLC"
