# pages/01_organization.py
from __future__ import annotations

from typing import Any, Dict, List
from pathlib import Path
import json
import streamlit as st

from everskills.services.access import (
    load_access,
    upsert_user,
    create_user,
    set_password,
    set_status,
    require_login,
    ADMIN_ROLES,
    ROLES,
)

st.set_page_config(page_title="Organization — EVERSKILLS", layout="wide")

user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

role = user["role"]

st.markdown("# Organization")
st.caption("People & accès (MVP).")

people: List[Dict[str, Any]] = load_access()

# Read-only for non-admin roles
is_admin = role in ADMIN_ROLES

left, right = st.columns([1.55, 1.0], gap="large")


def _norm(s: str) -> str:
    return (s or "").strip()


def _safe_email(s: str) -> str:
    return (s or "").strip().lower()


def _get_person(email: str) -> Dict[str, Any] | None:
    em = _safe_email(email)
    for p in people:
        if _safe_email(p.get("email", "")) == em:
            return p
    return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


with left:
    st.subheader("People")

    if not people:
        st.info("Aucun compte. (Normalement, 3 comptes de démo sont seedés au 1er lancement.)")
    else:
        rows = []
        for p in sorted(people, key=lambda x: str(x.get("email") or "")):
            rows.append(
                {
                    "email": p.get("email", ""),
                    "first_name": p.get("first_name", ""),
                    "last_name": p.get("last_name", ""),
                    "role": p.get("role", ""),
                    "status": p.get("status", ""),
                    "created_at": p.get("created_at", ""),
                    "updated_at": p.get("updated_at", ""),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Règles MVP")
    st.write("- Un user = 1 email + 1 rôle")
    st.write("- Les accès sont gérés ici (pas de self-signup).")
    st.write("- Mot de passe oublié : reset ici (pas d’email dans ce sprint).")

with right:
    st.subheader("Actions")

    if not is_admin:
        st.warning("Lecture seule : rôle admin/super_admin requis pour modifier les accès.")
        st.stop()

    emails = sorted([p.get("email", "") for p in people if p.get("email")])

    # -------------------------
    # Edit existing user identity (first/last name)
    # -------------------------
    st.markdown("#### ✏️ Edit prénom / nom (existant)")
    if not emails:
        st.info("Aucun user.")
    else:
        email_edit = st.selectbox("Utilisateur", options=emails, key="edit_user_email")
        p = _get_person(email_edit) or {}
        c1, c2 = st.columns(2)
        with c1:
            first_name = st.text_input("Prénom", value=str(p.get("first_name") or ""), key="edit_first_name")
        with c2:
            last_name = st.text_input("Nom", value=str(p.get("last_name") or ""), key="edit_last_name")

        if st.button("💾 Enregistrer identité", use_container_width=True):
            try:
                p2 = dict(p)
                p2["email"] = _safe_email(email_edit)
                p2["first_name"] = _norm(first_name)
                p2["last_name"] = _norm(last_name)
                # keep role/status/password_hash untouched
                upsert_user(p2)
                st.success("OK ✅")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()

    # -------------------------
    # Create user
    # -------------------------
    st.markdown("#### ➕ Créer un compte")
    with st.form("create_user_form", clear_on_submit=True):
        email = st.text_input("Email", placeholder="ex: prenom.nom@entreprise.com")
        c1, c2 = st.columns(2)
        with c1:
            first_name_new = st.text_input("Prénom", placeholder="ex: Valery")
        with c2:
            last_name_new = st.text_input("Nom", placeholder="ex: Nguyen")

        role_new = st.selectbox("Rôle", options=ROLES, index=0)
        temp_pwd = st.text_input("Mot de passe temporaire", type="password", placeholder="ex: demo1234")
        status = st.selectbox("Statut", options=["active", "inactive", "pending"], index=0)
        submitted = st.form_submit_button("Créer", use_container_width=True)

    if submitted:
        try:
            if not temp_pwd or len(temp_pwd) < 4:
                st.error("Mot de passe trop court.")
            else:
                create_user(
                    email=email,
                    role=role_new,
                    password=temp_pwd,
                    status=status,
                    created_by=user["email"],
                    first_name=first_name_new,
                    last_name=last_name_new,
                )
                st.success("Compte créé ✅")
                st.rerun()
        except Exception as e:
            st.error(str(e))

    st.divider()

    # -------------------------
    # Reset password
    # -------------------------
    st.markdown("#### 🔁 Reset mot de passe")
    if not emails:
        st.info("Aucun user.")
    else:
        email_sel = st.selectbox("Utilisateur", options=emails, key="reset_pwd_email")
        new_pwd = st.text_input("Nouveau mot de passe", type="password", placeholder="ex: demo1234", key="reset_pwd_value")
        if st.button("Reset password", use_container_width=True):
            try:
                if not new_pwd or len(new_pwd) < 4:
                    st.error("Mot de passe trop court.")
                else:
                    set_password(email_sel, new_pwd, actor=user["email"])
                    st.success("OK ✅")
                    st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()

    # -------------------------
    # Change status
    # -------------------------
    st.markdown("#### ✅ / ⛔ Activer / Désactiver")
    if emails:
        email_sel2 = st.selectbox("Utilisateur (statut)", options=emails, key="status_email")
        new_status = st.selectbox("Nouveau statut", options=["active", "inactive", "pending"], index=0, key="status_value")
        if st.button("Mettre à jour le statut", use_container_width=True):
            try:
                set_status(email_sel2, new_status, actor=user["email"])
                st.success("OK ✅")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()

    # -------------------------
    # Demo reset (data only)
    # -------------------------
    st.markdown("#### 🧹 Reset data démo (requests/campaigns/emails)")
    st.caption("Efface les données de test, sans toucher aux comptes (access.json).")

    if st.button("⚠️ Reset data", use_container_width=True):
        try:
            base_dir = Path(__file__).resolve().parents[1]  # EVERSKILLS/
            data_dir = base_dir / "data"
            files = [
                data_dir / "requests.json",
                data_dir / "campaigns.json",
                data_dir / "emails_outbox.json",
            ]
            for f in files:
                if f.name == "emails_outbox.json":
                    _write_json(f, [])
                else:
                    _write_json(f, [])
            st.success("Data reset ✅ (requests/campaigns/emails_outbox vidés)")
            st.rerun()
        except Exception as e:
            st.error(str(e))
