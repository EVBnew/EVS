from __future__ import annotations

from typing import Any, Dict, List
from datetime import datetime, timezone
import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns
from everskills.services.journal_gsheet import (
    build_entry,
    journal_create,
    journal_list_learner,
)
from everskills.services.mail_send_once import send_once

st.set_page_config(page_title="Canal Coach — EVERSKILLS", layout="wide")

require_role({"learner", "super_admin"})

user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.stop()

learner_email = (user.get("email") or "").strip().lower()

st.title("💬 Canal Coach")
st.caption("Conversation continue avec ton coach")

# -----------------------------
# Charger campagne active
# -----------------------------
campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]
my_camps = [
    c for c in campaigns
    if (c.get("learner_email") or "").lower() == learner_email
]

if not my_camps:
    st.info("Aucune campagne active.")
    st.stop()

camp = my_camps[0]
coach_email = (camp.get("coach_email") or "").strip().lower()

# -----------------------------
# CHAT HISTORY
# -----------------------------
try:
    items = journal_list_learner(learner_email, limit=100)
except Exception:
    items = []

st.markdown("---")

for it in reversed(items):
    body = it.get("body") or ""
    shared = bool(it.get("share_with_coach"))
    ts = it.get("created_at") or ""

    is_mine = (it.get("author_email") or "").lower() == learner_email

    align = "flex-end" if is_mine else "flex-start"
    bg = "#0B5FFF" if is_mine else "#F1F3F6"
    color = "white" if is_mine else "black"

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
# INPUT MESSAGE
# -----------------------------
st.markdown("---")

with st.container():
    message = st.text_area(
        "Ton message",
        height=80,
        placeholder="Écris ici ton post-it ou message rapide…",
        label_visibility="collapsed"
    )

    share = st.toggle("Partager avec mon coach", value=True)

    if st.button("Envoyer", use_container_width=True):
        if not message.strip():
            st.warning("Message vide.")
        else:
            entry = build_entry(
                author_user_id=str(user.get("id") or learner_email),
                author_email=learner_email,
                body=message.strip(),
                tags="chat",
                share_with_coach=share,
                coach_email=coach_email if share else None,
            )
            journal_create(entry)

            if share:
                cid = str(camp.get("id") or "")
                send_once(
                    event_key=f"CHAT_SHARED:{cid}:{entry.id}",
                    event_type="CHAT_SHARED",
                    request_id=cid,
                    to_email=coach_email,
                    subject=f"[EVERSKILLS] Nouveau message learner ({cid})",
                    text_body=message.strip(),
                    meta={"camp_id": cid},
                )

            st.rerun()
