from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from everskills.services.gsheet_access import get_gsheet_api
from everskills.services.passwords import generate_temp_password, hash_password_pbkdf2
from everskills.services.mailer import send_email



st.set_page_config(page_title="EVERSKILLS - Admin approvals", page_icon="✅", layout="wide")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    st.title("✅ Admin — Traiter les approvals")

    st.info(
        "Workflow :\n"
        "1) Admin met `status = approved` dans le Google Sheet (onglet 'New Users').\n"
        "2) Ici : clique 'Traiter les approvals' → email envoyé au learner + hash MDP écrit + flags mis à jour.\n"
    )

    api = get_gsheet_api()

    colA, colB = st.columns([1, 3])
    with colA:
        process = st.button("Traiter les approvals", type="primary")
    with colB:
        st.caption("Critère : status=approved ET password_sent != yes")

    res = api.list_users()
    if not res.ok:
        st.error(f"Impossible de lire le G-Sheet : {res.error}")
        st.json(res.data)
        return

    rows = res.data.get("rows", [])
    if not rows:
        st.warning("Aucune ligne.")
        return

    def norm(x) -> str:
        return str(x or "").strip()

    st.subheader("Demandes (vue brute)")
    st.dataframe(rows, use_container_width=True)

    to_process = []
    for r in rows:
        status = norm(r.get("status")).lower()
        sent = norm(r.get("password_sent")).lower()
        if status == "approved" and sent != "yes":
            to_process.append(r)

    st.subheader("À traiter")
    st.write(f"{len(to_process)} ligne(s)")

    if not to_process:
        st.success("Rien à faire.")
        return

    if not process:
        st.stop()

    processed = 0
    errors = []

    env = st.secrets.get("APP_ENV", "PROD")

    for r in to_process:
        email = norm(r.get("email")).lower()
        first_name = norm(r.get("first_name"))
        last_name = norm(r.get("last_name"))
        request_id = norm(r.get("request_id"))

        if not email or "@" not in email:
            errors.append({"email": email, "error": "Invalid email in row", "request_id": request_id})
            continue

        # 1) Generate temp password + hash
        temp_pwd = generate_temp_password()
        pwd_hash = hash_password_pbkdf2(temp_pwd)

        # 2) Update sheet: write hash + flags + activate
        upd = api.update_user(
            request_id=request_id,
            email=email,
            updates={
                "initial_password": pwd_hash,
                "password_sent": "yes",
                "sent_at": now_iso(),
                "status": "active",
            },
        )
        if not upd.ok:
            errors.append(
                {
                    "email": email,
                    "error": f"Sheet update failed: {upd.error}",
                    "details": upd.data,
                    "request_id": request_id,
                }
            )
            continue

        # 3) Send email to learner (transactionnel)
        subject = f"[EVERSKILLS] Accès validé ({env})"
        body = (
            f"Bonjour {first_name} {last_name},\n\n"
            "Ton accès à EVERSKILLS est validé.\n\n"
            f"Identifiant : {email}\n"
            f"Mot de passe temporaire : {temp_pwd}\n\n"
            "À la première connexion, tu pourras changer ton mot de passe.\n\n"
            "— EVERSKILLS\n"
        )

        mail_res = send_email(
            to_email=email,
            subject=subject,
            text_body=body,
            meta={"flow": "CR06", "request_id": request_id, "env": env},
        )

        if not mail_res.get("ok"):
            errors.append({"email": email, "error": "Email send failed", "details": mail_res, "request_id": request_id})
            continue

        processed += 1

    st.success(f"Traitement terminé : {processed} email(s) envoyés.")
    if errors:
        st.error(f"{len(errors)} erreur(s)")
        st.json(errors)


if __name__ == "__main__":
    main()
