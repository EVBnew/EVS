from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import requests
import streamlit as st


@dataclass
class JournalEntry:
    id: str
    created_at: int
    author_user_id: str
    author_email: str
    prompt: str
    body: str
    tags: List[str]
    share_with_coach: bool
    coach_email: Optional[str]
    thread_key: str


def _cfg() -> tuple[str, str]:
    url = st.secrets.get("GSHEET_USERS_WEBAPP_URL", "").strip()
    secret = st.secrets.get("GSHEET_USERS_SHARED_SECRET", "").strip()
    if not url or not secret:
        raise RuntimeError("Missing GSHEET_USERS_WEBAPP_URL or GSHEET_USERS_SHARED_SECRET in secrets.")
    return url, secret


def normalize_tags(tags: str | List[str]) -> List[str]:
    if isinstance(tags, list):
        raw = tags
    else:
        raw = [t.strip() for t in (tags or "").split(",")]
    clean: List[str] = []
    seen = set()
    for t in raw:
        t2 = t.strip().lower()
        if not t2 or t2 in seen:
            continue
        seen.add(t2)
        clean.append(t2)
    return clean[:10]


def build_entry(
    *,
    author_user_id: str,
    author_email: str,
    body: str,
    tags: str | List[str] = "",
    share_with_coach: bool = False,
    coach_email: Optional[str] = None,
    prompt: str = "Qu’as-tu testé aujourd’hui ?",
) -> JournalEntry:
    now = int(time.time())
    author_email_n = author_email.strip().lower()
    prompt_n = prompt.strip()
    share = bool(share_with_coach)

    return JournalEntry(
        id=str(uuid.uuid4()),
        created_at=now,
        author_user_id=author_user_id.strip(),
        author_email=author_email_n,
        prompt=prompt_n,
        body=body.strip(),
        tags=normalize_tags(tags),
        share_with_coach=share,
        coach_email=(coach_email.strip().lower() if share and coach_email else None),
        thread_key=f"{author_email_n}::{prompt_n.lower()}",
    )


def _post(payload: Dict[str, Any], timeout_s: int = 12) -> Dict[str, Any]:
    url, secret = _cfg()
    payload = dict(payload)
    payload["secret"] = secret

    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()

    try:
        data = r.json()
    except Exception:
        raise RuntimeError("WebApp did not return JSON.")

    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError(f"WebApp error: {data}")
    return data


def journal_create(entry: JournalEntry) -> JournalEntry:
    _post({"action": "journal_create", "data": asdict(entry)})
    return entry


def journal_list_learner(author_email: str, limit: int = 50) -> List[Dict[str, Any]]:
    data = _post({"action": "journal_list_learner", "author_email": author_email.strip().lower(), "limit": int(limit)})
    items = data.get("items", [])
    return items if isinstance(items, list) else []


def journal_list_coach(coach_email: str, limit: int = 100) -> List[Dict[str, Any]]:
    data = _post({"action": "journal_list_coach", "coach_email": coach_email.strip().lower(), "limit": int(limit)})
    items = data.get("items", [])
    return items if isinstance(items, list) else []
