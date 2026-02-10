# everskills/services/access.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from everskills.services.passwords import hash_password_pbkdf2, verify_password_pbkdf2

# ---------------------------------------------------------------------
# Super Admin (email-based override)
# ---------------------------------------------------------------------
SUPER_ADMIN_EMAILS = {"admin@everboarding.fr"}

BASE_DIR = Path(__file__).resolve().parents[2]  # EVERSKILLS/
DATA_DIR = BASE_DIR / "data"
ACCESS_PATH = DATA_DIR / "access.json"

ROLES = ["learner", "coach", "admin", "super_admin", "manager"]
ADMIN_ROLES = {"admin", "super_admin"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _is_super_admin_email(email: str) -> bool:
    em = _norm_email(email)
    return em in {_norm_email(x) for x in SUPER_ADMIN_EMAILS}


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


def load_access() -> List[Dict[str, Any]]:
    data = _read_json(ACCESS_PATH, default=[])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def save_access(rows: List[Dict[str, Any]]) -> None:
    rows = [r for r in rows if isinstance(r, dict) and r.get("email")]
    _write_json(ACCESS_PATH, rows)


def find_user(email: str) -> Optional[Dict[str, Any]]:
    email = _norm_email(email)
    for u in load_access():
        if _norm_email(u.get("email", "")) == email:
            return u
    return None


def upsert_user(user: Dict[str, Any]) -> None:
    email = _norm_email(user.get("email", ""))
    if not email:
        raise ValueError("Missing email")

    user["email"] = email
    user["first_name"] = str(user.get("first_name") or "").strip()
    user["last_name"] = str(user.get("last_name") or "").strip()

    rows = load_access()
    replaced = False
    for i, u in enumerate(rows):
        if _norm_email(u.get("email", "")) == email:
            rows[i] = user
            replaced = True
            break
    if not replaced:
        rows.append(user)
    save_access(rows)


def create_user(
    email: str,
    role: str,
    password: str,
    status: str = "active",
    created_by: str = "system",
    first_name: str = "",
    last_name: str = "",
) -> Dict[str, Any]:
    email = _norm_email(email)
    role = (role or "").strip()
    status = (status or "active").strip()

    if not email or "@" not in email:
        raise ValueError("Invalid email")
    if role not in ROLES:
        raise ValueError("Invalid role")
    if status not in ("active", "inactive", "pending"):
        raise ValueError("Invalid status")

    # Force super_admin role for listed emails
    if _is_super_admin_email(email):
        role = "super_admin"

    user = {
        "email": email,
        "role": role,
        "status": status,
        "first_name": (first_name or "").strip(),
        "last_name": (last_name or "").strip(),
        "password_hash": hash_password_pbkdf2(password),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": _norm_email(created_by),
    }
    upsert_user(user)
    return user


# -----------------------------------------------------------------------------
# Google Sheet helpers (CR06)
# -----------------------------------------------------------------------------
def _find_user_in_gsheet(email: str) -> Optional[Dict[str, Any]]:
    try:
        from everskills.services.gsheet_access import get_gsheet_api  # local import to avoid cycles

        api = get_gsheet_api()
        res = api.list_users()
        if not res.ok:
            return None
        rows = res.data.get("rows", [])
        em = _norm_email(email)
        for r in rows:
            if _norm_email(str(r.get("email") or "")) == em:
                return r
        return None
    except Exception:
        return None


def _update_user_in_gsheet(*, email: str, updates: Dict[str, Any], request_id: str = "") -> None:
    try:
        from everskills.services.gsheet_access import get_gsheet_api  # local import to avoid cycles

        api = get_gsheet_api()
        api.update_user(request_id=request_id, email=_norm_email(email), updates=updates)
    except Exception:
        pass


def set_password(email: str, new_password: str, actor: str = "admin") -> None:
    email = _norm_email(email)
    u = find_user(email)
    if not u:
        raise ValueError("User not found")

    new_hash = hash_password_pbkdf2(new_password)
    u["password_hash"] = new_hash
    u["updated_at"] = now_iso()
    u["last_password_reset_by"] = _norm_email(actor)
    upsert_user(u)

    # Mirror to GSheet (same hash field used by approvals/login fallback)
    _update_user_in_gsheet(email=email, updates={"initial_password": new_hash})


def change_password(email: str, old_password: str, new_password: str) -> None:
    """
    User changes own password (requires current password).
    Mirrors new hash to GSheet.initial_password.
    """
    email = _norm_email(email)
    u = find_user(email)
    if not u:
        raise ValueError("User not found")

    if not verify_password_pbkdf2(old_password or "", str(u.get("password_hash") or "")):
        raise ValueError("Mot de passe actuel incorrect")

    if not new_password or len(new_password) < 4:
        raise ValueError("Nouveau mot de passe trop court")

    new_hash = hash_password_pbkdf2(new_password)
    u["password_hash"] = new_hash
    u["updated_at"] = now_iso()
    u["last_password_change_at"] = now_iso()
    upsert_user(u)

    _update_user_in_gsheet(email=email, updates={"initial_password": new_hash})


def set_status(email: str, new_status: str, actor: str = "admin") -> None:
    email = _norm_email(email)
    u = find_user(email)
    if not u:
        raise ValueError("User not found")
    if new_status not in ("active", "inactive", "pending"):
        raise ValueError("Invalid status")
    u["status"] = new_status
    u["updated_at"] = now_iso()
    u["last_status_change_by"] = _norm_email(actor)
    upsert_user(u)


def authenticate(email: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Auth strategy:
      1) local access.json
      2) fallback Google Sheet:
         - status must be active
         - password checked against sheet.initial_password (same pbkdf2 format)
         - bootstrap user locally (store same hash in password_hash)
    """
    email = _norm_email(email)

    # 1) Local
    u = find_user(email)
    if u:
        if (u.get("status") or "") != "active":
            return None
        if not verify_password_pbkdf2(password or "", str(u.get("password_hash") or "")):
            return None

        role = str(u.get("role") or "learner").strip()
        if _is_super_admin_email(email):
            role = "super_admin"

        return {
            "email": email,
            "role": role,
            "status": str(u.get("status") or "active"),
            "first_name": str(u.get("first_name") or "").strip(),
            "last_name": str(u.get("last_name") or "").strip(),
        }

    # 2) Google Sheet fallback
    row = _find_user_in_gsheet(email)
    if not row:
        return None

    status = str(row.get("status") or "").strip().lower()
    if status != "active":
        return None

    sheet_hash = str(row.get("initial_password") or "").strip()
    if not sheet_hash:
        return None

    if not verify_password_pbkdf2(password or "", sheet_hash):
        return None

    role = str(row.get("role") or "learner").strip() or "learner"
    if _is_super_admin_email(email):
        role = "super_admin"
    elif role not in ROLES:
        role = "learner"

    local_user = {
        "email": email,
        "role": role,
        "status": "active",
        "first_name": str(row.get("first_name") or "").strip(),
        "last_name": str(row.get("last_name") or "").strip(),
        "password_hash": sheet_hash,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": "bootstrap_gsheet",
        "bootstrap_request_id": str(row.get("request_id") or "").strip(),
    }
    upsert_user(local_user)

    return {
        "email": email,
        "role": role,
        "status": "active",
        "first_name": local_user["first_name"],
        "last_name": local_user["last_name"],
    }

# ---------------------------------------------------------------------
# Session token helpers (stateless, signed)
# ---------------------------------------------------------------------
import base64
import hmac
import hashlib
import time

# Secret partagé (réutilise les secrets existants)
SESSION_SECRET = (
    "EVERSKILLS_SESSION_SECRET"
)  # override possible via env/secret plus tard


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_session_token(user: Dict[str, Any], ttl_seconds: int = 3600 * 8) -> str:
    """
    Create a signed session token.
    Payload is minimal on purpose (no PII duplication).
    """
    payload = {
        "email": _norm_email(user.get("email", "")),
        "role": user.get("role"),
        "exp": int(time.time()) + ttl_seconds,
    }

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)

    sig = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{payload_b64}.{sig_b64}"


def load_user_from_session_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validate token, check expiration, and rehydrate user from storage.
    """
    if not token or "." not in token:
        return None

    try:
        payload_b64, sig_b64 = token.split(".", 1)

        expected_sig = hmac.new(
            SESSION_SECRET.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(_b64url_encode(expected_sig), sig_b64):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        if int(payload.get("exp", 0)) < int(time.time()):
            return None

        email = _norm_email(payload.get("email", ""))
        if not email:
            return None

        # Always rehydrate from source of truth (no blind trust)
        u = find_user(email)
        if not u:
            return None
        if u.get("status") != "active":
            return None

        role = str(u.get("role") or "learner").strip()
        if _is_super_admin_email(email):
            role = "super_admin"

        return {
            "email": email,
            "role": role,
            "status": "active",
            "first_name": str(u.get("first_name") or "").strip(),
            "last_name": str(u.get("last_name") or "").strip(),
        }

    except Exception:
        return None

def ensure_demo_seed() -> None:
    # Seed only missing demo users (do not wipe existing access.json)
    if not find_user("admin@everboarding.fr"):
        create_user("admin@everboarding.fr", "super_admin", "demo1234", status="active", created_by="system", first_name="SuperAdmin")

    if not find_user("contact@everboarding.fr"):
        create_user("contact@everboarding.fr", "admin", "demo1234", status="active", created_by="system", first_name="Admin")

    if not find_user("nguyen.valery1@gmail.com"):
        create_user("nguyen.valery1@gmail.com", "learner", "demo1234", status="active", created_by="system", first_name="Valery")

    if not find_user("6464aguilera@gmail.com"):
        create_user("6464aguilera@gmail.com", "coach", "demo1234", status="active", created_by="system", first_name="Demo", last_name="Coach")




def require_login(session_user: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    if not session_user or not isinstance(session_user, dict):
        return False, "Tu dois te connecter."
    if (session_user.get("status") or "") != "active":
        return False, "Compte inactif."
    if (session_user.get("role") or "") not in ROLES:
        return False, "Rôle invalide."
    return True, ""


def can_access_role(session_user: Dict[str, Any], allowed_roles: set[str]) -> bool:
    role = str(session_user.get("role") or "")
    return role in allowed_roles
