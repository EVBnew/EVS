import streamlit as st

from ever_skills.services.storage import storage

st.set_page_config(page_title="EverSKILLS — Ma campagne", layout="wide")
st.title("📌 Ma campagne EverSKILLS")
st.caption("Valide le programme proposé par ton coach, puis suis tes actions semaine par semaine.")

role = st.session_state.get("evs_role", "learner")
email = (st.session_state.get("evs_email") or "").strip().lower()
coach_email = (st.session_state.get("evs_coach_email") or "coach@everboarding.fr").strip().lower()

if role != "learner":
    st.warning("Tu es en mode Coach. Passe en mode Learner dans la sidebar.")
    st.stop()

if not email:
    st.error("Renseigne ton email dans la sidebar.")
    st.stop()

campaigns = [
    c for c in storage.list_campaigns()
    if c.get("learner_email") == email and c.get("coach_email") == coach_email
]
if not campaigns:
    st.info("Aucune campagne trouvée. Crée d’abord une demande.")
    st.page_link("ever_skills/pages/learner_request.py", label="➡️ Soumettre une demande", icon="📝")
    st.stop()

def label(c):
    return f"{c.get('id')} — {c.get('status')} — {c.get('objective_raw')[:45]}"

c = st.selectbox("Choisir une campagne", campaigns, format_func=label)
cid = c.get("id")
c = storage.get_campaign(cid)

st.divider()
st.subheader("Résumé")
st.write(f"- ID : `{c['id']}`")
st.write(f"- Statut : **{c.get('status')}**")
st.write(f"- Coach : **{c.get('coach_email')}**")

st.markdown("### Objectif")
st.info(c.get("objective_raw", ""))

st.divider()
status = c.get("status")

if status == "submitted":
    st.info("Ta demande est en cours de traitement par le coach RH.")

elif status == "coach_validated":
    st.subheader("✅ Programme proposé par le coach")
    program = c.get("program") or {}
    st.write(program.get("objective", ""))
    for w in (program.get("weeks") or []):
        st.markdown(f"#### Semaine {w.get('week')}")
        st.write(f"**Réactivation :** {w.get('reactivation')}")
        st.write(f"**Exercice terrain :** {w.get('practice')}")
        st.write(f"**Prise de recul :** {w.get('reflection')}")
        st.markdown("---")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🚀 Valider et démarrer la campagne", type="primary", use_container_width=True):
            storage.update_campaign(cid, {"status": "active"})
            storage.add_message(cid, "learner", "Programme validé. Je démarre la campagne.")
            st.success("Campagne démarrée (status=active).")
            st.rerun()

    with col2:
        adj = st.text_area("Demander un ajustement (optionnel)", height=90)
        if st.button("✉️ Envoyer au coach", use_container_width=True):
            if adj.strip():
                storage.add_message(cid, "learner", f"Demande d’ajustement : {adj.strip()}")
                st.success("Demande envoyée.")
                st.rerun()
            else:
                st.warning("Écris un message d’ajustement (ou valide le programme).")

elif status == "active":
    st.subheader("📆 Suivi de campagne (active)")
    program = c.get("program") or {}
    weeks = program.get("weeks") or []
    if not weeks:
        st.warning("Programme manquant. Contacte le coach.")
    else:
        wk = st.selectbox("Semaine", [w.get("week") for w in weeks], index=0)
        w = [x for x in weeks if x.get("week") == wk][0]

        st.markdown(f"### Semaine {wk}")
        st.write(f"**Réactivation :** {w.get('reactivation')}")
        st.write(f"**Exercice terrain :** {w.get('practice')}")
        st.write(f"**Prise de recul :** {w.get('reflection')}")

        st.divider()
        fb = st.text_area("🗒️ Mon feedback (réalisé / difficultés / apprentissages)", height=120)
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("💾 Enregistrer mon feedback", use_container_width=True):
                if fb.strip():
                    storage.add_feedback(cid, wk, fb.strip())
                    st.success("Feedback enregistré.")
                    st.rerun()
                else:
                    st.warning("Écris un feedback (même court).")
        with col2:
            msg = st.text_area("💬 Contacter le coach (optionnel)", height=120)
            if st.button("Envoyer au coach", use_container_width=True):
                if msg.strip():
                    storage.add_message(cid, "learner", msg.strip())
                    st.success("Message envoyé.")
                    st.rerun()
                else:
                    st.warning("Écris un message.")

        st.divider()
        if st.button("✅ Clôturer la campagne", use_container_width=True):
            storage.update_campaign(cid, {"status": "closed"})
            storage.add_message(cid, "learner", "Campagne clôturée. Merci.")
            st.success("Campagne clôturée.")
            st.rerun()

elif status == "closed":
    st.success("🎉 Campagne clôturée.")
    st.caption("Tu peux lancer une nouvelle demande pour un nouvel objectif.")
    st.page_link("ever_skills/pages/learner_request.py", label="➡️ Nouvelle demande", icon="📝")

st.divider()
st.subheader("💬 Messages")
msgs = (c.get("messages") or [])
if not msgs:
    st.caption("Aucun message.")
else:
    for m in msgs[-20:]:
        st.write(f"**{m.get('from')}** — {m.get('ts')}")
        st.write(m.get("text"))
        st.markdown("---")


