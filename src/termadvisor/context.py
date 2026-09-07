"""Pull a few source lines around file:line hits in a stack trace.

Layer 3b. Reads the local disk, never the network.
"""

from __future__ import annotations

import re
from pathlib import Path

from termadvisor.redact import looks_like_secret_file, redact_text

_STACK_PATTERNS = [
    re.compile(
        r"(?P<path>(?:\/|\.\/|\.\.\/|[A-Za-z]:\\)[^\s:]+):(?P<line>\d+)(?::\d+)?"
    ),
    re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)'),
    re.compile(r"at (?P<path>[^\s(]+\.[A-Za-z0-9]+):(?P<line>\d+)(?::\d+)?"),
    re.compile(r"-->\s+(?P<path>[^\s:]+):(?P<line>\d+)"),
    re.compile(r"(?P<path>[\w./\\-]+\.[A-Za-z][A-Za-z0-9]+):(?P<line>\d+)(?::\d+)?"),
]


def extract_locations(text: str, limit: int = 8) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for pattern in _STACK_PATTERNS:
        for match in pattern.finditer(text or ""):
            path = match.group("path")
            line = int(match.group("line"))
            key = (path, line)
            if key in seen or _skip_path(path):
                continue
            seen.add(key)
            found.append(key)
            if len(found) >= limit:
                return found
    return found


def _skip_path(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    if any(
        part in lowered
        for part in ("/node_modules/", "/site-packages/", "/dist-packages/")
    ):
        return True
    return looks_like_secret_file(path)


def read_snippet(path: str, line: int, radius: int = 8, redact: bool = True) -> str | None:
    candidate = Path(path)
    if not candidate.is_file():
        return None
    try:
        if candidate.stat().st_size > 1_000_000:
            return None
        raw = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = raw.splitlines()
    if not lines:
        return None
    idx = max(1, min(line, len(lines)))
    start = max(1, idx - radius)
    end = min(len(lines), idx + radius)
    chunk = []
    for n in range(start, end + 1):
        mark = ">" if n == idx else " "
        chunk.append(f"{mark}{n:5d} | {lines[n - 1]}")
    body = "\n".join(chunk)
    if redact:
        body = redact_text(body)
    return f"# {candidate} lines {start}-{end} (error near {idx})\n{body}"


def collect_snippets(
    output: str,
    cwd: str,
    *,
    radius: int = 8,
    max_files: int = 4,
    redact: bool = True,
) -> list[str]:
    snippets: list[str] = []
    used: set[str] = set()
    root = Path(cwd) if cwd else Path.cwd()
    for path, line in extract_locations(output):
        resolved = path
        if not Path(path).is_file():
            maybe = (root / path).resolve()
            if maybe.is_file():
                resolved = str(maybe)
        if resolved in used:
            continue
        snippet = read_snippet(resolved, line, radius=radius, redact=redact)
        if not snippet:
            continue
        used.add(resolved)
        snippets.append(snippet)
        if len(snippets) >= max_files:
            break
    return snippets