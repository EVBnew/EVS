import streamlit as st

def get_context():
    """
    V1: contexte minimal.
    - token branchable ensuite via query params (st.query_params).
    - pour l'instant on stocke juste email/coach_email si dÃ©jÃ  en session.
    """
    q = dict(st.query_params) if hasattr(st, "query_params") else {}
    token = ""
    if "token" in q:
        v = q.get("token")
        token = (v[0] if isinstance(v, list) else v) or ""

    return {
        "token": token,
        "email": st.session_state.get("evs_email", ""),
        "coach_email": st.session_state.get("evs_coach_email", "coach@everboarding.fr"),
    }

