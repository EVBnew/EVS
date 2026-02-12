# everskills/services/mail_events.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

# File is independent (no streamlit import) to avoid side effects.

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # .../EVERSKILLS
DATA_DIR = PROJECT_ROOT / "data"
MAIL_EVENTS_PATH = DATA_DIR / "mail_events.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return default
        return json.loads(raw)
    except Exception:
        return default


def _write_json(path: Path, obj: Any) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def was_sent(event_key: str) -> bool:
    """
    Idempotency check: True if we already have an event with same key and status SENT.
    """
    key = (event_key or "").strip()
    if not key:
        return False

    rows = _read_json(MAIL_EVENTS_PATH, [])
    if not isinstance(rows, list):
        return False

    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("event_key") or "").strip() == key and str(r.get("status") or "").strip() == "SENT":
            return True
    return False


def log_event(
    *,
    event_key: str,
    event_type: str,
    request_id: str,
    to_email: str,
    subject: str,
    status: str,
    mail_mode: str = "",
    mail_ok: Optional[bool] = None,
    error: Optional[str] = None,
) -> None:
    """
    Append one event row. IMPORTANT: we log the `to_email` we received, no rewrite.
    """
    row: Dict[str, Any] = {
        "ts": now_iso(),
        "event_key": (event_key or "").strip(),
        "event_type": (event_type or "").strip(),
        "request_id": (request_id or "").strip(),
        "to": (to_email or "").strip(),  # <- source of truth for routing
        "subject": subject or "",
        "status": (status or "").strip(),
        "mail_mode": (mail_mode or "").strip(),
        "mail_ok": bool(mail_ok) if mail_ok is not None else None,
        "error": error,
    }

    rows = _read_json(MAIL_EVENTS_PATH, [])
    if not isinstance(rows, list):
        rows = []
    rows.append(row)
    _write_json(MAIL_EVENTS_PATH, rows)
