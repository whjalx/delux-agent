# Delux Agent

Shell-first AI assistant. Autonomous terminal agent with skills, memory, MCP support, and an interactive IDE.

- **Zero third-party dependencies** — Python standard library only
- **Multi-shell** — fish, bash, zsh support
- **Multi-platform** — Linux, macOS, Windows (WSL/PowerShell)
- **MCP support** — Connect to external tool servers
- **Bilingual** — English & Spanish

## Delux Gateway (Telegram)

Run Delux from your phone via Telegram — full bidirectional bridge:

```bash
# 1. Create a bot via @BotFather, then configure:
echo '{"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}' > ~/.delux/telegram.json

# 2. Start the gateway
delux-gateway

# Or run as a skill
@delux-gateway start
```

The gateway forwards Telegram messages to the Delux agent, streams step-by-step results back, and delivers the final answer. Supports `/start`, `/status`, `/cancel` commands and long-running tasks.

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

Requires **Python 3.11+**.

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows

# Install
pip install -e .

# Or from PyPI (when published)
# pip install delux-agent
```

## Setup

After installation:

```bash
delux setup
```

This wizard guides you through:
- Selecting an AI provider (OpenAI, OpenRouter, Groq, LM Studio, Ollama, custom)
- Configuring your API key or local endpoint
- Testing the connection with a live prompt

### Supported Providers

| Provider | Type | API Key |
|----------|------|---------|
| OpenAI | Cloud | Required |
| OpenRouter | Cloud (multi-model) | Required |
| DeepSeek | Cloud (reasoning) | Required |
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
```

## Usage

### Interactive IDE

```bash
delux             # Open IDE (default)
delux ide         # Same
```

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

### Subcommands

```bash
delux setup       # Configure providers and models
delux ide         # Open interactive IDE
```

## IDE Shortcuts

| Key | Action |
|-----|--------|
| **Tab** | Toggle planning mode |
| **Esc** | Quit |
| **Ctrl+C** | Cancel input |
| **Ctrl+L** | Clear screen |
| **/?** | Show shortcuts |
| **/m** | MCP servers menu |

### IDE Commands

| Command | Description |
|---------|-------------|
| `/help` | Full command list |
| `/status` | Current configuration |
| `/context` | View loaded context |
| `/model` | List/switch models |
| `/model add <name> <provider> <api_base>` | Add model |
| `/mcp` | List MCP servers |
| `/mcp add <name> <cmd> [args]` | Add MCP server |
| `/mcp discover` | Discover MCP tools |
| `/template` | Manage response templates |
| `/p` | Toggle planning |
| `/v` | Toggle validation |
| `/e` | Toggle ephemeral mode |
| `/a` | Toggle ask mode |
| `/lang <en\|es>` | Change language |
| `/quit` | Exit |

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
└── sessions/            # Saved session logs
    └── YYYYMMDD-HHMMSS-title.md
```

## Delux Skills

| Skill | Purpose |
|-------|---------|
| `delux-reasoning` | Structured chain-of-thought problem decomposition |
| `delux-codex` | Expert code analysis, generation, and refactoring |
| `delux-oracle` | Knowledge retrieval and cross-reference synthesis |
| `delux-judge` | Self-validation — reviews actions before finalizing |
| `delux-browser` | Playwright browser automation (screenshot, scrape, click, fill) |
| `delux-opencode` | Native OpenCode delegation for complex engineering tasks |
| `delux-gateway` | Bidirectional Telegram bridge for remote operation |

## Skills

Skills are self-documenting procedures. Create one:

```bash
delux --new-skill "change wallpaper" --summary "Modify desktop wallpaper."
```

Delux creates skills automatically when it learns a reusable procedure.

### Executable Skills

Skills can have executable scripts (`exec.bash`, `exec.py`, `exec.go`, etc.) that Delux runs directly.

## MCP Servers

Connect to [Model Context Protocol](https://modelcontextprotocol.io/) servers for external tools:

```bash
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /home/user
/mcp add github npx -y @modelcontextprotocol/server-github
/mcp discover
/mcp tools
```

The agent can use MCP tools via:
```json
{"action":"call_mcp","server":"filesystem","tool":"read_file","arguments":{"path":"/etc/hostname"}}
```

## Response Templates

Different models respond in different formats. Templates auto-detect and learn the best parse strategy:

```bash
/template                     # List configured templates
/template <model> auto        # Auto-detect (default)
/template <model> direct_json # Force direct JSON parse
/template <model> suffix "..." # Add custom system prompt suffix
/template <model> reset       # Reset to auto
```

Strategies: `direct_json`, `markdown_json`, `regex_json`, `no_action_wrap`, `plain_text`

## Safety

- Never uses `sudo`, `su`, `doas`, `pkexec`, or privilege escalation
- Shell commands run with your normal user permissions
- File operations limited to `DELUX_HOME`
- Commands run from the selected `--cwd`

## Shell Completions

Install completions manually (auto-installed by `install.sh`):

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
