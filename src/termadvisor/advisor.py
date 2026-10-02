"""Orchestrate local rules, redaction, snippets, then the model.

Layer 4b. This is the single function later CLI commands should call.

Flow of ``advise``:

1. If local_first: try trivial.diagnose_local. On a hit (and no extra
   question), return that Advice and never touch the network.
2. If offline: return the local hit, or a placeholder Advice.
3. Else, if Tavily is on, attach redacted web snippets. Never upload source files there.
4. Build a redacted payload (optional source snippets) and call
   provider.complete + parse_advice.
"""

from __future__ import annotations

import time

from termadvisor.capture import advice_cache_key, load_cached_advice, store_cached_advice
from termadvisor.config import AppConfig
from termadvisor.context import collect_snippets
from termadvisor.models import Advice, FailureEvent
from termadvisor.provider import complete, parse_advice
from termadvisor.redact import redact_text
from termadvisor.search import build_query, search
from termadvisor.trivial import diagnose_local


def build_payload(
    cfg: AppConfig,
    event: FailureEvent,
    question: str | None = None,
    web: str | None = None,
) -> str:
    output = event.tail(cfg.behavior.max_tail_lines)
    if cfg.behavior.redact:
        command = redact_text(event.command)
        output = redact_text(output)
        question = redact_text(question) if question else None
    else:
        command = event.command

    snippets: list[str] = []
    if cfg.privacy.upload_source_snippets and output:
        snippets = collect_snippets(
            output,
            event.cwd,
            radius=cfg.privacy.snippet_radius,
            max_files=cfg.privacy.max_snippet_files,
            redact=cfg.behavior.redact,
        )

    parts = [
        "Diagnose this terminal failure and propose copy-pasteable fixes.",
        f"Working directory: {event.cwd or '(unknown)'}",
        f"Exit code: {event.exit_code}",
        f"Command: {command or '(not recorded)'}",
    ]
    if event.shell:
        parts.append(f"Shell: {event.shell}")
    if question:
        parts.append(f"User question: {question}")
    parts.append("Output tail:")
    parts.append(
        output.strip()
        or "(no output was captured — infer from the command and exit code)"
    )
    if snippets:
        parts.append("Source snippets named in the stack trace:")
        parts.extend(snippets)
    if web:
        parts.append("Web search snippets (docs only, not local source):")
        parts.append(web)
    return "\n".join(parts)


def advise(
    cfg: AppConfig,
    event: FailureEvent,
    *,
    question: str | None = None,
    force_model: bool = False,
    offline: bool = False,
    use_cache: bool = True,
    use_search: bool | None = None,
) -> Advice:
    started = time.perf_counter()
    local = None
    if cfg.behavior.local_first and not force_model:
        local = diagnose_local(event)
        if local and not question:
            local.elapsed_s = time.perf_counter() - started
            return local

    if offline:
        if local:
            local.elapsed_s = time.perf_counter() - started
            return local
        advice = Advice(
            cause="Offline mode: no local rule matched and the model was not called.",
            suggestions=[],
            detail="Pipe a log into `TermAdvisor explain` after `TermAdvisor login`, or turn offline off.",
            confidence="low",
            source="offline",
            command=event.command,
            exit_code=event.exit_code,
        )
        advice.elapsed_s = time.perf_counter() - started
        return advice

    cache_on = use_cache and cfg.behavior.cache_advice
    key = advice_cache_key(event.command, event.exit_code, event.tail(200), question or "")
    if cache_on:
        cached = load_cached_advice(key, cfg.behavior.cache_ttl_s)
        if cached:
            advice = Advice.from_dict(cached)
            advice.source = "cache"
            advice.command = event.command
            advice.exit_code = event.exit_code
            advice.elapsed_s = time.perf_counter() - started
            if advice.detail:
                advice.detail += "\nServed from the local advice cache. No API call was made."
            else:
                advice.detail = "Served from the local advice cache. No API call was made."
            return advice

    web = ""
    search_on = cfg.tavily.enabled if use_search is None else use_search
    if search_on and cfg.has_tavily_key():
        web = search(cfg, build_query(event, question, redact=cfg.behavior.redact))

    payload = build_payload(cfg, event, question=question, web=web or None)
    raw = complete(cfg, payload)
    advice = parse_advice(raw)
    advice.model = cfg.resolved_model()
    advice.command = event.command
    advice.exit_code = event.exit_code
    advice.elapsed_s = time.perf_counter() - started
    if web:
        note = "Web snippets from Tavily were attached before the model call."
        advice.detail = f"{advice.detail}\n{note}".strip() if advice.detail else note
    if cache_on and advice.source == "model":
        store_cached_advice(key, advice.to_dict())
    return advice
