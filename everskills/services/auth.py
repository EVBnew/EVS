from __future__ import annotations
import streamlit as st
from typing import Dict


def get_context() -> Dict[str, str]:
    """
    Contexte minimal pour le proto.
    Stocké en session_state pour éviter les resets.
    """
    ctx = st.session_state.get("ctx")
    if not isinstance(ctx, dict):
        ctx = {
            "role": "learner",
            "email": "",
        }
        st.session_state["ctx"] = ctx
    # normalise
    ctx["role"] = (ctx.get("role") or "learner").strip().lower()
    ctx["email"] = (ctx.get("email") or "").strip().lower()
    return ctx


def set_context(role: str, email: str) -> None:
    st.session_state["ctx"] = {
        "role": (role or "learner").strip().lower(),
        "email": (email or "").strip().lower(),
    }
