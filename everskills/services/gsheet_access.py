from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import streamlit as st


@dataclass
class WebhookResult:
    ok: bool
    data: Dict[str, Any]
    error: str = ""


class GSheetAccessAPI:
    def __init__(self) -> None:
        self.url = st.secrets["GSHEET_USERS_WEBAPP_URL"]
        self.secret = st.secrets["GSHEET_USERS_SHARED_SECRET"]

    def _post(self, payload: Dict[str, Any]) -> WebhookResult:
        payload = dict(payload)
        payload["secret"] = self.secret

        try:
            r = requests.post(
                self.url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=25,
            )
        except Exception as e:
            return WebhookResult(False, {"ok": False}, error=f"Webhook unreachable: {e}")

        try:
            data = r.json()
        except Exception:
            return WebhookResult(False, {"ok": False, "raw": r.text}, error="Invalid JSON response from WebApp")

        if bool(data.get("ok")) is True:
            return WebhookResult(True, data, error="")

        return WebhookResult(False, data, error=str(data.get("error") or "Unknown error"))

    def create_user(
        self,
        email: str,
        first_name: str,
        last_name: str,
        role: str = "learner",
        status: str = "pending",
        initial_password: str = "",
        source: str = "streamlit",
        request_id: str = "",
    ) -> WebhookResult:
        return self._post(
            {
                "action": "create_user",
                "email": email.strip().lower(),
                "role": role,
                "status": status,
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "initial_password": initial_password,  # should be empty at request time
                "source": source,
                "request_id": request_id,
            }
        )

    def list_users(self) -> WebhookResult:
        return self._post({"action": "list_users"})

    def update_user(
        self,
        *,
        request_id: str = "",
        email: str = "",
        updates: Dict[str, Any],
    ) -> WebhookResult:
        payload: Dict[str, Any] = {"action": "update_user", "updates": updates}
        if request_id.strip():
            payload["request_id"] = request_id.strip()
        else:
            payload["email"] = email.strip().lower()

        return self._post(payload)


def get_gsheet_api() -> GSheetAccessAPI:
    return GSheetAccessAPI()
