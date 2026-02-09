# app.py
from __future__ import annotations

BUILD_ID = "1.3"
BUILD_DATE = "6 février 2026"

import sys
from pathlib import Path
import uuid
import requests

import streamlit as st

# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="WELCOME — EVERSKILLS", layout="wide")

# -----------------------------------------------------------------------------
# Ensure repo root (EVERSKILLS/) is on PYTHONPATH
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.access import (  # noqa: E402
    ensure_demo_seed,
    authenticate,
    find_user,
)
from everskills.services.passwords import hash_password_pbkdf2  # noqa: E402
from everskills.services.gsheet_access import get_gsheet_api  # noqa: E402
from everskills.services.mailer import send_email  # noqa: E402

# -----------------------------------------------------------------------------
# Seed demo users (DEV safe)
# -----------------------------------------------------------------------------
try:
    ensure_demo_seed()
except Exception:
    pass

# -----------------------------------------------------------------------------
# Global CSS (single source of truth)
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
section[data-testid="stSidebarNav"] { display: none; }
.block-container { max-width: 1200px; padding-top: 2.2rem; }
div[data-testid="stTextInput"] input { border-radius: 10px; }

/* Buttons (relief) */
div[data-testid="stButton"] > button,
div[data-testid="stFormSubmitButton"] > button {
  border-radius: 999px !important;
  padding: 0.55rem 1.2rem !important;
  min-height: 44px !important;
  font-weight: 600 !important;
  box-shadow: 0 2px 6px rgba(0,0,0,0.12) !important;
  transition: all 0.15s ease-in-out !important;
}
div[data-testid="stButton"] > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 10px rgba(0,0,0,0.18) !important;
}
div[data-testid="stButton"] > button:active,
div[data-testid="stFormSubmitButton"] > button:active {
  transform: translateY(0) !important;
  box-shadow: 0 2px 6px rgba(0,0,0,0.12) !important;
}

