"""Layer 4: provider parse + advisor routing. Network is mocked."""

from __future__ import annotations

from pathlib import Path

from termadvisor.advisor import advise, build_payload
from termadvisor.config import AppConfig
from termadvisor.models import FailureEvent
from termadvisor.provider import parse_advice


def test_parse_plain_json():
    raw = """
    {
      "cause": "wrong type",
      "suggestions": [{"text": "Number(id)", "kind": "code", "risk": "low"}],
      "detail": "TS2345",
      "confidence": "high"
    }
    """
    advice = parse_advice(raw)
    assert advice.cause == "wrong type"
    assert advice.suggestions[0].text == "Number(id)"
    assert advice.source == "model"


def test_parse_fenced_json_promotes_destructive_risk():
    raw = """```json
    {"cause": "wipe", "suggestions": [{"text": "rm -rf /tmp/build", "risk": "low"}]}
    ```"""
    advice = parse_advice(raw)
    assert advice.suggestions[0].risk == "high"
    assert advice.suggestions[0].is_high_risk()


def test_parse_bullets_when_not_json():
    raw = "Something broke\n1. pip install requests\n2. retry the command"
    advice = parse_advice(raw)
    assert advice.confidence == "low"
    assert any("pip install requests" in s.text for s in advice.suggestions)


def test_advise_uses_local_router_and_never_calls_model(monkeypatch):
    called = {"n": 0}

    def boom(_cfg, _payload):
        called["n"] += 1
        raise AssertionError("model should not be called for command-not-found")

    monkeypatch.setattr("termadvisor.advisor.complete", boom)
    cfg = AppConfig()
    event = FailureEvent(
        command="gitt status",
        exit_code=127,
        cwd="/tmp",
        output="bash: gitt: command not found",
    )
    advice = advise(cfg, event)
    assert advice.source == "local"
    assert "not on PATH" in advice.cause
    assert called["n"] == 0


def test_advise_offline_skips_model_for_hard_errors():
    cfg = AppConfig()
    event = FailureEvent(
        command="npm run build",
        exit_code=2,
        cwd="/tmp",
        output="src/api.ts:41: error TS2345: Argument of type 'string'",
    )
    advice = advise(cfg, event, offline=True)
    assert advice.source == "offline"
    assert advice.suggestions == []


def test_advise_calls_model_when_trivial_returns_none(monkeypatch):
    monkeypatch.setattr(
        "termadvisor.advisor.complete",
        lambda _cfg, _payload: '{"cause": "string vs UserId", "suggestions": [{"text": "Number(parseId(id))", "kind": "code"}]}',
    )
    cfg = AppConfig()
    event = FailureEvent(
        command="npm run build",
        exit_code=2,
        cwd="/tmp",
        output="src/api.ts:41: error TS2345: Argument of type 'string'",
    )
    advice = advise(cfg, event)
    assert advice.source == "model"
    assert "UserId" in advice.cause
    assert advice.suggestions[0].text.startswith("Number(")
    assert advice.exit_code == 2


def test_build_payload_redacts_secrets_and_attaches_snippet(tmp_path: Path):
    src = tmp_path / "api.ts"
    src.write_text("const x = 1;\nconst secret = 'sk-abcdefghijklmnopqrstuvwxyz123456';\n")
    cfg = AppConfig()
    event = FailureEvent(
        command="OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456 npm run build",
        exit_code=2,
        cwd=str(tmp_path),
        output=f"{src}:2: error TS2345: Argument of type 'string'",
    )
    payload = build_payload(cfg, event)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in payload
    assert "[REDACTED]" in payload


def test_force_model_skips_local_even_for_typos(monkeypatch):
    monkeypatch.setattr(
        "termadvisor.advisor.complete",
        lambda _cfg, _payload: '{"cause": "from-model", "suggestions": []}',
    )
    cfg = AppConfig()
    event = FailureEvent(
        command="gitt status",
        exit_code=127,
        cwd="/tmp",
        output="bash: gitt: command not found",
    )
    advice = advise(cfg, event, force_model=True)
    assert advice.source == "model"
    assert advice.cause == "from-model"