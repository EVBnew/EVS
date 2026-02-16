# pages/20_canal_chat.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timezone
import base64
import uuid
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
from everskills.services.mail_send_once import send_once

# -------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -------------------------------------------------------------------------
st.set_page_config(page_title="Canal Chat — EVERSKILLS", layout="wide")

# One page for BOTH roles (mobile-first)
require_role({"learner", "coach", "super_admin"})

# -------------------------------------------------------------------------
# Auth
# -------------------------------------------------------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.stop()

role = str((user or {}).get("role") or "").strip()
me_email = (user.get("email") or "").strip().lower()
if not me_email or "@" not in me_email:
    st.error("Email introuvable (session).")
    st.stop()

# -------------------------------------------------------------------------
# Constants / helpers
# -------------------------------------------------------------------------
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
    try:
        if isinstance(x, str) and x.strip().isdigit():
            x = int(x.strip())
        if isinstance(x, (int, float)) and x > 0:
            dt = datetime.fromtimestamp(int(x), tz=timezone.utc).astimezone()
            return dt.strftime("%d/%m %H:%M")
    except Exception:
        pass
    return str(x or "").strip()


def _thread_key_for_pair(learner_email: str) -> str:
    # Single thread per learner in Canal Chat
    return f"{_norm_email(learner_email)}::{CANAL_PROMPT_KEY}"


def _filter_items_for_thread(
    items: List[Dict[str, Any]],
    thread_key: str,
    learner_email: str,
    coach_email: str,
) -> List[Dict[str, Any]]:
    le = _norm_email(learner_email)
    ce = _norm_email(coach_email)
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

        # Fallback: old chat/canal messages between learner & coach
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


def _is_voice_note(body: str) -> bool:
    return body.strip().startswith("🎙️ Note vocale")


def _extract_drive_urls(body: str) -> Tuple[str, str]:
    """
    We store:
      🎙️ Note vocale
      Lien: <urlView>
      Download: <urlDownload>
    """
    url_view = ""
    url_dl = ""
    for line in (body or "").splitlines():
        l = line.strip()
        if l.lower().startswith("lien:"):
            url_view = l.split(":", 1)[1].strip()
        if l.lower().startswith("download:"):
            url_dl = l.split(":", 1)[1].strip()
    return url_view, url_dl


