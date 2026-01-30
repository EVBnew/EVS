# everskills/services/mailer.py
from __future__ import annotations

import json
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st


# ----------------------------
# Paths (no dependency on storage.py to avoid cycles)
# ----------------------------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # .../EVERSKILLS
DATA_DIR = PROJECT_ROOT / "data"
OUTBOX_PATH = DATA_DIR / "emails_outbox.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _append_outbox(item: Dict[str, Any]) -> None:
    _ensure_data_dir()
    existing = []
    if OUTBOX_PATH.exists():
        try:
            raw = OUTBOX_PATH.read_text(encoding="utf-8")
            existing = json.loads(raw) if raw.strip() else []
        except Exception:
            existing = []
    if not isinstance(existing, list):
        existing = []
    existing.append(item)
    OUTBOX_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    email_from: str


def get_smtp_config() -> Optional[SMTPConfig]:
    """
    Reads SMTP config from Streamlit secrets.

    Expected keys in .streamlit/secrets.toml:
      SMTP_HOST
      SMTP_PORT
      SMTP_USER
      SMTP_PASS
      EMAIL_FROM   (optional, defaults to SMTP_USER)
    """
    host = (st.secrets.get("SMTP_HOST") or "").strip()
    port_raw = st.secrets.get("SMTP_PORT")
    user = (st.secrets.get("SMTP_USER") or "").strip()
    password = (st.secrets.get("SMTP_PASS") or "").strip()
    email_from = (st.secrets.get("EMAIL_FROM") or user).strip()

    if not host or not user or not password:
        return None

    try:
        port = int(port_raw) if port_raw is not None else 587
    except Exception:
        port = 587

    return SMTPConfig(host=host, port=port, user=user, password=password, email_from=email_from)


def smtp_is_configured() -> bool:
    return get_smtp_config() is not None


def send_email(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Sends an email via SMTP if configured, otherwise writes into data/emails_outbox.json.

    Returns a dict:
      {"ok": True/False, "mode": "smtp"|"outbox", "details": "..."}
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return {"ok": False, "mode": "none", "details": "Missing to_email"}

    meta = meta or {}
    cfg = get_smtp_config()

    # Always log intent (useful for end-to-end debugging)
    outbox_item = {
        "ts": now_iso(),
        "to": to_email,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body or "",
        "meta": meta,
    }

    # If no SMTP config -> outbox
    if not cfg:
        _append_outbox({**outbox_item, "mode": "outbox", "sent": False})
        return {
            "ok": True,
            "mode": "outbox",
            "details": f"SMTP not configured. Saved to {OUTBOX_PATH}",
        }

    # Build message
    msg = EmailMessage()
    msg["From"] = cfg.email_from
    msg["To"] = to_email
    msg["Subject"] = subject

    # Text part (mandatory)
    msg.set_content(text_body)

    # Optional HTML part
    if html_body and html_body.strip():
        msg.add_alternative(html_body, subtype="html")

    # Send
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as server:
            server.ehlo()
            # TLS for 587
            if cfg.port == 587:
                server.starttls(context=context)
                server.ehlo()
            server.login(cfg.user, cfg.password)
            server.send_message(msg)

        _append_outbox({**outbox_item, "mode": "smtp", "sent": True})
        return {"ok": True, "mode": "smtp", "details": "Email sent via SMTP"}

    except Exception as e:
        # Fallback: keep trace in outbox
        _append_outbox({**outbox_item, "mode": "smtp", "sent": False, "error": str(e)})
        return {"ok": False, "mode": "smtp", "details": f"SMTP error: {e}"}  # noqa: TRY003
