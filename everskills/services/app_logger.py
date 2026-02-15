# everskills/services/app_logger.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

LOG_PATH = Path("data/app_events.json")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event_type: str, payload: Dict[str, Any] | None = None, level: str = "INFO") -> None:
    """
    Append-only JSON log, stored in data/app_events.json
    level: INFO | WARN | ERROR
    """
    payload = payload or {}

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": _utc_now_iso(),
        "level": (level or "INFO").upper(),
        "event_type": str(event_type),
        "payload": payload,
    }

    data: List[Dict[str, Any]] = []
    if LOG_PATH.exists():
        try:
            data = json.loads(LOG_PATH.read_text(encoding="utf-8")) or []
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []

    data.append(entry)
    LOG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
