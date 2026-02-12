# everskills/services/guard.py
from __future__ import annotations

from typing import Iterable, Optional, Set

import streamlit as st


def require_role(allowed_roles: Iterable[str], *, redirect: str = "app.py") -> None:
    """
    Guard anti-accès direct URL.
    - lit st.session_state["user"] (dict)
    - compare user["role"] à allowed_roles
    - super_admin bypass (toujours autorisé)
    """
    allowed: Set[str] = {str(r).strip() for r in allowed_roles if str(r).strip()}

    user = st.session_state.get("user")
    if not isinstance(user, dict):
        st.error("Tu dois te connecter.")
        try:
            st.switch_page(redirect)
        except Exception:
            pass
        st.stop()

    role = str(user.get("role") or "").strip()

    # super_admin = accès total
    if role == "super_admin":
        return

    if role not in allowed:
        st.error("Cette page n'est pas accessible avec ton profil.")
        st.stop()
