# pages/20_canal_coach.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple
import time
import uuid

import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns, now_iso
from everskills.services.journal_gsheet import (
    build_entry,
    journal_create,
    journal_list_learner,
    journal_list_coach,
)
from everskills.services.mail_send_once import send_once

st.set_page_config(page_title="Canal Coach — EVERSKILLS", layout="wide")

# --- ROLE GUARD (anti accès direct URL)
require_role({"learner", "super_admin"})

# ----------------------------
# Auth
# ----------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

if user.get("role") not in ("learner", "super_admin"):
    st.warning("Cette page est réservée aux apprenants.")
    st.stop()

def _norm_email(s: str) -> str:
    return (s or "").strip().lower()

def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _has_tag(item: Dict[str, Any], tag: str) -> bool:
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        return False
    return tag in [str(t).strip().lower() for t in tags]

learner_email = _norm_email(user.get("email") or "")
if not learner_email:
    st.error("Email learner introuvable (session).")
    st.stop()

st.title("💬 Canal Coach")
st.caption("Post-it + messages rapides. Visible par toi, partageable au coach.")

# -----------------------------
# Charger campagne active (pour trouver coach_email)
# -----------------------------
campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]

my_camps = [
    c for c in campaigns
    if _norm_email(c.get("learner_email", "")) == learner_email
    and str(c.get("status") or "").strip() in ("active", "program_ready", "closed", "draft", "coach_validated")
]

if not my_camps:
    st.info("Pas encore de campagne. Quand ton coach publie, tu pourras utiliser le Canal Coach.")
    st.stop()

labels = [f"{c.get('id','')} — {c.get('status','')} — {str(c.get('objective',''))[:50]}" for c in my_camps]
idx = st.selectbox("Choisir une campagne", range(len(my_camps)), format_func=lambda i: labels[i])
camp = my_camps[idx]

camp_id = str(camp.get("id") or "").strip()
coach_email = _norm_email(str(camp.get("coach_email") or "") or st.session_state.get("evs_coach_email") or "")
if not coach_email:
    coach_email = "admin@everboarding.fr"

# Tag de routage pour ne voir QUE les messages de CE learner
LEARNER_TAG = f"learner:{learner_email}"

# -----------------------------
# Composer (Post-it / message)
# -----------------------------
with st.container(border=True):
    st.markdown("### 🗒️ Nouveau post-it / message")

    mood = st.selectbox(
        "Humeur",
        options=["🟢 En confiance", "🔵 Flow", "🟡 Neutre", "🟠 Tendu", "🔴 Fatigué"],
        index=2,
        key=f"cc_mood_{camp_id}",
    )

    postit = st.text_area(
        "Message",
        height=120,
        placeholder="Écris ton post-it ici (idée, test, ressenti, question au coach...)",
        key=f"cc_body_{camp_id}",
    )

    tags_txt = st.text_input(
        "Tags (optionnel)",
        placeholder="ex: focus, respiration, assertivité",
        key=f"cc_tags_{camp_id}",
    )

    share_with_coach = st.toggle("Partager avec mon coach", value=True, key=f"cc_share_{camp_id}")

    c1, c2 = st.columns([1, 1])
    with c1:
        btn = st.button("Envoyer", use_container_width=True)
    with c2:
        st.caption(f"Coach: {coach_email}")

    if btn:
        if not postit.strip():
            st.warning("Message vide.")
        else:
            body = f"{mood}\n\n{postit.strip()}"
            # tags: toujours chat + learner tag, + tags user
            tags_full = ",".join([t for t in ["chat", LEARNER_TAG, (tags_txt or "").strip()] if t])

            try:
                entry = build_entry(
                    author_user_id=str(user.get("user_id") or user.get("id") or learner_email),
                    author_email=learner_email,
                    body=body,
                    tags=tags_full,
                    share_with_coach=bool(share_with_coach),
                    coach_email=coach_email if share_with_coach else None,
                    prompt="Canal Coach",
                )
                journal_create(entry)

                # Email coach immédiat (inchangé)
                if share_with_coach:
                    send_once(
                        event_key=f"CANAL_COACH_LEARNER:{camp_id}:{entry.id}",
                        event_type="CANAL_COACH_LEARNER",
                        request_id=camp_id,
                        to_email=coach_email,
                        subject=f"[EVERSKILLS] Message learner ({camp_id})",
                        text_body=f"Learner: {learner_email}\n\n{body}",
                        meta={"camp_id": camp_id, "learner_email": learner_email, "coach_email": coach_email, "journal_id": entry.id},
                    )

                st.success("Envoyé ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur: {e}")

# -----------------------------
# Conversation (merge learner + coach)
# -----------------------------
st.markdown("---")
st.subheader("💬 Conversation")

# 1) messages du learner (source learner)
try:
    learner_items = journal_list_learner(learner_email, limit=200)
except Exception:
    learner_items = []

learner_items = [
    it for it in learner_items
    if isinstance(it, dict)
    and _has_tag(it, "chat")
    and _has_tag(it, LEARNER_TAG)
]

# 2) messages du coach (source coach)
try:
    coach_items = journal_list_coach(coach_email, limit=300)
except Exception:
    coach_items = []

coach_items = [
    it for it in coach_items
    if isinstance(it, dict)
    and _has_tag(it, "chat")
    and _has_tag(it, LEARNER_TAG)
    and _norm_email(it.get("author_email") or "") == coach_email
]

# merge + tri
all_items = learner_items + coach_items
all_items = sorted(all_items, key=lambda x: _to_int(x.get("created_at"), 0))

if not all_items:
    st.info("Aucun message pour l’instant.")
    st.stop()

# Render bulles type WhatsApp
for it in all_items:
    body = str(it.get("body") or "")
    ts = str(it.get("created_at") or "")
    author = _norm_email(it.get("author_email") or "")

    is_me = author == learner_email
    align = "flex-end" if is_me else "flex-start"
    bg = "#111827" if is_me else "#F1F3F6"
    color = "white" if is_me else "black"

    st.markdown(
        f"""
        <div style="display:flex; justify-content:{align}; margin-bottom:8px;">
            <div style="
                background:{bg};
                color:{color};
                padding:10px 14px;
                border-radius:18px;
                max-width:78%;
                font-size:14px;
                line-height:1.35;
                box-shadow: 0 1px 0 rgba(0,0,0,0.05);
            ">
                {body.replace('\n','<br>')}
                <div style="font-size:10px; opacity:0.6; margin-top:6px;">
                    {ts}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
