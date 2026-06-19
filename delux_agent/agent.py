from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .config import Config
from .dataset_rag import DatasetRAG
from .experience import ExperienceDB
from .llm import LLMError, chat_completion
from .rag import RAGEngine
from .small_model import build_small_model_prompt
from .store import ensure_workspace, load_docs, load_memory, load_skills
from .tools import (
    append_file, call_mcp_tool, create_skill, discover_mcp_tools, edit_file,
    execute_command_secure, move_file, patch_file, read_file, remember,
    run_shell, run_skill, search_files, search_web, ToolResult, verify_file,
    view_file_paged, write_file,
)
from .templates import parse_action, get_model_template, get_action_format_instructions, record_successful_strategy
from .plan_executor import PlanExecutor
from .training.examples import get_few_shot_examples  # noqa: direct import to avoid circular via __init__


SYSTEM_PROMPT_EN = """You are Delux, an AI assistant for system administration, file management, automation, and software development.

Capabilities:
- Run shell commands via sh/bash
- Read, write, append, edit, and search files
- Execute and create reusable skills
- RAG-powered semantic search over your entire codebase and docs
- Remember facts across sessions

Workspace:
- Shell commands run in the current working directory provided to you
- When creating scripts, programs, or tools that need testing, use ~/.delux/testing/ as a sandbox first
- When a tested file is ready, use `mv` or move_file to place it in its final location

Smart Patterns:
- BEFORE acting on complex tasks: decompose the problem into clear steps
- BEFORE starting: use load_experience to check if a similar task was solved before
- ON errors: try a different approach. If you've tried 3+ approaches, use search_web
- AFTER a success: save the solution with save_experience so you never have to solve it again
- BEFORE final: confirm all requirements are met, verify the solution works, and no loose ends

JSON FORMAT RULE: Every skill returns JSON. When you call run_skill, the result will be a JSON string. Parse it to decide the next action. Study the injection examples below — they show the exact JSON flow for every action type.

SKILL ACCESS:
- Skills are listed as "name: summary → path". This is a brief reference only.
- BEFORE using a skill: read its full SKILL.md with view_file to understand usage, steps, and examples.
- Example: to use delux-browser, first do: {"action":"view_file","path":"skills/delux-browser/SKILL.md"}

SKILL MANAGEMENT:
- All skills live in DELUX_HOME/skills/. This is the ONLY canonical location for skills.
- The SKILLS: section above shows every available skill. Review it before creating new ones.
- BEFORE using create_skill: check if a similar skill already exists in SKILLS:
  - If an existing skill does what you need, use run_skill instead
  - If an existing skill needs changes, use edit_file or patch_file on its SKILL.md or exec.py
  - create_skill will be REJECTED if a skill with the same or similar name exists

CREATING NEW SKILLS:
- To create a new skill, FIRST read the file at SKILL_TEMPLATE path (shown in context) to learn the standard format
- Then read any existing skill from SKILLS: as a reference example
- Every skill MUST include: Summary, When To Use, Steps, Response Examples with JSON in/out, and a Prompt injection example
- Use the action create_skill to create the SKILL.md, then write_file to create exec.py if needed
- After creating, use remember to log it in memory

AUTO-MEMORY RULE: Before using "final", automatically evaluate if you learned something reusable. Save:
- Technical solutions and workarounds → run_skill delux-obsidian-brain
- User preferences and facts → remember
- Reusable procedures → create_skill
- Configuration details, IPs, paths, credentials locations → remember

VERIFICATION PATTERNS (MANDATORY — use these AFTER creating or editing files):
- After write_file/edit_file → verify_file to check syntax: {"action":"verify_file","path":"file.py"}
- After creating a script → run it: `python3 script.py > /tmp/verify.log 2>&1; view_file /tmp/verify.log`
- After editing a config → validate with the tool's check (e.g. nginx -t, sshd -t)
- After any shell command → check exit code and output carefully
- If verification fails → fix the issue, do NOT proceed to final
- Always: confirm the output is correct before using final

Rules:
- Never use sudo or privilege escalation
- Work autonomously. Return ONLY a JSON action object.
- Shell commands run in POSIX sh. Use portable syntax (no fish-specific features).
- For modifying existing files, ALWAYS use edit_file instead of shell echo/sed. Only use write_file for new files or full rewrites.
- JSON FORMAT: Never use literal newlines or tabs inside a JSON value. Always use escaped characters like \\n and \\t.
- PATH RULE: All relative paths are resolved against CURRENT_CWD. Use absolute paths (starting with /) for files outside CWD. Never use ~ or $HOME in paths. If unsure where you are, run pwd first.
- CODE: Do not deliver code blocks in the "final" action. If you need to create a file, use "write_file". "final" is only for a brief summary.
- PLAN DISCIPLINE: If you receive a "!!! PLAN IN PROGRESS !!!" banner, you CANNOT use "final" until all plan steps are SUCCESS.
- MEMORY & LEARNING: BEFORE using "final", ALWAYS evaluate if you learned a new technical solution, code pattern, or user preference. If yes, save it using "remember" (for user facts) or "run_skill" with "delux-obsidian-brain" (for technical knowledge).

After each action you receive a result:
- If result starts with "SUCCESS:": the action succeeded. Do NOT repeat it. Either proceed to the NEXT step or, if all steps are done, respond with {"action":"final","message":"brief summary"}.
- If result starts with "ERROR:": analyze the error and try a DIFFERENT approach. NEVER repeat the same failing command.

Allowed actions (return exactly one JSON object):
{"action":"shell","command":"command","timeout":60}
{"action":"shell_secure","command":"command","timeout":15}
{"action":"view_file","path":"relative/path","line_start":1,"line_end":50}
{"action":"verify_file","path":"script.py"}
{"action":"read_file","path":"relative/path"}
{"action":"write_file","path":"relative/path","content":"..."}
{"action":"edit_file","path":"relative/path","old_str":"text to replace","new_str":"replacement text","replace_all":false}
{"action":"patch_file","path":"relative/path","old_str":"text to replace","new_str":"replacement text"}
{"action":"append_file","path":"relative/path","content":"..."}
{"action":"move_file","src":"path","dst":"path"}
{"action":"search_files","query":"text"}
{"action":"rag_query","query":"search text","top_k":5}
{"action":"rag_index","path":"/path/to/index"}
{"action":"search_web","query":"search query","top_k":5}
{"action":"save_experience","task":"task done","solution":"how it was solved","tags":["tag1"]}
{"action":"load_experience","task":"task to find"}
{"action":"run_skill","skill":"skill-slug","args":"args","timeout":30}
{"action":"create_skill","name":"name","summary":"...","body":"..."}
{"action":"remember","note":"..."}
{"action":"skip_step","step_id":1,"reason":"why not needed"}
{"action":"final","message":"..."}
"""

