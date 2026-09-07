"""OpenAI-compatible chat call + JSON parse.

Layer 4a. The only module that should import ``openai``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from termadvisor.config import AppConfig
from termadvisor.models import Advice, Suggestion

SYSTEM_PROMPT = """You are TermAdvisor, a suggestions-only terminal assistant.
The user already ran a command. You never execute anything. You never ask them
to pipe secrets or paste .env files.

Return ONLY a JSON object with this shape:
{
  "cause": "one or two sentence diagnosis",
  "suggestions": [
    {"text": "exact command or code the user can copy", "kind": "command|code|config|explanation", "risk": "low|medium|high", "note": "optional short caveat"}
  ],
  "detail": "optional extra context, still concise",
  "confidence": "high|medium|low"
}

Rules:
- Prefer 1-3 concrete suggestions. First suggestion should be the safest likely fix.
- Suggestions must be copy-pasteable. Do not wrap them in markdown fences.
- Label anything destructive (rm, sudo, force-push, cluster delete, drop table) risk=high.
- Do not invent files, packages, or flags you are not reasonably sure about.
- If the log is insufficient, say so in cause and ask for a specific extra snippet.
- Do not include chain-of-thought. JSON only.
"""


def _client(cfg: AppConfig):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The 'openai' package is required. pip install openai") from exc

    key = cfg.resolved_api_key()
    if not key:
        raise RuntimeError(
            "No API key configured. Run `TermAdvisor login` or set "
            f"{cfg.provider.api_key_env}."
        )
    return OpenAI(
        api_key=key,
        base_url=cfg.provider.base_url.rstrip("/") + "/",
        timeout=cfg.provider.timeout_s,
    )


def complete(cfg: AppConfig, user_payload: str) -> str:
    client = _client(cfg)
    resp = client.chat.completions.create(
        model=cfg.resolved_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        temperature=cfg.provider.temperature,
        max_tokens=cfg.provider.max_tokens,
    )
    message = resp.choices[0].message
    return (message.content or "").strip()


def parse_advice(raw: str) -> Advice:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = _extract_json(text)
    if data is None:
        return Advice(
            cause=text.split("\n", 1)[0][:400] or "The model returned unstructured text.",
            suggestions=_suggestions_from_lines(text),
            detail=text,
            confidence="low",
            source="model",
        )
    return Advice.from_dict(
        {
            "cause": data.get("cause") or "No cause provided.",
            "suggestions": data.get("suggestions") or [],
            "detail": data.get("detail") or "",
            "confidence": data.get("confidence") or "medium",
            "source": "model",
        }
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _suggestions_from_lines(text: str) -> list[Suggestion]:
    found: list[Suggestion] = []
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)", stripped)
        if m:
            body = m.group(1).strip().strip("`")
            if body:
                found.append(Suggestion(text=body))
    return found[:5]