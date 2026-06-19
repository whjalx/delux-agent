"""
Sidebar panel for Delux IDE — right-side info panel style Claude Code.

Layout:
┌──────────────────────────────────────────┬────────────────────┐
│                                          │ ◈ PLAN  3/8        │
│  Main output + input area                │ ▓▓▓▓▓░░░░ 38%     │
│  (scroll region)                         │                    │
│                                          │ → Step 4: verify  │
│                                          │ ▶ shell: nginx    │
│                                          │ ────────────────  │
│                                          │ 📁 /home/user/prj │
│                                          │ ◉ gemma4-manual   │
│                                          │ 🇬🇧 en  V:off     │
└──────────────────────────────────────────┴────────────────────┘

The sidebar uses ANSI escape codes to maintain a fixed right panel while
the left side scrolls normally.
"""
from __future__ import annotations

import sys
from typing import Any

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[0m"
GRAY = "\033[38;5;245m"
WHITE = "\033[97m"


class SidebarState:
    """Mutable state for the sidebar, updated by events."""
    def __init__(self) -> None:
        self.visible: bool = True
        self.width: int = 38
        self.plan_progress: str = ""
        self.plan_step: str = ""
        self.plan_steps_list: list[dict] = []  # [{id, desc, status}, ...]
        self.current_action: str = ""
        self.cwd: str = ""
        self.model_name: str = ""
        self.lang: str = ""
        self.validate_mode: str = ""
        self.training_mode: bool = False
        self.ctx_enabled: bool = False
        self.mcp_servers: int = 0
        self.running: bool = False


def _term_width() -> int:
    import shutil
    return shutil.get_terminal_size((80, 24)).columns


def _term_height() -> int:
    import shutil
    return shutil.get_terminal_size((80, 24)).lines


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)


def _build_progress_bar(done: int, total: int, width: int = 16) -> str:
    if total == 0:
        return "░" * width
    filled = int(width * done / total)
    pct = int(100 * done / total)
    bar = f"{GREEN}{'▓' * filled}{RESET}{DIM}{'░' * (width - filled)}{RESET}"
    return f"{bar} {YELLOW}{pct}%{RESET}"


def draw_sidebar(state: SidebarState) -> None:
    """Draw the sidebar panel on the right side of the terminal."""
    if not state.visible:
        return

    w = _term_width()
    h = _term_height()
    sw = state.width
    left_w = w - sw

    if left_w < 40:
        # Terminal too narrow — don't draw sidebar
        return

    # Save cursor position
    sys.stdout.write("\x1b7")

    # Draw each row of the sidebar
    rows = _build_sidebar_rows(state, sw)
    for row_idx, row_content in enumerate(rows):
        if row_idx >= h - 1:  # leave bottom row for input
            break
        # Move cursor to the right panel at this row
        sys.stdout.write(f"\x1b[{row_idx + 1};{left_w + 1}H")
        # Clear to end of line
        sys.stdout.write("\x1b[K")
        # Write the row content
        sys.stdout.write(row_content)

    # Draw vertical separator line
    for row_idx in range(min(h - 1, len(rows) + 2)):
        sys.stdout.write(f"\x1b[{row_idx + 1};{left_w}H")
        sys.stdout.write(f"{DIM}│{RESET}")

    # Restore cursor position
    sys.stdout.write("\x1b8")
    sys.stdout.flush()


def _build_sidebar_rows(state: SidebarState, sw: int) -> list[str]:
    rows: list[str] = []

    # ── Plan section ──
    if state.plan_progress or state.running:
        rows.append(f"  {MAGENTA}{BOLD}◈ PLAN{RESET}")
        if state.plan_progress and "/" in state.plan_progress:
            try:
                done, total = state.plan_progress.split("/")
                rows.append(f"  {_build_progress_bar(int(done), int(total))}")
            except ValueError:
                pass
        if state.plan_step:
            rows.append(f"  {YELLOW}→{RESET} {state.plan_step[:sw - 6]}")
        rows.append(f"{DIM}{'─' * (sw - 2)}{RESET}")

    # ── Steps list ──
    if state.plan_steps_list:
        for s in state.plan_steps_list[:8]:
            sid = s.get("id", "?")
            desc = s.get("desc", "")[:sw - 8]
            status = s.get("status", "pending")
            if status == "done":
                icon = f"{GREEN}✓{RESET}"
            elif status == "skipped":
                icon = f"{YELLOW}⏭{RESET}"
            elif status == "failed":
                icon = f"{RED}✗{RESET}"
            elif status == "running":
                icon = f"{YELLOW}◐{RESET}"
            else:
                icon = f"{DIM}○{RESET}"
            rows.append(f"  {icon} {DIM}{sid}.{RESET} {desc}")
        if len(state.plan_steps_list) > 8:
            rows.append(f"  {DIM}...+{len(state.plan_steps_list) - 8} more{RESET}")
        rows.append(f"{DIM}{'─' * (sw - 2)}{RESET}")

    # ── Current action ──
    if state.current_action:
        rows.append(f"  {GREEN}▶{RESET} {state.current_action[:sw - 6]}")
        rows.append(f"{DIM}{'─' * (sw - 2)}{RESET}")

    # ── Environment ──
    env_rows: list[str] = []
    if state.cwd:
        # Shorten cwd
        home = str(Path.home()) if 'Path' in globals() else ""
        cwd_short = state.cwd
        try:
            from pathlib import Path as _P
            h = str(_P.home())
            if cwd_short.startswith(h):
                cwd_short = "~" + cwd_short[len(h):]
        except Exception:
            pass
        env_rows.append(f"  {GRAY}📁 {RESET}{cwd_short[:sw - 8]}")
    if state.model_name:
        env_rows.append(f"  {GRAY}◉ {RESET}{state.model_name[:sw - 8]}")
    if state.lang:
        v = f"V:{state.validate_mode}" if state.validate_mode else ""
        parts = [f"{GRAY}🌐 {RESET}{state.lang}"]
        if v:
            parts.append(f"{GRAY}{v}{RESET}")
        env_rows.append("  ".join(parts))
    if state.mcp_servers > 0:
        env_rows.append(f"  {GRAY}⚡ {RESET}MCP:{state.mcp_servers}")
    if state.training_mode:
        env_rows.append(f"  {YELLOW}🏋️ training{RESET}")
    if state.ctx_enabled:
        env_rows.append(f"  {CYAN}⚙ ctx{RESET}")

    rows.extend(env_rows)

    # Pad remaining rows to fill terminal height
    h = _term_height()
    while len(rows) < h - 2:
        rows.append("")

    return rows


def clear_sidebar() -> None:
    """Clear the sidebar area."""
    w = _term_width()
    h = _term_height()
    sys.stdout.write("\x1b7")
    for row in range(h - 1):
        sys.stdout.write(f"\x1b[{row + 1};{w - 38 + 1}H\x1b[K")
    sys.stdout.write("\x1b8")
    sys.stdout.flush()


def init_split(state: SidebarState) -> None:
    """Initialize terminal for split layout — set scroll region."""
    if not state.visible:
        return
    w = _term_width()
    left_w = w - state.width
    if left_w < 40:
        state.visible = False
        return
    # Set scroll region to only the left area (columns 0 to left_w-1)
    # Note: ANSI doesn't support column-based scroll regions, only row-based.
    # We work around this by redrawing the sidebar after each output.
    # The terminal will scroll full width, so we redraw sidebar rows.


def redraw_after_output(state: SidebarState) -> None:
    """Call after any print() to restore the sidebar."""
    draw_sidebar(state)


# Need Path for home expansion
from pathlib import Path