def _render_message(body: str, ts: str, is_me: bool) -> None:
    if _is_voice_note(body):
        url_view, url_dl = _extract_drive_urls(body)
        # bubble header
        header = "🎙️ Note vocale"
        _bubble(header, ts, is_me=is_me)

        # audio player (outside bubble, but right under it)
        # Prefer direct download URL for <audio> src
        src = url_dl or url_view
        if src:
            st.markdown(
                f"""
<div style="display:flex; justify-content:{'flex-end' if is_me else 'flex-start'}; margin-top:-4px; margin-bottom:10px;">
  <audio controls style="max-width:78%;">
    <source src="{_esc(src)}">
  </audio>
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            # fallback (no URL)
            pass
    else:
        _bubble(body, ts, is_me=is_me)


def _call_apps_script(action: str, payload: dict) -> dict:
    """
    Uses same secrets strategy as app.py.
    Expects secrets:
      - URL: GSHEET_WEBAPP_URL / APPS_SCRIPT_URL / GSHEET_API_URL / WEBHOOK_URL
      - SECRET: GSHEET_SHARED_SECRET / SHARED_SECRET / EVS_SECRET
    """
    url = (
        st.secrets.get("GSHEET_WEBAPP_URL")
        or st.secrets.get("APPS_SCRIPT_URL")
        or st.secrets.get("GSHEET_API_URL")
        or st.secrets.get("WEBHOOK_URL")
    )
    secret = (
        st.secrets.get("GSHEET_SHARED_SECRET")
        or st.secrets.get("SHARED_SECRET")
        or st.secrets.get("EVS_SECRET")
    )

    if not url or not secret:
        return {"ok": False, "error": "Missing secrets for Apps Script (URL or SECRET).", "data": None}

    body = {"secret": secret, "action": action, **payload}
    try:
        r = requests.post(str(url), json=body, timeout=45)
        j = r.json()
        return j if isinstance(j, dict) else {"ok": False, "error": "Non-JSON response", "data": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}


def _upload_voice_to_drive(audio_bytes: bytes, mime_type: str) -> Tuple[bool, str, str, str]:
    """
    Returns (ok, urlView, urlDownload, error)
    """
    filename = f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    ext = "webm"
    if "mpeg" in (mime_type or "") or "mp3" in (mime_type or ""):
        ext = "mp3"
    elif "wav" in (mime_type or ""):
        ext = "wav"
    elif "mp4" in (mime_type or "") or "m4a" in (mime_type or ""):
        ext = "m4a"
    filename = f"{filename}.{ext}"

    b64 = base64.b64encode(audio_bytes).decode("utf-8")
    res = _call_apps_script(
        "upload_voice_note",
        {"filename": filename, "mimeType": mime_type or "audio/webm", "base64Data": b64},
    )
    if not res.get("ok"):
        return False, "", "", str(res.get("error") or "Upload failed")

    data = res.get("data") or {}
    url_view = str(data.get("urlView") or "")
    url_dl = str(data.get("urlDownload") or "")
    return True, url_view, url_dl, ""


# -------------------------------------------------------------------------
# UI
# -------------------------------------------------------------------------
st.title("💬 Canal Chat")
st.caption("Conversation directe (mobile-first). Messages + notes vocales (Drive).")

campaigns = load_campaigns() or []
campaigns = [c for c in campaigns if isinstance(c, dict)]

# -------------------------------------------------------------------------
# Determine (camp_id, learner_email, coach_email) based on role
# -------------------------------------------------------------------------
camp: Optional[Dict[str, Any]] = None
camp_id = ""
learner_email = ""
coach_email = ""

if role in ("coach", "admin", "super_admin") and role != "learner":
    # Coach view: pick a learner
    my_camps = [
        c for c in campaigns
        if _norm_email(str(c.get("coach_email") or "")) == _norm_email(me_email)
        and _norm_email(str(c.get("learner_email") or ""))
    ]
    if not my_camps:
        st.info("Aucune campagne associée à ton email coach.")
        st.stop()

    # Deduplicate learners (keep most recent camp)
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
    coach_email = _norm_email(me_email)

else:
    # Learner view: pick a campaign
    my_camps = [
        c for c in campaigns
        if _norm_email(str(c.get("learner_email") or "")) == _norm_email(me_email)
        and str(c.get("id") or "").strip()
    ]
    if not my_camps:
        st.info("Aucune campagne. (Le canal s’active une fois une campagne créée.)")
        st.stop()

    labels = [
        f"{c.get('id','')} — {str(c.get('status') or '')} — {(c.get('objective') or '')[:50]}"
        for c in my_camps
    ]
    sel = st.selectbox("Choisir une campagne", options=list(range(len(my_camps))), format_func=lambda i: labels[i])

    camp = my_camps[int(sel)]
    camp_id = str(camp.get("id") or "").strip()
    learner_email = _norm_email(me_email)
    coach_email = _norm_email(str(camp.get("coach_email") or st.session_state.get("evs_coach_email") or ""))

    if not coach_email or "@" not in coach_email:
        st.warning("Email coach non trouvé sur la campagne. Le canal restera en lecture learner uniquement.")

# Thread key is based on learner
thread_key = _thread_key_for_pair(learner_email)

st.divider()
st.markdown(f"**Campagne :** `{camp_id}`  \n**Learner :** `{learner_email}`  \n**Coach :** `{coach_email or '-'}`")

# -------------------------------------------------------------------------
# Load messages (merge learner + coach views so both sides see full history)
# -------------------------------------------------------------------------
merged: Dict[str, Dict[str, Any]] = {}

# learner feed
try:
    li = journal_list_learner(learner_email, limit=300)
except Exception as e:
    st.error(f"Erreur de lecture (learner): {e}")
    li = []

for it in li or []:
    if isinstance(it, dict):
        iid = str(it.get("id") or "")
        if iid:
            merged[iid] = it

# coach feed (needed to see coach replies + shared posts)
ci: List[Dict[str, Any]] = []
if coach_email and "@" in coach_email:
    try:
        ci = journal_list_coach(coach_email, limit=500)
    except Exception as e:
        st.error(f"Erreur de lecture (coach feed): {e}")
        ci = []

    for it in ci or []:
        if isinstance(it, dict):
            iid = str(it.get("id") or "")
            if iid and iid not in merged:
                merged[iid] = it

all_items = list(merged.values())
items = _filter_items_for_thread(all_items, thread_key=thread_key, learner_email=learner_email, coach_email=coach_email or "")

if not items:
    st.info("Aucun message dans ce canal pour l’instant.")
else:
    for it in items:
        body = str(it.get("body") or "").strip()
        author = _norm_email(str(it.get("author_email") or ""))
        ts = _fmt_ts(it.get("created_at"))
        if not body:
            continue
        is_me = (author == _norm_email(me_email))
        _render_message(body=body, ts=ts, is_me=is_me)

st.divider()

# -------------------------------------------------------------------------
# Composer
# -------------------------------------------------------------------------
is_coach = role in ("coach", "admin", "super_admin") and _norm_email(me_email) == _norm_email(coach_email)
is_learner = _norm_email(me_email) == _norm_email(learner_email)

st.markdown("### ✍️ Écrire")

# Text message
mood = None
if is_learner:
    mood = st.selectbox("Énergie du jour", options=MOODS, index=2, key=f"canal_mood_{camp_id}")

text_msg = st.text_area(
    " ",
    height=90,
    placeholder="Écrire un message…",
    label_visibility="collapsed",
    key=f"msg_{camp_id}_{role}",
)

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    share_toggle_label = "Partager au coach" if is_learner else "Partager au learner"
    share_default = True
    share_to_other = st.toggle(share_toggle_label, value=share_default, key=f"share_{camp_id}_{role}")
with c2:
    # Email allowed for TEXT only (as requested)
    send_email_text = st.toggle("Envoyer aussi par email", value=True, key=f"email_{camp_id}_{role}")
with c3:
    st.caption("Texte → fil + (option) email")

# Voice note (no email option)
st.markdown("### 🎙️ Note vocale (Drive)")
audio_file = st.file_uploader(
    " ",
    type=["webm", "mp3", "wav", "m4a", "mp4", "ogg"],
    accept_multiple_files=False,
    label_visibility="collapsed",
    key=f"audio_{camp_id}_{role}",
)
audio_share = st.toggle("Partager dans le fil", value=True, key=f"audio_share_{camp_id}_{role}")
st.caption("Audio → upload Drive → bulle avec player. (Pas d’email pour l’audio)")

b1, b2 = st.columns([1, 1])
with b1:
    send_text_btn = st.button("📨 Envoyer texte", use_container_width=True, key=f"send_text_{camp_id}_{role}")
with b2:
    send_audio_btn = st.button("🎙️ Envoyer audio", use_container_width=True, key=f"send_audio_{camp_id}_{role}")

# -------------------------------------------------------------------------
# Send TEXT
# -------------------------------------------------------------------------
if send_text_btn:
    txt = (text_msg or "").strip()
    if not txt:
        st.warning("Message vide.")
    else:
        # Determine recipient and validation
        if is_learner:
            if share_to_other and (not coach_email or "@" not in coach_email):
                st.error("Coach email manquant sur la campagne. Impossible de partager.")
                st.stop()
            author_email = learner_email
            other_email = coach_email
            event_type = "CHAT_LEARNER_MSG"
            subject = f"[EVERSKILLS] Message learner ({camp_id})"
        else:
            # coach/admin
            if share_to_other and (not learner_email or "@" not in learner_email):
                st.error("Learner email manquant. Impossible de partager.")
                st.stop()
            author_email = coach_email or me_email
            other_email = learner_email
            event_type = "CHAT_COACH_REPLY"
            subject = f"[EVERSKILLS] Message coach ({camp_id})"

        body = txt
        if is_learner and mood:
            body = f"{mood}\n\n{txt}"

        try:
            entry = build_entry(
                author_user_id=str(user.get("id") or user.get("user_id") or author_email),
                author_email=_norm_email(author_email),
                body=body,
                tags=["chat", "canal"],
                share_with_coach=bool(share_to_other) if is_learner else True,  # coach feed needs it
                coach_email=_norm_email(coach_email) if (coach_email and "@" in coach_email) else None,
                prompt=CANAL_PROMPT,
            )
            # Force thread_key per learner
            entry.thread_key = thread_key
            journal_create(entry)

            # Optional email for TEXT
            if share_to_other and send_email_text and camp_id:
                to_email = _norm_email(other_email)
                if to_email and "@" in to_email:
                    send_once(
                        event_key=f"{event_type}:{camp_id}:{entry.id}",
                        event_type=event_type,
                        request_id=camp_id,
                        to_email=to_email,
                        subject=subject,
                        text_body=body,
                        meta={"camp_id": camp_id, "learner_email": learner_email, "coach_email": coach_email},
                    )

            st.rerun()
        except Exception as e:
            st.error(f"Erreur d’envoi: {e}")

# -------------------------------------------------------------------------
# Send AUDIO (Drive upload -> journal entry with URLs)
# -------------------------------------------------------------------------
if send_audio_btn:
    if not audio_file:
        st.warning("Aucun fichier audio sélectionné.")
    elif not audio_share:
        st.info("Audio non partagé (toggle OFF).")
    else:
        # Validate counterpart exists for thread context
        if is_learner and (not coach_email or "@" not in coach_email):
            st.error("Coach email manquant sur la campagne. Impossible de partager l’audio.")
            st.stop()
        if is_coach and (not learner_email or "@" not in learner_email):
            st.error("Learner email manquant. Impossible de partager l’audio.")
            st.stop()

        try:
            audio_bytes = audio_file.getvalue()
            mime = getattr(audio_file, "type", None) or "audio/webm"

            ok_up, url_view, url_dl, err = _upload_voice_to_drive(audio_bytes, mime)
            if not ok_up:
                st.error(f"Upload Drive KO: {err}")
                st.stop()

            # Create a journal entry containing the URLs
            body = "🎙️ Note vocale\n"
            body += f"Lien: {url_view}\n"
            body += f"Download: {url_dl}\n"

            author_email = coach_email if is_coach else learner_email

            entry = build_entry(
                author_user_id=str(user.get("id") or user.get("user_id") or author_email),
                author_email=_norm_email(author_email),
                body=body.strip(),
                tags=["chat", "canal", "voice"],
                share_with_coach=True,  # required so coach feed sees it
                coach_email=_norm_email(coach_email) if (coach_email and "@" in coach_email) else None,
                prompt=CANAL_PROMPT,
            )
            entry.thread_key = thread_key
            journal_create(entry)

            # NO EMAIL for audio (as requested)

            st.success("Note vocale envoyée ✅")
            st.rerun()
        except Exception as e:
            st.error(f"Erreur audio: {e}")
