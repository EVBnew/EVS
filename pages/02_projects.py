# pages/02_projects.py
from __future__ import annotations

import streamlit as st
from everskills.services.access import require_login

st.set_page_config(page_title="Projects — EVERSKILLS", layout="wide")

user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

role = (user.get("role") or "").strip()

st.markdown("# Projects")
st.caption("Router technique. Normalement, Welcome route déjà automatiquement.")

if role == "learner":
    st.switch_page("pages/11_learner_space.py")
else:
    st.switch_page("pages/10_coach_space.py")
