# app.py
from __future__ import annotations

BUILD_ID = "1.21"
BUILD_DATE = "4 février 2026"

import sys
from pathlib import Path

import streamlit as st

# -----------------------------------------------------------------------------
# Ensure repo root (EVERSKILLS/) is on PYTHONPATH
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.access import (  # noqa: E402
    ensure_demo_seed,
    authenticate,
    create_user,
    find_user,
)
from everskills.services.storage import reset_runtime_data  # noqa: E402

# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="WELCOME — EVERSKILLS", layout="wide")

# -----------------------------------------------------------------------------
# Seed demo users (DEV safe)
# -----------------------------------------------------------------------------
try:
    ensure_demo_seed()
except Exception:
    pass


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _logout() -> None:
    for k in ["user", "just_logged_in"]:
        if k in st.session_state:
            del st.session_state[k]


def _route_user(u: dict) -> None:
    role = (u.get("role") or "").strip()
    if role == "learner":
        st.switch_page("pages/11_learner_space.py")
    else:
        st.switch_page("pages/10_coach_space.py")


def _role() -> str:
    u = st.session_state.get("user") or {}
    return (u.get("role") or "").strip()


# -----------------------------------------------------------------------------
# Global CSS (UI preserved)
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
section[data-testid="stSidebarNav"] { display: none; }

.block-container {
    max-width: 1200px;
    padding-top: 2.2rem;
}

div[data-testid="stTextInput"] input {
    border-radius: 10px;
}

/* Buttons */
div[data-testid="stButton"] > button,
div[data-testid="stFormSubmitButton"] > button {
  border-radius: 999px !important;
  padding: 0.55rem 1.2rem !important;
  min-height: 44px !important;
  font-weight: 600 !important;
}

.evs-btn-primary div[data-testid="stFormSubmitButton"] > button {
  background: linear-gradient(180deg, #2F80ED 0%, #1F6FE5 100%) !important;
  color: #FFFFFF !important;
}

.evs-btn-secondary div[data-testid="stFormSubmitButton"] > button {
  background: linear-gradient(180deg, #F7F8FA 0%, #E9EDF3 100%) !important;
  color: #1F2A37 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Optional brand
# -----------------------------------------------------------------------------
try:
    from utils.brand import apply_brand, h1  # type: ignore

    apply_brand()
except Exception:
    h1 = None  # type: ignore


# -----------------------------------------------------------------------------
# Sidebar (role-based)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## EVERSKILLS")
    st.caption(f"EVERSKILLS · version {BUILD_ID} – {BUILD_DATE}")
    st.divider()

    st.page_link("app.py", label="Welcome", icon="🏠")
    st.page_link("pages/03_training.py", label="Mes formations", icon="🎓")

    r = _role()
    if r in ("coach", "admin", "super_admin"):
        st.page_link("pages/01_organization.py", label="Organization", icon="🏢")

    st.divider()
    st.caption("Espaces opérationnels")

    if r == "learner":
        st.page_link("pages/11_learner_space.py", label="Learner Space", icon="🎯")

    if r in ("coach", "admin", "super_admin"):
        st.page_link("pages/10_coach_space.py", label="Coach Space", icon="🧠")

# Hide sidebar on Welcome when not logged
if not st.session_state.get("user"):
    st.markdown(
        """
<style>
section[data-testid="stSidebar"] { display: none; }
</style>
""",
        unsafe_allow_html=True,
    )

# -----------------------------------------------------------------------------
# WELCOME
# -----------------------------------------------------------------------------
if h1:
    h1("WELCOME")  # type: ignore
else:
    st.title("WELCOME")

st.caption("EVERSKILLS · passez de la théorie à la pratique")

user = st.session_state.get("user")

# Immediate redirect after login
if user and st.session_state.get("just_logged_in") is True:
    st.session_state["just_logged_in"] = False
    _route_user(user)

# Already logged
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
    st.stop()

# -----------------------------------------------------------------------------
# LOGIN / SIGNUP
# -----------------------------------------------------------------------------
col_login, col_signup = st.columns([1.15, 1.0], gap="large")

with col_login:
    st.subheader("Accès")

    with st.container(border=True):
        st.markdown("### Connexion")

        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Mot de passe", type="password")

            st.markdown('<div class="evs-btn-primary">', unsafe_allow_html=True)
            submitted = st.form_submit_button("Connexion")
            st.markdown("</div>", unsafe_allow_html=True)

        if submitted:
            u = authenticate((email or "").strip(), password or "")
            if not u:
                st.error("Login échoué.")
            else:
                st.session_state["user"] = u
                st.session_state["just_logged_in"] = True
                st.success("Login OK ✅")
                st.rerun()

with col_signup:
    with st.container(border=True):
        st.markdown("### Créer un compte")

        with st.form("signup_form", clear_on_submit=True):
            first_name = st.text_input("Prénom")
            last_name = st.text_input("Nom")
            new_email = st.text_input("Email")
            new_password = st.text_input("Mot de passe", type="password")

            st.markdown('<div class="evs-btn-secondary">', unsafe_allow_html=True)
            create = st.form_submit_button("Créer mon compte")
            st.markdown("</div>", unsafe_allow_html=True)

        if create:
            fn, ln, em, pw = (
                (first_name or "").strip(),
                (last_name or "").strip(),
                (new_email or "").strip(),
                new_password or "",
            )

            if not fn or not ln or not em or not pw:
                st.error("Tous les champs sont obligatoires.")
            elif "@" not in em:
                st.error("Email invalide.")
            elif len(pw) < 4:
                st.error("Mot de passe trop court.")
            elif find_user(em):
                st.error("Cet email existe déjà.")
            else:
                try:
                    reset_runtime_data()
                    create_user(
                        email=em,
                        role="learner",
                        password=pw,
                        status="active",
                        created_by="self_signup",
                        first_name=fn,
                        last_name=ln,
                    )
                except Exception as e:
                    st.error(str(e))
                    st.stop()

                u = authenticate(em, pw)
                if not u:
                    st.error("Compte créé, mais login impossible.")
                else:
                    st.session_state["user"] = u
                    st.session_state["just_logged_in"] = True
                    st.success("Compte créé ✅")
                    st.rerun()
