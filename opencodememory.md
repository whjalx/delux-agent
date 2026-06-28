# OpenCode Memory — Delux Agent (Full Context)

## Repository

- **GitHub**: https://github.com/whjalx/delux-agent
- **Remote**: origin → https://github.com/whjalx/delux-agent.git
- **Branch**: main (up to date with origin/main)
- **Recent commit**: `c69a31c` "cleanup: remove legacy IDE, update README, improve gitignore"
- **Prior commit**: `286b6d7` "initial: delux-agent merged from devices" — captures entire workspace as-is

---

## Project Overview

Shell-first AI assistant. Autonomous terminal agent with skills, memory, MCP support, and interactive Textual-based TUI.

- Language: Python 3.11+
- Dependencies: `rich>=13.0`, `textual>=8.0`
- Entry point: `delux_agent.cli:main`
- License: MIT

---

## Project Structure (all files)

```
/home/jcast/project/delux-agent/
├── pyproject.toml
├── setup.py
├── README.md
├── MANIFEST.in
├── install.sh
├── install.ps1
├── opencodememory.md                 ← THIS FILE
├── DELUX_CORE_ADN.md                 ← Agent design document
├── DELUX_PROJECT_MEMORY.md           ← Project-level memory
├── rehumanize_model.py               ← Model rehumanization
├── context_eval.py                   ← Context evaluation script
├── .gitignore
├── delux_agent/                      ★ MAIN PACKAGE ★
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                        # CLI entry point + arg parsing
│   ├── agent.py                      # Core agent loop (run_with_result)
│   ├── config.py                     # Config dataclass + loader + is_small_model()
│   ├── llm.py                        # LLM chat completion
│   ├── small_model.py                # Small model guidance prompts
│   ├── plan_executor.py              # PlanExecutor, AgentPlan, PlanStepStatus
│   ├── templates.py                  # Response parse strategies
│   ├── tools.py                      # Tool implementations
│   ├── store.py                      # Workspace store (skills, docs, memory)
│   ├── console.py                    # Rich console helpers
│   ├── i18n.py                       # Internationalization EN/ES
│   ├── dataset_rag.py                # Dataset RAG (BM25 on parquet)
│   ├── experience.py                 # Experience DB (task/solution storage)
│   ├── rag.py                        # RAG engine (BM25)
│   ├── system_info.py                # System info
│   ├── contextualizer.py             # Context optimizer
│   ├── mcp_client.py                 # MCP client
│   ├── mcp_store.py                  # MCP server/tools store
│   ├── indexer.py                    # Project indexer
│   ├── training.py                   # Training utilities
│   ├── assets/                       # Built-in assets
│   ├── gateway/
│   │   ├── __init__.py
│   │   └── gateway.py                # Telegram bot gateway
│   ├── tui/
│   │   ├── __init__.py
│   │   ├── app.py                    # Textual TUI (DeluxTUI class)
│   │   └── delux.tcss               # TUI stylesheet
│   ├── wizard/
│   │   └── wizard.py                 # Setup wizard
│   ├── training/
│   │   ├── contextualizer.py         # Contextualizer config
│   │   └── examples.py               # Few-shot examples
│   └── mcp/                          # MCP protocol
├── skills/                           # Built-in skills
├── completions/                      # Shell completions (bash, fish, zsh)
├── docs/                             # Documentation
├── dataset_glaive/                   # Training datasets (README only)
├── dataset_hermes/                   # Training datasets (README only)
├── dataset_multiturn/                # Training datasets (README only)
├── memory/                           # Obsidian vault (knowledge graph)
├── graphify-out/                     # Knowledge graph output
├── training/                         # Training artifacts
├── tests/                            # Tests
└── scripts/                          # Scripts (empty)
```

---

## What Was Removed (Legacy IDE)

Files deleted in commit `c69a31c`:
- `delux_agent/ide.py` (top-level, 97KB, 2320 lines)
- `delux_agent/ide/__init__.py`
- `delux_agent/ide/ide.py` (99KB, 2379 lines — richer Rich-based DeluxIDE)
- `delux_agent/ide/sidebar.py` (5KB, 179 lines)
- `delux_agent/sidebar.py` (top-level, 7KB, 232 lines)

All legacy IDE references removed from `cli.py` (the `--legacy` flag, `DeluxIDE` fallback).

---

## Config (config.py)

### Config Dataclass Fields

```python
@dataclass(frozen=True)
class Config:
    root: Path
    memory_file: Path
    skills_dir: Path
    docs_dir: Path
    sessions_dir: Path
    testing_dir: Path
    shell: str
    provider: str
    api_base: str
    api_endpoint: str | None
    api_key: str | None
    model: str
    request_timeout: int
    models: list[ModelEntry]
    validator_*: configs
    embedding_*: configs
    lang: str = "en"
    response_template: str = "auto"
    small_model: bool = False
    cache_chunk_size: int = 0
    plan_model: str = ""
    plan_provider: str = ""
    plan_api_base: str = ""
    plan_api_key: str = ""
    plan_api_endpoint: str = ""
    ctx_model: str = ""
    ctx_provider: str = ""
    ctx_api_base: str = ""
    ctx_api_key: str = ""
    ctx_api_endpoint: str = ""
```

