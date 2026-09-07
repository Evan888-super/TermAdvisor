from __future__ import annotations

import os
import select
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table

from termadvisor import __version__
from termadvisor.advisor import advise
from termadvisor.capture import load_event, save_event
from termadvisor.config import (
    AppConfig,
    as_public_dict,
    config_path,
    load_config,
    save_config,
    set_value,
)
from termadvisor.hook import detect_shell, hook_snippet, install_hook, uninstall_hook
from termadvisor.models import FailureEvent
from termadvisor.render import interact, show_card

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="TermAdvisor — suggestions-only terminal advisor. It never runs your commands.",
)
config_app = typer.Typer(help="Read or change settings in ~/.config/TermAdvisor/config.toml")
app.add_typer(config_app, name="config")
console = Console()
err = Console(stderr=True)


def _cfg() -> AppConfig:
    return load_config()


def _stdin_has_data() -> bool:
    if sys.stdin is None or sys.stdin.closed:
        return False
    if not sys.stdin.isatty():
        return True
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(ready)
    except (OSError, ValueError):
        return False


def _read_stdin() -> str:
    if not _stdin_has_data():
        return ""
    try:
        return sys.stdin.read()
    except OSError:
        return ""


def _event_from_inputs(
    command: str | None,
    exit_code: int | None,
    cwd: str | None,
    output: str | None,
) -> FailureEvent:
    stored = load_event()
    return FailureEvent(
        command=command if command is not None else (stored.command if stored else ""),
        exit_code=exit_code if exit_code is not None else (stored.exit_code if stored else 1),
        cwd=cwd or (stored.cwd if stored else os.getcwd()),
        output=output if output is not None else (stored.output if stored else ""),
        shell=stored.shell if stored else "",
        started_at=stored.started_at if stored else None,
        finished_at=stored.finished_at if stored else None,
    )


@app.callback()
def _root() -> None:
    """TermAdvisor CLI."""


@app.command()
def version() -> None:
    """Print the package version."""
    console.print(__version__)


@app.command()
def login(
    key: Optional[str] = typer.Option(None, "--key", help="API key (otherwise you will be prompted)"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="OpenAI-compatible base URL"),
    model: Optional[str] = typer.Option(None, "--model", help="Model id or alias: super | nano | ultra"),
) -> None:
    """Store an API key once. Later sessions reuse ~/.config/TermAdvisor/config.toml."""
    cfg = _cfg()
    if base_url:
        cfg.provider.base_url = base_url
    if model:
        cfg.provider.model = model
    if key is None:
        console.print(
            "Paste a key for Nebius Token Factory, NVIDIA NIM, OpenRouter, "
            "or any OpenAI-compatible host."
        )
        console.print(f"Default endpoint: [cyan]{cfg.provider.base_url}[/cyan]")
        try:
            key = typer.prompt("API key", hide_input=True)
        except typer.Abort:
            raise typer.Exit(1)
    key = (key or "").strip()
    if not key:
        err.print("[red]Empty key — nothing stored.[/red]")
        raise typer.Exit(1)
    cfg.provider.api_key = key
    path = save_config(cfg)
    console.print(f"Saved credentials to [cyan]{path}[/cyan] (mode 0600).")
    console.print("You can also export [cyan]NEBIUS_API_KEY[/cyan] instead of storing the key on disk.")


@app.command()
def init(
    shell: Optional[str] = typer.Option(None, "--shell", help="bash | zsh | fish (auto-detected)"),
    print_only: bool = typer.Option(False, "--print", help="Print the hook instead of editing an rc file"),
) -> None:
    """Install a shell hook that records the last command and exit code."""
    shell = (shell or detect_shell()).lower()
    if shell not in {"bash", "zsh", "fish"}:
        err.print(f"[red]Unsupported shell '{shell}'. Use bash, zsh, or fish.[/red]")
        raise typer.Exit(2)
    if print_only:
        console.print(hook_snippet(shell))
        return
    path = install_hook(shell)
    console.print(f"Hook installed for [cyan]{shell}[/cyan] in [cyan]{path}[/cyan].")
    console.print("Open a new terminal (or source that file) for it to take effect.")
    console.print("Watching stays [yellow]off[/yellow] until you run [cyan]TermAdvisor on[/cyan].")


@app.command("uninit")
def uninit(
    shell: Optional[str] = typer.Option(None, "--shell"),
) -> None:
    """Remove the TermAdvisor block from your shell rc file."""
    path = uninstall_hook(shell)
    if path is None:
        console.print("No rc file found.")
        return
    console.print(f"Hook removed from [cyan]{path}[/cyan].")


