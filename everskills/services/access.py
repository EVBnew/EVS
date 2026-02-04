# everskills/services/access.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_DIR = Path(__file__).resolve().parents[2]  # EVERSKILLS/
DATA_DIR = BASE_DIR / "data"
ACCESS_PATH = DATA_DIR / "access.json"

ROLES: List[str] = ["learner", "coach", "admin", "super_admin", "manager"]
ADMIN_ROLES: Set[str] = {"admin", "super_admin"}

PBKDF2_ITERS = 210_000


def now_iso() -> str:
    """Local timestamp helper (avoid cross-module import issues)."""
    return datetime.now(timezone.utc).isoformat()


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return default
        return json.loads(raw)
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _pbkdf2_hash(password: str, salt: bytes, iters: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)


def hash_password(password: str) -> str:
    if not password or len(password) < 4:
        raise ValueError("Password too short")
    salt = os.urandom(16)
    dk = _pbkdf2_hash(password, salt, PBKDF2_ITERS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
        dk = _pbkdf2_hash(password or "", salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def load_access() -> List[Dict[str, Any]]:
    data = _read_json(ACCESS_PATH, default=[])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and x.get("email")]


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

    user = dict(user)  # avoid mutating caller
    user["email"] = email
    user["first_name"] = str(user.get("first_name") or "").strip()
    user["last_name"] = str(user.get("last_name") or "").strip()

    rows = load_access()
    for i, u in enumerate(rows):
        if _norm_email(u.get("email", "")) == email:
            rows[i] = user
            save_access(rows)
            return

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

    user = {
        "email": email,
        "role": role,
        "status": status,
        "first_name": (first_name or "").strip(),
        "last_name": (last_name or "").strip(),
        "password_hash": hash_password(password),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": _norm_email(created_by),
    }
    upsert_user(user)
    return user


def set_password(email: str, new_password: str, actor: str = "admin") -> None:
    email = _norm_email(email)
    u = find_user(email)
    if not u:
        raise ValueError("User not found")
    u["password_hash"] = hash_password(new_password)
    u["updated_at"] = now_iso()
    u["last_password_reset_by"] = _norm_email(actor)
    upsert_user(u)


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
    email = _norm_email(email)
    u = find_user(email)
    if not u:
        return None
    if (u.get("status") or "") != "active":
        return None
    if not verify_password(password or "", str(u.get("password_hash") or "")):
        return None

    return {
        "email": email,
        "role": str(u.get("role") or "learner"),
        "status": str(u.get("status") or "active"),
        "first_name": str(u.get("first_name") or "").strip(),
        "last_name": str(u.get("last_name") or "").strip(),
    }


def ensure_demo_seed() -> None:
    rows = load_access()
    if rows:
        return

    create_user("admin@everboarding.fr", "admin", "demo1234", status="active", created_by="system", first_name="Admin")
    create_user("contact@everboarding.fr", "coach", "demo1234", status="active", created_by="system", first_name="Coach")
    create_user("nguyen.valery1@gmail.com", "learner", "demo1234", status="active", created_by="system", first_name="Valery")


def require_login(session_user: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    if not session_user or not isinstance(session_user, dict):
        return False, "Tu dois te connecter."
    if (session_user.get("status") or "") != "active":
        return False, "Compte inactif."
    if (session_user.get("role") or "") not in ROLES:
        return False, "Rôle invalide."
    return True, ""


def can_access_role(session_user: Dict[str, Any], allowed_roles: Set[str]) -> bool:
    role = str(session_user.get("role") or "")
    return role in allowed_roles