### Effective Plan/Ctx Properties

```python
@properties:
    effective_plan_model -> plan_model or model
    effective_plan_provider, api_base, api_key, api_endpoint
    effective_ctx_model, provider, api_base, api_key, api_endpoint
```

### Env Var Overrides

```bash
DELUX_MODEL, DELUX_API_KEY, DELUX_API_BASE, DELUX_API_ENDPOINT
DELUX_PROVIDER, DELUX_SHELL, DELUX_TIMEOUT, DELUX_LANG, DELUX_HOME
DELUX_PLAN_MODEL, DELUX_PLAN_PROVIDER, DELUX_PLAN_API_BASE, DELUX_PLAN_API_KEY
DELUX_CTX_MODEL, DELUX_CTX_PROVIDER, DELUX_CTX_API_BASE, DELUX_CTX_API_KEY
DELUX_EMBEDDING_MODEL, DELUX_EMBEDDING_API_BASE, DELUX_EMBEDDING_API_KEY
DELUX_CACHE_CHUNK_SIZE
```

### Small Model Detection (config.py:190-197)

```python
_SMALL_MODEL_PATTERNS = [
    r'\b3b\b', r'\b1b\b', r'\b2b\b', r'\b4b\b',
    r'\bsmall\b', r'\btiny\b',
    r'\bphi-[0-3]\b', r'\bphi3\b',
    r'\bqwen2-0\.5', r'\bqwen2-1\.[35]', r'\bqwen2-2\b', r'\bqwen2-3b\b', r'\bqwen2-4b\b',
    r'\bgemma-2b\b', r'\bgemma-3b\b', r'\bgemma-4b\b',
    r'\bllama-3\.2-1b\b', r'\bllama-3\.2-3b\b',
]
```

Uses regex `re.search()` with `\b` word boundaries. Does NOT match:
- `gemma-7b`, `gemma-27b` (only gemma-{2,3,4}b)
- `qwen2-7b`, `qwen2-72b` (only qwen2-{0.5,1.x,2,3,4}b)
- `phi-4` (only phi-[0-3], phi3)
- `llama-3.2-11b` (only llama-3.2-{1,3}b)
- `qwen2-7b` doesn't match because "72b" contains "2b" but `\b2b\b` doesn't match "72b" due to word boundary

### Config Loading (config.py:129-185)

`load_config(cwd)` reads `delux.config.json` from `DELUX_HOME` env or `~/.delux/`.

---

## Agent (agent.py) — Complete Reference

### Agent Dataclass

```python
@dataclass
class Agent:
    config: Config
    cwd: Path
    transcript: list[AgentEvent] = field(default_factory=list)
    event_handler: AgentEventHandler | None = None
    max_steps: int = 12
    ephemeral: bool = False
    plan: object = None               # AgentPlan instance
    run_counter: int = 1
    plan_executor: object = None      # PlanExecutor instance
    contextualizer: object = None
    rag_engine: RAGEngine | None = None
    experience_db: ExperienceDB | None = None
    _cached_full_system: str | None = None
    _cached_base_context: str | None = None
    _rag_ds: DatasetRAG | None = None  # cached DatasetRAG instance
```

### run_with_result() — Full Flow

1. **Config validation**: If no API key and provider requires one, return error immediately
2. **Language detection**: `self.config.lang`
3. **Build system prompt**:
   - `system_prompt = _get_system_prompt(lang)` (EN or ES)
   - If small_mode: `system_prompt += "\n\n" + build_small_model_prompt(lang)` (short hints)
   - `full_system = system_prompt + action_format + few_shot + mcp_tools`
   - If template has system_suffix: use `system_prompt + t.system_suffix + few_shot + mcp_tools`
4. **Initialize PlanExecutor**: `PlanExecutor(self.plan, self.run_counter)`
5. **Build base_context**: `_build_context_without_plan()` — skills, docs (small: 200 lines, normal: 3000), memory (small: 100, normal: 1500)
6. **KV Cache warmup** (if `cache_chunk_size > 0`, small_mode, local provider, first run, prompt <= 5 words):
   - `_warmup_cache()` → sends one request with full system + base_context, max_tokens=1, timeout=10s
7. **Build dynamic context** (every turn):
   - `exp_context`: `ExperienceDB.find_similar(prompt, top_k=2)`
   - `dataset_few_shot`: `DatasetRAG.search(prompt, top_k=2)` → `format_few_shot()` (cached in `self._rag_ds`)
8. **Contextualizer** (if enabled): Translate prompt to English, run contextualizer, use optimized prompt
9. **Build messages** (cache-friendly order):
   ```python
   messages = [
       {"role": "system", "content": full_system + dataset_few_shot},
       {"role": "user", "content": base_context},
   ]
   # CACHE BOUNDARY — everything below changes per turn
   if exp_context:
       messages.append({"role": "user", "content": exp_context})
   if session_context:
       messages.extend(session_context)
   messages.append({"role": "user", "content": optimized_prompt})
   ```
