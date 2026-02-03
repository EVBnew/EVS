# app.py

BUILD_ID = "evs-prod-2026-02-03-01"

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure repo root (EVERSKILLS/) is on PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.access import ensure_demo_seed, authenticate, create_user, find_user  # noqa: E402
from everskills.services.storage import reset_runtime_data  # noqa: E402


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
    h1 = None  # type: ignore


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
    st.caption("v. 1.1")
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
if h1:
    h1("WELCOME")  # type: ignore
else:
    st.title("WELCOME")

st.caption("EVERSKILLS v. 1.1 — passez de la théorie à la pratique")

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
        # -----------------------------
        # LOGIN
        # -----------------------------
        with st.container(border=True):
            st.markdown("### Se connecter")
            with st.form("login_form", clear_on_submit=False):
                email = st.text_input("Email", value="")
                password = st.text_input("Mot de passe", value="", type="password")
                submitted = st.form_submit_button("🔐 Login", use_container_width=True)

            c1, c2 = st.columns([1, 1])
            with c1:
                st.caption(" ")
            with c2:
                st.markdown(
                    """
<div style="text-align:right; margin-top: 0.2rem;">
<a href="mailto:admin@everboarding.fr?subject=EVERSKILLS%20-%20Mot%20de%20passe%20oubli%C3%A9" style="text-decoration:none;">
Mot de passe oublié ?
</a>
</div>
""",
                    unsafe_allow_html=True,
                )

            if submitted:
                u = authenticate((email or "").strip(), password or "")
                if not u:
                    st.error("Login échoué (email / mot de passe / statut).")
                else:
                    st.session_state["user"] = u
                    st.session_state["just_logged_in"] = True
                    st.success("Login OK ✅ Redirection…")
                    st.rerun()

        st.divider()

        # -----------------------------
        # SIGN-UP (CR03/CR04) + RESET DATASET (Option A)
        # -----------------------------
        with st.container(border=True):
            st.markdown("### Créer un compte")
            st.caption("⚠️ Mode démo : la création de compte réinitialise les données (requests / campagnes / mails).")

            with st.form("signup_form", clear_on_submit=True):
                first_name = st.text_input("Prénom", value="")
                last_name = st.text_input("Nom", value="")
                new_email = st.text_input("Email", value="")
                new_password = st.text_input("Mot de passe", value="", type="password")
                create = st.form_submit_button("✅ Créer mon compte", use_container_width=True)

            if create:
                fn = (first_name or "").strip()
                ln = (last_name or "").strip()
                em = (new_email or "").strip()
                pw = new_password or ""

                if not fn or not ln or not em or not pw:
                    st.error("Tous les champs sont obligatoires.")
                elif "@" not in em:
                    st.error("Email invalide.")
                elif len(pw) < 4:
                    st.error("Mot de passe trop court (min 4 caractères).")
                else:
                    # Prevent overwriting existing accounts
                    if find_user(em):
                        st.error("Cet email existe déjà. Utilise la connexion ou contacte admin@everboarding.fr.")
                    else:
                        # OPTION A: reset runtime data on each sign-up
                        try:
                            reset_runtime_data()
                        except Exception as e:
                            st.error(f"Reset dataset impossible : {e}")
                            st.stop()

                        try:
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

                        # Auto-login
                        u = authenticate(em, pw)
                        if not u:
                            st.error("Compte créé, mais login impossible. Contacte admin@everboarding.fr.")
                        else:
                            st.session_state["user"] = u
                            st.session_state["just_logged_in"] = True
                            st.success("Compte créé ✅ Redirection…")
                            st.rerun()

with right:
    st.subheader("Rappel")
    st.markdown(
        """
- **Learner** : soumet une demande, valide le programme, fait ses updates hebdo.
- **Coach** : traite les demandes, génère/publie le programme, suit la progression, clôture la campagne.
"""
    )

st.divider()
