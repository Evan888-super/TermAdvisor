"""Layer 3: redact + context + trivial. No network."""

from __future__ import annotations

from pathlib import Path

from termadvisor.context import collect_snippets, extract_locations
from termadvisor.models import FailureEvent
from termadvisor.redact import looks_like_secret_file, redact_text
from termadvisor.trivial import diagnose_local, first_token


def test_redact_strips_common_secrets_and_keeps_the_rest():
    raw = """
Authorization: Bearer supersecrettokenvalue
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG
AKIAIOSFODNN7EXAMPLE
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA
-----END RSA PRIVATE KEY-----
postgres://user:hunter2@localhost/db
OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456
npm run build
"""
    out = redact_text(raw)
    assert "supersecrettokenvalue" not in out
    assert "wJalrXUtnFEMI" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "MIIEowIBAAKCAQEA" not in out
    assert "hunter2" not in out
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "npm run build" in out
    assert "[REDACTED]" in out


def test_secret_file_names_are_rejected_for_snippets():
    assert looks_like_secret_file("/tmp/project/.env")
    assert looks_like_secret_file("id_rsa")
    assert not looks_like_secret_file("src/api.ts")


def test_extract_locations_from_python_ts_and_rust():
    log = """
File "/tmp/demo/app.py", line 12, in <module>
  foo()
src/api.ts:41: error TS2345: Argument of type 'string'
--> src/main.rs:10:5
"""
    locs = extract_locations(log)
    paths = [p for p, _ in locs]
    assert any(p.endswith("app.py") for p in paths)
    assert any("api.ts" in p for p in paths)
    assert any("main.rs" in p for p in paths)


def test_collect_snippets_reads_file_and_redacts(tmp_path: Path):
    src = tmp_path / "broken.py"
    src.write_text("a = 1\nSECRET_TOKEN=sk-abcdefghijklmnopqrstuvwxyz123456\nraise ValueError('x')\n")
    log = f'File "{src}", line 3, in <module>\nValueError: x\n'
    snippets = collect_snippets(log, str(tmp_path), radius=1, max_files=2, redact=True)
    assert snippets
    assert "raise ValueError" in snippets[0]
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in snippets[0]


def test_collect_snippets_skips_env_files(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("PASSWORD=hunter2\n")
    log = f"{env}:1: something\n"
    snippets = collect_snippets(log, str(tmp_path), radius=2)
    assert snippets == []


def test_first_token_skips_env_assignments():
    assert first_token("FOO=1 BAR=2 git status") == "git"


def test_local_command_not_found():
    event = FailureEvent(
        command="gitt status",
        exit_code=127,
        cwd="/tmp",
        output="bash: gitt: command not found",
    )
    advice = diagnose_local(event)
    assert advice is not None
    assert advice.source == "local"
    assert "not on PATH" in advice.cause
    assert any("git" in s.text for s in advice.suggestions)


def test_local_port_in_use():
    event = FailureEvent(
        command="npm start",
        exit_code=1,
        cwd="/tmp",
        output="Error: listen EADDRINUSE: address already in use :::3000",
    )
    advice = diagnose_local(event)
    assert advice is not None
    assert "3000" in advice.cause


def test_local_missing_python_module():
    event = FailureEvent(
        command="python app.py",
        exit_code=1,
        cwd="/tmp",
        output="ModuleNotFoundError: No module named 'requests'",
    )
    advice = diagnose_local(event)
    assert advice is not None
    assert any("pip install requests" in s.text for s in advice.suggestions)


def test_local_missing_node_module():
    event = FailureEvent(
        command="node app.js",
        exit_code=1,
        cwd="/tmp",
        output="Error: Cannot find module 'express'",
    )
    advice = diagnose_local(event)
    assert advice is not None
    assert any("npm install express" in s.text for s in advice.suggestions)


def test_typescript_error_is_left_for_the_model():
    event = FailureEvent(
        command="npm run build",
        exit_code=2,
        cwd="/tmp",
        output="src/api.ts:41: error TS2345: Argument of type 'string' is not assignable",
    )
    assert diagnose_local(event) is None


def test_git_reject_does_not_suggest_force_push_as_safe():
    event = FailureEvent(
        command="git push",
        exit_code=1,
        cwd="/tmp",
        output="! [rejected] failed to push some refs\nupdates were rejected",
    )
    advice = diagnose_local(event)
    assert advice is not None
    risky = [s for s in advice.suggestions if s.is_high_risk()]
    assert risky
    assert all("force" not in s.text.lower() or s.risk == "high" for s in advice.suggestions)