# Delux Agent

Shell-first AI assistant. Autonomous terminal agent with skills, memory, MCP support, and an interactive TUI.

- **Zero third-party dependencies** — Python standard library only (TUI requires `textual`, RAG dataset requires `git-lfs`)
- **Multi-shell** — fish, bash, zsh support
- **Multi-platform** — Linux, macOS, Windows (WSL/PowerShell)
- **MCP support** — Connect to external tool servers
- **Bilingual** — English & Spanish
- **KV Cache optimization** — Stable prefix ordering for prompt caching (Ollama, llama.cpp, DeepSeek, OpenAI)
- **Small model support** — Auto-detected guidance + optional KV cache warmup

## Quick Install

### Linux / macOS / WSL

```bash
curl -fsSL https://raw.githubusercontent.com/anomalyco/delux-agent/main/install.sh | bash
```

Or if you cloned the repo:

```bash
cd delux-agent
bash install.sh
```

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/anomalyco/delux-agent/main/install.ps1 | iex"
```

### Manual (any platform)

Requires **Python 3.11+**. For the RAG trajectory dataset, **git-lfs** is required (auto-installed by the setup wizard).

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows

# Install with TUI support
pip install -e .
pip install textual           # Required for the interactive TUI
```

## Setup

```bash
delux setup
```

The wizard guides you through:
- Selecting an AI provider (OpenAI, OpenRouter, Groq, LM Studio, Ollama, DeepSeek, Google Gemini, custom)
- Configuring your API key or local endpoint
- Testing the connection
- Detecting small models (3B/4B/Phi/Gemma) and enabling optimizations
- Configuring optional contextualizer and training
- Installing pre-built trajectory dataset (auto-installs `git-lfs` if needed)

### Supported Providers

| Provider | Type | API Key |
|----------|------|---------|
| OpenAI | Cloud | Required |
| OpenRouter | Cloud (multi-model) | Required |
| DeepSeek | Cloud (reasoning + caching) | Required |
| Groq | Cloud (fast) | Required |
| Google Gemini | Cloud (native) | Required |
| LM Studio | Local | Optional |
| Ollama | Local | None |
| Custom | Any OpenAI-compatible URL | Optional |

### Environment Variables

Override config file values:

```bash
export DELUX_API_KEY="your-key"
export DELUX_MODEL="gpt-4.1-mini"
export DELUX_API_BASE="https://api.example.com/v1"
export DELUX_API_ENDPOINT="https://api.example.com/v1/chat/completions"
export DELUX_HOME="$HOME/.delux"
export DELUX_SHELL="fish"
export DELUX_TIMEOUT="180"
export DELUX_LANG="en"
export DELUX_CACHE_CHUNK_SIZE="512"   # KV cache warmup chunk size (0=off)
```

## Usage

### Interactive TUI (default)

```bash
delux
```

Opens a Textual-based terminal UI with:
- Real-time chat log
- Sidebar with model info, tokens, steps, modes
- Plan mode (Ctrl+Space / /plan)
- KV cache warmup for local models
- Small model tips

### One-shot Prompt

```bash
delux "analyze this codebase"
delux --cwd ~/project "find all TODO comments"
```

### CLI Options

```
delux [prompt]

Options:
  --cwd DIR       Working directory for shell commands
  --home DIR      DELUX_HOME workspace (default: ~/.delux)
  --max-steps N   Maximum autonomous actions (default: 12)
  --quiet         Only print the final answer
  --init          Create workspace directories
  --context       Print loaded memory, skills, and docs
  --new-skill N   Create a blank skill
  --summary TEXT  Summary for --new-skill
```

## TUI Shortcuts & Commands

| Key | Action |
|-----|--------|
| **Ctrl+Space** | Toggle Plan/Build mode |
| **Ctrl+C** | Cancel current execution |
| **Ctrl+L** | Clear screen |
| **Ctrl+Q** | Quit |

| Command | Description |
|---------|-------------|
| `/help` | Full command list |
| `/plan [on\|off]` | Toggle plan mode (creates step-by-step plan before execution) |
| `/status` | Current configuration (model, provider, cache settings) |
| `/model` | List/switch models |
| `/model add <name> <provider> <api_base>` | Add model |
| `/lang <en\|es>` | Change language |
| `/pwd` | Print working directory |
| `/cd <dir>` | Change working directory |
| `/clear` | Clear screen |
| `/quit` | Exit |

## Plan Mode

