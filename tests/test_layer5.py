"""Layer 5: render the Advice card. No network, no CLI."""

from __future__ import annotations

from termadvisor.models import Advice, Suggestion
from termadvisor.render import card_text, copy_to_clipboard, format_card


def _sample() -> Advice:
    return Advice(
        cause="parseId() returns string; UserId expects a number.",
        suggestions=[
            Suggestion(text="Number(parseId(req.params.id))", kind="code", risk="low"),
            Suggestion(
                text="git push --force origin main",
                kind="command",
                risk="low",
                note="only if the team agreed",
            ),
        ],
        detail="TS2345 at src/api.ts:41",
        confidence="high",
        source="demo",
        model="nvidia/nemotron-3-super-120b-a12b",
        elapsed_s=2.1,
        exit_code=2,
        command="npm run build",
    )


def test_format_card_is_a_panel():
    from rich.panel import Panel

    assert isinstance(format_card(_sample()), Panel)


def test_card_text_contains_cause_command_and_suggestions():
    text = card_text(_sample())
    assert "TermAdvisor" in text
    assert "Cause:" in text
    assert "parseId()" in text
    assert "npm run build" in text
    assert "Number(parseId" in text
    assert "exit 2" in text
    assert "demo" in text
    assert "nemotron-3-super-120b-a12b" in text


def test_high_risk_suggestion_is_flagged():
    text = card_text(_sample())
    assert "DO NOT AUTO-RUN" in text
    assert "high risk" in text
    assert "only if the team agreed" in text


def test_empty_advice_still_renders():
    text = card_text(Advice(cause="nothing to add", source="offline", exit_code=1))
    assert "nothing to add" in text
    assert "Try:" not in text


def test_copy_to_clipboard_false_without_tools(monkeypatch):
    monkeypatch.setattr("termadvisor.render.shutil.which", lambda _name: None)
    assert copy_to_clipboard("git status") is False
    assert copy_to_clipboard("") is False