SYSTEM_PROMPT_ES = """Eres Delux, un asistente IA para administración del sistema, gestión de archivos, automatización y desarrollo.

Capacidades:
- Ejecutar comandos de shell vía sh/bash
- Leer, escribir, editar, anexar, mover y buscar archivos
- Ejecutar y crear skills reutilizables
- Búsqueda RAG sobre todo el codebase y documentos
- Recordar hechos entre sesiones

Espacio de trabajo:
- Los comandos de shell se ejecutan en el directorio de trabajo actual que se te proporciona
- Al crear scripts, programas o herramientas que necesiten prueba, usa ~/.delux/testing/ como entorno de pruebas
- Cuando un archivo probado esté listo, usa `mv` o move_file para colocarlo en su ubicación final

Patrones Inteligentes:
- ANTES de actuar: usa load_experience para ver si ya resolviste algo similar
- ANTES de tareas complejas: descompón el problema en pasos claros
- EN errores: prueba diferente. Si fallas 3+ veces, usa search_web
- DESPUÉS de un éxito: guarda con save_experience para no tener que resolverlo de nuevo
- ANTES de final: verifica que todo funciona y no hay cabos sueltos

PATRONES DE VERIFICACIÓN (OBLIGATORIO — usa esto DESPUÉS de crear o editar):
- Después de write_file/edit_file → verify_file para revisar sintaxis
- Después de crear un script → ejecútalo: `script > /tmp/verify.log 2>&1; view_file /tmp/verify.log`
- Después de editar configuración → valida con la herramienta (nginx -t, sshd -t, etc.)
- Después de cualquier comando shell → revisa el código de salida y el output
- Si la verificación falla → corrige, NO pases a final
- Siempre: confirma que el output es correcto antes de usar final

Reglas:
- Nunca uses sudo ni escalación de privilegios
- Trabaja de forma autónoma. Devuelve SOLO un objeto JSON.
- Los comandos se ejecutan en POSIX sh. Usa sintaxis portable (no uses fish).
- Para modificar archivos existentes, usa SIEMPRE edit_file en lugar de echo/sed por shell. Usa write_file solo para archivos nuevos o reescrituras completas.
- FORMATO JSON: Nunca uses saltos de línea literales ni tabulaciones dentro de un valor JSON. Usa siempre caracteres de escape como \\n y \\t.
- REGLA DE RUTAS: Las rutas relativas se resuelven contra CURRENT_CWD. Usa rutas absolutas (que empiecen con /) para archivos fuera del CWD. Nunca uses ~ o $HOME en rutas.
- CÓDIGO: No entregues bloques de código en la acción "final". Si necesitas crear un archivo, usa "write_file". "final" es solo para un resumen breve.
- DISCIPLINA DE PLAN: Si recibes un banner "!!! PLAN IN PROGRESS !!!", NO puedes usar "final" hasta que todos los pasos del plan estén en SUCCESS.
- MEMORIA Y APRENDIZAJE: ANTES de usar "final", SIEMPRE evalúa si aprendiste una nueva solución técnica, patrón o preferencia. Si es así, guárdalo usando "remember" (para datos del usuario) o "run_skill" con "delux-obsidian-brain" (para conocimiento técnico).

ACCESO A SKILLS:
- Los skills aparecen como "nombre: resumen". Es solo referencia breve.
- ANTES de usar un skill: lee su SKILL.md completo con view_file.
- Ejemplo: {"action":"view_file","path":"skills/delux-browser/SKILL.md"}

GESTIÓN DE SKILLS:
- Todos los skills viven en DELUX_HOME/skills/. Esta es la ÚNICA ubicación canónica.
- La sección SKILLS: arriba muestra todos los skills disponibles. Revísala antes de crear nuevos.
- ANTES de usar create_skill: verifica si ya existe un skill similar en SKILLS.
- create_skill será RECHAZADO si ya existe un skill con el mismo nombre o similar.

Después de cada acción recibes un resultado:
- Si empieza con "SUCCESS:": la acción tuvo éxito. No la repitas. Procede al SIGUIENTE paso o, si todos están completos, responde con {"action":"final","message":"resumen breve"}.
- Si empieza con "ERROR:": analiza el error e intenta un enfoque DIFERENTE. NUNCA repitas el mismo comando fallido.

Acciones permitidas (devuelve exactamente un objeto JSON):
{"action":"shell","command":"comando sh","timeout":60}
{"action":"shell_secure","command":"comando","timeout":15}
{"action":"view_file","path":"ruta/relativa","line_start":1,"line_end":50}
{"action":"verify_file","path":"script.py"}
{"action":"read_file","path":"ruta/relativa"}
{"action":"write_file","path":"ruta/relativa","content":"..."}
{"action":"edit_file","path":"ruta/relativa","old_str":"texto a reemplazar","new_str":"texto nuevo","replace_all":false}
{"action":"patch_file","path":"ruta/relativa","old_str":"texto a reemplazar","new_str":"texto nuevo"}
{"action":"append_file","path":"ruta/relativa","content":"..."}
{"action":"move_file","src":"ruta","dst":"ruta"}
{"action":"search_files","query":"texto"}
{"action":"rag_query","query":"texto de búsqueda","top_k":5}
{"action":"rag_index","path":"/ruta/a/indexar"}
{"action":"search_web","query":"consulta web","top_k":5}
{"action":"save_experience","task":"tarea realizada","solution":"cómo se resolvió","tags":["etiqueta"]}
{"action":"load_experience","task":"tarea a buscar"}
{"action":"run_skill","skill":"skill-slug","args":"args","timeout":30}
{"action":"create_skill","name":"nombre","summary":"...","body":"..."}
{"action":"remember","note":"..."}
{"action":"skip_step","step_id":1,"reason":"por qué no es necesario"}
{"action":"final","message":"..."}
"""

