# pages/11_learner_space.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid
from datetime import datetime, timezone

import streamlit as st

from everskills.services.access import require_login, change_password
from everskills.services.storage import (
    load_requests,
    save_requests,
    load_campaigns,
    save_campaigns,
    now_iso,
)
from everskills.services.guard import require_role
from everskills.services.journal_gsheet import (
    build_entry,
    journal_create,
    journal_list_learner,
)

# CR11: email events (idempotent)
from everskills.services.mail_send_once import send_once


# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Learner Space — EVERSKILLS", layout="wide")

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
    st.info("Reviens à ton espace.")
    st.stop()


# ----------------------------
# Helpers
# ----------------------------
def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _admin_rh_email() -> str:
    """
    Routing #0:
    - ADMIN_EMAIL (prioritaire)
    - ACCESS_ADMIN_EMAIL (fallback)
    - hard fallback: contact@
    """
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
    """Week number based on activated_at/created_at. Fallback week=1."""
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


ACTION_STATUSES = [
    ("not_started", "🔴 Pas fait"),
    ("partial", "🟡 Partiel"),
    ("done", "🟢 Fait"),
]
ACTION_LABEL = {k: v for k, v in ACTION_STATUSES}


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
        if str(a.get("status") or "") == "done":
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


def _journal_history_block(learner_email: str) -> None:
    st.subheader("Journal — historique")
    st.caption("Tes notes (récent → ancien).")
    try:
        items = journal_list_learner(learner_email, limit=50)
    except Exception as e:
        st.error(f"Erreur de lecture journal: {e}")
        items = []

    if not items:
        st.info("Aucune note pour l’instant.")
        return

    for it in items[:20]:
        shared = bool(it.get("share_with_coach"))
        ts = it.get("created_at") or ""
        tags_list = it.get("tags") or []
        header = ("✅ Partagé" if shared else "🔒 Privé") + f" — {ts}"
        with st.expander(header, expanded=False):
            if tags_list:
                st.write("**Tags :** " + ", ".join([str(t) for t in tags_list]))
            st.text(it.get("body") or "")


# ----------------------------
# CR-04 — Sécurité du compte
# ----------------------------
st.divider()
st.markdown("### 🔐 Sécurité du compte")

with st.container(border=True):
    with st.form("change_password_form", clear_on_submit=True):
        old_pw = st.text_input("Mot de passe actuel", type="password")
        new_pw = st.text_input("Nouveau mot de passe", type="password")
        confirm_pw = st.text_input("Confirmer le nouveau mot de passe", type="password")
        submit_pw = st.form_submit_button("Changer mon mot de passe")

    if submit_pw:
        if not old_pw or not new_pw or not confirm_pw:
            st.error("Tous les champs sont requis.")
        elif new_pw != confirm_pw:
            st.error("Les mots de passe ne correspondent pas.")
        else:
            try:
                change_password(user["email"], old_pw, new_pw)
                st.success("Mot de passe mis à jour ✅")
            except Exception as e:
                st.error(str(e))


# ----------------------------
# UI
# ----------------------------
learner_email = _norm_email(user["email"])

st.title("🎯 Learner Space")
st.caption("Demande → plan → exécution → update → feedback coach")

t1, t2 = st.tabs(["📝 Ma demande", "📌 Mon plan"])


# ----------------------------
# TAB 1: Request
# ----------------------------
with t1:
    st.subheader("📝 Soumettre une demande")

    with st.form("learner_request_form", clear_on_submit=False):
        objective = st.text_input(
            "Objectif",
            placeholder="Ex: gagner en assertivité en réunion",
            max_chars=200,
        )

        context = st.text_area(
            "Contexte",
            height=120,
            placeholder="Décris la situation, ce que tu veux changer, la contrainte, etc.",
        )

        weeks = st.number_input(
            "Durée (semaines)",
            min_value=1,
            max_value=8,
            value=3,
            step=1,
        )

        submitted = st.form_submit_button("📨 Envoyer la demande")

    if submitted:
        if not (objective or "").strip():
            st.error("Objectif obligatoire.")
        else:
            requests = load_requests() or []
            requests = [r for r in requests if isinstance(r, dict)]

            rid = f"req_{uuid.uuid4().hex[:10]}"
            req = {
                "id": rid,
                "ts": now_iso(),
                "email": learner_email,
                "objective": (objective or "").strip(),
                "context": (context or "").strip(),
                "weeks": int(weeks),
                "supports": [],
                "status": "submitted",
            }
            requests.append(req)
            save_requests(requests)

            admin_to = _admin_rh_email().strip().lower()
            event_key = f"REQUEST_SUBMITTED:{rid}"

            if not admin_to:
                st.error("ADMIN_EMAIL / ACCESS_ADMIN_EMAIL manquant.")
            else:
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
                        f"Durée: {int(weeks)} semaine(s)\n\n"
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
            st.write(f"- `{r.get('status','')}` — {r.get('objective','')[:80]} — {r.get('id','')}")


