"""Shared types for TermAdvisor.

This module is the contract between every other file:

* ``FailureEvent`` — what happened in the user's shell
* ``Suggestion``   — one copy-pasteable fix the user may choose to run
* ``Advice``       — diagnosis shown as the terminal card

No I/O lives here: no config files, no API calls, no Rich output.
Later modules serialize these objects (capture.py), construct them
(trivial.py, provider.py), or render them (render.py).
"""

#draws the form "command / exit code / folder / log"

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

RiskLevel = Literal["low", "medium", "high"]
SuggestionKind = Literal["command", "code", "config", "explanation"]
AdviceSource = Literal["model", "local", "offline", "demo"]
Confidence = Literal["high", "medium", "low"]

RISK_LABELS: dict[str, str] = {
    "low": "safe to consider",
    "medium": "review before running",
    "high": "destructive or privileged — do not paste blindly",
}

# Substrings that force a suggestion to high risk even if the model
# labeled it "low". Keep these conservative — false positives only add
# a warning, false negatives would hide a dangerous paste.
HIGH_RISK_MARKERS: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "sudo rm",
    "mkfs",
    "dd if=",
    "drop database",
    "drop table",
    "force-push",
    "git push --force",
    "git push -f",
    "kubectl delete",
    "terraform destroy",
    ":(){",
    "chmod -r 777",
    "chmod -R 777",
    "shutdown",
    "reboot",
)


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def normalize_risk(value: Any) -> str:
    risk = _as_str(value, "low").strip().lower()
    if risk in RISK_LABELS:
        return risk
    return "low"


def normalize_kind(value: Any) -> str:
    kind = _as_str(value, "command").strip().lower()
    if kind in {"command", "code", "config", "explanation"}:
        return kind
    if kind in {"cmd", "shell"}:
        return "command"
    if kind in {"snippet", "patch"}:
        return "code"
    return "command"


def normalize_confidence(value: Any) -> str:
    conf = _as_str(value, "medium").strip().lower()
    if conf in {"high", "medium", "low"}:
        return conf
    return "medium"


def looks_destructive(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in HIGH_RISK_MARKERS)


@dataclass
class Suggestion:
    """One line the user can copy. TermAdvisor never executes it."""

    text: str
    risk: str = "low"
    kind: str = "command"
    note: str = ""

    def __post_init__(self) -> None:
        self.text = (self.text or "").strip()
        self.risk = normalize_risk(self.risk)
        self.kind = normalize_kind(self.kind)
        self.note = _as_str(self.note).strip()
        if self.is_high_risk():
            self.risk = "high"

    def is_high_risk(self) -> bool:
        return self.risk == "high" or looks_destructive(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "risk": self.risk,
            "kind": self.kind,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Suggestion:
        """Accept a string, or a dict from the model JSON.

        The model is instructed to use ``text``, but some completions
        say ``command`` or ``fix`` instead. All three are honored.
        """
        if isinstance(data, str):
            return cls(text=data)
        if not isinstance(data, dict):
            return cls(text=str(data))
        return cls(
            text=_as_str(data.get("text") or data.get("command") or data.get("fix")),
            risk=data.get("risk") or "low",
            kind=data.get("kind") or "command",
            note=_as_str(data.get("note")),
        )


@dataclass
class Advice:
    """What the terminal card displays after a diagnosis."""

    cause: str
    suggestions: list[Suggestion] = field(default_factory=list)
    detail: str = ""
    confidence: str = "medium"
    source: str = "model"
    model: str = ""
    elapsed_s: float = 0.0
    exit_code: int | None = None
    command: str = ""

    def __post_init__(self) -> None:
        self.cause = _as_str(self.cause).strip()
        self.detail = _as_str(self.detail).strip()
        self.confidence = normalize_confidence(self.confidence)
        self.source = _as_str(self.source, "model").strip().lower() or "model"
        self.model = _as_str(self.model).strip()
        self.command = _as_str(self.command)
        self.suggestions = [s for s in self.suggestions if s.text]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "detail": self.detail,
            "confidence": self.confidence,
            "source": self.source,
            "model": self.model,
            "elapsed_s": self.elapsed_s,
            "exit_code": self.exit_code,
            "command": self.command,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Advice:
        raw_suggestions: Iterable[Any] = data.get("suggestions") or []
        return cls(
            cause=_as_str(data.get("cause")),
            suggestions=[Suggestion.from_dict(item) for item in raw_suggestions],
            detail=_as_str(data.get("detail")),
            confidence=data.get("confidence") or "medium",
            source=_as_str(data.get("source"), "model"),
            model=_as_str(data.get("model")),
            elapsed_s=float(data.get("elapsed_s") or 0.0),
            exit_code=data.get("exit_code"),
            command=_as_str(data.get("command")),
        )


@dataclass
class FailureEvent:
    """One recorded shell invocation, usually a failure.

    ``output`` may be empty: the shell hook can only reliably capture
    command + exit + cwd. Full logs arrive via a pipe, ``--file``,
    or ``TermAdvisor wrap``.
    """

    command: str
    exit_code: int
    cwd: str
    output: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    shell: str = ""

    def tail(self, max_lines: int) -> str:
        """Last ``max_lines`` of output, with a marker if truncated."""
        if not self.output:
            return ""
        if max_lines <= 0:
            return self.output
        lines = self.output.splitlines()
        if len(lines) <= max_lines:
            return self.output
        omitted = len(lines) - max_lines
        return f"... ({omitted} earlier lines omitted)\n" + "\n".join(lines[-max_lines:])

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "cwd": self.cwd,
            "output": self.output,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "shell": self.shell,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureEvent:
        return cls(
            command=_as_str(data.get("command")),
            exit_code=int(data.get("exit_code") or 0),
            cwd=_as_str(data.get("cwd")),
            output=_as_str(data.get("output")),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            shell=_as_str(data.get("shell")),
        )