10. **Step loop** (1 to max_steps):
    - Get current plan step from PlanExecutor
    - If plan step active: inject step instruction into last user message
    - Call `chat_completion(messages, stream=False)`
    - Parse action with `_parse_action()` (uses template strategies)
    - If `_plain_text`: retry with JSON correction (up to 2 times)
    - Handle `skip_step` action
    - Block `final` if plan in progress and not complete
    - Emit `action_started` event
    - Dedup: if model repeats same successful action, auto-finalize
    - Dispatch action via `_dispatch(action)`
    - Emit `action_finished` event
    - Record plan step status
    - If `final`: emit `final_answer`, return result
    - If error: increment consecutive_errors, add error reflection
    - If 3+ consecutive errors: force new approach message
    - If 4+ errors: run `_diagnose_failure()`
    - If success: append assistant + user messages to messages list
    - If ephemeral: rebuild messages from scratch each step
11. **Max steps reached**: Force plan completion warning, return summary

### _parse_action(text) -> dict

```python
template = get_model_template(model, root)
preferred = template.preferred_strategy if template.preferred_strategy != "auto" else None
parsed, strategy = parse_action(text, preferred_strategy=preferred)
if preferred is None and strategy != "plain_text":
    record_successful_strategy(model, strategy, root)
action = {"action": parsed.action}
action.update(parsed.params)
return action
```

### _dispatch(action, step_number) -> str (SUCCESS: / ERROR:)

Handles: shell, read_file, write_file, append_file, edit_file, view_file, verify_file, patch_file, shell_secure, move_file, search_files, rag_query, rag_index, create_skill, run_skill, remember, search_web, save_experience, load_experience, call_mcp, final

### _warmup_cache() — Single Request

```python
chat_completion(api_base, api_key, model, [
    {"role": "system", "content": full_system},
    {"role": "user", "content": base_context},
], endpoint, timeout=10, max_tokens=1)
```

Emits: `cache_warming(part=1, total=1)`, then `cache_warmed(chunks=1)` or `cache_warmed(chunks=0, error=...)`.

### Event Emitter

```python
def _emit(self, event: str, **payload: object) -> None:
    if self.event_handler:
        self.event_handler(event, payload)
```

### Events Emitted by Agent

| Event | When | Payload |
|-------|------|---------|
| `token` | Each token chunk from LLM | `content: str` |
| `action_started` | Before dispatching action | `step, action, plan_step` |
| `shell_output` | Shell command output chunk | `step, action, chunk` |
| `action_finished` | After dispatch | `step, action, result, plan_step` |
| `final_answer` | Final action emitted | `step, action, answer` |
| `plan_step_active` | Plan step about to execute | `step_id, step_desc, progress` |
| `plan_step_matched` | Step ID identified | `step_id, step_desc` |
| `plan_step_skipped` | Model used skip_step | `step_id, reason, progress` |
| `plan_step_status` | Step completed/failed | `step_id, ok, progress` |
| `plan_completed` | All steps done | `summary` |
| `plan_final_blocked` | Model tried final early | `step_id` |
| `plan_max_steps_reached` | Max steps with incomplete plan | `summary` |
| `contextualizer_starting` | Context optimization begins | — |
| `contextualizer_finished` | Context optimization done | `savings, changes` |
| `cache_warming` | KV cache warmup chunk | `part, total` |
| `cache_warmed` | KV cache warmup done | `chunks, error` |

---

## LLM (llm.py)

### chat_completion()

```python
def chat_completion(
    api_base: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, str]],
    api_endpoint: str | None = None,
    timeout: int = 180,
    stream: bool = False,
    on_chunk=None,
    max_tokens: int | None = None,
) -> LLMResponse:
```

Returns `LLMResponse(text=str, raw=dict, provider=str)`.

### Google Gemini Detection

If `api_base == "google"` or URL has `generativelanguage.googleapis.com`:
- Maps OpenAI messages → Google format
- System message → `system_instruction`
- Other messages → `contents` with `user`/`model` roles
- Uses v1beta API
- `generationConfig`: `maxOutputTokens`, `temperature: 0.2`

### Streaming Behavior

If `stream=True`:
1. Sends SSE request via `_do_request()`
2. `_stream_with_timeout()` reads SSE lines in daemon thread
3. Parses `data: {...}` lines with `choices[0].delta.content`
4. `[DONE]` signal ends stream
5. If stream times out (thread.join timeout = max(timeout, 30)): fallback to non-streaming

**Currently**: All agent calls use `stream=False`. Streaming was disabled because:
- TUI doesn't display tokens in real-time
- SSE parser could hang on Ollama responses
- No consumer handles `token` events for display

### SSE Parsing

`_parse_sse_line(line: str) -> tuple[str, bool]`
- Lines starting with `"data: "` → parse JSON
- Extract `choices[0].delta.content` (handles empty content, missing keys)
- `[DONE]` line → done=True
- Non-SSE lines → `("", False)`

