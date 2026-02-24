# everskills/ui/sidebar.py
from __future__ import annotations

import base64
from textwrap import dedent
from typing import Any, Dict, Optional, Tuple

import streamlit as st


def _clamp_0_5(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        v = float(default)
    return max(0.0, min(5.0, v))


def _role_badge(role: str) -> Tuple[str, str]:
    r = (role or "").strip().lower()
    m = {
        "learner": ("LEARNER", "🎯"),
        "coach": ("COACH", "🧠"),
        "admin": ("ADMIN", "🛠️"),
        "super_admin": ("SA", "⭐"),
    }
    return m.get(r, (r.upper() or "USER", "👤"))


def _dot_color(score_int: int) -> str:
    # 1 orange, 2 orange/jaune, 3-4 jaune, 4-5 vert (4 jaune-vert, 5 vert)
    if score_int == 1:
        return "#F97316"  # orange
    if score_int == 2:
        return "#FACC15"  # jaune
    if score_int == 3:
        return "#EAB308"  # jaune soutenu
    if score_int == 4:
        return "#84CC16"  # jaune-vert
    if score_int == 5:
        return "#22C55E"  # vert
    return "rgba(0,0,0,0.12)"


def _render_bubbles(score_0_5: float) -> str:
    s = int(round(_clamp_0_5(score_0_5, 0.0)))
    parts = []
    for i in range(1, 6):
        if i <= s:
            parts.append(f'<span class="mb-dot" style="background:{_dot_color(i)};"></span>')
        else:
            parts.append('<span class="mb-dot mb-dot--empty"></span>')
    return f'<div class="mb-dots">{"".join(parts)}</div>'

def _render_moodboard(kpi: Dict[str, Any]) -> None:
    # Expected optional: mb_structure, mb_discipline, mb_progress, mb_feedback (0..5)
    # Fallbacks from progress/actions if missing.
    s_struct = kpi.get("mb_structure")
    s_disc = kpi.get("mb_discipline")
    s_prog = kpi.get("mb_progress")
    s_fb = kpi.get("mb_feedback")

    if s_prog is None:
        p = str(kpi.get("progress", "0%")).replace("%", "").strip()
        try:
            pct = float(p)
        except Exception:
            pct = 0.0
        s_prog = (pct / 100.0) * 5.0

    if s_disc is None:
        acts = str(kpi.get("actions", "0/0")).strip()
        done = 0.0
        total = 0.0
        if "/" in acts:
            a, b = acts.split("/", 1)
            try:
                done = float(a.strip())
                total = float(b.strip())
            except Exception:
                done, total = 0.0, 0.0
        ratio = (done / total) if total > 0 else 0.0
        s_disc = ratio * 5.0

    if s_struct is None:
        s_struct = 3.0
    if s_fb is None:
        s_fb = 3.0

    rows = [
        ("Structuration", _clamp_0_5(s_struct), "Plan clair et actionnable."),
        ("Discipline", _clamp_0_5(s_disc), "Régularité d’exécution."),
        ("Progrès", _clamp_0_5(s_prog), "Progrès mesurables."),
        ("Feedbacks", _clamp_0_5(s_fb), "Retours coach utiles."),
    ]

    html_rows = []
    for label, score, tip in rows:
        html_rows.append(
            f'<div class="mb-row" title="{tip}">'
            f'<div class="mb-label">{label}</div>'
            f"{_render_bubbles(score)}"
            f"</div>"
        )

    st.markdown(
        dedent(
            f"""
            <div class="mb-title">Mon Mood Board</div>
            <div class="mb-wrap">
              {''.join(html_rows)}
              <div class="mb-help">Survole un axe pour voir la définition</div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _render_indicators(kpi: Dict[str, Any]) -> None:
    st.markdown("<div class=\"sb-section-title\" style=\"text-align:center;\">Mes indicateurs</div>", unsafe_allow_html=True)

    # Parse numbers safely
    prog_raw = str(kpi.get("progress", "0%")).replace("%", "").strip()
    vel_raw = str(kpi.get("velocity", "+0%")).replace("%", "").strip()
    acts_raw = str(kpi.get("actions", "0/0")).strip()
    mood = str(kpi.get("mood", "🙂"))

    try:
        prog = float(prog_raw)
    except Exception:
        prog = 0.0

    try:
        vel = float(vel_raw.replace("+", "")) if vel_raw.startswith("+") else float(vel_raw)
    except Exception:
        vel = 0.0

    done, total = 0, 0
    if "/" in acts_raw:
        a, b = acts_raw.split("/", 1)
        try:
            done = int(float(a.strip()))
            total = int(float(b.strip()))
        except Exception:
            done, total = 0, 0

    c1, c2 = st.columns(2, gap="small")
    with c1:
        st.metric("Progression", f"{prog:.0f}%")
    with c2:
        st.metric("Vélocité", f"{vel:+.0f}%")

    c3, c4 = st.columns(2, gap="small")
    with c3:
        st.metric("Actions done", f"{done}/{total}")
    with c4:
        st.metric("Humeur", mood)


def render_sidebar(*, build_id: Optional[str] = None, build_date: Optional[str] = None) -> None:
    """
    Sidebar additive ONLY.
    - Does NOT hide Streamlit Pages nav.
    - Does NOT render custom navigation.
    """
    with st.sidebar:
        st.markdown(
            dedent(
                """
                <style>
                .sb-section-title{ margin-top:18px; 
  font-size: 15px;
  font-weight: 700;
  opacity: .85;
  margin: 4px 0 6px 0;
}

                /* Moodboard */
                .mb-title{
                  text-align:center;
                  font-weight:700;
                  opacity:0.80;
                  font-size:13px;
                  margin: 10px 0 10px 0;
                }
                .mb-wrap{ margin-top:32px; 
                  padding: 8px 8px 6px 8px;
                  border: 1px solid rgba(0,0,0,0.08);
                  border-radius: 12px;
                  background: rgba(0,0,0,0.015);
                }
                .mb-row{
                  display:flex;
                  align-items:center;
                  justify-content:space-between;
                  gap:10px;
                  margin: 8px 0;
                }
                .mb-label{
                  font-size:12px;
                  opacity:0.75;
                  white-space:nowrap;
                }
                .mb-dots{ display:flex; gap:6px; }
                .mb-dot{
                  width:10px; height:10px; border-radius:999px; display:inline-block;
                  background: rgba(0,0,0,0.18);
                }
                .mb-dot--empty{ background: rgba(0,0,0,0.12); }
                .mb-help{
                  font-size:11px; opacity:0.55; text-align:center; margin-top: 6px;
                }
                .sb-spacer{height:22px;}
.kpi-center-scope div[data-testid="stMetric"] { text-align: center !important; }
.kpi-center-scope div[data-testid="stMetricLabel"] { justify-content: center !important; }
.kpi-center-scope div[data-testid="stMetricValue"] { justify-content: center !important; }
.kpi-center-scope div[data-testid="stMetricDelta"] { justify-content: center !important; }
</style>
                """
            ).strip(),
            unsafe_allow_html=True,
        )

        if build_id and build_date:
            st.caption(f"version {build_id} – {build_date}")

        u = st.session_state.get("user") or {}
        if u:
            st.markdown('<div class="sb-section-title">Mon profil</div>', unsafe_allow_html=True)

            photo_bytes = st.session_state.get("PROFILE_PHOTO_BYTES")
            first = str(u.get("first_name") or "").strip()
            last = str(u.get("last_name") or "").strip()
            full = f"{first} {last}".strip()
            initials = (first[:1] + last[:1]).upper().strip() or "?"

            role_label, role_icon = _role_badge(str(u.get("role") or ""))

            # Profil (photo + nom dessous, centré)
            if isinstance(photo_bytes, (bytes, bytearray)) and len(photo_bytes) > 10:
                b64 = base64.b64encode(photo_bytes).decode("ascii")
                avatar = f'<img src="data:image/png;base64,{b64}" style="width:80px;height:80px;border-radius:999px;object-fit:cover;border:1px solid rgba(0,0,0,0.10);" />'
            else:
                avatar = f'<div style="width:80px;height:80px;border-radius:999px;display:flex;align-items:center;justify-content:center;border:1px solid rgba(0,0,0,0.10);background:rgba(0,0,0,0.03);font-weight:800;font-size:22px;">{initials}</div>'

            st.markdown(
                f"<div style='display:flex;flex-direction:column;align-items:center;gap:6px;margin-bottom:6px;'>{avatar}<div style='font-weight:700;font-size:14px;text-align:center;'>{full or (u.get('email') or '')}</div><div style='font-size:12px;opacity:.75;text-align:center;'>{role_icon} {role_label}</div></div>",
                unsafe_allow_html=True,
            )
            if u.get("email"):
                st.caption(u.get("email"))

            with st.expander("Changer la photo", expanded=False):
                up = st.file_uploader(
                    "Nouvelle photo",
                    type=["png", "jpg", "jpeg", "webp"],
                    accept_multiple_files=False,
                    key="profile_photo_uploader",
                    label_visibility="collapsed",
                )
                if up is not None:
                    try:
                        st.session_state["PROFILE_PHOTO_BYTES"] = up.getvalue()
                    except Exception:
                        st.session_state.pop("PROFILE_PHOTO_BYTES", None)

        # KPI / Moodboard (learner-space computes SIDEBAR_KPI)
        kpi = st.session_state.get("SIDEBAR_KPI")
        if isinstance(kpi, dict):
            _render_moodboard(kpi)
            st.markdown("<div class='sb-spacer'></div>", unsafe_allow_html=True)
            st.markdown("<div class='kpi-center-scope'>", unsafe_allow_html=True)

            _render_indicators(kpi)

            st.markdown("</div>", unsafe_allow_html=True)












