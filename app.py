# app.py
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure repo root (EVERSKILLS/) is on PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.access import ensure_demo_seed, authenticate  # noqa: E402


st.set_page_config(page_title="WELCOME — EVERSKILLS", layout="wide")

# Seed demo accounts if access.json is empty
try:
    ensure_demo_seed()
except Exception:
    pass

# Optional: hide Streamlit default multipage nav (avoid “mix”)
st.markdown(
    """
<style>
section[data-testid="stSidebarNav"] { display: none; }
</style>
""",
    unsafe_allow_html=True,
)

# Optional brand
try:
    from utils.brand import apply_brand, h1  # type: ignore

    apply_brand()
except Exception:
    pass


def _logout() -> None:
    for k in ["user", "just_logged_in"]:
        if k in st.session_state:
            del st.session_state[k]


def _route_user(u: dict) -> None:
    role = (u.get("role") or "").strip()
    if role == "learner":
        st.switch_page("pages/11_learner_space.py")
    else:
        # coach/admin/super_admin
        st.switch_page("pages/10_coach_space.py")


# Sidebar "platform" navigation (light)
with st.sidebar:
    st.markdown("## EVERSKILLS")
    st.caption("Platform demo (HR / Learning Tech)")
    st.divider()

    st.page_link("app.py", label="Welcome", icon="🏠")
    st.page_link("pages/01_organization.py", label="Organization", icon="🏢")
    st.page_link("pages/03_training.py", label="Mes formations", icon="🎓")

    st.divider()
    st.caption("Espaces opérationnels (selon rôle)")
    st.page_link("pages/10_coach_space.py", label="Coach Space", icon="🧠")
    st.page_link("pages/11_learner_space.py", label="Learner Space", icon="🎯")


# -----------------------------
# WELCOME content
# -----------------------------
try:
    h1("WELCOME")  # type: ignore
except Exception:
    st.title("WELCOME")

st.caption("Connexion à EVERSKILLS — plateforme de suivi post-formation coachée (démo)")

user = st.session_state.get("user")

# If we just logged in, route immediately (no extra click)
if user and st.session_state.get("just_logged_in") is True:
    st.session_state["just_logged_in"] = False
    _route_user(user)

left, right = st.columns([1.2, 1.0], gap="large")

with left:
    st.subheader("Accès")

    if user:
        st.success(f"Connecté : {user.get('email')} — rôle: {user.get('role')}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("➡️ Ouvrir mon espace", use_container_width=True):
                _route_user(user)
        with c2:
            if st.button("🚪 Logout", use_container_width=True):
                _logout()
                st.rerun()
    else:
        st.info("Connecte-toi pour accéder directement à ton espace.")
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", value="", placeholder="ex: nguyen.valery1@gmail.com")
            password = st.text_input("Mot de passe", value="", type="password", placeholder="ex: demo1234")
            submitted = st.form_submit_button("🔐 Login")

        if submitted:
            u = authenticate((email or "").strip(), password or "")
            if not u:
                st.error("Login échoué (email / mot de passe / statut).")
            else:
                st.session_state["user"] = u
                st.session_state["just_logged_in"] = True
                st.success("Login OK ✅ Redirection…")
                st.rerun()

        st.markdown(
            """
**Comptes démo**  
- Admin : `admin@everboarding.fr` / `demo1234`  
- Coach : `contact@everboarding.fr` / `demo1234`  
- Learner : `nguyen.valery1@gmail.com` / `demo1234`
"""
        )

with right:
    st.subheader("Rappel")
    st.markdown(
        """
- **Learner** : soumet une demande, valide le programme, fait ses updates hebdo.
- **Coach** : traite les demandes, génère/publie le programme, suit la progression, clôture la campagne.
"""
    )

st.divider()
st.caption("Tip démo : connecte-toi, tu es routé automatiquement vers l’espace correspondant.")
