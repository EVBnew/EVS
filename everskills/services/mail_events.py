from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # .../EVERSKILLS
DATA_DIR = PROJECT_ROOT / "data"
EVENTS_PATH = DATA_DIR / "mail_events.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_events() -> List[Dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        raw = EVENTS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else []
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_events(events: List[Dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def was_sent(event_key: str) -> bool:
    return any(
        e.get("event_key") == event_key and e.get("status") == "SENT"
        for e in _load_events()
    )


def log_event(
    *,
    event_key: str,
    event_type: str,
    request_id: str,
    to_email: str,
    subject: str,
    status: str,  # SENT | FAILED | SKIPPED
    mail_mode: str = "",
    mail_ok: Optional[bool] = None,
    error: Optional[str] = None,
) -> None:
    events = _load_events()
    events.append(
        {
            "sent_at": _utc_now_iso(),
            "event_key": event_key,
            "event_type": event_type,
            "request_id": request_id,
            "to": to_email,
            "subject": subject,
            "status": status,
            "mail_mode": mail_mode,
            "mail_ok": mail_ok,
            "error": error,
        }
    )
    _save_events(events)
