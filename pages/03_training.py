# pages/training.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from everskills.services.access import require_login

st.set_page_config(page_title="Training — EVERSKILLS", layout="wide")

user = st.session_state.get("user")
ok, msg = require_login(user)
if not ok:
    st.error(msg)
    st.info("Retourne sur Welcome (app) pour te connecter.")
    st.stop()

BASE_DIR = Path(__file__).resolve().parents[1]  # EVERSKILLS/
CATALOG_PATH = BASE_DIR / "data" / "training_catalog.json"

def _load_catalog() -> List[Dict[str, Any]]:
    if not CATALOG_PATH.exists():
        return []
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _seed_catalog_if_empty() -> None:
    if CATALOG_PATH.exists():
        return
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample = [
        {
            "title": "Prise de parole — Synthèse (PDF)",
            "description": "Support de formation : messages clés + structure.",
            "type": "url",
            "url": "https://everboarding.fr",
            "tag": "Soft skills",
        },
        {
            "title": "Management — Rituels hebdo",
            "description": "Checklist de rituels (1:1, feedback, priorisation).",
            "type": "url",
            "url": "https://everboarding.fr",
            "tag": "Management",
        },
    ]
    CATALOG_PATH.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")

_seed_catalog_if_empty()
catalog = _load_catalog()

st.markdown("# Training")
st.caption("Mini-LMS light (option pour les entreprises sans LMS).")

if not catalog:
    st.info("Catalogue vide.")
    st.stop()

cols = st.columns(3)
for i, item in enumerate(catalog):
    with cols[i % 3]:
        with st.container(border=True):
            st.markdown(f"### {item.get('title','(Sans titre)')}")
            st.caption(item.get("tag", ""))
            st.write(item.get("description", ""))

            url = item.get("url")
            if url:
                st.link_button("Ouvrir", url, use_container_width=True)
            else:
                st.button("Ouvrir", disabled=True, use_container_width=True)
