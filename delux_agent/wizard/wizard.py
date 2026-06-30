from __future__ import annotations

import getpass
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..config import load_config, write_config
from ..llm import LLMError, chat_completion
from ..store import ensure_workspace, load_docs, load_memory, load_skills
from ..training.contextualizer import load_ctx_config, save_ctx_config
from ..training.examples import FEW_SHOT_EXAMPLES


GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
RED = "\033[31m"


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label: str
    api_base: str
    default_model: str
    needs_key: bool = True
    note: str = ""


PRESETS = [
    ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"),
    ProviderPreset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4.1-mini"),
    ProviderPreset("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ProviderPreset(
        "opencode-zen",
        "OpenCode Zen",
        "https://opencode.ai/zen/v1",
        "big-pickle",
        True,
        "OpenCode Zen - tested & verified models. Sign in at https://opencode.ai/zen. Endpoint: https://opencode.ai/zen/v1/chat/completions",
    ),
    ProviderPreset(
        "opencode-go",
        "OpenCode Go",
        "https://opencode.ai/zen/go/v1",
        "qwen3.6-plus",
        True,
        "OpenCode Go - low cost subscription. Endpoint: https://opencode.ai/zen/go/v1/chat/completions",
    ),
    ProviderPreset(
        "lmstudio",
        "LM Studio local",
        "http://localhost:1234/v1",
        "local-model",
        False,
        "Endpoint used: http://localhost:1234/v1/chat/completions",
    ),
    ProviderPreset(
        "ollama",
        "Ollama OpenAI-compatible local",
        "http://localhost:11434/v1",
        "llama3.1",
        False,
        "Endpoint used: http://localhost:11434/v1/chat/completions. Start with `ollama serve`.",
    ),
    ProviderPreset(
        "google",
        "Google Gemini",
        "google",
        "gemini-1.5-flash",
        True,
        "Requires a Google AI Studio API Key. Using native Generative AI API.",
    ),
    ProviderPreset(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com/v1",
        "deepseek-chat",
        True,
        "DeepSeek API key required. Models: deepseek-chat, deepseek-reasoner.",
    ),
    ProviderPreset(
        "ddg-proxy",
        "DDG-AI Proxy (free local)",
        "http://localhost:8765/v1",
        "gpt-4o-mini",
        False,
        "Free OpenAI-compatible API via DuckDuckGo AI Chat (duck.ai). "
        "Uses Playwright + Chromium. Start: delux ddg-proxy",
    ),
]


MCP_PRESETS = [
    ("filesystem", "File System", "npx", ["-y", "@modelcontextprotocol/server-filesystem"]),
    ("github", "GitHub", "npx", ["-y", "@modelcontextprotocol/server-github"]),
    ("sqlite", "SQLite", "uvx", ["mcp-server-sqlite"]),
    ("fetch", "Web Fetch", "uvx", ["mcp-server-fetch"]),
]


def _ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    full_prompt = f"{prompt}{suffix}: "
    if secret:
        value = getpass.getpass(full_prompt).strip()
    else:
        value = input(full_prompt).strip()
    return value or (default or "")


def _ask_int(prompt: str, default: int) -> int:
    value = _ask(prompt, str(default))
    try:
        return int(value)
    except ValueError:
        print(f"  {RED}Invalid number `{value}`. Using {default}.{RESET}")
        return default


def _yes_no(prompt: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    answer = _ask(f"{prompt} ({default_text})", "").lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "si", "s\u00ed"}


def _ensure_v1(url: str) -> str:
    value = url.strip().rstrip("/")
    if value.endswith("/v1"):
        return value
    return value + "/v1"


def _endpoint(values: dict[str, str | None]) -> str:
    if values.get("api_endpoint"):
        return str(values["api_endpoint"])
    return str(values.get("api_base", "")).rstrip("/") + "/chat/completions"


def _load_existing_config_values(root: Path) -> dict:
    config_file = root / "delux.config.json"
    if not config_file.exists():
        return {"models": []}
    try:
        existing = load_config(root)
        return {
            "provider": existing.provider,
            "api_base": existing.api_base,
            "api_endpoint": existing.api_endpoint,
            "api_key": existing.api_key or "",
            "model": existing.model,
            "request_timeout": existing.request_timeout,
            "models": [
                {
                    "name": m.name,
                    "provider": m.provider,
                    "api_base": m.api_base,
                    "api_endpoint": m.api_endpoint,
                    "api_key": m.api_key,
                }
                for m in existing.models
            ],
        }
    except Exception:
        return {"models": []}


# ── Provider-specific model collectors ───────────────────────────────────────

