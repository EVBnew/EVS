# everskills/services/mailer.py
from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from everskills.services.storage import now_iso

BASE_DIR = Path(__file__).resolve().parents[2]  # EVERSKILLS/
DATA_DIR = BASE_DIR / "data"
OUTBOX_PATH = DATA_DIR / "emails_outbox.json"


@dataclass
class MailResult:
    ok: bool
    mode: str  # "smtp" or "outbox"
    error: str = ""


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_outbox(item: Dict[str, Any]) -> None:
    rows = _read_json(OUTBOX_PATH, default=[])
    if not isinstance(rows, list):
        rows = []
    rows.append(item)
    _write_json(OUTBOX_PATH, rows)


def _get_smtp_config() -> Dict[str, Any]:
    # All are expected in Streamlit Cloud secrets
    host = (st.secrets.get("SMTP_HOST") or "").strip()
    port = int(st.secrets.get("SMTP_PORT") or 587)
    user = (st.secrets.get("SMTP_USER") or "").strip()
    pwd = (st.secrets.get("SMTP_PASSWORD") or "").strip()
    sender = (st.secrets.get("SMTP_FROM") or user).strip()

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": pwd,
        "sender": sender,
    }


def send_email(
    to_email: str,
    subject: str,
    text: str,
    *,
    reply_to: Optional[str] = None,
    tags: Optional[Dict[str, Any]] = None,
    force_outbox: bool = False,
) -> MailResult:
    """
    Sends a real email via SMTP if secrets are present.
    Also logs to data/emails_outbox.json for audit.
    """
    to_email = (to_email or "").strip()
    subject = (subject or "").strip()
    text = (text or "").strip()

    if not to_email or "@" not in to_email:
        return MailResult(ok=False, mode="smtp", error="Invalid recipient email")

    cfg = _get_smtp_config()
    has_cfg = bool(cfg["host"] and cfg["user"] and cfg["password"] and cfg["sender"])

    # always log attempt
    outbox_item = {
        "ts": now_iso(),
        "to": to_email,
        "from": cfg.get("sender", ""),
        "subject": subject,
        "text": text,
        "reply_to": reply_to or "",
        "tags": tags or {},
        "mode": "smtp" if (has_cfg and not force_outbox) else "outbox",
        "status": "pending",
        "error": "",
    }

    if force_outbox or not has_cfg:
        outbox_item["status"] = "queued"
        _append_outbox(outbox_item)
        return MailResult(ok=True, mode="outbox", error="")

    msg = EmailMessage()
    msg["From"] = cfg["sender"]
    msg["To"] = to_email
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)

    try:
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=25) as s:
            s.ehlo()
            # STARTTLS (OVH standard)
            s.starttls()
            s.ehlo()
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)

        outbox_item["status"] = "sent"
        _append_outbox(outbox_item)
        return MailResult(ok=True, mode="smtp", error="")

    except Exception as e:
        outbox_item["status"] = "error"
        outbox_item["error"] = str(e)
        _append_outbox(outbox_item)
        return MailResult(ok=False, mode="smtp", error=str(e))