@app.command()
def on() -> None:
    """Turn on automatic advice after a failed command."""
    cfg = _cfg()
    cfg.behavior.watch = True
    save_config(cfg)
    console.print("Watching [green]on[/green]. Failed commands can show a suggestion card.")
    console.print("[dim]Successful commands stay silent. Nothing is executed for you.[/dim]")


@app.command()
def off() -> None:
    """Silence automatic cards. `explain` / `ask` still work."""
    cfg = _cfg()
    cfg.behavior.watch = False
    save_config(cfg)
    console.print("Watching [yellow]off[/yellow]. Use [cyan]TermAdvisor explain[/cyan] when you want advice.")


@app.command()
def status(
    quiet_watch: bool = typer.Option(
        False,
        "--quiet-watch",
        hidden=True,
        help="Exit 0 if watch is on, 1 otherwise.",
    ),
) -> None:
    """Show on/off, model, and whether a key is present."""
    cfg = _cfg()
    if quiet_watch:
        raise typer.Exit(0 if cfg.behavior.watch else 1)
    table = Table(title="TermAdvisor status", show_header=False)
    table.add_column("k", style="dim")
    table.add_column("v")
    table.add_row("version", __version__)
    table.add_row("config", str(config_path()))
    table.add_row("watch", "on" if cfg.behavior.watch else "off")
    table.add_row("model", cfg.resolved_model())
    table.add_row("base_url", cfg.provider.base_url)
    table.add_row("api_key_env", cfg.provider.api_key_env)
    table.add_row("key present", "yes" if cfg.has_key() else "no")
    table.add_row("redact", "on" if cfg.behavior.redact else "off")
    table.add_row("local_first", "on" if cfg.behavior.local_first else "off")
    table.add_row("source snippets", "on" if cfg.privacy.upload_source_snippets else "off")
    event = load_event()
    if event:
        table.add_row("last command", event.command or "(empty)")
        table.add_row("last exit", str(event.exit_code))
    console.print(table)


@app.command()
def explain(
    command: Optional[str] = typer.Option(None, "--command", "-c", help="Override the recorded command"),
    exit_code: Optional[int] = typer.Option(None, "--exit", "-x", help="Override the recorded exit code"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory to send"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Read a log file instead of stdin / last output"),
    offline: bool = typer.Option(False, "--offline", help="Only use local rules; never call the model"),
    force_model: bool = typer.Option(False, "--model-only", help="Skip local trivial routing"),
    no_interact: bool = typer.Option(False, "--no-interact", help="Print the card and exit"),
) -> None:
    """Explain the last failure, a piped log, or a log file."""
    cfg = _cfg()
    piped = _read_stdin()
    file_text = ""
    if file is not None:
        file_text = file.read_text(encoding="utf-8", errors="replace")
    output = file_text or piped or None
    event = _event_from_inputs(command, exit_code, cwd, output)
    if not event.command and not event.output:
        err.print("[red]Nothing to explain.[/red] Pipe a log, pass --file, or run a command after `TermAdvisor init`.")
        raise typer.Exit(2)
    _run_advice(cfg, event, offline=offline, force_model=force_model, no_interact=no_interact)


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the last command, a log, or a general terminal issue"),
    command: Optional[str] = typer.Option(None, "--command", "-c"),
    exit_code: Optional[int] = typer.Option(None, "--exit", "-x"),
    offline: bool = typer.Option(False, "--offline"),
    no_interact: bool = typer.Option(False, "--no-interact"),
) -> None:
    """Ask a question. Uses the last recorded failure as context when present."""
    cfg = _cfg()
    piped = _read_stdin()
    event = _event_from_inputs(command, exit_code, None, piped or None)
    if not event.command and not event.output:
        event.command = question
        event.exit_code = 1
    _run_advice(
        cfg,
        event,
        question=question,
        offline=offline,
        force_model=True,
        no_interact=no_interact,
    )


@app.command()
def wrap(
    args: list[str] = typer.Argument(..., help="Command to run"),
    offline: bool = typer.Option(False, "--offline"),
    no_interact: bool = typer.Option(False, "--no-interact"),
) -> None:
    """Run a command yourself-style: capture output, then advise if it fails. Does not apply fixes."""
    import subprocess

    if not args:
        raise typer.Exit(2)
    cfg = _cfg()
    proc = subprocess.run(args, text=True, capture_output=True)
    combined = ""
    if proc.stdout:
        sys.stdout.write(proc.stdout)
        combined += proc.stdout
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        if combined and not combined.endswith("\n"):
            combined += "\n"
        combined += proc.stderr
    event = FailureEvent(
        command=" ".join(args),
        exit_code=int(proc.returncode),
        cwd=os.getcwd(),
        output=combined,
        shell="wrap",
    )
    save_event(event)
    if proc.returncode == 0:
        raise typer.Exit(0)
    _run_advice(cfg, event, offline=offline, no_interact=no_interact)
    raise typer.Exit(proc.returncode)