---

## TUI (tui/app.py) — Complete Reference

### DeluxTUI(App)

The main (and only) interactive interface. Textual-based.

### Class State

```python
_streaming: bool = False
_splash_shown: bool = False
_config: Config
_cwd: Path
_max_steps: int = 12
_model_name: str
_provider: str
_answer_count: int = 0
_total_tokens: int = 0
_plan_mode: bool = False
_ask_mode: bool = True
_ephemeral: bool = False
_validate_mode: str = "off"
_prompt_history: list[str] = []
_lang: str
_i18n: I18n
_active_model_idx: int = 0
_validator_model_idx: int | None = None
_buffer: str = ""
_action_lines: int = 0
_answer_written: bool = False
_start_time: float = 0.0
_small_model_tip_lines: list[str] = []
```

### Layout (compose)
```
Header (clock)
├── Container#app-grid
│   ├── Container#chat-container
│   │   └── RichLog#chat-log
│   ├── Vertical#sidebar
│   │   ├── "Información"
│   │   ├── "Modelo" / Label#sidebar-model
│   │   ├── "Proveedor" / Label#sidebar-provider
│   │   ├── "Plan Model" / Label#sidebar-plan-model
│   │   ├── "Tokens" / Label#sidebar-tokens
│   │   ├── "Tiempo" / Label#sidebar-time
│   │   ├── "Pasos" / Label#sidebar-steps
│   │   ├── "Directorio" / Label#sidebar-cwd
│   │   ├── "Modos" / Label#sidebar-modes
│   │   └── "Estado" / Label#sidebar-status
│   └── Container#input-row
│       ├── Static#mode-indicator (PLAN/BUILD)
│       └── Input#prompt-input
└── Footer
```

### Lifecycle

`on_mount()`:
1. `_show_splash()` — Panel with "Delux" ASCII art + welcome
2. `_show_small_model_tip()` — if small_model detected: show tips (Ollama keep_alive, llama.cpp cache flags, warmup activation)
3. `_update_mode_indicator()` — sidebar + indicator

### Input Handling

`on_input_submitted(event)`:
1. If `_streaming`: return (ignore)
2. Clear input, append to history
3. Write user prompt to chat
4. Set `_streaming = True`, disable input, set status "Pensando..."
5. Call `_stream_response(text)` via `@work(exclusive=True, thread=True)`

### _stream_response(prompt) — Worker Thread

```python
@work(exclusive=True, thread=True)
def _stream_response(self, prompt: str):
    reset buffer, action_lines, answer_written
    build run_config (from active model)
    IF _plan_mode:
        write "Creating plan..."
        plan_obj = _create_plan(prompt, run_config)
    ELSE:
        plan_obj = None
    agent = Agent(config=run_config, plan=plan_obj, run_counter=answer_count+1, ...)
    write "Pensando..."
    result = agent.run_with_result(prompt, verbose=False)
    call_from_thread(_on_agent_done, result, elapsed)
```

### _create_plan(prompt, run_config) → AgentPlan | None

1. Import `build_planner_prompt`, `AgentPlan`, `PlanStepStatus` from `plan_executor`
2. Get `effective_plan_model`, `effective_plan_api_base`, `effective_plan_api_key`, `effective_plan_api_endpoint`
3. Call LLM with planner prompt
4. Parse JSON response
5. If `questions`: show to user, return None (execute directly)
6. If `steps`: create AgentPlan, write plan summary to chat, return plan
7. On error: log error, return None

### _on_agent_event(event, payload)

**Token handler**: Append to `_buffer`
**Action handlers**: `action_started` (shell/write/edit/read/search/skill/final), `shell_output`, `action_finished`
**Plan handlers**:
- `plan_step_active`: `📋 [progress] Step N: desc` (bold magenta)
- `plan_step_matched`: `→ Step: desc` (dim)
- `plan_step_skipped`: `⏭ Step N skipped (reason) [progress]` (yellow)
- `plan_step_status`: `✅/❌ Step N [progress]` (green/red)
- `plan_completed`: `✅ Plan completed!` + summary (bold green)
- `plan_final_blocked`: `⚠ Final blocked (plan not complete)` (yellow)
- `plan_max_steps_reached`: `⚠ Max steps reached` + summary (red)
**Cache handlers**: `cache_warming` (🧠 KV cache: part/total), `cache_warmed` (✅/⚠)
**Context handlers**: `contextualizer_starting` (dim), `contextualizer_finished` (dim)
**Final handler**: `final_answer` → set `_buffer = answer`

### _on_agent_done(result, elapsed)

1. Write `_buffer` as Markdown (if answer not written)
2. Write `result.answer` as Markdown (if answer not written)
3. Update sidebar: tokens, steps (answer_count), time
4. Set `_streaming = False`, status "Listo", re-enable input

### _on_agent_error(error)

Write error, set `_streaming = False`, status "Error", re-enable input

### _sidebar_modes() → str

