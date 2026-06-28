from __future__ import annotations

import asyncio
import json
import shlex
import time
from datetime import datetime
from pathlib import Path

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

from ..config import CONFIG_FILE, load_config
from ..store import (
    load_docs,
    load_memory,
    load_skills,
    save_session_markdown,
    slugify,
    upsert_skill,
)
from ..i18n import I18n, DEFAULT_LANG

SPLASH = """\
  ██████  ███████ ██      ██    ██ ██   ██
  ██   ██ ██      ██      ██    ██  ██ ██
  ██   ██ █████   ██      ██    ██   ███
  ██   ██ ██      ██      ██    ██  ██ ██
  ██████  ███████ ███████  ██████  ██   ██"""

WELCOME = """\
  Bienvenido a Delux Agent.
  Escribe /help para ver los comandos disponibles."""

COMMANDS: list[tuple[str, str, str]] = [
    ("/help, /?", "", "Muestra esta ayuda"),
    ("Ctrl+Space", "", "Alterna entre PLAN y BUILD"),
    ("/p, /plan", "[on|off]", "Modo plan (crea un plan antes de ejecutar)"),
    ("/v, /validate", "[on|off|once]", "Modo validación (revisa el output)"),
    ("/e, /ephemeral", "[on|off]", "Modo efímero (no guarda memoria)"),
    ("/a, /ask", "[on|off]", "Modo consulta (pide confirmación)"),
    ("/q, /quit", "", "Sale de la aplicación"),
    ("/clear", "", "Limpia la pantalla"),
    ("/status", "", "Muestra estado de la configuración"),
    ("/context", "", "Muestra memoria, skills y docs cargados"),
    ("/memory", "", "Muestra el contenido de la memoria"),
    ("/skills", "", "Lista las skills disponibles"),
    ("/docs", "", "Lista los documentos disponibles"),
    ("/config", "", "Muestra el archivo de configuración"),
    ("/sessions", "[load N|clear]", "Lista/ carga sesiones guardadas"),
    ("/history", "", "Muestra el historial de prompts"),
    ("/pwd", "", "Muestra el directorio actual"),
    ("/cd", "<path>", "Cambia el directorio de trabajo"),
    ("/new-skill", "<nombre>", "Crea una nueva skill"),
    ("/rs, /record-skill", "", "Crea una skill interactiva (graba comandos uno por uno)"),
    ("/save", "[título]", "Guarda la sesión actual"),
    ("/lang", "<en|es>", "Cambia el idioma"),
    ("/model", "[idx|add ...]", "Lista/ cambia/ añade modelos"),
    ("/vm", "[idx|off]", "Selecciona modelo de validación"),
    ("/sidebar", "[on|off]", "Muestra/oculta el panel lateral (Ctrl+B)"),
    ("/ctx, /contextualize", "", "Estado del contextualizador"),
    ("/index", "[build|rebuild]", "Gestiona el índice del proyecto"),
    ("/m, /mcp", "[add|rm|toggle|tools]", "Gestiona servidores MCP"),
    ("/template", "[model] [strategy|suffix ...]", "Muestra/configura plantilla de modelo"),
    ("/train, /tr", "[stats|list|clear|export]", "Gestiona ejemplos de feedback"),
    ("/compact", "", "Comprime el historial de conversación"),
]


# Wizard states for /record-skill
_WIZARD_IDLE = 0
_WIZARD_SKILL_NAME = 1
_WIZARD_SKILL_SUMMARY = 2
_WIZARD_RECORDING = 3
_WIZARD_CONFIRM = 4
_WIZARD_STEP_DESC = 5
_WIZARD_PARAM_ASK = 6
_WIZARD_PARAM_REWRITE = 7
_WIZARD_PARAM_DESC = 8
_WIZARD_PARAM_DETECT = 9
_WIZARD_EXEC_TYPE = 10


def _diff_preview(old: str, new: str, max_lines: int = 15) -> list[tuple[str, str]]:
    import difflib
    old_lines = old.split("\n")
    new_lines = new.split("\n")
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    if len(diff) >= 2:
        diff = diff[2:]
    result: list[tuple[str, str]] = []
    for line in diff[:max_lines]:
        if line.startswith("+"):
            result.append(("+", line[1:]))
        elif line.startswith("-"):
            result.append(("-", line[1:]))
        elif line.startswith("@@"):
            result.append(("@", line))
        else:
            result.append((" ", line[1:] if line.startswith(" ") else line))
    if len(diff) > max_lines:
        result.append(("...", f"({len(diff) - max_lines} more lines)"))
    return result