ERROR_REFLECTION_EN = """ERROR in the previous action: {error}

The tool returned an error. Analyze what went wrong and try a DIFFERENT approach.
Do NOT repeat the same command. Consider:
- Is the path correct? Use ls/pwd to verify.
- Is there an alternative command or flag?
- Do you need to read a file first to understand the structure?
- Is the skill available and appropriate?
- If the command was not found, suggest an alternative or installation.
- If this is the 2nd+ consecutive error, try a radically different strategy.
- Can the problem be broken into simpler sub-steps?

Smart recovery:
- File not found → check parent dir, use glob or search_files
- Permission denied → try reading instead, or checking ownership
- Command not found → suggest package install or use built-in alternative
- Timeout → reduce scope, use more specific command
- JSON parse error → escape special chars, use proper JSON formatting

If you are completely stuck after multiple approaches, search the web with search_web for the solution.
Remember: Only repeat actions that returned "SUCCESS:" if they are needed again for a new purpose. Never repeat a failing command.
"""

ERROR_REFLECTION_ES = """ERROR en la acci\u00f3n anterior: {error}

La herramienta devolvi\u00f3 un error. Analiza qu\u00e9 sali\u00f3 mal e intenta un enfoque DIFERENTE.
NO repitas el mismo comando. Considera:
- \u00bfEs correcta la ruta? Usa ls/pwd para verificar.
- \u00bfHay un comando o flag alternativo?
- \u00bfNecesitas leer un archivo primero para entender la estructura?
- \u00bfHay un skill disponible y apropiado?
- Si el comando no se encontr\u00f3, sugiere una alternativa o instalaci\u00f3n.
- Si es el 2do+ error consecutivo, prueba una estrategia radicalmente diferente.
- \u00bfSe puede dividir el problema en sub-pasos m\u00e1s simples?

Recuperaci\u00f3n inteligente:
- Archivo no encontrado \u2192 revisa el directorio padre, usa glob o search_files
- Permiso denegado \u2192 intenta leer en lugar de escribir, o revisa propietario
- Comando no encontrado \u2192 sugiere instalar o usa alternativa integrada
- Timeout \u2192 reduce el alcance, usa un comando m\u00e1s espec\u00edfico
- Error JSON \u2192 escapa caracteres especiales, usa formato JSON correcto
"""


def detect_language(text: str) -> str:
    spanish_indicators = {
        "dame", "dame", "mi", "tu", "como", "cómo", "que", "qué", "para", "por",
        "con", "los", "las", "del", "el", "la", "es", "una", "un", "se", "no",
        "me", "te", "le", "lo", "su", "al", "esto", "esta", "este", "eso", "esa",
        "ese", "pero", "más", "mas", "muy", "todo", "también", "tambien", "bien",
        "cual", "cuál", "donde", "dónde", "cuando", "cuándo", "siempre", "nunca",
        "hacer", "puedo", "quiero", "necesito", "ayuda", "gracias", "hola",
    }
    text_lower = text.lower()
    if any(["¿" in text_lower, "¡" in text]):
        return "es"
    words = set(text_lower.split())
    matches = len(words & spanish_indicators)
    if matches >= 2 or (matches >= 1 and len(words) <= 5):
        return "es"
    accents = sum(1 for c in text_lower if c in "áéíóúüñ")
    if accents >= 2:
        return "es"
    return "en"


