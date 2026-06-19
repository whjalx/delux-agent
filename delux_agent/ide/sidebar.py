from __future__ import annotations

import sys
import re
from pathlib import Path
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
        self.width: int = 36
        self.plan_progress: str = ""
        self.plan_step: str = ""
        self.plan_steps_list: list[dict] = []
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
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)


def _build_progress_bar(done: int, total: int, width: int = 12) -> str:
    if total == 0:
        return DIM + ("·" * width) + RESET
    filled = int(width * done / total)
    pct = int(100 * done / total)
    bar = GREEN + ("█" * filled) + DIM + ("·" * (width - filled)) + RESET
    return f"{bar}  {GREEN}{pct}%{RESET}"


def draw_sidebar(state: SidebarState) -> None:
    if not state.visible:
        return
    w = _term_width()
    h = _term_height()
    sw = state.width
    left_w = w - sw
    if left_w < 40:
        return
    sys.stdout.write("\x1b7")
    rows = _build_sidebar_rows(state, sw)
    for row_idx, row_content in enumerate(rows):
        if row_idx >= h - 1:
            break
        sys.stdout.write(f"\x1b[{row_idx + 1};{left_w + 1}H")
        sys.stdout.write("\x1b[K")
        sys.stdout.write(row_content)
    for row_idx in range(min(h - 1, len(rows) + 2)):
        sys.stdout.write(f"\x1b[{row_idx + 1};{left_w}H")
        sys.stdout.write(f"{DIM}│{RESET}")
    sys.stdout.write("\x1b8")
    sys.stdout.flush()


def _build_sidebar_rows(state: SidebarState, sw: int) -> list[str]:
    rows: list[str] = []

    if state.plan_progress or state.running:
        rows.append(f"  {MAGENTA}{BOLD}plan{RESET}")
        if state.plan_progress and "/" in state.plan_progress:
            try:
                done, total = state.plan_progress.split("/")
                rows.append(f"  {_build_progress_bar(int(done), int(total))}")
            except ValueError:
                pass
        if state.plan_step:
            rows.append(f"  {DIM}{state.plan_step[:sw - 6]}{RESET}")
        rows.append(f"")

    if state.plan_steps_list:
        for s in state.plan_steps_list[:8]:
            sid = s.get("id", "?")
            desc = s.get("desc", "")[:sw - 8]
            status = s.get("status", "pending")
            if status == "done":
                icon = f"{GREEN}✓{RESET}"
            elif status == "skipped":
                icon = f"{YELLOW}⊙{RESET}"
            elif status == "failed":
                icon = f"{RED}✗{RESET}"
            elif status == "running":
                icon = f"{YELLOW}◌{RESET}"
            else:
                icon = f"{DIM}·{RESET}"
            rows.append(f"  {icon} {DIM}{sid}.{RESET} {desc}")
        if len(state.plan_steps_list) > 8:
            rows.append(f"  {DIM}...+{len(state.plan_steps_list) - 8} more{RESET}")
        rows.append(f"")

    if state.current_action:
        rows.append(f"  {GREEN}·{RESET} {state.current_action[:sw - 6]}")
        rows.append(f"")

    env_rows: list[str] = []
    if state.cwd:
        cwd_short = state.cwd
        try:
            h = str(Path.home())
            if cwd_short.startswith(h):
                cwd_short = "~" + cwd_short[len(h):]
        except Exception:
            pass
        env_rows.append(f"  · {cwd_short[:sw - 6]}")
    if state.model_name:
        env_rows.append(f"  · {state.model_name[:sw - 6]}")
    if state.lang:
        v = f"V:{state.validate_mode}" if state.validate_mode else ""
        parts = [f"  · {state.lang}"]
        if v:
            parts.append(v)
        env_rows.append("  ".join(parts))
    if state.mcp_servers > 0:
        env_rows.append(f"  · MCP:{state.mcp_servers}")
    if state.training_mode:
        env_rows.append(f"  training")
    if state.ctx_enabled:
        env_rows.append(f"  ctx")
    rows.extend(env_rows)

    h = _term_height()
    while len(rows) < h - 2:
        rows.append("")
    return rows


def clear_sidebar() -> None:
    w = _term_width()
    h = _term_height()
    sys.stdout.write("\x1b7")
    for row in range(h - 1):
        sys.stdout.write(f"\x1b[{row + 1};{w - 36 + 1}H\x1b[K")
    sys.stdout.write("\x1b8")
    sys.stdout.flush()


def init_split(state: SidebarState) -> None:
    if not state.visible:
        return
    w = _term_width()
    left_w = w - state.width
    if left_w < 40:
        state.visible = False
        return


def redraw_after_output(state: SidebarState) -> None:
    draw_sidebar(state)
