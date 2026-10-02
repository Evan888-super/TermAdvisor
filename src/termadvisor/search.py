"""Optional Tavily web search before a model call.

Off unless the user stores a key and turns search on. The query is the
redacted command plus the last error line. Source files are not sent.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from termadvisor.config import AppConfig
from termadvisor.models import FailureEvent
from termadvisor.redact import redact_text

SEARCH_URL = "https://api.tavily.com/search"


def build_query(event: FailureEvent, question: str | None = None, redact: bool = True) -> str:
    lines = [line.strip() for line in (event.output or "").splitlines() if line.strip()]
    error = lines[-1] if lines else ""
    parts = [event.command or "", error, question or ""]
    query = " ".join(part for part in parts if part).strip()
    if redact:
        query = redact_text(query)
    return query[:400]


def format_results(payload: dict) -> str:
    chunks: list[str] = []
    answer = (payload.get("answer") or "").strip()
    if answer:
        chunks.append(f"Answer: {answer}")
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip().replace("\n", " ")
        if not (title or content):
            continue
        chunks.append(f"- {title} ({url})\n  {content[:500]}")
    return "\n".join(chunks).strip()


def search(cfg: AppConfig, query: str) -> str:
    key = cfg.resolved_tavily_key()
    if not key or not query.strip():
        return ""
    body = json.dumps(
        {
            "query": query,
            "search_depth": "basic",
            "max_results": int(cfg.tavily.max_results),
            "include_answer": True,
            "include_raw_content": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        SEARCH_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.tavily.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return f"(Tavily search failed: {exc})"
    if not isinstance(payload, dict):
        return ""
    return format_results(payload)
