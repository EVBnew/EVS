# pages/10_coach_space.py
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit command)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Coach Space — EVERSKILLS", layout="wide")

from everskills.services.access import require_login, find_user
from everskills.services.guard import require_role
from everskills.services.mail_send_once import send_once
from everskills.services.storage import (
    load_campaigns,
    load_requests,
    now_iso,
    save_campaigns,
    update_request,
)

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

require_role({"coach", "super_admin"})

if user.get("role") not in ("coach", "admin", "super_admin"):
    st.warning("Accès réservé aux coachs / admins.")
    st.stop()

coach_email = (user.get("email") or "").strip().lower()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


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
    stt = _req_status(req)
    assigned = _norm_email(str(req.get("assigned_coach_email") or ""))
    suffix = f" — assigné: {assigned}" if assigned else ""
    return f"{email} — {stt} — {rid} — {obj[:60]}{suffix}"


def _label_camp(c: Dict[str, Any]) -> str:
    cid = str(c.get("id") or "camp")
    email = str(c.get("learner_email") or "unknown")
    status = _camp_status(c)
    obj = str(c.get("objective") or "")
    return f"{email} — {status} — {cid} — {obj[:60]}"


def _append_event(
    camp: Dict[str, Any],
    event_type: str,
    actor: str = "coach",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
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


# -----------------------------------------------------------------------------
# Weekly plan logic
# -----------------------------------------------------------------------------
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
        stt = str(a.get("status") or "").strip()
        # Heuristic: learner may store keys (very_hard... / within_reach...),
        # we only count "easy" or "very_easy" as done-ish, and keep backward compat.
        if stt in ("easy", "very_easy", "done", "4", "5"):
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


def _make_action_id(camp_id: str, week_n: int, seed: str) -> str:
    base = f"{camp_id}::w{week_n}::{seed}".encode("utf-8", errors="ignore")
    return "act_" + hashlib.sha1(base).hexdigest()[:16]


def _ensure_action_ids(camp: Dict[str, Any]) -> None:
    camp_id = str(camp.get("id") or "camp").strip()
    wp = camp.get("weekly_plan") or []
    if not isinstance(wp, list):
        return

    for w in wp:
        if not isinstance(w, dict):
            continue
        week_n = int(w.get("week") or 0) or 0
        actions = w.get("actions") or []
        if not isinstance(actions, list):
            actions = []

        for i, a in enumerate(actions):
            if not isinstance(a, dict):
                continue
            if str(a.get("id") or "").strip():
                continue
            txt = str(a.get("text") or "").strip()
            seed = txt if txt else f"idx:{i}"
            a["id"] = _make_action_id(camp_id, week_n, seed)

        w["actions"] = actions


def _ensure_weekly_plan(camp: Dict[str, Any]) -> Dict[str, Any]:
    """
    - Keep weekly structure stable.
    - IMPORTANT: we do NOT inject placeholder text.
      Empty actions may exist in coach UI, but learner will only see actions once saved with real text.
    """
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
        for i, a in enumerate(actions):
            if isinstance(a, dict):
                aid = str(a.get("id") or "").strip()
                txt_raw = str(a.get("text") or "")
                stt = str(a.get("status") or "within_reach").strip() or "within_reach"

                # Keep item even if text is empty (coach draft), but ensure id is present
                if not aid:
                    seed = txt_raw.strip() if txt_raw.strip() else f"idx:{i}"
                    aid = _make_action_id(str(camp.get("id") or "camp"), w, seed)

                norm_actions.append({"id": aid, "text": txt_raw, "status": stt})

            elif isinstance(a, str) and a.strip():
                txt = a.strip()
                aid = _make_action_id(str(camp.get("id") or "camp"), w, txt)
                norm_actions.append({"id": aid, "text": txt, "status": "within_reach"})

        norm.append(
            {
                "week": w,
                "objective_week": str(existing.get("objective_week") or "").strip(),
                "actions": norm_actions,
                "learner_comment": str(existing.get("learner_comment") or "").strip(),
                "coach_comment": str(existing.get("coach_comment") or "").strip(),
                "updated_at": str(existing.get("updated_at") or "").strip(),
                "mood_score": existing.get("mood_score"),
                "closed_at": str(existing.get("closed_at") or "").strip(),
                "closed_by": str(existing.get("closed_by") or "").strip(),
            }
        )

    camp["weekly_plan"] = norm
    camp["kickoff_message"] = str(camp.get("kickoff_message") or "").strip()
    camp["closure_message"] = str(camp.get("closure_message") or "").strip()

    _ensure_action_ids(camp)
    return camp


# -----------------------------------------------------------------------------
# program_text -> weekly_plan sync
# -----------------------------------------------------------------------------
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
    current_week: Optional[int] = None

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
    camp_id = str(camp.get("id") or "camp").strip()

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
            item["actions"] = [
                {"id": _make_action_id(camp_id, week_n, a.strip()), "text": a.strip(), "status": "within_reach"}
                for a in acts
                if a.strip()
            ]
            changed = True

    camp["weekly_plan"] = wp
    camp["weekly_init_program_hash"] = prog_hash
    _ensure_action_ids(camp)
    return camp, changed


# -----------------------------------------------------------------------------
# OpenAI (program gen)
# -----------------------------------------------------------------------------
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
    dear = f"Cher {lf}," if lf else "Bonjour,"
    return (
        f"{dear}\n\n"
        f"Ça a été un réel plaisir de t'accompagner dans ton objectif : {objective}.\n"
        f"Au cours de ces {weeks} semaines, tu as réalisé avec brio les activités proposées, "
        "en prenant en compte les retours que nous avons évoqués ensemble lors des points hebdomadaires.\n\n"
        "Et maintenant ?\n"
        "Une autre phase peut commencer : la réflexivité — être son propre coach avec un regard précis et bienveillant.\n\n"
        "Nous pouvons aussi rester en contact en nous écrivant de temps en temps — ça me ferait très plaisir de suivre ton évolution.\n"
        "Et si tu souhaites approfondir certains concepts dans ce format, je resterai disponible.\n\n"
        f"{lf + ',' if lf else ''} à nouveau, ça a été un vrai plaisir de faire ce chemin ensemble.\n\n"
        f"Au plaisir de nous revoir et d'échanger.\n\n{cf}"
    )


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
st.title("Coach Space")
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

# -----------------------------------------------------------------------------
# LEFT
# -----------------------------------------------------------------------------
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
        visible: List[Dict[str, Any]] = []
        for r in requests_sorted:
            stt = _req_status(r)
            if stt == "submitted":
                visible.append(r)
                continue
            if stt in ("assigned", "in_progress"):
                if _norm_email(str(r.get("assigned_coach_email") or "")) == coach_email:
                    visible.append(r)

        if not visible:
            st.info("Aucune demande (submitted ou assignée à toi).")
        else:
            options = [str(r.get("id") or "").strip() for r in visible]
            labels = {str(r.get("id") or "").strip(): _label_req(r) for r in visible}
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

# -----------------------------------------------------------------------------
# MID
# -----------------------------------------------------------------------------
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
            st.write(f"**Assigné à :** `{_norm_email(str(selected_req.get('assigned_coach_email') or '')) or '-'}`")

    if not selected_camp:
        st.info("Aucune campagne liée. ➜ Crée-la dans la colonne de droite.")
    else:
        existing_text = (selected_camp.get("program_text") or "").strip()
        camp_id = str(selected_camp.get("id") or "").strip()

        if st.session_state.get("_draft_cid") != camp_id:
            st.session_state["_draft_cid"] = camp_id
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
            selected_camp, _ = _sync_weekly_plan_from_program(selected_camp)
            _save_campaign_in_list(campaigns, selected_camp)
            st.success("Rechargé ✅")
            st.rerun()

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

                learner_to = _norm_email(str(selected_camp.get("learner_email") or ""))
                prog_hash = _hash_text(program_text)
                event_key = f"PROGRAM_PUBLISHED:{camp_id}:{prog_hash}"
                send_once(
                    event_key=event_key,
                    event_type="PROGRAM_PUBLISHED",
                    request_id=camp_id,
                    to_email=learner_to,
                    subject=f"[EVERSKILLS] Programme prêt ({camp_id})",
                    text_body=(
                        "Ton coach a publié ton programme.\n\n"
                        "Connecte-toi à EVERSKILLS (Learner Space > Mon plan) pour le consulter "
                        "et confirmer le démarrage.\n\n"
                        f"Campagne: {camp_id}\n"
                    ),
                    meta={"camp_id": camp_id, "learner_email": learner_to, "coach_email": coach_email},
                )

                st.session_state["program_draft"] = program_text
                st.success("Publié ✅")
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

        kc1, kc2 = st.columns([1, 1])
        with kc1:
            if st.button("💾 Enregistrer le message de démarrage", use_container_width=True):
                selected_camp["kickoff_message"] = kickoff.strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "kickoff_saved", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.success("OK ✅")
                st.rerun()
        with kc2:
            if st.button("✨ Auto-générer (template)", use_container_width=True):
                learner_email2 = _norm_email(str(selected_camp.get("learner_email") or ""))
                learner_first = _first_name_from_access(learner_email2)
                coach_first = str(user.get("first_name") or "").strip()
                weeks2 = int(selected_camp.get("weeks") or 3)
                selected_camp["kickoff_message"] = _kickoff_template(learner_first, weeks2, coach_first).strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "kickoff_autofill", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.success("Template appliqué ✅")
                st.rerun()

        st.divider()
        st.subheader("📈 Suivi learner (lecture + réponse coach + édition programme hebdo)")

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
                    st.markdown("**🛠️ Programme de la semaine (coach peut éditer)**")
                    obj_key = f"week_obj__{selected_camp.get('id')}__{week_n}"
                    st.text_input(
                        "Objectif de la semaine",
                        value=str(w.get("objective_week") or ""),
                        key=obj_key,
                    )

                    actions = w.get("actions") or []
                    if not isinstance(actions, list):
                        actions = []

                    remove_idx: Optional[int] = None
                    st.caption("Actions (ajout + édition + sauvegarde manuelle)")

                    # Render inputs
                    for ai, a in enumerate(actions):
                        if not isinstance(a, dict):
                            continue

                        aid = str(a.get("id") or "").strip()
                        txt = str(a.get("text") or "")

                        row = st.columns([0.12, 0.70, 0.18])
                        with row[0]:
                            st.code(aid or "no_id")
                        with row[1]:
                            st.text_input(
                                f"Action {ai+1}",
                                value=txt,
                                key=f"week_act_txt__{selected_camp.get('id')}__{week_n}__{ai}",
                                label_visibility="collapsed",
                            )
                        with row[2]:
                            if st.button(
                                "🗑️ Supprimer",
                                key=f"rm_act__{selected_camp.get('id')}__{week_n}__{ai}",
                                use_container_width=True,
                            ):
                                remove_idx = ai

                    # Add + Save (manual persist)
                    add_col, save_col = st.columns([0.40, 0.60])

                    with add_col:
                        if st.button(
                            "➕ Ajouter une action",
                            key=f"add_act__{selected_camp.get('id')}__{week_n}",
                            use_container_width=True,
                        ):
                            camp_id_for_action = str(selected_camp.get("id") or "camp").strip()
                            new_id = _make_action_id(camp_id_for_action, week_n, f"new:{now_iso()}")
                            actions.append({"id": new_id, "text": "", "status": "within_reach"})
                            w["actions"] = actions

                            selected_camp["updated_at"] = now_iso()
                            _append_event(
                                selected_camp,
                                "coach_action_added",
                                actor="coach",
                                payload={"week": week_n, "action_id": new_id},
                            )
                            _save_campaign_in_list(campaigns, selected_camp)
                            st.rerun()

                    with save_col:
                        if st.button(
                            "💾 Enregistrer actions",
                            key=f"save_actions__{selected_camp.get('id')}__{week_n}",
                            use_container_width=True,
                        ):
                            acts = w.get("actions") or []
                            if not isinstance(acts, list):
                                acts = []

                            # Read back from session_state
                            for ai, a in enumerate(acts):
                                if not isinstance(a, dict):
                                    continue
                                ktxt = f"week_act_txt__{selected_camp.get('id')}__{week_n}__{ai}"
                                a["text"] = str(st.session_state.get(ktxt) or "").strip()

                                if not str(a.get("id") or "").strip():
                                    camp_id_for_action = str(selected_camp.get("id") or "camp").strip()
                                    a["id"] = _make_action_id(camp_id_for_action, week_n, a["text"] or f"idx:{ai}")

                            # Keep only non-empty actions so learner never sees useless placeholders
                            acts = [a for a in acts if isinstance(a, dict) and str(a.get("text") or "").strip()]
                            w["actions"] = acts
                            selected_camp["updated_at"] = now_iso()

                            _append_event(selected_camp, "coach_actions_saved", actor="coach", payload={"week": week_n})
                            _save_campaign_in_list(campaigns, selected_camp)

                            st.success("Actions enregistrées ✅")
                            st.rerun()

                    # Remove action (outside button, still in expander)
                    if remove_idx is not None and 0 <= remove_idx < len(actions):
                        removed = actions.pop(remove_idx)
                        w["actions"] = actions
                        selected_camp["updated_at"] = now_iso()
                        _append_event(
                            selected_camp,
                            "coach_action_removed",
                            actor="coach",
                            payload={
                                "week": week_n,
                                "action_id": str(removed.get("id") or ""),
                                "text": str(removed.get("text") or ""),
                            },
                        )
                        _save_campaign_in_list(campaigns, selected_camp)
                        st.rerun()

                    st.divider()

                    st.markdown("**Update learner**")
                    learner_txt = str(w.get("learner_comment") or "").strip()
                    if learner_txt:
                        st.success(learner_txt)
                    else:
                        st.info("(pas de commentaire)")

                    st.divider()

                    st.markdown("**Note d’ambiance (coach ajuste)**")
                    mood = str(w.get("mood_score") or "").strip()
                    try:
                        mood_int = int(mood) if mood else 3
                    except Exception:
                        mood_int = 3
                    mood_int = min(max(mood_int, 1), 5)

                    w["mood_score"] = st.radio(
                        " ",
                        options=[1, 2, 3, 4, 5],
                        index=[1, 2, 3, 4, 5].index(mood_int),
                        format_func=lambda x: f"{x}",
                        key=f"coach_week_mood__{selected_camp.get('id')}__{week_n}",
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

                    st.divider()

                    closed_at = str(w.get("closed_at") or "").strip()
                    if closed_at:
                        st.success(f"✅ Partie {week_n} clôturée ({closed_at})")
                    else:
                        if st.button(
                            f"✅ Clôturer partie {week_n}",
                            key=f"close_week__{selected_camp.get('id')}__{week_n}",
                            use_container_width=True,
                        ):
                            w["closed_at"] = now_iso()
                            w["closed_by"] = coach_email
                            selected_camp["updated_at"] = now_iso()
                            _append_event(selected_camp, "week_closed", actor="coach", payload={"week": week_n})
                            _save_campaign_in_list(campaigns, selected_camp)
                            st.rerun()

                    if st.button(
                        "💾 Enregistrer semaine (coach)",
                        key=f"save_coach_{selected_camp.get('id')}_{week_n}",
                        use_container_width=True,
                    ):
                        now = now_iso()

                        # mood_score (1..5)
                        try:
                            w["mood_score"] = int(w.get("mood_score") or 3)
                        except Exception:
                            w["mood_score"] = 3
                        w["mood_score"] = min(max(int(w["mood_score"]), 1), 5)

                        # persist objective
                        w["objective_week"] = (st.session_state.get(obj_key) or "").strip()

                        # persist actions text
                        acts = w.get("actions") or []
                        if not isinstance(acts, list):
                            acts = []

                        for ai, a in enumerate(acts):
                            if not isinstance(a, dict):
                                continue
                            ktxt = f"week_act_txt__{selected_camp.get('id')}__{week_n}__{ai}"
                            a["text"] = str(st.session_state.get(ktxt) or str(a.get("text") or "")).strip()
                            if not str(a.get("id") or "").strip():
                                camp_id_for_action = str(selected_camp.get("id") or "camp").strip()
                                a["id"] = _make_action_id(camp_id_for_action, week_n, a["text"] or f"idx:{ai}")

                        # remove empty actions at save time
                        acts = [a for a in acts if isinstance(a, dict) and str(a.get("text") or "").strip()]
                        w["actions"] = acts

                        w["coach_comment"] = coach_comment
                        w["updated_at"] = now
                        selected_camp["updated_at"] = now

                        _append_event(selected_camp, "coach_week_saved", actor="coach", payload={"week": week_n})
                        _save_campaign_in_list(campaigns, selected_camp)

                        learner_to = _norm_email(str(selected_camp.get("learner_email") or ""))
                        coach_from = _norm_email(str(selected_camp.get("coach_email") or coach_email))
                        cid3 = str(selected_camp.get("id") or "").strip()

                        send_once(
                            event_key=f"COACH_UPDATE:{cid3}:{week_n}:{now}",
                            event_type="COACH_UPDATE",
                            request_id=cid3,
                            to_email=learner_to,
                            subject=f"[EVERSKILLS] Retour coach semaine {week_n} ({cid3})",
                            text_body=(
                                f"Ton coach a répondu sur ta semaine {week_n}.\n\n"
                                f"Campagne: {cid3}\n"
                                f"Coach: {coach_from}\n\n"
                                f"{coach_comment.strip() or '(pas de message)'}"
                            ),
                            meta={
                                "camp_id": cid3,
                                "week": week_n,
                                "learner_email": learner_to,
                                "coach_email": coach_from,
                            },
                        )

                        st.success("OK ✅")
                        st.rerun()

# -----------------------------------------------------------------------------
# RIGHT
# -----------------------------------------------------------------------------
with col_right:
    st.subheader("🚦 Actions")

    if selected_req and not selected_camp:
        st.divider()
        if st.button("✅ Créer campagne (draft)", use_container_width=True):
            rid = str(selected_req.get("id") or "").strip()
            learner_email3 = _norm_email(str(selected_req.get("email") or ""))

            camp = {
                "id": f"camp_{rid}",
                "request_id": rid,
                "learner_email": learner_email3,
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
        st.divider()
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
                learner_email4 = _norm_email(str(selected_camp.get("learner_email") or ""))
                learner_first = _first_name_from_access(learner_email4)
                coach_first = str(user.get("first_name") or "").strip()
                weeks4 = int(selected_camp.get("weeks") or 3)
                objective4 = str(selected_camp.get("objective") or "").strip()

                if not str(selected_camp.get("closure_message") or "").strip():
                    selected_camp["closure_message"] = _closure_template(
                        learner_first, objective4, weeks4, coach_first
                    ).strip()

                selected_camp["status"] = "closed"
                selected_camp["closed_at"] = now_iso()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "campaign_closed", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)

                camp_id2 = str(selected_camp.get("id") or "").strip()
                send_once(
                    event_key=f"CAMPAIGN_CLOSED:{camp_id2}",
                    event_type="CAMPAIGN_CLOSED",
                    request_id=camp_id2,
                    to_email=learner_email4,
                    subject=f"[EVERSKILLS] Campagne clôturée ({camp_id2})",
                    text_body=str(selected_camp.get("closure_message") or "").strip()
                    or "Ta campagne est clôturée. Bravo pour le chemin parcouru !",
                    meta={"camp_id": camp_id2, "learner_email": learner_email4, "coach_email": coach_email},
                )

                st.success("Clôturé ✅ (message de clôture prêt + email envoyé)")
                st.rerun()

        st.divider()
        st.markdown("### 🏁 Message de clôture (visible learner)")

        closing = st.text_area(
            " ",
            value=str(selected_camp.get("closure_message") or ""),
            height=120,
            placeholder="Ex: Bravo pour le chemin parcouru... (message final)",
            label_visibility="collapsed",
            key=f"closure_{selected_camp.get('id')}",
        )

        cc1, cc2 = st.columns([1, 1])
        with cc1:
            if st.button("💾 Enregistrer le message de clôture", use_container_width=True):
                selected_camp["closure_message"] = closing.strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "closure_saved", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.success("OK ✅")
                st.rerun()
        with cc2:
            if st.button("✨ Auto-générer (template clôture)", use_container_width=True):
                learner_email5 = _norm_email(str(selected_camp.get("learner_email") or ""))
                learner_first = _first_name_from_access(learner_email5)
                coach_first = str(user.get("first_name") or "").strip()
                weeks5 = int(selected_camp.get("weeks") or 3)
                objective5 = str(selected_camp.get("objective") or "").strip()
                selected_camp["closure_message"] = _closure_template(
                    learner_first, objective5, weeks5, coach_first
                ).strip()
                selected_camp["updated_at"] = now_iso()
                _append_event(selected_camp, "closure_autofill", actor="coach")
                _save_campaign_in_list(campaigns, selected_camp)
                st.success("Template appliqué ✅")
                st.rerun()

        st.divider()
        st.markdown("**Événements**")
        ev = selected_camp.get("events")
        if isinstance(ev, list) and ev:
            for e in list(reversed(ev))[:12]:
                st.write(f"- {e.get('ts','')} — {e.get('type','')}")
        else:
            st.caption("Aucun.")