from __future__ import annotations

from datetime import date, timedelta
import uuid

import streamlit as st

from everskills.services.access import require_login
from everskills.services.gsheet_programs import (
    list_programs,
    list_objectives,
    list_comments,
    add_comment,
    upsert_objective,
)
from everskills.services.guard import require_role


st.set_page_config(page_title="Learner — Programme & Coach", page_icon="💬", layout="wide")

# --- ROLE GUARD (anti accès direct URL)
require_role({"learner", "super_admin"})


def _norm(x) -> str:
    return str(x or "").strip()


def _week_start_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pick_active_program(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    for r in rows:
        if _norm(r.get("status")).lower() == "active":
            return r
    return rows[0]


def main() -> None:
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

    learner_email = _norm(user.get("email")).lower()
    first_name = _norm(user.get("first_name"))

    st.title("💬 Programme & échanges coach (GSheet)")
    st.caption(f"Connecté : {learner_email}")

    # --- Load programs for learner
    pr = list_programs(learner_email=learner_email)
    if not pr.ok:
        st.error(f"Erreur list_programs : {pr.error}")
        st.json(pr.data)
        st.stop()

    programs = pr.data.get("rows", []) or []
    if not programs:
        st.info("Aucun programme trouvé (demande au coach de t’assigner un programme).")
        st.stop()

    programs_sorted = sorted(
        programs,
        key=lambda r: (_norm(r.get("updated_at")) or _norm(r.get("created_at"))),
        reverse=True,
    )

    labels = [
        f"{_norm(p.get('title')) or 'Programme'} · {_norm(p.get('program_id'))} · {_norm(p.get('status'))}"
        for p in programs_sorted
    ]

    default_prog = _pick_active_program(programs_sorted)
    default_index = 0
    if default_prog:
        for i, p in enumerate(programs_sorted):
            if _norm(p.get("program_id")) == _norm(default_prog.get("program_id")):
                default_index = i
                break

    sel = st.selectbox(
        "📚 Mon programme",
        options=list(range(len(programs_sorted))),
        format_func=lambda i: labels[i],
        index=default_index,
    )
    program = programs_sorted[sel]

    org_id = _norm(program.get("org_id"))
    program_id = _norm(program.get("program_id"))
    st.subheader(_norm(program.get("title")) or "Programme")

    with st.expander("Voir programme (JSON)", expanded=False):
        st.code(_norm(program.get("program_json")), language="json")

    # --- Week objectives
    ws = _week_start_monday(date.today()).isoformat()

    st.markdown("### ✅ Objectifs de la semaine")
    orr = list_objectives(org_id=org_id, program_id=program_id, week_start=ws)
    if not orr.ok:
        st.error(f"Erreur list_objectives : {orr.error}")
        st.json(orr.data)
        st.stop()

    objectives = orr.data.get("rows", []) or []
    if not objectives:
        st.info("Aucun objectif pour cette semaine.")
    else:
        for o in objectives:
            oid = _norm(o.get("objective_id"))
            txt = _norm(o.get("objective_text"))
            status = _norm(o.get("status")).lower() or "todo"
            checked = status == "done"

            new_checked = st.checkbox(txt or f"Objectif {oid}", value=checked, key=f"obj_{oid}")
            if new_checked != checked:
                new_status = "done" if new_checked else "todo"
                up = upsert_objective(
                    org_id=org_id,
                    objective_id=oid,
                    program_id=program_id,
                    week_start=ws,
                    objective_text=txt,
                    status=new_status,
                )
                if up.ok:
                    st.success("Objectif mis à jour ✅")
                    st.rerun()
                else:
                    st.error(f"Erreur update objectif : {up.error}")
                    st.json(up.data)
                    st.stop()

    with st.expander("➕ Ajouter un objectif", expanded=False):
        with st.form("add_objective", clear_on_submit=True):
            obj_text = st.text_input("Objectif")
            submit_obj = st.form_submit_button("Ajouter")

        if submit_obj:
            if not obj_text.strip():
                st.warning("Objectif vide.")
            else:
                oid = f"obj-{uuid.uuid4().hex[:10]}"
                up = upsert_objective(
                    org_id=org_id,
                    objective_id=oid,
                    program_id=program_id,
                    week_start=ws,
                    objective_text=obj_text.strip(),
                    status="todo",
                )
                if up.ok:
                    st.success("Objectif ajouté ✅")
                    st.rerun()
                else:
                    st.error(f"Erreur création objectif : {up.error}")
                    st.json(up.data)

    # --- Comments thread
    st.markdown("### 💬 Messages coach")
    cr = list_comments(org_id=org_id, program_id=program_id)
    if not cr.ok:
        st.error(f"Erreur list_comments : {cr.error}")
        st.json(cr.data)
        st.stop()

    comments = cr.data.get("rows", []) or []
    comments_sorted = sorted(comments, key=lambda r: _norm(r.get("created_at")))

    if not comments_sorted:
        st.info("Aucun message pour le moment.")
    else:
        for c in comments_sorted[-50:]:
            role = _norm(c.get("author_role")).lower() or "?"
            tag = "🧠 Coach" if role != "learner" else "🎯 Moi"
            st.markdown(f"**{tag}** · {_norm(c.get('created_at'))}")
            st.write(_norm(c.get("message")))
            st.divider()

    with st.form("post_comment", clear_on_submit=True):
        message = st.text_area(
            "Nouveau message",
            height=120,
            placeholder=f"{first_name + ', ' if first_name else ''}écris ici…",
        )
        send = st.form_submit_button("Envoyer")

    if send:
        if not message.strip():
            st.warning("Message vide.")
        else:
            cid = f"cmt-{uuid.uuid4().hex[:10]}"
            a = add_comment(
                org_id=org_id,
                comment_id=cid,
                program_id=program_id,
                week_start=ws,
                author_role="learner",
                author_email=learner_email,
                message=message.strip(),
            )
            if a.ok:
                st.success("Message envoyé ✅")
                st.rerun()
            else:
                st.error(f"Erreur envoi : {a.error}")
                st.json(a.data)


if __name__ == "__main__":
    main()
