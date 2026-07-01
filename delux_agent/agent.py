from __future__ import annotations

import ipaddress
import json
import re
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
from .store import (
    ensure_workspace, load_docs, load_memory, load_skills,
    save_pending_task, clear_pending_task,
)
from .tools import (
    _check_builtin_write, append_file, call_mcp_tool, create_skill, discover_mcp_tools,
    edit_file, execute_command_secure, move_file, patch_file, read_file, record_skill, remember,
    run_shell, run_skill, search_files, search_web, ToolResult, verify_file,
    view_file_paged, write_file,
)
from .tools import (
    browser_navigate, browser_click, browser_type, browser_scroll,
    browser_snapshot, browser_back, browser_screenshot, browser_extract, browser_close,
    vision_analyze, delegate_task,
    cron_add, cron_remove, cron_list, cron_enable, cron_run, cron_logs,
    kanban_add, kanban_list, kanban_move, kanban_show, kanban_delete, kanban_update,
    computer_screenshot, computer_click, computer_type, computer_keypress, computer_size,
)
from .templates import parse_action, get_model_template, get_action_format_instructions, record_successful_strategy, action_to_xml
from .plan_executor import PlanExecutor
from .training.examples import get_few_shot_examples  # noqa: direct import to avoid circular via __init__


SYSTEM_PROMPT_EN = """You are Delux, an AI assistant for system administration, file management, automation, and software development.

Capabilities:
- Run shell commands via sh/bash
- Read, write, append, edit, and search files
- Execute and create reusable skills
- RAG-powered semantic search over your entire codebase and docs
- Remember facts across sessions
- Browse the web interactively (navigate, click, type, scroll)
- Analyze images with vision AI
- Delegate complex tasks to subagents
- Schedule recurring tasks (cron)
- Manage tasks with a kanban board
- Control the desktop (click, type, screenshot, keypress)

Workspace:
- Shell commands run in the current working directory provided to you
- When creating scripts, programs, or tools that need testing, use ~/.delux/testing/ as a sandbox first
- When a tested file is ready, use `mv` or move_file to place it in its final location

Smart Patterns:
- SIMPLE CHAT: For greetings, short answers, or simple Q&A → go straight to final with a brief message. Do NOT run random commands.
- EXPLAIN AS YOU WORK: Add <info>text</info> inside your actions to explain mid-task. Say why, not just what. Users can't see your thinking — info is how you communicate. Example: <action>shell</action><command>ls</command><info>Listing files to check structure</info>
- AMBIGUITY: If the task has meaningful trade-offs or is underspecified, ask with a message in final. Do NOT guess on destructive operations (rm, overwrite, deploy). For low-stakes decisions, pick a reasonable default.
- BEFORE complex tasks: decompose into steps. Start with load_experience for similar past solutions.
- FOR multi-step work: use set_tasks for a checklist, task_done as you complete each item.
- ON errors: try a different approach. After 3+ failures, use search_web. After 3+ consecutive errors, report the blocker in final.
- AFTER success: save with save_experience so you never solve it again. Save technical patterns with record_skill.
- BEFORE final: confirm all requirements met, verify the solution works, no loose ends.

MEMORY RULES:
What TO save: user preferences, environment facts (OS/tools/project conventions), technical solutions to non-obvious problems, config paths/service names (NOT credentials).
What NOT to save: task progress/completed-work, temporary state/TODO lists/step counters, ephemeral IDs (commit SHAs, PR/issue numbers), anything stale in 7 days.
Save technical solutions via run_skill delux-obsidian-brain, user facts via remember. Procedures belong in skills, not memory.

FINISHING THE JOB (MANDATORY):
- Deliverable = WORKING artifact backed by REAL tool output — not a description.
- Do NOT stop after a stub, plan, or single command. Execute and confirm the result.
- NEVER fabricate output. If a command fails, say so honestly and try an alternative. Reporting a blocker is always better than inventing a result.
- Before "final": verify every file exists (view_file), every script runs (shell), every change produces expected output.
- If a tool fails 3+ times with different approaches, report the specific error in "final".

VERIFICATION PIPELINE (3 levels — apply in order):
Level 1 — SYNTAX: After write_file/edit_file → verify_file
Level 2 — EXECUTION: After creating scripts → run them (e.g. python3 script.py --help 2>&1 | head -20)
Level 3 — FUNCTIONAL: After building features → run the use case and check output matches expectations
RULE: Do NOT use "final" until Level 1 passes. Level 2 is mandatory for scripts. Level 3 is mandatory when the request has a testable outcome.

TOKEN EFFICIENCY:
- Your XML action is the ONLY output. No preamble, no explanation, no markdown wrapping.
- In "final": state what was done in 1-3 sentences. Do not recap every step.
- When reading files: use line_start/line_end. Do not read entire large files.
- Use edit_file over write_file when changing <30% of content.
- Chain simple independent shell commands with &&.

Rules:
- Never use sudo or privilege escalation.
- Work autonomously. Return ONLY one action in XML format per turn.
- Shell commands run in POSIX sh. Use portable syntax.
- PATH RULE: relative paths resolve against CURRENT_CWD. Use absolute paths outside CWD. Never use ~ or $HOME.
- Use edit_file instead of shell echo/sed for modifying existing files.
- BROWSER: Native actions (navigate/click/type/snapshot/scroll/back) keep browser OPEN between steps for multi-step workflows. skill delux-browser does ONE action and CLOSES it. Add headed=true to make the window visible.

After each action:
- SUCCESS → proceed to next step. When all done, use final.
- ERROR → analyze and try a DIFFERENT approach. NEVER repeat the same failing command.

ACTIONS REFERENCE (return exactly one per turn, in XML tags):
  shell(command, timeout=60)              — Run shell command
  shell_secure(command, timeout=15)        — Run sensitive command
  view_file(path, line_start=1, line_end=50) — View file section
  read_file(path)                          — Read entire file (small files only)
  write_file(path, content)                — Create/overwrite file
  edit_file(path, old_str, new_str)        — Replace text in file
  patch_file(path, old_str, new_str)       — Same as edit_file (alias)
  append_file(path, content)               — Append to file
  move_file(src, dst)                      — Move/rename file
  search_files(query)                      — Search file contents
  verify_file(path)                        — Check syntax
  rag_query(query, top_k=5)                — Semantic search via RAG
  search_web(query, top_k=5)               — Web search
  save_experience(task, solution, tags)    — Save reusable solution
  load_experience(task)                    — Find past solution
  run_skill(skill, args, timeout=30)       — Execute a skill
  create_skill(name, summary, body)        — Create new skill
  remember(note)                           — Save fact to memory
  record_skill(name, summary, steps)       — Record skill pattern
  set_tasks(tasks)                         — Create task checklist
  task_done(task)                          — Mark task complete
  skip_step(step_id, reason)               — Skip a plan step
  ANY ACTION + info (optional tag)         — Add <info>text</info> inside any action to explain mid-task
  final(summary, message)                  — End the task
  delegate_task(task, max_steps=90, timeout=120) — Spawn subagent
  browser_navigate(url, timeout=30)        — Open URL in browser
  browser_click(selector)                  — Click element
  browser_type(selector, text)             — Type into input
  browser_scroll(direction, amount)        — Scroll the page
  browser_snapshot()/screenshot()/extract()/back()/close() — Browser utilities
  vision_analyze(image_path, prompt)       — Analyze image with vision AI
  cron_add/remove/list/enable/run/logs     — Schedule/manage cron jobs
  kanban_add/list/move/show/delete/update  — Manage task board
  computer_screenshot/click/type/keypress/size — Desktop automation
"""

