# pages/11_learner_space.py
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

import streamlit as st

# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Learner Space — EVERSKILLS", layout="wide")

from everskills.services.access import require_login  # noqa: E402
from everskills.services.guard import require_role  # noqa: E402
from everskills.services.mail_send_once import send_once  # noqa: E402
from everskills.services.storage import (  # noqa: E402
    load_requests,
    save_requests,
    load_campaigns,
    save_campaigns,
    now_iso,
)

# Global sidebar (single source of truth)
from everskills.ui.sidebar import render_sidebar  # noqa: E402

# -----------------------------------------------------------------------------
# ROLE GUARD (anti accès direct URL)
# -----------------------------------------------------------------------------
require_role({"learner", "super_admin"})

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

if (user or {}).get("role") not in ("learner", "super_admin"):
    st.warning("Cette page est réservée aux apprenants.")
    st.stop()

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _admin_rh_email() -> str:
    v = str(st.secrets.get("ADMIN_EMAIL") or "").strip()
    if v:
        return v
    v = str(st.secrets.get("ACCESS_ADMIN_EMAIL") or "").strip()
    if v:
        return v
    return "contact@everboarding.fr"


def _parse_iso_dt(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _current_week_for_campaign(camp: Dict[str, Any]) -> int:
    try:
        weeks = int(camp.get("weeks") or 1)
    except Exception:
        weeks = 1

    start = _parse_iso_dt(str(camp.get("activated_at") or camp.get("created_at") or camp.get("ts") or ""))
    if not start:
        return 1
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    days = max(0, int((now - start).total_seconds() // 86400))
    wk = 1 + (days // 7)
    return max(1, min(int(wk), int(weeks)))


def _upsert_campaign(campaigns: List[Dict[str, Any]], camp: Dict[str, Any]) -> List[Dict[str, Any]]:
    cid = str(camp.get("id") or "").strip()
    out: List[Dict[str, Any]] = []
    replaced = False
    for c in campaigns:
        if isinstance(c, dict) and str(c.get("id") or "").strip() == cid:
            out.append(camp)
            replaced = True
        else:
            out.append(c)
    if not replaced:
        out.append(camp)
    return out


def _status_to_int(raw: Any) -> int:
    """
    Normalise l’état d’une action sur une échelle 1..5.
    Supporte:
    - int 1..5
    - str "1".."5"
    - anciens statuts ("very_easy", "easy", etc.) => mapping
    """
    if raw is None:
        return 3
    try:
        if isinstance(raw, int):
            return min(max(raw, 1), 5)
        s = str(raw).strip()
        if s.isdigit():
            return min(max(int(s), 1), 5)
        mapping = {
            "very_hard": 1,
            "hard": 2,
            "within_reach": 3,
            "easy": 4,
            "very_easy": 5,
            "not_started": 1,
            "partial": 3,
            "done": 5,
        }
        return mapping.get(s, 3)
    except Exception:
        return 3


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
                aid = str(a.get("id") or "").strip()
                txt = str(a.get("text") or "")
                stt = _status_to_int(a.get("status"))
                item = {"text": txt, "status": stt}
                if aid:
                    item["id"] = aid
                norm_actions.append(item)
            elif isinstance(a, str):
                norm_actions.append({"text": a, "status": 3})

        mood_score = existing.get("mood_score")
        mood_int = _status_to_int(mood_score) if str(mood_score or "").strip() else 3

        norm.append(
            {
                "week": w,
                "objective_week": str(existing.get("objective_week") or "").strip(),
                "actions": norm_actions,
                "learner_comment": str(existing.get("learner_comment") or "").strip(),
                "coach_comment": str(existing.get("coach_comment") or "").strip(),
                "updated_at": str(existing.get("updated_at") or "").strip(),
                "mood_score": mood_int,
                "closed_at": str(existing.get("closed_at") or "").strip(),
            }
        )

    camp["weekly_plan"] = norm
    camp["kickoff_message"] = str(camp.get("kickoff_message") or "").strip()
    camp["closure_message"] = str(camp.get("closure_message") or "").strip()
    return camp


def _compute_week_completion(week: Dict[str, Any]) -> float:
    actions = week.get("actions") or []
    if not isinstance(actions, list) or not actions:
        return 0.0
    total = 0
    done = 0
    for a in actions:
        if not isinstance(a, dict):
            continue
        txt = str(a.get("text") or "").strip()
        if not txt:
            continue
        total += 1
        stt = _status_to_int(a.get("status"))
        if stt >= 4:
            done += 1
    return (done / total * 100.0) if total else 0.0


def _compute_global_completion(camp: Dict[str, Any]) -> float:
    wp = camp.get("weekly_plan") or []
    if not isinstance(wp, list) or not wp:
        return 0.0
    total_pct = 0.0
    count = 0
    for w in wp:
        if isinstance(w, dict):
            total_pct += _compute_week_completion(w)
            count += 1
    return (total_pct / count) if count else 0.0


def _week_by_n(c: Dict[str, Any], n: int) -> Optional[Dict[str, Any]]:
    wpl = c.get("weekly_plan") or []
    if not isinstance(wpl, list):
        return None
    for it in wpl:
        if isinstance(it, dict) and int(it.get("week") or 0) == int(n):
            return it
    return None


def _date_to_iso(d: Any) -> str:
    if isinstance(d, date):
        return d.isoformat()
    s = str(d or "").strip()
    return s


def _render_action_plan_official(official: Dict[str, Any]) -> None:
    st.markdown("### 🧩 Mon plan d’action officiel")

    intention = str(official.get("intention") or "").strip()
    if intention:
        st.markdown("**🎯 Intention stratégique**")
        st.write(intention)

    engagement = official.get("engagement_score")
    if str(engagement or "").strip():
        try:
            e = int(engagement)
        except Exception:
            e = 0
        if 1 <= e <= 5:
            st.markdown("**📊 Niveau d’engagement**")
            st.write(f"{e}/5")

    actions = official.get("actions") or []
    if isinstance(actions, list) and actions:
        st.markdown("**📌 Actions prioritaires**")
        shown = 0
        for a in actions[:3]:
            if not isinstance(a, dict):
                continue
            desc = str(a.get("description") or "").strip()
            if not desc:
                continue
            shown += 1
            due = str(a.get("due_date") or "").strip()
            impact = str(a.get("impact") or "").strip()

            line = f"- **{desc}**"
            if due:
                line += f" _(échéance: {due})_"
            st.write(line)
            if impact:
                st.caption(f"Impact attendu : {impact}")

        if shown == 0:
            st.info("Plan officiel présent, mais aucune action n’est renseignée.")

    fr = str(official.get("frictions") or "").strip()
    if fr:
        st.markdown("**⛔ Freins anticipés**")
        st.write(fr)

    exp = official.get("coach_expectations") or {}
    if isinstance(exp, dict):
        txt = str(exp.get("text") or "").strip()
    else:
        txt = str(exp or "").strip()
    if txt:
        st.markdown("**🤝 Attentes vis-à-vis du coach**")
        st.write(txt)

    validated_at = str(official.get("validated_at") or "").strip()
    if validated_at:
        st.caption(f"Validé par le coach : {validated_at}")


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
learner_email = _norm_email(str((user or {}).get("email") or ""))

st.title("🎯 Learner Space")
st.caption("Demande → plan → exécution → suivi hebdo")

t1, t2 = st.tabs(["📝 Ma demande", "📌 Mon plan"])

# -----------------------------------------------------------------------------
# TAB 1: Request
# -----------------------------------------------------------------------------
with t1:
    st.subheader("📝 Soumettre une demande")

    with st.form("learner_request_form", clear_on_submit=False):
        objective = st.text_input("Objectif", placeholder="Ex: gagner en assertivité en réunion", max_chars=200)
        context = st.text_area(
            "Contexte",
            height=120,
            placeholder="Décris la situation, ce que tu veux changer, la contrainte, etc.",
        )
        weeks = st.number_input("Durée (parties)", min_value=1, max_value=8, value=3, step=1)

        st.divider()
        st.markdown("### 🧩 Plan d’action post-formation (optionnel)")
        ap_enabled = st.checkbox("☐ Je souhaite définir mon plan d’action maintenant", value=False)

        ap_intention = ""
        ap_engagement = 3
        ap_frictions = ""
        ap_expectations = ""
        ap_actions: List[Dict[str, Any]] = []

        # IMPORTANT (Streamlit): inside a form, widgets don't rerun on change.
        # So we always display the fields, and ap_enabled decides whether we save them.
        with st.expander("🧩 Définir mon plan d’action (3 actions max)", expanded=False):

            ap_intention = st.text_area(
                "🎯 Intention stratégique",
                height=90,
                placeholder="Ex: Je veux être capable de… / Je veux changer…",
                max_chars=800,
            )

            st.markdown("**📌 3 actions max**")
            for i in range(1, 4):
                with st.expander(f"Action {i}", expanded=(i == 1)):
                    desc = st.text_input(
                        "Description",
                        key=f"ap_desc_{i}",
                        placeholder="Ex: préparer 1 prise de parole par semaine…",
                        max_chars=800,
                    )
                    due = st.date_input(
                        "Échéance",
                        key=f"ap_due_{i}",
                        value=None,
                    )
                    impact = st.text_input(
                        "Impact attendu",
                        key=f"ap_impact_{i}",
                        placeholder="Ex: + clarté / + confiance / + efficacité…",
                        max_chars=120,
                    )

                    if (desc or "").strip():
                        ap_actions.append(
                            {
                                "id": f"ap_act_{uuid.uuid4().hex[:10]}",
                                "description": desc.strip(),
                                "due_date": _date_to_iso(due) if due else "",
                                "impact": (impact or "").strip(),
                            }
                        )

            ap_engagement = st.select_slider(
                "📊 Niveau d’engagement",
                options=[1, 2, 3, 4, 5],
                value=3,
                format_func=lambda x: {1: "1 (faible)", 2: "2", 3: "3", 4: "4", 5: "5 (fort)"}[x],
            )

            ap_frictions = st.text_area(
                "⛔ Freins anticipés",
                height=80,
                placeholder="Ex: manque de temps, peur du regard des autres, contexte d’équipe…",
                max_chars=800,
            )

            ap_expectations = st.text_area(
                "🤝 Attentes vis-à-vis du coach",
                height=80,
                placeholder="Ex: feedback direct, challenge, cadence, relecture…",
                max_chars=800,
            )

        # ------------------------------------------------------------------
        # CR16 — build action_plan_draft to persist in request
        # ------------------------------------------------------------------
        action_plan_draft = {
            "enabled": bool(ap_enabled),
            "intention": (ap_intention or "").strip(),
            "actions": ap_actions[:3],
            "engagement_score": int(ap_engagement or 3),
            "frictions": (ap_frictions or "").strip(),
            "coach_expectations": {"mode": "text", "text": (ap_expectations or "").strip(), "tags": []},
        }

        submitted = st.form_submit_button("📨 Envoyer la demande")

    if submitted:
        if not (objective or "").strip():
            st.error("Objectif obligatoire.")
        else:
            requests = [r for r in (load_requests() or []) if isinstance(r, dict)]

            rid = f"req_{uuid.uuid4().hex[:10]}"
            req: Dict[str, Any] = {
                "id": rid,
                "ts": now_iso(),
                "email": learner_email,
                "objective": (objective or "").strip(),
                "context": (context or "").strip(),
                "weeks": int(weeks),
                "supports": [],
                "status": "submitted",
                "action_plan_draft": action_plan_draft,
            }

            # CR16: optional action plan draft (stored inside Request)
            if ap_enabled:
                now = now_iso()
                req["action_plan_draft"]["enabled"] = True
                req["action_plan_draft"]["created_at"] = now
                req["action_plan_draft"]["updated_at"] = now
            else:
                req["action_plan_draft"]["enabled"] = False

            requests.append(req)
            save_requests(requests)

            admin_to = _admin_rh_email().strip().lower()
            event_key = f"REQUEST_SUBMITTED:{rid}"

            if not admin_to:
                st.error("ADMIN_EMAIL / ACCESS_ADMIN_EMAIL manquant.")
            else:
                extra = ""
                if ap_enabled:
                    extra = "\n\nPlan d’action: OUI (draft inclus dans la demande)."
                send_once(
                    event_key=event_key,
                    event_type="REQUEST_SUBMITTED",
                    request_id=rid,
                    to_email=admin_to,
                    subject=f"[EVERSKILLS] Nouvelle demande ({rid})",
                    text_body=(
                        "Une nouvelle demande learner a été soumise.\n\n"
                        f"Learner: {learner_email}\n"
                        f"Objectif: {(objective or '').strip()}\n"
                        f"Durée: {int(weeks)} partie(s)\n"
                        f"{extra}\n\n"
                        "Ouvre Admin RH Space pour l’assigner à un coach."
                    ),
                    meta={"learner_email": learner_email, "admin_email": admin_to},
                )

                st.success(f"Demande envoyée ✅ (destinataire: {admin_to})")

    st.divider()
    st.caption("Tes dernières demandes")
    my_reqs = [
        r
        for r in (load_requests() or [])
        if isinstance(r, dict) and _norm_email(r.get("email", "")) == learner_email
    ]
    my_reqs = sorted(my_reqs, key=lambda r: str(r.get("ts") or ""), reverse=True)

    if not my_reqs:
        st.info("Aucune demande pour l’instant.")
    else:
        for r in my_reqs[:6]:
            flag = ""
            ap = r.get("action_plan_draft")
            if isinstance(ap, dict) and bool(ap.get("enabled")):
                flag = " — 🧩 plan inclus"
            st.write(f"- `{r.get('status','')}` — {str(r.get('objective',''))[:80]} — {r.get('id','')}{flag}")

# -----------------------------------------------------------------------------
# TAB 2: Plan + suivi hebdo
# -----------------------------------------------------------------------------
with t2:
    st.subheader("📌 Mon plan")

    campaigns = [c for c in (load_campaigns() or []) if isinstance(c, dict)]
    my_campaigns = [
        c
        for c in campaigns
        if _norm_email(c.get("learner_email", "")) == learner_email
        and (c.get("status") in ("program_ready", "active", "closed", "draft", "coach_validated"))
    ]

    if not my_campaigns:
        st.info("Pas encore de campagne. Une fois que le coach publie, elle apparaîtra ici.")
        st.stop()

    labels = [f"{c.get('id','')} — {c.get('status','')} — {str(c.get('objective',''))[:50]}" for c in my_campaigns]
    idx = st.selectbox("Choisir une campagne", options=list(range(len(my_campaigns))), format_func=lambda i: labels[i])

    camp = _ensure_weekly_plan(my_campaigns[idx])
    current_week = _current_week_for_campaign(camp)
    camp_id = str(camp.get("id") or "").strip()

    # -------------------------------------------------------------------------
    # Push KPI to global sidebar (sidebar.py)
    # -------------------------------------------------------------------------
    pct_global = _compute_global_completion(camp)

    done_total = 0
    total_total = 0
    wp_all = camp.get("weekly_plan") or []
    if not isinstance(wp_all, list):
        wp_all = []

    for ww in wp_all:
        if not isinstance(ww, dict):
            continue
        acts = ww.get("actions") or []
        if not isinstance(acts, list):
            continue
        for aa in acts:
            if not isinstance(aa, dict):
                continue
            txt = str(aa.get("text") or "").strip()
            if not txt:
                continue
            total_total += 1
            if _status_to_int(aa.get("status")) >= 4:
                done_total += 1

    cur_w = _week_by_n(camp, current_week) or {}
    prev_w = _week_by_n(camp, max(1, current_week - 1)) or {}
    pct_cur = _compute_week_completion(cur_w) if cur_w else 0.0
    pct_prev = _compute_week_completion(prev_w) if (current_week > 1 and prev_w) else 0.0
    velocity = pct_cur - pct_prev

    mood_emoji = {1: "😫", 2: "😕", 3: "🙂", 4: "😄", 5: "🤩"}
    mood_val = _status_to_int(cur_w.get("mood_score")) if cur_w else 3
    mood_icon = mood_emoji.get(int(mood_val), "🙂")

    st.session_state["SIDEBAR_KPI"] = {
        "progress": f"{pct_global:.0f}%",
        "velocity": f"{velocity:+.0f}%",
        "actions": f"{done_total}/{total_total}" if total_total else "0/0",
        "mood": mood_icon,
        "camp_id": camp_id,
        "current_week": int(current_week),
    }

    render_sidebar()

    left, right = st.columns([1.05, 1.95], gap="large")

    # LEFT: résumé + plan/programme
    with left:
        st.markdown("### Résumé")
        st.write(f"**Objectif :** {camp.get('objective','')}")
        st.write(f"**Contexte :** {camp.get('context','')}")
        st.write(f"**Parties :** {camp.get('weeks', 3)}")
        st.write(f"**Statut :** `{camp.get('status','')}`")

        pct = _compute_global_completion(camp)
        st.caption(f"Progression globale : {pct:.0f}%")
        st.progress(min(max(pct / 100.0, 0.0), 1.0))



        # CR16: if weekly_plan_origin == action_plan, replace "Programme (coach)" by official action plan
        st.divider()

        weekly_origin = str(camp.get("weekly_plan_origin") or "").strip()
        ap = camp.get("action_plan") or {}
        if not isinstance(ap, dict):
            ap = {}
        official = ap.get("official") or {}
        if not isinstance(official, dict):
            official = {}

        if weekly_origin == "action_plan" and official:
            _render_action_plan_official(official)
        else:
            st.markdown("### Programme (coach)")
            program_text = str(camp.get("program_text") or "").strip()
            if program_text:
                st.markdown(program_text)
            else:
                st.info("Programme pas encore publié.")

        if camp.get("status") == "program_ready":
            st.warning("Programme prêt. Clique pour démarrer.")
            if st.button("✅ Confirmer et démarrer", use_container_width=True):
                now = now_iso()
                camp["status"] = "active"
                camp["activated_at"] = now
                camp["updated_at"] = now
                campaigns = _upsert_campaign(campaigns, camp)
                save_campaigns(campaigns)

                cid = str(camp.get("id") or "").strip()
                coach_to = str(camp.get("coach_email") or "").strip().lower() or "admin@everboarding.fr"
                kickoff_txt = str(camp.get("kickoff_message") or "").strip()

                send_once(
                    event_key=f"PROGRAM_VALIDATED:{cid}",
                    event_type="PROGRAM_VALIDATED",
                    request_id=cid,
                    to_email=coach_to,
                    subject=f"[EVERSKILLS] Programme validé ({cid})",
                    text_body=(
                    "Cet email marque le démarrage officiel de ton programme Everboarding.\n\n"
                    "Ton programme démarre officiellement. Tu peux suivre ton avancement dans Learner Space."
                    ),
                    meta={"camp_id": cid},
                )

                send_once(
                    event_key=f"PROGRAM_STARTED:{cid}",
                    event_type="PROGRAM_STARTED",
                    request_id=cid,
                    to_email=learner_email,
                    subject=f"[EVERSKILLS] Démarrage officiel ({cid})",
                    text_body=(
                    "Cet email marque le démarrage officiel de ton programme Everboarding.\n\n"
                    "Ton programme démarre officiellement. Tu peux suivre ton avancement dans Learner Space."
                    ),
                    meta={"camp_id": cid},
                )

                st.success("Campagne démarrée ✅")
                st.rerun()

    # RIGHT: suivi hebdo uniquement
    with right:
        st.markdown("### 📈 Suivi hebdo")
        st.caption("Ici : actions + commentaire + note d’ambiance. Le canal chat est ailleurs.")

        wp = camp.get("weekly_plan") or []
        if not isinstance(wp, list) or not wp:
            st.info("Aucun suivi disponible.")
            st.stop()

        for w in wp:
            if not isinstance(w, dict):
                continue

            part_n = int(w.get("week") or 0) or 0
            obj_part = str(w.get("objective_week") or f"Partie {part_n}").strip()

            pctw = _compute_week_completion(w)
            with st.expander(
                f"Partie {part_n} — {obj_part or 'Objectif non défini'} — {pctw:.0f}%",
                expanded=(part_n == current_week),
            ):
                closed_at = str(w.get("closed_at") or "").strip()
                is_closed = bool(closed_at)

                # Barre de progression par partie
                st.progress(min(max(pctw / 100.0, 0.0), 1.0))

                if is_closed:
                    st.success(f"✅ Partie clôturée ({closed_at})")

                st.markdown("**Objectif de la partie**")
                if obj_part:
                    st.write(obj_part)
                else:
                    st.warning("Objectif non défini.")

                st.divider()
                st.markdown("**Actions (coach → toi)**")

                actions = w.get("actions") or []
                if not isinstance(actions, list) or not actions:
                    st.caption("Pas d’actions pour l’instant.")
                else:
                    shown = 0
                    for ai, a in enumerate(actions):
                        if not isinstance(a, dict):
                            continue
                        txt = str(a.get("text") or "").strip()
                        if not txt:
                            continue  # IMPORTANT: on n’affiche pas les actions vides
                        shown += 1

                        aid = str(a.get("id") or "").strip()
                        if aid:
                            st.caption(f"action_id: `{aid}`")

                        st.write(f"- {txt}")

                        current = _status_to_int(a.get("status"))
                        key_id = aid or f"idx_{ai}"
                        new_status = st.radio(
                            " ",
                            options=[1, 2, 3, 4, 5],
                            index=[1, 2, 3, 4, 5].index(current),
                            format_func=lambda x: [
                                "😫 Très difficile",
                                "😕 Difficile",
                                "🙂 À ma portée",
                                "😄 Facile",
                                "🤩 Très facile",
                            ][x - 1],
                            key=f"learner_action__{camp.get('id')}__{part_n}__{key_id}",
                            horizontal=True,
                            label_visibility="collapsed",
                            disabled=is_closed,
                        )
                        a["status"] = int(new_status)

                    if shown == 0:
                        st.info("Le coach a ajouté des actions mais elles ne sont pas encore renseignées.")

                st.divider()
                st.markdown("**Note d’ambiance (1 à 5)**")

                mood_current = _status_to_int(w.get("mood_score"))
                mood_new = st.radio(
                    " ",
                    options=[1, 2, 3, 4, 5],
                    index=[1, 2, 3, 4, 5].index(mood_current),
                    key=f"learner_mood__{camp.get('id')}__{part_n}",
                    horizontal=True,
                    label_visibility="collapsed",
                    disabled=is_closed,
                )
                w["mood_score"] = int(mood_new)

                st.divider()
                st.markdown("**Ton compte-rendu (verbatim)**")

                comment = st.text_area(
                    " ",
                    value=str(w.get("learner_comment") or ""),
                    key=f"learner_comment_{camp.get('id')}_{part_n}",
                    height=110,
                    placeholder="Ex: ce que j’ai fait, ce qui a bloqué, ce que je vais tenter la semaine prochaine…",
                    label_visibility="collapsed",
                    disabled=is_closed,
                )

                coach_comment = str(w.get("coach_comment") or "").strip()
                if coach_comment:
                    st.markdown("**Retour coach**")
                    st.info(coach_comment)

                if st.button(
                    "💾 Enregistrer mon suivi",
                    key=f"save_learner_part_{camp.get('id')}_{part_n}",
                    use_container_width=True,
                    disabled=is_closed,
                ):
                    now = now_iso()
                    w["actions"] = actions
                    w["learner_comment"] = comment
                    w["updated_at"] = now
                    camp["updated_at"] = now

                    campaigns = _upsert_campaign(campaigns, camp)
                    save_campaigns(campaigns)

                    cid = str(camp.get("id") or "").strip()
                    coach_to = str(camp.get("coach_email") or "").strip().lower() or "admin@everboarding.fr"
                    send_once(
                        event_key=f"LEARNER_UPDATE:{cid}:{part_n}:{now}",
                        event_type="LEARNER_UPDATE",
                        request_id=cid,
                        to_email=coach_to,
                        subject=f"[EVERSKILLS] Suivi partie {part_n} ({cid})",
                        text_body=(
                            f"Suivi learner (partie {part_n}).\n\n"
                            f"Learner: {learner_email}\n"
                            f"Note d'ambiance: {w.get('mood_score')}\n\n"
                            f"{comment}"
                        ),
                        meta={"camp_id": cid, "week": part_n, "learner_email": learner_email},
                    )

                    st.success("OK ✅")
                    st.rerun()