# app.py
from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

# Ensure repo root (EVERSKILLS/) is on PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.storage import load_campaigns
from everskills.services.access import ensure_demo_seed, authenticate

st.set_page_config(page_title="EverSKILLS", layout="wide")

# Seed demo accounts if access.json is empty
try:
    ensure_demo_seed()
except Exception:
    pass

# Optional brand
try:
    from utils.brand import apply_brand, h1  # type: ignore
    apply_brand()
    h1("EverSKILLS")
except Exception:
    st.title("EverSKILLS")

st.caption("Module EVERBOARDING — Plateforme de suivi post-formation coachée (démo)")

# ------------------------------------------------------------
# OPTIONAL: hide Streamlit default navigation (avoid “mix”)
# ------------------------------------------------------------
st.markdown(
    """
<style>
/* Hide default Streamlit multipage nav */
section[data-testid="stSidebarNav"] { display: none; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Session helpers
# -----------------------------
def _logout() -> None:
    for k in ["user", "learner_email", "coach_email"]:
        if k in st.session_state:
            del st.session_state[k]

# -----------------------------
# Sidebar "platform" navigation
# -----------------------------
with st.sidebar:
    st.markdown("## EverSKILLS")
    st.caption("Platform demo (HR / Learning Tech)")
    st.divider()

    st.page_link("app.py", label="Welcome", icon="🏠")
    st.page_link("pages/01_organization.py", label="Organization", icon="🏢")
    st.page_link("pages/02_projects.py", label="Mes projets", icon="🗂️")
    st.page_link("pages/03_training.py", label="Mes formations", icon="🎓")

    st.divider()
    st.caption("Espaces opérationnels (selon rôle)")
    st.page_link("pages/10_coach_space.py", label="Coach Space", icon="🧠")
    st.page_link("pages/11_learner_space.py", label="Learner Space", icon="🎯")

# -----------------------------
# Welcome content
# -----------------------------
user = st.session_state.get("user")

left, mid, right = st.columns([1.2, 1.4, 1.2], gap="large")

with left:
    st.subheader("Accès")

    if user:
        st.success(f"Connecté : {user.get('email')} — rôle: {user.get('role')}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("➡️ Ouvrir Mes projets", use_container_width=True):
                st.switch_page("pages/02_projects.py")
        with c2:
            if st.button("🚪 Logout", use_container_width=True):
                _logout()
                st.rerun()
    else:
        st.info("Connecte-toi pour ouvrir l’espace Learner / Coach.")
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", value="", placeholder="ex: nguyen.valery1@gmail.com")
            password = st.text_input("Mot de passe", value="", type="password", placeholder="ex: demo1234")
            ok = st.form_submit_button("🔐 Login")

        if ok:
            u = authenticate((email or "").strip(), password or "")
            if not u:
                st.error("Login échoué (email / mot de passe / statut).")
            else:
                st.session_state["user"] = u
                st.success("Login OK ✅")
                st.rerun()

        st.markdown(
            """
**Comptes démo (si access.json vide)**  
- Admin : `admin@everboarding.fr` / `demo1234`  
- Coach : `contact@everboarding.fr` / `demo1234`  
- Learner : `nguyen.valery1@gmail.com` / `demo1234`
"""
        )

with mid:
    st.subheader("Navigation (pitch)")
    st.markdown(
        """
- **Organization** : gérer les accès (People)
- **Mes projets** : route automatiquement vers l’espace Learner / Coach selon le rôle
- **Mes formations** : vitrine de contenus (option sans LMS)
"""
    )

with right:
    st.subheader("Statut en live")
    camps = [c for c in (load_campaigns() or []) if isinstance(c, dict)]
    st.metric("Campagnes", len(camps))
    if camps:
        draft = sum(1 for c in camps if c.get("status") == "draft")
        program_ready = sum(1 for c in camps if c.get("status") == "program_ready")
        active = sum(1 for c in camps if c.get("status") == "active")
        closed = sum(1 for c in camps if c.get("status") == "closed")
        st.write(f"- draft: **{draft}**")
        st.write(f"- program_ready: **{program_ready}**")
        st.write(f"- active: **{active}**")
        st.write(f"- closed: **{closed}**")
    else:
        st.caption("Aucune campagne pour l’instant.")

st.divider()
st.success("➡️ Connecte-toi ici, puis va dans **Mes projets** pour être routé automatiquement.")
