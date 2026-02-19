# everskills/services/voice_notes.py
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st


@dataclass
class DriveUploadResult:
    ok: bool
    audio_url: str
    audio_url_alt: str
    file_id: str
    mime_type: str
    error: str = ""


def _webhook_url_and_secret() -> Tuple[str, str]:
    url = (
        st.secrets.get("GSHEET_WEBAPP_URL")
        or st.secrets.get("APPS_SCRIPT_URL")
        or st.secrets.get("GSHEET_API_URL")
        or st.secrets.get("WEBHOOK_URL")
        or ""
    )
    secret = (
        st.secrets.get("GSHEET_SHARED_SECRET")
        or st.secrets.get("SHARED_SECRET")
        or st.secrets.get("EVS_SECRET")
        or ""
    )
    return str(url).strip(), str(secret).strip()


def upload_voice_note_to_drive(
    *,
    file_name: str,
    mime_type: str,
    audio_bytes: bytes,
    timeout_s: int = 60,
) -> DriveUploadResult:
    url, secret = _webhook_url_and_secret()
    if not url or not secret:
        return DriveUploadResult(
            ok=False,
            audio_url="",
            audio_url_alt="",
            file_id="",
            mime_type=mime_type or "",
            error="Missing webhook secrets (URL/SECRET).",
        )

    b64 = base64.b64encode(audio_bytes).decode("ascii")
    payload = {
        "secret": secret,
        "action": "upload_voice_note",
        "file_name": file_name,
        "mime_type": mime_type,
        "data_b64": b64,
    }

    try:
        r = requests.post(url, json=payload, timeout=timeout_s)
        j = r.json() if r.content else {}
        if not isinstance(j, dict) or not j.get("ok"):
            return DriveUploadResult(
                ok=False,
                audio_url="",
                audio_url_alt="",
                file_id="",
                mime_type=mime_type or "",
                error=str((j or {}).get("error") or "Upload failed"),
            )

        return DriveUploadResult(
            ok=True,
            audio_url=str(j.get("audio_url") or ""),
            audio_url_alt=str(j.get("audio_url_alt") or ""),
            file_id=str(j.get("file_id") or ""),
            mime_type=str(j.get("mime_type") or mime_type or ""),
            error="",
        )
    except Exception as e:
        return DriveUploadResult(
            ok=False,
            audio_url="",
            audio_url_alt="",
            file_id="",
            mime_type=mime_type or "",
            error=str(e),
        )


def _openai_key() -> str:
    return str(st.secrets.get("OPENAI_API_KEY") or "").strip()


def transcribe_audio_openai(
    *,
    audio_bytes: bytes,
    file_name: str,
    mime_type: str,
    language: str = "fr",
    timeout_s: int = 90,
) -> str:
    """
    Uses OpenAI Audio Transcriptions endpoint.
    Model: gpt-4o-mini-transcribe (as requested)
    """
    api_key = _openai_key()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in st.secrets")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    files = {
        "file": (file_name, audio_bytes, mime_type or "application/octet-stream"),
    }
    data = {
        "model": "gpt-4o-mini-transcribe",
        "language": language,
        "response_format": "json",
    }

    r = requests.post(url, headers=headers, files=files, data=data, timeout=timeout_s)
    r.raise_for_status()
    j = r.json()
    txt = j.get("text")
    if not isinstance(txt, str) or not txt.strip():
        raise RuntimeError("Transcription returned empty text")
    return txt.strip()


def summarize_transcript_openai(
    *,
    transcript: str,
    timeout_s: int = 60,
) -> Tuple[str, List[str]]:
    """
    Chat summary with gpt-4o-mini -> returns (summary, bullets)
    """
    api_key = _openai_key()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in st.secrets")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    sys = (
        "Tu es un assistant de synthèse. "
        "Tu réponds en français. "
        "Tu produis un résumé court et une liste de points saillants."
    )
    user = (
        "Transcription:\n"
        f"{transcript}\n\n"
        "Retour attendu en JSON strict:\n"
        '{ "summary": "…", "highlights": ["…","…","…"] }\n'
        "Contraintes:\n"
        "- summary: 1 à 3 phrases max\n"
        "- highlights: 3 à 6 puces max\n"
    )

    body = {
        "model": "gpt-4o-mini",
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
    }

    r = requests.post(url, headers=headers, data=json.dumps(body), timeout=timeout_s)
    r.raise_for_status()
    j = r.json()
    content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    content = str(content)

    # Robust JSON extraction (no hard fail)
    summary = ""
    highlights: List[str] = []
    try:
        start = content.find("{")
        end = content.rfind("}")
        raw = content[start : end + 1] if start != -1 and end != -1 and end > start else content
        obj = json.loads(raw)
        summary = str(obj.get("summary") or "").strip()
        hl = obj.get("highlights") or []
        if isinstance(hl, list):
            highlights = [str(x).strip() for x in hl if str(x).strip()]
    except Exception:
        # fallback: simple heuristic
        summary = content.strip()

    if not summary:
        summary = "Résumé indisponible."
    if not highlights:
        highlights = []

    return summary, highlights


def build_voice_note_body(
    *,
    audio_url: str,
    transcript: str,
    summary: str,
    highlights: List[str],
) -> str:
    bullets = ""
    if highlights:
        bullets = "\n".join([f"- {b}" for b in highlights])

    parts = [
        "🎙️ Note vocale",
        f"Audio: {audio_url}",
        "",
        "Résumé:",
        summary.strip(),
        "",
        "Points saillants:" if bullets else "Points saillants:",
        bullets if bullets else "(aucun)",
        "",
        "Transcription:",
        transcript.strip(),
    ]
    return "\n".join(parts).strip()
