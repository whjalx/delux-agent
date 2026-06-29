from __future__ import annotations

import getpass
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import load_config, write_config
from .llm import LLMError, chat_completion
from .store import ensure_workspace, load_docs, load_memory, load_skills
from .contextualizer import load_ctx_config, save_ctx_config


GREEN = "\033[32m"
RESET = "\033[0m"


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
        print(f"Invalid number `{value}`. Using {default}.")
        return default


def _ensure_v1(url: str) -> str:
    value = url.strip().rstrip("/")
    if value.endswith("/v1"):
        return value
    return value + "/v1"


def _print_provider_menu() -> None:
    print("Providers:")
    for index, preset in enumerate(PRESETS, start=1):
        print(f"  {index}. {preset.label} ({preset.key})")
    print(f"  {len(PRESETS) + 1}. Custom")
    print(f"  {len(PRESETS) + 2}. Full custom endpoint")


def _yes_no(prompt: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    answer = _ask(f"{prompt} ({default_text})", "").lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "si", "sí"}


def _endpoint(values: dict[str, str | None]) -> str:
    if values.get("api_endpoint"):
        return str(values["api_endpoint"])
    return str(values.get("api_base", "")).rstrip("/") + "/chat/completions"


def _test_model(values: dict[str, str | int | None]) -> bool:
    endpoint = str(values.get("api_endpoint") or "")
    base = str(values.get("api_base") or "")
    timeout = int(values.get("request_timeout") or 180)
    print("")
    print("Testing model with prompt: hola")
    print(f"Endpoint: {endpoint or base.rstrip('/') + '/chat/completions'}")
    print(f"Timeout: {timeout}s")
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
        print("Test failed.")
        print(f"Reason: {exc}")
        print("El modelo, la URL o la API key parecen incorrectos, o el servidor local no esta respondiendo.")
        return False
    print("Test response:")
    print(response.text.strip())
    return True


