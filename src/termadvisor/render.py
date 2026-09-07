"""Draw an Advice object as a terminal card.

Layer 5. Does not decide what the advice is. Does not call the model.
Does not run suggested commands.
"""

from __future__ import annotations

import shutil
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from termadvisor.models import Advice

console = Console(stderr=False)


def _risk_style(risk: str) -> str:
    return {"high": "bold red", "medium": "yellow", "low": "green"}.get(risk, "white")


def format_card(advice: Advice) -> Panel:
    body = Text()
    meta_bits = []
    if advice.exit_code is not None:
        meta_bits.append(f"exit {advice.exit_code}")
    if advice.elapsed_s:
        meta_bits.append(f"{advice.elapsed_s:.1f}s")
    if advice.source:
        meta_bits.append(advice.source)
    if advice.model:
        meta_bits.append(advice.model.split("/")[-1])
    if meta_bits:
        body.append(" · ".join(meta_bits), style="dim")
        body.append("\n")

    if advice.command:
        body.append("cmd  ", style="dim")
        body.append(advice.command.strip()[:200], style="italic")
        body.append("\n")

    body.append("Cause: ", style="bold")
    body.append(advice.cause.strip() or "(none)")
    body.append("\n")

    if advice.suggestions:
        body.append("Try:\n", style="bold")
        for i, sug in enumerate(advice.suggestions, start=1):
            body.append(f"  {i}. ", style="bold cyan")
            body.append(sug.text.strip())
            tags = []
            if sug.kind and sug.kind != "command":
                tags.append(sug.kind)
            if sug.risk and sug.risk != "low":
                tags.append(sug.risk + " risk")
            if sug.is_high_risk():
                tags.append("DO NOT AUTO-RUN")
            if tags:
                body.append("  [" + ", ".join(tags) + "]", style=_risk_style(sug.risk))
            body.append("\n")
            if sug.note:
                body.append(f"      {sug.note}\n", style="dim")

    return Panel(body, title="TermAdvisor", border_style="cyan", padding=(0, 1))


def card_text(advice: Advice, width: int = 80) -> str:
    """Plain-text rendering of the card, for tests and logs."""
    buf = Console(record=True, width=width, color_system=None, highlight=False)
    buf.print(format_card(advice))
    return buf.export_text()


def show_card(advice: Advice) -> None:
    console.print(format_card(advice))


def show_detail(advice: Advice) -> None:
    if advice.detail:
        console.print(Panel(advice.detail.strip(), title="More detail", border_style="blue"))
    else:
        console.print("[dim]No extra detail from this diagnosis.[/dim]")


def copy_to_clipboard(text: str) -> bool:
    if not text:
        return False
    pbcopy = shutil.which("pbcopy")
    xclip = shutil.which("xclip")
    xsel = shutil.which("xsel")
    wl = shutil.which("wl-copy")
    try:
        if pbcopy:
            import subprocess

            subprocess.run([pbcopy], input=text.encode(), check=False)
            return True
        if wl:
            import subprocess

            subprocess.run([wl], input=text.encode(), check=False)
            return True
        if xclip:
            import subprocess

            subprocess.run(
                ["xclip", "-selection", "clipboard"], input=text.encode(), check=False
            )
            return True
        if xsel:
            import subprocess

            subprocess.run(
                ["xsel", "--clipboard", "--input"], input=text.encode(), check=False
            )
            return True
    except OSError:
        return False
    return False


def interact(advice: Advice) -> None:
    show_card(advice)
    if not advice.suggestions:
        if advice.detail:
            show_detail(advice)
        return
    if not sys.stdin.isatty():
        return
    n = len(advice.suggestions)
    console.print(
        f"[c] copy 1   [1-{n}] copy N   [e] more detail   [n] dismiss",
        style="dim",
    )
    try:
        choice = input().strip().lower()
    except EOFError:
        return
    if choice in {"n", "q", ""}:
        return
    if choice == "e":
        show_detail(advice)
        return
    index = 1
    if choice.startswith("c"):
        rest = choice[1:].strip()
        if rest.isdigit():
            index = int(rest)
    elif choice.isdigit():
        index = int(choice)
    else:
        return
    if not (1 <= index <= n):
        console.print("[red]No such suggestion.[/red]")
        return
    text = advice.suggestions[index - 1].text
    if copy_to_clipboard(text):
        console.print(f"[green]Copied suggestion {index} to the clipboard.[/green]")
    else:
        console.print("[yellow]Clipboard tool not found. Paste this yourself:[/yellow]")
        console.print(text)