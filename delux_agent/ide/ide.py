from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import indent

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

from ..agent import Agent, AgentRunResult
from ..console import console, make_banner, make_action_line, make_success, make_error, make_plan_box
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich.panel import Panel
from rich import box

_NO_BOX = box.Box(
    "    \n"
    "    \n"
    "    \n"
    "    \n"
    "    \n"
    "    \n"
    "    \n"
    "    \n"
)
from ..config import CONFIG_FILE, Config, ModelEntry, load_config, write_config
from ..plan_executor import build_planner_prompt
from ..system_info import get_compact_context
from ..i18n import I18n, DEFAULT_LANG
from ..store import load_docs, load_memory, load_skills, save_session_markdown, slugify, upsert_skill
from ..llm import chat_completion
from ..mcp.store import (
    MCPServerEntry, add_mcp_server, remove_mcp_server, toggle_mcp_server,
    load_mcp_servers, get_enabled_servers, discover_tools, cache_tools, get_tools_for_prompt,
    load_cached_tools, MCP_SERVERS_FILE, MCP_TOOLS_CACHE,
)
from ..mcp.client import MCPClient
from ..templates import list_templates, set_template, get_model_template, record_successful_strategy, PARSE_STRATEGIES
from ..training.contextualizer import (
    Contextualizer, ContextualizerConfig, load_ctx_config, save_ctx_config,
)
from ..training.training import (
    build_training_example, save_example, get_stats, clear_dataset,
    export_for_finetuning, get_dataset_path, ensure_training_dir,
    count_dataset_lines, estimate_file_size,
)
from .sidebar import SidebarState, draw_sidebar, redraw_after_output, init_split, clear_sidebar
from ..indexer import (
    build_index, export_obsidian_vault, expand_wikilinks,
    format_index_summary, ProjectIndex, OBSIDIAN_DIR, EmbeddingStore,
)


BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BLUE = "\033[34m"
RESET = "\033[0m"
GRAY = "\033[38;5;245m"
ITALIC = "\033[3m"


DESTRUCTIVE_PATTERNS = ["rm ", "rm -", "> ", ">> ", "mv ", "chmod ", "chown ", "truncate", "shred", "dd if=", "mkfs", "wipe"]
CONFIG_PATHS = ["/etc/", ".config/", "/etc", "conf.d", "rc.local", ".bashrc", ".zshrc", ".fish", "fstab", "sudoers", "sshd_config"]


def _is_delicate(action: dict, cwd: Path) -> bool:
    kind = action.get("action", "")
    if kind == "shell":
        cmd = action.get("command", "").lower()
        for pat in DESTRUCTIVE_PATTERNS:
            if pat in cmd:
                return True
        for cp in CONFIG_PATHS:
            if cp in cmd:
                return True
    if kind in {"write_file", "append_file"}:
        path = action.get("path", "").lower()
        for cp in CONFIG_PATHS:
            if cp in path:
                return True
    return False


def _term_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def _term_height() -> int:
    return shutil.get_terminal_size((80, 24)).lines


def _separator(char: str = "\u2500") -> str:
    return DIM + char * _term_width() + RESET


def _badge(label: str, color: str) -> str:
    return f"{color}[{label}]{RESET}"


ACTIONS_STYLE = {
    "shell": {"icon": "\u26a1", "color": GREEN},
    "read_file": {"icon": "\U0001f4c4", "color": BLUE},
    "write_file": {"icon": "\u270f\ufe0f", "color": BLUE},
    "append_file": {"icon": "\u270f\ufe0f", "color": BLUE},
    "search_files": {"icon": "\U0001f50d", "color": CYAN},
    "create_skill": {"icon": "\U0001f9e0", "color": MAGENTA},
    "run_skill": {"icon": "\U0001f680", "color": YELLOW},
    "remember": {"icon": "\U0001f4dd", "color": GRAY},
    "final": {"icon": "\u2705", "color": GREEN},
}

VALIDATE_MODES = {"off", "on", "once"}


@dataclass
class PlanStep:
    id: int
    description: str
    status: str = "pending"
    action_kind: str = ""
    detail: str = ""


@dataclass
class AgentPlan:
    prompt: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    summary: str = ""
    active_step: int = 0

    def mark_running(self, step_id: int) -> None:
        for s in self.steps:
            if s.id == step_id:
                s.status = "running"
                self.active_step = step_id

    def mark_done(self, step_id: int, ok: bool = True) -> None:
        for s in self.steps:
            if s.id == step_id:
                s.status = "done" if ok else "failed"

    def next_pending(self) -> PlanStep | None:
        for s in self.steps:
            if s.status == "pending":
                return s
        return None

    def progress(self) -> str:
        done = sum(1 for s in self.steps if s.status == "done")
        total = len(self.steps)
        return f"{done}/{total}"

    def is_complete(self) -> bool:
        return all(s.status in {"done", "failed"} for s in self.steps)

    def compact_context(self) -> str:
        lines = [f"Plan ({self.progress()}): {self.summary}"]
        current = None
        for s in self.steps:
            if s.status == "running":
                current = s
                break
        if current:
            lines.append(f"\nCurrent step: {current.id}. {current.description}")
        return "\n".join(lines)

    def full_context(self) -> str:
        lines = [f"PLAN: {self.summary}", ""]
        for s in self.steps:
            status_icon = {"pending": "\u25cb", "running": "\u25d0", "done": "\u2705", "failed": "\u274c"}[s.status]
            lines.append(f"  {status_icon} {s.id}. {s.description}")
            if s.detail:
                lines[-1] += f" [{s.detail}]"
        return "\n".join(lines)


@dataclass
class IdeState:
    cwd: Path
    prompt_history: list[str] = field(default_factory=list)
    run_history: list[AgentRunResult] = field(default_factory=list)
    plan: AgentPlan | None = None


