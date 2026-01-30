import streamlit as st
from ever_skills.services.storage import storage

st.set_page_config(page_title="EverSKILLS — Coach Programmes", layout="wide")
st.title("🧩 Coach RH — Programmes / campagnes")
st.caption("Vue rapide de toutes tes campagnes (coach). Pour traiter une demande: Inbox.")

role = st.session_state.get("evs_role", "learner")
coach_email = (st.session_state.get("evs_coach_email") or "coach@everboarding.fr").strip().lower()

if role != "coach":
    st.warning("Passe en mode Coach dans la sidebar.")
    st.stop()

campaigns = [c for c in storage.list_campaigns() if c.get("coach_email") == coach_email]
if not campaigns:
    st.info("Aucune campagne pour ce coach.")
    st.stop()

for c in campaigns:
    st.markdown(f"### {c.get('id')} — {c.get('status')}")
    st.write(f"Learner: **{c.get('learner_email')}**")
    st.write(f"Objectif: {c.get('objective_raw')}")
    st.write(f"Mis à jour: {c.get('updated_at')}")
    st.markdown("---")