def _get_google_models(api_key: str) -> list[str]:
    print("  Fetching available Google models (v1beta)...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                name = m.get("name", "").replace("models/", "")
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    models.append(name)
            return sorted(models)
    except Exception as e:
        print(f"  {RED}Failed to fetch models: {e}{RESET}")
        return []


def _configure_provider_model(existing: dict, preset: ProviderPreset | None) -> dict | None:
    """Interactively configure a single provider/model. Returns values dict or None."""
    if preset:
        default_base = existing.get("api_base", preset.api_base) if existing.get("provider") == preset.key else preset.api_base
        default_model = existing.get("model", preset.default_model) if existing.get("provider") == preset.key else preset.default_model
        default_key = existing.get("api_key", "")
        default_timeout = existing.get("request_timeout", 180)
    else:
        default_base = existing.get("api_base", "https://api.example.com")
        default_model = existing.get("model", "custom-model")
        default_key = existing.get("api_key", "")
        default_timeout = existing.get("request_timeout", 180)

    if preset and preset.note:
        print(f"  {DIM}{preset.note}{RESET}")

    if preset and preset.key == "google":
        api_key = _ask("  Google API key", default_key, secret=True)
        available_models = _get_google_models(api_key)
        if available_models:
            print("\n  Available models:")
            for i, m in enumerate(available_models, 1):
                print(f"    {i}. {m}")
            m_choice = _ask_int("  Choose model", 1)
            model = available_models[m_choice - 1] if 1 <= m_choice <= len(available_models) else available_models[0]
        else:
            model = _ask("  Model", default_model)
        api_base = "google"
        api_endpoint = None
    elif preset and preset.key == "deepseek":
        api_key = _ask("  DeepSeek API key", default_key, secret=True)
        print("\n  Available models:")
        print("    1. deepseek-chat (V3 \u2014 general purpose, recommended)")
        print("    2. deepseek-reasoner (R1 \u2014 reasoning/chain-of-thought)")
        m_choice = _ask_int("  Choose model", 1)
        model = "deepseek-chat" if m_choice == 1 else "deepseek-reasoner"
        api_base = _ensure_v1("https://api.deepseek.com")
        api_endpoint = None
    elif preset:
        api_base = _ask("  API base URL", default_base)
        model = _ask("  Model", default_model)
        api_key = _ask("  API key", default_key, secret=True) if preset.needs_key else _ask("  API key (optional)", default_key, secret=True)
        api_endpoint = None
    else:
        api_type = _ask("  API type", "openai")
        base = _ask("  Base URL without endpoint", default_base)
        api_base = _ensure_v1(base) if api_type.lower() in {"openai", "openai-compatible", "openai compatible"} else base.rstrip("/")
        model = _ask("  Model", default_model)
        api_key = _ask("  API key", "", secret=True)
        api_endpoint = None

    timeout = _ask_int("  Request timeout (seconds)", default_timeout)

    return {
        "provider": preset.key if preset else "custom",
        "api_base": api_base.rstrip("/") if api_base else api_base,
        "api_endpoint": api_endpoint,
        "api_key": api_key or None,
        "model": model,
        "request_timeout": timeout,
    }


def _configure_custom_endpoint(existing: dict) -> dict | None:
    default_key = existing.get("api_key", "")
    default_timeout = existing.get("request_timeout", 180)
    endpoint = _ask("  Full endpoint URL", "https://api.example.com/v1/chat/completions")
    model = _ask("  Model", "custom-model")
    api_key = _ask("  API key", default_key, secret=True)
    timeout = _ask_int("  Request timeout (seconds)", default_timeout)
    return {
        "provider": "full_custom",
        "api_base": "",
        "api_endpoint": endpoint,
        "api_key": api_key or None,
        "model": model,
        "request_timeout": timeout,
    }


def _test_model(values: dict[str, str | int | None]) -> bool:
    endpoint = str(values.get("api_endpoint") or "")
    base = str(values.get("api_base") or "")
    timeout = int(values.get("request_timeout") or 180)
    print("")
    print("  Testing model with prompt: hola")
    print(f"  Endpoint: {endpoint or base.rstrip('/') + '/chat/completions'}")
    print(f"  Timeout: {timeout}s")
    try:
        response = chat_completion(
            base,
            values.get("api_key") if isinstance(values.get("api_key"), str) else None,
            str(values.get("model")),
            [{"role": "user", "content": "hola"}],
            endpoint or None,
            timeout,
        )
    except LLMError as exc:
        print(f"  {RED}Test failed.{RESET}")
        print(f"  Reason: {exc}")
        print(f"  {YELLOW}Model, URL or API key might be incorrect.{RESET}")
        return False
    print("  Test response:")
    print(f"  {response.text.strip()}")
    return True


# ── MCP Server Management ────────────────────────────────────────────────────

def _setup_mcp_servers(root: Path) -> None:
    from ..mcp.store import add_mcp_server, MCPServerEntry

    print("")
    print("  Available MCP servers:")
    for i, (key, label, cmd, args) in enumerate(MCP_PRESETS, 1):
        print(f"    {i}. {label} ({key})")
    print(f"    {len(MCP_PRESETS) + 1}. Custom")
    print(f"    0. Done")

    while True:
        choice = _ask("  Add MCP server (number, or 0 to finish)", "0")
        try:
            choice_num = int(choice)
        except ValueError:
            break

        if choice_num == 0:
            break
        elif 1 <= choice_num <= len(MCP_PRESETS):
            key, label, cmd, args = MCP_PRESETS[choice_num - 1]
            print(f"\n  {label} MCP Server")
            print("  " + "-" * 30)

            extra_args = _ask("  Extra arguments (space-separated)", "")
            full_args = args + (extra_args.split() if extra_args else [])

            if key == "filesystem":
                default_path = str(Path.home())
                path = _ask("  Root directory to allow access", default_path)
                if path:
                    full_args.append(path)

            entry = MCPServerEntry(name=key, command=cmd, args=full_args, description=label)
            add_mcp_server(root, entry)
            print(f"  {GREEN}Added: {key}{RESET}")
        elif choice_num == len(MCP_PRESETS) + 1:
            name = _ask("  Server name", "myserver")
            command = _ask("  Command", "npx")
            args_str = _ask("  Arguments (space-separated)", "")
            args_list = args_str.split() if args_str else []
            desc = _ask("  Description", "")
            entry = MCPServerEntry(name=name, command=command, args=args_list, description=desc)
            add_mcp_server(root, entry)
            print(f"  {GREEN}Added: {name}{RESET}")
        else:
            print(f"  {RED}Invalid choice.{RESET}")


def _print_provider_menu() -> None:
    print("  Providers:")
    for i, preset in enumerate(PRESETS, 1):
        print(f"    {i}. {preset.label} ({preset.key})")
    print(f"    {len(PRESETS) + 1}. Custom (OpenAI-compatible)")
    print(f"    {len(PRESETS) + 2}. Full custom endpoint")


# ── Training/Contextualizer Setup ────────────────────────────────────────────

def _setup_contextualizer(root: Path) -> None:
    print("\n  Dynamic Intelligence Setup")
    print("  " + "-" * 30)

    cfg = load_ctx_config(root)
    cfg.enabled = _yes_no("  Enable Contextualizer", True)

    if cfg.enabled:
        print("\n  Select Training Dataset Size (examples for prefix caching):")
        print("    1. 50 examples  (Lightweight)")
        print("    2. 100 examples (Balanced)")
        print("    3. 300 examples (Expert - Recommended for GPU)")
        print("    4. 500 examples (Ultra)")
        print("    5. 1000 examples (Maximum - Needs 32k context)")

        size_choice = _ask("  Choose size", "3")
        size_map = {"1": 50, "2": 100, "3": 300, "4": 500, "5": 1000}
        cfg.dataset_size = size_map.get(size_choice, 300)

        _generate_training_dataset(root, cfg.dataset_size)
        print(f"  {GREEN}Generated dataset with {cfg.dataset_size} examples.{RESET}")

    _install_default_skills(root)
    print(f"  {GREEN}Installed default delux-* skills at {root}/skills/.{RESET}")

    _install_skill_template(root)
    print(f"  {GREEN}Installed SKILL_TEMPLATE.md at {root}/skills/.{RESET}")

    _generate_few_shot_examples(root)
    print(f"  {GREEN}Generated few-shot examples for prompt injection.{RESET}")

    save_ctx_config(root, cfg)
    print(f"  {GREEN}Saved Contextualizer configuration.{RESET}")


def _generate_training_dataset(root: Path, size: int) -> None:
    import random
    training_dir = root / "training"
    training_dir.mkdir(parents=True, exist_ok=True)

    dataset_path = training_dir / "training_examples.md"
    real_dataset_jsonl = training_dir / "dataset.jsonl"

    real_cases = []
    if real_dataset_jsonl.exists():
        try:
            with open(real_dataset_jsonl, 'r') as f:
                for line in f:
                    if line.strip():
                        real_cases.append(json.loads(line))
        except:
            pass

    with open(dataset_path, 'w') as f:
        f.write(f'# Delux Training Dataset ({size} Examples)\n\n')

        if real_cases:
            f.write('## REAL WORLD CASES\n')
            for i, case in enumerate(real_cases):
                user_msg = next((m['content'] for m in case['messages'] if m['role'] == 'user'), "Hello")
                assistant_actions = [m['content'] for m in case['messages'] if m['role'] == 'assistant']
                f.write(f'### Real Case {i+1}\nUSER: \"{user_msg}\"\n')
                for action in assistant_actions:
                    f.write(f'ACTION: {action}\n')
                f.write('\n')

    library_path = root / "training" / "expert_library.json"

    if not library_path.exists():
        print(f"  {GREEN}First time setup: Loading expert knowledge from built-in assets...{RESET}")
        assets_path = Path(__file__).resolve().parent.parent.parent / "delux_agent" / "assets" / "training_library.json"
        if assets_path.exists():
            import shutil
            library_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(assets_path, library_path)
        else:
            _build_base_library(library_path)

    expert_cases = []
    try:
        with open(library_path, 'r', encoding='utf-8') as lib_f:
            expert_cases = json.load(lib_f)
    except:
        pass

    needed = size - len(real_cases)
    selected_experts = expert_cases[:needed]

    with open(dataset_path, 'a') as f:
        for i, case in enumerate(selected_experts):
            idx = len(real_cases) + i + 1
            f.write(f'### Expert Case {idx}\nUSER: \"{case["user"]}\"\nACTION: {case["assistant"]}\n\n')


def _generate_few_shot_examples(root: Path) -> None:
    examples_dir = root / "training"
    examples_dir.mkdir(parents=True, exist_ok=True)
    path = examples_dir / "few_shot_examples.md"
    path.write_text(FEW_SHOT_EXAMPLES, encoding="utf-8")
    print(f"  {GREEN}Wrote few-shot examples to {path}{RESET}")


def _install_default_skills(root: Path) -> None:
    skills_dir = root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    import delux_agent
    dest = skills_dir / "SKILL_TEMPLATE.md"
    if not dest.exists():
        src = Path(delux_agent.__file__).parent / "skills" / "SKILL_TEMPLATE.md"
        if src.exists():
            import shutil
            shutil.copy2(str(src), str(dest))
            print(f"  {GREEN}Installed SKILL_TEMPLATE.md{RESET}")
    print(f"  {GREEN}Built-in skills loaded from package ({delux_agent.__version__}){RESET}")


def _install_skill_template(root: Path) -> None:
    skills_dir = root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    import delux_agent
    template_src = Path(delux_agent.__file__).parent / "skills" / "SKILL_TEMPLATE.md"
    template_dst = skills_dir / "SKILL_TEMPLATE.md"
    if template_src.exists() and not template_dst.exists():
        import shutil
        shutil.copy2(str(template_src), str(template_dst))


def _build_base_library(target_path: Path) -> None:
    import random
    scenarios = [
        {'q': 'Scan subnet {subnet} for open SSH ports.', 'a': '<action>shell</action>\n<command>nmap -p 22 {subnet}</command>\n<timeout>60</timeout>'},
        {'q': 'Fix permissions in {dir} for .env files.', 'a': '<action>shell</action>\n<command>find {dir} -name ".env" -exec chmod 600 {} \;</command>\n<timeout>30</timeout>'},
        {'q': 'Check Docker containers with status "exited".', 'a': '<action>shell</action>\n<command>docker ps -a -f status=exited</command>\n<timeout>30</timeout>'},
        {'q': 'Search for {error} in system logs today.', 'a': '<action>shell</action>\n<command>journalctl --since today | grep -i {error}</command>\n<timeout>30</timeout>'},
        {'q': 'Create backup of {dir} excluding node_modules.', 'a': '<action>shell</action>\n<command>tar --exclude="node_modules" -czf backup.tar.gz {dir}</command>\n<timeout>120</timeout>'},
        {'q': 'Send Telegram alert: Service {service} is down.', 'a': '<action>run_skill</action>\n<skill>delux-telegram-notify</skill>\n<args>CRITICAL: {service} is DOWN</args>\n<timeout>30</timeout>'},
        {'q': 'Analyze {file} for undocumented functions.', 'a': '<action>run_skill</action>\n<skill>delux-writer-pro</skill>\n<args>--path {file} --analyze docs</args>\n<timeout>60</timeout>'},
        {'q': 'Reason through this: {problem}. Break it down step by step.', 'a': '<action>run_skill</action>\n<skill>delux-reasoning</skill>\n<args>{problem}</args>\n<timeout>120</timeout>'},
        {'q': 'Review the code in {file} for bugs and improvements.', 'a': '<action>run_skill</action>\n<skill>delux-codex</skill>\n<args>{file}</args>\n<timeout>60</timeout>'},
        {'q': 'Look up what we know about {topic} across all sources.', 'a': '<action>run_skill</action>\n<skill>delux-oracle</skill>\n<args>{topic}</args>\n<timeout>60</timeout>'},
        {'q': 'Validate our work before finishing. Check the last actions.', 'a': '<action>run_skill</action>\n<skill>delux-judge</skill>\n<args>...</args>\n<timeout>30</timeout>'},
        {'q': 'Kill process on port {port}.', 'a': '<action>shell</action>\n<command>lsof -ti:{port} | xargs -r kill -9</command>\n<timeout>30</timeout>'},
        {'q': 'Find the largest files in {dir}.', 'a': '<action>shell</action>\n<command>du -sh {dir}/* 2>/dev/null | sort -rh | head -10</command>\n<timeout>30</timeout>'},
        {'q': 'Check disk usage and warn if over {pct}%.', 'a': '<action>shell</action>\n<command>df -h | awk \'NR>1 {if ($5+0 > {pct}) print "WARNING: " $6 " at " $5}\'</command>\n<timeout>30</timeout>'},
    ]

    subnets = ['192.168.1.0/24', '10.0.0.0/8', '172.16.0.0/12']
    dirs = ['/var/www', '/opt/app', '/etc/nginx']
    errors = ['Panic', 'Segfault', 'Timeout', 'OOM', 'DiskFull']
    services = ['nginx', 'postgresql', 'ssh', 'docker', 'redis']
    files = ['main.py', 'app.js', 'utils.go', 'config.json']
    ports = ['3000', '8080', '5432', '80', '443']
    pcts = ['80', '90', '95']
    problems = ['server is slow', 'deployment failed', 'api returns 500', 'memory leak']

    library = []
    for i in range(1000):
        s = random.choice(scenarios)
        q, a = s['q'], s['a']
        params = {'{subnet}': random.choice(subnets), '{dir}': random.choice(dirs), '{error}': random.choice(errors), '{service}': random.choice(services), '{file}': random.choice(files), '{port}': random.choice(ports), '{pct}': random.choice(pcts), '{problem}': random.choice(problems)}
        for k, v in params.items():
            q, a = q.replace(k, v), a.replace(k, v)
        library.append({'user': q, 'assistant': a})

    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(library, f, indent=2, ensure_ascii=False)


# ── Config Merge Helpers ─────────────────────────────────────────────────────

def _update_config_file(root: Path, updates: dict) -> dict:
    """Read existing config, merge updates, write back. Returns final data dict."""
    config_path = root / "delux.config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    data.update(updates)
    write_config(root, data)
    return data


def _add_model_to_config(root: Path, model_values: dict) -> None:
    """Add a model entry to the models list, keeping existing models."""
    models_entry = {
        "name": model_values["model"],
        "provider": model_values.get("provider", ""),
        "api_base": model_values.get("api_base", ""),
        "api_endpoint": model_values.get("api_endpoint"),
        "api_key": model_values.get("api_key"),
    }

    config_path = root / "delux.config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    models_list = data.get("models", [])
    # Check if a model with the same name already exists — update it
    found = False
    for i, m in enumerate(models_list):
        if isinstance(m, dict) and m.get("name") == model_values["model"]:
            models_list[i] = models_entry
            found = True
            print(f"  {YELLOW}Updated existing model: {model_values['model']}{RESET}")
            break
    if not found:
        models_list.append(models_entry)
        print(f"  {GREEN}Added model: {model_values['model']}{RESET}")

    data["models"] = models_list

    # Set as active model if this is the first one
    if not data.get("model"):
        data["model"] = model_values["model"]
        data["provider"] = model_values.get("provider", "")
        data["api_base"] = model_values.get("api_base", "")

    write_config(root, data)


def _set_active_model(root: Path, model_name: str) -> None:
    """Set the active model by name, looking it up in the models list."""
    config_path = root / "delux.config.json"
    if not config_path.exists():
        print(f"  {RED}No config file found.{RESET}")
        return

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"  {RED}Could not read config.{RESET}")
        return

    models = data.get("models", [])
    for m in models:
        if isinstance(m, dict) and m.get("name") == model_name:
            data["model"] = m["name"]
            data["provider"] = m.get("provider", data.get("provider", ""))
            data["api_base"] = m.get("api_base", data.get("api_base", ""))
            data["api_endpoint"] = m.get("api_endpoint", data.get("api_endpoint"))
            data["api_key"] = m.get("api_key", data.get("api_key"))
            write_config(root, data)
            print(f"  {GREEN}Active model set to: {model_name}{RESET}")
            return

    print(f"  {RED}Model '{model_name}' not found in models list.{RESET}")


