"""Settings and on-disk paths.

Layer 2a. Standard library only — does not import models.py —
so login/status/config-set can work before any failure exists.

Default locations (XDG, overridable):

* config: ``~/.config/TermAdvisor/config.toml``
  override with ``TERMADVISOR_CONFIG``
* cache:  ``~/.cache/TermAdvisor/``
  override with ``XDG_CACHE_HOME``

The config file is written mode 0600 because it may contain an API key.
"""

#puts the filled form in a drawer

from __future__ import annotations

import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomllib


APP_NAME = "TermAdvisor"

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_API_KEY_ENV = "NEBIUS_API_KEY"

MODEL_ALIASES = {
    "super": "nvidia/nemotron-3-super-120b-a12b",
    "nano": "nvidia/nemotron-3-nano-30b-a3b",
    "ultra": "nvidia/nemotron-3-ultra-550b-a55b",
    "lightning": "nvidia/nemotron-3.5-lightning",
}

SETTABLE: dict[str, tuple[str, str]] = {
    "watch": ("behavior", "watch"),
    "model": ("provider", "model"),
    "base_url": ("provider", "base_url"),
    "api_key": ("provider", "api_key"),
    "api_key_env": ("provider", "api_key_env"),
    "max_tail_lines": ("behavior", "max_tail_lines"),
    "redact": ("behavior", "redact"),
    "capture_output": ("behavior", "capture_output"),
    "local_first": ("behavior", "local_first"),
    "interactive": ("behavior", "interactive"),
    "upload_source_snippets": ("privacy", "upload_source_snippets"),
    "snippet_radius": ("privacy", "snippet_radius"),
    "timeout_s": ("provider", "timeout_s"),
    "max_tokens": ("provider", "max_tokens"),
}


def xdg_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def xdg_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".cache" / APP_NAME


def config_path() -> Path:
    override = os.environ.get("TERMADVISOR_CONFIG")
    if override:
        return Path(override).expanduser()
    return xdg_config_dir() / "config.toml"


@dataclass
class ProviderConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout_s: float = 60.0
    max_tokens: int = 1200
    temperature: float = 0.2


@dataclass
class BehaviorConfig:
    watch: bool = False
    max_tail_lines: int = 2000
    redact: bool = True
    capture_output: bool = False
    local_first: bool = True
    interactive: bool = True


@dataclass
class PrivacyConfig:
    upload_source_snippets: bool = True
    snippet_radius: int = 8
    max_snippet_files: int = 4


@dataclass
class AppConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)

    def resolved_model(self) -> str:
        raw = (self.provider.model or DEFAULT_MODEL).strip()
        return MODEL_ALIASES.get(raw.lower(), raw)

    def resolved_api_key(self) -> str:
        if self.provider.api_key:
            return self.provider.api_key
        env_name = self.provider.api_key_env or DEFAULT_API_KEY_ENV
        return os.environ.get(env_name, "") or os.environ.get("TERMADVISOR_API_KEY", "")

    def has_key(self) -> bool:
        return bool(self.resolved_api_key())


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _dump_toml(cfg: AppConfig) -> str:
    p, b, r = cfg.provider, cfg.behavior, cfg.privacy
    return "\n".join(
        [
            "[provider]",
            f'base_url = "{_escape(p.base_url)}"',
            f'api_key_env = "{_escape(p.api_key_env)}"',
            f'api_key = "{_escape(p.api_key)}"',
            f'model = "{_escape(p.model)}"',
            f"timeout_s = {float(p.timeout_s)}",
            f"max_tokens = {int(p.max_tokens)}",
            f"temperature = {float(p.temperature)}",
            "",
            "[behavior]",
            f"watch = {_bool(b.watch)}",
            f"max_tail_lines = {int(b.max_tail_lines)}",
            f"redact = {_bool(b.redact)}",
            f"capture_output = {_bool(b.capture_output)}",
            f"local_first = {_bool(b.local_first)}",
            f"interactive = {_bool(b.interactive)}",
            "",
            "[privacy]",
            f"upload_source_snippets = {_bool(r.upload_source_snippets)}",
            f"snippet_radius = {int(r.snippet_radius)}",
            f"max_snippet_files = {int(r.max_snippet_files)}",
            "",
        ]
    )


def _merge(section: dict[str, Any], target: object) -> None:
    for key, val in section.items():
        if not hasattr(target, key):
            continue
        current = getattr(target, key)
        if isinstance(current, bool):
            setattr(target, key, bool(val))
        elif isinstance(current, int) and not isinstance(current, bool):
            setattr(target, key, int(val))
        elif isinstance(current, float):
            setattr(target, key, float(val))
        else:
            setattr(target, key, val)


def load_config() -> AppConfig:
    path = config_path()
    cfg = AppConfig()
    if not path.exists():
        return cfg
    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw) if raw.strip() else {}
    if "provider" in data:
        _merge(data["provider"], cfg.provider)
    if "behavior" in data:
        _merge(data["behavior"], cfg.behavior)
    if "privacy" in data:
        _merge(data["privacy"], cfg.privacy)
    return cfg


def save_config(cfg: AppConfig) -> Path:
    path = config_path()
    _ensure_parent(path)
    path.write_text(_dump_toml(cfg), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def set_value(cfg: AppConfig, key: str, value: str) -> AppConfig:
    key = key.strip()
    if "=" in key and value == "":
        key, value = key.split("=", 1)
    if key not in SETTABLE:
        raise KeyError(f"Unknown setting '{key}'. Known: {', '.join(sorted(SETTABLE))}")
    section_name, field_name = SETTABLE[key]
    section = getattr(cfg, section_name)
    current = getattr(section, field_name)
    parsed: Any = value
    if isinstance(current, bool):
        parsed = value.strip().lower() in {"1", "true", "yes", "on"}
    elif isinstance(current, int) and not isinstance(current, bool):
        parsed = int(value)
    elif isinstance(current, float):
        parsed = float(value)
    setattr(section, field_name, parsed)
    return cfg


def cache_dir() -> Path:
    path = xdg_cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def as_public_dict(cfg: AppConfig) -> dict[str, Any]:
    data = asdict(cfg)
    key = data["provider"].get("api_key") or ""
    if key:
        data["provider"]["api_key"] = _mask(key)
    return data


def _mask(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "…" + key[-3:]