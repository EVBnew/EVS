# everskills/services/access_backend.py
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st


@dataclass
class AccessBackend:
    """Interface simple: load only for gsheet_csv; json supports load+save."""
    def load_access(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def can_write(self) -> bool:
        return False

    def save_access(self, rows: List[Dict[str, Any]]) -> None:
        raise NotImplementedError("This backend is read-only")


@dataclass
class JsonAccessBackend(AccessBackend):
    access_path: Path

    def load_access(self) -> List[Dict[str, Any]]:
        if not self.access_path.exists():
            return []
        try:
            raw = self.access_path.read_text(encoding="utf-8")
            if not raw.strip():
                return []
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [x for x in data if isinstance(x, dict)]
        except Exception:
            return []

    def can_write(self) -> bool:
        return True

    def save_access(self, rows: List[Dict[str, Any]]) -> None:
        rows = [r for r in rows if isinstance(r, dict) and r.get("email")]
        self.access_path.parent.mkdir(parents=True, exist_ok=True)
        self.access_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class GSheetCsvAccessBackend(AccessBackend):
    csv_url: str

    def load_access(self) -> List[Dict[str, Any]]:
        url = (self.csv_url or "").strip()
        if not url:
            return []

        # Streamlit's built-in fetcher (works in Streamlit Cloud)
        try:
            resp = st.runtime.scriptrunner.script_run_context.get_script_run_ctx()  # noqa: F841
        except Exception:
            pass

        try:
            import requests  # type: ignore
        except Exception:
            requests = None  # type: ignore

        try:
            if requests is None:
                return []
            r = requests.get(url, timeout=12)
            if r.status_code != 200:
                return []
            content = r.text
        except Exception:
            return []

        buf = io.StringIO(content)
        reader = csv.DictReader(buf)

        out: List[Dict[str, Any]] = []
        for row in reader:
            if not isinstance(row, dict):
                continue
            # Normalize keys + strip
            norm = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items()}
            if not norm.get("email"):
                continue
            out.append(norm)
        return out


def get_access_backend(json_access_path: Path) -> AccessBackend:
    backend = (st.secrets.get("ACCESS_BACKEND") or "json").strip().lower()
    if backend == "gsheet_csv":
        url = (st.secrets.get("ACCESS_GSHEET_CSV_URL") or "").strip()
        return GSheetCsvAccessBackend(csv_url=url)
    return JsonAccessBackend(access_path=json_access_path)
