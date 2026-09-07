"""Local diagnoses for obvious failures. No network.

Layer 3c. Takes a ``FailureEvent`` from models.py and either returns
an ``Advice`` (source='local') or None, meaning 'let the model look'.

This is the cheap router from the README: command-not-found,
EADDRINUSE, missing pip/npm modules, permission denied, rejected git
push. Compiler traces (TS2345, rustc, SyntaxError) return None on
purpose — those benefit from Super.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
from functools import lru_cache

from termadvisor.models import Advice, FailureEvent, Suggestion

_COMMAND_NOT_FOUND = re.compile(
    r"(?:command not found|not found|is not recognized as|No such file or directory|"
    r"unknown command|not a valid command)",
    re.IGNORECASE,
)
_PERMISSION = re.compile(r"permission denied|operation not permitted", re.IGNORECASE)
_PORT_IN_USE = re.compile(
    r"(?:eaddrinuse|address already in use|port\s+\d+\s+is already)",
    re.IGNORECASE,
)
_MODULE = re.compile(
    r"(?:No module named ['\"](?P<mod>[^'\"]+)['\"]|"
    r"Cannot find module ['\"](?P<nmod>[^'\"]+)['\"])"
)
_PIP_FAIL = re.compile(
    r"ERROR: Could not find a version that satisfies|pip.*No matching distribution",
    re.I,
)
_GIT_REJECT = re.compile(
    r"(?:failed to push|non-fast-forward|updates were rejected)", re.I
)
_TS = re.compile(r"error TS\d+")
_RUST = re.compile(r"^error(?:\[E\d+\])?:", re.M)
_SYNTAX = re.compile(r"SyntaxError|ParseError|unexpected token", re.I)

_SHELL_BUILTINS = {
    "cd", "echo", "printf", "source", ".", "export", "alias", "unalias",
    "set", "unset", "eval", "exec", "exit", "return", "shift", "wait",
    "jobs", "fg", "bg", "true", "false", "test", "[", "[[", "hash",
    "type", "ulimit", "umask", "read", "pwd", "pushd", "popd", "dirs",
    "times", "trap", "bind", "history", "fc", "let", "local", "declare",
    "typeset", "readonly", "command", "builtin", "enable", "help",
    "logout", "suspend", "caller", "complete", "compgen",
}


@lru_cache(maxsize=1)
def _path_binaries() -> tuple[str, ...]:
    names: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        try:
            for entry in os.listdir(directory):
                names.add(entry)
        except OSError:
            continue
    return tuple(sorted(names))


def similar_commands(name: str, n: int = 5) -> list[str]:
    if not name:
        return []
    return difflib.get_close_matches(name, _path_binaries(), n=n, cutoff=0.6)


def first_token(command: str) -> str:
    """First program name, skipping FOO=bar prefixes."""
    cmd = command.strip()
    if not cmd:
        return ""
    parts = cmd.split()
    i = 0
    while i < len(parts) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", parts[i]):
        i += 1
    token = parts[i] if i < len(parts) else parts[0]
    return os.path.basename(token)


def diagnose_local(event: FailureEvent) -> Advice | None:
    """Return advice without calling a model when the failure is obvious."""
    output = event.output or ""
    command = event.command or ""
    token = first_token(command)

    if token and token not in _SHELL_BUILTINS and shutil.which(token) is None:
        if (
            (not output)
            or _COMMAND_NOT_FOUND.search(output)
            or event.exit_code in {127, 9009}
        ):
            guesses = similar_commands(token)
            suggestions = [
                Suggestion(
                    text=command.replace(token, guess, 1),
                    kind="command",
                    risk="low",
                    note=f"did you mean `{guess}`?",
                )
                for guess in guesses
            ]
            if not suggestions:
                suggestions = [
                    Suggestion(
                        text=f"type {token}",
                        kind="command",
                        risk="low",
                        note="check whether the binary exists and is on PATH",
                    )
                ]
            return Advice(
                cause=f"`{token}` is not on PATH (command not found).",
                suggestions=suggestions,
                detail="This was classified locally. No API call was made.",
                confidence="high",
                source="local",
                command=command,
                exit_code=event.exit_code,
            )

    if _PERMISSION.search(output):
        return Advice(
            cause="The process was denied permission to read, write, or execute something.",
            suggestions=[
                Suggestion(text=f"ls -ld -- {token or '.'}", kind="command", risk="low"),
                Suggestion(
                    text="# inspect ownership and modes; avoid chmod 777 and avoid sudo unless you trust the path",
                    kind="explanation",
                    risk="medium",
                ),
            ],
            detail=(
                "Permission errors are often a missing execute bit, a directory "
                "owned by root, or SELinux/AppArmor — not a missing package."
            ),
            confidence="medium",
            source="local",
            command=command,
            exit_code=event.exit_code,
        )

    port_match = re.search(r"port\s+(\d+)|:(\d+)\b", output, re.I)
    if _PORT_IN_USE.search(output):
        port = "PORT"
        if port_match:
            port = port_match.group(1) or port_match.group(2) or "PORT"
        return Advice(
            cause=f"Something is already bound to port {port}.",
            suggestions=[
                Suggestion(
                    text=f"ss -ltnp | grep :{port} || lsof -i :{port}",
                    kind="command",
                    risk="low",
                ),
                Suggestion(
                    text="# stop that process, or start your app on another port",
                    kind="explanation",
                    risk="low",
                ),
            ],
            confidence="high",
            source="local",
            command=command,
            exit_code=event.exit_code,
        )

    mod = _MODULE.search(output)
    if mod:
        name = mod.group("mod") or mod.group("nmod") or "that package"
        if mod.group("nmod"):
            install = f"npm install {name}"
        else:
            install = f"pip install {name}"
        return Advice(
            cause=f"Missing dependency: `{name}`.",
            suggestions=[
                Suggestion(text=install, kind="command", risk="low"),
                Suggestion(
                    text="# confirm you are in the intended virtualenv / node project before installing",
                    kind="explanation",
                    risk="low",
                ),
            ],
            confidence="high",
            source="local",
            command=command,
            exit_code=event.exit_code,
        )

    if _GIT_REJECT.search(output):
        return Advice(
            cause="The remote has commits you do not have locally, so a plain push was rejected.",
            suggestions=[
                Suggestion(text="git fetch origin && git status", kind="command", risk="low"),
                Suggestion(
                    text="git pull --rebase",
                    kind="command",
                    risk="medium",
                    note="rewrites local commits that have not been pushed",
                ),
                Suggestion(
                    text="# do not force-push shared branches unless the team agreed",
                    kind="explanation",
                    risk="high",
                ),
            ],
            confidence="high",
            source="local",
            command=command,
            exit_code=event.exit_code,
        )

    if _TS.search(output) or _RUST.search(output) or _SYNTAX.search(output) or _PIP_FAIL.search(output):
        return None
    return None