# pages/99_logs.py
from __future__ import annotations

import json
from pathlib import Path
import streamlit as st

from everskills.services.guard import require_role

st.set_page_config(page_title="Logs â€” EVERSKILLS", layout="wide")

# ðŸ”’ rÃ©servÃ© admin/super_admin
require_role({"admin", "super_admin"})

LOG_PATH = Path("data/app_events.json")

st.title("ðŸ§¾ Logs applicatifs")
st.caption("Audit trail interne (indÃ©pendant des logs Streamlit Cloud).")

if not LOG_PATH.exists():
    st.warning("Aucun log pour lâ€™instant (data/app_events.json absent).")
    st.info("DÃ©clenche un Ã©vÃ©nement (ex: soumettre une demande) puis reviens ici.")
    st.stop()

raw = LOG_PATH.read_text(encoding="utf-8")
try:
    items = json.loads(raw) or []
except Exception:
    items = []

if not isinstance(items, list):
    st.error("Format invalide: le fichier nâ€™est pas une liste JSON.")
    st.code(raw[:2000])
    st.stop()

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    levels = sorted({(x.get("level") or "INFO") for x in items})
    level_filter = st.multiselect("Level", options=levels, default=levels)
with col2:
    types = sorted({(x.get("event_type") or "") for x in items})
    type_filter = st.multiselect("Event type", options=types, default=types)
with col3:
    contains = st.text_input("Contient (recherche texte)", value="")

filtered = []
needle = (contains or "").strip().lower()
for x in reversed(items):  # derniers en premier
    if level_filter and (x.get("level") or "INFO") not in level_filter:
        continue
    if type_filter and (x.get("event_type") or "") not in type_filter:
        continue
    if needle:
        blob = json.dumps(x, ensure_ascii=False).lower()
        if needle not in blob:
            continue
    filtered.append(x)

st.write(f"RÃ©sultats: **{len(filtered)}** / {len(items)}")

st.download_button(
    "â¬‡ï¸ TÃ©lÃ©charger app_events.json",
    data=raw.encode("utf-8"),
    file_name="app_events.json",
    mime="application/json",
    width="stretch",
)

st.divider()
st.json(filtered[:200])  # limite affichage
