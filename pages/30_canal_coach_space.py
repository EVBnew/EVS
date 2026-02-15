from __future__ import annotations

from typing import Dict, List
import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns
from everskills.services.journal_gsheet import (
    build_entry,
    journal_create,
    journal_list_coach,
)
from everskills.services.mail_send_once import send_once

st.set_page_config(page_title="Canal Coach — EVERSKILLS", layout="wide")

require_role({"coach", "super_admin"})

user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.stop()

coach_email = (user.get("email") or "").strip().lower()

st.title("💬 Canal Coach")
st.caption("Conversation directe avec tes learners")

# -----------------------------
# Charger campagnes du coach
# -----------------------------
campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]
my_camps = [
    c for c in campaigns
    if (c.get("coach_email") or "").lower() == coach_email
]

if not my_camps:
    st.info("Aucune campagne.")
    st.stop()

labels = [
    f"{c.get('learner_email')} — {c.get('id')}"
    for c in my_camps
]

idx = st.selectbox("Choisir un learner", range(len(my_camps)), format_func=lambda i: labels[i])
camp = my_camps[idx]

learner_email = (camp.get("learner_email") or "").strip().lower()

# -----------------------------
# Charger messages
# -----------------------------
try:
    items = journal_list_coach(coach_email, limit=200)
except Exception:
    items = []

items = [
    it for it in items
    if (it.get("author_email") or "").lower() in (learner_email, coach_email)
]

st.markdown("---")

for it in reversed(items):
    body = it.get("body") or ""
    ts = it.get("created_at") or ""
    author = (it.get("author_email") or "").lower()

    is_coach = author == coach_email

    align = "flex-end" if is_coach else "flex-start"
    bg = "#111827" if is_coach else "#F1F3F6"
    color = "white" if is_coach else "black"

    st.markdown(
        f"""
        <div style="display:flex; justify-content:{align}; margin-bottom:8px;">
            <div style="
                background:{bg};
                color:{color};
                padding:10px 14px;
                border-radius:18px;
                max-width:75%;
                font-size:14px;
            ">
                {body.replace('\n','<br>')}
                <div style="font-size:10px; opacity:0.6; margin-top:4px;">
                    {ts}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------
# Input coach
# -----------------------------
st.markdown("---")

message = st.text_area(
    "Répondre",
    height=80,
    placeholder="Répondre au learner…",
    label_visibility="collapsed"
)

if st.button("Envoyer", use_container_width=True):
    if not message.strip():
        st.warning("Message vide.")
    else:
        entry = build_entry(
            author_user_id=str(user.get("id") or coach_email),
            author_email=coach_email,
            body=message.strip(),
            tags="chat",
            share_with_coach=True,
            coach_email=coach_email,
        )
        journal_create(entry)

        cid = str(camp.get("id") or "")

        send_once(
            event_key=f"CHAT_COACH_REPLY:{cid}:{entry.id}",
            event_type="CHAT_COACH_REPLY",
            request_id=cid,
            to_email=learner_email,
            subject=f"[EVERSKILLS] Message coach ({cid})",
            text_body=message.strip(),
            meta={"camp_id": cid},
        )

        st.rerun()