Composed parts: PLAN/BUILD, `[yellow]small[/]`, ask, ephem, val:N

### _update_mode_indicator()

Updates `#mode-indicator` (PLAN green bold / BUILD dim) and `#sidebar-modes`

### Commands Handled

`/help`, `/plan [on|off]`, `/validate [on|off|once]`, `/ephemeral [on|off]`, `/ask [on|off]`, `/quit`, `/clear`, `/status`, `/context`, `/memory`, `/skills`, `/docs`, `/config`, `/sessions`, `/history`, `/pwd`, `/cd`, `/new-skill`, `/save`, `/lang`, `/model`, `/vm`, `/sidebar`, `/ctx`, `/index`, `/mcp`, `/template`, `/finetune`, `/train`

### Bindings

- `Ctrl+Space` → `action_toggle_plan()`
- `Ctrl+C` → `action_cancel_stream()`
- `Ctrl+L` → `action_clear()`
- `Ctrl+Q` → quit

### Plan Toggle Feedback

`action_toggle_plan()` and `/plan` write "Plan mode: ON/OFF (modelo: name)" to chat.

### Small Model Startup Tip

```python
if is_small_model(model) or config.small_model:
    provider = provider.lower()
    cache_tips = {
        "ollama": "Ollama: OLLAMA_KEEP_ALIVE=24h mantiene el modelo en RAM",
        "lmstudio": "LM Studio: caché KV automática mientras el servidor corre",
    }
    Show: 💡 Small Model Detected
    Tip: Send 'hi' or 'hola' first to warm up KV cache.
    Provider-specific tip (if ollama/lmstudio)
    llama.cpp: --cache-type-k q8_0 --cache-type-v q8_0
    Activar warmup: DELUX_CACHE_CHUNK_SIZE=512
```

---

## Plan Executor (plan_executor.py) — Complete Reference

### Data Types

```python
@dataclass
class PlanStepStatus:
    id: int
    description: str
    detail: str = ""
    status: str = "pending"  # pending | running | done | failed | skipped

@dataclass
class PlanExecution:
    exec_id: str          # "plan1", "plan2"
    prompt: str
    summary: str
    steps: list[PlanStepStatus]
    current_idx: int = 0
    in_progress: bool = True
    # Methods: next_step(), mark_done(), mark_skipped(), step_by_id()
    #          is_complete(), progress_str(), build_step_instruction()
    #          build_completion_message(), step_summary()

@dataclass
class AgentPlan:
    prompt: str = ""
    steps: list = field(default_factory=list)
    summary: str = ""
    active_step: int = 0
    # NOTE: compact_context() does NOT exist in this class
    # agent.py checks hasattr(self.plan, "compact_context") before calling

class PlanExecutor:
    def __init__(self, plan: AgentPlan | None, exec_counter: int)
    # Properties: in_progress, plan_complete
    # Methods: get_current_step(), build_instruction_for_step(), record_done()
    #          record_skip(), can_finalize(), finalize_summary(), progress_str()
```

### build_step_instruction(step) → str

Generates the "PLAN IN PROGRESS" banner with:
- Current step description and specifics
- Progress (N/M)
- Completed steps list
- Remaining steps count
- Action required instructions
- `skip_step` JSON example
- "Do NOT use final until ALL steps are done/skipped"

### build_planner_prompt(prompt, system_context, history, lang) → str

Two formats:
- **EN**: "You are Delux's planner (READ-ONLY mode)..."
- **ES**: "Eres el planificador de Delux (MODO SOLO LECTURA)..."

Output Option A: `{"summary": "...", "steps": [{"description": "...", "detail": "..."}]}`
Output Option B: `{"type": "questions", "questions": [{"text": "...", "options": ["..."]}]}`

---

## Small Model (small_model.py)

### EN Hints
```
--- SMALL MODEL HINTS ---
Keep responses short and focused. Prefer simple shell commands over complex multi-step plans.
If stuck after 2 errors, try a different approach or search_web.
For simple questions (greetings, info), respond with final directly.
```

### ES Hints
```
--- AYUDA PARA MODELO PEQUEÑO ---
Responde breve y directo. Prefiere comandos shell simples sobre planes complejos.
Si fallas 2 veces seguidas, cambia de enfoque o busca en internet.
Para cosas simples (saludos, info), responde con final directamente.
```

---

## Gateway (gateway/gateway.py) — Complete Reference

### TelegramConfig

```python
@dataclass
class TelegramConfig:
    token: str
    chat_ids: list[str]
    @classmethod def load() -> TelegramConfig | None
```

Reads from `~/.delux/telegram.json`:
```json
{"token": "BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}
```

### Key Functions

- `escape_html(text)` — &, <, > escaping
- `escape_markdown(text)` — backslash escaping
- `send_message(token, chat_id, text)` — plain text (escaped, no parse_mode)
- `send_html(token, chat_id, html_text)` — HTML parse_mode
- `send_chunked_html(token, chat_id, text)` — splits at 4000 chars
- `send_chunked_plain(token, chat_id, text)` — same, plain
- `edit_message(), edit_html(), delete_message(), send_action()`
- `build_inline_keyboard(buttons)` — inline keyboard markup