@app.command("last")
def last_cmd() -> None:
    """Show the last recorded command / exit / output tail."""
    event = load_event()
    if not event:
        console.print("No command recorded yet. Run [cyan]TermAdvisor init[/cyan] or [cyan]TermAdvisor wrap -- …[/cyan].")
        raise typer.Exit(1)
    console.print(f"[dim]cwd[/dim]  {event.cwd}")
    console.print(f"[dim]exit[/dim] {event.exit_code}")
    console.print(f"[dim]cmd[/dim]  {event.command}")
    if event.output:
        tail = event.tail(40)
        console.print("[dim]out[/dim]")
        console.print(tail)


@app.command()
def demo() -> None:
    """Print a sample suggestion card (no network)."""
    from termadvisor.models import Advice, Suggestion

    advice = Advice(
        cause="parseId() returns string; UserId expects a number.",
        suggestions=[
            Suggestion(text="Number(parseId(req.params.id))", kind="code", risk="low"),
            Suggestion(text="Widen UserId to string (API-wide; riskier)", kind="code", risk="medium"),
        ],
        detail="TypeScript TS2345 at src/api.ts:41 — the helper and the branded type disagree.",
        confidence="high",
        source="demo",
        model="nvidia/nemotron-3-super-120b-a12b",
        elapsed_s=2.1,
        exit_code=2,
        command="npm run build",
    )
    show_card(advice)
    console.print("[dim]This is a canned example. Real cards come from `explain` / `ask` / watch mode.[/dim]")


@config_app.command("show")
def config_show() -> None:
    """Print the current config (API key masked)."""
    cfg = _cfg()
    console.print(Pretty(as_public_dict(cfg)))


@config_app.command("path")
def config_path_cmd() -> None:
    """Print the config file path."""
    console.print(str(config_path()))


@config_app.command("set")
def config_set(
    assignment: str = typer.Argument(..., help="key=value  e.g. watch=off  model=nano"),
) -> None:
    """Change one setting. Example: TermAdvisor config set watch=off"""
    cfg = _cfg()
    if "=" not in assignment:
        err.print("Use key=value, for example watch=off or model=super")
        raise typer.Exit(2)
    key, value = assignment.split("=", 1)
    try:
        set_value(cfg, key, value)
    except KeyError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    save_config(cfg)
    console.print(f"Set [cyan]{key}[/cyan] = [cyan]{value}[/cyan]")


@app.command("__hook", hidden=True)
def hook_entry(
    exit_code: int = typer.Option(..., "--exit"),
    command: str = typer.Option("", "--command"),
    cwd: str = typer.Option("", "--cwd"),
    shell: str = typer.Option("", "--shell"),
) -> None:
    """Called from the shell hook. Records the event; advises only when watch is on and the command failed."""
    cfg = _cfg()
    existing = load_event()
    output = existing.output if existing and existing.command == command else ""
    event = FailureEvent(
        command=command,
        exit_code=exit_code,
        cwd=cwd or os.getcwd(),
        output=output,
        shell=shell,
    )
    save_event(event)
    if exit_code == 0 or not cfg.behavior.watch:
        raise typer.Exit(0)
    if os.environ.get("TERMADVISOR_SILENT") == "1":
        raise typer.Exit(0)
    try:
        advice = advise(cfg, event)
    except Exception as exc:
        err.print(f"[dim]TermAdvisor skipped: {exc}[/dim]")
        raise typer.Exit(0)
    show_card(advice)
    raise typer.Exit(0)


def _run_advice(
    cfg: AppConfig,
    event: FailureEvent,
    *,
    question: str | None = None,
    offline: bool = False,
    force_model: bool = False,
    no_interact: bool = False,
) -> None:
    save_event(event)
    try:
        advice = advise(
            cfg,
            event,
            question=question,
            force_model=force_model,
            offline=offline,
        )
    except Exception as exc:
        err.print(f"[red]TermAdvisor could not get advice:[/red] {exc}")
        raise typer.Exit(1)
    if no_interact or not cfg.behavior.interactive:
        show_card(advice)
        return
    interact(advice)