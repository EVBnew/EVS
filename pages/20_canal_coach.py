# pages/20_canal_coach.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone

import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns
from everskills.services.journal_gsheet import build_entry, journal_create, journal_list_learner, journal_list_coach
from everskills.services.mail_send_once import send_once

# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Canal Coach — EVERSKILLS", layout="wide")

# --- ROLE GUARD (anti accès direct URL)
require_role({"learner", "super_admin"})

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.stop()

learner_email = (user.get("email") or "").strip().lower()
if not learner_email or "@" not in learner_email:
    st.error("Email learner introuvable (session).")
    st.stop()

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
CANAL_PROMPT = "Canal Coach"
CANAL_PROMPT_KEY = CANAL_PROMPT.lower().strip()

MOODS = ["🟢 En confiance", "🔵 Flow", "🟡 Neutre", "🟠 Tendu", "🔴 Fatigué"]


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _esc(s: str) -> str:
    s = s or ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _fmt_ts(x: Any) -> str:
    try:
        if isinstance(x, str) and x.strip().isdigit():
            x = int(x.strip())
        if isinstance(x, (int, float)) and x > 0:
            dt = datetime.fromtimestamp(int(x), tz=timezone.utc).astimezone()
            return dt.strftime("%d/%m %H:%M")
    except Exception:
        pass
    return str(x or "").strip()


def _thread_key_for_learner(email: str) -> str:
    return f"{_norm_email(email)}::{CANAL_PROMPT_KEY}"


def _filter_items_for_thread(
    items: List[Dict[str, Any]],
    thread_key: str,
    learner_email_: str,
    coach_email_: str,
) -> List[Dict[str, Any]]:
    le = _norm_email(learner_email_)
    ce = _norm_email(coach_email_)
    out: List[Dict[str, Any]] = []

    for it in items:
        if not isinstance(it, dict):
            continue

        tk = str(it.get("thread_key") or "").strip().lower()
        author = _norm_email(str(it.get("author_email") or ""))
        tags = [str(t).strip().lower() for t in _as_list(it.get("tags") or [])]

        # Primary: canonical thread_key
        if tk and tk == thread_key:
            out.append(it)
            continue

        # Fallback: old "chat/canal" messages between learner and coach
        if author in (le, ce) and ("chat" in tags or "canal" in tags):
            out.append(it)
            continue

    def _sort_key(d: Dict[str, Any]) -> Tuple[int, str]:
        ca = d.get("created_at")
        try:
            ca_i = int(ca)
        except Exception:
            ca_i = 0
        return ca_i, str(d.get("id") or "")

    return sorted(out, key=_sort_key)


