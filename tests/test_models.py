from termadvisor.models import Advice, FailureEvent, Suggestion, looks_destructive


def test_suggestion_from_string_and_aliases():
    assert Suggestion.from_dict("echo hi").text == "echo hi"
    parsed = Suggestion.from_dict(
        {"command": "pip install requests", "risk": "LOW", "kind": "cmd"}
    )
    assert parsed.text == "pip install requests"
    assert parsed.risk == "low"
    assert parsed.kind == "command"


def test_destructive_text_is_promoted_to_high_risk():
    sug = Suggestion(text="git push --force origin main", risk="low")
    assert sug.is_high_risk()
    assert sug.risk == "high"
    assert looks_destructive("terraform destroy -auto-approve")


def test_advice_drops_empty_suggestions_and_roundtrips():
    advice = Advice(
        cause=" missing module ",
        suggestions=[
            Suggestion(text="pip install requests"),
            Suggestion(text=""),
        ],
        confidence="HIGH",
        command="python app.py",
        exit_code=1,
    )
    assert len(advice.suggestions) == 1
    assert advice.confidence == "high"
    clone = Advice.from_dict(advice.to_dict())
    assert clone.cause == "missing module"
    assert clone.suggestions[0].text == "pip install requests"


def test_failure_event_tail_truncates():
    event = FailureEvent(
        command="npm run build",
        exit_code=2,
        cwd="/tmp/app",
        output="\n".join(f"line {i}" for i in range(10)),
    )
    tail = event.tail(3)
    assert "line 9" in tail
    assert "line 0" not in tail
    assert "7 earlier lines omitted" in tail
    clone = FailureEvent.from_dict(event.to_dict())
    assert clone.command == "npm run build"
    assert clone.exit_code == 2