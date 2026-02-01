# pages/10_coach_space.py
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from everskills.services.access import require_login, find_user
from everskills.services.mailer import send_email
from everskills.services.storage import (
    load_requests,
    load_campaigns,
    save_campaigns,
    update_request,
    now_iso,
)

st.set_page_config(page_title="Coach Space — EVERSKILLS", layout="wide")

# ----------------------------
# Auth
# ----------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

if user.get("role") not in ("coach", "admin", "super_admin"):
    st.warning("Accès réservé aux coachs / admins.")
    st.stop()

coach_email = (user.get("email") or "").strip().lower()
coach_first_name = str(user.get("first_name") or "").strip()

# ----------------------------
# Helpers
# ----------------------------
def _sort_key_req(req: Dict[str, Any]) -> str:
    return str(req.get("ts") or req.get("created_at") or "")

def _req_status(req: Dict[str, Any]) -> str:
    return (req.get("status") or "submitted").strip()

def _camp_status(camp: Dict[str, Any]) -> str:
    return (camp.get("status") or "").strip()

def _label_req(req: Dict[str, Any]) -> str:
    rid = str(req.get("id") or "").strip()
    email = (req.get("email") or "unknown").strip()
    obj = (req.get("objective") or "").strip()
    return f"{email} — {_req_status(req)} — {rid} — {obj[:60]}"

def _label_camp(c: Dict[str, Any]) -> str:
    cid = c.get("id", "camp")
    email = c.get("learner_email", "unknown")
    status = _camp_status(c)
    obj = c.get("objective", "")
    return f"{email} — {status} — {cid} — {obj[:60]}"

def _append_event(camp: Dict[str, Any], event_type: str, actor: str, payload: Optional[Dict[str, Any]] = None) -> None:
    events = camp.get("events")
    if not isinstance(events, list):
        events = []
    events.append({"ts": now_iso(), "actor": actor, "type": event_type, "payload": payload or {}})
    camp["events"] = events

def _find_campaign_by_request_id(campaigns: List[Dict[str, Any]], request_id: str) -> Optional[Dict[str, Any]]:
    for c in campaigns:
        if not isinstance(c, dict):
            continue
        if str(c.get("request_id") or "").strip() == request_id:
            return c
    return None

def _save_campaign_in_list(campaigns: List[Dict[str, Any]], camp: Dict[str, Any]) -> None:
    cid = str(camp.get("id") or "").strip()
    if not cid:
        raise ValueError("Campaign has no id")
    replaced = False
    for i, c in enumerate(campaigns):
        if isinstance(c, dict) and str(c.get("id") or "").strip() == cid:
            campaigns[i] = camp
            replaced = True
            break
    if not replaced:
        campaigns.append(camp)
    save_campaigns(campaigns)

ACTION_STATUSES = [
    ("not_started", "🔴 Pas fait"),
    ("partial", "🟡 Partiel"),
    ("done", "🟢 Fait"),
]
ACTION_LABEL = {k: v for k, v in ACTION_STATUSES}

def _compute_week_completion(week: Dict[str, Any]) -> Tuple[int, int, float]:
    actions = week.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    total = 0
    done = 0
    for a in actions:
        if not isinstance(a, dict):
            continue
        txt = str(a.get("text") or "").strip()
        if not txt:
            continue
        total += 1
        if str(a.get("status") or "").strip() == "done":
            done += 1
    pct = (done / total * 100.0) if total > 0 else 0.0
    return done, total, pct

def _compute_global_completion(camp: Dict[str, Any]) -> Tuple[int, int, float]:
    wp = camp.get("weekly_plan") or []
    if not isinstance(wp, list):
        wp = []
    done_total = 0
    total_total = 0
    for w in wp:
        if not isinstance(w, dict):
            continue
        d, t, _ = _compute_week_completion(w)
        done_total += d
        total_total += t
    pct = (done_total / total_total * 100.0) if total_total > 0 else 0.0
    return done_total, total_total, pct

