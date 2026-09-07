"""Layer 6: CLI + hook snippets. Isolated HOME / config / cache."""

from __future__ import annotations

from typer.testing import CliRunner

from termadvisor.cli import app
from termadvisor.hook import MARKER_BEGIN, hook_snippet, install_hook, uninstall_hook

runner = CliRunner()


def _isolate(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv(
        "TERMADVISOR_CONFIG",
        str(tmp_path / "config" / "TermAdvisor" / "config.toml"),
    )
    return home


def test_demo_prints_card(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "TermAdvisor" in result.stdout
    assert "parseId()" in result.stdout


def test_login_on_off_status_and_config_set(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert runner.invoke(app, ["login", "--key", "sk-test-not-real-0123456789abcdef"]).exit_code == 0
    assert runner.invoke(app, ["on"]).exit_code == 0
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "yes" in status.stdout
    assert runner.invoke(app, ["config", "set", "model=nano"]).exit_code == 0
    assert "nano" in runner.invoke(app, ["status"]).stdout


def test_explain_offline_command_not_found(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        ["explain", "--offline", "--no-interact", "--command", "gitt status", "--exit", "127"],
        input="bash: gitt: command not found\n",
    )
    assert result.exit_code == 0
    assert "not on PATH" in result.stdout
    assert "gitt status" in runner.invoke(app, ["last"]).stdout


def test_explain_offline_typescript_is_placeholder(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        ["explain", "--offline", "--no-interact", "--command", "npm run build", "--exit", "2"],
        input="src/api.ts:41: error TS2345: Argument of type 'string'\n",
    )
    assert result.exit_code == 0
    assert "Offline mode" in result.stdout


def test_init_print_and_hook_install(monkeypatch, tmp_path):
    home = _isolate(monkeypatch, tmp_path)
    printed = runner.invoke(app, ["init", "--shell", "bash", "--print"])
    assert printed.exit_code == 0
    assert "TermAdvisor __hook" in printed.stdout
    path = install_hook("bash")
    assert MARKER_BEGIN in path.read_text(encoding="utf-8")
    assert path == home / ".bashrc"
    uninstall_hook("bash")
    assert MARKER_BEGIN not in path.read_text(encoding="utf-8")


def test_hook_records_but_stays_quiet_when_watch_off(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        ["__hook", "--exit", "127", "--command", "gitt status", "--cwd", "/tmp", "--shell", "bash"],
    )
    assert result.exit_code == 0
    assert "gitt status" in runner.invoke(app, ["last"]).stdout
    assert "not on PATH" not in result.stdout