class DeluxTUI(App):
    CSS_PATH = "delux.tcss"

    BINDINGS = [
        ("ctrl+q", "quit", "Salir"),
        ("ctrl+l", "clear", "Limpiar"),
        ("ctrl+space", "toggle_plan", "Plan/Build"),
        ("ctrl+c", "cancel_stream", "Cancelar"),
        ("ctrl+up", "feedback_up", "[↑] Save"),
        ("ctrl+down", "feedback_down", "[↓] Discard"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
    ]

    _streaming: bool = False
    _splash_shown: bool = False

    def __init__(self, config, cwd: Path, max_steps: int = 12) -> None:
        super().__init__()
        self._config = config
        self._cwd = cwd
        self._max_steps = max_steps
        self._model_name = config.model or "deepseek"
        self._provider = (config.provider or "openai").upper()
        self._answer_count = 0
        self._total_tokens = 0
        self._plan_mode = False
        self._ask_mode = True
        self._ephemeral = False
        self._validate_mode = "off"
        self._prompt_history: list[str] = []
        self._lang = config.lang or DEFAULT_LANG
        self._i18n = I18n(self._lang)
        self._active_model_idx = 0
        self._validator_model_idx: int | None = None
        self._project_index = None
        self._wizard_state = _WIZARD_IDLE
        self._wizard_data: dict = {}
        self._last_prompt = ""
        self._last_answer = ""
        self._session_summary = ""
        self._conversation: list[dict] = []
        self._awaiting_input: str | None = None
        self._feedback_showing = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="app-grid"):
            with Container(id="chat-container"):
                yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
            with Vertical(id="sidebar"):
                yield Label("Información", id="sidebar-title")
                yield Label("Modelo", classes="sidebar-label")
                yield Label(self._model_name, id="sidebar-model", classes="sidebar-value")
                yield Label("Proveedor", classes="sidebar-label")
                yield Label(self._provider, id="sidebar-provider", classes="sidebar-value")
                yield Label("Plan Model", classes="sidebar-label")
                yield Label(self._config.effective_plan_model, id="sidebar-plan-model", classes="sidebar-value")
                yield Label("Tokens", classes="sidebar-label")
                yield Label("0", id="sidebar-tokens", classes="sidebar-value")
                yield Label("Tiempo", classes="sidebar-label")
                yield Label("0.0s", id="sidebar-time", classes="sidebar-value")
                yield Label("Pasos", classes="sidebar-label")
                yield Label("0", id="sidebar-steps", classes="sidebar-value")
                yield Label("Directorio", classes="sidebar-label")
                yield Label(str(self._cwd)[:24], id="sidebar-cwd", classes="sidebar-value")
                yield Label("Modos", classes="sidebar-label")
                yield Label("", id="sidebar-modes", classes="sidebar-value")
                yield Label("Estado", classes="sidebar-label")
                yield Label("Listo", id="sidebar-status", classes="sidebar-value")
        with Container(id="input-row"):
            yield Static("BUILD", id="mode-indicator")
            yield Input(placeholder="Escribe tu mensaje o /help...", id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self._show_splash()
        self._show_small_model_tip()
        self._update_mode_indicator()
        self._update_mode_indicator()
        self.query_one("#prompt-input", Input).focus()

    def _show_small_model_tip(self) -> None:
        from ..config import is_small_model
        if is_small_model(self._config.model) or self._config.small_model:
            provider = (self._config.provider or "").lower()
            cache_tips = {
                "ollama": "Ollama: OLLAMA_KEEP_ALIVE=24h mantiene el modelo en RAM",
                "lmstudio": "LM Studio: caché KV automática mientras el servidor corre",
            }
            tip_provider = cache_tips.get(provider, "")
            lines = [
                "[bold yellow]💡 Small Model Detected[/]",
                "[yellow]Tip: Send 'hi' or 'hola' first to warm up KV cache.[/]",
            ]
            if tip_provider:
                lines.append(f"[yellow]{tip_provider}[/]")
            lines.append("[yellow]llama.cpp: --cache-type-k q8_0 --cache-type-v q8_0[/]")
            lines.append("[yellow]Activar warmup: DELUX_CACHE_CHUNK_SIZE=512 o en config \"cache_chunk_size\": 512[/]")
            for line in lines:
                self._write_chat(Text.from_markup(line))
            self._write_chat(Text(""))

    def _show_splash(self) -> None:
        chat = self.query_one("#chat-log", RichLog)
        chat.clear()
        splash_text = Text(SPLASH, style="bold cyan")
        welcome_text = Text("\n\n" + WELCOME, style="dim")
        content = Text.assemble(splash_text, welcome_text)
        panel = Panel(content, box=box.ROUNDED, border_style="dim", padding=(1, 2))
        chat.write(panel)
        chat.write("")
        self._splash_shown = True

    def _write_chat(self, *renderables) -> None:
        chat = self.query_one("#chat-log", RichLog)
        for r in renderables:
            chat.write(r)

    def _sidebar_modes(self) -> str:
        parts = []
        if self._plan_mode:
            parts.append("[bold green]PLAN[/]")
        else:
            parts.append("[dim]BUILD[/]")
        from ..config import is_small_model
        if self._config.small_model or is_small_model(self._config.model):
            parts.append("[yellow]small[/]")
        if self._ask_mode:
            parts.append("ask")
        if self._ephemeral:
            parts.append("ephem")
        if self._validate_mode != "off":
            parts.append(f"val:{self._validate_mode}")
        return " ".join(parts) if parts else "—"

    def _update_mode_indicator(self) -> None:
        try:
            indicator = self.query_one("#mode-indicator", Static)
            if self._plan_mode:
                indicator.update("[bold green]PLAN[/]")
            else:
                indicator.update("[dim]BUILD[/]")
        except Exception:
            pass
        try:
            from rich.text import Text as RichText
            from textual.widgets import Label as TLabel
            label = self.query_one("#sidebar-modes", TLabel)
            label.update(RichText.from_markup(self._sidebar_modes()))
        except Exception:
            pass

    def action_toggle_plan(self) -> None:
        self._plan_mode = not self._plan_mode
        plan_model = self._config.effective_plan_model
        try:
            self._write_chat(Text(
                f"  Plan mode: {'ON' if self._plan_mode else 'OFF'}"
                + (f" (modelo: {plan_model})" if self._plan_mode else ""),
                style="bold green" if self._plan_mode else "dim",
            ))
        except Exception:
            pass
        self._update_mode_indicator()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Vertical)
        grid = self.query_one("#app-grid", Container)
        if sidebar.styles.display == "none":
            sidebar.styles.display = "block"
            grid.styles.grid_columns = "1fr 30"
            self._write_chat(Text("  Sidebar: visible", style="dim"))
        else:
            sidebar.styles.display = "none"
            grid.styles.grid_columns = "1fr 0"
            self._write_chat(Text("  Sidebar: oculto", style="dim"))

    def _set_status(self, status: str) -> None:
        try:
            self.query_one("#sidebar-status", Label).update(status)
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self._streaming:
            return

        inp = self.query_one("#prompt-input", Input)
        inp.value = ""

        if self._feedback_showing:
            self._hide_feedback_prompt()

        if self._awaiting_input:
            await self._handle_awaited_input(text)
            inp.focus()
            return

        if self._wizard_state != _WIZARD_IDLE:
            await self._handle_wizard_input(text)
            inp.focus()
            return

        if text.startswith("/"):
            await self._handle_command(text)
            inp.focus()
            return

        self._prompt_history.append(text)
        self._write_chat(Text(f"\n  ❯ {text}\n", style="bold green"))
        self._streaming = True
        inp.disabled = True
        self._set_status("Pensando...")
        self._update_mode_indicator()
        self._stream_response(text)

    async def _handle_command(self, raw: str) -> None:
        try:
            parts = shlex.split(raw)
        except Exception:
            parts = raw.split()
        command = parts[0]
        args = parts[1:]

        cmd_map: dict[str, str] = {
            "/help": "help", "/?": "help",
            "/p": "plan", "/plan": "plan",
            "/v": "validate", "/validate": "validate",
            "/e": "ephemeral", "/ephemeral": "ephemeral",
            "/a": "ask", "/ask": "ask",
            "/q": "quit", "/quit": "quit",
            "/clear": "clear",
            "/status": "status",
            "/context": "context",
            "/memory": "memory",
            "/skills": "skills",
            "/docs": "docs",
            "/config": "config",
            "/sessions": "sessions",
            "/history": "history",
            "/pwd": "pwd",
            "/cd": "cd",
            "/new-skill": "new_skill",
            "/record-skill": "record_skill", "/rs": "record_skill",
            "/save": "save",
            "/lang": "lang",
            "/model": "model",
            "/vm": "vm",
            "/sidebar": "sidebar",
            "/ctx": "ctx", "/contextualize": "ctx",
            "/index": "index",
            "/m": "mcp", "/mcp": "mcp",
            "/template": "template",
            "/ft": "finetune", "/finetune": "finetune",
            "/train": "train", "/tr": "train",
            "/compact": "compact",
        }

        handler = cmd_map.get(command)
        if handler is None:
            self._write_chat(
                Text(f"  Comando desconocido: {command}", style="red"),
                Text("  Escribe /help para ver los comandos disponibles.", style="dim"),
            )
            return

        method = getattr(self, f"_cmd_{handler}", None)
        if method:
            await method(args)
        else:
            self._write_chat(Text(f"  Comando no implementado aún: {command}", style="yellow"))

    async def _cmd_help(self, args: list[str]) -> None:
        table = Table(box=box.SIMPLE, border_style="dim", padding=(0, 1))
        table.add_column("Comando", style="bold cyan")
        table.add_column("Args", style="dim")
        table.add_column("Descripción", style="white")
        for cmd, arg, desc in COMMANDS:
            table.add_row(cmd, arg, desc)
        self._write_chat(
            Text("\n  Comandos disponibles:\n", style="bold"),
            table,
            Text("  Ctrl+Space: Plan/Build  |  Ctrl+Q: Salir  |  Ctrl+L: Limpiar pantalla\n", style="dim"),
        )

    async def _cmd_plan(self, args: list[str]) -> None:
        if not args or args[0] in ("toggle",):
            self._plan_mode = not self._plan_mode
        elif args[0] == "on":
            self._plan_mode = True
        elif args[0] == "off":
            self._plan_mode = False
        else:
            self._write_chat(Text(f"  Usa: /plan [on|off]", style="yellow"))
            return
        plan_model = self._config.effective_plan_model
        state = "ON" if self._plan_mode else "OFF"
        mode_info = f"  Plan mode: {state}" + (f" (modelo: {plan_model})" if self._plan_mode else "")
        self._write_chat(Text(mode_info, style="bold green" if self._plan_mode else "dim"))
        self._update_mode_indicator()

    async def _cmd_validate(self, args: list[str]) -> None:
        if not args:
            self._validate_mode = "on" if self._validate_mode == "off" else "off"
        elif args[0] in ("on", "off", "once"):
            self._validate_mode = args[0]
        else:
            self._write_chat(Text(f"  Usa: /validate [on|off|once]", style="yellow"))
            return
        self._write_chat(Text(f"  Validate: {self._validate_mode.upper()}", style="green" if self._validate_mode != "off" else "dim"))
        self._update_mode_indicator()

    async def _cmd_ephemeral(self, args: list[str]) -> None:
        if not args:
            self._ephemeral = not self._ephemeral
        elif args[0] == "on":
            self._ephemeral = True
        elif args[0] == "off":
            self._ephemeral = False
        else:
            self._write_chat(Text(f"  Usa: /ephemeral [on|off]", style="yellow"))
            return
        state = "ON" if self._ephemeral else "OFF"
        self._write_chat(Text(f"  Ephemeral: {state}", style="green" if self._ephemeral else "dim"))
        self._update_mode_indicator()

    async def _cmd_ask(self, args: list[str]) -> None:
        if not args:
            self._ask_mode = not self._ask_mode
        elif args[0] == "on":
            self._ask_mode = True
        elif args[0] == "off":
            self._ask_mode = False
        else:
            self._write_chat(Text(f"  Usa: /ask [on|off]", style="yellow"))
            return
        state = "ON" if self._ask_mode else "OFF"
        self._write_chat(Text(f"  Ask: {state}", style="green" if self._ask_mode else "dim"))
        self._update_mode_indicator()

    async def _cmd_quit(self, args: list[str]) -> None:
        self.exit()

    async def _cmd_clear(self, args: list[str]) -> None:
        self._show_splash()

    async def _cmd_status(self, args: list[str]) -> None:
        c = self._config
        from ..config import is_small_model
        table = Table(box=box.SIMPLE, border_style="dim", padding=(0, 1))
        table.add_column("Clave", style="bold cyan")
        table.add_column("Valor", style="white")
        table.add_row("Provider", c.provider or "—")
        table.add_row("Modelo", c.model or "—")
        table.add_row("Endpoint", c.api_endpoint or "—")
        table.add_row("Directorio", str(self._cwd))
        table.add_row("API Key", "✓ configurada" if c.api_key else "✗ no configurada")
        table.add_row("Timeout", f"{c.request_timeout}s")
        small_flag = " ✓" if (c.small_model or is_small_model(c.model)) else ""
        chunk_val = f"{c.cache_chunk_size} tokens" if c.cache_chunk_size > 0 else "off"
        table.add_row("Caché chunk", f"{chunk_val}{small_flag}")
        table.add_row("Idioma", self._lang)
        table.add_row("Modos", self._sidebar_modes())
        table.add_row("Total runs", str(self._answer_count))
        table.add_row("Tokens totales", str(self._total_tokens))
        self._write_chat(Text("\n  Estado:\n", style="bold"), table)

    async def _cmd_context(self, args: list[str]) -> None:
        c = self._config
        memory = load_memory(c.memory_file)[:500]
        skills = load_skills(c.builtin_skills_dir, c.skills_dir)
        docs = load_docs(c.docs_dir)[:500]

        self._write_chat(Text("\n  Contexto cargado:\n", style="bold"))
        if memory.strip():
            self._write_chat(Panel(memory.strip(), title="Memoria", border_style="dim"))
        else:
            self._write_chat(Text("  Memoria: vacía", style="dim"))
        if skills:
            skill_lines = "\n".join(f"  • {s.name}: {s.summary}" for s in skills)
            self._write_chat(Panel(skill_lines, title="Skills", border_style="dim"))
        else:
            self._write_chat(Text("  Skills: ninguna", style="dim"))
        if docs:
            self._write_chat(Panel(docs.strip(), title="Docs", border_style="dim"))
        else:
            self._write_chat(Text("  Docs: ninguno", style="dim"))

    async def _cmd_memory(self, args: list[str]) -> None:
        memory = load_memory(self._config.memory_file)
        self._write_chat(
            Text("\n  Memoria:\n", style="bold"),
            Panel(memory or "  (vacía)", border_style="dim"),
        )

    async def _cmd_skills(self, args: list[str]) -> None:
        skills = load_skills(self._config.builtin_skills_dir, self._config.skills_dir)
        if not skills:
            self._write_chat(Text("  No hay skills instaladas.", style="dim"))
            return
        table = Table(box=box.SIMPLE, border_style="dim", padding=(0, 1))
        table.add_column("Skill", style="bold cyan")
        table.add_column("Resumen", style="white")
        for s in skills:
            badge = f" [exec:{s.exec_lang}]" if s.has_exec else ""
            table.add_row(f"{s.name}{badge}", s.summary or "—")
        self._write_chat(Text("\n  Skills disponibles:\n", style="bold"), table)

    async def _cmd_docs(self, args: list[str]) -> None:
        docs = load_docs(self._config.docs_dir)
        self._write_chat(
            Text("\n  Documentos:\n", style="bold"),
            Panel(docs or "  (no hay docs)", border_style="dim"),
        )

    async def _cmd_config(self, args: list[str]) -> None:
        path = self._config.root / CONFIG_FILE
        if path.exists():
            content = path.read_text(encoding="utf-8")
            self._write_chat(
                Text(f"\n  Config ({path}):\n", style="bold"),
                Panel(content, border_style="dim"),
            )
        else:
            self._write_chat(Text(f"  No se encontró {path}", style="red"))

    async def _cmd_sessions(self, args: list[str]) -> None:
        if args and args[0] == "clear":
            self._write_chat(Text("  Contexto de sesión limpiado.", style="dim"))
            return
        sessions_dir = self._config.sessions_dir
        if not sessions_dir.exists():
            self._write_chat(Text("  No hay sesiones guardadas.", style="dim"))
            return
        files = sorted(sessions_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        if not files:
            self._write_chat(Text("  No hay sesiones guardadas.", style="dim"))
            return
        table = Table(box=box.SIMPLE, border_style="dim", padding=(0, 1))
        table.add_column("#", style="bold cyan")
        table.add_column("Archivo", style="white")
        for i, f in enumerate(files, 1):
            table.add_row(str(i), f.name)
        self._write_chat(
            Text("\n  Sesiones guardadas (últimas 20):\n", style="bold"),
            table,
            Text("  Usa /sessions load <N> para cargar una sesión.", style="dim"),
        )

    async def _cmd_history(self, args: list[str]) -> None:
        if not self._prompt_history:
            self._write_chat(Text("  No hay historial de prompts.", style="dim"))
            return
        table = Table(box=box.SIMPLE, border_style="dim", padding=(0, 1))
        table.add_column("#", style="bold cyan")
        table.add_column("Prompt", style="white")
        for i, p in enumerate(self._prompt_history[-30:], 1):
            table.add_row(str(i), p[:80])
        self._write_chat(Text("\n  Historial de prompts:\n", style="bold"), table)

    async def _cmd_pwd(self, args: list[str]) -> None:
        self._write_chat(Text(f"  {self._cwd}", style="cyan"))

    async def _cmd_cd(self, args: list[str]) -> None:
        if not args:
            self._write_chat(Text(f"  {self._cwd}", style="cyan"))
            return
        try:
            new = Path(args[0]).expanduser().resolve()
            if new.is_dir():
                self._cwd = new
                self.query_one("#sidebar-cwd", Label).update(str(new)[:24])
                self._write_chat(Text(f"  → {new}", style="green"))
            else:
                self._write_chat(Text(f"  No es un directorio: {new}", style="red"))
        except Exception as e:
            self._write_chat(Text(f"  Error: {e}", style="red"))

    async def _cmd_new_skill(self, args: list[str]) -> None:
        name = " ".join(args).strip()
        if not name:
            self._write_chat(Text("  Usa: /new-skill <nombre>", style="yellow"))
            return
        try:
            slug = slugify(name)
            skill_dir = self._config.skills_dir / slug
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                skill_file.write_text(
                    f"# {name}\n\n"
                    "Summary: \n\n"
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
            upsert_skill(self._config.memory_file, slug, "User-created skill.")
            self._write_chat(Text(f"  Skill creada: {skill_file}", style="green"))
        except Exception as e:
            self._write_chat(Text(f"  Error: {e}", style="red"))

    # ── /record-skill Wizard ──

    async def _cmd_record_skill(self, args: list[str]) -> None:
        """Start the interactive skill recording wizard."""
        self._wizard_data = {
            "name": "",
            "summary": "",
            "steps": [],
            "pending_cmd": "",
            "pending_output": "",
            "pending_rc": 0,
            "step_num": 0,
        }
        self._wizard_state = _WIZARD_SKILL_NAME
        self._write_chat(Text(""))
        self._write_chat(Panel(
            "This wizard will help you create a skill interactively.\n"
            "You will provide a name, summary, and record terminal commands\n"
            "one by one. Each command will be executed so you can verify it works.\n"
            "At the end, everything will be packaged into a proper skill.",
            title="🔧 Skill Recorder",
            border_style="cyan",
        ))
        self._write_chat(Text("\n  Step 1/3: What is the name of the skill?", style="bold cyan"))

    async def _handle_wizard_input(self, text: str) -> None:
        state = self._wizard_state

        if state == _WIZARD_SKILL_NAME:
            name = text.strip()
            if not name:
                self._write_chat(Text("  Name cannot be empty.", style="red"))
                return
            self._wizard_data["name"] = name
            self._wizard_state = _WIZARD_SKILL_SUMMARY
            self._write_chat(Text(f"  ✓ Name: {name}", style="green"))
            self._write_chat(Text("\n  Step 2/3: What does this skill do? (one-line summary)", style="bold cyan"))

        elif state == _WIZARD_SKILL_SUMMARY:
            summary = text.strip()
            if not summary:
                self._write_chat(Text("  Summary cannot be empty.", style="red"))
                return
            self._wizard_data["summary"] = summary
            self._wizard_data["step_num"] = 1
            self._wizard_state = _WIZARD_RECORDING
            self._write_chat(Text(f"  ✓ Summary: {summary}", style="green"))
            self._write_chat(Text(""))
            self._write_chat(Text("  Now let's record the terminal commands for each step.", style="bold"))
            self._write_chat(Text("  Enter a command, and I'll execute it so you can verify the output.", style="dim"))
            self._write_chat(Text('  Type [bold]done[/] when all steps are recorded, or [bold]cancel[/] to abort.', style="dim"))
            self._write_chat(Text(""))
            self._write_chat(Text("  Step 1: Enter a command:", style="bold cyan"))

        elif state == _WIZARD_RECORDING:
            cmd = text.strip()
            if not cmd:
                return
            if cmd.lower() in ("done", "exit", "finish"):
                self._write_chat(Text("  Script type: bash (shell) or python? [bash/py]:", style="cyan"))
                self._wizard_state = _WIZARD_EXEC_TYPE
                return
            if cmd.lower() == "cancel":
                self._write_chat(Text("  Wizard cancelled.", style="yellow"))
                self._wizard_state = _WIZARD_IDLE
                self._wizard_data = {}
                return

            self._write_chat(Text(f"\n  → $ {cmd}", style="yellow"))
            self._write_chat(Text("  Running...", style="dim"))

            stdout, stderr, rc = await self._run_cmd(cmd)
            output = stdout + stderr

            if output.strip():
                lines = output.strip().split("\n")
                if len(lines) > 40:
                    lines = lines[:40]
                    lines.append(f"  ... ({len(output.strip().split(chr(10))) - 40} more lines truncated)")
                for line in lines:
                    self._write_chat(Text(f"    {line}", style="dim"))
            self._write_chat(Text(f"  → exit code: {rc}", style="green" if rc == 0 else "red"))

            self._wizard_data["pending_cmd"] = cmd
            self._wizard_data["pending_output"] = output.strip()
            self._wizard_data["pending_rc"] = rc
            self._wizard_state = _WIZARD_CONFIRM
            self._write_chat(Text("  Keep this step? [Y/n] (or 'edit' to modify the command):", style="cyan"))

        elif state == _WIZARD_CONFIRM:
            choice = text.strip().lower()
            if choice in ("", "y", "yes"):
                self._wizard_state = _WIZARD_STEP_DESC
                self._write_chat(Text("  Description for this step (optional, press Enter to skip):", style="cyan"))
            elif choice in ("n", "no"):
                self._wizard_state = _WIZARD_RECORDING
                self._write_chat(Text("  Step discarded.", style="dim"))
                sn = self._wizard_data["step_num"]
                self._write_chat(Text(f"  Step {sn}: Enter a command (or 'done' to finish):", style="bold cyan"))
            elif choice == "edit":
                self._wizard_state = _WIZARD_RECORDING
                sn = self._wizard_data["step_num"]
                self._write_chat(Text("  Re-enter the command (or 'done' to finish):", style="yellow"))
            else:
                self._write_chat(Text("  Please answer Y, n, or edit:", style="yellow"))

        elif state == _WIZARD_PARAM_ASK:
            choice = text.strip().lower()
            if choice in ("", "n", "no"):
                sn = self._wizard_data["step_num"] + 1
                self._wizard_data["step_num"] = sn
                self._wizard_state = _WIZARD_RECORDING
                self._write_chat(Text(f"  Step {sn}: Enter a command (or 'done' to finish):", style="bold cyan"))
            elif choice in ("y", "yes"):
                self._wizard_state = _WIZARD_PARAM_REWRITE
                self._write_chat(Text("  Enter the command with {variable} placeholders:", style="cyan"))
                self._write_chat(Text(f"  Original: {self._wizard_data['pending_cmd']}", style="dim"))
            else:
                self._write_chat(Text("  Please answer y or N:", style="yellow"))

        elif state == _WIZARD_PARAM_REWRITE:
            cmd = text.strip()
            if not cmd:
                return
            import re
            vars_found = re.findall(r'\{(\w+)\}', cmd)
            if not vars_found:
                self._write_chat(Text("  No variables found. Use {name} syntax.", style="yellow"))
                return
            idx = self._wizard_data["_pending_step_idx"]
            self._wizard_data["steps"][idx]["command"] = cmd
            self._wizard_data["pending_var_names"] = vars_found
            self._wizard_data["pending_var_idx"] = 0
            self._wizard_data["pending_var_descs"] = {}
            self._wizard_state = _WIZARD_PARAM_DESC
            self._write_chat(Text(f"  Variables: {', '.join(vars_found)}", style="green"))
            self._write_chat(Text(f"  Description for '{vars_found[0]}':", style="cyan"))

        elif state == _WIZARD_PARAM_DESC:
            desc = text.strip()
            idx = self._wizard_data["pending_var_idx"]
            names = self._wizard_data["pending_var_names"]
            cur_var = names[idx]
            if desc:
                self._wizard_data["pending_var_descs"][cur_var] = desc
            else:
                self._wizard_data["pending_var_descs"][cur_var] = cur_var
            if idx + 1 < len(names):
                self._wizard_data["pending_var_idx"] = idx + 1
                self._write_chat(Text(f"  Description for '{names[idx + 1]}':", style="cyan"))
            else:
                step_idx = self._wizard_data["_pending_step_idx"]
                self._wizard_data["steps"][step_idx]["variables"] = dict(self._wizard_data["pending_var_descs"])
                self._wizard_data["pending_detect_idx"] = 0
                self._wizard_data["pending_detect_data"] = {}
                self._wizard_state = _WIZARD_PARAM_DETECT
                self._write_chat(Text("  Auto-detect or default values for variables? [y/N]:", style="cyan"))

        elif state == _WIZARD_PARAM_DETECT:
            idx = self._wizard_data.get("_pending_step_idx", 0)
            names = list(self._wizard_data["steps"][idx].get("variables", {}).keys())
            di = self._wizard_data.get("pending_detect_idx", 0)

            if di == 0 and text.strip().lower() in ("", "n", "no"):
                # Skip auto-detect entirely
                self._wizard_data["steps"][idx]["detect"] = {}
                sn = self._wizard_data["step_num"] + 1
                self._wizard_data["step_num"] = sn
                self._wizard_state = _WIZARD_RECORDING
                self._write_chat(Text(f"  Step {sn}: Enter a command (or 'done' to finish):", style="bold cyan"))

            elif di < len(names):
                cur = names[di]
                if di == 0 and text.strip().lower() in ("y", "yes"):
                    self._wizard_data["pending_detect_data"] = {}
                    self._write_chat(Text(f"  Auto-detect command for '{cur}' (or Enter to skip):", style="cyan"))
                    self._wizard_data["pending_detect_idx"] = 1
                elif di > 0:
                    cmd_detect = text.strip()
                    if cmd_detect:
                        self._wizard_data["pending_detect_data"][names[di - 1]] = cmd_detect
                    if di < len(names):
                        self._write_chat(Text(f"  Auto-detect command for '{names[di]}' (or Enter to skip):", style="cyan"))
                        self._wizard_data["pending_detect_idx"] = di + 1
                    else:
                        self._wizard_data["steps"][idx]["detect"] = dict(self._wizard_data["pending_detect_data"])
                        sn = self._wizard_data["step_num"] + 1
                        self._wizard_data["step_num"] = sn
                        self._wizard_state = _WIZARD_RECORDING
                        self._write_chat(Text(f"  Step {sn}: Enter a command (or 'done' to finish):", style="bold cyan"))
                else:
                    self._write_chat(Text("  Answer y or N:", style="yellow"))
            else:
                self._write_chat(Text(f"  Step {sn}: Enter a command (or 'done' to finish):", style="bold cyan"))
                self._wizard_state = _WIZARD_RECORDING

        elif state == _WIZARD_EXEC_TYPE:
            choice = text.strip().lower()
            if choice in ("", "bash", "b", "sh"):
                self._wizard_data["exec_type"] = "bash"
            elif choice in ("python", "py", "p"):
                self._wizard_data["exec_type"] = "python"
            else:
                self._write_chat(Text("  Choose bash or python:", style="yellow"))
                return
            await self._finalize_wizard()

        elif state == _WIZARD_STEP_DESC:
            desc = text.strip()
            step_data = {
                "command": self._wizard_data["pending_cmd"],
                "output": self._wizard_data["pending_output"],
                "description": desc,
                "success": self._wizard_data.get("pending_rc", 0) == 0,
                "variables": {},
            }
            self._wizard_data["steps"].append(step_data)
            self._wizard_data["_pending_step_idx"] = len(self._wizard_data["steps"]) - 1
            self._wizard_state = _WIZARD_PARAM_ASK
            self._write_chat(Text(f"  ✅ Step recorded: {step_data['command'][:60]}", style="green"))
            self._write_chat(Text("  Parameterize this command with variables? [y/N]:", style="cyan"))

    async def _run_cmd(self, cmd: str) -> tuple[str, str, int]:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._cwd),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                return "", "Command timed out (30s)", -1
            return stdout.decode(errors="replace"), stderr.decode(errors="replace"), proc.returncode or 0
        except Exception as e:
            return "", str(e), -1

    async def _finalize_wizard(self) -> None:
        data = self._wizard_data
        steps = data["steps"]

        if not steps:
            self._write_chat(Text("  No steps recorded. Wizard cancelled.", style="red"))
            self._wizard_state = _WIZARD_IDLE
            self._wizard_data = {}
            return

        self._write_chat(Text(""))
        self._write_chat(Text(f"  Generating skill with {len(steps)} step(s)...", style="bold green"))

        name = data["name"]
        summary = data["summary"]
        slug = slugify(name)

        skill_dir = self._config.skills_dir / slug
        if skill_dir.exists():
            self._write_chat(Text(f"  ⚠ Skill `{slug}` already exists. Overwriting.", style="yellow"))

        # ── Collect all variables and detect commands across steps ──
        import re
        all_vars: list[str] = []
        var_descs: dict[str, str] = {}
        detect_commands: dict[str, str] = {}
        for s in steps:
            for vname, vdesc in s.get("variables", {}).items():
                if vname not in var_descs:
                    all_vars.append(vname)
                    var_descs[vname] = vdesc
            for vn, detect_cmd in s.get("detect", {}).items():
                if detect_cmd and vn not in detect_commands:
                    detect_commands[vn] = detect_cmd

        has_vars = bool(all_vars)
        args_label = " ".join(f"<{v}>" for v in all_vars) if has_vars else "[arguments]"
        args_json = " ".join(f"{v}=<value>" for v in all_vars) if has_vars else ""

        steps_text = ""
        for i, s in enumerate(steps, 1):
            cmd_display = s["command"]
            steps_text += f"{i}. `{cmd_display}`"
            if s["description"]:
                steps_text += f" — {s['description']}"
            steps_text += "\n"
            if s.get("variables"):
                for vn, vd in s["variables"].items():
                    steps_text += f"   - `{vn}`: {vd}\n"

        # ── Build args section ──
        args_section = ""
        if has_vars:
            args_section = "## Arguments\n\n"
            for v in all_vars:
                args_section += f"- `{v}`: {var_descs.get(v, v)}\n"
                if v in detect_commands:
                    args_section += f"  - Auto-detects with: `{detect_commands[v]}` if not provided\n"

        skill_body = f"""# {name}

Summary: {summary}

## When To Use

- {summary.lower()}

## Usage

{slug} {args_label}

{args_section}## Steps

{steps_text}
## Response Examples

### Agent invoca la skill
```json
{{"action":"run_skill","skill":"{slug}","args":"{args_json}","timeout":30}}
```

### Skill devuelve resultado
```json
{{"status":"ok","result":"done"}}
```

### Prompt injection example
```
--- {slug} example ---
USER: "<task description>"
AGENT: {{"action":"run_skill","skill":"{slug}","args":"{args_json}","timeout":30}}
RESULT: {{"status":"ok","result":"done"}}
NEXT ACTION: {{"action":"final","answer":"Task completed."}}
```

## Caveats

- Tested on this machine only; adapt paths as needed
"""

        # ── Determine exec type ──
        exec_type = data.get("exec_type", "bash")

        # ── Build exec script ──
        if exec_type == "python":
            exec_ext = "py"
            exec_lines = [
                "#!/usr/bin/env python3",
                f'"""Auto-generated by /record-skill — {name}"""',
                "",
                "import sys, subprocess, json, shlex",
                "",
            ]
            if has_vars:
                exec_lines.append(f"# Arguments: {' '.join(f'${{i+1}}={v}' for i, v in enumerate(all_vars))}")
                for i, v in enumerate(all_vars, 1):
                    exec_lines.append(f'{v} = sys.argv[{i}] if len(sys.argv) > {i - 1} and sys.argv[{i}] else None')
                exec_lines.append("")
                if detect_commands:
                    for vn, detect_cmd in detect_commands.items():
                        exec_lines.append(f'if not {vn}:')
                        exec_lines.append(f'    result = subprocess.run(shlex.split("{detect_cmd}"), capture_output=True, text=True)')
                        exec_lines.append(f'    {vn} = result.stdout.strip()')
                    exec_lines.append("")

            for idx, s in enumerate(steps, 1):
                cmd = s["command"]
                for vn in all_vars:
                    cmd = cmd.replace("{" + vn + "}", f'{{{vn}}}').replace("$", "")
                if s["description"]:
                    exec_lines.append(f"    # Step {idx}: {s['description']}")
                exec_lines.append(f'    print(f"  → Step {idx}: {cmd}")')
                exec_lines.append(f'    r = subprocess.run(shlex.split(f"""{cmd}"""), capture_output=True, text=True)')
                exec_lines.append(f'    sys.stdout.write(r.stdout)')
                exec_lines.append(f'    sys.stderr.write(r.stderr)')
                exec_lines.append(f'    if r.returncode != 0:')
                exec_lines.append(f'        print(json.dumps({{"status":"error","step":{idx},"msg":r.stderr.strip()}}))')
                exec_lines.append(f'        sys.exit(r.returncode)')
                exec_lines.append("")
            exec_code = "\n".join(exec_lines)
        else:
            exec_ext = "bash"
            exec_lines = [
                "#!/usr/bin/env bash",
                "# Auto-generated by /record-skill",
                f"# Skill: {name}",
                "",
                "set -euo pipefail",
                "",
            ]
            if has_vars:
                exec_lines.append(f"# Arguments: {' '.join(f'${{i+1}}={v}' for i, v in enumerate(all_vars))}")
                for i, v in enumerate(all_vars, 1):
                    exec_lines.append(f'{v}="${{{i}}}"')
                exec_lines.append("")
                if detect_commands:
                    for vn, detect_cmd in detect_commands.items():
                        exec_lines.append(f'if [ -z "${{{vn}}}" ]; then')
                        exec_lines.append(f'    {vn}=$({detect_cmd})')
                        exec_lines.append("fi")
                    exec_lines.append("")

            for i, s in enumerate(steps, 1):
                if s["description"]:
                    exec_lines.append(f"# Step {i}: {s['description']}")
                cmd = s["command"]
                for vn in all_vars:
                    cmd = cmd.replace("{" + vn + "}", f'"${{{vn}}}"')
                exec_lines.append(cmd)
                exec_lines.append("")
            exec_code = "\n".join(exec_lines)

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(skill_body, encoding="utf-8")
            exec_path = skill_dir / f"exec.{exec_ext}"
            exec_path.write_text(exec_code, encoding="utf-8")
            exec_path.chmod(0o755)
            upsert_skill(self._config.memory_file, slug, summary)

            self._write_chat(Text(""))
            skill_path = self._config.skills_dir / slug
            self._write_chat(Panel(
                f"  Name:    {name}\n"
                f"  Summary: {summary}\n"
                f"  Steps:   {len(steps)}\n"
                f"  Type:    {exec_type}\n"
                f"  Path:    {skill_path}\n",
                title="✅ Skill Created!",
                border_style="green",
            ))
            self._write_chat(Text(f"  Files:", style="bold"))
            self._write_chat(Text(f"    📄 {skill_path}/SKILL.md", style="dim"))
            self._write_chat(Text(f"    ⚡ {skill_path}/exec.{exec_ext}", style="dim"))
            self._write_chat(Text(""))
            self._write_chat(Text("  Edit the exec file to add conditionals, loops, or custom logic.", style="dim"))
            self._write_chat(Text(f"  $EDITOR {skill_path}/exec.{exec_ext}", style="dim"))
            self._write_chat(Text("  Use /skills to see it in the list.", style="dim"))
        except Exception as e:
            self._write_chat(Text(f"  Error creating skill: {e}", style="red"))

        self._wizard_state = _WIZARD_IDLE
        self._wizard_data = {}

    async def _cmd_save(self, args: list[str]) -> None:
        title = " ".join(args).strip() or "manual-session"
        history = "\n".join(f"- {p}" for p in self._prompt_history) or "- none"
        body = "\n".join([
            "# Delux IDE Notes",
            "",
            f"- CWD: {self._cwd}",
            "",
            "## Prompt History",
            "",
            history,
            "",
        ])
        try:
            path = save_session_markdown(self._config.sessions_dir, title, body)
            self._write_chat(Text(f"  Sesión guardada: {path.name}", style="green"))
        except Exception as e:
            self._write_chat(Text(f"  Error: {e}", style="red"))

    async def _cmd_lang(self, args: list[str]) -> None:
        if not args:
            self._write_chat(Text(f"  Idioma actual: {self._lang}", style="cyan"))
            return
        lang = args[0].lower()
        if lang in ("en", "es"):
            self._lang = lang
            self._i18n = I18n(lang)
            self._write_chat(Text(f"  Idioma cambiado a {lang}", style="green"))
        else:
            self._write_chat(Text(f"  Idiomas soportados: en, es", style="yellow"))

    async def _cmd_model(self, args: list[str]) -> None:
        if not args:
            table = Table(box=box.SIMPLE, border_style="dim", padding=(0, 1))
            table.add_column("#", style="bold cyan")
            table.add_column("Modelo", style="white")
            table.add_column("Provider", style="dim")
            for i, m in enumerate(self._config.models):
                mark = " ← activo" if i == self._active_model_idx else ""
                table.add_row(str(i), f"{m.name}{mark}", m.provider or "—")
            self._write_chat(Text("\n  Modelos disponibles:\n", style="bold"), table)
            self._write_chat(Text("  Usa /model <N> para cambiar de modelo.", style="dim"))
            return

        if args[0] == "add" and len(args) >= 3:
            try:
                from ..config import ModelEntry
                name = args[1]
                provider = args[2]
                api_base = args[3] if len(args) > 3 else ""
                new_model = ModelEntry(name=name, provider=provider, api_base=api_base)
                self._config.models.append(new_model)
                self._config.model = name
                load_config(self._config.root)
                self._write_chat(Text(f"  Modelo añadido: {name} ({provider})", style="green"))
            except Exception as e:
                self._write_chat(Text(f"  Error: {e}", style="red"))
            return

        try:
            idx = int(args[0])
            if 0 <= idx < len(self._config.models):
                self._active_model_idx = idx
                m = self._config.models[idx]
                self._model_name = m.name
                self._provider = (m.provider or self._config.provider or "").upper()
                self.query_one("#sidebar-model", Label).update(self._model_name)
                self.query_one("#sidebar-provider", Label).update(self._provider)
                self._write_chat(Text(f"  Modelo activo: {m.name}", style="green"))
            else:
                self._write_chat(Text(f"  Índice inválido: {idx}", style="red"))
        except ValueError:
            self._write_chat(Text(f"  Usa: /model <N> | /model add <name> <provider> [api_base]", style="yellow"))

    async def _cmd_vm(self, args: list[str]) -> None:
        if not args:
            if self._validator_model_idx is not None:
                self._write_chat(Text(f"  Modelo de validación: {self._config.models[self._validator_model_idx].name}", style="cyan"))
            else:
                self._write_chat(Text("  Modelo de validación: mismo que el activo", style="dim"))
            return
        if args[0] == "off":
            self._validator_model_idx = None
            self._write_chat(Text("  Validación con el modelo activo.", style="dim"))
            return
        try:
            idx = int(args[0])
            if 0 <= idx < len(self._config.models):
                self._validator_model_idx = idx
                self._write_chat(Text(f"  Modelo de validación: {self._config.models[idx].name}", style="green"))
            else:
                self._write_chat(Text(f"  Índice inválido: {idx}", style="red"))
        except ValueError:
            self._write_chat(Text(f"  Usa: /vm <N> | /vm off", style="yellow"))

    async def _cmd_sidebar(self, args: list[str]) -> None:
        sidebar = self.query_one("#sidebar", Vertical)
        grid = self.query_one("#app-grid", Container)
        if not args:
            visible = sidebar.styles.display != "none"
            self._write_chat(Text(f"  Sidebar: {'visible' if visible else 'oculto'}", style="dim"))
            return
        if args[0] in ("on", "show"):
            sidebar.styles.display = "block"
            grid.styles.grid_columns = "1fr 30"
        elif args[0] in ("off", "hide"):
            sidebar.styles.display = "none"
            grid.styles.grid_columns = "1fr 0"
        else:
            if sidebar.styles.display == "none":
                sidebar.styles.display = "block"
                grid.styles.grid_columns = "1fr 30"
            else:
                sidebar.styles.display = "none"
                grid.styles.grid_columns = "1fr 0"

    async def _cmd_ctx(self, args: list[str]) -> None:
        try:
            from ..training.contextualizer import load_ctx_config
            ctx = load_ctx_config(self._config.root)
            self._write_chat(
                Text("\n  Contextualizador:\n", style="bold"),
                Panel(
                    f"  Estado: {'ON' if ctx.enabled else 'OFF'}\n"
                    f"  Modelo: {ctx.model or '—'}\n"
                    f"  API Base: {ctx.api_base or '—'}\n"
                    f"  Max tokens: {ctx.max_tokens or '—'}",
                    border_style="dim",
                ),
            )
        except Exception as e:
            self._write_chat(Text(f"  Error: {e}", style="red"))

    async def _cmd_index(self, args: list[str]) -> None:
        self._write_chat(
            Text("  /index no está disponible en la interfaz TUI todavía.", style="yellow"),
            Text("  Usa la CLI clásica: `delux index build`", style="dim"),
        )

    async def _cmd_mcp(self, args: list[str]) -> None:
        self._write_chat(
            Text("  /mcp no está disponible en la interfaz TUI todavía.", style="yellow"),
            Text("  Usa la CLI clásica: `delux mcp`", style="dim"),
        )

    async def _cmd_template(self, args: list[str]) -> None:
        from ..templates import list_templates, get_model_template, set_template

        if not args:
            templates = list_templates(self._config.root)
            if not templates:
                self._write_chat(Text("  No hay templates configurados.", style="dim"))
                return
            table = Table(box=box.SIMPLE, border_style="dim")
            table.add_column("Modelo", style="bold cyan")
            table.add_column("Estrategia", style="white")
            table.add_column("System Suffix", style="dim")
            for name, t in templates:
                suffix = t.system_suffix[:60] + "..." if len(t.system_suffix) > 60 else t.system_suffix or "\u2014"
                table.add_row(name, t.preferred_strategy, suffix)
            self._write_chat(Text("\n  Templates:\n", style="bold"), table)
            return

        model = args[0]

        if len(args) == 1:
            t = get_model_template(model, self._config.root)
            suffix = t.system_suffix if t.system_suffix else "\u2014"
            panel = Panel(
                f"  Modelo: {t.name}\n"
                f"  Estrategia: {t.preferred_strategy}\n"
                f"  System Suffix: {suffix}",
                title="Template",
                border_style="dim",
            )
            self._write_chat(Text(f"\n  Template para {model}:\n", style="bold"), panel)
            self._write_chat(Text(
                "  /template <model> strategy <direct_json|markdown_json|regex_json|auto>\n"
                '  /template <model> suffix "<text>"',
                style="dim",
            ))
            return

        if len(args) >= 3 and args[1] == "strategy":
            strategy = args[2]
            set_template(model, strategy=strategy, root=self._config.root)
            self._write_chat(Text(f"  Template {model}: estrategia = {strategy}", style="green"))
            return

        if len(args) >= 3 and args[1] == "suffix":
            suffix = " ".join(args[2:])
            set_template(model, suffix=suffix, root=self._config.root)
            if suffix:
                self._write_chat(Text(f"  Template {model}: suffix set.", style="green"))
            else:
                self._write_chat(Text(f"  Template {model}: suffix cleared.", style="green"))
            return

        self._write_chat(Text("  Usa: /template [model] | /template <model> strategy <s> | /template <model> suffix \"<text>\"", style="yellow"))

    async def _cmd_finetune(self, args: list[str]) -> None:
        try:
            from ..training.contextualizer import Contextualizer
            Contextualizer.print_finetune_recommendations()
            self._write_chat(Text("  Recomendaciones mostradas en la terminal.", style="dim"))
        except Exception as e:
            self._write_chat(Text(f"  Error: {e}", style="red"))

    async def _cmd_train(self, args: list[str]) -> None:
        examples_path = self._config.root / "examples" / "feedback.jsonl"
        if not args:
            total = 0
            if examples_path.exists():
                with open(examples_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            total += 1
            self._write_chat(Text(f"  Ejemplos de feedback: {total}", style="bold"))
            self._write_chat(Text("  /train stats | list | clear | export [path]", style="dim"))
            return

        cmd = args[0]

        if cmd == "stats":
            if not examples_path.exists():
                self._write_chat(Text("  No hay ejemplos de feedback.", style="dim"))
                return
            total = 0
            cats = {}
            with open(examples_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    try:
                        data = json.loads(line)
                        model = data.get("model", "?")
                        cats[model] = cats.get(model, 0) + 1
                    except json.JSONDecodeError:
                        pass
            size = examples_path.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
            dash = "\u2014"
            models_str = ', '.join(f'{m}: {c}' for m, c in sorted(cats.items(), key=lambda x: -x[1])) if cats else dash
            panel = Panel(
                f"  Total: {total}\n"
                f"  Tamaño: {size_str}\n"
                f"  Por modelo: {models_str}",
                title="Feedback Stats",
                border_style="dim",
            )
            self._write_chat(Text("\n  Ejemplos de feedback:\n", style="bold"), panel)

        elif cmd == "list":
            if not examples_path.exists():
                self._write_chat(Text("  No hay ejemplos de feedback.", style="dim"))
                return
            entries = []
            with open(examples_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            entries = entries[-10:]
            table = Table(box=box.SIMPLE, border_style="dim")
            table.add_column("Prompt", style="bold cyan")
            table.add_column("Modelo", style="dim")
            table.add_column("Fecha", style="dim")
            for e in reversed(entries):
                prompt = e.get("prompt", "")[:60]
                model = e.get("model", "?")
                ts = e.get("timestamp", "")[:10]
                table.add_row(prompt, model, ts)
            self._write_chat(Text("\n  Últimos ejemplos:\n", style="bold"), table)

        elif cmd == "clear":
            if examples_path.exists():
                examples_path.unlink()
            self._write_chat(Text("  Ejemplos de feedback eliminados.", style="green"))

        elif cmd == "export":
            if not examples_path.exists():
                self._write_chat(Text("  No hay ejemplos para exportar.", style="dim"))
                return
            export_path = Path(args[1]) if len(args) > 1 else self._config.root / "examples" / "feedback_export.jsonl"
            import shutil
            shutil.copy2(examples_path, export_path)
            total = 0
            with open(examples_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        total += 1
            self._write_chat(Text(f"  Exportados {total} ejemplos a {export_path}", style="green"))

        else:
            self._write_chat(Text("  Usa: /train stats | list | clear | export [path]", style="yellow"))

    # ── /compact ──

    async def _cmd_compact(self, args: list[str]) -> None:
        if not self._conversation:
            self._write_chat(Text("  No hay conversación para comprimir.", style="dim"))
            return
        active_idx = self._active_model_idx
        model_cfg = self._config.models[active_idx] if active_idx < len(self._config.models) else None
        current_model = model_cfg.name if model_cfg else (self._config.model or "deepseek")
        self._write_chat(Text("  Choose a model for summarization:", style="bold cyan"))
        self._write_chat(Text(f"  [1] {current_model} (current)", style="white"))
        self._write_chat(Text("  [2] Other model", style="white"))
        self._awaiting_input = "compact_model"

    async def _handle_awaited_input(self, text: str) -> None:
        if self._awaiting_input == "compact_model":
            choice = text.strip()
            if not choice or choice == "1":
                self._write_chat(Text("  Compacting conversation...", style="dim"))
                self._run_compact(model_name=None)
            elif choice == "2":
                self._awaiting_input = "compact_other_model"
                self._write_chat(Text("  Enter model name or alias:", style="cyan"))
            else:
                self._write_chat(Text("  Choose 1 or 2:", style="yellow"))
            return

        if self._awaiting_input == "compact_other_model":
            model_name = text.strip()
            if model_name:
                self._write_chat(Text(f"  Compacting with {model_name}...", style="dim"))
                self._run_compact(model_name=model_name)
            else:
                self._write_chat(Text("  Model name cannot be empty:", style="yellow"))
            return

    @work(thread=True)
    def _run_compact(self, model_name: str | None = None) -> None:
        self._awaiting_input = None

        lines = []
        for i, turn in enumerate(self._conversation, 1):
            lines.append(f"Turn {i}:")
            lines.append(f"  User: {turn['prompt']}")
            lines.append(f"  Assistant: {turn['answer'][:600]}")
            lines.append("")
        full_text = "\n".join(lines)

        summary_prompt = (
            "Summarize the following conversation between a user and Delux (an AI assistant). "
            "Extract: main goals, what was accomplished, key decisions, current state, "
            "files modified, skills created. "
            "Be concise but informative. This summary will be used as context.\n\n"
            + full_text
        )

        try:
            from ..llm import chat_completion

            use_model = model_name or self._config.model
            api_base = self._config.api_base
            api_key = self._config.api_key
            api_ep = self._config.api_endpoint

            response = chat_completion(api_base, api_key, use_model,
                [{"role": "user", "content": summary_prompt}],
                api_ep, timeout=30)

            summary = response.text.strip()
        except Exception as e:
            last_turns = self._conversation[-3:]
            lines = []
            for turn in last_turns:
                lines.append(f"User: {turn['prompt'][:200]}")
                lines.append(f"Assistant: {turn['answer'][:200]}")
            summary = "Recent conversation:\n" + "\n".join(lines)
            self.call_from_thread(self._write_chat, Text(f"  LLM error, using last 3 turns: {e}", style="dim"))

        self._session_summary = summary
        self._conversation = []
        self._prompt_history = []

        self.call_from_thread(self._on_compact_done, summary)

    def _on_compact_done(self, summary: str) -> None:
        n_lines = summary.count("\n") + 1
        preview = summary[:600]
        self._write_chat(Text("  Conversation compacted.", style="bold green"))
        self._write_chat(Panel(preview, title=f"Session Summary ({n_lines} lines)", border_style="cyan"))
        self._write_chat(Text("  The summary will be injected as context for future turns.", style="dim"))
        self._set_status("Listo")

    # ── Feedback (text + keyboard) ──

    def _show_feedback_prompt(self) -> None:
        self._feedback_showing = True
        self._write_chat(Text("  [\u2191] Save example  [\u2193] Discard  (Ctrl+\u2191 / Ctrl+\u2193)", style="dim"))

    def _hide_feedback_prompt(self) -> None:
        self._feedback_showing = False

    def action_feedback_up(self) -> None:
        if self._feedback_showing:
            self._save_feedback_example()
        self._hide_feedback_prompt()

    def action_feedback_down(self) -> None:
        self._hide_feedback_prompt()

    def _save_feedback_example(self) -> None:
        if not self._last_prompt:
            return
        examples_dir = self._config.root / "examples"
        examples_dir.mkdir(parents=True, exist_ok=True)
        examples_path = examples_dir / "feedback.jsonl"
        entry = {
            "prompt": self._last_prompt,
            "response": self._last_answer,
            "model": self._model_name,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            with open(examples_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._write_chat(Text("  [\u2191] Saved as feedback example.", style="green"))
        except Exception as e:
            self._write_chat(Text(f"  Error saving example: {e}", style="red"))

    @work(exclusive=True, thread=True)
    def _stream_response(self, prompt: str) -> None:
        start = time.monotonic()
        self._buffer = ""
        self._action_lines = 0
        self._answer_written = False
        self._start_time = start

        if self._plan_mode:
            self.call_from_thread(self._write_chat, Text("  📋 Creating plan...", style="bold yellow"))

        from ..agent import prepare_agent, build_session_context
        agent = prepare_agent(
            config=self._config,
            cwd=self._cwd,
            event_handler=lambda ev, pl: self.call_from_thread(self._on_agent_event, ev, pl),
            prompt=prompt,
            active_model_idx=self._active_model_idx,
            validator_model_idx=self._validator_model_idx,
            plan_mode=self._plan_mode,
            ephemeral=self._ephemeral,
            max_steps=self._max_steps,
            run_counter=self._answer_count + 1,
            lang=self._lang,
        )
        # If plan was created, report it
        if agent.plan:
            self.call_from_thread(self._write_chat, Text(f"  📋 Plan: {agent.plan.summary} ({len(agent.plan.steps)} steps)", style="bold green"))
        elif self._plan_mode:
            self.call_from_thread(self._write_chat, Text("  ⚠ Could not create plan, executing directly.", style="dim"))

        self.call_from_thread(self._write_chat, Text("  \U0001f914 ", style="yellow").append("Pensando...", style="dim"))

        session_ctx = build_session_context(
            session_summary=self._session_summary,
            history=self._conversation,
        )

        try:
            result = agent.run_with_result(prompt, verbose=False, session_context=session_ctx)
            self.call_from_thread(self._on_agent_done, result, time.monotonic() - start)
        except Exception as e:
            self.call_from_thread(self._on_agent_error, str(e))

    def _on_agent_event(self, event: str, payload: dict) -> None:
        if event == "token":
            content = payload.get("content", "")
            if content:
                self._buffer += content

        elif event == "action_started":
            action = payload.get("action", {})
            kind = action.get("action", "unknown")
            if kind == "shell":
                cmd = str(action.get("command", ""))[:200]
                self._write_chat(Text(f"  \u2192 shell  {cmd}", style="cyan"))
                self._action_lines += 1
            elif kind in ("write_file", "append_file"):
                path = str(action.get("path", ""))
                content = str(action.get("content", ""))
                lines_n = content.count("\n") + 1 if content else 0
                self._write_chat(Text(f"  \u2192 {kind}  {path}  ({lines_n} lines)", style="cyan"))
                self._action_lines += 1
                # Show content preview (first 10 lines)
                if content:
                    preview_lines = content.split("\n")[:10]
                    for l in preview_lines:
                        self._write_chat(Text(f"  + {l}", style="green"))
                    if content.count("\n") >= 10:
                        self._write_chat(Text(f"  ... ({lines_n - 10} more lines)", style="dim"))
            elif kind in ("edit_file", "patch_file"):
                path = str(action.get("path", ""))
                old_str = str(action.get("old_str", ""))
                new_str = str(action.get("new_str", ""))
                self._write_chat(Text(f"  \u2192 {kind}  {path}", style="yellow"))
                self._action_lines += 1
                if old_str or new_str:
                    for prefix, line in _diff_preview(old_str, new_str):
                        if prefix == "+":
                            self._write_chat(Text(f"  + {line}", style="green"))
                        elif prefix == "-":
                            self._write_chat(Text(f"  - {line}", style="red"))
                        elif prefix == "@":
                            self._write_chat(Text(f"  {line}", style="dim cyan"))
                        elif prefix == "...":
                            self._write_chat(Text(f"  {line}", style="dim"))
                        elif prefix == " ":
                            self._write_chat(Text(f"    {line}", style="dim"))
                        self._action_lines += 1
            elif kind in ("read_file", "view_file"):
                self._write_chat(Text(f"  \u2192 {kind}  {action.get('path', '')}", style="cyan"))
                self._action_lines += 1
            elif kind == "search_files":
                self._write_chat(Text(f"  \u2192 search  '{action.get('query', '')[:100]}'", style="magenta"))
                self._action_lines += 1
            elif kind == "run_skill":
                s = str(action.get("skill", ""))
                a = str(action.get("args", ""))[:80]
                self._write_chat(Text(f"  \u2192 skill  {s}  {a}", style="yellow"))
                self._action_lines += 1
            elif kind == "final":
                pass
            else:
                self._write_chat(Text(f"  \u2192 {kind}", style="dim"))
                self._action_lines += 1

        elif event == "shell_output":
            chunk = str(payload.get("chunk", ""))
            if chunk:
                for line in chunk.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                    if line:
                        self._write_chat(Text(f"    {line}", style="dim"))

        elif event == "action_finished":
            result = str(payload.get("result", "")).strip()
            if result.startswith("SUCCESS:"):
                detail = result[8:]
                if detail:
                    self._write_chat(Text(f"  \u2713  {detail[:200]}", style="green"))
            elif result.startswith("ERROR:"):
                detail = result[6:]
                self._write_chat(Text(f"  \u2717  {detail[:200]}", style="red"))

        elif event == "final_answer":
            answer = str(payload.get("answer", ""))
            if answer:
                self._buffer = answer

        elif event == "cache_warming":
            part = payload.get("part", 0)
            total = payload.get("total", 0)
            self._write_chat(Text(f"  🧠 KV cache: {part}/{total}", style="dim"))

        elif event == "cache_warmed":
            chunks = payload.get("chunks", 0)
            error = payload.get("error", "")
            if error:
                self._write_chat(Text(f"  ⚠ KV cache warmup: {error}", style="dim"))
            elif chunks:
                self._write_chat(Text(f"  ✅ KV cache listo", style="green"))

        elif event == "plan_step_active":
            step_id = payload.get("step_id", "")
            step_desc = payload.get("step_desc", "")
            progress = payload.get("progress", "")
            self._write_chat(Text(f"  📋 [{progress}] Step {step_id}: {step_desc}", style="bold magenta"))

        elif event == "plan_step_matched":
            step_desc = payload.get("step_desc", "")
            self._write_chat(Text(f"  → Step: {step_desc}", style="dim"))

        elif event == "plan_step_skipped":
            step_id = payload.get("step_id", "")
            reason = payload.get("reason", "")
            progress = payload.get("progress", "")
            self._write_chat(Text(f"  ⏭ Step {step_id} skipped ({reason}) [{progress}]", style="yellow"))

        elif event == "plan_step_status":
            step_id = payload.get("step_id", "")
            ok = payload.get("ok", False)
            progress = payload.get("progress", "")
            icon = "✅" if ok else "❌"
            self._write_chat(Text(f"  {icon} Step {step_id} [{progress}]", style="green" if ok else "red"))

        elif event == "plan_completed":
            summary = payload.get("summary", "")
            self._write_chat(Text(f"  ✅ Plan completed!", style="bold green"))
            if summary:
                self._write_chat(Text(f"  {summary}", style="dim"))

        elif event == "plan_final_blocked":
            self._write_chat(Text(f"  ⚠ Final blocked (plan not complete, continuing)", style="yellow"))

        elif event == "plan_max_steps_reached":
            summary = payload.get("summary", "")
            self._write_chat(Text(f"  ⚠ Max steps reached with plan incomplete", style="red"))
            if summary:
                self._write_chat(Text(f"  {summary}", style="dim"))

        elif event == "contextualizer_starting":
            self._write_chat(Text("  Optimizando contexto...", style="dim"))

        elif event == "contextualizer_finished":
            changes = payload.get("changes", "")
            if changes:
                self._write_chat(Text(f"  Contexto optimizado: {changes}", style="dim"))

    def _on_agent_done(self, result, elapsed: float) -> None:
        if self._buffer and not self._answer_written:
            self._write_chat(Markdown(self._buffer))
            self._write_chat("")
            self._answer_written = True

        answer_text = getattr(result, "answer", self._buffer)
        if answer_text and not self._answer_written:
            self._write_chat(Markdown(answer_text))
            self._write_chat("")
            self._answer_written = True

        # Store for feedback and compact
        self._last_prompt = self._prompt_history[-1] if self._prompt_history else ""
        self._last_answer = answer_text or self._buffer
        self._conversation.append({
            "prompt": self._last_prompt,
            "answer": self._last_answer,
        })
        self._show_feedback_prompt()

        self._answer_count += 1
        self._total_tokens += len(self._buffer)
        try:
            self.query_one("#sidebar-tokens", Label).update(str(self._total_tokens))
            self.query_one("#sidebar-steps", Label).update(str(self._answer_count))
            self.query_one("#sidebar-time", Label).update(f"{elapsed:.1f}s")
        except Exception:
            pass

        self._streaming = False
        self._set_status("Listo")
        inp = self.query_one("#prompt-input", Input)
        inp.disabled = False
        inp.focus()

    def _on_agent_error(self, error: str) -> None:
        self._write_chat(Text(f"  Error: {error}", style="red"))
        self._streaming = False
        self._set_status("Error")
        inp = self.query_one("#prompt-input", Input)
        inp.disabled = False
        inp.focus()

    def action_cancel_stream(self) -> None:
        """Cancela la ejecución actual si está en progreso."""
        if self._streaming:
            self._streaming = False
            self._set_status("Cancelado")
            try:
                inp = self.query_one("#prompt-input", Input)
                inp.disabled = False
                inp.focus()
            except Exception:
                pass
            self._write_chat(Text("  ⛔ Cancelado por el usuario", style="yellow"))

    def action_clear(self) -> None:
        self._show_splash()