def _ensure_weekly_plan(camp: Dict[str, Any]) -> Dict[str, Any]:
    try:
        weeks = int(camp.get("weeks") or 3)
    except Exception:
        weeks = 3

    wp = camp.get("weekly_plan")
    if not isinstance(wp, list):
        wp = []

    by_week: Dict[int, Dict[str, Any]] = {}
    for item in wp:
        if isinstance(item, dict):
            try:
                by_week[int(item.get("week") or 0)] = item
            except Exception:
                pass

    norm: List[Dict[str, Any]] = []
    for w in range(1, weeks + 1):
        existing = by_week.get(w, {})
        actions = existing.get("actions")
        if not isinstance(actions, list):
            actions = []

        norm_actions: List[Dict[str, Any]] = []
        for a in actions:
            if isinstance(a, dict):
                txt = str(a.get("text") or "").strip()
                stt = str(a.get("status") or "not_started").strip()
                if txt:
                    norm_actions.append({"text": txt, "status": stt})
            elif isinstance(a, str) and a.strip():
                norm_actions.append({"text": a.strip(), "status": "not_started"})

        norm.append(
            {
                "week": w,
                "objective_week": str(existing.get("objective_week") or "").strip(),
                "actions": norm_actions,
                "learner_comment": str(existing.get("learner_comment") or "").strip(),
                "coach_comment": str(existing.get("coach_comment") or "").strip(),
                "updated_at": str(existing.get("updated_at") or "").strip(),
            }
        )

    camp["weekly_plan"] = norm
    camp["kickoff_message"] = str(camp.get("kickoff_message") or "").strip()
    camp["closure_message"] = str(camp.get("closure_message") or "").strip()
    return camp

# ----------------------------
# program_text -> weekly_plan sync
# ----------------------------
def _hash_text(s: str) -> str:
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()

def _clean_md_line(line: str) -> str:
    s = (line or "").strip()
    s = re.sub(r"^\s*(?:[#>\-\*\u2022]+\s*)+", "", s)
    s = s.strip()
    s = re.sub(r"^\*{1,3}\s*(.*?)\s*\*{1,3}$", r"\1", s)
    s = re.sub(r"^_{1,3}\s*(.*?)\s*_{1,3}$", r"\1", s)
    return s.strip()

def _extract_week_sections(program_text: str) -> Dict[int, List[str]]:
    text = (program_text or "").strip()
    if not text:
        return {}
    lines = text.splitlines()
    header_re = re.compile(r"(?i)^\s*semaine\s*(\d{1,2})\s*[:\-\.\u2013\u2014]\s*(.*)\s*$")

    sections: Dict[int, List[str]] = {}
    current_week: int | None = None

    for raw in lines:
        line = _clean_md_line(raw)
        if not line:
            continue
        m = header_re.match(line)
        if m:
            wk = int(m.group(1))
            if 1 <= wk <= 52:
                current_week = wk
                sections.setdefault(wk, [])
                remainder = (m.group(2) or "").strip()
                if remainder:
                    sections[wk].append(remainder)
            else:
                current_week = None
            continue
        if current_week is not None:
            sections[current_week].append(line)
    return sections

def _pick_objective_and_actions(lines: List[str]) -> Tuple[str, List[str]]:
    clean = [_clean_md_line(ln) for ln in (lines or [])]
    clean = [ln for ln in clean if ln.strip()]
    if not clean:
        return "", []
    obj = ""
    actions: List[str] = []

    obj_re = re.compile(r"(?i)^\s*objectif(?:\s+de\s+la\s+semaine)?\s*:\s*(.*)$")
    action_line_re = re.compile(r"^\s*(?:[-•]\s+|\d+\.\s+|\d+\)\s+)(.+)$")

    for ln in clean[:15]:
        m = obj_re.match(ln)
        if m:
            cand = (m.group(1) or "").strip()
            if cand:
                obj = cand
                break
    if not obj:
        obj = clean[0].strip()

    in_actions_block = False
    for ln in clean:
        if re.match(r"(?i)^\s*actions?\b\s*:?\s*$", ln) or re.match(r"(?i)^\s*actions?\s+terrain\s*:?\s*$", ln):
            in_actions_block = True
            continue

        m = action_line_re.match(ln)
        if m:
            t = (m.group(1) or "").strip()
            if t:
                actions.append(t)
        elif in_actions_block:
            if len(ln) > 5 and not re.match(r"(?i)^(objectif|rappel|indicateur)\b", ln):
                actions.append(ln.strip())

        if len(actions) >= 3:
            break

    actions = [a for a in actions if a]
    return obj.strip(), actions[:3]

