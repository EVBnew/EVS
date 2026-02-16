# app.py
from __future__ import annotations

BUILD_ID = "1.3"
BUILD_DATE = "6 février 2026"

import sys
from pathlib import Path
import uuid
import requests

import streamlit as st
import streamlit.components.v1 as components

# -----------------------------------------------------------------------------
# Repo root (used for safe page links)
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent


def safe_page_link(page_path: str, label: str, icon: str) -> None:
    """
    Prevent StreamlitPageNotFoundError if a page file does not exist in the repo.
    page_path examples:
      - "pages/11_learner_space.py"
      - "pages/10_coach_space.py"
    """
    try:
        if (REPO_ROOT / page_path).exists():
            st.page_link(page_path, label=label, icon=icon)
    except Exception:
        # Never crash sidebar
        pass


# -----------------------------------------------------------------------------
# Page config (MUST be first Streamlit call)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="EVERSKILLS",
    page_icon="assets/pwa/favicon-32.png",
    layout="wide",
)

# -----------------------------------------------------------------------------
# PWA-ish meta / icons (best-effort)
# -----------------------------------------------------------------------------
components.html(
    """
<script>
(function() {
  const addLink = (rel, href, sizes, type) => {
    const l = document.createElement('link');
    l.rel = rel; l.href = href;
    if (sizes) l.sizes = sizes;
    if (type) l.type = type;
    document.head.appendChild(l);
  };

  const addMeta = (name, content) => {
    const m = document.createElement('meta');
    m.name = name; m.content = content;
    document.head.appendChild(m);
  };

  addLink('apple-touch-icon',
    'https://raw.githubusercontent.com/EVBnew/EVS/main/assets/pwa/apple-touch-icon.png',
    '180x180'
  );

  addLink('icon',
    'https://raw.githubusercontent.com/EVBnew/EVS/main/assets/pwa/favicon-32.png',
    null,
    'image/png'
  );

  addMeta('theme-color', '#0B5FFF');
  addMeta('apple-mobile-web-app-capable', 'yes');
  addMeta('apple-mobile-web-app-status-bar-style', 'default');
  addMeta('apple-mobile-web-app-title', 'EVERSKILLS');
})();
</script>
""",
    height=0,
)