# ----------------------------
# TAB 2: My Plan (Post-It en tête + Weekly intact)
# ----------------------------
with t2:
    st.subheader("📌 Mon plan")

    campaigns = load_campaigns() or []
    campaigns = [c for c in campaigns if isinstance(c, dict)]
    my_campaigns = [
        c
        for c in campaigns
        if _norm_email(c.get("learner_email", "")) == learner_email
        and (c.get("status") in ("program_ready", "active", "closed", "draft", "coach_validated"))
    ]

    if not my_campaigns:
        st.info("Pas encore de campagne. Une fois que le coach publie, elle apparaîtra ici.")
        st.stop()

    labels = [f"{c.get('id','')} — {c.get('status','')} — {c.get('objective','')[:50]}" for c in my_campaigns]
    idx = st.selectbox("Choisir une campagne", options=list(range(len(my_campaigns))), format_func=lambda i: labels[i])

    camp = _ensure_weekly_plan(my_campaigns[idx])
    current_week = _current_week_for_campaign(camp)

    left, right = st.columns([1.05, 1.95], gap="large")

    # ----------------------------
    # LEFT: Summary
    # ----------------------------
    with left:
        st.markdown("### Résumé")
        st.write(f"**Objectif :** {camp.get('objective','')}")
        st.write(f"**Contexte :** {camp.get('context','')}")
        st.write(f"**Semaines :** {camp.get('weeks', 3)}")
        st.write(f"**Statut :** `{camp.get('status','')}`")

        pct = _compute_global_completion(camp)
        st.caption(f"Progression globale : {pct:.0f}%")
        st.progress(min(max(pct / 100.0, 0.0), 1.0))

        kickoff = str(camp.get("kickoff_message") or "").strip()
        if kickoff:
            st.divider()
            st.markdown("### 💬 Message du coach")
            st.success(kickoff)

        closing = str(camp.get("closure_message") or "").strip()
        if closing:
            st.divider()
            st.markdown("### 🏁 Message de clôture")
            st.success(closing)
        elif str(camp.get("status") or "").strip() == "closed":
            st.divider()
            st.markdown("### 🏁 Message de clôture")
            st.info("Campagne clôturée. (Message de clôture non renseigné.)")

        st.divider()
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
                coach_email = str(camp.get("coach_email") or "").strip().lower() or "admin@everboarding.fr"
                kickoff_txt = str(camp.get("kickoff_message") or "").strip()

                send_once(
                    event_key=f"PROGRAM_VALIDATED:{cid}",
                    event_type="PROGRAM_VALIDATED",
                    request_id=cid,
                    to_email=coach_email,
                    subject=f"[EVERSKILLS] Programme validé ({cid})",
                    text_body=f"Le learner {learner_email} a validé le programme.\n\nCampagne: {cid}",
                    meta={"camp_id": cid, "learner_email": learner_email, "coach_email": coach_email},
                )

                send_once(
                    event_key=f"PROGRAM_STARTED:{cid}",
                    event_type="PROGRAM_STARTED",
                    request_id=cid,
                    to_email=learner_email,
                    subject=f"[EVERSKILLS] Démarrage officiel ({cid})",
                    text_body=kickoff_txt or "Ton programme démarre officiellement.",
                    meta={"camp_id": cid},
                )

                st.success("Campagne démarrée ✅")
                st.rerun()

    # ----------------------------
    # RIGHT: Post-it (top) + Weekly (unchanged) + Journal history
    # ----------------------------
    with right:
        # ---------------------------------------------------------------------
        # CR12 — POST-IT (accès direct, mobile-first)
        # - dispo seulement si campagne ACTIVE
        # - peut s'injecter dans weekly_comment (append, ne remplace pas)
        # - peut être partagé au coach (email + journal coach)
        # ---------------------------------------------------------------------
        st.markdown("### 🗒️ Post-it rapide")
        st.caption("À la volée. Optionnel : l’insérer dans ta semaine courante et/ou l’envoyer au coach.")

        camp_status = str(camp.get("status") or "").strip()

        # Email context
        author_email = learner_email
        author_user_id = str(user.get("user_id") or user.get("id") or author_email or "unknown").strip()

        coach_default = str(camp.get("coach_email") or "").strip().lower() or str(
            st.session_state.get("evs_coach_email") or ""
        ).strip().lower()

        with st.container(border=True):
            if camp_status != "active":
                st.info("Post-it disponible quand la campagne est **ACTIVE**.")
            else:
                with st.form("postit_quick_form", clear_on_submit=True):
                    mood = st.selectbox(
                        "Émotion / énergie",
                        options=["🟢 En confiance", "🔵 Flow", "🟡 Neutre", "🟠 Tendu", "🔴 Fatigué"],
                        index=2,
                    )

                    c1, c2 = st.columns(2)
                    with c1:
                        ps_success = st.text_area("Succès", height=80, placeholder="Ce qui a marché…")
                    with c2:
                        ps_difficulty = st.text_area("Difficulté", height=80, placeholder="Ce qui a bloqué…")

                    ps_learning = st.text_area("Apprentissage", height=80, placeholder="Ce que je retiens…")
                    ps_tags = st.text_input("Tags (virgules)", placeholder="ex: focus, respiration, assertivité")

                    inject_week = st.toggle("Insérer aussi dans mon Weekly Update (semaine courante)", value=True)
                    share_with_coach = st.toggle("Envoyer au coach", value=False)

                    coach_email_for_share = st.text_input(
                        "Email coach",
                        value=coach_default,
                        disabled=not share_with_coach,
                        placeholder="coach@email.com",
                    )

                    submitted_postit = st.form_submit_button("✅ Enregistrer Post-it", use_container_width=True)

                if submitted_postit:
                    if not (ps_success.strip() or ps_difficulty.strip() or ps_learning.strip()):
                        st.error("Renseigne au moins une section (Succès / Difficulté / Apprentissage).")
                    elif share_with_coach and ("@" not in coach_email_for_share):
                        st.error("Email coach invalide.")
                    else:
                        now = now_iso()
                        week_n = int(current_week)

                        body = (
                            f"Énergie: {mood}\n\n"
                            f"Succès:\n{ps_success.strip()}\n\n"
                            f"Difficulté:\n{ps_difficulty.strip()}\n\n"
                            f"Apprentissage:\n{ps_learning.strip()}\n"
                        )

                        try:
                            entry = build_entry(
                                author_user_id=author_user_id,
                                author_email=author_email,
                                body=body,
                                tags=ps_tags,
                                share_with_coach=share_with_coach,
                                coach_email=coach_email_for_share if share_with_coach else None,
                                prompt="post-it",
                            )
                            journal_create(entry)

                            # Inject into weekly comment (append only)
                            if inject_week:
                                wp = camp.get("weekly_plan") or []
                                if not isinstance(wp, list):
                                    wp = []
                                target_week = None
                                for w in wp:
                                    if isinstance(w, dict) and int(w.get("week") or 0) == week_n:
                                        target_week = w
                                        break
                                if target_week is not None:
                                    old = str(target_week.get("learner_comment") or "").strip()
                                    stamp = datetime.now().strftime("%d/%m %H:%M")
                                    block = f"🟨 Post-it ({stamp})\n{body.strip()}\n"
                                    target_week["learner_comment"] = (block + "\n\n" + old).strip()
                                    target_week["updated_at"] = now
                                    camp["updated_at"] = now

                                    campaigns = _upsert_campaign(campaigns, camp)
                                    save_campaigns(campaigns)

                            # Email coach (immediate)
                            if share_with_coach and "@" in coach_email_for_share:
                                cid = str(camp.get("id") or "").strip()
                                to_email = coach_email_for_share.strip().lower()
                                send_once(
                                    event_key=f"JOURNAL_SHARED:{cid}:{week_n}:{entry.id}",
                                    event_type="JOURNAL_SHARED",
                                    request_id=cid,
                                    to_email=to_email,
                                    subject=f"[EVERSKILLS] Post-it partagé — semaine {week_n} ({cid})",
                                    text_body=(
                                        f"Le learner {author_email} a partagé un post-it.\n\n"
                                        f"Campagne: {cid}\n"
                                        f"Semaine: {week_n}\n\n"
                                        f"{body}"
                                    ),
                                    meta={
                                        "camp_id": cid,
                                        "week": week_n,
                                        "learner_email": author_email,
                                        "coach_email": to_email,
                                        "journal_id": entry.id,
                                    },
                                )

                            st.success("Post-it enregistré ✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur d’enregistrement: {e}")

        st.divider()

        # --------------------------------------
        # SUIVI HEBDO (inchangé)
        # --------------------------------------
        st.markdown("### Suivi hebdo")

        wp = camp.get("weekly_plan") or []
        if not isinstance(wp, list) or not wp:
            st.info("Aucun suivi hebdo disponible.")
        else:
            for w in wp:
                if not isinstance(w, dict):
                    continue

                week_n = int(w.get("week") or 0) or 0
                obj_week = str(w.get("objective_week") or f"Semaine {week_n}").strip()

                pctw = _compute_week_completion(w)
                with st.expander(
                    f"Semaine {week_n} — {obj_week or 'Objectif non défini'} — {pctw:.0f}%",
                    expanded=(week_n == current_week),
                ):
                    st.markdown("**Objectif de la semaine**")
                    if obj_week:
                        st.write(obj_week)
                    else:
                        st.warning("Objectif non défini.")

                    st.divider()
                    st.markdown("**Actions (coach → toi)**")

                    actions = w.get("actions") or []
                    if not isinstance(actions, list) or not actions:
                        st.caption("Pas d’actions pré-remplies pour l’instant.")
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
                            new_status = st.radio(
                                " ",
                                options=keys,
                                index=idxs,
                                format_func=lambda k: ACTION_LABEL.get(k, k),
                                key=f"learner_action_{camp.get('id')}_{week_n}_{ai}",
                                horizontal=True,
                                label_visibility="collapsed",
                            )
                            a["status"] = new_status

                    st.divider()
                    st.markdown("**Ton commentaire (verbatim)**")
                    comment = st.text_area(
                        " ",
                        value=str(w.get("learner_comment") or ""),
                        key=f"learner_comment_{camp.get('id')}_{week_n}",
                        height=90,
                        placeholder="Ex: j’ai fait l’action 1, pas eu le temps pour l’action 2.",
                        label_visibility="collapsed",
                    )

                    coach_comment = str(w.get("coach_comment") or "").strip()
                    if coach_comment:
                        st.markdown("**Retour coach**")
                        st.info(coach_comment)

                    if st.button(
                        "💾 Enregistrer mon update",
                        key=f"save_learner_week_{camp.get('id')}_{week_n}",
                        use_container_width=True,
                    ):
                        now = now_iso()
                        w["actions"] = actions
                        w["learner_comment"] = comment
                        w["updated_at"] = now
                        camp["updated_at"] = now

                        campaigns = _upsert_campaign(campaigns, camp)
                        save_campaigns(campaigns)

                        cid = str(camp.get("id") or "").strip()
                        coach_email = str(camp.get("coach_email") or "").strip().lower() or "admin@everboarding.fr"
                        send_once(
                            event_key=f"LEARNER_UPDATE:{cid}:{week_n}:{now}",
                            event_type="LEARNER_UPDATE",
                            request_id=cid,
                            to_email=coach_email,
                            subject=f"[EVERSKILLS] Update semaine {week_n} ({cid})",
                            text_body=f"Update learner (semaine {week_n}).\n\nLearner: {learner_email}\n\n{comment}",
                            meta={"camp_id": cid, "week": week_n, "learner_email": learner_email},
                        )

                        st.success("OK ✅")
                        st.rerun()

        st.divider()
        _journal_history_block(learner_email)
