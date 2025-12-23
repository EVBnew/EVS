# Import du thÃ¨me EVB (robuste selon l'endroit d'oÃ¹ tu lances Streamlit)
try:
    from utils.brand import apply_brand, h1, h2, h3
except ModuleNotFoundError:
    import sys, os
    sys.path.append(os.path.join(os.path.dirname(__file__), "utils"))
    from brand import apply_brand, h1, h2, h3

# dashboard_apprenant.py â€” EVERBOARDING (apprenant) â€” Version end-user centric
# CorrigÃ© pour lire la bonne source publiÃ©e (data/public/exercices.json) + fallback legacy
# - Accueil personnalisÃ© + "Reprendre lÃ  oÃ¹ tu tâ€™es arrÃªtÃ©"
# - Progression par thÃ¨me (barre), objectifs jour/semaine (simples)
# - CTA plus clairs, cÃ©lÃ©brations, fin de thÃ¨me => bascule Plan dâ€™action
# - Conserve : rejouer, Ã©val IA/locale, fuzzy pour texte Ã  trous, persistance JSON

import os, json, re, unicodedata, difflib
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import streamlit as st

# =========================
# Config & brand
# =========================
st.set_page_config(page_title="Ta progression EVERBOARDING", layout="wide")
apply_brand()

st.sidebar.caption(f"CWD: {Path.cwd()}")
st.sidebar.caption("Theme EVB chargÃ© âœ”")
h1("Dashboard Apprenant")
st.title("ðŸŽ“ Ta progression EVERBOARDING")

# =========================
# Chemins (nouveau format + fallback legacy)
# =========================
DATA_DIR = Path("data")
PUBLIC_JSON = DATA_DIR / "public" / "exercices.json"        # <- source publiÃ©e par l'admin
LEGACY_JSON = DATA_DIR / "exercices_valides.json"           # <- compat ancienne version

MODE_PATH = DATA_DIR / "mode.json"
PROGRESS_PATH = DATA_DIR / "user_progress.json"
ACTION_PLANS_PATH = DATA_DIR / "action_plans.json"
PLANNING_PATH = DATA_DIR / "planning.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Mode (cloud/local) & OpenAI client (optionnel)
# =========================
try:
    mode = json.loads(MODE_PATH.read_text(encoding="utf-8")).get("mode", "local")
except Exception:
    mode = "local"

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

def get_openai_client():
    if mode != "cloud":
        return None
    api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

client = get_openai_client()