def _week_needs_fill(w: Dict[str, Any]) -> bool:
    obj = str(w.get("objective_week") or "").strip()
    actions = w.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    has_action = any(isinstance(a, dict) and str(a.get("text") or "").strip() for a in actions)
    return (not obj) or (not has_action)

def _sync_weekly_plan_from_program(camp: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    program_text = str(camp.get("program_text") or "").strip()
    if not program_text:
        return camp, False

    camp = _ensure_weekly_plan(camp)
    wp = camp.get("weekly_plan") or []
    if not isinstance(wp, list):
        wp = []

    prog_hash = _hash_text(program_text)
    already = str(camp.get("weekly_init_program_hash") or "").strip()
    needs_retry = any(isinstance(w, dict) and _week_needs_fill(w) for w in wp)

    if already == prog_hash and not needs_retry:
        return camp, False

    sections = _extract_week_sections(program_text)
    if not sections:
        if not needs_retry:
            camp["weekly_init_program_hash"] = prog_hash
            return camp, True
        return camp, False

    changed = False
    for item in wp:
        if not isinstance(item, dict):
            continue
        week_n = int(item.get("week") or 0) or 0
        if week_n <= 0:
            continue
        lines = sections.get(week_n)
        if not lines:
            continue

        obj, acts = _pick_objective_and_actions(lines)

        if not str(item.get("objective_week") or "").strip() and obj.strip():
            item["objective_week"] = obj.strip()
            changed = True

        current_actions = item.get("actions")
        if not isinstance(current_actions, list):
            current_actions = []
        has_any_action = any(isinstance(a, dict) and str(a.get("text") or "").strip() for a in current_actions)

        if (not has_any_action) and acts:
            item["actions"] = [{"text": a.strip(), "status": "not_started"} for a in acts if a.strip()]
            changed = True

    camp["weekly_plan"] = wp
    camp["weekly_init_program_hash"] = prog_hash
    return camp, changed

# ----------------------------
# OpenAI
# ----------------------------
def _get_openai_client():
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None
    api_key = (st.secrets.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

def _build_program_prompt(objective: str, context: str, weeks: int) -> str:
    return f"""
Tu es un coach RH. Tu dois produire un programme EVERSKILLS simple, concret et actionnable.

Objectif de progression : {objective}
Contexte : {context}
Durée : {weeks} semaines

Contraintes :
- Format court, lisible, en français.
- 1 objectif SMART.
- 3 axes maximum.
- Un rythme hebdomadaire.
- Pour chaque semaine :
  - 1 objectif de semaine
  - 2–3 actions terrain (très concrètes)
  - 1 rappel de connaissance
  - 1 indicateur
- Termine par : "Message à l’apprenant" (3 lignes, ton coach).

Réponds en texte clair (pas de JSON).
""".strip()

def _first_name_from_access(email: str) -> str:
    u = find_user(email or "")
    if not u:
        return ""
    return str(u.get("first_name") or "").strip()

def _kickoff_template(learner_first: str, weeks: int, coach_first: str) -> str:
    lf = learner_first or ""
    cf = coach_first or "Ton coach"
    hello = f"Bonjour {lf}," if lf else "Bonjour,"
    return (
        f"{hello}\n\n"
        "Merci pour ta demande qui est très claire. Bravo, c'est déjà un premier pas essentiel : "
        "exprimer son projet avec clarté.\n"
        f"J'ai pu préparer un programme de travail sur la durée souhaitée ({weeks} semaines).\n\n"
        "Je te propose de nous en parler lors du rendez-vous de démarrage.\n\n"
        "Voici quelques options de dates:\n"
        "- [Option 1]\n"
        "- [Option 2]\n"
        "- [Option 3]\n\n"
        "J'espère que l'une d'entre elles te conviendra.\n\n"
        "D'ici là je reste disponible pour toute question.\n\n"
        f"A bientôt.\n\n{cf}"
    )

def _closure_template(learner_first: str, objective: str, weeks: int, coach_first: str) -> str:
    lf = learner_first or ""
    cf = coach_first or "Ton coach"
    hello = f"Cher {lf}," if lf else "Bonjour,"
    return (
        f"{hello}\n\n"
        f"Ça a été un réel plaisir de t'accompagner dans ton objectif : {objective}.\n"
        f"Au cours de ces {weeks} semaines, tu as réalisé avec brio les activités proposées, "
        "en prenant en compte les retours que nous avons évoqués ensemble lors des points hebdomadaires.\n\n"
        "Et maintenant ?\n"
        "Une autre phase peut commencer : la réflexivité — être son propre coach avec un regard précis et bienveillant.\n\n"
        "Nous pouvons aussi rester en contact en nous écrivant de temps en temps — ça me ferait très plaisir de suivre ton évolution.\n"
        "Et si tu souhaites approfondir certains concepts dans ce format, je resterai disponible.\n\n"
        "Au plaisir de nous revoir et d'échanger.\n\n"
        f"{cf}"
    )

def _mail_subject(prefix: str, camp: Dict[str, Any]) -> str:
    obj = str(camp.get("objective") or "").strip()
    cid = str(camp.get("id") or "").strip()
    base = f"{prefix} — {obj[:60]}".strip()
    if cid:
        return f"{base} [{cid}]"
    return base

# ----------------------------
# UI
# ----------------------------
st.title("🧠 Coach Space")
st.caption("Demandes → campagnes → programme → suivi → clôture.")

requests_raw: List[Dict[str, Any]] = load_requests() or []
campaigns_raw: List[Dict[str, Any]] = load_campaigns() or []

requests_sorted = sorted([r for r in requests_raw if isinstance(r, dict)], key=_sort_key_req, reverse=True)
campaigns = [c for c in campaigns_raw if isinstance(c, dict)]

active_count = sum(1 for c in campaigns if _camp_status(c) == "active")
program_ready_count = sum(1 for c in campaigns if _camp_status(c) == "program_ready")
draft_count = sum(1 for c in campaigns if _camp_status(c) == "draft")
new_requests_count = sum(1 for r in requests_sorted if _req_status(r) == "submitted")

st.subheader("📊 Dashboard")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Active", active_count)
m2.metric("Program ready", program_ready_count)
m3.metric("Draft", draft_count)
m4.metric("New requests", new_requests_count)

st.divider()

col_left, col_mid, col_right = st.columns([1.15, 2.25, 1.2], gap="large")

st.session_state.setdefault("coach_view", "Demandes")
st.session_state.setdefault("selected_req_id", "")
st.session_state.setdefault("selected_camp_id", "")
st.session_state.setdefault("program_draft", "")
st.session_state.setdefault("_draft_cid", "")

with col_left:
    st.subheader("📌 Sélection")
    view = st.radio(
        "Vue",
        ["Demandes", "Campagnes"],
        horizontal=True,
        index=0 if st.session_state["coach_view"] == "Demandes" else 1,
    )
    st.session_state["coach_view"] = view

    if view == "Demandes":
        submitted = [r for r in requests_sorted if _req_status(r) == "submitted"]
        if not submitted:
            st.info("Aucune demande submitted.")
        else:
            options = [str(r.get("id") or "").strip() for r in submitted]
            labels = {str(r.get("id") or "").strip(): _label_req(r) for r in submitted}
            default = st.session_state.get("selected_req_id", "")
            idx = options.index(default) if default in options else 0
            rid = st.selectbox("Demande", options=options, index=idx, format_func=lambda x: labels.get(x, x))
            st.session_state["selected_req_id"] = rid
            st.session_state["selected_camp_id"] = ""
    else:
        if not campaigns:
            st.info("Aucune campagne.")
        else:
            options = [str(c.get("id") or "").strip() for c in campaigns if str(c.get("id") or "").strip()]
            labels = {str(c.get("id") or "").strip(): _label_camp(c) for c in campaigns}
            default = st.session_state.get("selected_camp_id", "")
            idx = options.index(default) if default in options else 0
            cid = st.selectbox("Campagne", options=options, index=idx, format_func=lambda x: labels.get(x, x))
            st.session_state["selected_camp_id"] = cid
            st.session_state["selected_req_id"] = ""

selected_req: Optional[Dict[str, Any]] = None
selected_camp: Optional[Dict[str, Any]] = None

if st.session_state["coach_view"] == "Demandes":
    rid = (st.session_state.get("selected_req_id") or "").strip()
    if rid:
        selected_req = next((r for r in requests_sorted if str(r.get("id") or "").strip() == rid), None)
        if selected_req:
            selected_camp = _find_campaign_by_request_id(campaigns, rid)
else:
    cid = (st.session_state.get("selected_camp_id") or "").strip()
    if cid:
        selected_camp = next((c for c in campaigns if str(c.get("id") or "").strip() == cid), None)

if selected_camp:
    selected_camp = _ensure_weekly_plan(selected_camp)

with col_mid:
    st.subheader("🧾 Programme & suivi")

    if selected_req:
        with st.container(border=True):
            st.markdown("#### Infos learner")
            st.write(f"**Learner :** {selected_req.get('email','')}")
            st.write(f"**Objectif :** {selected_req.get('objective','')}")
            st.write(f"**Contexte :** {selected_req.get('context','')}")
            st.write(f"**Semaines :** {selected_req.get('weeks', 3)}")
            st.write(f"**Statut request :** `{_req_status(selected_req)}`")

    if not selected_camp:
        st.info("Aucune campagne liée. ➜ Crée-la dans la colonne de droite.")
    else:
        existing_text = (selected_camp.get("program_text") or "").strip()
        cid = str(selected_camp.get("id") or "").strip()

        if st.session_state.get("_draft_cid") != cid:
            st.session_state["_draft_cid"] = cid
            st.session_state["program_draft"] = existing_text

        b1, b2, b3 = st.columns([1, 1, 1.4])
        with b1:
            do_gen = st.button("⚡ Générer (IA)", use_container_width=True)
        with b2:
            do_regen = st.button("🔁 Regénérer", use_container_width=True)
        with b3:
            do_load = st.button("↩️ Recharger depuis campagne", use_container_width=True)

        if do_load:
            st.session_state["program_draft"] = (selected_camp.get("program_text") or "").strip()
            st.success("Draft rechargé ✅")

        if do_gen or do_regen:
            client = _get_openai_client()
            model = (st.secrets.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
            if not client:
                st.error("OPENAI_API_KEY manquante (ou SDK openai absent).")
            else:
                objective = str(selected_camp.get("objective") or "").strip()
                context = str(selected_camp.get("context") or "").strip()
                try:
                    weeks = int(selected_camp.get("weeks") or 3)
                except Exception:
                    weeks = 3
                prompt = _build_program_prompt(objective, context, weeks)
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "Tu es un coach RH exigeant, pragmatique et bienveillant."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.4,
                        max_tokens=900,
                    )
                    text = (resp.choices[0].message.content or "").strip()
                    st.session_state["program_draft"] = text
                    st.success("Programme généré ✅")
                except Exception as e:
                    st.error(f"Erreur IA: {e}")

        program_text = st.text_area(
            "Programme (modifiable)",
            value=st.session_state.get("program_draft", ""),
            height=280,
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Enregistrer le programme", use_container_width=True):
                selected_camp["program_text"] = program_text
                selected_camp, changed = _sync_weekly_plan_from_program(selected_camp)
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "program_saved", actor="coach", payload={"weekly_synced": bool(changed)})
                _save_campaign_in_list(campaigns, selected_camp)
                st.session_state["program_draft"] = program_text
                st.success("OK ✅ (programme enregistré + plan hebdo synchronisé)")
                st.rerun()

        with c2:
            if st.button("📤 Publier (program_ready)", use_container_width=True):
                selected_camp["program_text"] = program_text
                selected_camp["status"] = "program_ready"
                selected_camp, _ = _sync_weekly_plan_from_program(selected_camp)
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "program_published", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)

                if selected_req:
                    update_request(str(selected_req.get("id")), {"status": "archived", "updated_at": now_iso()})

                # Mail learner
                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                subj = _mail_subject("Programme prêt", selected_camp)
                body = (
                    "Bonjour,\n\n"
                    "Ton coach a publié ton programme EVERSKILLS.\n"
                    "Tu peux te connecter et cliquer sur “Confirmer et démarrer”.\n\n"
                    f"Objectif: {selected_camp.get('objective','')}\n"
                    f"Durée: {selected_camp.get('weeks', 3)} semaines\n\n"
                    "À bientôt."
                )
                send_email(learner_email, subj, body, reply_to=coach_email, tags={"event": "program_ready"})

                st.session_state["program_draft"] = program_text
                st.success("Publié ✅ (mail envoyé)")
                st.rerun()

        st.divider()
        st.markdown("### 💬 Message de démarrage (visible learner)")

        kickoff = st.text_area(
            " ",
            value=str(selected_camp.get("kickoff_message") or ""),
            height=120,
            placeholder="Ex: Bienvenue ! Cette semaine, on démarre simple et concret.",
            label_visibility="collapsed",
            key=f"kickoff_{selected_camp.get('id')}",
        )

        kc1, kc2, kc3 = st.columns([1, 1, 1])
        with kc1:
            if st.button("💾 Enregistrer", use_container_width=True):
                selected_camp["kickoff_message"] = kickoff.strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "kickoff_saved", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)

                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                subj = _mail_subject("Message de démarrage", selected_camp)
                send_email(learner_email, subj, kickoff.strip(), reply_to=coach_email, tags={"event": "kickoff_saved"})

                st.success("OK ✅ (mail envoyé)")
                st.rerun()

        with kc2:
            if st.button("✨ Auto-générer", use_container_width=True):
                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                learner_first = _first_name_from_access(learner_email)
                weeks = int(selected_camp.get("weeks") or 3)
                selected_camp["kickoff_message"] = _kickoff_template(learner_first, weeks, coach_first_name).strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "kickoff_autofill", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.success("Template appliqué ✅")
                st.rerun()

        with kc3:
            if st.button("📨 Renvoyer mail", use_container_width=True):
                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                subj = _mail_subject("Message de démarrage", selected_camp)
                send_email(learner_email, subj, str(selected_camp.get("kickoff_message") or ""), reply_to=coach_email, tags={"event": "kickoff_resend"})
                st.success("Mail renvoyé ✅")

        st.divider()
        st.subheader("📈 Suivi learner (lecture + réponse coach)")

        done_all, total_all, pct_all = _compute_global_completion(selected_camp)
        st.caption(f"Complétude globale : {pct_all:.0f}% ({done_all}/{total_all} actions faites)")
        st.progress(min(max(pct_all / 100.0, 0.0), 1.0))

        wp = selected_camp.get("weekly_plan") or []
        if not isinstance(wp, list) or not wp:
            st.info("weekly_plan vide.")
        else:
            for w in wp:
                if not isinstance(w, dict):
                    continue
                week_n = int(w.get("week") or 0) or 0
                obj_week = str(w.get("objective_week") or f"Semaine {week_n}").strip()

                d, t, pct = _compute_week_completion(w)
                header = f"Semaine {week_n} — {obj_week or 'Objectif non défini'} — {pct:.0f}% ({d}/{t})"

                with st.expander(header, expanded=(week_n == 1)):
                    st.markdown("**Update learner**")
                    learner_txt = str(w.get("learner_comment") or "").strip()
                    if learner_txt:
                        st.success(learner_txt)
                    else:
                        st.info("(pas de commentaire)")

                    st.divider()
                    st.markdown("**Actions & statut (coach ajuste)**")
                    actions = w.get("actions") or []
                    if not isinstance(actions, list) or not actions:
                        st.caption("Aucune action (initialisation depuis programme).")
                    else:
                        for ai, a in enumerate(actions):
                            if not isinstance(a, dict):
                                continue
                            txt = str(a.get("text") or "").strip()
                            if not txt:
                                continue
                            st.write(f"- {txt}")
                            current = str(a.get("status") or "not_started").strip()
                            keys = [k for k, _ in ACTION_STATUSES]
                            idxs = keys.index(current) if current in keys else 0
                            a["status"] = st.radio(
                                " ",
                                options=keys,
                                index=idxs,
                                format_func=lambda k: ACTION_LABEL.get(k, k),
                                key=f"coach_action_{selected_camp.get('id')}_{week_n}_{ai}",
                                horizontal=True,
                                label_visibility="collapsed",
                            )

                    st.divider()
                    st.markdown("**Réponse coach (visible learner)**")
                    coach_comment = st.text_area(
                        " ",
                        value=str(w.get("coach_comment") or ""),
                        key=f"coach_comment_{selected_camp.get('id')}_{week_n}",
                        height=90,
                        label_visibility="collapsed",
                    )

                    if st.button("💾 Enregistrer semaine (coach)", key=f"save_coach_{selected_camp.get('id')}_{week_n}", use_container_width=True):
                        now = now_iso()
                        w["coach_comment"] = coach_comment
                        w["updated_at"] = now
                        selected_camp["updated_at"] = now
                        _append_event(selected_camp, "coach_week_saved", actor="coach", payload={"week": week_n})
                        _save_campaign_in_list(campaigns, selected_camp)

                        learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                        subj = _mail_subject(f"Retour coach — semaine {week_n}", selected_camp)
                        send_email(learner_email, subj, coach_comment.strip(), reply_to=coach_email, tags={"event": "coach_week_saved", "week": week_n})

                        st.success("OK ✅ (mail envoyé)")
                        st.rerun()

