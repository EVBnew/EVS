from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

import streamlit as st


@dataclass
class APIResult:
    ok: bool
    data: Dict[str, Any]
    error: str = ""


def _secrets() -> tuple[str, str]:
    url = str(st.secrets.get("GSHEET_USERS_WEBAPP_URL") or "").strip()
    secret = str(st.secrets.get("GSHEET_USERS_SHARED_SECRET") or "").strip()
    if not url:
        raise RuntimeError("Missing secret: GSHEET_USERS_WEBAPP_URL")
    if not secret:
        raise RuntimeError("Missing secret: GSHEET_USERS_SHARED_SECRET")
    return url, secret


def _post(payload: Dict[str, Any], timeout: int = 25) -> APIResult:
    url, secret = _secrets()
    payload = {**payload, "secret": secret}

    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        ok = bool(data.get("ok"))
        return APIResult(ok=ok, data=data, error="" if ok else str(data.get("error") or "Unknown error"))
    except Exception as e:
        return APIResult(ok=False, data={}, error=str(e))


# -----------------------------
# Programs
# -----------------------------
def create_program(
    *,
    org_id: str,
    program_id: str,
    learner_email: str,
    title: str,
    program_json: Any,
    status: str = "active",
    program_version: str = "1",
) -> APIResult:
    return _post(
        {
            "action": "create_program",
            "org_id": org_id,
            "program_id": program_id,
            "learner_email": learner_email,
            "title": title,
            "program_json": program_json,  # can be dict or string
            "status": status,
            "program_version": program_version,
        }
    )


def list_programs(*, org_id: str = "", learner_email: str = "") -> APIResult:
    return _post(
        {
            "action": "list_programs",
            "org_id": org_id,
            "learner_email": learner_email,
        }
    )


# -----------------------------
# Weekly objectives
# -----------------------------
def upsert_objective(
    *,
    org_id: str,
    objective_id: str,
    program_id: str,
    week_start: str,  # YYYY-MM-DD
    objective_text: str,
    status: str = "todo",
) -> APIResult:
    return _post(
        {
            "action": "upsert_objective",
            "org_id": org_id,
            "objective_id": objective_id,
            "program_id": program_id,
            "week_start": week_start,
            "objective_text": objective_text,
            "status": status,
        }
    )


def list_objectives(*, org_id: str = "", program_id: str = "", week_start: str = "") -> APIResult:
    return _post(
        {
            "action": "list_objectives",
            "org_id": org_id,
            "program_id": program_id,
            "week_start": week_start,
        }
    )


# -----------------------------
# Comments (thread)
# -----------------------------
def add_comment(
    *,
    org_id: str,
    comment_id: str,
    program_id: str,
    author_role: str,
    author_email: str,
    message: str,
    week_start: str = "",
) -> APIResult:
    return _post(
        {
            "action": "add_comment",
            "org_id": org_id,
            "comment_id": comment_id,
            "program_id": program_id,
            "week_start": week_start,
            "author_role": author_role,
            "author_email": author_email,
            "message": message,
        }
    )


def list_comments(*, org_id: str = "", program_id: str = "", week_start: str = "") -> APIResult:
    return _post(
        {
            "action": "list_comments",
            "org_id": org_id,
            "program_id": program_id,
            "week_start": week_start,
        }
    )