/* Primary (blue) — apply to BOTH form submit + regular buttons */
.evs-btn-primary div[data-testid="stFormSubmitButton"] > button,
.evs-btn-primary div[data-testid="stButton"] > button {
  background: linear-gradient(180deg, #2F80ED 0%, #1F6FE5 100%) !important;
  color: #FFFFFF !important;
  border: 1px solid rgba(31,111,229,0.40) !important;
}

/* Secondary (grey) — apply to BOTH form submit + regular buttons */
.evs-btn-secondary div[data-testid="stFormSubmitButton"] > button,
.evs-btn-secondary div[data-testid="stButton"] > button {
  background: linear-gradient(180deg, #F7F8FA 0%, #E9EDF3 100%) !important;
  color: #1F2A37 !important;
  border: 1px solid rgba(156,163,175,0.55) !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Optional brand
# -----------------------------------------------------------------------------
try:
    from utils.brand import apply_brand, h1  # type: ignore

    apply_brand()
except Exception:
    h1 = None  # type: ignore

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _logout() -> None:
    for k in ["user", "just_logged_in", "auth_mode"]:
        if k in st.session_state:
            del st.session_state[k]


def _route_user(u: dict) -> None:
    role = (u.get("role") or "").strip()
    if role == "learner":
        st.switch_page("pages/11_learner_space.py")
    else:
        st.switch_page("pages/10_coach_space.py")


def _role() -> str:
    u = st.session_state.get("user") or {}
    return (u.get("role") or "").strip()


def _call_apps_script(action: str, payload: dict) -> dict:
    """
    Minimal caller for CR08 without changing other modules.
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
        r = requests.post(str(url), json=body, timeout=20)
        j = r.json()
        return j if isinstance(j, dict) else {"ok": False, "error": "Non-JSON response", "data": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}


# -----------------------------------------------------------------------------
# Sidebar (role-based)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## EVERSKILLS")
    st.caption(f"EVERSKILLS · version {BUILD_ID} – {BUILD_DATE}")
    st.divider()

    st.page_link("app.py", label="Welcome", icon="🏠")
    st.page_link("pages/03_training.py", label="Mes formations", icon="🎓")

    r = _role()
    if r in ("coach", "admin", "super_admin"):
        st.page_link("pages/01_organization.py", label="Organization", icon="🏢")

    st.divider()
    st.caption("Espaces opérationnels")

    if r == "learner":
        st.page_link("pages/11_learner_space.py", label="Learner Space", icon="🎯")
    if r in ("coach", "admin", "super_admin"):
        st.page_link("pages/10_coach_space.py", label="Coach Space", icon="🧠")

# -----------------------------------------------------------------------------
# WELCOME
# -----------------------------------------------------------------------------
if h1:
    h1("WELCOME")  # type: ignore
else:
    st.title("VOTRE LOGO")

st.caption("Propulsé par EVERBOARDING · Upskilling Solutions")

user = st.session_state.get("user")

# ✅ FIX: Hide sidebar on Welcome when not logged (real CSS injection)
if not user:
    st.markdown(
        """
<style>
section[data-testid="stSidebar"] { display: none !important; }
</style>
""",
        unsafe_allow_html=True,
    )

# Token in URL -> reset screen
qp = st.query_params
reset_token = (qp.get("reset_token") or "").strip()
reset_email = (qp.get("email") or "").strip().lower()

# Immediate redirect after login
if user and st.session_state.get("just_logged_in") is True:
    st.session_state["just_logged_in"] = False
    _route_user(user)

# Already logged
if user:
    st.success(f"Connecté : {user.get('email')} — rôle: {user.get('role')}")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("➡️ Ouvrir mon espace", use_container_width=True):
            _route_user(user)
    with c2:
        if st.button("🚪 Logout", use_container_width=True):
            _logout()
            st.rerun()
    st.stop()

# -----------------------------------------------------------------------------
# RESET PASSWORD (token flow)
# -----------------------------------------------------------------------------
def _reset_screen(token: str, email: str) -> None:
    st.subheader("Réinitialiser le mot de passe")
    with st.container(border=True):
        with st.form("reset_form"):
            em = st.text_input("Email", value=email or "", disabled=bool(email))
            p1 = st.text_input("Nouveau mot de passe", type="password")
            p2 = st.text_input("Confirmer", type="password")
            st.markdown('<div class="evs-btn-primary">', unsafe_allow_html=True)
            ok = st.form_submit_button("Enregistrer")
            st.markdown("</div>", unsafe_allow_html=True)

        if ok:
            em2 = (em or "").strip().lower()
            if not em2 or "@" not in em2:
                st.error("Email invalide.")
                st.stop()
            if not p1 or len(p1) < 10:
                st.error("Mot de passe trop court (min 10 caractères).")
                st.stop()
            if p1 != p2:
                st.error("Les mots de passe ne correspondent pas.")
                st.stop()

            # 1) validate token via Apps Script
            res = _call_apps_script("confirm_password_reset", {"email": em2, "token": token, "new_password": p1})
            if not res.get("ok"):
                st.error("Lien invalide ou expiré.")
                st.stop()

            # 2) write new password hash into GSheet via wrapper
            new_hash = hash_password_pbkdf2(p1)
            api = get_gsheet_api()

            updates = {
                "initial_password": new_hash,
                "reset_token_hash": "",
                "reset_expires_at": "",
                "reset_requested_at": "",
            }

            try:
                upd = api.update_user(email=em2, request_id="", updates=updates)  # type: ignore
            except TypeError:
                upd = api.update_user(email=em2, updates=updates)  # type: ignore

            if not getattr(upd, "ok", False):
                st.error("Mot de passe non enregistré (update_user).")
                st.caption(str(getattr(upd, "error", "")))
                st.stop()

            # 3) login with new password
            u = authenticate(em2, p1)
            if not u:
                st.success("Mot de passe mis à jour ✅")
                st.info("Reconnecte-toi depuis l'écran de connexion.")
                st.stop()

            st.session_state["user"] = u
            st.session_state["just_logged_in"] = True

            st.query_params.clear()
            st.rerun()


if reset_token:
    _reset_screen(reset_token, reset_email)
    st.stop()

# -----------------------------------------------------------------------------
# LOGIN / SIGNUP
# -----------------------------------------------------------------------------
if "auth_mode" not in st.session_state:
    st.session_state["auth_mode"] = "login"  # or "reset_request"

col_login, col_signup = st.columns([1.15, 1.0], gap="large")

with col_login:
    st.subheader("Accès")
    with st.container(border=True):
        if st.session_state["auth_mode"] == "reset_request":
            st.markdown("### Mot de passe oublié")

            with st.form("reset_request_form", clear_on_submit=True):
                email = st.text_input("Email")
                st.markdown('<div class="evs-btn-primary">', unsafe_allow_html=True)
                sent = st.form_submit_button("Envoyer le lien de réinitialisation")
                st.markdown("</div>", unsafe_allow_html=True)

            if sent:
                em = (email or "").strip().lower()
                if not em or "@" not in em:
                    st.error("Email invalide.")
                    st.stop()

                # IMPORTANT: Apps Script now uses APP_BASE_URL from Script Properties (safe),
                # so no need to send app_base_url in payload.
                _call_apps_script("request_password_reset", {"email": em})

                st.success("Si un compte existe pour cet email, tu recevras un message.")
                st.session_state["auth_mode"] = "login"

            # ✅ left side button in BLUE
            st.markdown('<div class="evs-btn-primary">', unsafe_allow_html=True)
            back = st.button("⬅️ Retour", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            if back:
                st.session_state["auth_mode"] = "login"
                st.rerun()

        else:
            st.markdown("### Connexion")
            with st.form("login_form"):
                email = st.text_input("Email")
                password = st.text_input("Mot de passe", type="password")
                st.markdown('<div class="evs-btn-primary">', unsafe_allow_html=True)
                submitted = st.form_submit_button("Connexion")
                st.markdown("</div>", unsafe_allow_html=True)

            # ✅ left side button in BLUE
            st.markdown('<div class="evs-btn-primary">', unsafe_allow_html=True)
            forgot = st.button("Mot de passe oublié ?", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            if forgot:
                st.session_state["auth_mode"] = "reset_request"
                st.rerun()

            if submitted:
                u = authenticate((email or "").strip(), password or "")
                if not u:
                    st.error("Login échoué.")
                else:
                    st.session_state["user"] = u
                    st.session_state["just_logged_in"] = True
                    st.success("Login OK ✅")
                    st.rerun()

with col_signup:
    with st.container(border=True):
        st.markdown("### Créer un compte")
        st.caption("Si tu n’as pas encore de mot de passe, fais une demande. L’admin te donnera tes accès.")

        with st.form("signup_form", clear_on_submit=True):
            first_name = st.text_input("Prénom")
            last_name = st.text_input("Nom")
            new_email = st.text_input("Email")

            # ✅ right side submit stays GREY
            st.markdown('<div class="evs-btn-secondary">', unsafe_allow_html=True)
            create = st.form_submit_button("Envoyer ma demande d’accès")
            st.markdown("</div>", unsafe_allow_html=True)

        if create:
            fn = (first_name or "").strip()
            ln = (last_name or "").strip()
            em = (new_email or "").strip().lower()

            if not fn or not ln or not em:
                st.error("Tous les champs sont obligatoires.")
                st.stop()
            if "@" not in em:
                st.error("Email invalide.")
                st.stop()

            if find_user(em):
                st.info("Un compte existe déjà pour cet email. Essaie de te connecter.")
                st.stop()

            api = get_gsheet_api()
            request_id = f"app-{uuid.uuid4().hex[:12]}"
            res = api.create_user(
                email=em,
                first_name=fn,
                last_name=ln,
                role="learner",
                status="pending",
                initial_password="",
                source="streamlit",
                request_id=request_id,
            )

            if not res.ok:
                st.error(f"Demande non envoyée : {res.error}")
                st.json(res.data)
                st.stop()

            admin_email = str(st.secrets.get("ACCESS_ADMIN_EMAIL") or "admin@everboarding.fr")
            send_email(
                to_email=admin_email,
                subject="[EVERSKILLS] Nouvelle demande d’accès",
                text_body=f"Nouvelle demande:\n{fn} {ln}\n{em}\nrequest_id={request_id}\n",
                meta={"flow": "CR06", "type": "admin_notify", "request_id": request_id},
            )

            st.success("Demande envoyée ✅")
            st.info(f"Tu recevras tes identifiants par email après validation par l’admin ({admin_email}).")