Toggle with `Ctrl+Space` or `/plan`. When active:
1. The planner LLM creates a step-by-step plan from your prompt
2. Steps are displayed with progress (e.g., `📋 [2/5] Step 1: Run: ls -la src/`)
3. The agent executes each step autonomously
4. Steps can be skipped, completed, or failed — tracked in real-time
5. The agent cannot `final` until all steps are done/skipped
6. When complete, a summary shows each step's status

You can configure a separate model for planning (`plan_model` in config or `DELUX_PLAN_MODEL` env var).

## KV Cache Optimization

Delux structures messages so the **prefix (system prompt + base context) is byte-identical between turns**. This enables:
- **Local models (Ollama/llama.cpp)**: KV cache reuse for the stable prefix
- **API models (DeepSeek, OpenAI)**: Prompt caching on the server side

For local models, optional cache warmup pre-processes the system prompt on first turn:
```json
// delux.config.json
"cache_chunk_size": 512   // 300-1000 tokens per chunk, 0=off
```
Or via env: `DELUX_CACHE_CHUNK_SIZE=512 delux`

Tips for local inference:
- **Ollama**: `OLLAMA_KEEP_ALIVE=24h` keeps model in RAM
- **llama.cpp**: `--cache-type-k q8_0 --cache-type-v q8_0` for quantized KV cache

## Small Model Support

When `small_model: true` is set (or auto-detected for models with `3b`, `1b`, `2b`, `4b`, `phi-3`, etc.):
- Shorter docs/memory limits (200/100 lines vs 3000/1500)
- Concise system prompt hints for focused responses
- Optional KV cache warmup (if `cache_chunk_size > 0`)

Setup wizard auto-detects small models and asks for confirmation.

## Delux Gateway (Telegram)

Run Delux from your phone via Telegram:

```bash
# 1. Create a bot via @BotFather, then configure:
echo '{"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}' > ~/.delux/telegram.json

# 2. Start the gateway
delux-gateway
```

Supports `/start`, `/status`, `/cancel`, `/retry`, `/stats` commands, session history, and long-running tasks with typing indicators.

## Workspace Structure

```
~/.delux/
├── delux.config.json    # Configuration
├── templates.json       # Per-model parse templates
├── mcp_servers.json     # MCP server definitions
├── mcp_tools.json       # Cached MCP tool schemas
├── memory/
│   └── memory.md        # Persistent memory
├── skills/              # Skill definitions
│   ├── skill-name/
│   │   ├── SKILL.md
│   │   └── exec.py      # Optional executable
│   └── README.md
├── docs/                # Reference documentation
│   └── *.md
├── training/            # Few-shot examples & contextualizer
└── sessions/            # Saved session logs
```

## Delux Skills

| Skill | Purpose |
|-------|---------|
| `delux-reasoning` | Structured chain-of-thought problem decomposition |
| `delux-codex` | Expert code analysis, generation, and refactoring |
| `delux-oracle` | Knowledge retrieval and cross-reference synthesis |
| `delux-judge` | Self-validation — reviews actions before finalizing |
| `delux-browser` | Playwright browser automation |
| `delux-gateway` | Bidirectional Telegram bridge |
| `delux-telegram-notify` | One-way Telegram notifications |
| `delux-writer-pro` | Long-form document writing and editing |
| `delux-rag` | Project RAG indexing and search |
| `delux-obsidian-brain` | Technical knowledge persistence |

Skills are self-documenting procedures. Create one with:

```bash
delux --new-skill "change wallpaper" --summary "Modify desktop wallpaper."
```

### Executable Skills

Skills can have executable scripts (`exec.py`, `exec.bash`, etc.) that Delux runs directly.

## MCP Servers

Connect to [Model Context Protocol](https://modelcontextprotocol.io/) servers:

```bash
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /home/user
/mcp add github npx -y @modelcontextprotocol/server-github
/mcp discover
/mcp tools
```

The agent can use MCP tools:
```json
{"action":"call_mcp","server":"filesystem","tool":"read_file","arguments":{"path":"/etc/hostname"}}
```

## Safety

- Never uses `sudo`, `su`, `doas`, `pkexec`, or privilege escalation
- Shell commands run with your normal user permissions
- Workspace isolated to `DELUX_HOME`
- Commands run from the selected `--cwd`

## Shell Completions

Auto-installed by `install.sh`. Manual install:

```bash
# Fish
cp completions/delux.fish ~/.config/fish/completions/

# Bash
sudo cp completions/delux.bash /usr/share/bash-completion/completions/delux

# Zsh
mkdir -p ~/.zsh/completion
cp completions/_delux ~/.zsh/completion/
# Add to ~/.zshrc: fpath=(~/.zsh/completion $fpath)
```