def _remove_model_from_config(root: Path, model_name: str) -> None:
    """Remove a model from the models list."""
    config_path = root / "delux.config.json"
    if not config_path.exists():
        print(f"  {RED}No config file found.{RESET}")
        return

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"  {RED}Could not read config.{RESET}")
        return

    models = data.get("models", [])
    new_models = [m for m in models if not (isinstance(m, dict) and m.get("name") == model_name)]
    if len(new_models) == len(models):
        print(f"  {RED}Model '{model_name}' not found.{RESET}")
        return

    data["models"] = new_models
    write_config(root, data)
    print(f"  {GREEN}Removed model: {model_name}{RESET}")

    # If active model was removed, switch to first available
    if data.get("model") == model_name and new_models:
        first = new_models[0]
        data["model"] = first.get("name", "")
        data["provider"] = first.get("provider", "")
        write_config(root, data)
        print(f"  {YELLOW}Active model switched to: {first.get('name')}{RESET}")


# ── Config Viewer ────────────────────────────────────────────────────────────

def _print_context(root: Path) -> None:
    config = load_config(root)
    skills = load_skills(config.builtin_skills_dir, config.skills_dir)
    print("")
    print("  Final context")
    print("  " + "=" * 30)
    print(f"  Home: {config.root}")
    print(f"  Config: {config.root / 'delux.config.json'}")
    print(f"  Memory: {config.memory_file}")
    print(f"  Skills: {config.skills_dir}")
    print(f"  Docs: {config.docs_dir}")
    print(f"  Active Provider: {config.provider}")
    print(f"  Active Model: {config.model}")
    ep = config.api_endpoint or config.api_base.rstrip("/") + "/chat/completions"
    print(f"  Endpoint: {ep}")
    print(f"  Timeout: {config.request_timeout}s")
    print("")
    print("  Configured models:")
    if config.models:
        for m in config.models:
            active = f" {GREEN}\u27a4 ACTIVE{RESET}" if m.name == config.model else ""
            print(f"    - {YELLOW}{m.name}{RESET} ({m.provider}){active}")
    else:
        print(f"    {DIM}none{RESET}")
    print("")
    print("  Skills loaded:")
    if skills:
        for skill in skills:
            print(f"    - {skill.name}: {skill.summary}")
    else:
        print(f"    {DIM}none{RESET}")
    print("")
    print("  Memory preview:")
    print(f"  {load_memory(config.memory_file)[:600].strip()}")
    print("")
    print("  Docs loaded:")
    docs = load_docs(config.docs_dir)
    print(f"  {docs[:600].strip() if docs else 'No docs loaded.'}")


