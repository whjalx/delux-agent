# Skills

Delux skills are modular extensions that provide reusable capabilities to the agent.

## Structure

Each skill lives in its own directory:

```text
skills/<skill-name>/
├── SKILL.md       # Documentation (required)
└── exec.{py,bash,c}  # Executable script (recommended)
```

## Skill Documentation

Every SKILL.md must include:

- **Summary**: One-line description
- **When To Use**: Bulleted list of use cases
- **Usage**: Command-line syntax
- **Steps**: Numbered execution steps
- **Response Examples**: JSON invocation, JSON result, and prompt injection example
- **Caveats**: Important warnings and limitations

See [SKILL_TEMPLATE.md](SKILL_TEMPLATE.md) for the full required format.

## Available Skills

| Skill | Description | Exec |
|---|---|---|
| delux-browser | Browser automation via Playwright | Python |
| delux-code-stats | Codebase line/file statistics by language | Python |
| delux-codex | Source code analysis, generation, and refactoring | Python |
| delux-dataset-rag | Searchable library of real agent trajectories | Python |
| delux-disk-benchmark | Disk write/read performance benchmark | C |
| delux-fast-tree | Blazing fast directory tree visualizer | C |
| delux-gateway | Bidirectional Telegram bridge for remote management | Python |
| delux-git-summary | Visual git repository status dashboard | Bash |
| delux-judge | Self-validation and critique of agent actions | Python |
| delux-net-check | Network diagnostics (ping, DNS, public IP) | Python |
| delux-obsidian-brain | Knowledge base manager (Markdown + WikiLinks) | Python |
| delux-opencode | OpenCode integration for complex software tasks | Python |
| delux-oracle | Knowledge retrieval and synthesis across sources | Python |
| delux-quick-search | Web search via DuckDuckGo (ddgr) | Python |
| delux-rag | Native BM25 RAG engine for local file indexing | Python |
| delux-reasoning | Structured problem decomposition with confidence scoring | Python |
| delux-search-expert | Advanced multi-file search with ripgrep | Bash |
| delux-sys-health | System health overview (CPU, memory, disk, network) | Python |
| delux-telegram-notify | Send notifications to Telegram | Python |
| delux-writer-pro | Robust file writer with directory creation and verification | Python |

## Creating a New Skill

1. Copy the structure from [SKILL_TEMPLATE.md](SKILL_TEMPLATE.md)
2. Follow the conventions of existing skills for consistency
3. Ensure Response Examples include all three parts (invocation, result, prompt injection)