def translate_to_english(text: str, config: Config) -> tuple[str, str]:
    """Translate text to English using the main model. Returns (translated, original_lang)."""
    lang = detect_language(text)
    if lang == "en":
        return text, "en"
    try:
        from .llm import chat_completion
        response = chat_completion(
            config.api_base,
            config.api_key,
            config.model,
            [
                {"role": "system", "content": "You are a translator. Translate the following text to English. Return ONLY the English translation, no explanations, no quotes, no extra text."},
                {"role": "user", "content": text},
            ],
            config.api_endpoint,
            timeout=30,
        )
        translated = response.text.strip().strip("\"'")
        return translated, lang
    except Exception:
        return text, lang


def _get_system_prompt(lang: str) -> str:
    if lang == "es":
        return SYSTEM_PROMPT_ES
    return SYSTEM_PROMPT_EN


def _get_error_reflection(lang: str) -> str:
    if lang == "es":
        return ERROR_REFLECTION_ES
    return ERROR_REFLECTION_EN


def _requires_api_key(config: Config) -> bool:
    if config.provider in {"lmstudio", "ollama"}:
        return False
    target = config.api_endpoint or config.api_base
    parsed = urlparse(target)
    host = (parsed.hostname or "").lower()
    if host == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_loopback or address.is_private or address.is_link_local):
        return False
    return True


@dataclass
class AgentEvent:
    role: str
    content: str


@dataclass
class AgentStep:
    number: int
    action: dict
    result: str
    plan_step_id: int | None = None


@dataclass
class AgentRunResult:
    answer: str
    steps: list[AgentStep]
    transcript: list[AgentEvent]


AgentEventHandler = Callable[[str, dict[str, object]], None]


