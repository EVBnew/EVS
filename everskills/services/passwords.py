from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass


PBKDF2_ITERATIONS = 200_000


def generate_temp_password(length: int = 14) -> str:
    # readable + strong (no ambiguous chars)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#%?"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_password_pbkdf2(password: str) -> str:
    """
    Returns: pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>
    """
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("utf-8").rstrip("=")
    dk_b64 = base64.urlsafe_b64encode(dk).decode("utf-8").rstrip("=")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${dk_b64}"


def verify_password_pbkdf2(password: str, stored: str) -> bool:
    try:
        scheme, iters_s, salt_b64, dk_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iters = int(iters_s)

        # restore padding
        def _pad(s: str) -> str:
            return s + "=" * ((4 - len(s) % 4) % 4)

        salt = base64.urlsafe_b64decode(_pad(salt_b64).encode("utf-8"))
        dk_stored = base64.urlsafe_b64decode(_pad(dk_b64).encode("utf-8"))

        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, dk_stored)
    except Exception:
        return False
