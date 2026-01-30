# everskills/services/storage.py
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
import secrets
from typing import Any, Dict, List, Optional


# ----------------------------
# Paths
# ----------------------------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # .../EVERSKILLS
DATA_DIR = PROJECT_ROOT / "data"

REQUESTS_PATH = DATA_DIR / "requests.json"
CAMPAIGNS_PATH = DATA_DIR / "campaigns.json"

# Uploads live inside the package (so the app can reference relative paths)
PACKAGE_DIR = THIS_FILE.parents[1]  # .../everskills
UPLOAD_DIR = PACKAGE_DIR / "temp_uploads"


# ----------------------------
# Utils
# ----------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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
    ensure_dirs()
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_id(prefix: str) -> str:
    # stable length, readable
    return f"{prefix}_{secrets.token_hex(6)}"


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _support_to_dict(s: Any) -> Optional[Dict[str, str]]:
    """
    Normalise one support item into {"name": "...", "path": "..."} or None.
    Accepts:
      - dict {path,name}
      - string path
    """
    if isinstance(s, dict):
        p = str(s.get("path") or "").strip()
        if not p:
            return None
        name = str(s.get("name") or os.path.basename(p) or "support")
        return {"name": name, "path": p}

    if isinstance(s, str):
        p = s.strip()
        if not p:
            return None
        return {"name": os.path.basename(p) or "support", "path": p}

    return None


# ----------------------------
# NEW: workflow checkpoints helpers (check-in/check-out/touchpoints)
# ----------------------------
def _default_checkpoints(weeks: int) -> Dict[str, Any]:
    """
    Minimal, stable schema.
    touchpoints is a fixed-size list (len = weeks) to avoid append bugs in UI.
    """
    weeks = int(weeks) if isinstance(weeks, int) or str(weeks).isdigit() else 3
    if weeks <= 0:
        weeks = 3

    return {
        "checkin": {"done": False, "date": None},
        "checkout": {"done": False, "date": None},
        "touchpoints": [
            {"week": i + 1, "done": False, "date": None, "note": ""} for i in range(weeks)
        ],
    }


