import streamlit as st

from ever_skills.services.storage import storage

st.set_page_config(page_title="EverSKILLS — Coach Inbox", layout="wide")
st.title("📥 Coach RH — Demandes EverSKILLS")
st.caption("Traite les demandes entrantes. Génère un programme, ajuste, puis envoie à validation apprenant.")

role = st.session_state.get("evs_role", "learner")
coach_email = (st.session_state.get("evs_coach_email") or "coach@everboarding.fr").strip().lower()

if role != "coach":
    st.warning("Tu es en mode Learner. Passe en mode Coach dans la sidebar.")
    st.stop()

db = storage.load()
campaigns = db.get("campaigns", [])

submitted = [c for c in campaigns if c.get("status") == "submitted" and c.get("coach_email") == coach_email]
coach_validated = [c for c in campaigns if c.get("status") == "coach_validated" and c.get("coach_email") == coach_email]
active = [c for c in campaigns if c.get("status") == "active" and c.get("coach_email") == coach_email]

colA, colB, colC = st.columns(3)
colA.metric("Demandes à traiter", len(submitted))
colB.metric("En validation apprenant", len(coach_validated))
colC.metric("Campagnes actives", len(active))

st.divider()

def label(c):
    return f"{c.get('id')} — {c.get('learner_email')} — {c.get('objective_raw')[:50]}"

choices = submitted or coach_validated or active
if not choices:
    st.info("Aucune demande / campagne pour ce coach.")
    st.stop()

selected = st.selectbox("Sélectionner une demande/campagne", choices, format_func=label)
cid = selected.get("id")
c = storage.get_campaign(cid)
if not c:
    st.error("Campagne introuvable (rafraîchis).")
    st.stop()

st.subheader("Détails")
st.write(f"- ID : `{c['id']}`")
st.write(f"- Learner : **{c['learner_email']}**")
st.write(f"- Statut : **{c['status']}**")
st.write(f"- Durée : **{c.get('weeks', 3)} semaines**")
if c.get("support"):
    st.write(f"- Support : `{c['support'].get('filename')}` (stocké: `{c['support'].get('stored_as')}`)")

st.markdown("### Objectif brut")
st.info(c.get("objective_raw", ""))

def heuristic_program(objective_raw: str, weeks: int = 3):
    weeks = int(weeks)
    base_obj = objective_raw.strip()
    return {
        "objective": f"Objectif opérationnel : {base_obj}",
        "weeks": [
            {
                "week": w,
                "reactivation": "Rappel d’un concept clé + 1 point d’attention.",
                "practice": "1 situation réelle à tester + 1 phrase-type / comportement observable.",
                "reflection": "Qu’est-ce qui a aidé / bloqué ? Que je fais différemment la prochaine fois ?",
            }
            for w in range(1, weeks + 1)
        ],
        "notes_coach": "Ajuste le vocabulaire au contexte (métier, manager, équipe).",
    }

st.divider()
st.subheader("🧩 Programme EverSKILLS")

program = c.get("program") or heuristic_program(c.get("objective_raw", ""), c.get("weeks", 3))

objective = st.text_area("Objectif reformulé (coach)", value=program.get("objective", ""), height=90)
notes_coach = st.text_area("Notes coach (optionnel)", value=program.get("notes_coach", ""), height=70)

weeks_list = program.get("weeks", [])
edited_weeks = []
for w in weeks_list:
    st.markdown(f"#### Semaine {w.get('week')}")
    reactivation = st.text_area(
        f"Réactivation (S{w.get('week')})",
        value=w.get("reactivation", ""),
        height=70,
        key=f"re_{cid}_{w.get('week')}",
    )
    practice = st.text_area(
        f"Exercice terrain (S{w.get('week')})",
        value=w.get("practice", ""),
        height=70,
        key=f"pr_{cid}_{w.get('week')}",
    )
    reflection = st.text_area(
        f"Prise de recul (S{w.get('week')})",
        value=w.get("reflection", ""),
        height=70,
        key=f"rf_{cid}_{w.get('week')}",
    )
    edited_weeks.append(
        {
            "week": int(w.get("week")),
            "reactivation": reactivation,
            "practice": practice,
            "reflection": reflection,
        }
    )

new_program = {"objective": objective, "weeks": edited_weeks, "notes_coach": notes_coach}

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("💾 Enregistrer le programme", use_container_width=True):
        storage.update_campaign(cid, {"program": new_program})
        st.success("Programme enregistré.")

with col2:
    if c.get("status") == "submitted":
        if st.button("📤 Envoyer à validation apprenant", type="primary", use_container_width=True):
            storage.update_campaign(cid, {"program": new_program, "status": "coach_validated"})
            storage.add_message(cid, "coach", "Programme envoyé à validation. Merci de valider ou demander un ajustement.")
            st.success("Envoyé à l’apprenant (status=coach_validated).")
            st.rerun()

st.divider()
st.subheader("💬 Messages")
msgs = c.get("messages") or []
if not msgs:
    st.caption("Aucun message.")
else:
    for m in msgs[-20:]:
        st.write(f"**{m.get('from')}** — {m.get('ts')}")
        st.write(m.get("text"))
        st.markdown("---")

reply = st.text_area("Répondre à l’apprenant", height=90)
if st.button("Envoyer la réponse"):
    if reply.strip():
        storage.add_message(cid, "coach", reply.strip())
        st.success("Message envoyé.")
        st.rerun()