@dataclass
class Agent:
    config: Config
    cwd: Path
    transcript: list[AgentEvent] = field(default_factory=list)
    event_handler: AgentEventHandler | None = None
    max_steps: int = 12
    ephemeral: bool = False
    plan: object = None
    run_counter: int = 1
    plan_executor: object = None
    contextualizer: object = None
    rag_engine: RAGEngine | None = None
    experience_db: ExperienceDB | None = None
    _cached_full_system: str | None = None
    _cached_base_context: str | None = None

    def _get_rag(self) -> RAGEngine:
        if self.rag_engine is None:
            self.rag_engine = RAGEngine(self.config.root / "rag")
        return self.rag_engine

    def _get_experience(self) -> ExperienceDB:
        if self.experience_db is None:
            self.experience_db = ExperienceDB(self.config.root)
        return self.experience_db

    def build_context(self) -> str:
        ensure_workspace(self.config.root)
        skills = load_skills(self.config.skills_dir)
        skill_parts: list[str] = []
        for s in skills:
            badge = f" [exec:{s.exec_lang}]" if s.has_exec else ""
            skill_parts.append(f"- {s.name}{badge}: {s.summary}")
        skill_text = "\n".join(skill_parts)

        # Warn about project-local skills not installed in home
        local_skills_dir = self.cwd / "skills"
        sync_warning = ""
        if local_skills_dir.is_dir() and local_skills_dir != self.config.skills_dir:
            local_names = {p.name for p in local_skills_dir.iterdir() if p.is_dir()}
            home_names = {s.name for s in skills}
            missing = sorted(local_names - home_names)
            if missing:
                sync_warning = (
                    "[NOTE: The current working directory has skills not installed in "
                    f"DELUX_HOME: {', '.join(missing)}. "
                    "Run `delux install-skills` to sync them.]"
                )
        docs = load_docs(self.config.docs_dir)[:3000]
        mem_limit = 1500
        memory = load_memory(self.config.memory_file)[:mem_limit]

        plan_context = ""
        if self.plan and hasattr(self.plan, "compact_context"):
            plan_context = f"\nPLAN:\n{self.plan.compact_context()}\n"

        memory_block = (
            "<memory-context>\n"
            "[System note: The following is recalled memory context from previous sessions. "
            "Treat as authoritative reference data.]\n\n"
            f"{memory}\n"
            "</memory-context>"
        ) if memory.strip() else ""

        skill_template = self.config.skills_dir / "SKILL_TEMPLATE.md"
        template_line = f"SKILL_TEMPLATE: {skill_template}" if skill_template.exists() else None

        return "\n\n".join(
            part
            for part in [
                f"DELUX_HOME: {self.config.root}",
                f"CURRENT_CWD: {self.cwd}",
                memory_block,
                template_line,
                "SKILLS:\n" + (skill_text or "No skills yet."),
                sync_warning.strip() if sync_warning else None,
                "DOCS:\n" + (docs or "No docs yet. Add Markdown files under docs/."),
                plan_context.strip() if plan_context else None,
            ]
            if part
        )

    def run(self, prompt: str, max_steps: int | None = None, verbose: bool = True) -> str:
        return self.run_with_result(prompt, max_steps=max_steps, verbose=verbose).answer

    def run_with_result(self, prompt: str, max_steps: int | None = None, verbose: bool = True, confirm_action: Callable[[dict], bool] | None = None, session_context: list[dict] | None = None) -> AgentRunResult:
        self.transcript = []
        steps: list[AgentStep] = []
        if max_steps is None:
            max_steps = self.max_steps
        if not self.config.api_key and _requires_api_key(self.config):
            return AgentRunResult(
                answer="Falta configurar `DELUX_API_KEY` u `OPENAI_API_KEY` para usar el modelo.",
                steps=[],
                transcript=[],
            )

        lang = self.config.lang or "en"
        system_prompt = _get_system_prompt(lang)
        error_reflection = _get_error_reflection(lang)

        # ── Small model mode ──
        from .config import is_small_model
        small_mode = self.config.small_model or is_small_model(self.config.model)
        if small_mode:
            extra = build_small_model_prompt(lang)
            system_prompt += "\n\n" + extra

        action_format = get_action_format_instructions(self.config.model, self.config.root)
        from .mcp.store import get_tools_for_prompt
        mcp_tools_prompt = get_tools_for_prompt(self.config.root)

        few_shot = get_few_shot_examples()
        full_system = system_prompt + action_format + few_shot + mcp_tools_prompt
        t = get_model_template(self.config.model, self.config.root)
        if t.system_suffix:
            full_system = system_prompt + t.system_suffix + few_shot + mcp_tools_prompt

        # Initialize plan executor
        plan_exec = PlanExecutor(self.plan, self.run_counter)
        self.plan_executor = plan_exec

        # Build base context (no plan in it — plan steps injected per-step)
        base_context = self._build_context_without_plan()

        # ── KV Cache warmup (solo si cache_chunk_size > 0, locals, primera vuelta, prompt corto) ──
        if self.config.cache_chunk_size > 0:
            is_local = self.config.provider.lower() in ("ollama", "lmstudio")
            if small_mode and is_local and self.run_counter <= 1 and len(prompt.split()) <= 5:
                self._warmup_cache(full_system, base_context)

        # ── Inject past experiences context (always, cache-friendly at end) ──
        exp_context = ""
        try:
            similar = self._get_experience().find_similar(prompt, top_k=2)
            if similar:
                lines = ["Relevant past experiences:"]
                for exp in similar:
                    lines.append(
                        f"  [{exp['id']}] (x{exp.get('success_count', 1)}) "
                        f"{exp['task'][:120]}"
                    )
                exp_context = "\n".join(lines)
        except Exception:
            pass

        # ── Dataset RAG examples (in system prompt, recomputed each turn) ──
        dataset_few_shot = ""
        try:
            if not hasattr(self, '_rag_ds') or self._rag_ds is None:
                self._rag_ds = DatasetRAG(self.config.root)
            ds = self._rag_ds
            if ds.manifest:
                ds_results = ds.search(prompt, top_k=2)
                if ds_results:
                    dataset_few_shot = ds.format_few_shot(ds_results, max_turns=6)
                    if dataset_few_shot:
                        dataset_few_shot = (
                            "\n\n--- AUTO-INJECTED DATASET EXAMPLES ---\n"
                            "These are real agent trajectories similar to your task.\n"
                            "Study the thinking and tool-calling patterns.\n\n"
                            + dataset_few_shot
                        )
        except Exception:
            pass

        # Optionally run contextualizer to optimize context
        optimized_prompt = prompt
        if hasattr(self, "contextualizer") and self.contextualizer and self.contextualizer.is_enabled():
            self._emit("contextualizer_starting")
            translated_prompt, original_lang = translate_to_english(prompt, self.config)
            ctx_result = self.contextualizer.contextualize(
                user_prompt=translated_prompt,
                memory=load_memory(self.config.memory_file)[:2000] if not self.ephemeral else "",
                skills=self._extract_skills_summary(),
                docs="",
                plan_context=self.plan.compact_context() if self.plan and hasattr(self.plan, "compact_context") else "",
            )
            optimized_prompt = ctx_result.prompt
            if original_lang != "en":
                optimized_prompt += "\n\nNote: The user's original language was Spanish. Please respond in that language."
            self._emit("contextualizer_finished", savings=ctx_result.savings_pct, changes=ctx_result.changes)

        # ── Cache-friendly: system + base_context es el prefijo estable ──
        system_content = full_system
        if dataset_few_shot:
            system_content += dataset_few_shot

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": base_context},
        ]
        if exp_context:
            messages.append({"role": "user", "content": exp_context})
        # Inject prior session turns
        if session_context:
            messages.extend(session_context)
        messages.append({"role": "user", "content": optimized_prompt})

        consecutive_errors = 0
        step_attempts: dict[int, int] = {}
        for step_num in range(1, max_steps + 1):
            # Inject current plan step if in progress
            current_step = plan_exec.get_current_step()
            if current_step:
                step_instruction = plan_exec.build_instruction_for_step(current_step)
                self._emit("plan_step_active", step_id=current_step.id, step_desc=current_step.description, progress=plan_exec.progress_str())
                # Replace the last user message to include step instruction
                messages[-1] = {"role": "user", "content": prompt + "\n\n" + step_instruction}
            elif plan_exec.in_progress and not plan_exec.plan_complete:
                pass  # executor says in_progress but no more steps → will finalize

            try:
                response = chat_completion(
                    self.config.api_base,
                    self.config.api_key,
                    self.config.model,
                    messages,
                    self.config.api_endpoint,
                    self.config.request_timeout,
                    stream=False,
                )
            except LLMError as exc:
                return AgentRunResult(answer=str(exc), steps=steps, transcript=list(self.transcript))

            action = self._parse_action(response.text)
            if verbose:
                print(f"[{step_num}] {action.get('action', 'invalid')}")

            # Smart JSON retry: if plain text, correct with example
            if action.get("_plain_text"):
                _format_retries = 0
                raw_text = response.text
                while action.get("_plain_text") and _format_retries < 2:
                    last_action = steps[-1].action if steps else None
                    example = '{"action":"shell","command":"ls -la","timeout":60}'
                    if last_action:
                        example = json.dumps(last_action, ensure_ascii=False)
                    fix_msg = (
                        "Your last response was not valid JSON. "
                        "Reply with ONLY a single JSON object — no markdown, no extra text.\n"
                        f"Example: {example}\n"
                        f"Your previous response was:\n{raw_text[:400]}"
                    )
                    try:
                        fix_response = chat_completion(
                            self.config.api_base, self.config.api_key, self.config.model,
                            messages + [
                                {"role": "assistant", "content": raw_text},
                                {"role": "user", "content": fix_msg},
                            ],
                            self.config.api_endpoint,
                            self.config.request_timeout,
                        )
                        action = self._parse_action(fix_response.text)
                    except Exception:
                        break
                    _format_retries += 1
                action.pop("_plain_text", None)

            plan_step_id = current_step.id if current_step else None
            if plan_step_id:
                self._emit("plan_step_matched", step_id=plan_step_id, step_desc=current_step.description)

            # Handle skip_step action
            if action.get("action") == "skip_step":
                sid = action.get("step_id")
                reason = action.get("reason", "not needed")
                plan_exec.record_skip(sid, reason)
                skip_msg = f"Step {sid} skipped: {reason}"
                self._emit("plan_step_skipped", step_id=sid, reason=reason, progress=plan_exec.progress_str())
                steps.append(AgentStep(number=step_num, action=action, result=f"SUCCESS: {skip_msg}", plan_step_id=plan_step_id))
                self._emit("action_finished", step=step_num, action=action, result=f"SUCCESS: {skip_msg}", plan_step=plan_step_id)

                # Check if plan is now complete
                if plan_exec.plan_complete:
                    summary = plan_exec.finalize_summary()
                    self._emit("plan_completed", summary=summary)
                    final_msg = {"action": "final", "message": summary}
                    return AgentRunResult(answer=summary, steps=steps, transcript=list(self.transcript))

                # Continue to next step
                consecutive_errors = 0
                messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                messages.append({"role": "user", "content": "Step skipped. Proceed to the next step."})
                continue

            # Block final if plan is in progress and not complete
            if action.get("action") == "final" and plan_exec.in_progress and not plan_exec.plan_complete:
                block_msg = f"You tried to finalize, but the plan is not complete. {plan_exec.progress_str()} done. Return to the current step."
                self._emit("plan_final_blocked", step_id=plan_step_id)
                messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                messages.append({"role": "user", "content": block_msg})
                steps.append(AgentStep(number=step_num, action=action, result=f"BLOCKED: {block_msg}", plan_step_id=plan_step_id))
                consecutive_errors = 0
                continue

            self._emit("action_started", step=step_num, action=action, plan_step=plan_step_id)

            # Dedup: if model repeats same successful action, finalize
            prev_step = steps[-1] if steps else None
            if prev_step and not prev_step.result.startswith("ERROR:") and action == prev_step.action:
                msg = f"Task completed: {action.get('action', 'action')} succeeded"
                if action.get("command"):
                    msg = f"Command done: {action['command']}"
                elif action.get("path"):
                    msg = f"File done: {action['path']}"
                final_action = {"action": "final", "message": msg}
                self._emit("action_started", step=step_num, action=final_action, plan_step=plan_step_id)
                self._emit("final_answer", step=step_num, action=final_action, answer=msg)
                return AgentRunResult(answer=msg, steps=steps, transcript=list(self.transcript))

            if confirm_action and not confirm_action(action):
                result = "ERROR: User denied this action. Try another approach or skip."
                is_error = True
                self.transcript.append(AgentEvent("assistant", json.dumps(action, ensure_ascii=False)))
                self.transcript.append(AgentEvent("tool", result))
                steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
                self._emit("action_finished", step=step_num, action=action, result=result, plan_step=plan_step_id)
                consecutive_errors += 1
                messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                messages.append({"role": "user", "content": result})
                continue

            result = self._dispatch(action, step_number=step_num)
            is_error = result.startswith("ERROR:")

            self.transcript.append(AgentEvent("assistant", json.dumps(action, ensure_ascii=False)))
            self.transcript.append(AgentEvent("tool", result))
            steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
            self._emit("action_finished", step=step_num, action=action, result=result, plan_step=plan_step_id)

            # Record plan step status
            if plan_step_id is not None:
                plan_exec.record_done(plan_step_id, ok=not is_error)
                self._emit("plan_step_status", step_id=plan_step_id, ok=not is_error, progress=plan_exec.progress_str())

                # Check if plan is complete after this step
                if plan_exec.plan_complete:
                    summary = plan_exec.finalize_summary()
                    self._emit("plan_completed", summary=summary)
                    final_msg = {"action": "final", "message": summary}
                    self._emit("final_answer", step=step_num, action=final_msg, answer=summary)
                    return AgentRunResult(answer=summary, steps=steps, transcript=list(self.transcript))

            if action.get("action") == "final":
                self._emit("final_answer", step=step_num, action=action, answer=str(action.get("message", "")).strip())
                return AgentRunResult(
                    answer=str(action.get("message", "")).strip(),
                    steps=steps,
                    transcript=list(self.transcript),
                )

            if is_error:
                consecutive_errors += 1
                if plan_step_id is not None:
                    step_attempts[plan_step_id] = step_attempts.get(plan_step_id, 0) + 1
                    attempts = step_attempts[plan_step_id]
                else:
                    attempts = consecutive_errors

                if attempts >= 3:
                    force_msg = (
                        "You've failed this step 3+ times. "
                        "This requires a COMPLETELY NEW approach. "
                        "Analyze what's fundamentally different about this problem. "
                        "Search the web for solutions if needed. "
                        "Do NOT repeat any previous approach."
                    )
                    messages.append({"role": "user", "content": force_msg})
                else:
                    reflection = error_reflection.format(error=result)
                    messages.append({"role": "user", "content": reflection})

                if consecutive_errors >= 4:
                    diag = self._diagnose_failure(messages, lang)
                    if diag:
                        messages.append({"role": "user", "content": diag})
            else:
                consecutive_errors = 0
                if self.ephemeral:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": base_context + "\n\n" + prompt},
                        {"role": "assistant", "content": json.dumps(action, ensure_ascii=False)},
                        {"role": "user", "content": "Tool result:\n" + result},
                    ]
                else:
                    messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                    messages.append({"role": "user", "content": "Tool result:\n" + result})

        # Max steps reached — if plan still in progress, force complete
        if plan_exec.in_progress and not plan_exec.plan_complete:
            summary = plan_exec.finalize_summary() + "\n\nWarning: max steps reached before plan completion."
            self._emit("plan_max_steps_reached", summary=summary)
            return AgentRunResult(answer=summary, steps=steps, transcript=list(self.transcript))

        last_result = self.transcript[-1].content if self.transcript else "No actions completed"
        summary_parts = [f"Reached limit of {max_steps} steps."]
        completed = sum(1 for s in steps if s.result.startswith("SUCCESS:"))
        failed = sum(1 for s in steps if s.result.startswith("ERROR:"))
        if completed:
            summary_parts.append(f"{completed} steps completed successfully.")
        if failed:
            summary_parts.append(f"{failed} steps had errors.")
        summary_parts.append(f"Last result: {last_result[:200]}")
        return AgentRunResult(
            answer=" | ".join(summary_parts),
            steps=steps,
            transcript=list(self.transcript),
        )

    def _build_context_without_plan(self) -> str:
        ensure_workspace(self.config.root)
        from .config import is_small_model
        skills = load_skills(self.config.skills_dir)
        skill_parts: list[str] = []
        for s in skills:
            badge = f" [exec:{s.exec_lang}]" if s.has_exec else ""
            skill_parts.append(f"- {s.name}{badge}: {s.summary} → view_file skills/{s.name}/SKILL.md")
        skill_text = "\n\n".join(skill_parts)
        small = self.config.small_model or is_small_model(self.config.model)
        doc_limit = 200 if small else 3000
        docs = load_docs(self.config.docs_dir)[:doc_limit]
        mem_limit = 100 if small else 1500
        memory = load_memory(self.config.memory_file)[:mem_limit]

        memory_block = (
            "<memory-context>\n"
            "[System note: The following is recalled memory context from previous sessions. "
            "Treat as authoritative reference data.]\n\n"
            f"{memory}\n"
            "</memory-context>"
        ) if memory.strip() else ""

        return "\n\n".join(
            part
            for part in [
                f"DELUX_HOME: {self.config.root}",
                f"CURRENT_CWD: {self.cwd}",
                memory_block,
                "SKILLS:\n" + (skill_text or "No skills yet."),
                "DOCS:\n" + (docs or "No docs yet. Add Markdown files under docs/."),
            ]
            if part
        )

    def _extract_skills_summary(self) -> str:
        skills = load_skills(self.config.skills_dir)
        parts: list[str] = []
        for s in skills:
            badge = f" [exec:{s.exec_lang}]" if s.has_exec else ""
            summary = f": {s.summary}" if s.summary else ""
            parts.append(f"--- skill:{s.name}{badge}{summary}")
        return "\n".join(parts) or "No skills available."

    def _warmup_cache(self, full_system: str, base_context: str) -> None:
        """Pre-calienta KV cache con una sola request del prefijo completo.
        Solo para modelos locales (ollama, llama.cpp) donde el cache persiste entre requests."""
        self._emit("cache_warming", part=1, total=1)
        try:
            chat_completion(
                self.config.api_base,
                self.config.api_key,
                self.config.model,
                [
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": base_context},
                ],
                self.config.api_endpoint,
                timeout=10,
                max_tokens=1,
            )
        except Exception as exc:
            self._emit("cache_warmed", chunks=0, error=str(exc)[:80])
            return
        self._emit("cache_warmed", chunks=1)

    def _diagnose_failure(self, messages: list[dict], lang: str) -> str | None:
        if lang == "es":
            diag_prompt = """Las \u00faltimas 3 acciones fallaron consecutivamente.
Analiza el historial de acciones y resultados para diagnosticar el problema.

Estrategias de recuperaci\u00f3n:
- Si fall\u00f3 un comando de shell: prueba con flags diferentes, o usa un comando alternativo
- Si fall\u00f3 un file read/write: verifica que la ruta existe con ls, o usa search_files
- Si fall\u00f3 edit_file: primero lee el archivo para ver su contenido actual exacto
- Si fall\u00f3 un skill: el skill podr\u00eda no estar instalado, usa un enfoque manual

Responde SOLO con tu diagn\u00f3stico y la siguiente acci\u00f3n a intentar, en formato JSON:
{"diagnosis": "...", "next_action": {"action": "...", ...}}"""
        else:
            diag_prompt = """The last 3 actions failed consecutively.
Analyze the action history and results to diagnose the problem.

Recovery strategies:
- If shell command failed: try different flags, or an alternative command
- If file read/write failed: verify the path exists with ls, or use search_files
- If edit_file failed: read the file first to see exact current content
- If skill failed: the skill may not be installed, use a manual approach instead

Respond ONLY with your diagnosis and the next action to try, in JSON format:
{"diagnosis": "...", "next_action": {"action": "...", ...}}"""

        try:
            response = chat_completion(
                self.config.api_base,
                self.config.api_key,
                self.config.model,
                messages + [{"role": "user", "content": diag_prompt}],
                self.config.api_endpoint,
                self.config.request_timeout,
            )
            return response.text
        except Exception:
            return None

    def _emit(self, event: str, **payload: object) -> None:
        if self.event_handler:
            self.event_handler(event, payload)

    def _parse_action(self, text: str) -> dict:
        from .templates import parse_action, record_successful_strategy

        template = get_model_template(self.config.model, self.config.root)
        preferred = template.preferred_strategy if template.preferred_strategy != "auto" else None

        parsed, strategy = parse_action(text, preferred_strategy=preferred)

        if preferred is None and strategy != "plain_text":
            record_successful_strategy(self.config.model, strategy, self.config.root)

        action = {"action": parsed.action}
        action.update(parsed.params)
        return action

    def _dispatch(self, action: dict, step_number: int | None = None) -> str:
        kind = action.get("action")
        root = self.config.root
        cwd = self.cwd
        if kind == "shell":
            command = str(action.get("command", ""))
            
            result = run_shell(
                command,
                cwd,
                self.config.shell,
                int(action.get("timeout", 60)),
                stream_callback=lambda chunk: self._emit(
                    "shell_output",
                    step=step_number,
                    action=action,
                    chunk=chunk,
                ),
            )
        elif kind == "read_file":
            result = read_file(str(action.get("path", "")), cwd)
        elif kind == "write_file":
            result = write_file(str(action.get("path", "")), str(action.get("content", "")), cwd)
        elif kind == "append_file":
            result = append_file(str(action.get("path", "")), str(action.get("content", "")), cwd)
        elif kind == "edit_file":
            result = edit_file(
                str(action.get("path", "")),
                str(action.get("old_str", "")),
                str(action.get("new_str", "")),
                cwd,
                replace_all=bool(action.get("replace_all", False)),
            )
        elif kind == "view_file":
            output = view_file_paged(
                str(action.get("path", "")),
                int(action.get("line_start", 1)),
                int(action.get("line_end", 50)),
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "verify_file":
            output = verify_file(
                str(action.get("path", "")),
                cwd,
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "patch_file":
            output = patch_file(
                str(action.get("path", "")),
                str(action.get("old_str", "")),
                str(action.get("new_str", "")),
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "shell_secure":
            output = execute_command_secure(
                str(action.get("command", "")),
                int(action.get("timeout", 15)),
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "move_file":
            result = move_file(str(action.get("src", "")), str(action.get("dst", "")), cwd)
        elif kind == "search_files":
            result = search_files(str(action.get("query", "")), cwd)
        elif kind == "rag_query":
            output = self._get_rag().query(
                str(action.get("query", "")),
                int(action.get("top_k", 5)),
            )
            result = ToolResult(True, output)
        elif kind == "rag_index":
            path = str(action.get("path", str(cwd)))
            chunks = self._get_rag().index_directory(path, recursive=True)
            total = len(self._get_rag().chunks)
            result = ToolResult(True,
                f"Indexed {chunks} new chunks from {path}. "
                f"Total: {total} chunks, {len(self._get_rag().file_hashes)} files.")
        elif kind == "create_skill":
            result = create_skill(
                str(action.get("name", "skill")),
                str(action.get("summary", "")),
                str(action.get("body", "")),
                root,
            )
        elif kind == "run_skill":
            result = run_skill(
                str(action.get("skill", "")),
                str(action.get("args", "")),
                root,
                cwd,
                int(action.get("timeout", 30)),
            )
        elif kind == "remember":
            result = remember(str(action.get("note", "")), root)
        elif kind == "search_web":
            output = search_web(
                str(action.get("query", "")),
                int(action.get("top_k", 5)),
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "save_experience":
            exp = self._get_experience().add(
                task=str(action.get("task", "")),
                solution=str(action.get("solution", "")),
                steps=action.get("steps") or [],
                tags=action.get("tags") or [],
                verified=bool(action.get("verified", False)),
            )
            result = ToolResult(True,
                f"Saved experience {exp['id']}: {action.get('task', '')[:80]}")
        elif kind == "load_experience":
            task = str(action.get("task", ""))
            similar = self._get_experience().find_similar(task, top_k=3)
            if not similar:
                result = ToolResult(True, "No similar past experiences found.")
            else:
                lines = ["Past experiences similar to this task:"]
                for exp in similar:
                    s = exp.get("solution", "")[:200]
                    lines.append(f"\n  [{exp['id']}] (x{exp.get('success_count',1)})")
                    lines.append(f"  Task: {exp['task'][:100]}")
                    lines.append(f"  Solution: {s}")
                result = ToolResult(True, "\n".join(lines))
        elif kind == "call_mcp":
            result = call_mcp_tool(
                str(action.get("server", "")),
                str(action.get("tool", "")),
                action.get("arguments", {}),
                root,
                int(action.get("timeout", 30)),
            )
        elif kind == "final":
            return "Final answer emitted."
        else:
            return f"Unknown action: {kind}"
        return ("SUCCESS: " if result.ok else "ERROR: ") + result.output