def _ensure_playwright(root: Path) -> None:
    try:
        import playwright  # noqa: F401
        return
    except ImportError:
        pass
    if not _yes_no("  Playwright no instalado. ¿Instalar ahora (pip install playwright>=1.40)?", True):
        print(f"  {YELLOW}DDG-AI Proxy requiere Playwright. Ejecuta después: pip install 'playwright>=1.40'{RESET}")
        return
    import subprocess, sys
    print("  Instalando Playwright...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "playwright>=1.40"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        print(f"  {RED}Error instalando Playwright: {exc}{RESET}")
        return
    print("  Instalando Chromium...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        print(f"  {RED}Error instalando Chromium: {exc}{RESET}")
        print(f"  {YELLOW}Ejecuta después: python -m playwright install chromium{RESET}")
        return
    print(f"  {GREEN}Playwright + Chromium instalados.{RESET}")


def _configure_plan_model(root: Path) -> None:
    print("\n  Plan Mode Model Configuration")
    print("  " + "-" * 30)
    if _yes_no("  Use same model as main", True):
        return
    print("")
    _print_provider_menu()
    pchoice = _ask("  Choose provider for Plan mode", "1")
    try:
        pnum = int(pchoice)
    except ValueError:
        print(f"  {RED}Invalid choice.{RESET}")
        return
    if pnum == len(PRESETS) + 3:
        return
    elif 1 <= pnum <= len(PRESETS):
        values = _configure_provider_model({}, PRESETS[pnum - 1])
    elif pnum == len(PRESETS) + 1:
        values = _configure_provider_model({}, None)
    elif pnum == len(PRESETS) + 2:
        values = _configure_custom_endpoint({})
    else:
        return
    if values:
        is_ddg_proxy = 1 <= pnum <= len(PRESETS) and PRESETS[pnum - 1].key == "ddg-proxy"
        _update_config_file(root, {
            "plan_model": values.get("model", ""),
            "plan_provider": values.get("provider", ""),
            "plan_api_base": values.get("api_base", ""),
            "plan_api_key": values.get("api_key", ""),
            "plan_free": is_ddg_proxy,
        })
        if is_ddg_proxy:
            _ensure_playwright(root)
        print(f"  {GREEN}Plan mode model configured.{RESET}")


# Git LFS auto-install commands per platform
# (detector_binary, install_command)
_GIT_LFS_INSTALL: list[tuple[str, str]] = [
    ("dnf", "sudo dnf install -y git-lfs"),
    ("apt-get", "sudo apt-get install -y git-lfs"),
    ("apt", "sudo apt-get install -y git-lfs"),
    ("pacman", "sudo pacman -S --noconfirm git-lfs"),
    ("zypper", "sudo zypper install -y git-lfs"),
    ("brew", "brew install git-lfs"),
]


def _import_dataset_rag(root: Path) -> None:
    project_root = Path(__file__).resolve().parent.parent.parent

    # Pre-built RAG file
    prebuilt = project_root / "rag-raw" / "dataset-rag.jsonl.gz"

    # Check if RAG already has data to avoid redundant imports
    try:
        from ..dataset_rag import DatasetRAG
        ds = DatasetRAG(root)
        if ds.manifest:
            print(f"  {DIM}Dataset RAG already imported.{RESET}")
            return
    except Exception:
        pass

    if prebuilt.exists():
        import shutil, gzip, json

        # Validate the file is a real gzip (not a git-lfs pointer)
        real_gzip = False
        try:
            with open(prebuilt, "rb") as f:
                magic = f.read(2)
                real_gzip = (magic == b'\x1f\x8b')
        except Exception:
            pass

        if not real_gzip:
            # Auto-install git-lfs and pull the dataset
            import subprocess, shutil
            lfs_ok = False
            try:
                subprocess.run(["git", "lfs", "version"], capture_output=True, text=True, timeout=10)
                lfs_ok = True
            except FileNotFoundError:
                print(f"  {YELLOW}git-lfs not found. Installing...{RESET}")
                for detector, install_cmd in _GIT_LFS_INSTALL:
                    if shutil.which(detector):
                        try:
                            subprocess.run(install_cmd, shell=True, capture_output=True, text=True, timeout=60)
                            break
                        except Exception:
                            continue
                try:
                    subprocess.run(["git", "lfs", "version"], capture_output=True, text=True, timeout=10)
                    lfs_ok = True
                except FileNotFoundError:
                    print(f"  {YELLOW}Could not install git-lfs automatically. Install it manually: "
                          f"https://git-lfs.com{RESET}")

            if lfs_ok and prebuilt.stat().st_size < 1000:  # still a pointer (<1KB)
                print(f"  {YELLOW}Downloading RAG dataset (251 MB via git-lfs)...{RESET}")
                result = subprocess.run(
                    ["git", "lfs", "pull", "--include", "rag-raw/dataset-rag.jsonl.gz"],
                    cwd=project_root, capture_output=True, text=True, timeout=600,
                )
                if result.returncode != 0:
                    print(f"  {YELLOW}git-lfs pull failed: {result.stderr.strip()[:200]}{RESET}")
                else:
                    with open(prebuilt, "rb") as f:
                        magic = f.read(2)
                        real_gzip = (magic == b'\x1f\x8b')
                    if not real_gzip:
                        print(f"  {YELLOW}File still not a valid gzip after pull (size: {prebuilt.stat().st_size} bytes).{RESET}")

        if prebuilt.stat().st_size < 1000:
            print(f"  {DIM}RAG dataset not available. Install git-lfs and run: "
                  f"cd {project_root} && git lfs pull{RESET}")
            print(f"  {DIM}Or skip dataset RAG (agent will run without few-shot examples).{RESET}")
        elif real_gzip:
            print(f"  {YELLOW}Installing pre-built trajectory RAG...{RESET}")
            try:
                dst = root / "dataset-rag"
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(prebuilt), str(dst / "entries.jsonl.gz"))
                with gzip.open(prebuilt, "rb") as f:
                    count = sum(1 for _ in f)
                (dst / "manifest.json").write_text(json.dumps({"prebuilt": count}, ensure_ascii=False), encoding="utf-8")
                print(f"  {GREEN}Installed {count} pre-built trajectories.{RESET}")
            except Exception as exc:
                print(f"  {YELLOW}Pre-built RAG install failed: {exc}{RESET}")
        else:
            print(f"  {DIM}RAG dataset not available (git-lfs pull failed or no gzip file).{RESET}")
        return

    ds_paths = [
        (project_root / "dataset_hermes" / "data" / "kimi" / "train.parquet"),
        (project_root / "dataset_hermes" / "data" / "glm-5.1" / "train.parquet"),
        (project_root / "dataset_multiturn" / "data" / "train-00000-of-00001.parquet"),
    ]
    if not any(p.exists() for p in ds_paths):
        print(f"  {DIM}No dataset files found for RAG import.{RESET}")
        return

    print(f"\n  {YELLOW}Importing agent trajectory datasets into local RAG...{RESET}")
    try:
        from ..dataset_rag import DatasetRAG
        ds = DatasetRAG(root)
        total = 0
        for p in ds_paths:
            if p.exists():
                source = DatasetRAG.SOURCE_HERMES_KIMI if "kimi" in p.name else \
                        DatasetRAG.SOURCE_HERMES_GLM if "glm" in p.name else \
                        DatasetRAG.SOURCE_MULTITURN
                n = ds.import_hermes_parquet(str(p), source)
                total += n
        if total:
            print(f"  {GREEN}Imported {total} agent trajectories.{RESET}")
        else:
            print(f"  {DIM}Dataset RAG already up to date.{RESET}")
    except Exception as exc:
        print(f"  {YELLOW}Dataset import skipped: {exc}{RESET}")


# ── Main Setup Entry Point ───────────────────────────────────────────────────

def run_setup(root: Path) -> int:
    print(f"\n  {BOLD}{GREEN}Delux Setup{RESET}")
    print(f"  {DIM}Home: {root}{RESET}")
    print(f"  {'=' * 40}")

    ensure_workspace(root)
    existing = _load_existing_config_values(root)

    while True:
        models = existing.get("models", [])
        active_model = existing.get("model", "")

        print(f"\n  {BOLD}Configuration Menu{RESET}")
        print(f"  {'-' * 40}")

        if models:
            print(f"  Configured models:")
            for i, m in enumerate(models):
                name = m.get("name", "?")
                prov = m.get("provider", "")
                active = f" {GREEN}\u27a4 ACTIVE{RESET}" if name == active_model else ""
                print(f"    {i+1}. {YELLOW}{name}{RESET} ({prov}){active}")
        else:
            print(f"  {DIM}No models configured yet.{RESET}")

        print("")
        print(f"    a. {BOLD}Add a new provider/model{RESET}")
        if models:
            print(f"    s. Set active model")
            print(f"    r. Remove a model")
        print(f"    m. Configure MCP servers")
        print(f"    p. Configure Plan Mode model (different from main)")
        print(f"    t. Configure Dynamic Intelligence (Training)")
        print(f"    v. View current configuration")
        print(f"    q. Exit")

        choice = _ask("  Choice", "q").lower()

        if choice == "q" or choice == "exit":
            _import_dataset_rag(root)
            print(f"\n  {GREEN}Setup complete.{RESET}")
            _print_context(root)
            print("")
            print(f"  Run: delux \"di hola y ejecuta pwd\"")
            return 0

        elif choice == "a":
            print("")
            _print_provider_menu()
            print(f"    {len(PRESETS) + 3}. Back to menu")

            pchoice = _ask("  Choose provider", "1")
            try:
                pnum = int(pchoice)
            except ValueError:
                print(f"  {RED}Invalid choice.{RESET}")
                continue

            if pnum == len(PRESETS) + 3:
                continue
            elif 1 <= pnum <= len(PRESETS):
                preset = PRESETS[pnum - 1]
                values = _configure_provider_model(existing, preset)
            elif pnum == len(PRESETS) + 1:
                values = _configure_provider_model(existing, None)
            elif pnum == len(PRESETS) + 2:
                values = _configure_custom_endpoint(existing)
            else:
                print(f"  {RED}Invalid choice.{RESET}")
                continue

            if values:
                _add_model_to_config(root, values)
                from ..config import is_small_model as _detect_small
                if _detect_small(values.get("model", "")):
                    print(f"  {YELLOW}Small model detected ({values['model']}). Enabling optimizations.{RESET}")
                    _update_config_file(root, {"small_model": True})
                elif _yes_no("  Is this a small/limited model (3B, 4B, Phi, Gemma, Tiny)?", False):
                    _update_config_file(root, {"small_model": True})
                if _yes_no("  Test this model now", True):
                    _test_model(values)
                # Reload existing config
                existing = _load_existing_config_values(root)

        elif choice == "s" and models:
            print("")
            for i, m in enumerate(models):
                name = m.get("name", "?")
                prov = m.get("provider", "")
                active = f" {GREEN}\u27a4{RESET}" if name == active_model else ""
                print(f"    {i+1}. {active} {YELLOW}{name}{RESET} ({prov})")
            midx = _ask_int("  Select model", 1)
            if 1 <= midx <= len(models):
                _set_active_model(root, models[midx - 1].get("name", ""))
                existing = _load_existing_config_values(root)

        elif choice == "r" and models:
            print("")
            for i, m in enumerate(models):
                name = m.get("name", "?")
                print(f"    {i+1}. {YELLOW}{name}{RESET}")
            midx = _ask_int("  Select model to remove", 1)
            if 1 <= midx <= len(models):
                _remove_model_from_config(root, models[midx - 1].get("name", ""))
                existing = _load_existing_config_values(root)

        elif choice == "m":
            _setup_mcp_servers(root)

        elif choice == "p":
            _configure_plan_model(root)
            existing = _load_existing_config_values(root)

        elif choice == "t":
            _setup_contextualizer(root)

        elif choice == "v":
            _print_context(root)

        else:
            print(f"  {RED}Invalid choice.{RESET}")
