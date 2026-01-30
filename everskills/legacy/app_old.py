import streamlit as st
from pathlib import Path
import json
from datetime import datetime

DATA_DIR = Path("data")
CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"


def ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CAMPAIGNS_FILE.exists():
        CAMPAIGNS_FILE.write_text(json.dumps({"campaigns": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_campaigns():
    ensure_storage()
    try:
        data = json.loads(CAMPAIGNS_FILE.read_text(encoding="utf-8"))
        if "campaigns" not in data or not isinstance(data["campaigns"], list):
            return {"campaigns": []}
        return data
    except Exception:
        return {"campaigns": []}


def stats(data):
    campaigns = data.get("campaigns", [])
    total = len(campaigns)
    active = sum(1 for c in campaigns if c.get("status") == "ACTIVE")
    closed = sum(1 for c in campaigns if c.get("status") == "CLOSED")
    draft = sum(1 for c in campaigns if c.get("status") == "DRAFT")
    return total, draft, active, closed


st.set_page_config(page_title="EVERSKILLS", layout="wide")

st.title("EVERSKILLS")
st.caption("MVP — Suivi post-formation coaché (Learner / Coach)")

data = load_campaigns()
total, draft, active, closed = stats(data)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Campagnes", total)
c2.metric("Draft", draft)
c3.metric("Actives", active)
c4.metric("Clôturées", closed)

st.divider()

st.subheader("Accès")
st.write("Choisis ton espace. L’accès se fait par email (MVP).")

colA, colB = st.columns(2)
with colA:
    st.page_link("learner_space.py", label="➡️ Learner Space", icon="🎯")
with colB:
    st.page_link("coach_space.py", label="➡️ Coach Space", icon="🧑‍🏫")

st.divider()

st.subheader("Dernières campagnes")
campaigns = data.get("campaigns", [])
campaigns_sorted = sorted(campaigns, key=lambda c: c.get("updated_at", ""), reverse=True)[:8]

if not campaigns_sorted:
    st.info("Aucune campagne pour l’instant.")
else:
    for c in campaigns_sorted:
        st.markdown(
            f"- **{c.get('title','(sans titre)')}** — {c.get('status','?')} "
            f"— learner: `{c.get('learner_email','?')}` — coach: `{c.get('coach_email','?')}` "
            f"— maj: {c.get('updated_at','?')}"
        )

st.caption(f"Dernière lecture: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
