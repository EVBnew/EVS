# pages/20_canal_chat.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timezone
import base64
import requests

import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns
from everskills.services.journal_gsheet import (
    build_entry,
    journal_create,
    journal_list_learner,
    journal_list_coach,
)

# ---------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# ---------------------------------------------------------------------
st.set_page_config(page_title="Canal Chat — EVERSKILLS", layout="wide")

# Canal chat = 1 seule page pour learner + coach
require_role({"learner", "coach", "super_admin"})

# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.stop()

me_email = (user.get("email") or "").strip().lower()
me_role = (user.get("role") or "").strip().lower()

if not me_email or "@" not in me_email:
    st.error("Email introuvable (session).")
    st.stop()

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
CANAL_PROMPT = "Canal Chat"
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
    # created_at expected as epoch seconds (int) but keep fallback
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


def _extract_audio_url(body: str) -> Optional[str]:
    # convention: we store a single line like "AUDIO_URL: <url>"
    if not body:
        return None
    for line in body.splitlines():
        s = line.strip()
        if s.lower().startswith("audio_url:"):
            return s.split(":", 1)[1].strip() or None
    return None


def _bubble(body: str, ts: str, is_me: bool) -> None:
    align = "flex-end" if is_me else "flex-start"
    bg = "#111827" if is_me else "#F3F4F6"
    color = "white" if is_me else "#111827"

    audio_url = _extract_audio_url(body)
    safe_ts = _esc(ts)

    # If audio => render player
    if audio_url:
        safe_audio = _esc(audio_url)
        inner = f"""
<div style="margin-bottom:6px; font-weight:600;">🎙️ Note vocale</div>
<audio controls style="width: 260px; max-width: 100%;">
  <source src="{safe_audio}">
</audio>
"""
    else:
        safe_body = _esc(body).replace("\n", "<br>")
        inner = f"<div>{safe_body}</div>"

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
    {inner}
    <div style="font-size:11px; opacity:0.65; margin-top:6px; text-align:right;">
      {safe_ts}
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _apps_script_url_and_secret() -> Tuple[str, str]:
    url = (
        st.secrets.get("GSHEET_WEBAPP_URL")
        or st.secrets.get("APPS_SCRIPT_URL")
        or st.secrets.get("GSHEET_API_URL")
        or st.secrets.get("WEBHOOK_URL")
        or ""
    )
    secret = (
        st.secrets.get("GSHEET_SHARED_SECRET")
        or st.secrets.get("SHARED_SECRET")
        or st.secrets.get("EVS_SECRET")
        or ""
    )
    return str(url).strip(), str(secret).strip()


