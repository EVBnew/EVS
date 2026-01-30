# pages/projects.py
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

role = user["role"]

st.markdown("# Projects")
st.caption("Route automatiquement vers l’espace opérationnel selon ton rôle.")

if role == "learner":
    st.success("Rôle learner détecté → ouverture Learner Space.")
    if st.button("▶ Ouvrir Learner Space", use_container_width=True):
        st.switch_page("pages/11_learner_space.py")

    # auto-route
    st.switch_page("pages/11_learner_space.py")

else:
    st.success("Rôle coach/admin détecté → ouverture Coach Space.")
    if st.button("▶ Ouvrir Coach Space", use_container_width=True):
        st.switch_page("pages/10_coach_space.py")

    st.switch_page("pages/10_coach_space.py")
