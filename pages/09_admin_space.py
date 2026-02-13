# pages/09_admin_space.py
from __future__ import annotations

from typing import Any, Dict, List
import re

import streamlit as st

from everskills.services.access import require_login
from everskills.services.storage import load_requests, save_requests, update_request, now_iso
from everskills.services.guard import require_role

# CR11: email events (idempotent)
from everskills.services.mail_send_once import send_once

st.set_page_config(page_title="Admin RH — EVERSKILLS", layout="wide")

# ----------------------------
# Auth
# ----------------------------
user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

# Admin RH (client) + Super Admin (plateforme) peuvent accéder
require_role({"admin", "super_admin"})

role = str(user.get("role") or "").strip()
if role not in ("admin", "super_admin"):
    st.warning("Accès réservé aux Admin RH / Super Admin.")
    st.stop()

actor_email = (user.get("email") or "").strip().lower()


# ----------------------------
# Helpers
# ----------------------------
def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _is_email(s: str) -> bool:
    s = (s or "").strip()
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s))


def _safe_requests() -> List[Dict[str, Any]]:
    reqs = load_requests() or []
    reqs = [r for r in reqs if isinstance(r, dict)]

    # soft migration: ensure fields exist
    changed = False
    for r in reqs:
        if "assigned_coach_email" not in r:
            r["assigned_coach_email"] = ""
            changed = True
        if "updated_at" not in r:
            r["updated_at"] = ""
            changed = True
        if "status" not in r:
            r["status"] = "submitted"
            changed = True

    if changed:
        save_requests(reqs)

    return reqs


def _sort_key_req(r: Dict[str, Any]) -> str:
    return str(r.get("ts") or r.get("created_at") or "")


def _label_req(r: Dict[str, Any]) -> str:
    rid = str(r.get("id") or "").strip()
    status = str(r.get("status") or "submitted").strip()
    learner = _norm_email(str(r.get("email") or ""))
    obj = str(r.get("objective") or "").strip()
    coach = _norm_email(str(r.get("assigned_coach_email") or ""))
    coach_part = coach if coach else "—"
    return f"{learner} — {status} — coach:{coach_part} — {rid} — {obj[:45]}"


# ----------------------------
# UI
# ----------------------------
st.title("📬 Admin RH Space")
st.caption("Demandes learner (#0) → assignation coach (#0,5) → suivi.")

reqs = _safe_requests()
reqs_sorted = sorted(reqs, key=_sort_key_req, reverse=True)

submitted = [r for r in reqs_sorted if str(r.get("status") or "") == "submitted"]
assigned = [r for r in reqs_sorted if str(r.get("status") or "") == "assigned"]
archived = [r for r in reqs_sorted if str(r.get("status") or "") == "archived"]

m1, m2, m3 = st.columns(3)
m1.metric("Submitted", len(submitted))
m2.metric("Assigned", len(assigned))
m3.metric("Archived", len(archived))

st.divider()

tabs = st.tabs(["📥 Submitted", "✅ Assigned", "🗃️ Archived"])


# ----------------------------
# TAB: Submitted
# ----------------------------
with tabs[0]:
    st.subheader("📥 Demandes à traiter")

    if not submitted:
        st.success("Rien à traiter ✅")
    else:
        options = [str(r.get("id") or "").strip() for r in submitted]
        labels = {str(r.get("id") or "").strip(): _label_req(r) for r in submitted}

        rid = st.selectbox(
            "Choisir une demande",
            options=options,
            format_func=lambda x: labels.get(x, x),
        )

        req = next((r for r in submitted if str(r.get("id") or "").strip() == rid), None)
        if not req:
            st.warning("Demande introuvable.")
        else:
            learner_email = _norm_email(str(req.get("email") or ""))
            objective = str(req.get("objective") or "").strip()
            context = str(req.get("context") or "").strip()
            weeks = int(req.get("weeks") or 3)

            with st.container(border=True):
                st.markdown("#### Détails demande")
                st.write(f"**ID :** `{rid}`")
                st.write(f"**Learner :** {learner_email}")
                st.write(f"**Objectif :** {objective}")
                st.write(f"**Durée :** {weeks} semaine(s)")
                if context:
                    st.write(f"**Contexte :** {context}")

            st.divider()
            st.markdown("### #0,5 — Assigner un coach")

            default_coach = _norm_email(str(req.get("assigned_coach_email") or ""))

            with st.form("assign_coach_form", clear_on_submit=False):
                coach_email = st.text_input(
                    "Email du coach",
                    value=default_coach,
                    placeholder="ex: coach@entreprise.com",
                )
                send_mail = st.checkbox("Envoyer l’email au coach", value=True)
                do_assign = st.form_submit_button("✅ Assigner")

            if do_assign:
                coach_email_n = _norm_email(coach_email)
                if not _is_email(coach_email_n):
                    st.error("Email coach invalide.")
                else:
                    now = now_iso()
                    update_request(
                        rid,
                        {
                            "assigned_coach_email": coach_email_n,
                            "status": "assigned",
                            "updated_at": now,
                        },
                    )

                    # Email #0,5 (idempotent)
                    if send_mail:
                        send_once(
                            event_key=f"COACH_ASSIGNED:{rid}",
                            event_type="COACH_ASSIGNED",
                            request_id=rid,
                            to_email=coach_email_n,
                            subject=f"[EVERSKILLS] Nouvelle demande assignée ({rid})",
                            text_body=(
                                "Une nouvelle demande learner t’a été assignée.\n\n"
                                f"Request: {rid}\n"
                                f"Learner: {learner_email}\n"
                                f"Objectif: {objective}\n"
                                f"Durée: {weeks} semaine(s)\n\n"
                                "Connecte-toi à EVERSKILLS → Coach Space → Demandes."
                            ),
                            meta={
                                "request_id": rid,
                                "learner_email": learner_email,
                                "assigned_by": actor_email,
                            },
                        )

                    st.success("Coach assigné ✅")
                    st.rerun()


# ----------------------------
# TAB: Assigned
# ----------------------------
with tabs[1]:
    st.subheader("✅ Demandes assignées")
    if not assigned:
        st.info("Aucune demande assignée.")
    else:
        for r in assigned[:40]:
            st.write(f"- {_label_req(r)}")


# ----------------------------
# TAB: Archived
# ----------------------------
with tabs[2]:
    st.subheader("🗃️ Demandes archivées")
    if not archived:
        st.info("Aucune demande archivée.")
    else:
        for r in archived[:40]:
            st.write(f"- {_label_req(r)}")