st.markdown('<link rel="manifest" href="/assets/pwa/manifest.json">', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Ensure repo root (EVERSKILLS/) is on PYTHONPATH
# -----------------------------------------------------------------------------
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from everskills.services.access import (  # noqa: E402
    ensure_demo_seed,
    authenticate,
    find_user,
    issue_session_token,
    load_user_from_session_token,
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
# Session bootstrap from URL token (back button / refresh safe)
# -----------------------------------------------------------------------------
qp = st.query_params
session_token = (qp.get("session") or "").strip()

if session_token and not st.session_state.get("user"):
    u = load_user_from_session_token(session_token)
    if u:
        st.session_state["user"] = u
        st.session_state["just_logged_in"] = False
    else:
        try:
            st.query_params.pop("session", None)
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Global CSS (single source of truth)
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
/* Hide Streamlit auto page nav (we use our own sidebar) */
section[data-testid="stSidebarNav"] { display: none; }

/* Layout */
.block-container { max-width: 1200px; padding-top: 2.2rem; }
div[data-testid="stTextInput"] input { border-radius: 10px; }

/* Make columns stretch (login & signup cards same height) */
div[data-testid="stHorizontalBlock"] { align-items: stretch; }
div[data-testid="column"] > div { height: 100%; }

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

/* Force filled Streamlit kinds */
button[kind="secondary"],
button[kind="secondary"]:hover,
button[kind="secondary"]:active {
  background: linear-gradient(180deg, #F7F8FA 0%, #E9EDF3 100%) !important;
  color: #1F2A37 !important;
  border: 1px solid rgba(156,163,175,0.55) !important;
}

button[kind="primary"],
button[kind="primary"]:hover,
button[kind="primary"]:active {
  background: linear-gradient(180deg, #2F80ED 0%, #1F6FE5 100%) !important;
  color: #FFFFFF !important;
  border: 1px solid rgba(31,111,229,0.40) !important;
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
    try:
        st.query_params.pop("session", None)
    except Exception:
        pass


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

    # Always available
    st.page_link("app.py", label="Welcome", icon="🏠")

    # Hidden-by-default pages: ONLY show if file exists
    # (avoid crashes if you renamed/removed them)
    safe_page_link("pages/01_organization.py", label="Organisation", icon="🏢")
    safe_page_link("pages/02_projects.py", label="Projets", icon="🗂️")
    safe_page_link("pages/03_training.py", label="Mes formations", icon="🎓")
    safe_page_link("pages/12_learner_program_chat.py", label="Learner program chat", icon="💬")

    r = _role()

    st.divider()
    st.caption("Espaces opérationnels")

    if r in ("learner", "super_admin"):
        safe_page_link("pages/11_learner_space.py", label="Learner Space", icon="🎯")
        # Canal Chat (learner)
        safe_page_link("pages/20_canal_chat.py", label="Canal Chat", icon="💬")
        # fallback if you still have the old filename
        safe_page_link("pages/20_canal_coach.py", label="Canal Chat", icon="💬")

    if r in ("coach", "admin", "super_admin"):
        safe_page_link("pages/10_coach_space.py", label="Coach Space", icon="🧠")
        # Canal Chat (coach)
        safe_page_link("pages/30_canal_chat_coach.py", label="Canal Chat (coach)", icon="💬")
        safe_page_link("pages/30_canal_coach_space.py", label="Canal Chat (coach)", icon="💬")

    # Admin (if present)
    if r in ("admin", "super_admin"):
        safe_page_link("pages/90_admin_approvals.py", label="Admin Space", icon="🛠️")

# -----------------------------------------------------------------------------
# WELCOME
# -----------------------------------------------------------------------------
if h1:
    h1("WELCOME")  # type: ignore
else:
    st.title("WELCOME")

user = st.session_state.get("user")
st.caption("Propulsé par EVERBOARDING · Upskilling Solutions")

# Hide sidebar on Welcome when not logged
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
        if st.button("➡️ Ouvrir mon espace", use_container_width=True, type="primary"):
            _route_user(user)
    with c2:
        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            _logout()
            st.rerun()
    st.stop()

# -----------------------------------------------------------------------------
# RESET PASSWORD (token flow)
# -----------------------------------------------------------------------------
def _reset_screen(token: str, email: str) -> None:
    st.subheader("Réinitialiser le mot de passe")

    with st.container(border=True):
        em = st.text_input("Email", value=email or "", disabled=bool(email))
        p1 = st.text_input("Nouveau mot de passe", type="password")
        p2 = st.text_input("Confirmer", type="password")

        ok_submit = st.button("Enregistrer", type="primary")
        if not ok_submit:
            return

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

        res = _call_apps_script("confirm_password_reset", {"email": em2, "token": token, "new_password": p1})
        if not res.get("ok"):
            st.error("Lien invalide ou expiré.")
            st.stop()

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

        u2 = authenticate(em2, p1)
        if not u2:
            st.success("Mot de passe mis à jour ✅")
            st.info("Reconnecte-toi depuis l'écran de connexion.")
            try:
                st.query_params.pop("reset_token", None)
                st.query_params.pop("email", None)
            except Exception:
                pass
            st.stop()

        st.session_state["user"] = u2
        st.session_state["just_logged_in"] = True
        st.query_params["session"] = issue_session_token(u2)

        try:
            st.query_params.pop("reset_token", None)
            st.query_params.pop("email", None)
        except Exception:
            pass

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

# --- LEFT: LOGIN
with col_login:
    st.subheader("Accès")
    with st.container(border=True):
        if st.session_state["auth_mode"] == "reset_request":
            st.markdown("### Mot de passe oublié")

            email_reset = st.text_input("Email", key="reset_email_input")

            if st.button("Envoyer le lien de réinitialisation", type="primary"):
                em = (email_reset or "").strip().lower()
                if not em or "@" not in em:
                    st.error("Email invalide.")
                    st.stop()
                _call_apps_script("request_password_reset", {"email": em})
                st.success("Si un compte existe pour cet email, tu recevras un message.")
                st.session_state["auth_mode"] = "login"
                st.rerun()

            if st.button("⬅️ Retour", type="secondary", use_container_width=True):
                st.session_state["auth_mode"] = "login"
                st.rerun()

        else:
            st.markdown("### Connexion")

            email = st.text_input("Email", key="login_email")
            password = st.text_input("Mot de passe", type="password", key="login_password")

            submitted = st.button("Connexion", type="secondary")

            if st.button("Mot de passe oublié ?", type="secondary", use_container_width=True):
                st.session_state["auth_mode"] = "reset_request"
                st.rerun()

            if submitted:
                u = authenticate((email or "").strip(), password or "")
                if not u:
                    st.error("Login échoué.")
                else:
                    st.session_state["user"] = u
                    st.session_state["just_logged_in"] = True
                    st.query_params["session"] = issue_session_token(u)
                    st.success("Login OK ✅")
                    st.rerun()

# --- RIGHT: SIGNUP
with col_signup:
    with st.container(border=True):
        st.markdown("### Créer un compte")
        st.caption("Si tu n’as pas encore de mot de passe, fais une demande. L’admin te donnera tes accès.")

        first_name = st.text_input("Prénom", key="signup_first_name")
        last_name = st.text_input("Nom", key="signup_last_name")
        new_email = st.text_input("Email", key="signup_email")

        create = st.button("Envoyer ma demande d’accès", type="primary")

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

            for k in ["signup_first_name", "signup_last_name", "signup_email"]:
                if k in st.session_state:
                    st.session_state[k] = ""