### GatewaySession

```python
@dataclass
class GatewaySession:
    chat_id: str
    history: list[dict] = field(default_factory=list)
    last_message_id: int | None = None
    status_message_id: int | None = None
    def add_turn(user, assistant)  # max 10 turns history
```

### GatewayEventHandler

```python
class GatewayEventHandler:
    def __init__(self, token, chat_id, session)
    def set_cancel_flag(ev)
    def _status(text, edit=True)  # sends/edits status message
    def __call__(self, event, payload)  # main event handler
```

Handles: `action_started` (shell/write/edit/read/verify/run_skill/search_web/rag/final with emoji), `action_finished` (ERROR notification, write/edit/patch success notification), `final_answer` (chunked HTML result + log), `plan_step_active` (📋 progress), `contextualizer_starting` (🧠)

### _process_prompt(tg, chat_id, text)

**Fixed implementation**:
1. Get `cancel_ev` and `session`
2. Send "Processing..." message
3. Load config using `DELUX_HOME` env or `~/.delux` (NOT `load_config(None)`)
4. Build `session_ctx` from session history (last 3 turns)
5. Create `Agent` with event_handler = GatewayEventHandler
6. Run agent in thread: `result_container = []; result_container.append(agent.run_with_result(text, session_context=...).answer)`
7. Wait with 1s polling, typing indicator every 5s, "still running" warning at 120s
8. On done: `session.add_turn(text, answer)`
9. On error: log + send error to chat
10. Finally: unregister task

**IMPORTANT**: Uses `run_with_result()` with `session_context` (not `run()` without context).

### run_gateway(config_path, poll_interval, single_run) → int

Main loop: long-polling `getUpdates` with 30s timeout.
Handles commands: `/start`, `/help`, `/status`, `/reset`, `/retry`, `/stats`, `/cancel`
Routes text messages to `_process_prompt()`.

### Defines

```python
TELEGRAM_CONFIG_PATH = "~/.delux/telegram.json"
MAX_MESSAGE_LENGTH = 4000
MAX_RETRIES = 5
BASE_RETRY_DELAY = 1.0
```

---

## CLI (cli.py) — Complete Entry Point

### Subcommand Routing

```python
if argv[0] == "gateway":    → run_gateway()
if argv[0] == "ide":        → DeluxTUI (Textual, no fallback)
if argv[0] == "setup":      → run_setup()
if argv[0] == "install-skills" → install default skills
if args.init:               → ensure workspace
if args.context:            → print context
if args.new_skill:          → create skill
if args.prompt:             → one-shot Agent.run()
else (no prompt):           → DeluxTUI.run()
```

### _cli_event_handler (for one-shot mode)

CLI-specific event handler. Prints action lines with icons. Handles: `action_started` (shell, write_file, etc.), `shell_output` (truncated), `action_finished` (success/error), `final_answer`.

### Config loading

```python
root = Path(args.home) if args.home else None
config = load_config(root)  # root=None → default_root() → ~/.delux or DELUX_HOME
ensure_workspace(config.root)
```

---

## Wizard (wizard/wizard.py) — Setup Flow

### run_setup(root) → int

1. `ensure_workspace(root)`
2. Show menu with configured models
3. Options: Add model, Set active, Remove model, Configure MCP, Configure Plan model, Configure Dynamic Intelligence, View config
4. On exit: `_import_dataset_rag(root)`, show context summary

### Provider Presets

```python
PRESETS = [
    ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"),
    ProviderPreset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4.1-mini"),
    ProviderPreset("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ProviderPreset("lmstudio", "LM Studio local", "http://localhost:1234/v1", "local-model", False),
    ProviderPreset("ollama", "Ollama local", "http://localhost:11434/v1", "llama3.1", False),
    ProviderPreset("google", "Google Gemini", "google", "gemini-1.5-flash"),
    ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
]
```

### Small Model Detection in Wizard

After `_add_model_to_config()`:
```python
from ..config import is_small_model as _detect_small
if _detect_small(values.get("model", "")):
    print(f"Small model detected ({values['model']}). Enabling optimizations.")
    _update_config_file(root, {"small_model": True})
elif _yes_no("Is this a small/limited model (3B, 4B, Phi, Gemma, Tiny)?", False):
    _update_config_file(root, {"small_model": True})
```

### Dataset RAG Import (optimized)

```python
def _import_dataset_rag(root):
    # Check if dataset parquet files exist in project root
    ds_paths = [
        project_root / "dataset_hermes/data/kimi/train.parquet",
        project_root / "dataset_hermes/data/glm-5.1/train.parquet",
        project_root / "dataset_multiturn/data/train-00000-of-00001.parquet",
    ]
    if not any(p.exists()): return
    # NEW: Check if RAG already has data
    ds = DatasetRAG(root)
    if ds.manifest: return  # skip if already imported
    # Import each parquet
    # ...
```

---

## Templates (templates.py)

