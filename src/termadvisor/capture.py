"""Persist the last shell failure.

Layer 2b. Depends on ``config.cache_dir`` for the path and on
``models.FailureEvent`` for the record shape.

Files under the cache directory:

* ``last_event.json``  — full FailureEvent (command, exit, cwd, output)
* ``last_output.txt``  — the log alone, so a later pipe can attach output
* ``history.jsonl``    — last 50 command/exit/cwd lines (no full logs)

The shell hook will call ``save_event`` after every command of interest.
``explain`` / ``ask`` will call ``load_event`` on a later invocation —
hence disk, not process memory.
"""

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


SESSION_LOG_NAME = "session.log"
CAPTURE_FLAG_NAME = "capture.on"
ADVICE_CACHE_NAME = "advice_cache.json"


def session_log_path() -> Path:
    return cache_dir() / SESSION_LOG_NAME


def capture_flag_path() -> Path:
    return cache_dir() / CAPTURE_FLAG_NAME


def set_capture_flag(enabled: bool) -> Path:
    path = capture_flag_path()
    if enabled:
        path.write_text("1\n", encoding="utf-8")
    elif path.exists():
        path.unlink()
    return path


def read_session_tail(max_lines: int = 80) -> str:
    """Last lines of the optional script(1) session log. Empty if capture is off."""
    path = session_log_path()
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if max_lines <= 0:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def advice_cache_path() -> Path:
    return cache_dir() / ADVICE_CACHE_NAME


def advice_cache_key(command: str, exit_code: int, output: str, question: str = "") -> str:
    import hashlib

    basis = "\n".join(
        [
            (command or "").strip(),
            str(exit_code),
            (output or "").strip()[-4000:],
            (question or "").strip(),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8", errors="replace")).hexdigest()


def load_cached_advice(key: str, ttl_s: int):
    """Return a cached Advice dict if it is still fresh, else None."""
    path = advice_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    row = data.get(key) if isinstance(data, dict) else None
    if not isinstance(row, dict):
        return None
    saved_at = float(row.get("saved_at") or 0)
    if ttl_s > 0 and (time.time() - saved_at) > ttl_s:
        return None
    advice = row.get("advice")
    return advice if isinstance(advice, dict) else None


def store_cached_advice(key: str, advice: dict, limit: int = 40) -> None:
    path = advice_cache_path()
    data: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data[key] = {"saved_at": time.time(), "advice": advice}
    if len(data) > limit:
        ranked = sorted(data.items(), key=lambda item: float(item[1].get("saved_at") or 0))
        data = dict(ranked[-limit:])
    path.write_text(json.dumps(data), encoding="utf-8")