with col_right:
    st.subheader("🚦 Actions")

    if selected_req and not selected_camp:
        if st.button("✅ Créer campagne (draft)", use_container_width=True):
            rid = str(selected_req.get("id") or "").strip()
            learner_email = (selected_req.get("email") or "").strip().lower()

            camp = {
                "id": f"camp_{rid}",
                "request_id": rid,
                "learner_email": learner_email,
                "coach_email": coach_email,
                "objective": (selected_req.get("objective") or "").strip(),
                "context": (selected_req.get("context") or "").strip(),
                "weeks": int(selected_req.get("weeks") or 3),
                "status": "draft",
                "program_text": "",
                "weekly_plan": [],
                "kickoff_message": "",
                "closure_message": "",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            camp = _ensure_weekly_plan(camp)
            _append_event(camp, "campaign_created", actor="coach")
            campaigns.append(camp)
            save_campaigns(campaigns)

            update_request(rid, {"status": "in_progress", "updated_at": now_iso()})
            st.success("Campagne créée ✅")
            st.rerun()

    if selected_camp:
        st.write(f"**Campagne :** `{selected_camp.get('id')}`")
        st.write(f"**Statut :** `{selected_camp.get('status')}`")
        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🟡 Remettre draft", use_container_width=True):
                selected_camp["status"] = "draft"
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "status_draft", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.rerun()

        with c2:
            if st.button("✅ Clôturer (closed)", use_container_width=True):
                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                learner_first = _first_name_from_access(learner_email)
                weeks = int(selected_camp.get("weeks") or 3)
                objective = str(selected_camp.get("objective") or "").strip()

                if not str(selected_camp.get("closure_message") or "").strip():
                    selected_camp["closure_message"] = _closure_template(learner_first, objective, weeks, coach_first_name).strip()

                selected_camp["status"] = "closed"
                selected_camp["closed_at"] = now_iso()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "campaign_closed", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)

                subj = _mail_subject("Programme clôturé", selected_camp)
                send_email(learner_email, subj, str(selected_camp.get("closure_message") or ""), reply_to=coach_email, tags={"event": "campaign_closed"})

                st.success("Clôturé ✅ (mail envoyé)")
                st.rerun()

        st.divider()
        st.markdown("### 🏁 Message de clôture (visible learner)")

        closing = st.text_area(
            " ",
            value=str(selected_camp.get("closure_message") or ""),
            height=120,
            placeholder="Message final (learner) …",
            label_visibility="collapsed",
            key=f"closure_{selected_camp.get('id')}",
        )

        cc1, cc2 = st.columns([1, 1])
        with cc1:
            if st.button("💾 Enregistrer clôture", use_container_width=True):
                selected_camp["closure_message"] = closing.strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "closure_saved", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)

                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                subj = _mail_subject("Message de clôture", selected_camp)
                send_email(learner_email, subj, closing.strip(), reply_to=coach_email, tags={"event": "closure_saved"})

                st.success("OK ✅ (mail envoyé)")
                st.rerun()

        with cc2:
            if st.button("✨ Auto-générer clôture", use_container_width=True):
                learner_email = str(selected_camp.get("learner_email") or "").strip().lower()
                learner_first = _first_name_from_access(learner_email)
                weeks = int(selected_camp.get("weeks") or 3)
                objective = str(selected_camp.get("objective") or "").strip()
                selected_camp["closure_message"] = _closure_template(learner_first, objective, weeks, coach_first_name).strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "closure_autofill", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.success("Template clôture appliqué ✅")
                st.rerun()

        st.divider()
        st.markdown("**Événements**")
        ev = selected_camp.get("events")
        if isinstance(ev, list) and ev:
            for e in list(reversed(ev))[:10]:
                st.write(f"- {e.get('ts','')} — {e.get('type','')}")
        else:
            st.caption("Aucun.")
