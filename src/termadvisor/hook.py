from __future__ import annotations

import os
from pathlib import Path

MARKER_BEGIN = "# >>> TermAdvisor hook >>>"
MARKER_END = "# <<< TermAdvisor hook <<<"


def detect_shell() -> str:
    name = os.environ.get("TERMADVISOR_SHELL") or os.environ.get("SHELL") or ""
    base = Path(name).name
    if base in {"bash", "zsh", "fish"}:
        return base
    return base or "bash"


def hook_snippet(shell: str) -> str:
    if shell == "zsh":
        return _ZSH
    if shell == "fish":
        return _FISH
    return _BASH


def rc_path_for(shell: str) -> Path:
    home = Path.home()
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR", home)) / ".zshrc"
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    for name in (".bashrc", ".bash_profile"):
        path = home / name
        if path.exists():
            return path
    return home / ".bashrc"


def install_hook(shell: str | None = None) -> Path:
    shell = shell or detect_shell()
    path = rc_path_for(shell)
    path.parent.mkdir(parents=True, exist_ok=True)
    block = f"\n{MARKER_BEGIN}\n{hook_snippet(shell).rstrip()}\n{MARKER_END}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if MARKER_BEGIN in existing:
        start = existing.index(MARKER_BEGIN)
        end = existing.index(MARKER_END) + len(MARKER_END) if MARKER_END in existing else len(existing)
        updated = existing[:start] + block.strip() + existing[end:]
        if not updated.endswith("\n"):
            updated += "\n"
    else:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        updated = existing + block
    path.write_text(updated, encoding="utf-8")
    return path


def uninstall_hook(shell: str | None = None) -> Path | None:
    shell = shell or detect_shell()
    path = rc_path_for(shell)
    if not path.exists():
        return None
    existing = path.read_text(encoding="utf-8")
    if MARKER_BEGIN not in existing:
        return path
    start = existing.index(MARKER_BEGIN)
    end = existing.index(MARKER_END) + len(MARKER_END) if MARKER_END in existing else len(existing)
    updated = existing[:start] + existing[end:]
    updated = updated.replace("\n\n\n", "\n\n")
    path.write_text(updated, encoding="utf-8")
    return path


_BASH = r'''
# Records the last command / exit code. Does not run suggested fixes.
_termadvisor_preexec() {
  TERMADVISOR_LAST_CMD="$1"
  TERMADVISOR_LAST_PWD="$PWD"
}
_termadvisor_prompt() {
  local _ta_ec=$?
  local _ta_cmd="${TERMADVISOR_LAST_CMD:-}"
  if [[ -z "$_ta_cmd" ]]; then
    _ta_cmd="$(HISTTIMEFORMAT= history 1 2>/dev/null | sed 's/^ *[0-9]* *//')"
  fi
  case "$_ta_cmd" in
    TermAdvisor*|termadvisor*) return $_ta_ec ;;
    "") return $_ta_ec ;;
  esac
  if command -v TermAdvisor >/dev/null 2>&1; then
    TermAdvisor __hook --exit "$_ta_ec" --command "$_ta_cmd" --cwd "${TERMADVISOR_LAST_PWD:-$PWD}" --shell bash >/dev/null 2>&1 &
  fi
  return $_ta_ec
}
if [[ -n "${bash_preexec_imported:-}" ]] || typeset -f preexec >/dev/null 2>&1; then
  preexec_functions+=(_termadvisor_preexec)
  precmd_functions+=(_termadvisor_prompt)
else
  _termadvisor_debug() {
    if [[ -n "$COMP_LINE" || -n "$READLINE_LINE" && "$BASH_COMMAND" == "$PROMPT_COMMAND" ]]; then
      return
    fi
    case "$BASH_COMMAND" in
      _termadvisor_*|TermAdvisor*|termadvisor*) return ;;
    esac
    TERMADVISOR_LAST_CMD="$BASH_COMMAND"
    TERMADVISOR_LAST_PWD="$PWD"
  }
  trap '_termadvisor_debug' DEBUG
  if [[ -z "${PROMPT_COMMAND:-}" ]]; then
    PROMPT_COMMAND="_termadvisor_prompt"
  elif [[ "$PROMPT_COMMAND" != *_termadvisor_prompt* ]]; then
    PROMPT_COMMAND="_termadvisor_prompt; $PROMPT_COMMAND"
  fi
fi
'''

_ZSH = r'''
_termadvisor_preexec() {
  TERMADVISOR_LAST_CMD="$1"
  TERMADVISOR_LAST_PWD="$PWD"
}
_termadvisor_precmd() {
  local _ta_ec=$?
  local _ta_cmd="${TERMADVISOR_LAST_CMD:-}"
  case "$_ta_cmd" in
    TermAdvisor*|termadvisor*) return ;;
    "") return ;;
  esac
  if command -v TermAdvisor >/dev/null 2>&1; then
    TermAdvisor __hook --exit "$_ta_ec" --command "$_ta_cmd" --cwd "${TERMADVISOR_LAST_PWD:-$PWD}" --shell zsh >/dev/null 2>&1 &
  fi
}
autoload -Uz add-zsh-hook 2>/dev/null || true
add-zsh-hook preexec _termadvisor_preexec 2>/dev/null || true
add-zsh-hook precmd _termadvisor_precmd 2>/dev/null || true
'''

_FISH = r'''
function _termadvisor_preexec --on-event fish_preexec
    set -g TERMADVISOR_LAST_CMD $argv
    set -g TERMADVISOR_LAST_PWD $PWD
end
function _termadvisor_postexec --on-event fish_postexec
    set -l _ta_ec $status
    set -l _ta_cmd $TERMADVISOR_LAST_CMD
    if test -z "$_ta_cmd"
        return
    end
    switch $_ta_cmd
        case 'TermAdvisor*' 'termadvisor*'
            return
    end
    if command -q TermAdvisor
        TermAdvisor __hook --exit $_ta_ec --command "$_ta_cmd" --cwd "$TERMADVISOR_LAST_PWD" --shell fish >/dev/null 2>&1 &
    end
end
'''