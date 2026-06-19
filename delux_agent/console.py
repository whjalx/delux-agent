"""Beautiful terminal output using rich."""

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

delux_theme = Theme({
    "info": "dim white",
    "success": "green",
    "error": "red",
    "warning": "yellow",
    "action": "cyan",
    "edit": "yellow",
    "file": "cyan",
    "search": "magenta",
    "dim": "dim white",
    "model": "bold cyan",
    "title": "bold magenta",
    "path": "dim italic",
})

console = Console(theme=delux_theme, highlight=False)


def make_banner(provider: str, model: str, flags: list[str], w: int | None = None) -> Panel:
    title = Text()
    title.append("  delux  ", style="title")
    title.append(f"{provider} · {model}", style="model")
    if flags:
        title.append(f"  ", style="")
        title.append("  ".join(flags), style="dim")
    return Panel(title, box=box.ROUNDED, padding=(0, 0), border_style="dim")


def make_action_line(kind: str, detail: str = "", detail_style: str = "dim") -> Text:
    t = Text()
    t.append("  ")
    t.append("→", style="dim")
    t.append(" ")
    t.append(kind, style=detail_style)
    if detail:
        t.append("  ", style="")
        t.append(detail, style="dim")
    return t


def make_success(msg: str) -> Text:
    t = Text()
    t.append("  ")
    t.append("✓", style="success")
    t.append("  ", style="")
    t.append(msg, style="dim")
    return t


def make_error(msg: str) -> Text:
    t = Text()
    t.append("  ")
    t.append("✗", style="error")
    t.append("  ", style="")
    t.append(msg, style="error")
    return t


def make_plan_box(steps: list[dict], summary: str, progress: str) -> Panel:
    table = Table.grid(padding=(0, 1))
    for s in steps:
        sid = s.get("id", "?")
        desc = s.get("description", "")
        status = s.get("status", "pending")
        if status == "done":
            icon = "✓"
            style = "success"
        elif status == "running":
            icon = "◌"
            style = "warning"
        elif status == "failed":
            icon = "✗"
            style = "error"
        elif status == "skipped":
            icon = "⊙"
            style = "dim"
        else:
            icon = "·"
            style = "dim"
        table.add_row(
            Text(f"  {icon}", style=style),
            Text(f"{sid}.", style="dim"),
            Text(desc, style=style if status == "running" else ""),
        )
    if progress:
        table.add_row("", "", "")
        table.add_row("  ", Text(progress, style="info"), "")
    return Panel(
        table,
        title=Text(f" plan ", style="bold magenta"),
        box=box.ROUNDED,
        border_style="dim",
        padding=(0, 0),
    )