def _upload_voice_note(file_name: str, mime: str, b64: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    url, secret = _apps_script_url_and_secret()
    if not url or not secret:
        return {"ok": False, "error": "Missing Apps Script URL/SECRET"}

    payload = {
        "secret": secret,
        "action": "upload_voice_note",
        "file_name": file_name,
        "mime_type": mime,
        "data_b64": b64,
        "meta": meta or {},
    }
    try:
        r = requests.post(url, json=payload, timeout=45)
        j = r.json()
        return j if isinstance(j, dict) else {"ok": False, "error": "Non-JSON response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------
st.title("💬 Canal Chat")
st.caption("Conversation directe (bulles) + note vocale (sans Drive manuel).")

campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]

# ---------------------------------------------------------------------
# Resolve context: learner_email + coach_email + camp_id
# ---------------------------------------------------------------------
learner_email = ""
coach_email = ""
camp_id = ""

if me_role in ("coach", "super_admin"):
    my_camps = [
        c
        for c in campaigns
        if _norm_email(str(c.get("coach_email") or "")) == me_email
        and _norm_email(str(c.get("learner_email") or ""))
        and str(c.get("id") or "").strip()
    ]

    if not my_camps:
        st.info("Aucune campagne associée à ton email coach.")
        st.stop()

    # Deduplicate learners (keep latest camp per learner)
    by_learner: Dict[str, Dict[str, Any]] = {}
    for c in my_camps:
        le = _norm_email(str(c.get("learner_email") or ""))
        if not le:
            continue
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
    coach_email = me_email

else:
    my_camps = [
        c
        for c in campaigns
        if _norm_email(str(c.get("learner_email") or "")) == me_email
        and str(c.get("id") or "").strip()
    ]
    if not my_camps:
        st.info("Aucune campagne. (Le canal s’active une fois une campagne créée.)")
        st.stop()

    labels = [f"{c.get('id','')} — {str(c.get('status') or '')} — {(c.get('objective') or '')[:50]}" for c in my_camps]
    sel = st.selectbox("Choisir une campagne", options=list(range(len(my_camps))), format_func=lambda i: labels[i])

    camp = my_camps[int(sel)]
    camp_id = str(camp.get("id") or "").strip()

    learner_email = me_email
    coach_email = _norm_email(str(camp.get("coach_email") or st.session_state.get("evs_coach_email") or ""))
    if not coach_email or "@" not in coach_email:
        st.warning("Email coach non trouvé sur la campagne. (Le canal restera en lecture/écriture learner local.)")

thread_key = _thread_key_for_learner(learner_email)

st.divider()
st.markdown(
    f"**Campagne :** `{camp_id}`  \n"
    f"**Learner :** `{learner_email}`  \n"
    f"**Coach :** `{coach_email or '-'}`"
)

# ---------------------------------------------------------------------
# Load messages (merge learner + coach feed)
# ---------------------------------------------------------------------
merged: Dict[str, Dict[str, Any]] = {}

# Learner feed
try:
    learner_items = journal_list_learner(learner_email, limit=250)
except Exception as e:
    st.error(f"Erreur de lecture (learner feed): {e}")
    learner_items = []

for it in learner_items:
    if isinstance(it, dict):
        iid = str(it.get("id") or "")
        if iid:
            merged[iid] = it

# Coach feed (if coach email exists)
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

items = _filter_items_for_thread(
    list(merged.values()),
    thread_key=thread_key,
    learner_email_=learner_email,
    coach_email_=coach_email or "",
)

st.divider()

if not items:
    st.info("Aucun message dans ce canal pour l’instant.")
else:
    for it in items:
        body = str(it.get("body") or "").strip()
        author = _norm_email(str(it.get("author_email") or ""))
        ts = _fmt_ts(it.get("created_at"))
        if body:
            _bubble(body=body, ts=ts, is_me=(author == me_email))

st.divider()

# ---------------------------------------------------------------------
# Composer (text + voice) — NO EMAIL
# ---------------------------------------------------------------------
st.markdown("### ✍️ Écrire / 🎙️ Envoyer une note vocale")

is_learner = me_role in ("learner", "super_admin") and me_email == learner_email
is_coach = me_role in ("coach", "super_admin") and me_email == coach_email

# Mood (keep it, as requested)
mood = st.selectbox(
    "Énergie du jour",
    options=MOODS,
    index=2,
    key=f"canal_mood_{camp_id}_{me_role}",
)

# Text message
message = st.text_area(
    " ",
    height=90,
    placeholder="Écrire un message…",
    label_visibility="collapsed",
    key=f"canal_msg_{camp_id}_{me_role}",
)

# Voice note (direct in-app)
audio = st.audio_input("🎙️ Note vocale (enregistre puis valide)")

c1, c2 = st.columns([1, 1])
with c1:
    share_other_side = st.toggle(
        "Partager dans le canal",
        value=True,
        key=f"share_in_canal_{camp_id}_{me_role}",
        help="Si OFF : la note reste privée (rarement utile).",
    )
with c2:
    st.caption("Aucun email envoyé (comme demandé).")

if st.button("📨 Envoyer", use_container_width=True, key=f"send_btn_{camp_id}_{me_role}"):
    txt = (message or "").strip()
    has_audio = audio is not None

    if not txt and not has_audio:
        st.warning("Message vide.")
        st.stop()

    # Determine who is "coach" for share_with_coach routing
    # Storage rule: items appear to coach only if share_with_coach=True and coach_email is set
    if share_other_side and (not coach_email or "@" not in coach_email):
        st.error("Coach email manquant sur la campagne. Impossible de partager.")
        st.stop()

    try:
        # 1) If audio: upload via Apps Script (Drive backend invisible)
        audio_url = None
        if has_audio:
            raw = audio.getvalue()
            mime = getattr(audio, "type", "") or "audio/wav"
            fname = getattr(audio, "name", "") or f"voice_{camp_id}_{int(datetime.now().timestamp())}.wav"
            b64 = base64.b64encode(raw).decode("utf-8")

            up = _upload_voice_note(
                file_name=fname,
                mime=mime,
                b64=b64,
                meta={
                    "camp_id": camp_id,
                    "thread_key": thread_key,
                    "author_email": me_email,
                    "learner_email": learner_email,
                    "coach_email": coach_email,
                },
            )
            if not up.get("ok"):
                st.error(f"Upload audio KO: {up.get('error')}")
                st.stop()

            audio_url = str(up.get("audio_url") or "").strip()
            if not audio_url:
                st.error("Upload audio KO: audio_url manquant.")
                st.stop()

        # 2) Build body
        parts: List[str] = []
        if mood:
            parts.append(mood)

        if txt:
            parts.append(txt)

        if audio_url:
            parts.append(f"AUDIO_URL: {audio_url}")

        body = "\n\n".join(parts).strip()

        # 3) Persist in Journal (threaded)
        entry = build_entry(
            author_user_id=str(user.get("id") or user.get("user_id") or me_email),
            author_email=me_email,
            body=body,
            tags=["chat", "canal", "audio"] if audio_url else ["chat", "canal"],
            share_with_coach=bool(share_other_side),
            coach_email=coach_email if share_other_side else None,
            prompt=CANAL_PROMPT,
        )
        entry.thread_key = thread_key

        journal_create(entry)

        st.rerun()

    except Exception as e:
        st.error(f"Erreur d’envoi: {e}")