SYSTEM_PROMPT_ES = """Eres Delux, un asistente IA para administración del sistema, gestión de archivos, automatización y desarrollo.

Capacidades:
- Ejecutar comandos de shell vía sh/bash
- Leer, escribir, editar, anexar, mover y buscar archivos
- Ejecutar y crear skills reutilizables
- Búsqueda RAG sobre todo el codebase y documentos
- Recordar hechos entre sesiones
- Navegar la web interactivamente (navegar, hacer clic, escribir, desplazar)
- Analizar imágenes con visión IA
- Delegar tareas complejas a subagentes
- Programar tareas recurrentes (cron)
- Gestionar tareas con un tablero kanban
- Controlar el escritorio (clic, escribir, captura de pantalla, teclas)

Espacio de trabajo:
- Los comandos de shell se ejecutan en el directorio de trabajo actual que se te proporciona
- Al crear scripts, programas o herramientas que necesiten prueba, usa ~/.delux/testing/ como entorno de pruebas
- Cuando un archivo probado esté listo, usa `mv` o move_file para colocarlo en su ubicación final

Patrones Inteligentes:
- CHAT SIMPLE: Para saludos, respuestas cortas o preguntas simples → usa final directo con mensaje breve. NO ejecutes comandos al azar.
- EXPLICA MIENTRAS TRABAJAS: Añade <info>texto</info> dentro de tus acciones para explicar en medio de la tarea. Di el porqué, no solo el qué. Ejemplo: <action>shell</action><command>ls</command><info>Listando archivos para revisar estructura</info>
- AMBIGÜEDAD: Si la tarea tiene trade-offs significativos o está subespecificada, pregunta con un mensaje en final.
- ANTES de tareas complejas: descompón en pasos. Empieza con load_experience para soluciones similares.
- PARA trabajo multi-paso: usa set_tasks para checklist, task_done al completar cada item.
- EN errores: prueba enfoque diferente. Tras 3+ fallos, usa search_web. Tras 3+ errores consecutivos, reporta el bloqueo en final.
- DESPUÉS de éxito: guarda con save_experience. Guarda patrones técnicos con record_skill.
- ANTES de final: confirma requisitos cumplidos, verifica funcionamiento, sin cabos sueltos.

REGLAS DE MEMORIA:
Qué GUARDAR: preferencias del usuario, facts del entorno (OS/herramientas/convenciones del proyecto), soluciones técnicas a problemas no obvios, rutas de config/nombres de servicios (NO credenciales).
Qué NO guardar: progreso de tareas/trabajo completado, estado temporal/listas TODO/contadores de pasos, IDs efímeros (commit SHAs, números de PR/issue), anything obsoleto en 7 días.
Guarda soluciones técnicas con run_skill delux-obsidian-brain, facts de usuario con remember.

FINALIZAR EL TRABAJO (OBLIGATORIO):
- Entregable = artifacto FUNCIONAL respaldado por output REAL de herramientas — no una descripción.
- No pares después de un stub, plan o comando único. Ejecuta y confirma el resultado.
- NUNCA fabriques output. Si un comando falla, dilo honestamente e intenta una alternativa. Reportar un bloqueo siempre es mejor que inventar un resultado.
- Antes de "final": verifica que cada archivo existe (view_file), cada script funciona (shell), cada cambio produce el output esperado.
- Si una herramienta falla 3+ veces con diferentes enfoques, reporta el error específico en "final".

PIPELINE DE VERIFICACIÓN (3 niveles — aplicar en orden):
Nivel 1 — SINTAXIS: Después de write_file/edit_file → verify_file
Nivel 2 — EJECUCIÓN: Después de crear scripts → ejecútalos (e.g. python3 script.py --help)
Nivel 3 — FUNCIONAL: Después de construir funciones → ejecuta el caso de uso y verifica el output
REGLAS: No uses "final" hasta Nivel 1 OK. Nivel 2 obligatorio para scripts. Nivel 3 obligatorio cuando el resultado es verificable.

EFICIENCIA DE TOKENS:
- Tu acción XML es el ÚNICO output. Sin preámbulos, explicaciones ni markdown.
- En "final": di lo que se hizo en 1-3 oraciones. No recapitules cada paso.
- Al leer archivos: usa line_start/line_end. No leas archivos grandes completos.
- Usa edit_file en lugar de write_file cuando cambies <30% del contenido.
- Encadena comandos shell simples e independientes con &&.

Reglas:
- Nunca uses sudo ni escalación de privilegios.
- Trabaja autónomamente. Devuelve SOLO una acción en XML por turno.
- Los comandos shell se ejecutan en POSIX sh. Usa sintaxis portable.
- REGLA DE RUTAS: rutas relativas se resuelven contra CURRENT_CWD. Usa absolutas fuera del CWD. Nunca uses ~ o $HOME.
- Usa edit_file en lugar de echo/sed por shell para modificar archivos existentes.
- NAVEGADOR: Acciones nativas (navigate/click/type/snapshot/scroll/back) mantienen el navegador ABIERTO entre pasos. skill delux-browser hace UNA acción y CIERRA. Añade headed=true para mostrar la ventana.

Después de cada acción:
- SUCCESS → continúa al siguiente paso. Cuando termines, usa final.
- ERROR → analiza e intenta un enfoque DIFERENTE. NUNCA repitas el mismo comando.

REFERENCIA DE ACCIONES (devuelve exactamente una por turno, en XML):
  shell(command, timeout=60)              — Ejecutar comando shell
  shell_secure(command, timeout=15)        — Comando sensible
  view_file(path, line_start=1, line_end=50) — Ver sección de archivo
  read_file(path)                          — Leer archivo completo (solo pequeños)
  write_file(path, content)                — Crear/sobrescribir archivo
  edit_file(path, old_str, new_str)        — Reemplazar texto en archivo
  patch_file(path, old_str, new_str)       — Igual que edit_file (alias)
  append_file(path, content)               — Añadir a archivo
  move_file(src, dst)                      — Mover/renombrar archivo
  search_files(query)                      — Buscar en archivos
  verify_file(path)                        — Verificar sintaxis
  rag_query(query, top_k=5)                — Búsqueda semántica vía RAG
  search_web(query, top_k=5)               — Búsqueda web
  save_experience(task, solution, tags)    — Guardar solución reutilizable
  load_experience(task)                    — Encontrar solución pasada
  run_skill(skill, args, timeout=30)       — Ejecutar un skill
  create_skill(name, summary, body)        — Crear nuevo skill
  remember(note)                           — Guardar hecho en memoria
  record_skill(name, summary, steps)       — Registrar patrón de skill
  set_tasks(tasks)                         — Crear checklist de tareas
  task_done(task)                          — Marcar tarea completada
  skip_step(step_id, reason)               — Saltar paso del plan
  CUALQUIER ACCIÓN + info (tag opcional)   — Añade <info>texto</info> dentro de cualquier acción para explicar
  final(summary, message)                  — Finalizar la tarea
  delegate_task(task, max_steps=90, timeout=120) — Lanzar subagente
  browser_navigate(url, timeout=30)        — Abrir URL en navegador
  browser_click(selector)                  — Hacer clic en elemento
  browser_type(selector, text)             — Escribir en input
  browser_scroll(direction, amount)        — Desplazar página
  browser_snapshot()/screenshot()/extract()/back()/close() — Utilidades navegador
  vision_analyze(image_path, prompt)       — Analizar imagen con visión IA
  cron_add/remove/list/enable/run/logs     — Programar/gestionar cron
  kanban_add/list/move/show/delete/update  — Gestionar tablero de tareas
  computer_screenshot/click/type/keypress/size — Automatización escritorio
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


def build_session_context(
    session_summary: str = "",
    history: list[dict] | None = None,
) -> list[dict] | None:
    ctx: list[dict] = []
    if session_summary:
        ctx.append({"role": "user", "content": "[Previous conversation summary]\n" + session_summary})
    if history:
        for turn in history[-5:]:
            ctx.append({"role": "user", "content": str(turn.get("user") or turn.get("prompt") or "")})
            ctx.append({"role": "assistant", "content": str(turn.get("assistant") or turn.get("answer") or "")})
    return ctx or None


def _check_missing_files(message: str, steps: list) -> str | None:
    """If final message claims files by extension, verify write_file/edit_file/shell was used for each."""
    ext_pat = r'\b\w+\.(css|js|html?|tsx?|jsx|py|json|ya?ml|xml|md|txt|sh|env|conf|go|rs|vue|svelte|php)\b'
    claimed = set()
    for m in re.finditer(ext_pat, message.lower()):
        claimed.add(m.group(1))
    if not claimed:
        return None

    created = set()
    for s in steps:
        a = s.action
        if a.get("action") in ("write_file", "edit_file", "patch_file"):
            path = a.get("path", "")
            if "." in path:
                created.add(path.rsplit(".", 1)[-1].lower())
        elif a.get("action") == "shell":
            cmd = a.get("command", "")
            for m in re.finditer(ext_pat, cmd.lower()):
                created.add(m.group(1))

    missing = claimed - created
    if not missing:
        return None
    exts = ", .".join(sorted(missing))
    return (
        f"ERROR: Tu mensaje final menciona archivos .{exts} que no existen en el historial de acciones. "
        f"Debes crearlos con write_file antes de finalizar."
    )


_TASKS_PATH = Path.home() / ".delux" / "tasks.json"


def _load_tasks() -> list[dict] | None:
    """Return list of {desc, done} or None."""
    if _TASKS_PATH.is_file():
        try:
            return json.loads(_TASKS_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            _TASKS_PATH.unlink()
            return None
    return None


def _save_tasks(tasks: list[dict]) -> None:
    _TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TASKS_PATH.write_text(json.dumps(tasks, indent=2))


def _clear_tasks() -> None:
    if _TASKS_PATH.is_file():
        _TASKS_PATH.unlink()


def _tasks_to_markdown(tasks: list[dict] | None) -> str | None:
    """Convert tasks list to markdown checkbox format for prompt injection."""
    if not tasks:
        return None
    lines = ["[Active tasks]"]
    for t in tasks:
        status = "x" if t.get("done") else " "
        lines.append(f"- [{status}] {t.get('desc', '?')}")
    lines.append("[End tasks]")
    return "\n".join(lines)


def _check_tasks_done() -> str | None:
    """Return error string if any task is not done, else None."""
    tasks = _load_tasks()
    if not tasks:
        return None
    pending = [t for t in tasks if not t.get("done")]
    if not pending:
        return None
    lines = ["- [ ] " + t.get("desc", "?") for t in pending]
    return (
        "ERROR: You have incomplete tasks:\n"
        + "\n".join(lines)
        + "\n\nUse task_done to mark them complete before calling final."
    )


def _try_xml_plan(text: str) -> dict | None:
    """Extract plan data from XML format: <plan><summary>...</summary><step>...</step></plan>"""
    import re
    text = re.sub(r"^```(?:xml)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    summary_m = re.search(r"<summary>([\s\S]*?)</summary>", text)
    steps = re.findall(
        r"<step[^>]*>\s*<description>([\s\S]*?)</description>(?:\s*<detail>([\s\S]*?)</detail>)?\s*</step>",
        text,
    )
    questions = re.findall(
        r"<question>\s*<text>([\s\S]*?)</text>\s*<options>(.*?)</options>\s*</question>",
        text,
        re.DOTALL,
    )
    if summary_m:
        opts_list = []
        for qtext, qopts in questions:
            opts = re.findall(r"<option>([^<]*)</option>", qopts)
            opts_list.append({"text": qtext.strip(), "options": opts})
        if opts_list:
            return {"questions": opts_list}
        step_list = []
        for desc, detail in steps:
            step_list.append({"description": desc.strip(), "detail": detail.strip() if detail else ""})
        if step_list:
            return {"summary": summary_m.group(1).strip(), "steps": step_list}
    return None


def _try_text_plan(text: str) -> dict | None:
    """Parse a plain-text plan when XML parsing fails.
    Handles numbered lists, bullet lists, action-prefixed lines, 'Step N:' format,
    and inline "Create file.ext description Create file2.ext description" format."""
    import re
    primary = r'(?:Run|Read|Search|Create|Install|Build|Deploy|Test|Verify|List|Show|Open|Navigate|Analyze|Review|Fix|Update|Remove|Delete|Add|Copy|Move|Execute)'

    # Strategy 1: split by 'Step N:' pattern
    parts = re.split(r'Step\s+\d+\s*:\s*', text.strip())
    if len(parts) > 2:
        steps = []
        for part in parts[1:]:
            part = part.strip().rstrip(".").strip()
            if part:
                steps.append({"description": part, "detail": ""})
        if steps:
            summary = steps[0]["description"][:100]
            return {"summary": summary, "steps": steps}

    # Strategy 2: split at position before action+filename.ext mid-line
    # Handles "Create index.html ...Create style.css ...Create script.js" (no periods)
    parts = re.split(r'(?<=\s)(?=' + primary + r'\s+\S*\.\w{2,4}\s)', text.strip())
    if len(parts) > 1:
        steps = []
        for part in parts:
            part = part.strip()
            if part:
                steps.append({"description": part, "detail": ""})
        if steps:
            summary = steps[0]["description"][:100]
            return {"summary": summary, "steps": steps}

    # Strategy 3: split by period + action word (handles "Create X. Create Y.")
    parts = re.split(rf'\.\s+(?={primary}\s)', text.strip())
    if len(parts) > 1:
        steps = []
        for part in parts:
            part = part.strip().rstrip(".")
            if part:
                steps.append({"description": part, "detail": ""})
        if steps:
            summary = steps[0]["description"][:100]
            return {"summary": summary, "steps": steps}

    # Strategy 4: split by newlines with numbered/bullet/action-prefix
    steps = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r'^\d+[.)]\s+(.+)$', line):
            steps.append({"description": re.match(r'^\d+[.)]\s+(.+)$', line).group(1).strip(), "detail": ""})
        elif re.match(r'^[-*]\s+(.+)$', line):
            steps.append({"description": re.match(r'^[-*]\s+(.+)$', line).group(1).strip(), "detail": ""})
        elif re.match(rf'^({primary})\s*:\s*(.+)$', line, re.IGNORECASE):
            m = re.match(rf'^({primary})\s*:\s*(.+)$', line, re.IGNORECASE)
            steps.append({"description": f"{m.group(1)}: {m.group(2).strip()}", "detail": ""})
        elif re.match(rf'^{primary}\s', line, re.IGNORECASE):
            steps.append({"description": line, "detail": ""})
    if steps:
        summary = steps[0]["description"][:100]
        return {"summary": summary, "steps": steps}
    return None


def clean_model_response(response: str) -> str:
    """Strip non-XML content from model response before parsing."""
    response = re.sub(r'```xml\s*', '', response)
    response = re.sub(r'```\s*$', '', response)
    match = re.search(r'<action>', response)
    if match:
        response = response[match.start():]
    return response.strip()


def classify_complexity(user_message: str) -> str:
    """Classify user message complexity for context injection levels: minimal, light, or full."""
    msg_lower = user_message.lower().strip()
    simple_greetings = [
        r'^(hola|hi|hello|hey|buenos?\s*(días|tardes|noches)|qué\s*tal|c(o|ó)mo\s*est(a|á)s)',
        r'^(thanks?|gracias|ok|sí|no|listo|perfecto|genial|dale|sale)$',
        r'^si$',
    ]
    for pat in simple_greetings:
        if re.match(pat, msg_lower):
            return "minimal"
    if len(msg_lower.split()) < 10 and '?' in msg_lower:
        return "light"
    return "full"


def create_plan(prompt: str, config: Config, lang: str = "en", cwd: str = "") -> object | None:
    from .plan_executor import build_planner_prompt, AgentPlan, PlanStepStatus
    from .llm import chat_completion, LLMError
    import json as _json
    import re

    plan_model = config.effective_plan_model
    plan_base = config.effective_plan_api_base
    plan_key = config.effective_plan_api_key
    plan_ep = config.effective_plan_api_endpoint

    sys_context = f"Current directory: {cwd or config.cwd or '.'}\nProject root: {config.root}"
    planner_prompt = build_planner_prompt(prompt=prompt, system_context=sys_context, lang=lang)

    text = ""
    try:
        plan_response = chat_completion(
            plan_base, plan_key, plan_model,
            [
                {"role": "system", "content": "You ONLY output XML. Never add text before or after the XML. No markdown. No code fences. Just raw XML."},
                {"role": "user", "content": planner_prompt},
            ],
            plan_ep, timeout=30,
        )
        text = plan_response.text.strip()
        data = _try_xml_plan(text) or _try_json_plan(text) or _try_text_plan(text)
    except LLMError as e:
        import sys
        print(f"[plan] API error ({plan_model}): {e}", file=sys.stderr)
        return None
    except Exception as e:
        import sys
        print(f"[plan] Unexpected error: {e}", file=sys.stderr)
        return None

    if data and "questions" in data:
        import sys
        print(f"[plan] Model asked questions instead of creating plan", file=sys.stderr)
        return None

    if data and data.get("steps"):
        summary = data.get("summary", "")
        raw_steps = data.get("steps", [])
        step_list = []
        for i, s in enumerate(raw_steps, 1):
            desc = s.get("description", f"Step {i}")
            detail = s.get("detail", "")
            step_list.append(PlanStepStatus(id=i, description=desc, detail=detail))
        plan = AgentPlan(prompt=prompt, steps=step_list, summary=summary)
        import sys
        print(f"[plan] Created: {summary} ({len(step_list)} steps)", file=sys.stderr)
        return plan

    import sys
    print(f"[plan] Parse failed. Raw: {text[:200] if text else 'empty'}", file=sys.stderr)
    return None


def _try_json_plan(text: str) -> dict | None:
    """Fallback JSON plan parser."""
    import json as _json
    import re
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    json_start = text.find("{")
    json_end = text.rfind("}")
    if json_start >= 0 and json_end > json_start:
        text = text[json_start:json_end + 1]
    try:
        return _json.loads(text)
    except Exception:
        return None


def prepare_agent(
    config: Config,
    cwd: Path,
    event_handler,
    prompt: str,
    *,
    active_model_idx: int = 0,
    validator_model_idx: int | None = None,
    plan_mode: bool = False,
    ephemeral: bool = False,
    system_suffix: str = "",
    max_steps: int = 90,
    run_counter: int = 1,
    lang: str = "en",
) -> "Agent":
    from dataclasses import replace as _replace

    run_config = config
    active_cfg = config.models[active_model_idx] if active_model_idx < len(config.models) else None
    if active_cfg:
        run_config = _replace(
            config,
            model=active_cfg.name,
            provider=active_cfg.provider or config.provider,
            api_base=active_cfg.api_base or config.api_base,
            api_key=active_cfg.api_key or config.api_key,
        )

    if validator_model_idx is not None and validator_model_idx < len(config.models):
        vm = config.models[validator_model_idx]
        run_config = _replace(run_config,
            validator_model=vm.name,
            validator_provider=vm.provider or run_config.provider,
            validator_api_base=vm.api_base or run_config.api_base,
            validator_api_key=vm.api_key or run_config.api_key,
        )

    plan_obj = None
    if plan_mode:
        plan_obj = create_plan(prompt, run_config, lang, cwd=str(cwd))

    return Agent(
        config=run_config, cwd=cwd,
        event_handler=event_handler,
        max_steps=max_steps, ephemeral=ephemeral,
        plan=plan_obj, system_suffix=system_suffix,
        run_counter=run_counter,
    )


@dataclass
class Agent:
    config: Config
    cwd: Path
    transcript: list[AgentEvent] = field(default_factory=list)
    event_handler: AgentEventHandler | None = None
    max_steps: int = 90
    ephemeral: bool = False
    plan: object = None
    run_counter: int = 1
    plan_executor: object = None
    contextualizer: object = None
    rag_engine: RAGEngine | None = None
    experience_db: ExperienceDB | None = None
    system_suffix: str = ""
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


    def run(self, prompt: str, max_steps: int | None = None, verbose: bool = True) -> str:
        return self.run_with_result(prompt, max_steps=max_steps, verbose=verbose).answer

    def run_with_result(self, prompt: str, max_steps: int | None = None, verbose: bool = True, confirm_action: Callable[[dict], bool] | None = None, session_context: list[dict] | None = None) -> AgentRunResult:
        from .browser import set_headless_mode
        set_headless_mode(self.config.browser_headless)
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
        if self.system_suffix:
            full_system += "\n\n" + self.system_suffix

        # Initialize plan executor
        plan_exec = PlanExecutor(self.plan, self.run_counter)
        self.plan_executor = plan_exec

        # Classify complexity and build minimal/light/full context
        complexity = classify_complexity(prompt)
        base_context = self._build_context_without_plan(complexity)

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
                # Small models benefit from more examples
                ds_top_k = 5 if small_mode else 2
                ds_max_turns = 8 if small_mode else 6
                ds_results = ds.search(prompt, top_k=ds_top_k)
                if ds_results:
                    dataset_few_shot = ds.format_few_shot(ds_results, max_turns=ds_max_turns)
                    if dataset_few_shot:
                        dataset_few_shot = (
                            "\n\n--- AUTO-INJECTED DATASET EXAMPLES ---\n"
                            "These are real agent trajectories similar to your task.\n"
                            "Study the thinking and tool-calling patterns.\n\n"
                            + dataset_few_shot
                        )
        except Exception:
            pass

        # ── User feedback examples (injected as few-shot context) ──
        feedback_examples = ""
        try:
            fb_path = self.config.root / "examples" / "feedback.jsonl"
            if fb_path.exists():
                import json as _json
                fb_lines: list[str] = []
                with open(fb_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and len(fb_lines) < 3:
                            try:
                                data = _json.loads(line)
                                p = data.get("prompt", "")[:200]
                                r = data.get("response", "")[:400]
                                if p and r:
                                    fb_lines.append(f"USER: {p}\nAGENT: {r}")
                            except _json.JSONDecodeError:
                                pass
                if fb_lines:
                    feedback_examples = (
                        "\n\n--- YOUR FEEDBACK EXAMPLES ---\n"
                        "These are tasks you previously approved. Follow the same patterns.\n\n"
                        + "\n\n".join(fb_lines)
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

        # ── Build messages with optimal cache ordering ──
        messages = [
            {"role": "system", "content": full_system},
        ]

        # Always send CWD as a separate, prominent message right before the prompt.
        # This ensures the model always knows the current directory, regardless of history.
        if session_context:
            messages.extend(session_context)
        else:
            # First turn: send base_context (it'll persist in history)
            messages.append({"role": "user", "content": base_context})
        # CURRENT CWD — always the last context before the prompt, never ambiguous
        messages.append({"role": "user", "content": f"CURRENT DIRECTORY: {self.cwd}"})
        messages.append({"role": "user", "content": optimized_prompt})

        # Small models get extra dynamic context (at the end, no cache impact for large)
        if small_mode:
            if dataset_few_shot:
                messages.append({"role": "user", "content": dataset_few_shot})
            if feedback_examples:
                messages.append({"role": "user", "content": feedback_examples})
            if exp_context:
                messages.append({"role": "user", "content": exp_context})

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

            # ── Inject current tasks (replace if already present) ──
            tasks_content = _tasks_to_markdown(_load_tasks())
            if tasks_content:
                # Find and replace existing task message, or append new one
                task_idx = None
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user" and isinstance(messages[i].get("content"), str) and messages[i]["content"].startswith("[Active tasks]"):
                        task_idx = i
                        break
                task_msg = {"role": "user", "content": tasks_content}
                if task_idx is not None:
                    messages[task_idx] = task_msg
                else:
                    messages.append(task_msg)

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
                save_pending_task(self.config.root, prompt)
                return AgentRunResult(answer=str(exc), steps=steps, transcript=list(self.transcript))

            action = self._parse_action(response.text)
            if verbose:
                print(f"[{step_num}] {action.get('action', 'invalid')}")

            # Smart format retry: if plain text, correct with example
            if action.get("_plain_text"):
                _format_retries = 0
                raw_text = response.text
                while action.get("_plain_text") and _format_retries < 2:
                    last_action = steps[-1].action if steps else None
                    example = "<action>shell</action>\n<command>ls -la</command>\n<timeout>60</timeout>"
                    if last_action:
                        example = action_to_xml(last_action)
                    fix_msg = (
                        "Your last response was not valid XML action format. "
                        "Reply with ONLY an action using XML tags — no markdown, no extra text.\n"
                        f"Example:\n{example}\n"
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
                messages.append({"role": "assistant", "content": action_to_xml(action)})
                messages.append({"role": "user", "content": "Step skipped. Proceed to the next step."})
                continue

            # ── Handle task actions ──
            if action.get("action") == "set_tasks":
                raw = action.get("tasks", "")
                if isinstance(raw, str):
                    try:
                        descs = json.loads(raw) if raw.strip() else []
                    except (json.JSONDecodeError, ValueError):
                        descs = [raw]
                elif isinstance(raw, list):
                    descs = [str(d) for d in raw]
                else:
                    descs = []
                if not descs:
                    result = "ERROR: set_tasks needs a JSON array in <tasks> tag"
                else:
                    saved = [{"desc": d, "done": False} for d in descs]
                    _save_tasks(saved)
                    self._emit("tasks_updated", tasks=saved)
                    result = f"SUCCESS: Created {len(descs)} tasks."
                self.transcript.append(AgentEvent("assistant", action_to_xml(action)))
                self.transcript.append(AgentEvent("tool", result))
                steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
                self._emit("action_finished", step=step_num, action=action, result=result, plan_step=plan_step_id)
                consecutive_errors = 0
                messages.append({"role": "assistant", "content": action_to_xml(action)})
                messages.append({"role": "user", "content": result})
                continue

            if action.get("action") == "task_done":
                desc = action.get("task", "")
                if not desc:
                    result = "ERROR: task_done needs a <task> tag"
                else:
                    tasks = _load_tasks()
                    if not tasks:
                        result = "ERROR: No active tasks. Use set_tasks first."
                    else:
                        found = False
                        for t in tasks:
                            if not t.get("done") and desc.lower() in t.get("desc", "").lower():
                                t["done"] = True
                                found = True
                                break
                        if not found:
                            # Try matching against all tasks (including already done)
                            for t in tasks:
                                if desc.lower() in t.get("desc", "").lower():
                                    t["done"] = True
                                    found = True
                                    break
                        if found:
                            _save_tasks(tasks)
                            self._emit("tasks_updated", tasks=tasks)
                            pending = sum(1 for t in tasks if not t.get("done"))
                            result = f"SUCCESS: Task '{desc}' completed. {pending} task(s) remaining."
                        else:
                            result = f"ERROR: No task matches '{desc}'. Active tasks: {[t['desc'] for t in tasks]}"
                self.transcript.append(AgentEvent("assistant", action_to_xml(action)))
                self.transcript.append(AgentEvent("tool", result))
                steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
                self._emit("action_finished", step=step_num, action=action, result=result, plan_step=plan_step_id)
                consecutive_errors = 0
                messages.append({"role": "assistant", "content": action_to_xml(action)})
                messages.append({"role": "user", "content": result})
                continue

            # Block final if plan is in progress and not complete
            if action.get("action") == "final" and plan_exec.in_progress and not plan_exec.plan_complete:
                block_msg = f"You tried to finalize, but the plan is not complete. {plan_exec.progress_str()} done. Return to the current step."
                self._emit("plan_final_blocked", step_id=plan_step_id)
                messages.append({"role": "assistant", "content": action_to_xml(action)})
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
                clear_pending_task(self.config.root)
                return AgentRunResult(answer=msg, steps=steps, transcript=list(self.transcript))

            if confirm_action and not confirm_action(action):
                result = "ERROR: User denied this action. Try another approach or skip."
                is_error = True
                self.transcript.append(AgentEvent("assistant", action_to_xml(action)))
                self.transcript.append(AgentEvent("tool", result))
                steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
                self._emit("action_finished", step=step_num, action=action, result=result, plan_step=plan_step_id)
                consecutive_errors += 1
                messages.append({"role": "assistant", "content": action_to_xml(action)})
                messages.append({"role": "user", "content": result})
                continue

            result = self._dispatch(action, step_number=step_num)
            is_error = result.startswith("ERROR:")

            self.transcript.append(AgentEvent("assistant", action_to_xml(action)))
            self.transcript.append(AgentEvent("tool", result))
            steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
            self._emit("action_finished", step=step_num, action=action, result=result, plan_step=plan_step_id)

            # Record plan step status
            if plan_step_id is not None:
                plan_exec.record_done(plan_step_id, ok=not is_error)
                self._emit("plan_step_status", step_id=plan_step_id, ok=not is_error, progress=plan_exec.progress_str())

                # Check if plan is complete after this step
                if plan_exec.plan_complete:
                    _clear_tasks()
                    self._emit("tasks_updated", tasks=[])
                    summary = plan_exec.finalize_summary()
                    self._emit("plan_completed", summary=summary)
                    final_msg = {"action": "final", "message": summary}
                    self._emit("final_answer", step=step_num, action=final_msg, answer=summary)
                    clear_pending_task(self.config.root)
                    return AgentRunResult(answer=summary, steps=steps, transcript=list(self.transcript))

            # ── Reject final if it claims files that were never created ──
            if action.get("action") == "final":
                final_msg = action.get("message", "") or ""
                final_summary = action.get("summary", "") or ""
                combined = f"{final_msg} {final_summary}"
                if combined:
                    err = _check_missing_files(combined, steps)
                    if err:
                        result = err
                        is_error = True
                        self.transcript.append(AgentEvent("assistant", action_to_xml(action)))
                        self.transcript.append(AgentEvent("tool", result))
                        steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
                        consecutive_errors += 1
                        messages.append({"role": "assistant", "content": action_to_xml(action)})
                        messages.append({"role": "user", "content": result})
                        continue

                # ── Check for incomplete tasks ──
                err = _check_tasks_done()
                if err:
                    result = err
                    is_error = True
                    self.transcript.append(AgentEvent("assistant", action_to_xml(action)))
                    self.transcript.append(AgentEvent("tool", result))
                    steps.append(AgentStep(number=step_num, action=action, result=result, plan_step_id=plan_step_id))
                    consecutive_errors += 1
                    messages.append({"role": "assistant", "content": action_to_xml(action)})
                    messages.append({"role": "user", "content": result})
                    continue

            if action.get("action") == "final":
                _clear_tasks()
                self._emit("tasks_updated", tasks=[])
                clear_pending_task(self.config.root)
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
                        {"role": "assistant", "content": action_to_xml(action)},
                        {"role": "user", "content": "Tool result:\n" + result},
                    ]
                else:
                    messages.append({"role": "assistant", "content": action_to_xml(action)})
                    messages.append({"role": "user", "content": "Tool result:\n" + result})

        # Max steps reached — if plan still in progress, force complete
        if plan_exec.in_progress and not plan_exec.plan_complete:
            save_pending_task(self.config.root, prompt)
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
        save_pending_task(self.config.root, prompt)
        return AgentRunResult(
            answer=" | ".join(summary_parts),
            steps=steps,
            transcript=list(self.transcript),
        )

    def _fmt_skill(self, s: Skill) -> str:
        parts = [f"- {s.name}"]
        if s.builtin:
            parts.append(" [built-in]")
        if s.has_exec:
            parts.append(f" [exec:{s.exec_lang}]")
        parts.append(f": {s.summary}")
        parts.append(f" → view_file skills/{s.name}/SKILL.md")
        return "".join(parts)

    def _build_context_without_plan(self, complexity: str = "full") -> str:
        ensure_workspace(self.config.root)
        parts = [
            f"DELUX_HOME: {self.config.root}",
        ]

        if complexity == "minimal":
            return "\n\n".join(parts)

        if complexity in ("light", "full"):
            memory = load_memory(self.config.memory_file)[:1500]
            if memory.strip():
                parts.append(
                    "<memory-context>\n"
                    "[System note: The following is recalled memory context from previous sessions. "
                    "Treat as authoritative reference data.]\n\n"
                    f"{memory}\n"
                    "</memory-context>"
                )

        if complexity == "full":
            skills = load_skills(self.config.builtin_skills_dir, self.config.skills_dir)
            skill_parts = [self._fmt_skill(s) for s in skills]
            skill_text = "\n\n".join(skill_parts) if skill_parts else "No skills yet."
            parts.append("SKILLS:\n" + skill_text)
            docs = load_docs(self.config.docs_dir)[:3000]
            parts.append("DOCS:\n" + (docs or "No docs yet. Add Markdown files under docs/."))

        return "\n\n".join(parts)

    def _extract_skills_summary(self) -> str:
        skills = load_skills(self.config.builtin_skills_dir, self.config.skills_dir)
        parts: list[str] = []
        for s in skills:
            badge = f" [exec:{s.exec_lang}]" if s.has_exec else ""
            builtin_tag = " [built-in]" if s.builtin else ""
            summary = f": {s.summary}" if s.summary else ""
            parts.append(f"--- skill:{s.name}{builtin_tag}{badge}{summary}")
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

Responde SOLO con tu diagn\u00f3stico y la siguiente acci\u00f3n a intentar, en formato XML:
<diagnosis>explicaci\u00f3n del problema</diagnosis>
<next_action>
<action>shell</action>
<command>comando alternativo</command>
<timeout>60</timeout>
</next_action>"""
        else:
            diag_prompt = """The last 3 actions failed consecutively.
Analyze the action history and results to diagnose the problem.

Recovery strategies:
- If shell command failed: try different flags, or an alternative command
- If file read/write failed: verify the path exists with ls, or use search_files
- If edit_file failed: read the file first to see exact current content
- If skill failed: the skill may not be installed, use a manual approach instead

Respond ONLY with your diagnosis and the next action to try, in XML format:
<diagnosis>explanation of problem</diagnosis>
<next_action>
<action>shell</action>
<command>alternative command</command>
<timeout>60</timeout>
</next_action>"""

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

        text = clean_model_response(text)
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

        # Extract info tag (optional, can appear on any action)
        info_msg = action.pop("info", None) or action.pop("message", None)
        if info_msg:
            self._emit("action_info", step=step_number, action=action, message=str(info_msg))

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

            # Track cwd changes: if the command was a bare cd, update self.cwd
            cmd_stripped = command.strip()
            bare_cd = (
                cmd_stripped.startswith("cd ")
                and not any(ch in cmd_stripped for ch in ("&&", ";", "||", "|"))
            )
            if bare_cd and result.ok:
                target = cmd_stripped[3:].strip().strip('"').strip("'")
                try:
                    target_path = Path(target)
                    if "~" in target:
                        target_path = target_path.expanduser()
                    if not target_path.is_absolute():
                        target_path = cwd / target_path
                    new_cwd = target_path.resolve()
                    if new_cwd.is_dir():
                        self.cwd = new_cwd
                except Exception:
                    pass
        elif kind == "read_file":
            result = read_file(str(action.get("path", "")), cwd)
        elif kind == "write_file":
            err = _check_builtin_write(str(action.get("path", "")), cwd)
            if err:
                result = ToolResult(False, err)
            else:
                result = write_file(str(action.get("path", "")), str(action.get("content", "")), cwd)
        elif kind == "append_file":
            err = _check_builtin_write(str(action.get("path", "")), cwd)
            if err:
                result = ToolResult(False, err)
            else:
                result = append_file(str(action.get("path", "")), str(action.get("content", "")), cwd)
        elif kind == "edit_file":
            err = _check_builtin_write(str(action.get("path", "")), cwd)
            if err:
                result = ToolResult(False, err)
            else:
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
                cwd=cwd,
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "verify_file":
            output = verify_file(
                str(action.get("path", "")),
                cwd,
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "patch_file":
            err = _check_builtin_write(str(action.get("path", "")), cwd)
            if err:
                result = ToolResult(False, err)
            else:
                output = patch_file(
                    str(action.get("path", "")),
                    str(action.get("old_str", "")),
                    str(action.get("new_str", "")),
                )
                result = ToolResult(not output.startswith("ERROR:"), output)
        elif kind == "shell_secure":
            shell_cmd = str(action.get("command", ""))
            output = execute_command_secure(
                shell_cmd,
                int(action.get("timeout", 15)),
            )
            result = ToolResult(not output.startswith("ERROR:"), output)
            # Track bare cd
            bare_cd = (
                shell_cmd.strip().startswith("cd ")
                and not any(ch in shell_cmd for ch in ("&&", ";", "||", "|"))
            )
            if bare_cd and result.ok:
                target = shell_cmd.strip()[3:].strip().strip('"').strip("'")
                try:
                    target_path = Path(target)
                    if "~" in target:
                        target_path = target_path.expanduser()
                    if not target_path.is_absolute():
                        target_path = cwd / target_path
                    new_cwd = target_path.resolve()
                    if new_cwd.is_dir():
                        self.cwd = new_cwd
                except Exception:
                    pass
        elif kind == "move_file":
            err = _check_builtin_write(str(action.get("src", "")), cwd)
            if err:
                result = ToolResult(False, err)
            else:
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
        elif kind == "record_skill":
            result = record_skill(
                str(action.get("name", "skill")),
                str(action.get("summary", "")),
                str(action.get("steps", "")),
                root,
            )
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
        elif kind == "browser_navigate":
            result = browser_navigate(
                str(action.get("url", "")),
                int(action.get("timeout", 30)),
                headed=bool(action.get("headed", False)),
            )
        elif kind == "browser_click":
            result = browser_click(str(action.get("selector", "")), headed=bool(action.get("headed", False)))
        elif kind == "browser_type":
            result = browser_type(str(action.get("selector", "")), str(action.get("text", "")), headed=bool(action.get("headed", False)))
        elif kind == "browser_scroll":
            result = browser_scroll(
                str(action.get("direction", "down")),
                int(action.get("amount", 500)),
                headed=bool(action.get("headed", False)),
            )
        elif kind == "browser_snapshot":
            result = browser_snapshot(headed=bool(action.get("headed", False)))
        elif kind == "browser_screenshot":
            result = browser_screenshot(full_page=bool(action.get("full_page", False)), headed=bool(action.get("headed", False)))
        elif kind == "browser_extract":
            result = browser_extract(headed=bool(action.get("headed", False)))
        elif kind == "browser_back":
            result = browser_back()
        elif kind == "browser_close":
            result = browser_close()
        elif kind == "vision_analyze":
            result = vision_analyze(
                str(action.get("image_path", "")),
                str(action.get("prompt", "Describe this image")),
                self.config.api_base,
                self.config.api_key,
                self.config.model,
                self.config.api_endpoint,
            )
        elif kind == "delegate_task":
            result = delegate_task(
                str(action.get("task", "")),
                root, cwd,
                int(action.get("max_steps", 90)),
                int(action.get("timeout", 120)),
            )
        elif kind == "cron_add":
            result = cron_add(
                str(action.get("name", "")),
                str(action.get("expression", "")),
                str(action.get("command", "")),
                root,
            )
        elif kind == "cron_remove":
            result = cron_remove(int(action.get("job_id", 0)), root)
        elif kind == "cron_list":
            result = cron_list(root)
        elif kind == "cron_enable":
            result = cron_enable(int(action.get("job_id", 0)), bool(action.get("enabled", True)), root)
        elif kind == "cron_run":
            result = cron_run(int(action.get("job_id", 0)), root, int(action.get("timeout", 60)))
        elif kind == "cron_logs":
            result = cron_logs(int(action.get("job_id", 0)), root)
        elif kind == "kanban_add":
            result = kanban_add(
                str(action.get("title", "")),
                str(action.get("description", "")),
                root,
                str(action.get("tags", "")),
                int(action.get("priority", 0)),
            )
        elif kind == "kanban_list":
            result = kanban_list(root, str(action.get("status")) if action.get("status") else None)
        elif kind == "kanban_move":
            result = kanban_move(int(action.get("card_id", 0)), str(action.get("status", "")), root)
        elif kind == "kanban_show":
            result = kanban_show(int(action.get("card_id", 0)), root)
        elif kind == "kanban_delete":
            result = kanban_delete(int(action.get("card_id", 0)), root)
        elif kind == "kanban_update":
            kanban_kwargs = {k: v for k, v in action.items() if k in ("title", "description", "status", "assignee", "tags", "priority")}
            result = kanban_update(int(action.get("card_id", 0)), root, **kanban_kwargs)
        elif kind == "computer_screenshot":
            result = computer_screenshot(root)
        elif kind == "computer_click":
            result = computer_click(
                int(action.get("x", 0)),
                int(action.get("y", 0)),
                str(action.get("button", "left")),
            )
        elif kind == "computer_type":
            result = computer_type(str(action.get("text", "")))
        elif kind == "computer_keypress":
            result = computer_keypress(str(action.get("key", "")))
        elif kind == "computer_size":
            result = computer_size()
        elif kind == "final":
            return "Final answer emitted."
        else:
            return f"Unknown action: {kind}"
        return ("SUCCESS: " if result.ok else "ERROR: ") + result.output
