"""Persist the last shell failure.

Layer 2b. Uses ``config.cache_dir`` for the path and
``models.FailureEvent`` (``to_dict`` / ``from_dict``) for the record.

Files under the cache directory:

* ``last_event.json``  — full FailureEvent
* ``last_output.txt``  — the log alone, so a later pipe can attach output
* ``history.jsonl``    — last 50 command/exit/cwd rows (no full logs)

The shell hook will call ``save_event`` after a command.
``explain`` / ``ask`` will call ``load_event`` in a later process.
"""

#a different drawer for settings

from __future__ import annotations

import json
import time
from pathlib import Path

from termadvisor.config import cache_dir
from termadvisor.models import FailureEvent

LAST_EVENT_NAME = "last_event.json"
LAST_OUTPUT_NAME = "last_output.txt"
HISTORY_NAME = "history.jsonl"
MAX_HISTORY = 50


def last_event_path() -> Path:
    return cache_dir() / LAST_EVENT_NAME


def last_output_path() -> Path:
    return cache_dir() / LAST_OUTPUT_NAME


def history_path() -> Path:
    return cache_dir() / HISTORY_NAME


def save_event(event: FailureEvent) -> Path:
    if event.finished_at is None:
        event.finished_at = time.time()
    payload = event.to_dict()
    path = last_event_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    last_output_path().write_text(event.output or "", encoding="utf-8")
    _append_history(payload)
    return path


def load_event() -> FailureEvent | None:
    path = last_event_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    output = data.get("output") or ""
    if not output and last_output_path().exists():
        try:
            output = last_output_path().read_text(encoding="utf-8")
        except OSError:
            output = ""
        data["output"] = output
    return FailureEvent.from_dict(data)


def update_output(text: str, append: bool = False) -> None:
    """Attach (or extend) a log on the already-recorded command."""
    path = last_output_path()
    if append and path.exists():
        try:
            text = path.read_text(encoding="utf-8") + text
        except OSError:
            pass
    path.write_text(text, encoding="utf-8")
    event = load_event()
    if event:
        event.output = text
        save_event(event)


def load_history(limit: int = MAX_HISTORY) -> list[dict]:
    path = history_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict] = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _append_history(payload: dict) -> None:
    path = history_path()
    slim = {
        "command": payload.get("command"),
        "exit_code": payload.get("exit_code"),
        "cwd": payload.get("cwd"),
        "finished_at": payload.get("finished_at"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(slim) + "\n")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_HISTORY:
            path.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n", encoding="utf-8")
    except OSError:
        pass