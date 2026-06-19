from __future__ import annotations

import asyncio
import shlex
import time
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

from ..agent import Agent
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
    ("/save", "[título]", "Guarda la sesión actual"),
    ("/lang", "<en|es>", "Cambia el idioma"),
    ("/model", "[idx|add ...]", "Lista/ cambia/ añade modelos"),
    ("/vm", "[idx|off]", "Selecciona modelo de validación"),
    ("/sidebar", "[on|off]", "Muestra/oculta el panel lateral"),
    ("/ctx, /contextualize", "", "Estado del contextualizador"),
    ("/index", "[build|rebuild]", "Gestiona el índice del proyecto"),
    ("/m, /mcp", "[add|rm|toggle|tools]", "Gestiona servidores MCP"),
    ("/template", "[model]", "Muestra/configura plantilla de modelo"),
    ("/train, /tr", "[on|off|stats]", "Modo entrenamiento"),
]


class DeluxTUI(App):
    CSS_PATH = "delux.tcss"

    BINDINGS = [
        ("ctrl+q", "quit", "Salir"),
        ("ctrl+l", "clear", "Limpiar"),
        ("ctrl+space", "toggle_plan", "Plan/Build"),
        ("ctrl+c", "cancel_stream", "Cancelar"),
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
        skills = load_skills(c.skills_dir)
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
        skills = load_skills(self._config.skills_dir)
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
            self._loaded_session_context = None
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
        if not args:
            visible = sidebar.styles.display != "none"
            self._write_chat(Text(f"  Sidebar: {'visible' if visible else 'oculto'}", style="dim"))
            return
        if args[0] in ("on", "show"):
            sidebar.styles.display = "block"
        elif args[0] in ("off", "hide"):
            sidebar.styles.display = "none"
        else:
            sidebar.styles.display = "block" if sidebar.styles.display == "none" else "none"

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
        self._write_chat(
            Text("  /template no está disponible en la interfaz TUI todavía.", style="yellow"),
        )

    async def _cmd_finetune(self, args: list[str]) -> None:
        try:
            from ..training.contextualizer import Contextualizer
            Contextualizer.print_finetune_recommendations()
            self._write_chat(Text("  Recomendaciones mostradas en la terminal.", style="dim"))
        except Exception as e:
            self._write_chat(Text(f"  Error: {e}", style="red"))

    async def _cmd_train(self, args: list[str]) -> None:
        self._write_chat(
            Text("  /train no está disponible en la interfaz TUI todavía.", style="yellow"),
        )

    @work(exclusive=True, thread=True)
    def _stream_response(self, prompt: str) -> None:
        start = time.monotonic()
        self._buffer = ""
        self._action_lines = 0
        self._answer_written = False
        self._start_time = start

        active_idx = self._active_model_idx
        model_cfg = self._config.models[active_idx] if active_idx < len(self._config.models) else None

        from dataclasses import replace
        model_cfg = self._config.models[active_idx] if active_idx < len(self._config.models) else None

        run_config = self._config
        if model_cfg:
            run_config = replace(
                self._config,
                model=model_cfg.name,
                provider=model_cfg.provider or self._config.provider,
                api_base=model_cfg.api_base or self._config.api_base,
                api_key=model_cfg.api_key or self._config.api_key,
            )

        # ── Plan mode: create plan before execution ──
        plan_obj = None
        if self._plan_mode:
            self.call_from_thread(self._write_chat, Text("  📋 Creating plan...", style="bold yellow"))
            plan_obj = self._create_plan(prompt, run_config)
            if plan_obj is None:
                self.call_from_thread(self._write_chat, Text("  ⚠ Could not create plan, executing directly.", style="dim"))

        agent = Agent(
            config=run_config,
            cwd=self._cwd,
            event_handler=lambda ev, pl: self.call_from_thread(self._on_agent_event, ev, pl),
            max_steps=self._max_steps,
            ephemeral=self._ephemeral,
            plan=plan_obj,
            run_counter=self._answer_count + 1,
        )

        self.call_from_thread(self._write_chat, Text("  \U0001f914 ", style="yellow").append("Pensando...", style="dim"))

        try:
            result = agent.run_with_result(prompt, verbose=False)
            self.call_from_thread(self._on_agent_done, result, time.monotonic() - start)
        except Exception as e:
            self.call_from_thread(self._on_agent_error, str(e))

    def _create_plan(self, prompt: str, run_config) -> object | None:
        """Call the planner LLM to create a step-by-step plan."""
        from ..plan_executor import build_planner_prompt, AgentPlan, PlanStepStatus
        from ..llm import chat_completion

        plan_model = self._config.effective_plan_model
        plan_base = self._config.effective_plan_api_base
        plan_key = self._config.effective_plan_api_key
        plan_ep = self._config.effective_plan_api_endpoint

        planner_prompt = build_planner_prompt(
            prompt=prompt,
            lang=self._lang,
        )

        try:
            response = chat_completion(
                plan_base, plan_key, plan_model,
                [{"role": "user", "content": planner_prompt}],
                plan_ep,
                timeout=60,
            )
        except Exception as e:
            self.call_from_thread(self._write_chat, Text(f"  ⚠ Planner error: {e}", style="red"))
            return None

        import json
        try:
            data = json.loads(response.text.strip())
        except json.JSONDecodeError:
            self.call_from_thread(self._write_chat, Text("  ⚠ Planner response was not valid JSON.", style="red"))
            return None

        if "questions" in data:
            questions = data.get("questions", [])
            for q in questions:
                text = q.get("text", "")
                opts = q.get("options", [])
                line = f"  ❓ {text}"
                if opts:
                    line += f"  ({', '.join(opts)})"
                self.call_from_thread(self._write_chat, Text(line, style="yellow"))
            self.call_from_thread(self._write_chat, Text("  ⚠ Plan needs clarification, executing directly.", style="dim"))
            return None

        summary = data.get("summary", "")
        raw_steps = data.get("steps", [])
        if not raw_steps:
            self.call_from_thread(self._write_chat, Text("  ⚠ Planner returned no steps.", style="red"))
            return None

        step_list = []
        for i, s in enumerate(raw_steps, 1):
            desc = s.get("description", f"Step {i}")
            detail = s.get("detail", "")
            step_list.append(PlanStepStatus(id=i, description=desc, detail=detail))

        plan = AgentPlan(prompt=prompt, steps=step_list, summary=summary)
        self.call_from_thread(self._write_chat, Text(f"  📋 Plan: {summary} ({len(step_list)} steps)", style="bold green"))
        return plan

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
            elif kind in ("edit_file", "patch_file"):
                path = str(action.get("path", ""))
                self._write_chat(Text(f"  \u2192 {kind}  {path}", style="yellow"))
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