def _ensure_checkpoints(c: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure checkpoints exists, is a dict, and touchpoints length matches weeks.
    Never deletes existing information.
    """
    weeks = c.get("weeks") or c.get("semaines") or 3
    try:
        weeks = int(weeks)
    except Exception:
        weeks = 3
    if weeks <= 0:
        weeks = 3

    cps = c.get("checkpoints")
    if not isinstance(cps, dict):
        return _default_checkpoints(weeks)

    # ensure required keys
    cps.setdefault("checkin", {"done": False, "date": None})
    cps.setdefault("checkout", {"done": False, "date": None})

    tps = cps.get("touchpoints")
    if not isinstance(tps, list):
        tps = []

    # normalize items
    norm_tps: List[Dict[str, Any]] = []
    for i, tp in enumerate(tps):
        if isinstance(tp, dict):
            norm_tps.append(
                {
                    "week": int(tp.get("week") or (i + 1)),
                    "done": bool(tp.get("done", False)),
                    "date": tp.get("date"),
                    "note": tp.get("note", "") or "",
                }
            )

    # resize to weeks (keep existing, pad missing)
    while len(norm_tps) < weeks:
        norm_tps.append({"week": len(norm_tps) + 1, "done": False, "date": None, "note": ""})

    # if longer, keep extra but it shouldn't happen; we won't drop it to avoid data loss
    cps["touchpoints"] = norm_tps

    return cps


# ----------------------------
# Normalizers
# ----------------------------
def normalize_requests_ids(requests: Any) -> List[Dict[str, Any]]:
    """
    Ensures:
      - list of dict
      - each request has non-empty id
      - supports is list (strings or dict allowed)
      - status exists
      - created_at/updated_at exist
    """
    out: List[Dict[str, Any]] = []
    for r in _as_list(requests):
        if not isinstance(r, dict):
            continue

        rid = (r.get("id") or "").strip()
        if not rid:
            # if legacy had rid key, reuse it
            rid = (r.get("rid") or "").strip()
        if not rid:
            rid = _new_id("req")

        supports = _as_list(r.get("supports"))
        status = r.get("status") or "submitted"

        created_at = r.get("created_at") or r.get("ts") or now_iso()
        updated_at = r.get("updated_at") or created_at

        out.append(
            {
                **r,
                "id": rid,
                "supports": supports,
                "status": status,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    return out


def _normalize_campaign(c: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unifies multiple historical schemas into one.
    Target keys:
      id, request_id, learner_email, coach_email
      objective, context, supports (list of {name,path})
      weeks, status
      program (free-form), messages (list), created_at, updated_at
      + checkpoints (new, for check-in/check-out/touchpoints)
    """
    cid = str(c.get("id") or "").strip() or _new_id("camp")

    request_id = (
        str(c.get("request_id") or "").strip()
        or str(c.get("rid") or "").strip()
        or str(c.get("request") or "").strip()
        or ""
    )

    learner_email = c.get("learner_email") or c.get("email") or ""
    coach_email = c.get("coach_email") or ""

    objective = c.get("objective") or ""
    context = c.get("context") or ""

    weeks = c.get("weeks") or c.get("semaines") or 3
    try:
        weeks = int(weeks)
    except Exception:
        weeks = 3

    status = c.get("status") or "coach_validated"

    created_at = c.get("created_at") or now_iso()
    updated_at = c.get("updated_at") or created_at

    # supports: accept either "supports" (preferred) or "support_files"
    supports_in = _as_list(c.get("supports"))
    if not supports_in:
        supports_in = _as_list(c.get("support_files"))

    supports_norm: List[Dict[str, str]] = []
    for s in supports_in:
        d = _support_to_dict(s)
        if d:
            supports_norm.append(d)

    # program: accept "program" or "plan" or "weekly_plan"
    program = c.get("program")
    if program is None:
        program = c.get("plan")
    if program is None:
        program = c.get("weekly_plan")
    if program is None:
        program = []

    messages = _as_list(c.get("messages"))

    out = {
        **c,
        "id": cid,
        "request_id": request_id,
        "learner_email": learner_email,
        "coach_email": coach_email,
        "objective": objective,
        "context": context,
        "supports": supports_norm,
        "weeks": weeks,
        "status": status,
        "program": program,
        "messages": messages,
        "created_at": created_at,
        "updated_at": updated_at,
    }

    # NEW: ensure checkpoints exists (backward compatible)
    out["checkpoints"] = _ensure_checkpoints(out)

    return out


def _normalize_campaigns(campaigns: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in _as_list(campaigns):
        if not isinstance(c, dict):
            continue
        out.append(_normalize_campaign(c))
    return out


# ----------------------------
# Migration (NO recursion)
# ----------------------------
def _migrate_legacy_if_needed() -> None:
    """
    One-shot, safe migrations.
    Reads raw json files, normalizes, writes back.
    MUST NOT call load_requests/load_campaigns (to avoid recursion).
    """
    ensure_dirs()

    # requests
    raw_req = _read_json(REQUESTS_PATH, [])
    norm_req = normalize_requests_ids(raw_req)
    _write_json(REQUESTS_PATH, norm_req)

    # campaigns
    raw_camp = _read_json(CAMPAIGNS_PATH, [])
    norm_camp = _normalize_campaigns(raw_camp)
    _write_json(CAMPAIGNS_PATH, norm_camp)


# ----------------------------
# Public API used by pages
# ----------------------------
def load_requests() -> List[Dict[str, Any]]:
    _migrate_legacy_if_needed()
    return normalize_requests_ids(_read_json(REQUESTS_PATH, []))


def save_requests(requests: List[Dict[str, Any]]) -> None:
    _write_json(REQUESTS_PATH, normalize_requests_ids(requests))


def save_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append a request (or update if id exists).
    Ensures non-empty id.
    Returns normalized request.
    """
    requests = load_requests()

    rid = (req.get("id") or "").strip()
    if not rid:
        rid = _new_id("req")
        req["id"] = rid

    req_norm = normalize_requests_ids([req])[0]

    replaced = False
    for i, r in enumerate(requests):
        if r.get("id") == rid:
            requests[i] = {**r, **req_norm, "updated_at": now_iso()}
            replaced = True
            break

    if not replaced:
        requests.append(req_norm)

    save_requests(requests)
    return req_norm


def update_request(request_id: str, patch: Dict[str, Any]) -> None:
    requests = load_requests()
    changed = False

    for i, r in enumerate(requests):
        if r.get("id") == request_id:
            requests[i] = {**r, **patch, "updated_at": patch.get("updated_at") or now_iso()}
            changed = True
            break

    if changed:
        save_requests(requests)


def load_campaigns() -> List[Dict[str, Any]]:
    _migrate_legacy_if_needed()
    return _normalize_campaigns(_read_json(CAMPAIGNS_PATH, []))


def save_campaigns(campaigns: List[Dict[str, Any]]) -> None:
    _write_json(CAMPAIGNS_PATH, _normalize_campaigns(campaigns))


def upsert_campaign(camp: Dict[str, Any]) -> Dict[str, Any]:
    campaigns = load_campaigns()

    cid = str(camp.get("id") or "").strip()
    if not cid:
        cid = _new_id("camp")
        camp["id"] = cid

    camp_norm = _normalize_campaign(camp)

    replaced = False
    for i, c in enumerate(campaigns):
        if c.get("id") == cid:
            campaigns[i] = {**c, **camp_norm, "updated_at": now_iso()}
            replaced = True
            break

    if not replaced:
        campaigns.append(camp_norm)

    save_campaigns(campaigns)
    return camp_norm


# Alias (some pages may expect save_campaign)
def save_campaign(camp: Dict[str, Any]) -> Dict[str, Any]:
    return upsert_campaign(camp)


def update_campaign(campaign_id: str, patch: Dict[str, Any]) -> None:
    campaigns = load_campaigns()
    changed = False

    for i, c in enumerate(campaigns):
        if c.get("id") == campaign_id:
            campaigns[i] = {**c, **patch, "updated_at": patch.get("updated_at") or now_iso()}
            changed = True
            break

    if changed:
        save_campaigns(campaigns)


# ----------------------------
# NEW: helper to create campaign from request (for coach inbox workflow)
# ----------------------------
def create_campaign_from_request(req: Dict[str, Any], coach_email: str = "") -> Dict[str, Any]:
    """
    Non-breaking helper.
    - Keeps your current schema compatibility
    - Sets checkpoints for check-in/check-out/touchpoints
    - Default status: coach_validated (you can set checkin_pending in UI if you want)
    """
    req_norm = normalize_requests_ids([req])[0]

    weeks = req_norm.get("weeks") or 3
    try:
        weeks = int(weeks)
    except Exception:
        weeks = 3

    supports_in = _as_list(req_norm.get("supports"))
    supports_norm: List[Dict[str, str]] = []
    for s in supports_in:
        d = _support_to_dict(s)
        if d:
            supports_norm.append(d)

    camp = {
        "id": _new_id("camp"),
        "request_id": req_norm.get("id", ""),
        "learner_email": req_norm.get("email", ""),
        "coach_email": (coach_email or "").strip(),
        "objective": req_norm.get("objective", ""),
        "context": req_norm.get("context", ""),
        "supports": supports_norm,
        "weeks": weeks,
        "status": "coach_validated",
        "program": [],
        "messages": [],
        "checkpoints": _default_checkpoints(weeks),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    return _normalize_campaign(camp)