# =========================
# Helpers gÃ©nÃ©raux
# =========================
def safe_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def to01(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if 0.0 <= v <= 1.0: return v
    if 2.0 <= v <= 5.0: return max(0.0, min(1.0, (v - 2.0) / 3.0))
    return max(0.0, min(1.0, v))

def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def fuzzy_equal(a: str, b: str, tolerance: float = 0.2) -> bool:
    a, b = norm(a), norm(b)
    if not a or not b: return False
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return (1.0 - ratio) <= tolerance

def today_local() -> date:
    return datetime.now().date()

# =========================
# Chargement des exercices (nouvelle logique)
# =========================
def _group_by_theme(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for ex in items:
        th = str(ex.get("theme", "Sans thÃ¨me")).strip() or "Sans thÃ¨me"
        out.setdefault(th, []).append(ex)
    return out

def load_exercises() -> Tuple[Dict[str, List[Dict[str, Any]]], str, Optional[str], Optional[str]]:
    """
    Retourne:
    - dict {theme: [exo, ...]}
    - label_source (affichage)
    - rid (si prÃ©sent)
    - str_date_modif (si dispo)
    Cherche d'abord data/public/exercices.json (wrapper {exercices:[...]})
    puis fallback data/exercices_valides.json (legacy).
    """
    # 1) Public JSON (format wrapper)
    if PUBLIC_JSON.exists():
        try:
            raw = json.loads(PUBLIC_JSON.read_text(encoding="utf-8"))
            rid = raw.get("rid")
            # wrapper
            if isinstance(raw, dict) and isinstance(raw.get("exercices"), list):
                items = raw["exercices"]
                data = _group_by_theme(items)
            else:
                # on tente de normaliser un dict/ list quelconque
                items = []
                if isinstance(raw, dict):
                    # ex: dict mapping theme -> list
                    # si on trouve une clÃ© non-liste "rid"/"generated_at", on l'ignore
                    if "exercices" in raw and isinstance(raw["exercices"], list):
                        items = raw["exercices"]
                    else:
                        # dict libre => aplatir valeurs liste
                        for v in raw.values():
                            if isinstance(v, list):
                                items.extend([e for e in v if isinstance(e, dict)])
                elif isinstance(raw, list):
                    items = [e for e in raw if isinstance(e, dict)]
                data = _group_by_theme(items)

            mtime = datetime.fromtimestamp(PUBLIC_JSON.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            return data, f"Public JSON (data/public/exercices.json)", rid, mtime
        except Exception as e:
            st.warning(f"âš ï¸ Impossible de lire {PUBLIC_JSON}: {e}")

    # 2) Legacy JSON (liste plate ou dict mapping)
    if LEGACY_JSON.exists():
        try:
            raw = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
            items = []
            if isinstance(raw, list):
                items = [e for e in raw if isinstance(e, dict)]
            elif isinstance(raw, dict):
                # dict thÃ¨me -> liste d'exos
                for v in raw.values():
                    if isinstance(v, list):
                        items.extend([e for e in v if isinstance(e, dict)])
            data = _group_by_theme(items)
            mtime = datetime.fromtimestamp(LEGACY_JSON.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            return data, f"Legacy JSON (data/exercices_valides.json)", None, mtime
        except Exception as e:
            st.warning(f"âš ï¸ Impossible de lire {LEGACY_JSON}: {e}")

    return {}, "No source", None, None

DATA, source_label, rid, modified = load_exercises()
THEMES = sorted(DATA.keys())

# =========================
# Persistance : progress & plans
# =========================
def load_json(path: Path, default: Any):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def save_json(path: Path, payload: Any):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))

def load_progress() -> Dict[str, Any]: return load_json(PROGRESS_PATH, {})
def save_progress(db: Dict[str, Any]): save_json(PROGRESS_PATH, db)

def log_attempt(user: str, theme: str, exo: Dict[str, Any], score01: float,
                level: str = "", feedback: str = ""):
    db = load_progress()
    bag = db.setdefault(user, {})
    theme_map = bag.setdefault(theme, {})
    exo_id = exo.get("id") or f"{exo.get('type','exo')}_{abs(hash(exo.get('question','')))%10_000_000}"
    node = theme_map.setdefault(exo_id, {"type": exo.get("type",""), "history": []})
    node["type"] = exo.get("type", node.get("type",""))
    entry = {
        "score": round(score01, 4),
        "level": level,
        "feedback": feedback,
        "timestamp": safe_now_iso(),
        "type": exo.get("type",""),
        "question": exo.get("question",""),
    }
    node["history"].append(entry)
    node["latest"] = entry
    save_progress(db)

def load_plans() -> Dict[str, Any]: return load_json(ACTION_PLANS_PATH, {})
def save_plans(db: Dict[str, Any]): save_json(ACTION_PLANS_PATH, db)

def get_plan_node(db: Dict[str, Any], user: str, theme: str) -> Dict[str, Any]:
    return db.setdefault(user, {}).setdefault(theme, {"latest": {}, "history": []})

# =========================
# Planification RH (contexte)
# =========================
def load_planning() -> Dict[str, Any]:
    p = load_json(PLANNING_PATH, {})
    if not isinstance(p, dict): return {"enabled": False}
    return {
        "enabled": bool(p.get("enabled")),
        "start_date": p.get("start_date"),
        "weeks": int(p.get("weeks", 3)),
    }

def parse_date_iso(s: str) -> Optional[date]:
    try:
        y, m, d = map(int, str(s).split("-"))
        return date(y, m, d)
    except Exception:
        return None

# =========================
# Ã‰valuation ouverte (exercices)
# =========================
CANON_LABELS = ["Excellent", "Câ€™est vraiment encourageant", "Tu es sur la bonne voie", "Argh, Ã  renforcer"]

def label_from_score(score25: int) -> str:
    return {
        5: CANON_LABELS[0], 4: CANON_LABELS[1], 3: CANON_LABELS[2], 2: CANON_LABELS[3],
    }.get(max(2, min(5, int(score25))), CANON_LABELS[2])

def heuristic_open_eval(answer: str, question: str, expected: str = None) -> Dict[str, Any]:
    a = (answer or "").strip()
    if not a:
        return {
            "score": 2, "label": label_from_score(2),
            "feedback": "RÃ©ponse trÃ¨s courte ou absente.",
            "suggestions": ["Contexte â†’ Actions â†’ RÃ©sultats", "Ajoute un exemple + un indicateur."],
            "improved": "Ex. Â« Contexte : X. Actions : A,B,C. RÃ©sultats visÃ©s : +15% en 2 mois. Â»",
        }
    tokens = re.findall(r"\w+", a.lower()); uniq = len(set(tokens)); long = len(a)
    s = 5 if (long > 350 and uniq > 60) else 4 if (long > 200 and uniq > 40) else 3 if (long > 80 and uniq > 20) else 2
    return {
        "score": s, "label": label_from_score(s),
        "feedback": "Bonne base ; ajoute des mÃ©triques." if s <= 3 else "Solide ; prÃ©cise des mÃ©triques.",
        "suggestions": ["Structure ta rÃ©ponse", "1 exemple concret + 1 KPI"],
        "improved": "Ex. Â« Contexteâ€¦ Actionsâ€¦ KPI & dÃ©lai. Â»",
    }

def gpt_open_eval(answer: str, question: str, expected: str = None) -> Dict[str, Any]:
    if not client: return heuristic_open_eval(answer, question, expected)
    try:
        prompt = f"""
Ã‰value en franÃ§ais cette question ouverte. JSON STRICT :
{{
  "score": 2..5,
  "label": "Excellent" | "Câ€™est vraiment encourageant" | "Tu es sur la bonne voie" | "Argh, Ã  renforcer",
  "feedback": "1â€“2 phrases",
  "suggestions": ["..",".."],
  "improved": "rÃ©ponse courte amÃ©liorÃ©e"
}}
Question : {question}
Ã‰lÃ©ments attendus : {expected or "N/A"}
RÃ©ponse : {answer}
"""
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Tu es un Ã©valuateur pÃ©dagogique bienveillant et prÃ©cis."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        data = json.loads(text)
        s = max(2, min(5, int(data.get("score", 3))))
        return {
            "score": s,
            "label": data.get("label") or label_from_score(s),
            "feedback": data.get("feedback") or "",
            "suggestions": (data.get("suggestions") or [])[:3],
            "improved": data.get("improved") or "",
        }
    except Exception:
        return heuristic_open_eval(answer, question, expected)

# =========================
# Session state
# =========================
def init_state():
    st.session_state.setdefault("current_index", 0)
    st.session_state.setdefault("scores", {})
    st.session_state.setdefault("validated", {})
    st.session_state.setdefault("open_evals", {})
    st.session_state.setdefault("pending_retry", None)
    st.session_state.setdefault("plan_eval_cache", {})

init_state()

# =========================
# Bandeau source
# =========================
src_bits = [source_label]
if rid: src_bits.append(f"RID: {rid}")
if modified: src_bits.append(f"ModifiÃ©: {modified}")
st.caption(" | ".join(src_bits))

# =========================
# Sidebar : identitÃ©, thÃ¨me, mode
# =========================
with st.sidebar:
    st.header("ðŸªª Identifiant")
    user_email = st.text_input("Votre e-mail (ou pseudo)", value="demo.user@everboarding.fr").strip()
    st.caption("UtilisÃ© pour lâ€™historique (dashboard & plans dâ€™action).")
    st.divider()
    st.header("ðŸ“š ThÃ¨me")
    if THEMES:
        selected_theme = st.selectbox("ThÃ¨me", THEMES, index=0)
    else:
        selected_theme = st.text_input("ThÃ¨me (si aucun exercice)", value="GÃ©nÃ©rique").strip()
    st.divider()
    st.header("âš™ï¸ Mode")
    st.caption(f"Ã‰valuation IA : **{('Cloud GPT-4o' if client else 'Locale (heuristique)')}**")
    st.caption(f"Mode global : **{mode.upper()}**")

# =========================
# Accueil end-user : reprise + contexte RH + objectifs
# =========================
colA, colB, colC = st.columns([2,2,3])

with colA:
    st.subheader(f"ðŸ‘‹ Bienvenue{f' {user_email}' if user_email else ''}")
    total_for_theme = len([ex for ex in (DATA.get(selected_theme, []) if DATA else []) if isinstance(ex, dict) and ex.get("question")])
    first_unvalidated = None
    for i in range(total_for_theme):
        if not st.session_state.validated.get((selected_theme, i)):
            first_unvalidated = i; break
    if first_unvalidated is not None:
        if st.button("â–¶ï¸ Reprendre lÃ  oÃ¹ tu tâ€™es arrÃªtÃ©"):
            st.session_state.current_index = first_unvalidated
            st.experimental_rerun()

with colB:
    db = load_progress()
    user_log = (db.get(user_email, {}) if user_email else {})
    today = today_local()
    week_start = today - timedelta(days=today.weekday())
    done_today = 0; done_week = 0
    for theme, exmap in user_log.items():
        if not isinstance(exmap, dict): continue
        for _, node in exmap.items():
            for att in (node.get("history") or []):
                try:
                    dt = datetime.fromisoformat(str(att.get("timestamp","")).replace("Z","+00:00")).date()
                except Exception:
                    continue
                if dt == today: done_today += 1
                if week_start <= dt <= week_start + timedelta(days=6): done_week += 1
    DAILY_GOAL = 3; WEEKLY_GOAL = 10
    st.metric("ðŸ”¥ Exercices aujourdâ€™hui", f"{done_today}/{DAILY_GOAL}")
    st.metric("ðŸ“… Cette semaine", f"{done_week}/{WEEKLY_GOAL}")

with colC:
    plan_cfg = load_planning()
    if plan_cfg.get("enabled") and plan_cfg.get("start_date"):
        sd = parse_date_iso(plan_cfg["start_date"])
        if sd:
            ed = sd + timedelta(days=plan_cfg.get("weeks", 3) * 7 - 1)
            days_left = (ed - today_local()).days
            st.subheader("ðŸ—“ï¸ FenÃªtre RH")
            st.caption(f"Du **{sd.isoformat()}** au **{ed.isoformat()}** ({plan_cfg['weeks']} sem.)")
            st.caption(f"â³ Jours restants : **{max(0, days_left)}**")

st.divider()

# =========================
# Onglets
# =========================
tab_exo, tab_plan = st.tabs(["ðŸ“ Exercices", "ðŸ—ºï¸ Plan dâ€™action (SMART)"])

# =========================
# Onglet â€” Exercices
# =========================
with tab_exo:
    if not DATA:
        st.info("â„¹ï¸ Aucun exercice publiÃ© pour lâ€™instant. Va dans lâ€™espace Admin et clique Â« Publier Â» (puis reviens ici).")
    else:
        exos = [ex for ex in DATA.get(selected_theme, []) if isinstance(ex, dict) and ex.get("question")]
        total = len(exos)
        if total == 0:
            st.info("â„¹ï¸ Aucun exercice pour ce thÃ¨me.")
        else:
            validated_count = sum(1 for i in range(total) if st.session_state.validated.get((selected_theme, i)))
            st.progress(validated_count / max(1, total), text=f"Progression â€” {validated_count}/{total} exercices validÃ©s")

            pending = st.session_state.pop("pending_retry", None)
            if pending and pending.get("theme") == selected_theme:
                ridx = int(pending.get("idx", 0))
                st.session_state.pop(f"mc_{selected_theme}_{ridx}", None)
                st.session_state.pop(f"fib_{selected_theme}_{ridx}", None)
                st.session_state.pop(f"oe_{selected_theme}_{ridx}", None)
                st.session_state.validated.pop((selected_theme, ridx), None)
                st.session_state.open_evals.pop((selected_theme, ridx), None)
                st.session_state.current_index = ridx

            if st.session_state.current_index >= total:
                st.session_state.current_index = 0
            idx = st.session_state.current_index
            exo = exos[idx]

            def type_key(s: str) -> str:
                s = (s or "").strip().lower()
                if s in ("multiple choice", "qcm"): return "multiple_choice"
                if s in ("fill in the blank", "fill-in-the-blank", "texte Ã  trous", "texte a trous"): return "fill_blank"
                if s in ("open ended", "open question", "question ouverte"): return "open_ended"
                return s

            kind = type_key(exo.get("type"))
            st.subheader(f"ðŸ“ Exercice {idx+1}/{total} â€¢ {exo.get('type','?')}")
            st.markdown(f"**ThÃ¨me :** {selected_theme}")
            st.markdown(f"**Question :** {exo.get('question','')}")

            # --- QCM ---
            if kind == "multiple_choice":
                options = exo.get("options", [])
                correct = (exo.get("answer") or (exo.get("reponses_correctes", [None])[0]) or "")
                mc_key = f"mc_{selected_theme}_{idx}"
                try:
                    selected = st.radio("Choisissez une rÃ©ponse :", options, index=None, key=mc_key)
                except TypeError:
                    placeholder = "â€” SÃ©lectionnez â€”"
                    selected = st.radio("Choisissez une rÃ©ponse :", [placeholder] + options, index=0, key=mc_key)
                    if selected == placeholder: selected = None

                c1, c2 = st.columns([1,1])
                with c1:
                    if st.button("âœ… Valider", key=f"val_mc_{selected_theme}_{idx}"):
                        if selected is None:
                            st.warning("SÃ©lectionne une rÃ©ponse pour valider.")
                        else:
                            is_correct = (selected == correct)
                            first_time = not st.session_state.validated.get((selected_theme, idx))
                            if first_time:
                                st.session_state.scores[selected_theme] = st.session_state.scores.get(selected_theme, 0) + (1 if is_correct else 0)
                            st.session_state.validated[(selected_theme, idx)] = True

                            if is_correct:
                                st.success("âœ… Bonne rÃ©ponse")
                                if first_time: st.balloons()
                                fb = "Bonne rÃ©ponse"
                            else:
                                st.error(f"âŒ Mauvaise rÃ©ponse â€” attendu : {correct}")
                                fb = f"Mauvaise rÃ©ponse â€” attendu : {correct}"

                            log_attempt(user_email, selected_theme, exo, 1.0 if is_correct else 0.0, level="", feedback=fb)

                with c2:
                    if st.button("ðŸ” Rejouer", key=f"retry_mc_{selected_theme}_{idx}"):
                        st.session_state["pending_retry"] = {"theme": selected_theme, "idx": idx}
                        st.experimental_rerun()

            # --- Texte Ã  trous ---
            elif kind == "fill_blank":
                fib_key = f"fib_{selected_theme}_{idx}"
                st.text_input("Votre rÃ©ponse :", key=fib_key)
                expected_raw = (exo.get("answer") or (exo.get("blanks", [None])[0]) or "")
                c1, c2 = st.columns([1,1])
                with c1:
                    if st.button("âœ… Valider", key=f"val_fib_{selected_theme}_{idx}"):
                        user_answer = st.session_state.get(fib_key, "")
                        expected = str(expected_raw).strip().lower()
                        given = str(user_answer).strip().lower()
                        is_correct = bool(expected) and (given == expected or fuzzy_equal(given, expected, tolerance=0.2))
                        first_time = not st.session_state.validated.get((selected_theme, idx))
                        if first_time:
                            st.session_state.scores[selected_theme] = st.session_state.scores.get(selected_theme, 0) + (1 if is_correct else 0)
                        st.session_state.validated[(selected_theme, idx)] = True

                        if expected:
                            if is_correct:
                                st.success("âœ… Bonne rÃ©ponse")
                                if first_time: st.balloons()
                                fb = "Bonne rÃ©ponse"
                            else:
                                st.error(f"âŒ Mauvaise rÃ©ponse â€” attendu : {expected_raw}")
                                fb = f"Mauvaise rÃ©ponse â€” attendu : {expected_raw}"
                        else:
                            st.info("RÃ©ponse enregistrÃ©e.")
                            fb = "RÃ©ponse enregistrÃ©e"

                        log_attempt(user_email, selected_theme, exo, 1.0 if is_correct else 0.0, level="", feedback=fb)
                with c2:
                    if st.button("ðŸ” Rejouer", key=f"retry_fib_{selected_theme}_{idx}"):
                        st.session_state["pending_retry"] = {"theme": selected_theme, "idx": idx}
                        st.experimental_rerun()

            # --- Question ouverte ---
            elif kind == "open_ended":
                oe_key = f"oe_{selected_theme}_{idx}"
                st.text_area("Votre rÃ©ponse :", height=170, key=oe_key)
                c1, c2 = st.columns([1,1])
                with c1:
                    if st.button("âœ… Valider", key=f"val_oe_{selected_theme}_{idx}"):
                        user_answer = st.session_state.get(oe_key, "")
                        expected = exo.get("answer")
                        evaluation = gpt_open_eval(user_answer, exo.get("question",""), expected)
                        st.session_state.open_evals[(selected_theme, idx)] = evaluation

                        s25 = int(evaluation["score"]); s01 = to01(s25)
                        st.success(f"**{evaluation['label']}** â€” score {s25}/5")
                        if evaluation.get("feedback"): st.info(f"ðŸ’¬ {evaluation['feedback']}")
                        if evaluation.get("suggestions"):
                            st.markdown("ðŸ’¡ **Pistes concrÃ¨tes**")
                            for sgt in evaluation["suggestions"]:
                                st.markdown(f"- {sgt}")
                        if evaluation.get("improved"):
                            st.markdown("âœï¸ **Exemple de rÃ©ponse amÃ©liorÃ©e (court)**")
                            st.code(evaluation["improved"], language="markdown")
                        if s25 == 5: st.balloons()

                        log_attempt(user_email, selected_theme, exo, s01, level=evaluation["label"], feedback=evaluation.get("feedback",""))
                with c2:
                    if st.button("ðŸ” Rejouer", key=f"retry_oe_{selected_theme}_{idx}"):
                        st.session_state["pending_retry"] = {"theme": selected_theme, "idx": idx}
                        st.experimental_rerun()

            # --- Navigation ---
            st.markdown("---")
            nav1, nav2 = st.columns([1,1])
            with nav1:
                if st.button("â¬…ï¸ PrÃ©cÃ©dent", key=f"prev_{selected_theme}_{idx}") and idx > 0:
                    st.session_state.current_index -= 1
                    st.experimental_rerun()
            with nav2:
                if st.button("âž¡ï¸ Suivant", key=f"next_{selected_theme}_{idx}"):
                    if idx + 1 < total:
                        st.session_state.current_index += 1
                        st.experimental_rerun()
                    else:
                        st.success("ðŸŽ‰ Tu as terminÃ© tous les exercices de ce thÃ¨me !")
                        st.info("Passe au **Plan dâ€™action (SMART)** pour transformer lâ€™intention en actions concrÃ¨tes.")
                        st.balloons()

# =========================
# Onglet â€” Plan dâ€™action (SMART)
# =========================
with tab_plan:
    st.subheader(f"ðŸ—ºï¸ Plan dâ€™action â€” {selected_theme or 'GÃ©nÃ©rique'}")
    st.caption("Objectif SMART â†’ Contexte â†’ Actions â†’ Obstacles â†’ KPIs â†’ Ã‰chÃ©ance. "
               "Valide avec lâ€™IA (si dispo) puis enregistre.")

    def load_json_path(p: Path, default: Any): 
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return default

    plans_db = load_plans()
    node = get_plan_node(plans_db, user_email or "anonymous", selected_theme or "GÃ©nÃ©rique")
    latest = node.get("latest") or {}

    objectif = st.text_area("ðŸŽ¯ Objectif (SMART)", value=latest.get("objective",""), height=90,
                            placeholder="Ex. Augmenter le taux de complÃ©tion de 60% Ã  80% sur 6 semaines.")
    contexte = st.text_area("ðŸžï¸ Contexte (oÃ¹/pourquoi)", value=latest.get("context",""), height=90)
    cA, cB, cC = st.columns(3)
    with cA:
        action1 = st.text_input("ðŸ› ï¸ Action 1", value=(latest.get("actions", ["","",""])+["","",""])[0])
    with cB:
        action2 = st.text_input("ðŸ› ï¸ Action 2", value=(latest.get("actions", ["","",""])+["","",""])[1])
    with cC:
        action3 = st.text_input("ðŸ› ï¸ Action 3 (facultatif)", value=(latest.get("actions", ["","",""])+["","",""])[2])
    obstacles = st.text_area("ðŸ§± Obstacles (Ã  lever)", value=latest.get("obstacles",""), height=70)
    kpis = st.text_area("ðŸ“ˆ Indicateurs / KPIs", value=latest.get("kpis",""), height=70,
                        placeholder="Ex. % de complÃ©tion, dÃ©lai moyen, score qualitÃ©â€¦")
    default_deadline = None
    try:
        if latest.get("deadline"):
            y,m,d = map(int, str(latest["deadline"]).split("-"))
            default_deadline = date(y,m,d)
    except Exception:
        pass
    if default_deadline is None: default_deadline = today_local()
    deadline = st.date_input("ðŸ—“ï¸ Ã‰chÃ©ance", value=default_deadline)
    actions_list = [action1, action2, action3]

    colx, coly = st.columns([1,1])
    with colx:
        validate_ai = st.button("ðŸ§ª Valider avec lâ€™IA")
    with coly:
        save_btn = st.button("ðŸ’¾ Enregistrer")

    plan_eval = None
    if validate_ai:
        def heuristic_plan_eval(objective, context, actions, obstacles, kpis, deadline_iso):
            specific = len((objective or "").strip()) >= 20
            measurable = bool(re.search(r"(\d+|%|taux|kpi|score|indicateur|x\/\d)", (objective + " " + (kpis or "")).lower()))
            achievable = sum(1 for a in actions if (a or "").strip()) >= 2
            relevant = len((context or "").strip()) >= 15
            timebound = bool(deadline_iso)
            score = sum([specific, measurable, achievable, relevant, timebound])
            s = 5 if score >= 4 else 4 if score == 3 else 3 if score == 2 else 2
            d = f" dâ€™ici le {deadline_iso}" if deadline_iso else " sous 6 semaines"
            improved = f"Â« {objective.strip() or 'DÃ©finir un objectif'}{d}, mesurÃ© par {kpis or 'un indicateur'} ; " \
                       f"mise en Å“uvre via {', '.join([a for a in actions if (a or '').strip()][:3])}. Â»"
            missing = []
            if not specific:  missing.append("Rends lâ€™objectif plus spÃ©cifique (verbe dâ€™action, pÃ©rimÃ¨tre).")
            if not measurable: missing.append("Ajoute des indicateurs chiffrÃ©s (%/nombre, seuils).")
            if not achievable: missing.append("DÃ©taille 2â€“3 actions concrÃ¨tes (qui fait quoi, quand).")
            if not relevant:   missing.append("Relie Ã  lâ€™impact mÃ©tier (qualitÃ©, dÃ©lai, risque, satisfaction).")
            if not timebound:  missing.append("Fixe une date prÃ©cise.")
            return {
                "score": s, "label": label_from_score(s),
                "feedback": "Plan cohÃ©rent." if s >= 4 else "Plan Ã  prÃ©ciser (SMART).",
                "suggestions": missing[:3] if missing else ["Conserve un suivi hebdomadaire des indicateurs."],
                "improved": improved
            }

        deadline_iso = deadline.isoformat() if deadline else None
        if client:
            try:
                prompt = f"""
Tu joues le rÃ´le dâ€™un Coach IA. Ã‰value ce plan dâ€™action au regard des critÃ¨res SMART et renvoie un JSON STRICT :
{{
  "score": 2..5,
  "label": "Excellent" | "Câ€™est vraiment encourageant" | "Tu es sur la bonne voie" | "Argh, Ã  renforcer",
  "feedback": "1â€“2 phrases de synthÃ¨se",
  "suggestions": ["3 conseils concrets maximum"],
  "improved": "rÃ©Ã©criture SMART synthÃ©tique en 2â€“3 lignes"
}}
Contexte : {contexte}
Objectif : {objectif}
Actions : {actions_list}
Obstacles : {obstacles}
KPIs : {kpis}
Ã‰chÃ©ance : {deadline_iso or "N/A"}
"""
                resp = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "Tu es un coach pÃ©dagogique exigeant et bienveillant."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )
                data = json.loads((resp.choices[0].message.content or "").strip())
                s = max(2, min(5, int(data.get("score", 3))))
                plan_eval = {
                    "score": s,
                    "label": data.get("label") or label_from_score(s),
                    "feedback": data.get("feedback") or "",
                    "suggestions": (data.get("suggestions") or [])[:3],
                    "improved": data.get("improved") or "",
                }
            except Exception:
                plan_eval = heuristic_plan_eval(objectif, contexte, actions_list, obstacles, kpis, deadline_iso)
        else:
            plan_eval = heuristic_plan_eval(objectif, contexte, actions_list, obstacles, kpis, deadline_iso)

        st.session_state["plan_eval_cache"][(user_email, selected_theme)] = plan_eval

    if not plan_eval:
        plan_eval = st.session_state["plan_eval_cache"].get((user_email, selected_theme))

    if plan_eval:
        st.success(f"**{plan_eval['label']}** â€” score {plan_eval['score']}/5")
        if plan_eval.get("feedback"): st.info(f"ðŸ’¬ {plan_eval['feedback']}")
        if plan_eval.get("suggestions"):
            st.markdown("ðŸ’¡ **Pistes dâ€™amÃ©lioration**")
            for sgt in plan_eval["suggestions"]:
                st.markdown(f"- {sgt}")
        if plan_eval.get("improved"):
            st.markdown("âœï¸ **Version SMART proposÃ©e**")
            st.code(plan_eval["improved"], language="markdown")

    if save_btn:
        entry = {
            "objective": objectif,
            "context": contexte,
            "actions": [a for a in actions_list if (a or "").strip()],
            "obstacles": obstacles,
            "kpis": kpis,
            "deadline": deadline.isoformat() if deadline else "",
            "timestamp": safe_now_iso(),
            "evaluation": plan_eval or {
                "score": 3, "label": label_from_score(3), "feedback": "", "suggestions": [], "improved": ""
            },
        }
        node["history"].append(entry)
        node["latest"] = entry
        save_plans(plans_db)
        st.success("âœ… Plan dâ€™action enregistrÃ©.")