def _get_google_models(api_key: str) -> list[str]:
    print("Fetching available Google models (v1beta)...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                name = m.get("name", "").replace("models/", "")
                # Filtrar solo los que soportan generación de contenido
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    models.append(name)
            return sorted(models)
    except Exception as e:
        print(f"Failed to fetch models: {e}")
        return []


def _print_context(root: Path) -> None:
    config = load_config(root)
    skills = load_skills(config.builtin_skills_dir, config.skills_dir)
    print("")
    print("Final context")
    print("=============")
    print(f"Home: {config.root}")
    print(f"Config: {config.root / 'delux.config.json'}")
    print(f"Memory: {config.memory_file}")
    print(f"Skills: {config.skills_dir}")
    print(f"Docs: {config.docs_dir}")
    print(f"Provider: {config.provider}")
    print(f"Model: {config.model}")
    print(f"Endpoint: {config.api_endpoint or config.api_base.rstrip('/') + '/chat/completions'}")
    print(f"Timeout: {config.request_timeout}s")
    print("")
    print("Skills loaded:")
    if skills:
        for skill in skills:
            print(f"- {skill.name}: {skill.summary}")
    else:
        print("- none")
    print("")
    print("Memory preview:")
    print(load_memory(config.memory_file)[:800].strip())
    print("")
    print("Docs loaded:")
    docs = load_docs(config.docs_dir)
    print(docs[:800].strip() if docs else "No docs loaded.")


def run_setup(root: Path) -> int:
    selected_root = root
    print(f"Default Delux home: {root}")
    if not _yes_no("Use this home path", True):
        selected_root = Path(_ask("Delux home path", str(root))).expanduser().resolve()
    root = selected_root
    ensure_workspace(root)
    
    # ── Try to load existing config for defaults ─────────────────────────────
    existing_config = None
    try:
        existing_config = load_config(root)
        print(f"Detected existing configuration for model: {existing_config.model}")
    except:
        pass

    print(f"Delux setup at {root}")
    _print_provider_menu()
    
    # Suggest existing provider if available
    default_provider_choice = "1"
    if existing_config:
        for i, p in enumerate(PRESETS, 1):
            if p.key == existing_config.provider:
                default_provider_choice = str(i)
                break
    
    choice = _ask("Choose provider", default_provider_choice)

    values: dict[str, str | None] = {}
    try:
        choice_num = int(choice)
    except ValueError:
        choice_num = 0

    if 1 <= choice_num <= len(PRESETS):
        preset = PRESETS[choice_num - 1]
        if preset.note:
            print(preset.note)
            
        default_base = existing_config.api_base if existing_config and existing_config.provider == preset.key else preset.api_base
        default_model = existing_config.model if existing_config and existing_config.provider == preset.key else preset.default_model
        default_key = existing_config.api_key if existing_config else ""
        default_timeout = existing_config.request_timeout if existing_config else 180

        if preset.key == "google":
            api_key = _ask("Google API key", default_key, secret=True)
            available_models = _get_google_models(api_key)
            if available_models:
                print("\nAvailable models:")
                for i, m in enumerate(available_models, 1):
                    print(f"  {i}. {m}")
                m_choice = _ask_int("Choose model", 1)
                model = available_models[m_choice - 1] if 1 <= m_choice <= len(available_models) else available_models[0]
            else:
                model = _ask("Model", default_model)
            api_base = "google"
        else:
            api_base = _ask("API base URL", default_base)
            model = _ask("Model", default_model)
            api_key = _ask("API key", default_key, secret=True) if preset.needs_key else _ask("API key optional", default_key, secret=True)
            
        timeout = _ask_int("Request timeout seconds", default_timeout)
        values = {
            "provider": preset.key,
            "api_base": api_base.rstrip("/"),
            "api_endpoint": None,
            "api_key": api_key or None,
            "model": model,
            "request_timeout": timeout,
        }
    elif choice_num == len(PRESETS) + 1:
        api_type = _ask("API type", "openai")
        base = _ask("Base URL without endpoint", "https://api.example.com")
        api_base = _ensure_v1(base) if api_type.lower() in {"openai", "openai-compatible", "openai compatible"} else base.rstrip("/")
        model = _ask("Model", "custom-model")
        api_key = _ask("API key", "", secret=True)
        timeout = _ask_int("Request timeout seconds", 180)
        values = {
            "provider": "custom",
            "api_type": api_type,
            "api_base": api_base,
            "api_endpoint": None,
            "api_key": api_key or None,
            "model": model,
            "request_timeout": timeout,
        }
    elif choice_num == len(PRESETS) + 2:
        endpoint = _ask("Full endpoint URL", "https://api.example.com/v1/chat/completions")
        model = _ask("Model", "custom-model")
        api_key = _ask("API key", "", secret=True)
        timeout = _ask_int("Request timeout seconds", 180)
        values = {
            "provider": "full_custom",
            "api_base": "",
            "api_endpoint": endpoint,
            "api_key": api_key or None,
            "model": model,
            "request_timeout": timeout,
        }
    else:
        print("Invalid provider choice.")
        return 2

    path = write_config(root, values)
    print(f"Wrote {path}")
    print(f"Resolved endpoint: {_endpoint(values)}")
    if _yes_no("Test this model now with prompt `hola`", True):
        _test_model(values)

    # MCP server setup
    print("")
    print("MCP Servers (optional)")
    print("=====================")
    print("MCP servers provide external tools like file system access, GitHub, databases, etc.")
    if _yes_no("Configure MCP servers now", False):
        _setup_mcp_servers(root)

    # Contextualizer (Dynamic Intelligence) setup
    print("")
    print("Dynamic Intelligence (Training Dataset)")
    print("======================================")
    print("Provides hundreds of examples for prefix caching and improved reasoning.")
    if _yes_no("Configure Dynamic Intelligence (Training Dataset) now", True):
        _setup_contextualizer(root)

    _print_context(root)
    print("")
    print("Setup complete. Run: delux \"di hola y ejecuta pwd\"")
    return 0


MCP_PRESETS = [
    ("filesystem", "File System", "npx", ["-y", "@modelcontextprotocol/server-filesystem"]),
    ("github", "GitHub", "npx", ["-y", "@modelcontextprotocol/server-github"]),
    ("sqlite", "SQLite", "uvx", ["mcp-server-sqlite"]),
    ("fetch", "Web Fetch", "uvx", ["mcp-server-fetch"]),
]


def _setup_mcp_servers(root: Path) -> None:
    from .mcp_store import add_mcp_server, MCPServerEntry

    print("")
    print("Available MCP servers:")
    for i, (key, label, cmd, args) in enumerate(MCP_PRESETS, 1):
        print(f"  {i}. {label} ({key})")
    print(f"  {len(MCP_PRESETS) + 1}. Custom")

    choice = _ask("Add MCP server (number, or 0 to skip)", "0")
    try:
        choice_num = int(choice)
    except ValueError:
        return

    while 1 <= choice_num <= len(MCP_PRESETS):
        key, label, cmd, args = MCP_PRESETS[choice_num - 1]
        print(f"\n{label} MCP Server")
        print("-" * 30)

        extra_args = _ask("Extra arguments (space-separated)", "")
        full_args = args + (extra_args.split() if extra_args else [])

        if key == "filesystem":
            default_path = str(Path.home())
            path = _ask("Root directory to allow access", default_path)
            if path:
                full_args.append(path)

        entry = MCPServerEntry(name=key, command=cmd, args=full_args, description=label)
        add_mcp_server(root, entry)
        print(f"  {GREEN}Added: {key}{RESET}")

        choice = _ask("Add another MCP server (number, or 0 to skip)", "0")
        try:
            choice_num = int(choice)
        except ValueError:
            return

    if choice_num == len(MCP_PRESETS) + 1:
        name = _ask("Server name", "myserver")
        command = _ask("Command", "npx")
        args_str = _ask("Arguments (space-separated)", "")
        args = args_str.split() if args_str else []
        desc = _ask("Description", "")
        entry = MCPServerEntry(name=name, command=command, args=args, description=desc)
        add_mcp_server(root, entry)
        print(f"  {GREEN}Added: {name}{RESET}")


def _setup_contextualizer(root: Path) -> None:
    print("\nDynamic Intelligence Setup")
    print("-" * 30)
    
    cfg = load_ctx_config(root)
    cfg.enabled = _yes_no("Enable Contextualizer", True)
    
    if cfg.enabled:
        print("\nSelect Training Dataset Size (examples for prefix caching):")
        print("  1. 50 examples  (Lightweight)")
        print("  2. 100 examples (Balanced)")
        print("  3. 300 examples (Expert - Recommended for GPU)")
        print("  4. 500 examples (Ultra)")
        print("  5. 1000 examples (Maximum - Needs 32k context)")
        
        size_choice = _ask("Choose size", "3")
        size_map = {"1": 50, "2": 100, "3": 300, "4": 500, "5": 1000}
        cfg.dataset_size = size_map.get(size_choice, 300)
        
        # Generate the dataset file
        _generate_training_dataset(root, cfg.dataset_size)
        print(f"  {GREEN}Generated dataset with {cfg.dataset_size} examples.{RESET}")

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
        
        # ── REAL CASES ──
        if real_cases:
            f.write('## REAL WORLD CASES\n')
            for i, case in enumerate(real_cases):
                user_msg = next((m['content'] for m in case['messages'] if m['role'] == 'user'), "Hello")
                assistant_actions = [m['content'] for m in case['messages'] if m['role'] == 'assistant']
                f.write(f'### Real Case {i+1}\nUSER: \"{user_msg}\"\n')
                for action in assistant_actions:
                    f.write(f'ACTION: {action}\n')
                f.write('\n')

    # ── EXPERT LIBRARY CHECK/GENERATION ──
    library_path = root / "training" / "expert_library.json"
    
    if not library_path.exists():
        print(f"  {GREEN}First time setup: Loading expert knowledge from built-in assets...{RESET}")
        # Intentamos copiar desde los activos del paquete
        assets_path = Path(__file__).parent / "assets" / "training_library.json"
        if assets_path.exists():
            import shutil
            library_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(assets_path, library_path)
        else:
            # Fallback si no hay activos (generación manual como antes)
            _build_base_library(library_path)
        
    expert_cases = []
    try:
        with open(library_path, 'r', encoding='utf-8') as lib_f:
            expert_cases = json.load(lib_f)
    except:
        pass

        needed = size - len(real_cases)
        # Tomamos los primeros N de la librería para consistencia
        selected_experts = expert_cases[:needed]
        
        for i, case in enumerate(selected_experts):
            idx = len(real_cases) + i + 1
            f.write(f'### Expert Case {idx}\nUSER: \"{case["user"]}\"\nACTION: {case["assistant"]}\n\n')


def _build_base_library(target_path: Path) -> None:
    import random
    scenarios = [
        {'q': 'Scan subnet {subnet} for open SSH ports.', 'a': '<action>shell</action>\n<command>nmap -p 22 {subnet}</command>\n<timeout>60</timeout>'},
        {'q': 'Fix permissions in {dir} for .env files.', 'a': '<action>shell</action>\n<command>find {dir} -name ".env" -exec chmod 600 {} \;</command>\n<timeout>30</timeout>'},
        {'q': 'Check Docker containers with status "exited".', 'a': '<action>shell</action>\n<command>docker ps -a -f status=exited</command>\n<timeout>30</timeout>'},
        {'q': 'Search for {error} in system logs today.', 'a': '<action>shell</action>\n<command>journalctl --since today | grep -i {error}</command>\n<timeout>30</timeout>'},
        {'q': 'Create backup of {dir} excluding node_modules.', 'a': '<action>shell</action>\n<command>tar --exclude="node_modules" -czf backup.tar.gz {dir}</command>\n<timeout>120</timeout>'},
        {'q': 'Send Telegram alert: Service {service} is down.', 'a': '<action>run_skill</action>\n<skill>telegram-notify</skill>\n<args>CRITICAL: {service} is DOWN</args>\n<timeout>30</timeout>'},
        {'q': 'Analyze {file} for undocumented functions.', 'a': '<action>run_skill</action>\n<skill>writer-pro</skill>\n<args>--path {file} --analyze docs</args>\n<timeout>60</timeout>'},
    ]
    
    subnets = ['192.168.1.0/24', '10.0.0.0/8', '172.16.0.0/12']
    dirs = ['/var/www', '/opt/app', '/etc/nginx']
    errors = ['Panic', 'Segfault', 'Timeout']
    services = ['nginx', 'postgresql', 'ssh']
    files = ['main.py', 'app.js', 'utils.go']
    
    library = []
    for i in range(1000):
        s = random.choice(scenarios)
        q, a = s['q'], s['a']
        params = {'{subnet}': random.choice(subnets), '{dir}': random.choice(dirs), '{error}': random.choice(errors), '{service}': random.choice(services), '{file}': random.choice(files)}
        for k, v in params.items():
            q, a = q.replace(k, v), a.replace(k, v)
        library.append({'user': q, 'assistant': a})
        
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(library, f, indent=2, ensure_ascii=False)
