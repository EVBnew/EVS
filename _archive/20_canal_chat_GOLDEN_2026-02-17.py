# pages/20_canal_chat.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone
import base64
import json
import requests

import streamlit as st

from everskills.services.access import require_login
from everskills.services.guard import require_role
from everskills.services.storage import load_campaigns
from everskills.services.journal_gsheet import build_entry, journal_create

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


def _apps_script_url_and_secret() -> Tuple[str, str]:
    # compatible avec tes secrets actuels
    url = (
        st.secrets.get("GSHEET_USERS_WEBAPP_URL")
        or st.secrets.get("GSHEET_WEBAPP_URL")
        or st.secrets.get("APPS_SCRIPT_URL")
        or st.secrets.get("GSHEET_API_URL")
        or st.secrets.get("WEBHOOK_URL")
        or ""
    )
    secret = (
        st.secrets.get("GSHEET_USERS_SHARED_SECRET")
        or st.secrets.get("GSHEET_SHARED_SECRET")
        or st.secrets.get("SHARED_SECRET")
        or st.secrets.get("EVS_SECRET")
        or ""
    )
    return str(url).strip(), str(secret).strip()


def _post_webhook(payload: Dict[str, Any], timeout_s: int = 45) -> Dict[str, Any]:
    url, _ = _apps_script_url_and_secret()
    if not url:
        return {"ok": False, "error": "Missing Apps Script URL"}
    try:
        r = requests.post(url, json=payload, timeout=timeout_s)
        try:
            j = r.json()
        except Exception:
            snippet = (r.text or "")[:400]
            return {
                "ok": False,
                "error": "Non-JSON response from webhook",
                "status": r.status_code,
                "snippet": snippet,
            }
        return j if isinstance(j, dict) else {"ok": False, "error": "Non-dict JSON response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _journal_list_for_me(learner_email: str, coach_email: str) -> List[Dict[str, Any]]:
    """
    Récupère les items visibles pour l'utilisateur courant.
    - Coach: journal_list_coach(coach_email=coach)
    - Learner: merge journal_list_learner(author_email=learner) + journal_list_coach(coach_email=coach)
      (permet le flux coach->learner)
    """
    url, secret = _apps_script_url_and_secret()
    if not url or not secret:
        return []

    # Coach view
    if me_role == "coach" and coach_email and "@" in coach_email:
        payload = {"secret": secret, "action": "journal_list_coach", "coach_email": coach_email, "limit": 300}
        j = _post_webhook(payload)
        return list(j.get("items") or []) if j.get("ok") else []

    # Learner view = merge
    items: List[Dict[str, Any]] = []

    p1 = {"secret": secret, "action": "journal_list_learner", "author_email": learner_email, "limit": 200}
    j1 = _post_webhook(p1)
    if j1.get("ok"):
        items.extend(list(j1.get("items") or []))

    if coach_email and "@" in coach_email:
        p2 = {"secret": secret, "action": "journal_list_coach", "coach_email": coach_email, "limit": 300}
        j2 = _post_webhook(p2)
        if j2.get("ok"):
            items.extend(list(j2.get("items") or []))

    return items


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

        if tk and tk == thread_key:
            out.append(it)
            continue

        # fallback ancien format
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

    # ✅ ordre: plus ancien -> plus récent (chat standard)
    return sorted(out, key=_sort_key, reverse=True)


def _parse_canonical_body(body: str) -> Dict[str, Any]:
    """
    Canon:
      {type, mood, text, audio:{url,url_alt,mime,file_id}}
    Retro-compat:
      - "[VOICE]: <url>"
      - "AUDIO_URL: <url>"
    """
    body = (body or "").strip()
    out: Dict[str, Any] = {"type": "text", "mood": "", "text": "", "audio": {}}

    if not body:
        return out

    if body.startswith("EVSMSG:"):
        raw = body[len("EVSMSG:") :].strip()
        try:
            j = json.loads(raw)
            if isinstance(j, dict):
                out["type"] = str(j.get("type") or "text")
                out["mood"] = str(j.get("mood") or "")
                out["text"] = str(j.get("text") or "")
                audio = j.get("audio") if isinstance(j.get("audio"), dict) else {}
                out["audio"] = {
                    "url": str(audio.get("url") or "").strip(),
                    "url_alt": str(audio.get("url_alt") or "").strip(),
                    "mime": str(audio.get("mime") or "").strip(),
                    "file_id": str(audio.get("file_id") or "").strip(),
                }
                return out
        except Exception:
            out["text"] = body
            return out

    # rétro-compat
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    mood = lines[0] if lines and lines[0] in MOODS else ""
    if mood:
        lines = lines[1:]

    joined = "\n".join(lines).strip()

    url = ""
    if "AUDIO_URL:" in joined:
        parts = joined.split("AUDIO_URL:", 1)
        out["text"] = parts[0].strip()
        url = parts[1].strip()
    elif "[VOICE]:" in joined:
        parts = joined.split("[VOICE]:", 1)
        out["text"] = parts[0].strip()
        url = parts[1].strip()
    else:
        out["text"] = joined

    out["mood"] = mood
    if url:
        out["type"] = "voice"
        out["audio"] = {"url": url, "url_alt": "", "mime": "", "file_id": ""}

    return out


def _bubble_text(text: str, mood: str, ts: str, is_me: bool) -> None:
    align = "flex-end" if is_me else "flex-start"
    bg = "#111827" if is_me else "#F3F4F6"
    color = "white" if is_me else "#111827"

    safe_ts = _esc(ts)
    safe_mood = _esc(mood) if mood else ""
    safe_text = _esc(text).replace("\n", "<br>") if text else ""

    mood_html = f'<div style="font-weight:600; margin-bottom:6px;">{safe_mood}</div>' if mood else ""
    inner = f"{mood_html}<div>{safe_text}</div>"

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


@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_audio_bytes(url: str) -> Tuple[bytes, str]:
    u = (url or "").strip()
    if not u:
        return b"", ""
    r = requests.get(u, allow_redirects=True, timeout=25)
    ct = (r.headers.get("Content-Type") or "").lower()

    # Drive renvoie parfois du HTML => KO
    if "text/html" in ct or (r.content and r.content[:15].lower().startswith(b"<!doctype html")):
        return b"", ct

    return r.content or b"", ct


def _bubble_voice(audio_url: str, audio_url_alt: str, mime: str, ts: str, is_me: bool) -> None:
    # ✅ pas de vignette / pas d’humeur sur les vocaux
    align = "flex-end" if is_me else "flex-start"
    bg = "#111827" if is_me else "#F3F4F6"
    color = "white" if is_me else "#111827"
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
    <div style="font-weight:600; margin-bottom:6px;">🎙️ Note vocale</div>
    <div style="font-size:11px; opacity:0.65; margin-top:6px; text-align:right;">
      {safe_ts}
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    src = (audio_url or "").strip() or (audio_url_alt or "").strip()
    if not src:
        st.error("Audio introuvable (url vide).")
        return

    data, ct = _fetch_audio_bytes(src)
    if data:
        try:
            st.audio(data, format=(mime or ct or None))
        except Exception:
            st.audio(data)
    else:
        st.warning("Audio non lisible en live (Drive). Utilise le fallback ci-dessous.")

    if audio_url_alt:
        st.link_button("Ouvrir le lien audio (fallback)", audio_url_alt)


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
    return _post_webhook(payload, timeout_s=90)


def _build_structured_text(ok_txt: str, ko_txt: str, learn_txt: str) -> str:
    ok_txt = (ok_txt or "").strip()
    ko_txt = (ko_txt or "").strip()
    learn_txt = (learn_txt or "").strip()

    parts: List[str] = []
    if ok_txt:
        parts.append("✅ Ce qui a fonctionné\n" + ok_txt)
    if ko_txt:
        parts.append("❌ Ce qui n’a pas marché\n" + ko_txt)
    if learn_txt:
        parts.append("💡 Mes enseignements\n" + learn_txt)

    return "\n\n".join(parts).strip()


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------
st.title("💬 Canal Chat")
st.caption("Conversation directe (bulles) + note vocale (lecture live).")

st.markdown(
    """

<style>

/* Espace en bas pour ne pas masquer les derniers messages */
.main .block-container{
  padding-bottom: 360px !important;
}

/* Composer FIXE en bas (vrai chat) */
.evs-composer{
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: 16px;
  z-index: 9999;
  width: min(980px, calc(100vw - 64px));
  background: rgba(255,255,255,0.96);
  backdrop-filter: blur(6px);
  border: 1px solid rgba(0,0,0,0.10);
  border-radius: 14px;
  padding: 12px 12px 6px 12px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}

/* Dark mode */
@media (prefers-color-scheme: dark){
  .evs-composer{
    background: rgba(15,23,42,0.92);
    border: 1px solid rgba(255,255,255,0.10);
  }
}

</style>
""",
    unsafe_allow_html=True,
)


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
        st.warning("Email coach non trouvé sur la campagne. (Partage canal indisponible.)")

thread_key = _thread_key_for_learner(learner_email)

# ---------------------------------------------------------------------
# Composer (sticky, visible tout le temps)
# ---------------------------------------------------------------------
st.markdown('<div class="evs-composer">', unsafe_allow_html=True)

mood = st.selectbox(
    "Énergie du jour",
    options=MOODS,
    index=2,
    key=f"canal_mood_{camp_id}_{me_role}",
)

colA, colB, colC = st.columns(3)
with colA:
    ok_txt = st.text_area(
        "✅ Ce qui a fonctionné",
        height=110,
        key=f"canal_ok_{camp_id}_{me_role}",
        placeholder="Ex: j’ai gardé mon calme…",
    )
with colB:
    ko_txt = st.text_area(
        "❌ Ce qui n’a pas marché",
        height=110,
        key=f"canal_ko_{camp_id}_{me_role}",
        placeholder="Ex: j’ai perdu le fil…",
    )
with colC:
    learn_txt = st.text_area(
        "💡 Mes enseignements",
        height=110,
        key=f"canal_learn_{camp_id}_{me_role}",
        placeholder="Ex: je dois préparer…",
    )

audio = st.audio_input("🎙️ Note vocale (enregistre puis valide)")

c1, c2 = st.columns([1, 1])
with c1:
    share_other_side = st.toggle(
        "Partager dans le canal",
        value=True,
        key=f"share_in_canal_{camp_id}_{me_role}",
        help="Si OFF : la note reste privée.",
    )
with c2:
    st.caption("Aucun email envoyé.")

send = st.button("📨 Envoyer", use_container_width=True, key=f"send_btn_{camp_id}_{me_role}")

st.markdown("</div>", unsafe_allow_html=True)

if send:
    txt_struct = _build_structured_text(ok_txt, ko_txt, learn_txt)
    has_audio = audio is not None

    if not txt_struct and not has_audio:
        st.warning("Message vide.")
        st.stop()

    if share_other_side and (not coach_email or "@" not in coach_email):
        st.error("Coach email manquant sur la campagne. Impossible de partager.")
        st.stop()

    try:
        audio_payload: Dict[str, Any] = {}
        if has_audio:
            raw = audio.getvalue()  # bytes
            if not raw:
                st.error("Audio vide (0 byte). Refaire l’enregistrement.")
                st.stop()

            mime = getattr(audio, "type", "") or "audio/webm"
            fname = getattr(audio, "name", "") or f"voice_{camp_id}_{int(datetime.now().timestamp())}.webm"
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

            audio_payload = {
                "url": str(up.get("audio_url") or "").strip(),
                "url_alt": str(up.get("audio_url_alt") or "").strip(),
                "mime": str(up.get("mime_type") or mime).strip(),
                "file_id": str(up.get("file_id") or "").strip(),
            }

            if not audio_payload["url"] and not audio_payload["url_alt"]:
                st.error("Upload audio KO: audio_url manquant.")
                st.stop()

        msg_obj = {
            "v": 1,
            "type": "voice" if has_audio else "text",
            "mood": mood or "",
            "text": txt_struct,
            "audio": audio_payload if has_audio else {},
        }
        body = "EVSMSG:" + json.dumps(msg_obj, ensure_ascii=False)

        entry = build_entry(
            author_user_id=str(user.get("id") or user.get("user_id") or me_email),
            author_email=me_email,
            body=body,
            tags=["chat", "canal", "audio"] if has_audio else ["chat", "canal"],
            share_with_coach=bool(share_other_side),
            coach_email=coach_email if share_other_side else None,
            prompt=CANAL_PROMPT,
        )
        entry.thread_key = thread_key

        journal_create(entry)
        st.rerun()

    except Exception as e:
        st.error(f"Erreur d’envoi: {e}")

# ---------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------
st.divider()

raw_items = _journal_list_for_me(learner_email=learner_email, coach_email=coach_email)
items = _filter_items_for_thread(
    raw_items,
    thread_key=thread_key,
    learner_email_=learner_email,
    coach_email_=coach_email or "",
)

if not items:
    st.info("Aucun message dans ce canal pour l’instant.")
else:
    for it in items:
        body = str(it.get("body") or "").strip()
        author = _norm_email(str(it.get("author_email") or ""))
        ts = _fmt_ts(it.get("created_at"))
        if not body:
            continue

        parsed = _parse_canonical_body(body)
        is_me = (author == me_email)

        if parsed.get("type") == "voice":
            audio_d = parsed.get("audio") if isinstance(parsed.get("audio"), dict) else {}
            _bubble_voice(
                audio_url=str(audio_d.get("url") or ""),
                audio_url_alt=str(audio_d.get("url_alt") or ""),
                mime=str(audio_d.get("mime") or ""),
                ts=ts,
                is_me=is_me,
            )
        else:
            _bubble_text(
                text=str(parsed.get("text") or body),
                mood=str(parsed.get("mood") or ""),
                ts=ts,
                is_me=is_me,
            )