def _bubble(body: str, ts: str, is_me: bool) -> None:
    # WhatsApp-like bubbles
    align = "flex-end" if is_me else "flex-start"
    bg = "#111827" if is_me else "#F3F4F6"
    color = "white" if is_me else "#111827"

    safe_body = _esc(body).replace("\n", "<br>")
    safe_ts = _esc(ts)

    st.markdown(
        f"""
<div style="display:flex; justify-content:{align}; margin:8px 0;">
  <div style="
      background:{bg};
      color:{color};
      padding:10px 14px;
      border-radius:18px;
      max-width:78%;
      font-size:14px;
      line-height:1.35;
      box-shadow: 0 1px 2px rgba(0,0,0,0.06);
  ">
    <div>{safe_body}</div>
    <div style="font-size:11px; opacity:0.65; margin-top:6px; text-align:right;">
      {safe_ts}
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
st.title("💬 Canal Coach")
st.caption("Conversation directe avec ton coach (style WhatsApp).")

# -----------------------------------------------------------------------------
# Select campaign (to find coach_email)
# -----------------------------------------------------------------------------
campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]

my_camps = [
    c
    for c in campaigns
    if _norm_email(str(c.get("learner_email") or "")) == learner_email
    and str(c.get("id") or "").strip()
]

if not my_camps:
    st.info("Aucune campagne. (Le canal s’active une fois une campagne créée.)")
    st.stop()

labels = [f"{c.get('id','')} — {str(c.get('status') or '')} — {(c.get('objective') or '')[:50]}" for c in my_camps]
sel = st.selectbox("Choisir une campagne", options=list(range(len(my_camps))), format_func=lambda i: labels[i])

camp = my_camps[int(sel)]
camp_id = str(camp.get("id") or "").strip()
coach_email = _norm_email(str(camp.get("coach_email") or st.session_state.get("evs_coach_email") or ""))
if not coach_email or "@" not in coach_email:
    st.warning("Email coach non trouvé sur la campagne. (Le canal restera en lecture learner uniquement.)")

thread_key = _thread_key_for_learner(learner_email)

# -----------------------------------------------------------------------------
# Load messages (MERGE learner + coach feed)
# -----------------------------------------------------------------------------
merged: Dict[str, Dict[str, Any]] = {}

# 1) learner feed (always available)
try:
    learner_items = journal_list_learner(learner_email, limit=250)
except Exception as e:
    st.error(f"Erreur de lecture (learner): {e}")
    learner_items = []

for it in learner_items:
    if isinstance(it, dict):
        iid = str(it.get("id") or "")
        if iid:
            merged[iid] = it

# 2) coach feed (to see coach replies + shared learner posts)
coach_items: List[Dict[str, Any]] = []
if coach_email and "@" in coach_email:
    try:
        coach_items = journal_list_coach(coach_email, limit=400)
    except Exception as e:
        st.error(f"Erreur de lecture (coach feed): {e}")
        coach_items = []

    for it in coach_items:
        if isinstance(it, dict):
            iid = str(it.get("id") or "")
            if iid and iid not in merged:
                merged[iid] = it

all_items = list(merged.values())

# Filter to this conversation thread
items = _filter_items_for_thread(
    all_items,
    thread_key=thread_key,
    learner_email_=learner_email,
    coach_email_=coach_email or "",
)

st.divider()
st.markdown(f"**Campagne :** `{camp_id}`  \n**Coach :** `{coach_email or '-'}`")

if not items:
    st.info("Aucun message dans ce canal pour l’instant.")
else:
    for it in items:
        body = str(it.get("body") or "").strip()
        author = _norm_email(str(it.get("author_email") or ""))
        ts = _fmt_ts(it.get("created_at"))
        if body:
            _bubble(body=body, ts=ts, is_me=(author == learner_email))

st.divider()

# -----------------------------------------------------------------------------
# Input learner (send message)
# -----------------------------------------------------------------------------
st.markdown("### Écrire au coach")

mood = st.selectbox(
    "Énergie du jour",
    options=MOODS,
    index=2,
    key=f"canal_mood_{camp_id}",
)

message = st.text_area(
    " ",
    height=90,
    placeholder="Écrire un message…",
    label_visibility="collapsed",
    key=f"learner_msg_{camp_id}",
)

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    send_to_coach = st.toggle("Partager au coach", value=True, key=f"send_to_coach_{camp_id}")
with c2:
    send_email = st.toggle("Envoyer aussi par email", value=True, key=f"send_email_{camp_id}")
with c3:
    st.caption("Le message est ajouté au fil + (option) email.")

if st.button("📨 Envoyer", use_container_width=True, key=f"send_btn_{camp_id}"):
    txt = message.strip()
    if not txt:
        st.warning("Message vide.")
    elif send_to_coach and (not coach_email or "@" not in coach_email):
        st.error("Coach email manquant sur la campagne. Impossible de partager au coach.")
    else:
        body = f"{mood}\n\n{txt}"

        try:
            entry = build_entry(
                author_user_id=str(user.get("id") or user.get("user_id") or learner_email),
                author_email=learner_email,
                body=body,
                tags=["chat", "canal"],
                share_with_coach=bool(send_to_coach),
                coach_email=coach_email if send_to_coach else None,
                prompt=CANAL_PROMPT,
            )
            # Force unified thread_key
            entry.thread_key = thread_key

            journal_create(entry)

            # Email coach (kept, as requested)
            if send_to_coach and send_email and camp_id:
                send_once(
                    event_key=f"CHAT_LEARNER_MSG:{camp_id}:{entry.id}",
                    event_type="CHAT_LEARNER_MSG",
                    request_id=camp_id,
                    to_email=coach_email,
                    subject=f"[EVERSKILLS] Message learner ({camp_id})",
                    text_body=body,
                    meta={"camp_id": camp_id, "learner_email": learner_email, "coach_email": coach_email},
                )

            st.rerun()
        except Exception as e:
            st.error(f"Erreur d’envoi: {e}")
