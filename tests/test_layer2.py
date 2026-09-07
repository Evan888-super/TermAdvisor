"""Layer 1 + layer 2: models, config, capture.

Isolates disk with TERMADVISOR_CONFIG and XDG_CACHE_HOME so a test
never writes into the developer's real home directory.
"""

from __future__ import annotations

import stat

from termadvisor.capture import load_event, load_history, save_event, update_output
from termadvisor.config import (
    AppConfig,
    as_public_dict,
    load_config,
    save_config,
    set_value,
)
from termadvisor.models import FailureEvent


def test_config_roundtrip_permissions_and_alias(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setenv("TERMADVISOR_CONFIG", str(cfg_file))

    cfg = AppConfig()
    cfg.provider.api_key = "secret-key-value"
    set_value(cfg, "watch", "on")
    set_value(cfg, "model", "nano")
    set_value(cfg, "max_tail_lines", "80")
    save_config(cfg)

    mode = cfg_file.stat().st_mode
    assert mode & stat.S_IRWXG == 0
    assert mode & stat.S_IRWXO == 0

    loaded = load_config()
    assert loaded.behavior.watch is True
    assert loaded.behavior.max_tail_lines == 80
    assert loaded.provider.api_key == "secret-key-value"
    assert loaded.resolved_model().endswith("nano-30b-a3b")
    assert loaded.has_key() is True


def test_config_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMADVISOR_CONFIG", str(tmp_path / "missing.toml"))
    cfg = load_config()
    assert cfg.behavior.watch is False
    assert cfg.behavior.redact is True
    assert cfg.has_key() is False


def test_config_masks_key_and_reads_env(monkeypatch):
    cfg = AppConfig()
    cfg.provider.api_key = "abcdefghijklmnop"
    public = as_public_dict(cfg)
    assert "abcdefghijklmnop" not in public["provider"]["api_key"]

    cfg.provider.api_key = ""
    monkeypatch.setenv("NEBIUS_API_KEY", "from-env")
    assert cfg.resolved_api_key() == "from-env"


def test_capture_uses_failure_event_dict_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    original = FailureEvent(
        command="npm run build",
        exit_code=2,
        cwd="/tmp/app",
        output="error TS2345\nmore",
        shell="zsh",
    )
    save_event(original)
    loaded = load_event()
    assert loaded is not None
    assert loaded.command == original.command
    assert loaded.exit_code == original.exit_code
    assert loaded.cwd == original.cwd
    assert loaded.output == original.output
    assert loaded.shell == original.shell
    assert loaded.finished_at is not None
    assert loaded.to_dict()["command"] == "npm run build"


def test_capture_can_attach_log_after_command(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    save_event(FailureEvent(command="gitt status", exit_code=127, cwd="/tmp"))
    update_output("bash: gitt: command not found\n")
    loaded = load_event()
    assert loaded is not None
    assert loaded.command == "gitt status"
    assert "command not found" in loaded.output


def test_history_omits_full_log_and_missing_cache_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    save_event(
        FailureEvent(
            command="false",
            exit_code=1,
            cwd="/tmp",
            output="this should not be in history",
        )
    )
    rows = load_history()
    assert len(rows) == 1
    assert rows[0]["command"] == "false"
    assert rows[0]["exit_code"] == 1
    assert "this should not" not in str(rows[0])

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty"))
    assert load_event() is None
    assert load_history() == []