### Parse Strategies

- `direct_json` — Try JSON.parse directly
- `markdown_json` — Extract JSON from ```json blocks
- `regex_json` — Use regex to find JSON object
- `no_action_wrap` — Handle responses without wrapping
- `plain_text` — Last resort, treat as plain text

### Action Format Instructions

Generated by `get_action_format_instructions(model, root)` — shows the model what actions are available and their JSON format.

### Model Templates

Per-model parse templates stored at `~/.delux/templates.json`.
`get_model_template()` reads this file, falls back to defaults.
`set_template()` saves to the file.

---

## Tools (tools.py)

All tool functions return `ToolResult(ok: bool, output: str)`.

| Tool | Function | Key Behavior |
|------|----------|--------------|
| shell | `run_shell(cmd, cwd, shell, timeout, stream_callback)` | Wraps in sh -c, has timeout |
| shell_secure | `execute_command_secure(cmd, timeout)` | 15s default timeout |
| read_file | `read_file(path, cwd)` | 30KB cap |
| view_file | `view_file_paged(path, start, end, cwd)` | Range of lines |
| write_file | `write_file(path, content, cwd)` | Creates parent dirs |
| append_file | `append_file(path, content, cwd)` | Appends to file |
| edit_file | `edit_file(path, old, new, cwd, replace_all)` | Exact string replace |
| patch_file | `patch_file(path, old, new)` | For skill files in DELUX_HOME |
| move_file | `move_file(src, dst, cwd)` | shutil.move |
| search_files | `search_files(query, cwd)` | Recursive grep |
| verify_file | `verify_file(path, cwd)` | Syntax check by extension |
| search_web | `search_web(query, top_k)` | DuckDuckGo |
| remember | `remember(note, root)` | Appends to memory.md |
| run_skill | `run_skill(slug, args, root, cwd, timeout)` | Reads SKILL.md, runs exec |
| create_skill | `create_skill(name, summary, body, root)` | Creates SKILL.md in skills dir |
| call_mcp | `call_mcp_tool(server, tool, arguments, root, timeout)` | MCP tool call |

---

## Dataset RAG (dataset_rag.py)

- `DatasetRAG(root)` class — BM25-based search over agent trajectory parquet files
- Sources: `SOURCE_HERMES_KIMI`, `SOURCE_HERMES_GLM`, `SOURCE_MULTITURN`
- Manifest stored at `{root}/dataset_rag/manifest.json`
- `search(query, top_k)` → returns formatted few-shot examples
- Cached in `Agent._rag_ds` (created once per Agent instance)

---

## Experience DB (experience.py)

- `ExperienceDB(root)` — JSON-based persistent task/solution store
- `find_similar(task, top_k)` → BM25 keyword matching
- `add(task, solution, steps, tags, verified)` → saves new experience
- Stored at `{root}/experience/`

---

## RAG Engine (rag.py)

- `RAGEngine(db_path)` — BM25 search over indexed project files
- `index_directory(path, recursive)` → chunks files
- `query(query, top_k)` → returns ranked results
- Stored at `{root}/rag/`

---

## Contextualizer (training/contextualizer.py)

- `Contextualizer(config, ctx_config)` — optimizes context for efficiency
- `contextualize(user_prompt, memory, skills, docs, plan_context)` → optimized prompt + savings_pct
- Dataset generation for prefix caching
- Configurable dataset size (50/100/300/500/1000 examples)

---

## i18n (i18n.py)

- `I18n(lang)` class with `.t(key)` method
- JSON-based translations at `delux_agent/assets/locales/`
- Languages: EN, ES

---

## Store (store.py)

- `load_skills(dir)` → `[Skill(name, summary, has_exec, exec_lang)]`
- `load_docs(dir)` → concatenated markdown content from docs dir
- `load_memory(path)` → content from memory.md
- `ensure_workspace(root)` → creates all required directories
- `save_session_markdown(dir, title, body)` → saves to sessions/
- `upsert_skill(filepath, slug, summary)` → updates skill definition

---

## Pyproject.toml — IMPORTANT NOTES

```toml
[project]
dependencies = [
    "rich>=13.0",
    "textual>=8.0"
]