class DeluxIDE:
    def __init__(self, config: Config, cwd: Path, max_steps: int = 12) -> None:
        self.config = config
        self.state = IdeState(cwd=cwd)
        self.max_steps = max_steps
        self._total_runs = 0
        self._i18n = I18n(config.lang if config.lang else DEFAULT_LANG)
        self._validate_mode = "off"
        self._ephemeral = False
        self._plan_mode = False
        self._ask_mode = True
        self._loaded_session_context: str | None = None
        self._session_context_turns = 2
        self._skill_names: list[str] = []
        self._active_model_idx = 0
        self._validator_model_idx: int | None = None
        self._ctx_cfg = load_ctx_config(config.root)
        self._training_mode = False
        self._status = {
            "current_action": "",
            "plan_progress": "",
            "plan_step": "",
            "running": False,
        }
        self._sidebar = SidebarState()
        self._sidebar.cwd = str(cwd)
        self._sidebar.model_name = config.model
        self._sidebar.lang = config.lang or "en"
        self._sidebar.validate_mode = "off"
        self._sidebar.mcp_servers = len([s for s in get_enabled_servers(config.root)])
        self._load_skills_list()
        self._sync_model_from_config()
        self._setup_readline()
        self._project_index: ProjectIndex | None = None
        self._output_log: list[str] = []
        self._live: Live | None = None

    def _setup_sigwinch_handler(self) -> None:
        import signal
        def _handle_sigwinch(signum, frame):
            if hasattr(self, '_live') and self._live:
                self._live.refresh()
        signal.signal(signal.SIGWINCH, _handle_sigwinch)

    def _install_sidebar_redraw(self) -> None:
        pass  # handled by _tui_render

    def _load_skills_list(self) -> None:
        skills = load_skills(self.config.skills_dir)
        self._skill_names = [s.name for s in skills]

    def _sync_model_from_config(self) -> None:
        if not self.config.models:
            return
        for i, m in enumerate(self.config.models):
            if m.name == self.config.model:
                self._active_model_idx = i
                return

    def _active_model(self) -> ModelEntry:
        if self.config.models and 0 <= self._active_model_idx < len(self.config.models):
            return self.config.models[self._active_model_idx]
        return ModelEntry(
            name=self.config.model,
            provider=self.config.provider,
            api_base=self.config.api_base,
            api_endpoint=str(self.config.api_endpoint or ""),
            api_key=str(self.config.api_key or ""),
        )

    def _active_api_base(self) -> str:
        m = self._active_model()
        return m.api_base or self.config.api_base

    def _active_api_key(self) -> str | None:
        m = self._active_model()
        return m.api_key or self.config.api_key

    def _active_api_endpoint(self) -> str | None:
        m = self._active_model()
        return m.api_endpoint or None

    def _active_provider(self) -> str:
        m = self._active_model()
        return m.provider or self.config.provider

    def _validator_model_entry(self) -> ModelEntry:
        if self._validator_model_idx is not None and self.config.models:
            if 0 <= self._validator_model_idx < len(self.config.models):
                return self.config.models[self._validator_model_idx]
        return self._active_model()

    def _validator_api_base(self) -> str:
        m = self._validator_model_entry()
        return m.api_base or self.config.api_base

    def _validator_api_key(self) -> str | None:
        m = self._validator_model_entry()
        return m.api_key or self.config.api_key

    def _validator_api_endpoint(self) -> str | None:
        m = self._validator_model_entry()
        return m.api_endpoint or None

    def _validator_model_name(self) -> str:
        m = self._validator_model_entry()
        return m.name or self.config.model

    def _build_active_config(self) -> Config:
        from dataclasses import replace
        m = self._active_model()
        return replace(
            self.config,
            model=m.name,
            provider=m.provider or self.config.provider,
            api_base=m.api_base or self.config.api_base,
            api_endpoint=m.api_endpoint or None,
            api_key=m.api_key or self.config.api_key,
        )

    def _build_validator_config(self) -> Config:
        from dataclasses import replace
        m = self._validator_model_entry()
        return replace(
            self.config,
            model=m.name,
            provider=m.provider or self.config.provider,
            api_base=m.api_base or self.config.api_base,
            api_endpoint=m.api_endpoint or None,
            api_key=m.api_key or self.config.api_key,
        )

    def _expand_at_skills(self, prompt: str) -> str:
        if "@" not in prompt:
            return prompt

        parts = re.split(r'(@[\w-]*)', prompt)
        for i, part in enumerate(parts):
            if part.startswith("@") and len(part) > 1:
                query = part[1:].lower()
                exact = None
                matches = []
                for s in self._skill_names:
                    if s.lower() == query:
                        exact = s
                    elif s.lower().startswith(query):
                        matches.append(s)

                if exact:
                    parts[i] = f"@{exact}"
                elif len(matches) == 1:
                    parts[i] = f"@{matches[0]}"
                elif len(matches) > 1:
                    print(f"  {DIM}Ambiguous {part}: did you mean?{RESET}")
                    for idx, m in enumerate(matches, 1):
                        print(f"    {DIM}{idx}.{RESET} {YELLOW}@{m}{RESET}")
                    try:
                        choice = input(f"  {DIM}Select (1-{len(matches)}, or Enter for all): {RESET}").strip()
                        if choice.isdigit() and 1 <= int(choice) <= len(matches):
                            parts[i] = f"@{matches[int(choice) - 1]}"
                        else:
                            parts[i] = " ".join(f"@{m}" for m in matches)
                    except (EOFError, KeyboardInterrupt):
                        parts[i] = f"@{matches[0]}"
                elif len(matches) == 0:
                    print(f"  {DIM}No skill matches {part}. Available skills:{RESET}")
                    for s in self._skill_names[:10]:
                        print(f"    {YELLOW}@{s}{RESET}")
                    if len(self._skill_names) > 10:
                        print(f"    {DIM}...+{len(self._skill_names) - 10} more{RESET}")
                    parts[i] = ""

        result = "".join(parts)
        if result != prompt:
            print(f"  {DIM}Expanded: {result}{RESET}")
        return result

    def _expand_obsidian_links(self, prompt: str) -> str:
        if "[[" not in prompt:
            return prompt

        store = None
        if self._project_index:
            store = EmbeddingStore.load(self.config.root, self._project_index.project)

        semantic_matches = set()
        def on_sem_match(link, rel, score):
            semantic_matches.add(rel)
            lbl = self.t("index.semantic_match")
            print(f"  {DIM}[{self.t('index.wikilink_expanded')} ({lbl}): {CYAN}{rel}{RESET}{DIM} ({score*100:.1f}% similitud para {YELLOW}\"{link}\"{RESET}{DIM})]{RESET}")

        expanded_prompt, expanded_files = expand_wikilinks(
            prompt,
            self._project_index,
            self.state.cwd,
            embedding_store=store,
            config=self.config,
            on_semantic_match=on_sem_match,
        )

        standard_files = [f for f in expanded_files if f not in semantic_matches]
        if standard_files:
            label = self.t("index.wikilink_expanded")
            files_str = ", ".join(f"{CYAN}{f}{RESET}" for f in standard_files)
            print(f"  {DIM}[{label}: {files_str}]{RESET}")

        return expanded_prompt

    def _refresh_sidebar(self) -> None:
        sb = self._sidebar
        sb.plan_progress = self._status.get("plan_progress", "")
        sb.plan_step = self._status.get("plan_step", "")
        sb.plan_steps_list = []
        sb.current_action = self._status.get("current_action", "")
        sb.running = self._status.get("running", False)
        sb.cwd = str(self.state.cwd)
        sb.training_mode = self._training_mode
        sb.ctx_enabled = self._ctx_cfg.enabled
        m = self._active_model()
        sb.model_name = m.name
        sb.lang = self.config.lang or "en"
        sb.validate_mode = self._validate_mode
        sb.mcp_servers = len([s for s in get_enabled_servers(self.config.root)])

        if self.state.plan:
            for s in self.state.plan.steps:
                sb.plan_steps_list.append({
                    "id": s.id,
                    "desc": s.description,
                    "status": s.status,
                })

        self._tui_refresh()

    def _hide_sidebar(self) -> None:
        self._sidebar.visible = False
        clear_sidebar()

    def _toggle_sidebar(self) -> bool:
        self._sidebar.visible = not self._sidebar.visible
        if self._sidebar.visible:
            self._refresh_sidebar()
        else:
            clear_sidebar()
        return self._sidebar.visible

    def _setup_readline(self) -> None:
        pass

    def _repaint_prompt(self) -> None:
        pass

    def _show_prompt_inline(self) -> None:
        pass

    def _get_prompt_toolkit_session(self):
        try:
            import os
            import json
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.styles import Style

            if getattr(self, '_pt_session', None) is not None:
                return self._pt_session

            kb = KeyBindings()

            @kb.add('tab')
            def _toggle_plan(event):
                self._plan_mode = not self._plan_mode
                event.app.invalidate()

            @kb.add('c-l')
            def _clear(event):
                event.app.exit(result='__CLEAR__')

            wal_bg = '#1a1a2e'
            wal_fg = '#c8c4c3'
            wal_accent = '#bd93f9'
            wal_active = '#ffb86c'
            wal_sep = '#6272a4'
            wal_label = '#44475a'

            try:
                wal_path = os.path.expanduser('~/.cache/wal/colors.json')
                if os.path.exists(wal_path):
                    with open(wal_path, 'r') as f:
                        wal_data = json.load(f)
                    c = wal_data.get('colors', {})
                    s = wal_data.get('special', {})
                    wal_bg = s.get('background', wal_bg)
                    wal_fg = s.get('foreground', wal_fg)
                    wal_accent = c.get('color5', wal_accent)
                    wal_active = c.get('color3', wal_active)
                    wal_sep = c.get('color8', wal_sep)
                    wal_label = c.get('color7', wal_label)
            except Exception:
                pass

            style_dict = {
                'prompt':          f'{wal_accent} bold',
                'prompt.plan':     f'{wal_active} bold',
                'separator':       f'{wal_sep}',
                'bottom-toolbar':            f'bg:{wal_bg} {wal_fg}',
                'bottom-toolbar.key':        f'bg:{wal_bg} {wal_accent} bold',
                'bottom-toolbar.key.active': f'bg:{wal_bg} {wal_active} bold',
                'bottom-toolbar.sep':        f'bg:{wal_bg} {wal_sep}',
                'bottom-toolbar.label':      f'bg:{wal_bg} {wal_label}',
            }
            style = Style.from_dict(style_dict)

            self._pt_history = InMemoryHistory()
            session = PromptSession(
                history=self._pt_history,
                key_bindings=kb,
                style=style,
                bottom_toolbar=self._get_toolbar,
                enable_history_search=True,
                vi_mode=False,
                mouse_support=False,
                wrap_lines=True,
                refresh_interval=0.5,
            )
            self._pt_session = session
            return session
        except ImportError:
            return None

    def _get_toolbar(self):
        from prompt_toolkit.formatted_text import FormattedText
        plan_key_style = 'class:bottom-toolbar.key.active' if self._plan_mode else 'class:bottom-toolbar.key'
        plan_val = f' {self.t("toolbar.on")} ' if self._plan_mode else f' {self.t("toolbar.plan").lower()} '
        ask_key_style = 'class:bottom-toolbar.key.active' if self._ask_mode else 'class:bottom-toolbar.key'
        ask_val = f' {self.t("toolbar.on")} ' if self._ask_mode else f' {self.t("toolbar.off")} '
        sep = ('class:bottom-toolbar.sep', '  ·  ')
        items = [
            ('class:bottom-toolbar', ' '),
            ('class:bottom-toolbar.key', '↑↓'),
            ('class:bottom-toolbar.label', ' hist '),
            sep,
            ('class:bottom-toolbar.key', 'Tab'),
            (plan_key_style, plan_val),
            sep,
            (ask_key_style, '/ask'),
            ('class:bottom-toolbar.label', ask_val),
            sep,
            ('class:bottom-toolbar.key', '^L'),
            ('class:bottom-toolbar.label', f' {self.t("toolbar.clear").lower()} '),
            sep,
            ('class:bottom-toolbar.key', '/q'),
            ('class:bottom-toolbar.label', f' {self.t("toolbar.quit").lower()} '),
            ('class:bottom-toolbar', ' '),
        ]
        if self._loaded_session_context:
            items.insert(1, ('class:bottom-toolbar.key.active', f' ✦{self.t("toolbar.session_loaded")} '))
            items.insert(2, sep)
        return FormattedText(items)

    def _build_pt_prompt(self):
        from prompt_toolkit.formatted_text import FormattedText
        label = self._i18n.t('prompt.label')
        if self._plan_mode:
            return FormattedText([
                ('class:prompt.plan', f'{label} [plan]'),
                ('class:separator', ' ❯ '),
            ])
        return FormattedText([
            ('class:prompt', label),
            ('class:separator', ' ❯ '),
        ])

    def _show_shortcut_bar(self) -> None:
        if getattr(self, '_pt_session', None) is not None:
            return
        w = _term_width()
        plan_c = YELLOW if self._plan_mode else DIM
        plan_l = 'PLAN' if self._plan_mode else 'plan'
        bar = (f"  {DIM}│{RESET} "
               f"{BOLD}↑↓{RESET}{DIM} hist{RESET}  "
               f"{BOLD}Tab{RESET}{DIM}={plan_c}{plan_l}{RESET}  "
               f"{BOLD}^L{RESET}{DIM} clear{RESET}  "
               f"{BOLD}^C{RESET}{DIM} cancel{RESET}  "
               f"{BOLD}/?{RESET}{DIM} help{RESET}  "
               f"{BOLD}/q{RESET}{DIM} quit  {DIM}│{RESET}")
        print(bar)

    def _draw_prompt(self, buffer: str, cursor_pos: int | None = None) -> None:
        sys.stdout.write("\r\x1b[K")
        label = self._i18n.t("prompt.label")
        prompt_str = (f"{CYAN}{BOLD}{label} [{YELLOW}plan{RESET}{CYAN}]{RESET}"
                      if self._plan_mode else f"{CYAN}{BOLD}{label}{RESET}")
        sys.stdout.write(f"{prompt_str} {DIM}❯{RESET} {buffer}")
        if cursor_pos is not None:
            vis = re.sub(r'\x1b\[[0-9;]*m', '', prompt_str)
            sys.stdout.write(f"\x1b[{len(vis) + 3 + cursor_pos + 1}G")
        sys.stdout.flush()

    def _read_input_raw(self) -> str | None:
        session = self._get_prompt_toolkit_session()

        if session is not None:
            try:
                result = session.prompt(self._build_pt_prompt)
                if result is None:
                    return None
                result = result.strip()
                if result and (not self.state.prompt_history or self.state.prompt_history[-1] != result):
                    self.state.prompt_history.append(result)
                return result
            except KeyboardInterrupt:
                return ''
            except EOFError:
                return None

        try:
            return input(f"{DIM}>{RESET} ").strip()
        except EOFError:
            return None
        except KeyboardInterrupt:
            return ''

    def _tui_render(self) -> Panel:
        from rich.console import Group
        w = shutil.get_terminal_size((80, 24)).columns

        header = make_banner(
            (self._active_model().provider or self.config.provider).upper(),
            self._active_model().name,
            self._get_flags(),
        )

        max_main = shutil.get_terminal_size((80, 24)).lines - 8
        visible = self._output_log[-max_main:] if len(self._output_log) > max_main else self._output_log
        if visible:
            from rich.text import Text as RichText
            main_content = RichText("\n".join(visible))
        else:
            main_content = Text("ready", style="dim")
        main_panel = Panel(
            main_content,
            box=box.SIMPLE,
            border_style="dim",
            padding=(0, 1),
        )

        sidebar_content = self._build_sidebar_text()
        if sidebar_content:
            side_w = min(36, w // 4)
            side = Panel(sidebar_content, box=box.SIMPLE, border_style="dim", width=side_w, padding=(0, 0))
            from rich.columns import Columns
            body = Columns([main_panel, side], expand=True)
        else:
            body = main_panel

        return Group(header, body)

    def _get_flags(self) -> list[str]:
        flags = [(self.config.lang or "en").upper()]
        if self._plan_mode: flags.append("plan")
        if self._ask_mode: flags.append("ask")
        if self._ephemeral: flags.append("ephemeral")
        if self._ctx_cfg.enabled: flags.append("ctx")
        mcp = list(get_enabled_servers(self.config.root))
        if mcp: flags.append(f"mcp:{len(mcp)}")
        return flags

    def _build_sidebar_text(self) -> str:
        lines = []
        s = self._status
        if s.get("plan_progress") or s.get("running"):
            lines.append(f"[bold magenta]plan[/]")
            if s.get("plan_progress"):
                lines.append(f"  [green]{s['plan_progress']}[/]")
            if s.get("plan_step"):
                lines.append(f"  [dim]{s['plan_step'][:30]}[/]")
            lines.append("")
        if s.get("current_action"):
            lines.append(f"  [green]·[/] {s['current_action'][:30]}")
            lines.append("")
        cwd = str(self.state.cwd)
        try:
            h = str(Path.home())
            if cwd.startswith(h):
                cwd = "~" + cwd[len(h):]
        except:
            pass
        lines.append(f"  [dim]{cwd[:30]}[/]")
        lines.append(f"  [dim]{self._active_model().name[:30]}[/]")
        return "\n".join(lines)

    def run(self) -> int:
        self._setup_sigwinch_handler()
        self._get_prompt_toolkit_session()

        self._live = Live(self._tui_render(), console=console, screen=True, auto_refresh=False, redirect_stdout=False)

        with self._live:
            while True:
                self._live.update(self._tui_render())
                try:
                    raw = self._read_input_raw()
                except Exception:
                    raw = None

                if raw is None:
                    return 0

                if raw == '__CLEAR__':
                    self._output_log.clear()
                    self._live.update(self._tui_render())
                    continue

                if raw == '':
                    continue

                if raw.startswith('/'):
                    if not self._handle_command(raw):
                        return 0
                    self._live.update(self._tui_render())
                    continue

                self._tui_emit(f"  > {raw[:200]}")
                self._run_prompt(raw)

        self._live = None
        return 0

    def t(self, key: str) -> str:
        return self._i18n.t(key)

    def _print_banner(self) -> None:
        m = self._active_model()
        provider = (m.provider or self.config.provider).upper()
        model_name = m.name
        flags = [(self.config.lang or "en").upper()]
        if self._plan_mode:
            flags.append("plan")
        if self._ask_mode:
            flags.append("ask")
        if self._ephemeral:
            flags.append("ephemeral")
        if self._ctx_cfg.enabled:
            flags.append("ctx")
        mcp_servers = list(get_enabled_servers(self.config.root))
        if mcp_servers:
            flags.append(f"mcp:{len(mcp_servers)}")
        console.print()
        console.print(make_banner(provider, model_name, flags))
        console.print()

    def _handle_command(self, raw: str) -> bool:
        parts = shlex.split(raw)
        command = parts[0]
        args = parts[1:]

        if command in ("/help", "/?"):
            if command == "/?":
                self._show_shortcuts()
            else:
                self._cmd_help()
        elif command in ("/p", "/plan"):
            if command == "/p" or not args:
                self._plan_mode = not self._plan_mode
                mode_str = f"{GREEN}ON{RESET}" if self._plan_mode else f"{DIM}OFF{RESET}"
                print(f"  {DIM}[Plan: {mode_str}]{RESET}")
                return True
            if args[0] in ("on", "off"):
                self._plan_mode = args[0] == "on"
            else:
                print(f"  {RED}Unknown: {args[0]}. Use on|off{RESET}")
                return True
        elif command in ("/v", "/validate"):
            if command == "/v" or not args:
                if self._validate_mode == "off":
                    self._validate_mode = "on"
                else:
                    self._validate_mode = "off"
                mode_str = f"{GREEN}ON{RESET}" if self._validate_mode == "on" else f"{DIM}OFF{RESET}"
                print(f"  {DIM}[Validate: {mode_str}]{RESET}")
                return True
            if args[0] in ("on", "off", "once"):
                self._validate_mode = args[0]
            else:
                print(f"  {RED}Unknown: {args[0]}. Use on|off|once{RESET}")
                return True
        elif command in ("/e", "/ephemeral"):
            if command == "/e" or not args:
                self._ephemeral = not self._ephemeral
                mode_str = f"{GREEN}ON{RESET}" if self._ephemeral else f"{DIM}OFF{RESET}"
                print(f"  {DIM}[Ephemeral: {mode_str}]{RESET}")
                return True
            if args[0] in ("on", "off"):
                self._ephemeral = args[0] == "on"
            else:
                print(f"  {RED}Unknown: {args[0]}. Use on|off{RESET}")
                return True
        elif command in ("/a", "/ask"):
            if command == "/a" or not args:
                self._ask_mode = not self._ask_mode
                mode_str = f"{GREEN}ON{RESET}" if self._ask_mode else f"{DIM}OFF{RESET}"
                print(f"  {DIM}[Ask: {mode_str}]{RESET}")
                return True
            if args[0] in ("on", "off"):
                self._ask_mode = args[0] == "on"
            else:
                print(f"  {RED}Unknown: {args[0]}. Use on|off{RESET}")
                return True
        elif command in ("/q", "/quit"):
            return False
        elif command == "/status":
            self._show_status()
        elif command == "/context":
            self._show_context()
        elif command == "/memory":
            print(load_memory(self.config.memory_file))
        elif command == "/skills":
            self._show_skills()
        elif command == "/docs":
            self._show_docs()
        elif command == "/config":
            path = self.config.root / CONFIG_FILE
            if path.exists():
                print(path.read_text(encoding="utf-8"))
            else:
                print(f"{RED}{self.t('status.missing_config')}: {path}{RESET}")
        elif command == "/sessions":
            self._cmd_sessions(args)
        elif command == "/history":
            self._show_history()
        elif command == "/pwd":
            print(f"{DIM}{self.state.cwd}{RESET}")
        elif command == "/cd":
            self._change_directory(args)
        elif command == "/new-skill":
            self._new_skill(args)
        elif command == "/save":
            self._save_notes(" ".join(args).strip() or "manual-session")
        elif command == "/clear":
            self.state.prompt_history.clear()
            self.state.run_history.clear()
            print(f"{GREEN}{self.t('status.cleared')}{RESET}")
        elif command == "/lang":
            self._cmd_lang(args)
        elif command == "/validate":
            self._cmd_validate(args)
        elif command == "/ephemeral":
            self._cmd_ephemeral(args)
        elif command == "/plan":
            self._cmd_plan(args)
        elif command == "/ask":
            self._cmd_ask(args)
        elif command == "/model":
            self._cmd_model(args)
        elif command == "/vm":
            self._cmd_vm(args)
        elif command in ("/m", "/mcp"):
            if not args:
                self._cmd_mcp_list()
            elif args[0] == "add":
                self._cmd_mcp_add(args[1:])
            elif args[0] == "rm":
                self._cmd_mcp_remove(args[1:])
            elif args[0] == "toggle":
                self._cmd_mcp_toggle(args[1:])
            elif args[0] == "discover":
                self._cmd_mcp_discover(args[1:])
            elif args[0] == "tools":
                self._cmd_mcp_tools(args[1:])
            else:
                self._cmd_mcp_list()
        elif command == "/template":
            self._cmd_template(args)
        elif command in ("/ctx", "/contextualize"):
            self._cmd_ctx(args)
        elif command in ("/ft", "/finetune"):
            from ..training.contextualizer import Contextualizer
            Contextualizer.print_finetune_recommendations()
        elif command in ("/train", "/tr"):
            self._cmd_train(args)
        elif command == "/sidebar":
            if not args:
                vis = "visible" if self._sidebar.visible else "hidden"
                print(f"  {DIM}Sidebar: {vis}. Use /sidebar on|off|toggle{RESET}")
            elif args[0] in ("on", "show"):
                self._sidebar.visible = True
                self._refresh_sidebar()
                print(f"  {GREEN}Sidebar enabled.{RESET}")
            elif args[0] in ("off", "hide"):
                self._hide_sidebar()
                print(f"  {DIM}Sidebar hidden.{RESET}")
            else:
                self._toggle_sidebar()
                print(f"  {DIM}Sidebar toggled.{RESET}")
        elif command == "/index":
            self._cmd_index(args)
        else:
            print(f"{RED}{self.t('status.unknown_cmd')}: {command}{RESET}")
        return True

    def _show_shortcuts(self) -> None:
        print(f"\n{BOLD}{CYAN}\u2318 Shortcuts{RESET}")
        print(_separator())
        shortcuts = [
            (f"{BOLD}/p{RESET}", "Toggle plan mode"),
            (f"{BOLD}/v{RESET}", "Toggle validate mode"),
            (f"{BOLD}/e{RESET}", "Toggle ephemeral mode"),
            (f"{BOLD}/a{RESET}", "Toggle ask mode"),
            (f"{BOLD}/m{RESET}", "MCP servers"),
            (f"{BOLD}/ctx{RESET}", "Contextualizer"),
            (f"{BOLD}/train{RESET}", "Training mode"),
            (f"{BOLD}/ft{RESET}", "Fine-tuning guide"),
            (f"{BOLD}/model{RESET}", "Switch model"),
            (f"{BOLD}/?{RESET}", "Full help"),
            (f"{BOLD}/q{RESET}", "Quit"),
        ]
        for key, desc in shortcuts:
            print(f"  {key} {DIM}\u2192 {desc}{RESET}")
        print(f"\n{DIM}Type {BOLD}/?{RESET}{DIM} for complete command reference.{RESET}")
        print(f"{DIM}Press {BOLD}Esc{RESET}{DIM} to quit, {BOLD}^C{RESET}{DIM} to cancel, {BOLD}^L{RESET}{DIM} to clear.{RESET}\n")

    def _cmd_help(self) -> None:
        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('help_commands')}{RESET}")
        print(_separator())
        cmds = [
            ("help, ?", "Show this help"),
            ("status", "Show connection and config status"),
            ("context", "Show memory, skills, and docs context"),
            ("memory", "Show full memory contents"),
            ("skills", "List available skills"),
            ("docs", "List available documentation"),
            ("config", "Show current config file"),
            ("sessions", "List saved session files"),
            ("history", "Show prompt history"),
            ("pwd", "Show current working directory"),
            ("cd <path>", "Change working directory"),
            ("new-skill <name>", "Create a new skill"),
            ("save [title]", "Save current session notes"),
            ("clear", "Clear prompt and run history"),
            ("lang <en|es>", "Change display language"),
            ("plan <on|off>", "Toggle planning mode (create plan before each task)"),
            ("validate <on|off|once>", "Toggle validator mode (review output after task)"),
            ("ephemeral <on|off>", "Toggle ephemeral mode (no memory/skills saved)"),
            ("ask <on|off>", "Toggle ask mode (confirm before delicate actions)"),
            ("model [idx]", "Switch active model or add new model"),
            ("vm [idx|off]", "Set validator model (separate from active model)"),
            ("mcp", "List configured MCP servers"),
            ("mcp add <name> <cmd>", "Add a new MCP server"),
            ("mcp rm <name>", "Remove an MCP server"),
            ("mcp toggle <name>", "Enable/disable an MCP server"),
            ("mcp discover [name]", "Discover tools from MCP servers"),
            ("mcp tools [name]", "Show cached MCP tools"),
            ("template [model] [strategy]", "Set response parsing strategy per model"),
            ("ctx [on|off|model|base|max|recommend]", "Configure contextualizer (prompt optimization)"),
            ("ft, finetune", "Show fine-tuning recommendations for custom Delux model"),
            ("train [on|off|stats|export|clear|path]", "Training mode — save successful runs to dataset"),
            ("sidebar [on|off|toggle]", "Toggle right-side info panel"),
            ("index [build|rebuild|list|search|obsidian]", self.t("cmd.index")),
            ("quit, q", "Exit Delux IDE"),
        ]
        max_cmd = max(len(c) for c, _ in cmds)
        for cmd, desc in cmds:
            print(f"  {DIM}/{cmd:<{max_cmd}}{RESET} {DIM}{desc}{RESET}")
        print(f"\n{DIM}{self.t('help_input_hint')}{RESET}")
        if self._skill_names:
            print(f"{DIM}Type @<tab> to insert a skill name.{RESET}")
        print()

    def _cmd_lang(self, args: list[str]) -> None:
        if not args:
            available = self._i18n.available()
            current = self._i18n.lang
            print(f"  {DIM}Current: {current}{RESET}")
            for code, name in available:
                marker = " \u2190" if code == current else ""
                print(f"  {GREEN if code == current else DIM}{code}: {name}{marker}{RESET}")
            return
        lang = args[0].lower()
        if lang in ("en", "es"):
            self._i18n.lang = lang
            self._pt_session = None
            print(f"{GREEN}{self.t('status.lang_set')} {lang}{RESET}")
            self._print_banner()
        else:
            print(f"{RED}Unknown language: {lang}. Available: en, es{RESET}")

    def _cmd_validate(self, args: list[str]) -> None:
        if not args:
            mode = self._validate_mode
            print(f"  {DIM}Validator: {mode}{RESET}")
            print(f"  {DIM}/validate on{RESET}   - validate every run")
            print(f"  {DIM}/validate once{RESET}  - validate next run only")
            print(f"  {DIM}/validate off{RESET}   - disable validation")
            return
        mode = args[0].lower()
        if mode not in VALIDATE_MODES:
            print(f"{RED}Usage: /validate <on|off|once>{RESET}")
            return
        self._validate_mode = mode
        if mode == "on":
            print(f"{GREEN}{self.t('status.validate_on')}{RESET}")
        elif mode == "once":
            print(f"{YELLOW}{self.t('status.validate_once')}{RESET}")
        else:
            print(f"{DIM}{self.t('status.validate_off')}{RESET}")
        self._print_banner()

    def _cmd_ephemeral(self, args: list[str]) -> None:
        if not args:
            status = self.t("status.ephemeral_on") if self._ephemeral else self.t("status.ephemeral_off")
            print(f"  {DIM}Ephemeral: {status}{RESET}")
            return
        mode = args[0].lower()
        if mode == "on":
            self._ephemeral = True
            print(f"{YELLOW}{self.t('status.ephemeral_on')}{RESET}")
        elif mode == "off":
            self._ephemeral = False
            print(f"{GREEN}{self.t('status.ephemeral_off')}{RESET}")
        else:
            print(f"{RED}Usage: /ephemeral <on|off>{RESET}")
        self._print_banner()

    def _cmd_plan(self, args: list[str]) -> None:
        if not args:
            status = "on" if self._plan_mode else "off"
            print(f"  {DIM}Plan mode: {status}{RESET}")
            print(f"  {DIM}/plan on{RESET}   - create explicit plan before each run")
            print(f"  {DIM}/plan off{RESET}   - execute directly without planning")
            if self.state.plan:
                p = self.state.plan
                print(f"\n  {DIM}Current plan: {p.summary}{RESET}")
                for s in p.steps:
                    icon = {"pending": "\u25cb", "running": "\u25d0", "done": "\u2705", "failed": "\u274c"}[s.status]
                    print(f"    {icon} {s.id}. {s.description}")
            return
        mode = args[0].lower()
        if mode == "on":
            self._plan_mode = True
            print(f"{GREEN}Plan mode enabled. A plan will be created before each run.{RESET}")
        elif mode == "off":
            self._plan_mode = False
            self.state.plan = None
            print(f"{DIM}Plan mode disabled.{RESET}")
        else:
            print(f"{RED}Usage: /plan <on|off>{RESET}")
        self._print_banner()

    def _cmd_ask(self, args: list[str]) -> None:
        if not args:
            status = "on" if self._ask_mode else "off"
            print(f"  {DIM}Ask mode: {status}{RESET}")
            print(f"  {DIM}/ask on{RESET}   - ask before delicate actions or after failures")
            print(f"  {DIM}/ask off{RESET}   - run autonomously without asking")
            return
        mode = args[0].lower()
        if mode == "on":
            self._ask_mode = True
            print(f"{GREEN}Ask mode enabled. Delux will ask before delicate actions.{RESET}")
        elif mode == "off":
            self._ask_mode = False
            print(f"{DIM}Ask mode disabled.{RESET}")
        else:
            print(f"{RED}Usage: /ask <on|off>{RESET}")
        self._print_banner()

    def _cmd_model(self, args: list[str]) -> None:
        models = self.config.models
        if not args:
            print(f"\n{BOLD}{MAGENTA}\u25c6 Models{RESET}")
            print(_separator())
            for i, m in enumerate(models):
                marker = f"{GREEN}\u27a4{RESET}" if i == self._active_model_idx else f"{DIM}{i}.{RESET}"
                provider = f"{DIM}({m.provider}){RESET}" if m.provider else ""
                endpoint = f"{DIM}{m.api_base}{RESET}" if not m.api_endpoint and m.api_base else ""
                ep_display = m.api_endpoint or endpoint
                print(f"  {marker} {i}. {YELLOW}{m.name}{RESET} {provider} {DIM}{ep_display}{RESET}")
            print(f"\n  {DIM}/model <idx>{RESET} - switch active model")
            print(f"  {DIM}/model add <name> <provider> <api_base> [api_key]{RESET} - add new model")
            print()
            return
        if args[0] == "add":
            if len(args) < 4:
                print(f"{RED}Usage: /model add <name> <provider> <api_base> [api_key]{RESET}")
                return
            name = args[1]
            provider = args[2]
            api_base = args[3]
            api_key = args[4] if len(args) > 4 else ""
            new_model = ModelEntry(name=name, provider=provider, api_base=api_base, api_key=api_key)
            models.append(new_model)
            cfg_file = self.config.root / CONFIG_FILE
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                data = {}
            data["models"] = [
                {"name": m.name, "provider": m.provider, "api_base": m.api_base, "api_endpoint": m.api_endpoint, "api_key": m.api_key}
                for m in models
            ]
            write_config(self.config.root, data)
            print(f"{GREEN}Added model: {YELLOW}{name}{RESET} {GREEN}({provider}){RESET}")
            self._print_banner()
            return
        try:
            idx = int(args[0])
        except ValueError:
            for i, m in enumerate(models):
                if m.name.lower() == args[0].lower():
                    idx = i
                    break
            else:
                print(f"{RED}Unknown model: {args[0]}. Use /model to see available models.{RESET}")
                return
        if not (0 <= idx < len(models)):
            print(f"{RED}Model index out of range (0-{len(models) - 1}).{RESET}")
            return
        self._active_model_idx = idx
        m = self._active_model()
        print(f"{GREEN}Active model: {m.name}{RESET}")
        self._print_banner()

    def _cmd_vm(self, args: list[str]) -> None:
        if not args:
            current = self._validator_model_idx
            active = self._active_model().name
            vm = self._validator_model_entry().name
            print(f"\n{BOLD}{MAGENTA}\u25c6 Validator Model{RESET}")
            print(_separator())
            if current is None:
                print(f"  {DIM}Using active model: {YELLOW}{active}{RESET}")
            else:
                print(f"  {GREEN}\u27a4 {YELLOW}{vm}{RESET}")
            print(f"\n  {DIM}/vm <idx>{RESET} - set validator model")
            print(f"  {DIM}/vm off{RESET} - use active model as validator")
            print()
            return
        if args[0].lower() == "off":
            self._validator_model_idx = None
            print(f"{GREEN}Validator now uses active model.{RESET}")
            return
        try:
            idx = int(args[0])
        except ValueError:
            for i, m in enumerate(self.config.models):
                if m.name.lower() == args[0].lower():
                    idx = i
                    break
            else:
                print(f"{RED}Unknown model: {args[0]}. Use /model to see available.{RESET}")
                return
        if not (0 <= idx < len(self.config.models)):
            print(f"{RED}Model index out of range (0-{len(self.config.models) - 1}).{RESET}")
            return
        self._validator_model_idx = idx
        m = self._validator_model_entry()
        print(f"{GREEN}Validator model: {m.name}{RESET}")

    def _cmd_mcp_list(self) -> None:
        servers = load_mcp_servers(self.config.root)
        tools = get_tools_for_prompt(self.config.root)
        print(f"\n{BOLD}{MAGENTA}\u25c6 MCP Servers{RESET}")
        print(_separator())
        if not servers:
            print(f"  {DIM}No MCP servers configured.{RESET}")
            print(f"  {DIM}/mcp add <name> <command> [args...]{RESET} - add a server")
            print()
            return
        for s in servers:
            status = f"{GREEN}ON{RESET}" if s.enabled else f"{DIM}OFF{RESET}"
            cmd = f"{s.command} {' '.join(s.args)}"
            print(f"  {YELLOW}{s.name}{RESET} {status} {DIM}({cmd}){RESET}")
            if s.description:
                print(f"    {DIM}{s.description}{RESET}")
        if tools:
            print(f"\n{BOLD}Available Tools:{RESET}")
            print(tools)
        print(f"\n  {DIM}/mcp add <name> <command> [args...]{RESET} - add server")
        print(f"  {DIM}/mcp rm <name>{RESET} - remove server")
        print(f"  {DIM}/mcp toggle <name>{RESET} - enable/disable")
        print(f"  {DIM}/mcp discover [name]{RESET} - discover tools")
        print()

    def _cmd_mcp_add(self, args: list[str]) -> None:
        if len(args) < 2:
            print(f"{RED}Usage: /mcp add <name> <command> [args...]{RESET}")
            return
        name = args[0]
        command = args[1]
        cmd_args = args[2:]
        entry = MCPServerEntry(name=name, command=command, args=cmd_args)
        add_mcp_server(self.config.root, entry)
        print(f"{GREEN}Added MCP server: {YELLOW}{name}{RESET}")
        try:
            all_tools = discover_tools(self.config.root, name)
            cache_tools(self.config.root, all_tools)
            for srv, tools in all_tools.items():
                for t in tools:
                    if t.name != "error":
                        print(f"  {GREEN}\u2713 {t.name}{RESET} {DIM}{t.description}{RESET}")
        except Exception as exc:
            print(f"  {YELLOW}Could not discover tools: {exc}{RESET}")
        self._print_banner()

    def _cmd_mcp_remove(self, args: list[str]) -> None:
        if not args:
            print(f"{RED}Usage: /mcp rm <name>{RESET}")
            return
        if remove_mcp_server(self.config.root, args[0]):
            print(f"{GREEN}Removed MCP server: {YELLOW}{args[0]}{RESET}")
            self._print_banner()
        else:
            print(f"{RED}MCP server not found: {args[0]}{RESET}")

    def _cmd_mcp_toggle(self, args: list[str]) -> None:
        if not args:
            print(f"{RED}Usage: /mcp toggle <name>{RESET}")
            return
        if toggle_mcp_server(self.config.root, args[0]):
            servers = load_mcp_servers(self.config.root)
            s = next((x for x in servers if x.name == args[0]), None)
            status = "enabled" if s and s.enabled else "disabled"
            print(f"{GREEN}MCP server {YELLOW}{args[0]}{RESET} {GREEN}{status}{RESET}")
        else:
            print(f"{RED}MCP server not found: {args[0]}{RESET}")

    def _cmd_mcp_discover(self, args: list[str]) -> None:
        name = args[0] if args else None
        try:
            all_tools = discover_tools(self.config.root, name)
            cache_tools(self.config.root, all_tools)
            print(f"\n{BOLD}{MAGENTA}\u25c6 Discovered MCP Tools{RESET}")
            print(_separator())
            for srv, tools in all_tools.items():
                print(f"  {YELLOW}{srv}{RESET}")
                for t in tools:
                    if t.name == "error":
                        print(f"    {RED}\u2717 {t.description}{RESET}")
                    else:
                        print(f"    {GREEN}\u2713 {t.name}{RESET} {DIM}{t.description}{RESET}")
            print()
        except Exception as exc:
            print(f"{RED}Failed to discover MCP tools: {exc}{RESET}")

    def _cmd_mcp_tools(self, args: list[str]) -> None:
        name = args[0] if args else None
        cached = load_cached_tools(self.config.root)
        if not cached:
            print(f"{RED}No MCP tools cached. Run /mcp discover first.{RESET}")
            return
        if name:
            if name in cached:
                print(f"\n{BOLD}{MAGENTA}\u25c6 MCP Tools: {name}{RESET}")
                print(_separator())
                for t in cached[name]:
                    if t.name == "error":
                        print(f"    {RED}\u2717 {t.description}{RESET}")
                    else:
                        print(f"    {GREEN}\u2713 {t.name}{RESET} {DIM}{t.description}{RESET}")
                print()
            else:
                print(f"{RED}No cached tools for server: {name}{RESET}")
        else:
            print(get_tools_for_prompt(self.config.root))

    def _cmd_template(self, args: list[str]) -> None:
        if not args:
            templates = list_templates(self.config.root)
            print(f"\n{BOLD}{MAGENTA}\u25c6 Response Templates{RESET}")
            print(_separator())
            if not templates:
                print(f"  {DIM}No templates configured. Auto-detect is active.{RESET}")
            for name, t in templates:
                print(f"  {YELLOW}{name}{RESET} {DIM}\u2192 strategy: {t.preferred_strategy}{RESET}")
                if t.system_suffix:
                    print(f"    {DIM}suffix: {t.system_suffix[:60]}...{RESET}")
            print(f"\n  {DIM}/template <model> <strategy>{RESET} - set parse strategy")
            print(f"  {DIM}/template <model> suffix <text>{RESET} - set custom system suffix")
            print(f"  {DIM}Strategies: {', '.join(PARSE_STRATEGIES)}{RESET}")
            print()
            return
        if args[0] == "reset":
            model = args[1] if len(args) > 1 else self.config.model
            set_template(model, strategy="reset", root=self.config.root)
            print(f"{GREEN}Template reset for {YELLOW}{model}{RESET}")
            return
        if len(args) < 2:
            print(f"{RED}Usage: /template <model> <strategy>{RESET}")
            return
        model = args[0]
        if args[1] == "suffix":
            suffix = " ".join(args[2:]) if len(args) > 2 else ""
            set_template(model, suffix=suffix, root=self.config.root)
            print(f"{GREEN}Template suffix set for {YELLOW}{model}{RESET}")
        elif args[1] in PARSE_STRATEGIES or args[1] == "auto":
            set_template(model, strategy=args[1], root=self.config.root)
            print(f"{GREEN}Template strategy set: {YELLOW}{model}{RESET} {GREEN}\u2192 {args[1]}{RESET}")
        else:
            print(f"{RED}Unknown strategy: {args[1]}. Use: {', '.join(PARSE_STRATEGIES)}{RESET}")

    def _cmd_ctx(self, args: list[str]) -> None:
        if not args:
            status = f"{GREEN}ON{RESET}" if self._ctx_cfg.enabled else f"{DIM}OFF{RESET}"
            print(f"\n{BOLD}{MAGENTA}\u25c6 Contextualizer{RESET}")
            print(_separator())
            print(f"  Status: {status}")
            print(f"  Model: {YELLOW}{self._ctx_cfg.model}{RESET}")
            print(f"  Provider: {self._ctx_cfg.provider}")
            print(f"  API Base: {DIM}{self._ctx_cfg.api_base}{RESET}")
            print(f"  Max context tokens: {self._ctx_cfg.max_context_tokens}")
            print()
            print(f"  {DIM}/ctx on{RESET}           - enable contextualizer")
            print(f"  {DIM}/ctx off{RESET}          - disable contextualizer")
            print(f"  {DIM}/ctx model <name>{RESET}  - set model (e.g. qwen2.5:1.5b)")
            print(f"  {DIM}/ctx base <url>{RESET}    - set API base URL")
            print(f"  {DIM}/ctx max <tokens>{RESET}  - set max context tokens")
            print(f"  {DIM}/ctx recommend{RESET}     - show recommended models")
            print()
            return
        action = args[0].lower()
        if action == "on":
            self._ctx_cfg.enabled = True
            save_ctx_config(self.config.root, self._ctx_cfg)
            print(f"{GREEN}Contextualizer enabled. Model: {YELLOW}{self._ctx_cfg.model}{RESET}")
        elif action == "off":
            self._ctx_cfg.enabled = False
            save_ctx_config(self.config.root, self._ctx_cfg)
            print(f"{DIM}Contextualizer disabled.{RESET}")
        elif action == "model" and len(args) >= 2:
            self._ctx_cfg.model = args[1]
            save_ctx_config(self.config.root, self._ctx_cfg)
            print(f"{GREEN}Contextualizer model: {YELLOW}{args[1]}{RESET}")
        elif action == "base" and len(args) >= 2:
            self._ctx_cfg.api_base = args[1]
            save_ctx_config(self.config.root, self._ctx_cfg)
            print(f"{GREEN}Contextualizer API base: {args[1]}{RESET}")
        elif action == "max" and len(args) >= 2:
            try:
                self._ctx_cfg.max_context_tokens = int(args[1])
                save_ctx_config(self.config.root, self._ctx_cfg)
                print(f"{GREEN}Max context tokens: {args[1]}{RESET}")
            except ValueError:
                print(f"{RED}Invalid token count: {args[1]}{RESET}")
        elif action == "recommend":
            from ..training.contextualizer import Contextualizer
            Contextualizer.print_recommendations()
        else:
            print(f"{RED}Usage: /ctx <on|off|model|base|max|recommend> [value]{RESET}")

    def _cmd_train(self, args: list[str]) -> None:
        if not args:
            status = f"{GREEN}ON{RESET}" if self._training_mode else f"{DIM}OFF{RESET}"
            stats = get_stats(self.config.root)
            print(f"\n{BOLD}{MAGENTA}\u25c6 Training Mode{RESET}")
            print(_separator())
            print(f"  Status: {status}")
            print(f"  Dataset: {stats.total} examples ({stats.file_size})")
            if stats.avg_steps > 0:
                print(f"  Avg steps per example: {stats.avg_steps:.1f}")
            if stats.last_updated:
                print(f"  Last updated: {stats.last_updated}")
            if stats.categories:
                print(f"\n  Categories:")
                for cat, count in list(stats.categories.items())[:8]:
                    print(f"    {YELLOW}{cat}{RESET}: {count}")
                if len(stats.categories) > 8:
                    print(f"    {DIM}+{len(stats.categories) - 8} more{RESET}")
            print()
            print(f"  {DIM}/train on{RESET}         - enable training mode")
            print(f"  {DIM}/train off{RESET}        - disable training mode")
            print(f"  {DIM}/train stats{RESET}      - show dataset statistics")
            print(f"  {DIM}/train export <path>{RESET} - export dataset for fine-tuning")
            print(f"  {DIM}/train clear{RESET}      - clear the dataset")
            print(f"  {DIM}/train path{RESET}       - show dataset file path")
            print()
            return
        action = args[0].lower()
        if action == "on":
            self._training_mode = True
            ensure_training_dir(self.config.root)
            print(f"{GREEN}Training mode enabled. After each task, you'll be asked to save good examples.{RESET}")
        elif action == "off":
            self._training_mode = False
            print(f"{DIM}Training mode disabled.{RESET}")
        elif action == "stats":
            stats = get_stats(self.config.root)
            print(f"\n{BOLD}{MAGENTA}\u25c6 Dataset Statistics{RESET}")
            print(_separator())
            print(f"  Total examples: {YELLOW}{stats.total}{RESET}")
            print(f"  File size: {stats.file_size}")
            if stats.total > 0:
                print(f"  Avg steps per example: {stats.avg_steps:.1f}")
                print(f"  Total steps across examples: {stats.steps_total}")
                print(f"  Estimated tokens: {stats.steps_total * 50:,} - {stats.steps_total * 100:,}")
            if stats.last_updated:
                print(f"  Last updated: {stats.last_updated}")
            if stats.categories:
                print(f"\n  Categories:")
                for cat, count in stats.categories.items():
                    print(f"    {YELLOW}{cat}{RESET}: {count}")
            print()
        elif action == "clear":
            count = clear_dataset(self.config.root)
            print(f"{GREEN}Dataset cleared. Removed {count} examples.{RESET}")
        elif action == "export" and len(args) >= 2:
            output = Path(args[1]).expanduser()
            exported = export_for_finetuning(self.config.root, output)
            print(f"{GREEN}Exported {exported} examples to {output}{RESET}")
            print(f"  Use this file for fine-tuning with Unsloth, Axolotl, or Ollama.")
        elif action == "path":
            path = get_dataset_path(self.config.root)
            print(f"  Dataset path: {YELLOW}{path}{RESET}")
            if path.exists():
                print(f"  Size: {estimate_file_size(path)}")
                print(f"  Examples: {count_dataset_lines(path)}")
        else:
            print(f"{RED}Usage: /train <on|off|stats|export|clear|path> [value]{RESET}")

    def _show_status(self) -> None:
        endpoint = self.config.api_endpoint or (self.config.api_base.rstrip("/") + "/chat/completions")
        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('section.status')}{RESET}")
        print(_separator())
        items = [
            (self.t("banner.home"), str(self.config.root)),
            ("Config", str(self.config.root / CONFIG_FILE)),
            ("CWD", str(self.state.cwd)),
            ("Memory", str(self.config.memory_file)),
            ("Skills", str(self.config.skills_dir)),
            ("Docs", str(self.config.docs_dir)),
            ("Sessions", str(self.config.sessions_dir)),
            (self.t("status.provider"), self._active_provider()),
            (self.t("status.model"), self._active_model().name),
            (self.t("status.endpoint"), self._active_api_endpoint() or (self._active_api_base().rstrip("/") + "/chat/completions")),
            (self.t("status.timeout"), f"{self.config.request_timeout}s"),
            (self.t("status.api_key"), self.t("status.yes") if self._active_api_key() else self.t("status.no")),
        ]
        vm_name = self._validator_model_name()
        if self._validator_model_idx is not None or vm_name != self._active_model().name:
            items.append((self.t("status.validator_model"), vm_name))
        max_label = max(len(k) for k, _ in items)
        for label, value in items:
            color = GREEN if self.t("status.yes") == value else DIM
            print(f"  {DIM}{label:>{max_label}}{RESET}  {color}{value}{RESET}")
        if self.config.models:
            print(f"\n  {DIM}Models (/model to switch):{RESET}")
            for i, m in enumerate(self.config.models):
                marker = f"{GREEN}\u27a4{RESET}" if i == self._active_model_idx else f"{DIM}{i}.{RESET}"
                vm_marker = f" {YELLOW}[V]{RESET}" if self._validator_model_idx == i else ""
                print(f"    {marker} {YELLOW}{m.name}{RESET}{vm_marker}")
        print()

    def _show_context(self) -> None:
        skills = load_skills(self.config.skills_dir)
        docs = list(sorted(self.config.docs_dir.rglob("*.md")))

        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('section.context')}{RESET}")
        print(_separator())

        print(f"{BOLD}{self.t('section.memory')}{RESET}")
        print(DIM + load_memory(self.config.memory_file)[:1200].rstrip() + RESET)

        print(f"\n{BOLD}{self.t('section.skills')}{RESET} {DIM}({len(skills)}){RESET}")
        if skills:
            for skill in skills:
                summary = f": {skill.summary}" if skill.summary else ""
                if skill.has_exec:
                    print(f"  {_badge('exec', YELLOW)} {GREEN}{skill.name}{RESET}{DIM}{summary}{RESET}")
                else:
                    print(f"  {DIM}- {skill.name}{summary}{RESET}")
        else:
            print(f"  {DIM}{self.t('status.none')}{RESET}")

        print(f"\n{BOLD}{self.t('section.docs')}{RESET} {DIM}({len(docs)}){RESET}")
        if docs:
            for path in docs:
                print(f"  {DIM}- {path.relative_to(self.config.root)}{RESET}")
        else:
            print(f"  {DIM}{self.t('status.none')}{RESET}")
        print()

    def _show_skills(self) -> None:
        skills = load_skills(self.config.skills_dir)
        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('section.skills')}{RESET}")
        print(_separator())
        if not skills:
            print(f"  {DIM}{self.t('status.no_skills')}{RESET}")
            return
        for skill in skills:
            summary = f": {skill.summary}" if skill.summary else ""
            if skill.has_exec:
                print(f"  {_badge('exec:' + skill.exec_lang, YELLOW)} {GREEN}{skill.name}{RESET}{DIM}{summary}{RESET}")
            else:
                print(f"  {DIM}- {skill.name}{summary}{RESET}")
        print()

    def _show_docs(self) -> None:
        docs = list(sorted(self.config.docs_dir.rglob("*.md")))
        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('section.docs')}{RESET}")
        print(_separator())
        if not docs:
            print(f"  {DIM}{self.t('status.no_docs')}{RESET}")
            return
        for path in docs:
            print(f"  {DIM}- {path.relative_to(self.config.root)}{RESET}")
        print()

    def _cmd_sessions(self, args: list[str]) -> None:
        files = list(sorted(self.config.sessions_dir.glob("*.md")))
        if args and args[0] == "load" and len(args) > 1:
            try:
                idx = int(args[1]) - 1
                recent = files[-20:]
                if 0 <= idx < len(recent):
                    content = recent[idx].read_text(encoding="utf-8")
                    self._loaded_session_context = content
                    print(f"{GREEN}✦ {self.t('toolbar.session_loaded')}: {recent[idx].name}{RESET}")
                    print(f"  {DIM}The agent will use this session as context on the next run.{RESET}")
                else:
                    print(f"{RED}Session index out of range.{RESET}")
            except (ValueError, IndexError):
                print(f"{RED}Usage: /sessions load <number>{RESET}")
            return
        if args and args[0] == "clear":
            self._loaded_session_context = None
            print(f"{DIM}Loaded session context cleared.{RESET}")
            return
        self._show_sessions(files)

    def _show_sessions(self, files: list | None = None) -> None:
        import datetime
        if files is None:
            files = list(sorted(self.config.sessions_dir.glob("*.md")))
        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('section.sessions')}{RESET}")
        print(_separator())
        if not files:
            print(f"  {DIM}{self.t('status.no_sessions')}{RESET}")
            print(f"  {DIM}Use /save to save the current session.{RESET}")
            return
        recent = files[-20:]
        for i, path in enumerate(recent, 1):
            try:
                mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime)
                date_str = mtime.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = ""
            loaded = bool(self._loaded_session_context and path.name in self._loaded_session_context[:200])
            marker = f" {GREEN}✦{RESET}" if loaded else ""
            print(f"  {DIM}{i:2}.{RESET} {path.stem}{marker}  {DIM}{date_str}{RESET}")
        print(f"\n  {DIM}/sessions load <n>  \u2192 inject session as agent context{RESET}")
        print(f"  {DIM}/sessions clear     \u2192 remove loaded context{RESET}")
        print()

    def _show_history(self) -> None:
        print(f"\n{BOLD}{MAGENTA}\u25c6 {self.t('section.history')}{RESET}")
        print(_separator())
        if not self.state.prompt_history:
            print(f"  {DIM}{self.t('status.no_prompts')}{RESET}")
            return
        for idx, prompt in enumerate(self.state.prompt_history, start=1):
            print(f"  {DIM}{idx}.{RESET} {prompt}")
        print()

    def _change_directory(self, args: list[str]) -> None:
        if not args:
            print(f"{RED}Usage: /cd <path>{RESET}")
            return
        target = Path(args[0]).expanduser()
        if not target.is_absolute():
            target = (self.state.cwd / target).resolve()
        if not target.exists() or not target.is_dir():
            print(f"{RED}Directory not found: {target}{RESET}")
            return
        self.state.cwd = target
        print(f"{GREEN}{self.t('status.cwd_set')} {self.state.cwd}{RESET}")

    def _new_skill(self, args: list[str]) -> None:
        if not args:
            print(f"{RED}Usage: /new-skill <name>{RESET}")
            return
        name = " ".join(args).strip()
        slug = slugify(name)
        skill_dir = self.config.skills_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            skill_file.write_text(
                f"# {name}\n\n"
                "Summary: User-created skill.\n\n"
                "## When To Use\n\n"
                "- \n\n"
                "## Steps\n\n"
                "1. \n\n"
                "## Verification\n\n"
                "- \n\n"
                "## Caveats\n\n"
                "- \n",
                encoding="utf-8",
            )
        upsert_skill(self.config.memory_file, slug, "User-created skill.")
        self._load_skills_list()
        print(f"{GREEN}Created skill: {skill_file}{RESET}")

    def _build_progress_bar(self, progress: str) -> str:
        if not progress or "/" not in progress:
            return progress
        try:
            done, total = progress.split("/")
            done_n = int(done)
            total_n = int(total)
        except ValueError:
            return progress
        if total_n == 0:
            return "0/0"
        width = 16
        filled = int(width * done_n / total_n)
        bar = "█" * filled + "·" * (width - filled)
        return f"{GREEN}{bar}{RESET}  {GREEN}{done}/{total}{RESET}"

    def _show_plan_ui(self) -> None:
        plan = self.state.plan
        if not plan:
            return
        self._tui_emit(f"  plan: {plan.summary}  ({plan.progress()})")
        for s in plan.steps:
            icon = {"done": "✓", "running": "◌", "failed": "✗", "skipped": "⊙"}.get(s.status, "·")
            self._tui_emit(f"  {icon} {s.id}. {s.description}")
        self._tui_emit("")

    def _run_questionnaire(self, questions: list) -> list[str] | None:
        lang = self.config.lang or "en"
        is_es = lang == "es"

        print(f"\n{DIM}{_separator('\u2501')}{RESET}")
        header = "  \U0001f914 Necesito m\u00e1s detalles antes de crear el plan:" if is_es else "  \U0001f914 Need more details before creating the plan:"
        print(f"{BOLD}{CYAN}{header}{RESET}")
        print(f"{DIM}{_separator('\u2501')}{RESET}")

        answers: list[str] = []

        for qi, q in enumerate(questions, 1):
            if isinstance(q, dict):
                q_text = q.get("text", str(q))
                options = q.get("options", [])
            else:
                q_text = str(q)
                options = []

            print(f"\n  {BOLD}{YELLOW}{qi}. {q_text}{RESET}")

            if options:
                for i, opt in enumerate(options, 1):
                    print(f"     {CYAN}{i}{RESET}. {opt}")
                custom_n = len(options) + 1
                custom_lbl = "Respuesta personalizada..." if is_es else "Custom answer..."
                print(f"     {DIM}{custom_n}{RESET}. {DIM}{custom_lbl}{RESET}")

                prompt_hint = f"  \u276f [1-{custom_n}]: " if is_es else f"  \u276f Select [1-{custom_n}]: "
            else:
                prompt_hint = "  \u276f "

            while True:
                try:
                    from prompt_toolkit import prompt as pt_prompt
                    from prompt_toolkit.styles import Style
                    style = Style.from_dict({'prompt': '#D9926C bold'})
                    raw = pt_prompt(prompt_hint, style=style).strip()
                except (ImportError, KeyboardInterrupt, EOFError):
                    try:
                        raw = input(prompt_hint).strip()
                    except (KeyboardInterrupt, EOFError):
                        print(f"\n  {DIM}Cancelled.{RESET}")
                        return None

                if not raw:
                    continue

                if options:
                    if raw.isdigit():
                        idx = int(raw)
                        if 1 <= idx <= len(options):
                            ans = options[idx - 1]
                            print(f"     {GREEN}\u2713 {ans}{RESET}")
                            break
                        elif idx == len(options) + 1:
                            custom_prompt = "  \u276f Escribe tu respuesta: " if is_es else "  \u276f Type your answer: "
                            try:
                                from prompt_toolkit import prompt as pt_prompt
                                from prompt_toolkit.styles import Style
                                ans = pt_prompt(custom_prompt, style=Style.from_dict({'prompt': '#D9926C bold'})).strip()
                            except (ImportError, KeyboardInterrupt, EOFError):
                                ans = input(custom_prompt).strip()
                            if ans:
                                print(f"     {GREEN}\u2713 {ans}{RESET}")
                                break
                        else:
                            invalid = f"  {RED}Elige entre 1 y {len(options) + 1}.{RESET}" if is_es else f"  {RED}Choose between 1 and {len(options) + 1}.{RESET}"
                            print(invalid)
                    else:
                        ans = raw
                        print(f"     {GREEN}\u2713 {ans}{RESET}")
                        break
                else:
                    ans = raw
                    break

            answers.append(f"Q: {q_text}\nA: {ans}")

        print(f"\n{DIM}{_separator('\u2501')}{RESET}\n")
        return answers

    def _create_plan(self, prompt: str) -> AgentPlan | None:
        print(f"\n{DIM}{_separator('\u2501')}{RESET}")
        print(f"  {BOLD}{MAGENTA}\U0001f4cb Creating plan...{RESET}")
        lang = self.config.lang or "en"

        ctx = ""
        try:
            ctx = get_compact_context(self.state.cwd)
        except Exception:
            pass
        hist = ""
        try:
            if self.state.history:
                recent = self.state.history[-5:]
                hist = "\n".join(f"{h.get('role','?')}: {str(h.get('content',''))[:200]}" for h in recent)
        except Exception:
            pass

        plan_prompt = build_planner_prompt(prompt, system_context=ctx, history=hist, lang=lang)

        max_rounds = 3
        for round_num in range(max_rounds):
            try:
                ac = self._build_active_config()
                plan_model = self.config.effective_plan_model
                plan_provider = self.config.effective_plan_provider
                plan_api_base = self.config.effective_plan_api_base
                plan_api_key = self.config.effective_plan_api_key
                plan_api_endpoint = self.config.effective_plan_api_endpoint

                response = chat_completion(
                    plan_api_base or ac.api_base,
                    plan_api_key or ac.api_key,
                    plan_model or ac.model,
                    [{"role": "user", "content": plan_prompt}],
                    plan_api_endpoint or ac.api_endpoint,
                    min(ac.request_timeout, 60),
                )
                text = response.text.strip()

                if text.startswith("```"):
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()

                json_start = text.find("{")
                json_end = text.rfind("}")
                if json_start >= 0 and json_end > json_start:
                    text = text[json_start:json_end + 1]

                data = json.loads(text)

                if data.get("type") == "questions":
                    if round_num >= max_rounds - 1:
                        print(f"  {YELLOW}Max clarification rounds reached. Proceeding with available info.{RESET}")
                        break
                    questions = data.get("questions", [])
                    if not questions:
                        continue
                    answers = self._run_questionnaire(questions)
                    if answers is None:
                        return None
                    plan_prompt += "\n\nUser answers:\n" + "\n".join(answers)
                    continue

                plan = AgentPlan(prompt=prompt, summary=data.get("summary", ""))
                for i, step_data in enumerate(data.get("steps", []), 1):
                    plan.steps.append(PlanStep(
                        id=i,
                        description=step_data.get("description", ""),
                        detail=step_data.get("detail", ""),
                    ))
                if not plan.steps:
                    return None
                return plan
            except Exception as exc:
                print(f"  {RED}Failed to create plan: {exc}{RESET}")
                if round_num < max_rounds - 1:
                    continue
                return None
        return None

    def _match_action_to_plan(self, action: dict) -> int | None:
        plan = self.state.plan
        if not plan:
            return None

        kind = action.get("action", "")
        command = action.get("command", "")
        path = action.get("path", "")
        skill = action.get("skill", "")
        query = action.get("query", "")

        targets = [command, path, skill, query]
        target_text = " ".join(str(t).lower() for t in targets if t)

        for s in plan.steps:
            if s.status != "pending":
                continue
            step_text = f"{s.description} {s.detail}".lower()
            for word in step_text.split():
                if len(word) > 3 and word in target_text:
                    return s.id
            if kind and kind.lower() in step_text:
                return s.id
        return None

    def _run_prompt(self, prompt: str) -> None:
        prompt = self._expand_at_skills(prompt)
        prompt = self._expand_obsidian_links(prompt)
        self.state.prompt_history.append(prompt)
        self._total_runs += 1

        if self._plan_mode:
            plan = self._create_plan(prompt)
            if plan:
                self.state.plan = plan
                self._print_banner()
                self._show_plan_ui()
            else:
                self._output(f"  {DIM}Could not create plan. Executing directly.{RESET}")

        self._show_plan_ui()

        self._output(f"\n{_separator()}")
        self._output(f"  {BOLD}{CYAN}\u276f {RESET}{BOLD}{prompt}{RESET}")
        self._output(f"  {DIM}run #{self._total_runs}{RESET}")
        self._output(_separator())
        self._output(f"\n  {YELLOW}\U0001f914 {self.t('prompt.thinking')}{RESET}")
        sys.stdout.flush()

        active_config = self._build_active_config()

        ctx = Contextualizer(active_config, self._ctx_cfg) if self._ctx_cfg.enabled else None

        self._status["running"] = True
        self._status["current_action"] = ""
        if self.state.plan:
            self._status["plan_progress"] = self.state.plan.progress()
            self._status["plan_step"] = "Planning..."
        else:
            self._status["plan_progress"] = ""
            self._status["plan_step"] = ""
        self._refresh_sidebar()

        agent = Agent(
            config=active_config,
            cwd=self.state.cwd,
            event_handler=self._handle_agent_event,
            max_steps=self.max_steps,
            ephemeral=self._ephemeral,
            plan=self.state.plan,
            run_counter=self._total_runs,
            contextualizer=ctx,
        )

        session_ctx: list[dict] = []
        if not self._ephemeral:
            recent_runs = self.state.run_history[-self._session_context_turns:]
            for past in recent_runs:
                for ev in past.transcript:
                    if ev.role == "assistant":
                        session_ctx.append({"role": "assistant", "content": ev.content})
                    elif ev.role == "tool":
                        session_ctx.append({"role": "user", "content": f"Tool result:\n{ev.content}"})
            if self._loaded_session_context:
                session_ctx.insert(0, {
                    "role": "user",
                    "content": f"[Prior session context]\n{self._loaded_session_context[:3000]}\n[End prior session]"
                })

        result = agent.run_with_result(
            prompt,
            max_steps=self.max_steps,
            verbose=False,
            confirm_action=self._confirm_action,
            session_context=session_ctx if session_ctx else None,
        )
        self.state.run_history.append(result)
        self._print_run_result(result)

        if not self._ephemeral:
            self._save_run(prompt, result)

        self._maybe_validate(prompt, result)

        plan_done = False
        if hasattr(agent, "plan_executor") and agent.plan_executor:
            plan_done = agent.plan_executor.plan_complete
        elif self.state.plan and self.state.plan.is_complete():
            plan_done = True

        if plan_done:
            progress = ""
            if hasattr(agent, "plan_executor") and agent.plan_executor:
                progress = agent.plan_executor.progress_str()
            elif self.state.plan:
                progress = self.state.plan.progress()
            print(f"\n{GREEN}\u2705 Plan completed ({progress}){RESET}")
            self._print_banner()
            self.state.plan = None
        elif self.state.plan:
            progress = ""
            if hasattr(agent, "plan_executor") and agent.plan_executor:
                progress = agent.plan_executor.progress_str()
            else:
                progress = self.state.plan.progress()
            print(f"\n{YELLOW}\u26a0 Plan incomplete ({progress}). Clearing plan.{RESET}")
            self.state.plan = None

        self._status["running"] = False
        self._status["current_action"] = ""
        self._status["plan_progress"] = ""
        self._status["plan_step"] = ""
        self._refresh_sidebar()

        if self._training_mode and result.steps:
            self._maybe_save_training_example(prompt, result, active_config)

    def _maybe_save_training_example(self, prompt: str, result: AgentRunResult, active_config: Config) -> None:
        has_errors = any(step.result.startswith("ERROR:") for step in result.steps)
        if has_errors:
            return

        print(f"\n{DIM}{_separator('\u2501')}{RESET}")
        print(f"  {BOLD}{CYAN}\U0001f3cb\ufe0f  Training Mode{RESET}")
        print(f"  {GREEN}Task completed successfully ({len(result.steps)} steps).{RESET}")
        print()
        print(f"  {YELLOW}Save this as a training example?{RESET}")
        print(f"  {DIM}[Y]es  [N]o  [S]kip (don't ask again this session)  [Enter] skip{RESET}")

        self._ensure_cooked_terminal()

        try:
            choice = input(f"\n  {CYAN}{BOLD}delux \u276f {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("")
            return

        if choice == "y":
            model_name = self._active_model().name
            example = build_training_example(prompt, result.steps, result.answer, model_name)
            if save_example(self.config.root, example):
                stats = get_stats(self.config.root)
                print(f"  {GREEN}\u2705 Saved to dataset ({stats.total} total examples){RESET}")
            else:
                print(f"  {RED}Failed to save example.{RESET}")
        elif choice == "s":
            self._training_mode = False
            print(f"  {DIM}Training mode disabled for this session.{RESET}")
        elif choice == "n":
            print(f"  {DIM}Not saved.{RESET}")
        else:
            print(f"  {DIM}Skipped.{RESET}")

        print()

    def _ensure_cooked_terminal(self) -> None:
        try:
            import termios as _tc
            fd = sys.stdin.fileno()
            if sys.stdin.isatty():
                attrs = _tc.tcgetattr(fd)
                if not (attrs[3] & _tc.ICANON):
                    _tc.tcsetattr(fd, _tc.TCSAFLUSH, attrs)
        except Exception:
            pass

    def _maybe_validate(self, prompt: str, result: AgentRunResult) -> None:
        should_validate = self._validate_mode == "on" or self._validate_mode == "once"
        if self._validate_mode == "once":
            self._validate_mode = "off"
        has_delicate = any(_is_delicate(step.action, self.state.cwd) for step in result.steps)
        should_validate = should_validate or has_delicate

        if not should_validate:
            return
        self._run_validation(prompt, result)

    def _run_validation(self, prompt: str, result: AgentRunResult) -> None:
        print(f"\n{DIM}{_separator('\u2501')}{RESET}")
        print(f"  {BOLD}{YELLOW}\U0001f52c {self.t('validator.label')}{RESET}")

        validator_prompt = self._build_validator_prompt(prompt, result)
        vc = self._build_validator_config()

        try:
            response = chat_completion(
                vc.api_base, vc.api_key, vc.model, validator_prompt, vc.api_endpoint, vc.request_timeout,
            )
            print(f"  {response.text}")
        except Exception as exc:
            print(f"  {RED}Validator error: {exc}{RESET}")

        print(f"{DIM}{_separator('\u2501')}{RESET}\n")

    def _confirm_action(self, action: dict) -> bool:
        if not self._ask_mode:
            return True
        if not _is_delicate(action, self.state.cwd):
            return True

        print(f"\n{DIM}{_separator('\u2501')}{RESET}")
        print(f"  {BOLD}{YELLOW}\u2753 Ask Mode: Confirm Action{RESET}")
        kind = action.get("action", "")
        detail = action.get("command", action.get("path", ""))
        print(f"  {YELLOW}\u26a0 Delicate action: {kind} -> {detail}{RESET}")

        try:
            from prompt_toolkit.shortcuts import confirm
            ans = confirm("  Proceed? (y/n) ")
        except Exception:
            try:
                ans = input("  Proceed? [Y/n] ").strip().lower() not in ('n', 'no')
            except (EOFError, KeyboardInterrupt):
                ans = False

        print(f"{DIM}{_separator('\u2501')}{RESET}\n")
        return ans

    def _build_validator_prompt(self, prompt: str, result: AgentRunResult) -> list[dict]:
        steps_text = ""
        for step in result.steps:
            steps_text += f"\nStep {step.number}: {step.action.get('action', 'unknown')}\n"
            steps_text += f"  Action: {json.dumps(step.action, ensure_ascii=False)}\n"
            if step.result:
                steps_text += f"  Result: {step.result[:500]}\n"

        has_delicate = any(_is_delicate(step.action, self.state.cwd) for step in result.steps)
        delicate_tag = " (DESTRUCTIVE/CONFIG TASK - Be strict)" if has_delicate else ""

        plan_context = ""
        if self.state.plan:
            plan_context = f"\nOriginal plan:\n{self.state.plan.full_context()}\n"

        lang = self.config.lang or "en"
        if lang == "es":
            system = f"""Eres un validador para el asistente IA Delux. Eval\u00faa la siguiente ejecuci\u00f3n.{delicate_tag}

Responde en este formato JSON exacto:
{{
  "score": <1-10>,
  "correct": true/false,
  "issues": ["lista de problemas encontrados, o vac\u00edo"],
  "suggestions": ["sugerencias de mejora, o vac\u00edo"],
  "summary": "<veredicto breve>"
}}

S\u00e9 riguroso. Verifica:
- \u00bfLas acciones fueron apropiadas para la tarea?
- \u00bfHubo errores que se ignoraron?
- \u00bfLa respuesta final es precisa?
- \u00bfLas acciones destructivas fueron justificadas y seguras?"""
        else:
            system = f"""You are a validator for the Delux AI assistant. Evaluate the following execution.{delicate_tag}

Respond in this exact JSON format:
{{
  "score": <1-10>,
  "correct": true/false,
  "issues": ["list of issues found, or empty if none"],
  "suggestions": ["improvement suggestions, or empty"],
  "summary": "<brief verdict>"
}}

Be thorough. Check for:
- Were the actions appropriate for the task?
- Were there errors that were ignored?
- Is the final answer accurate?
- Were destructive actions justified and safe?"""

        user = f"""Task: {prompt}{plan_context}
Execution steps:
{steps_text}

Final answer:
{result.answer}"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _tui_emit(self, text: str, ansi: bool = False) -> None:
        import re as _re
        clean = _re.sub(r'\x1b\[[\d;?]*[ -/]*[@-~]', '', text)
        clean = _re.sub(r'\x1b[PX^_]', '', clean)
        self._output_log.append(clean)
        self._tui_refresh()

    def _output(self, *args, **kwargs) -> None:
        line = " ".join(str(a) for a in args)
        self._tui_emit(line)
        print(line, **kwargs)

    def _tui_refresh(self) -> None:
        if hasattr(self, '_live') and self._live:
            try:
                self._live.update(self._tui_render())
            except Exception:
                pass

    def _handle_agent_event(self, event: str, payload: dict) -> None:
        if event == "action_started":
            action = payload.get("action", {})
            kind = action.get("action", "unknown")

            if kind == "shell":
                cmd = str(action.get("command", ""))[:200]
                self._status["current_action"] = cmd[:50]
                self._tui_emit(f"  → shell  {cmd}")
            elif kind in ("write_file",):
                path = str(action.get("path", ""))
                content = str(action.get("content", ""))
                lines = content.count("\n") + 1 if content else 0
                self._status["current_action"] = f"write {path}"
                self._tui_emit(f"  → write  {path}  ({lines} lines)")
            elif kind in ("edit_file", "patch_file"):
                path = str(action.get("path", ""))
                old = str(action.get("old_str", ""))
                new = str(action.get("new_str", ""))
                added = new.count("\n") - old.count("\n")
                removed = old.count("\n") - new.count("\n")
                parts = []
                if added > 0: parts.append(f"+{added}")
                if removed > 0: parts.append(f"-{removed}")
                diff = f"  ({', '.join(parts)})" if parts else ""
                self._status["current_action"] = f"edit {path}"
                self._tui_emit(f"  → edit  {path}{diff}")
            elif kind in ("read_file", "view_file"):
                p = str(action.get("path", ""))
                self._status["current_action"] = f"read {p}"
                self._tui_emit(f"  → read  {p}")
            elif kind in ("search_files", "search_web", "rag_query"):
                q = str(action.get("query", ""))[:100]
                self._status["current_action"] = f"search {q}"
                self._tui_emit(f"  → search  '{q}'")
            elif kind == "rag_index":
                p = str(action.get("path", ""))
                self._status["current_action"] = f"index {p}"
                self._tui_emit(f"  → index  {p}")
            elif kind in ("verify_file",):
                p = str(action.get("path", ""))
                self._status["current_action"] = f"verify {p}"
                self._tui_emit(f"  → verify  {p}")
            elif kind == "create_skill":
                n = str(action.get("name", ""))
                self._status["current_action"] = f"skill {n}"
                self._tui_emit(f"  → skill  {n}")
            elif kind == "run_skill":
                s = str(action.get("skill", ""))
                a = str(action.get("args", ""))[:80]
                self._status["current_action"] = f"run {s}"
                self._tui_emit(f"  → {s}  {a}")
            elif kind == "move_file":
                src = str(action.get("src", ""))
                dst = str(action.get("dst", ""))
                self._status["current_action"] = f"move {src}"
                self._tui_emit(f"  → move  {src} → {dst}")
            elif kind in ("remember", "save_experience"):
                self._status["current_action"] = kind
                self._tui_emit(f"  → {kind}")
            elif kind == "skip_step":
                sid = action.get("step_id", "")
                reason = action.get("reason", "")
                self._status["current_action"] = f"skip {sid}"
                self._tui_emit(f"  → skip  step {sid}: {reason}")
            elif kind == "final":
                self._status["current_action"] = ""
                self._tui_emit(f"  ✓  {self.t('action.done')}")
            else:
                self._tui_emit(f"  → {kind}")

            self._tui_refresh()

        elif event == "shell_output":
            chunk = str(payload.get("chunk", ""))
            if not chunk:
                return
            for line in chunk.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                if line:
                    self._tui_emit(f"    {line}")

        elif event == "action_finished":
            action = payload.get("action", {})
            kind = action.get("action", "unknown")
            result = str(payload.get("result", "")).strip()
            ok = result.startswith("SUCCESS:")
            detail = result[8:] if ok else result[6:] if result.startswith("ERROR:") else result

            if ok:
                if detail:
                    self._tui_emit(f"  ✓  {detail[:300]}")
            else:
                self._tui_emit(f"  ✗  {detail[:300]}")

        elif event == "plan_step_active":
            step_id = payload.get("step_id")
            step_desc = payload.get("step_desc", "")
            progress = payload.get("progress", "")
            self._status["plan_progress"] = progress
            self._status["plan_step"] = f"Step {step_id}: {step_desc}"
            self._status["running"] = True
            if self.state.plan:
                self.state.plan.mark_running(step_id)
            bar = self._build_progress_bar(progress)
            print(f"\n  {MAGENTA}\u25c6 PLAN{RESET} {bar} {DIM}\u2014{RESET} Step {step_id}: {BOLD}{step_desc}{RESET}")
            self._show_plan_ui()
            self._refresh_sidebar()

        elif event == "plan_step_matched":
            step_id = payload.get("step_id")
            step_desc = payload.get("step_desc", "")
            if self.state.plan:
                self.state.plan.mark_running(step_id)
            print(f"  {DIM}\u2192 Plan step {step_id}: {step_desc}{RESET}")

        elif event == "plan_step_skipped":
            step_id = payload.get("step_id")
            reason = payload.get("reason", "")
            progress = payload.get("progress", "")
            bar = self._build_progress_bar(progress)
            print(f"  {YELLOW}\u23ed\ufe0f Step {step_id} skipped{RESET} {DIM}({reason}){RESET} {bar}")

        elif event == "plan_step_status":
            step_id = payload.get("step_id")
            ok = payload.get("ok", False)
            progress = payload.get("progress", "")
            if self.state.plan:
                self.state.plan.mark_done(step_id, ok)
            bar = self._build_progress_bar(progress)
            icon = f"{GREEN}\u2705{RESET}" if ok else f"{RED}\u274c{RESET}"
            print(f"  {icon} Step {step_id} {DIM}({progress}){RESET}")

        elif event == "plan_completed":
            summary = payload.get("summary", "")
            self._status["running"] = False
            self._status["plan_progress"] = ""
            self._status["plan_step"] = ""
            self._status["current_action"] = ""
            self._refresh_sidebar()
            print(f"\n  {GREEN}\u2705 Plan completed{RESET}")
            print(f"  {DIM}{summary}{RESET}")
            if self.state.plan:
                for s in self.state.plan.steps:
                    if s.status == "pending":
                        s.status = "done"
            self._show_plan_ui()

        elif event == "plan_final_blocked":
            step_id = payload.get("step_id")
            print(f"  {YELLOW}\u26a0 Final blocked{RESET} {DIM}(plan step {step_id} not complete, continuing){RESET}")

        elif event == "plan_max_steps_reached":
            summary = payload.get("summary", "")
            print(f"\n  {RED}\u274c Max steps reached{RESET}")
            print(f"  {DIM}{summary}{RESET}")

        elif event == "contextualizer_starting":
            print(f"  {DIM}\u2699\ufe0f  Optimizing context...{RESET}")

        elif event == "contextualizer_finished":
            savings = payload.get("savings", 0)
            changes = payload.get("changes", [])
            if savings > 0:
                print(f"  {GREEN}\u2699\ufe0f  Context optimized: {savings:.0f}% token savings{RESET}")
            for change in changes[:3]:
                print(f"    {DIM}- {change}{RESET}")

        elif event == "final_answer":
            print(f"  {_separator('\u2501')}")

    def _print_run_result(self, result: AgentRunResult) -> None:
        self._output(f"\n  {BOLD}{GREEN}\u2726{RESET} {BOLD}{self.t('answer.title')}{RESET}")
        self._output(f"  {DIM}\u2500{'\u2500' * min(60, _term_width() - 4)}{RESET}")
        self._output(f"  {result.answer}")
        self._output("")

    def _save_run(self, prompt: str, result: AgentRunResult) -> None:
        lines = [
            "# Delux Session",
            "",
            f"- Prompt: {prompt}",
            f"- CWD: {self.state.cwd}",
            f"- Model: {self.config.model}",
            "",
        ]
        if self.state.plan:
            lines.extend(["## Plan", "", self.state.plan.full_context(), ""])
        lines.extend(["## Steps", ""])
        if result.steps:
            for step in result.steps:
                lines.append(f"### {step.number}. {step.action.get('action', 'unknown')}")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(step.action, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")
                if step.action.get("action") != "final" and step.result.strip():
                    lines.append("```text")
                    lines.append(step.result)
                    lines.append("```")
                    lines.append("")
        else:
            lines.append("No tool steps.")
            lines.append("")
        lines.extend(["## Answer", "", result.answer, ""])
        path = save_session_markdown(self.config.sessions_dir, prompt, "\n".join(lines))
        self._output(f"  {DIM}{self.t('answer.saved')}: {path.name}{RESET}")

    def _save_notes(self, title: str) -> None:
        history = "\n".join(f"- {prompt}" for prompt in self.state.prompt_history) or "- none"
        result = "\n".join(
            f"- Run {idx}: {run.answer[:120]}" for idx, run in enumerate(self.state.run_history, start=1)
        ) or "- none"
        body = "\n".join(
            [
                "# Delux IDE Notes",
                "",
                f"- CWD: {self.state.cwd}",
                "",
                "## Prompt History",
                "",
                history,
                "",
                "## Run Summaries",
                "",
                result,
            ]
        )
        path = save_session_markdown(self.config.sessions_dir, title, body)
        self._output(f"{GREEN}{self.t('answer.saved_notes')}: {path}{RESET}")

    # ── /index command ────────────────────────────────────────────────────────

    def _cmd_index(self, args: list[str]) -> None:
        sub = args[0] if args else ""

        if not sub:
            if self._project_index is None:
                print(f"  {YELLOW}{self.t('index.not_built')}{RESET}")
                print(f"  {DIM}Run {BOLD}/index build{RESET}{DIM} to index the current project.{RESET}")
            else:
                print(f"\n{BOLD}{CYAN}◆ {self.t('index.status')}{RESET}")
                print(_separator())
                print(f"  {format_index_summary(self._project_index)}")
                vault_dir = self.config.root / OBSIDIAN_DIR / self._project_index.project
                if vault_dir.exists():
                    n = len(list(vault_dir.glob("*.md")))
                    print(f"  {DIM}Obsidian vault: {vault_dir}  ({n} notes){RESET}")

                store = EmbeddingStore.load(self.config.root, self._project_index.project)
                lbl = self.t('index.embeddings_status')
                if store.embeddings and store.embedding_model:
                    total = len(self._project_index.files)
                    count = len(store.embeddings)
                    print(f"  {DIM}{lbl}: {store.embedding_model} ({count}/{total} files){RESET}")
                else:
                    print(f"  {DIM}{lbl}: {self.config.embedding_model or 'none'}{RESET}")
                print()
            return

        # ── Build / Rebuild ───────────────────────────────────────────────────
        if sub in ("build", "rebuild"):
            force = (sub == "rebuild")
            print(f"\n  {YELLOW}⟳ {self.t('index.building')}...{RESET}")
