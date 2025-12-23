from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class JsonStorage:
    path: Path

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"campaigns": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {"campaigns": []}
            raw.setdefault("campaigns", [])
            if not isinstance(raw["campaigns"], list):
                raw["campaigns"] = []
            return raw
        except Exception:
            return {"campaigns": []}

    def save(self, db: Dict[str, Any]) -> None:
        if "campaigns" not in db or not isinstance(db["campaigns"], list):
            db["campaigns"] = []
        atomic_write(self.path, db)

    def create_campaign(
        self,
        learner_email: str,
        coach_email: str,
        objective_raw: str,
        support: Optional[Dict[str, Any]] = None,
        weeks: int = 3,
    ) -> Dict[str, Any]:
        db = self.load()
        camp = {
            "id": uuid4().hex[:12],
            "learner_email": (learner_email or "").strip().lower(),
            "coach_email": (coach_email or "").strip().lower(),
            "objective_raw": (objective_raw or "").strip(),
            "support": support or None,
            "weeks": int(weeks),
            "status": "submitted",  # submitted -> coach_validated -> active -> closed
            "program": None,        # set by coach
            "messages": [],         # [{from, text, ts}]
            "feedback": [],         # [{week, text, ts}]
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        db["campaigns"].append(camp)
        self.save(db)
        return camp

    def list_campaigns(self) -> List[Dict[str, Any]]:
        return self.load().get("campaigns", [])

    def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        for c in self.list_campaigns():
            if c.get("id") == campaign_id:
                return c
        return None

    def update_campaign(self, campaign_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        db = self.load()
        for i, c in enumerate(db.get("campaigns", [])):
            if c.get("id") == campaign_id:
                c.update(updates)
                c["updated_at"] = now_iso()
                db["campaigns"][i] = c
                self.save(db)
                return c
        return None

    def add_message(self, campaign_id: str, sender: str, text: str) -> None:
        c = self.get_campaign(campaign_id)
        if not c:
            return
        msg = {"from": sender, "text": (text or "").strip(), "ts": now_iso()}
        messages = c.get("messages") or []
        messages.append(msg)
        self.update_campaign(campaign_id, {"messages": messages})

    def add_feedback(self, campaign_id: str, week: int, text: str) -> None:
        c = self.get_campaign(campaign_id)
        if not c:
            return
        fb = {"week": int(week), "text": (text or "").strip(), "ts": now_iso()}
        feedback = c.get("feedback") or []
        feedback.append(fb)
        self.update_campaign(campaign_id, {"feedback": feedback})


storage = JsonStorage(Path(__file__).resolve().parents[1] / "data" / "campaigns.json")

