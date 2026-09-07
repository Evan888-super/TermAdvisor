"""Strip secrets from text before it can leave the machine.

Layer 3a. Pure string functions. No config I/O, no model calls.

Used later by advisor.build_payload() on the command + log + question,
and by context.read_snippet() on any source window we attach.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED PRIVATE KEY]",
    ),
    (
        re.compile(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
            re.DOTALL,
        ),
        "[REDACTED CERTIFICATE]",
    ),
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)\S+"),
        r"\1\2" + REDACTED,
    ),
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*basic\s+)\S+"),
        r"\1" + REDACTED,
    ),
    (re.compile(r"AKIA[0-9A-Z]{16}"), REDACTED),
    (
        re.compile(r"(?i)(aws_secret_access_key\s*[:=]\s*)\S+"),
        r"\1" + REDACTED,
    ),
    (re.compile(r"ghp_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"gho_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"sk_live_[A-Za-z0-9]{16,}"), REDACTED),
    (re.compile(r"sk_test_[A-Za-z0-9]{16,}"), REDACTED),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), REDACTED),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"xai-[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"nvapi-[A-Za-z0-9_-]{20,}"), REDACTED),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        REDACTED,
    ),
    (
        re.compile(
            r"(?i)((?:postgres|postgresql|mysql|mongodb|redis|amqp|https?)://[^:\s/]+:)([^@\s]+)(@)"
        ),
        r"\1" + REDACTED + r"\3",
    ),
    (
        re.compile(
            r'(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIALS?)\s*[=:]\s*)([\'"]?)([^\s\'"]+)(\2)'
        ),
        r"\1\2" + REDACTED + r"\4",
    ),
    (
        re.compile(
            r"(?i)(--(?:token|password|passwd|secret|api-key|apikey|key)\s+)(\S+)"
        ),
        r"\1" + REDACTED,
    ),
    (
        re.compile(
            r'(?i)(export\s+[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY)\s*=\s*)([\'"]?)([^\s\'"]+)(\2)'
        ),
        r"\1\2" + REDACTED + r"\4",
    ),
]


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def looks_like_secret_file(path: str) -> bool:
    """True when context.py must refuse to read this path."""
    name = path.replace("\\", "/").lower()
    suspects = (
        ".env",
        "id_rsa",
        "id_ed25519",
        "credentials",
        "secret",
        ".pem",
        ".p12",
        ".key",
        "auth.json",
        "service-account",
    )
    return any(s in name for s in suspects)