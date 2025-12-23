import sys
from pathlib import Path

# Force the repo root (EVERBOARDING/) into Python path so `import ever_skills...` works on Windows/Streamlit
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

from ever_skills.services.auth import get_context
from ever_skills.services.storage import storage

st.set_page_config(page_title="EverSKILLS", layout="wide")

# Optional: reuse your EVB brand
try:
    from utils.brand import apply_brand, h1
    apply_brand()
    h1("EverSKILLS")
except Exception:
    st.title("EverSKILLS")

st.caption("Module EVERBOARDING — Activation post-formation coachée")

UPLOAD_DIR = Path(__file__).parent / "temp_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ctx = get_context()

with st.sidebar:
    st.header("🔐 Accès")
    st.caption("V1: authentification simple (email + rôle). Token branchable ensuite.")
    role = st.selectbox("Rôle", ["Learner (apprenant)", "Coach RH"], index=0)
    email = st.text_input("Email", value=ctx.get("email", "")).strip().lower()
    coach_email = st.text_input(
        "Email coach (référence)",
        value=ctx.get("coach_email", "coach@everboarding.fr")
    ).strip().lower()

    st.divider()
    st.header("🧭 Navigation")
if role.startswith("Learner"):
    st.page_link("pages/learner_request.py", label="✍️ Soumettre une demande", icon="📝")
    st.page_link("pages/learner_campaign.py", label="📆 Ma campagne", icon="📌")
else:
    st.page_link("pages/coach_inbox.py", label="📥 Demandes", icon="📥")
    st.page_link("pages/coach_program.py", label="🧩 Programmes / campagnes", icon="🧩")


# Share context to pages
st.session_state["evs_role"] = "learner" if role.startswith("Learner") else "coach"
st.session_state["evs_email"] = email
st.session_state["evs_coach_email"] = coach_email

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Ce que fait EverSKILLS (V1)")
    st.markdown(
        """
- L’apprenant exprime **un objectif de progression** (avec ou sans support).
- Le coach RH **prépare un programme** (V1: heuristique) et le valide.
- L’apprenant valide, puis la campagne devient **active**.
- L’apprenant partage ses retours, le coach répond.
        """
    )

with col2:
    st.subheader("Statut en live")
    db = storage.load()
    st.metric("Campagnes", len(db.get("campaigns", [])))
    submitted = sum(1 for c in db.get("campaigns", []) if c.get("status") == "submitted")
    coach_validated = sum(1 for c in db.get("campaigns", []) if c.get("status") == "coach_validated")
    active = sum(1 for c in db.get("campaigns", []) if c.get("status") == "active")
    st.write(f"- submitted: **{submitted}**")
    st.write(f"- coach_validated: **{coach_validated}**")
    st.write(f"- active: **{active}**")

st.divider()
st.info("➡️ Utilise la navigation à gauche pour créer une demande (Learner) ou traiter les demandes (Coach).")
