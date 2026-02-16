# pages/30_canal_coach_space.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone

import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns
from everskills.services.journal_gsheet import build_entry, journal_create, journal_list_coach
from everskills.services.mail_send_once import send_once

# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Canal Coach — EVERSKILLS", layout="wide")

# --- ROLE GUARD (anti accès direct URL)
require_role({"coach", "super_admin"})

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.stop()

coach_email = (user.get("email") or "").strip().lower()
if not coach_email or "@" not in coach_email:
    st.error("Email coach introuvable (session).")
    st.stop()

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
CANAL_PROMPT = "Canal Coach"
CANAL_PROMPT_KEY = CANAL_PROMPT.lower().strip()


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _esc(s: str) -> str:
    s = s or ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _fmt_ts(x: Any) -> str:
    # created_at is expected as epoch seconds int
    try:
        if isinstance(x, str) and x.strip().isdigit():
            x = int(x.strip())
        if isinstance(x, (int, float)) and x > 0:
            dt = datetime.fromtimestamp(int(x), tz=timezone.utc).astimezone()
            return dt.strftime("%d/%m %H:%M")
    except Exception:
        pass
    return str(x or "").strip()


def _thread_key_for_learner(learner_email: str) -> str:
    # We force a single shared thread per learner in Canal Coach
    return f"{_norm_email(learner_email)}::{CANAL_PROMPT_KEY}"


def _filter_items_for_thread(items: List[Dict[str, Any]], thread_key: str, learner_email: str) -> List[Dict[str, Any]]:
    le = _norm_email(learner_email)
    out: List[Dict[str, Any]] = []

    for it in items:
        if not isinstance(it, dict):
            continue

        tk = str(it.get("thread_key") or "").strip().lower()
        author = _norm_email(str(it.get("author_email") or ""))
        tags = [str(t).strip().lower() for t in _as_list(it.get("tags") or [])]

        # Primary: our canonical thread_key
        if tk and tk == thread_key:
            out.append(it)
            continue

        # Fallback (older messages before thread key normalization):
        # keep "chat" messages between this learner and this coach
        if author in (le, coach_email) and ("chat" in tags or "canal" in tags):
            out.append(it)
            continue

    # Sort: oldest -> newest (conversation feel)
    def _sort_key(d: Dict[str, Any]) -> Tuple[int, str]:
        ca = d.get("created_at")
        try:
            ca_i = int(ca)
        except Exception:
            ca_i = 0
        return ca_i, str(d.get("id") or "")

    out = sorted(out, key=_sort_key)
    return out


def _bubble(body: str, ts: str, is_coach: bool) -> None:
    # WhatsApp-like bubbles
    align = "flex-end" if is_coach else "flex-start"
    bg = "#111827" if is_coach else "#F3F4F6"
    color = "white" if is_coach else "#111827"

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
st.caption("Conversation directe avec tes learners (style WhatsApp).")

# Load campaigns for this coach
campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]

my_camps = [
    c for c in campaigns
    if _norm_email(str(c.get("coach_email") or "")) == coach_email
    and _norm_email(str(c.get("learner_email") or ""))  # has learner
]

if not my_camps:
    st.info("Aucune campagne associée à ton email coach.")
    st.stop()

# Deduplicate learners (keep latest camp per learner if multiple)
by_learner: Dict[str, Dict[str, Any]] = {}
for c in my_camps:
    le = _norm_email(str(c.get("learner_email") or ""))
    if not le:
        continue
    # pick the most recently updated if possible
    prev = by_learner.get(le)
    if not prev:
        by_learner[le] = c
        continue
    a = str(c.get("updated_at") or c.get("created_at") or "")
    b = str(prev.get("updated_at") or prev.get("created_at") or "")
    if a > b:
        by_learner[le] = c

learners = sorted(list(by_learner.keys()))
labels = [f"{le} — {by_learner[le].get('id','')}" for le in learners]

sel = st.selectbox("Choisir un learner", options=list(range(len(learners))), format_func=lambda i: labels[i])
learner_email = learners[int(sel)]
camp = by_learner[learner_email]
camp_id = str(camp.get("id") or "").strip()

thread_key = _thread_key_for_learner(learner_email)

# Load messages shared with this coach
try:
    all_items = journal_list_coach(coach_email, limit=400)
except Exception as e:
    st.error(f"Erreur de lecture: {e}")
    all_items = []

items = _filter_items_for_thread(all_items, thread_key=thread_key, learner_email=learner_email)

st.divider()

# Conversation header (small)
st.markdown(
    f"**Learner :** `{learner_email}`  \n"
    f"**Campagne :** `{camp_id}`"
)

# Conversation history
if not items:
    st.info("Aucun message dans ce canal pour l’instant.")
else:
    for it in items:
        body = str(it.get("body") or "").strip()
        author = _norm_email(str(it.get("author_email") or ""))
        ts = _fmt_ts(it.get("created_at"))
        if body:
            _bubble(body=body, ts=ts, is_coach=(author == coach_email))

st.divider()

# -----------------------------------------------------------------------------
# Input coach (reply)
# -----------------------------------------------------------------------------
st.markdown("### Répondre")
message = st.text_area(
    " ",
    height=90,
    placeholder="Écrire un message au learner…",
    label_visibility="collapsed",
    key=f"coach_reply_{learner_email}",
)

c1, c2 = st.columns([1.0, 1.0])
with c1:
    send_email = st.toggle("Envoyer aussi par email", value=True, key=f"coach_reply_email_{learner_email}")
with c2:
    st.caption("Astuce : ce message va dans le fil + (option) email.")

if st.button("📨 Envoyer", use_container_width=True, key=f"coach_send_{learner_email}"):
    if not message.strip():
        st.warning("Message vide.")
    else:
        try:
            # Build entry as coach, but FORCE the learner thread_key so the conversation stays unified
            entry = build_entry(
                author_user_id=str(user.get("id") or user.get("user_id") or coach_email),
                author_email=coach_email,
                body=message.strip(),
                tags=["chat", "canal"],
                share_with_coach=True,  # must be True so it appears in journal_list_coach
                coach_email=coach_email,
                prompt=CANAL_PROMPT,
            )
            # IMPORTANT: unify thread_key with learner
            entry.thread_key = thread_key

            journal_create(entry)

            # Email (kept as-is, per your instruction)
            if send_email and camp_id:
                send_once(
                    event_key=f"CHAT_COACH_REPLY:{camp_id}:{entry.id}",
                    event_type="CHAT_COACH_REPLY",
                    request_id=camp_id,
                    to_email=_norm_email(learner_email),
                    subject=f"[EVERSKILLS] Message coach ({camp_id})",
                    text_body=message.strip(),
                    meta={"camp_id": camp_id, "learner_email": learner_email, "coach_email": coach_email},
                )

            st.rerun()
        except Exception as e:
            st.error(f"Erreur d’envoi: {e}")