[project.urls]  # ← dependencies MUST be BEFORE this
```

**BUG FIXED**: `dependencies` MUST come before `[project.urls]`. If after, TOML parsers nest `dependencies` under `urls`, causing install failure with "project.urls.dependencies must be string".

---

## .gitignore

```
__pycache__/  *.pyc  *.pyo
.venv/  venv/  *.egg-info/  .eggs/
dist/  build/
node_modules/  package-lock.json
go/pkg/mod/  go.sum
*.gguf  *.safetensors  *.bin  *.wav  *.parquet  *.zip  *.tar.gz
.gradle/  .DS_Store  Thumbs.db  .vscode/  .idea/
*.log  logs/  logs_gemini/  logs_google_ai/
.cache/  .pytest_cache/  .graphify-cache/
*.so  *.jar
graphify-out/  memory/
dataset_glaive/data/  dataset_hermes/data/  dataset_multiturn/data/
training/dataset_apply/
perfil_chrome_mlbb/  server/worlds/  .cmake/
```

---

## Config File Location

`~/.delux/delux.config.json`

```json
{
  "provider": "openai",
  "model": "gpt-4.1-mini",
  "api_key": "...",
  "small_model": true,
  "cache_chunk_size": 512,
  "plan_model": "",
  "lang": "en",
  "request_timeout": 180
}
```

---

## Shell Completions

- `completions/delux.fish` → Fish shell
- `completions/delux.bash` → Bash
- `completions/_delux` → Zsh
- Auto-installed by `install.sh`

---

## Skills (built-in)

Located at `/home/jcast/project/delux-agent/skills/`:
- delux-browser — Playwright browser automation
- delux-code-stats — Code statistics
- delux-codex — Code analysis/generation/refactoring
- delux-dataset-rag — Dataset RAG queries
- delux-disk-benchmark — Disk performance testing
- delux-fast-tree — Fast directory tree
- delux-gateway — Telegram bridge wrapper
- delux-git-summary — Git repository summary
- delux-judge — Self-validation
- delux-net-check — Network connectivity check
- delux-obsidian-brain — Technical knowledge persistence
- delux-opencode — OpenCode delegation
- delux-oracle — Knowledge retrieval
- delux-quick-search — Quick file search
- delux-rag — Project RAG
- delux-reasoning — Step-by-step reasoning
- delux-search-expert — Advanced search
- delux-sys-health — System health check
- delux-telegram-notify — One-way Telegram notifications
- delux-writer-pro — Long-form writing

Each skill has SKILL.md with documentation, and optionally exec.py.

---

## MCP (Model Context Protocol)

- `mcp_store.py` — `MCPServerEntry`, `add/remove/toggle/discover/cache_tools`
- `mcp_client.py` — `MCPClient` with connect/call_tool/list_tools
- Config: `~/.delux/mcp_servers.json`, `~/.delux/mcp_tools.json`
- Action: `{"action":"call_mcp","server":"name","tool":"tool_name","arguments":{}}`

---

## Training

- `training/examples.py` — `FEW_SHOT_EXAMPLES` (injected into system prompt)
- `training/contextualizer.py` — Context optimizer with dataset generation
- Dataset import from parquet files (hermes, multiturn) via `dataset_rag.py`

---

## Known Issues & Fixes Applied

### 1. Legacy IDE removed
- Deleted `delux_agent/ide.py` (top-level) + `delux_agent/ide/` directory + `delux_agent/sidebar.py`
- Only TUI remains as interactive interface
- CLI no longer falls back to DeluxIDE

### 2. Streaming disabled (was causing hangs)
- `agent.py` now uses `stream=False` instead of `stream=True`
- SSE parser (`_stream_with_timeout`) could hang on Ollama responses
- TUI doesn't display tokens in real-time, so streaming provides no benefit
- Gateway and CLI also don't benefit from streaming

### 3. Small model extra prompt was harmful
- Old version: ~800+ tokens repeating tool descriptions + "Do NOT give up" persistence
- Conflicted with system prompt, made models execute commands even on "hola"
- New version: ~60 tokens, 3 short lines of helpful hints
- No tool repetition, no aggressive persistence

### 4. Dataset RAG examples were in wrong role
- Old: `dataset_few_shot` moved to user message (model interpreted examples as user commands)
- Fixed: appended to system message content only (model sees them as system instructions)

### 5. Dataset RAG redundant imports
- `wizard.py:_import_dataset_rag()` now checks `ds.manifest` before importing
- Skips if RAG already has data

### 6. Pyproject.toml dependencies position
- `dependencies` must be before `[project.urls]` section
- Fixed in current version

### 7. Gateway thread result capture
- Replaced fragile `setattr(threading.current_thread(), "_result", ...)` with `result_container: list[str]`
- Now uses `agent.run_with_result()` with `session_context` instead of `agent.run()`

### 8. Session context in gateway
- Passes last 3 turns of conversation history as `session_context` to Agent
- Enables KV cache prefix reuse across turns

### 9. Small model auto-detection for 7B+ models
- Old: `"2b" in "qwen2-72b"` was True (substring match)
- Old: `"gemma"` matched all Gemma models (2B, 7B, 27B)
- Fixed: regex with `\b` word boundaries for all patterns

### 10. Config loading in gateway
- Old: `load_config(None)` resolves differently than explicit path
- Fixed: `Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))`

### 11. Toggle plan button
- `action_toggle_plan()` now shows plan model info in chat

### 12. Cache fields added to Agent
- `_cached_full_system`, `_cached_base_context`, `_rag_ds` for performance

### 13. OpenCodeMemory created
- This file! Contains full project context for new OpenCode sessions.

---

## Testing

- No formal test framework detected
- Syntax verification: `python3 -c "import ast; ast.parse(open('file.py').read())"`
- Import verification: `python3 -c "from delux_agent.module import Class"`
- Install verification: `pip install -e .`
