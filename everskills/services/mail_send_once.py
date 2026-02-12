from __future__ import annotations

from typing import Any, Dict, Optional

from everskills.services.mail_events import log_event, was_sent
from everskills.services.mailer import send_email


def send_once(
    *,
    event_key: str,
    event_type: str,
    request_id: str,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    if was_sent(event_key):
        log_event(
            event_key=event_key,
            event_type=event_type,
            request_id=request_id,
            to_email=to_email,
            subject=subject,
            status="SKIPPED",
            error="already_sent",
        )
        return False

    try:
        res = send_email(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            meta=meta,
        )
        ok = bool(res.get("ok"))
        mode = str(res.get("mode", ""))
        details = str(res.get("details", ""))

        log_event(
            event_key=event_key,
            event_type=event_type,
            request_id=request_id,
            to_email=to_email,
            subject=subject,
            status="SENT" if ok else "FAILED",
            mail_mode=mode,
            mail_ok=ok,
            error=None if ok else details,
        )
        return ok

    except Exception as e:
        log_event(
            event_key=event_key,
            event_type=event_type,
            request_id=request_id,
            to_email=to_email,
            subject=subject,
            status="FAILED",
            error=str(e),
        )
        return False
