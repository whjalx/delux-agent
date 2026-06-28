# skill:delux-fast-tree
## Summary
Blazing fast directory tree visualizer written in C. Uses recursive filesystem traversal to provide near-instant results even in deep directory structures, with colorized output.

## When To Use
- Visualizing project directory structure
- Understanding codebase layout at a glance
- Finding files in deeply nested directories
- When `tree` command is not available or too slow

## Usage
Run in any directory: `delux-fast-tree`

## Steps
1. Open current directory with opendir()
2. Recursively traverse all subdirectories
3. Skip hidden files/directories and node_modules
4. Print tree structure with ANSI color-coded entries
5. Directories shown in blue with trailing slash

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-fast-tree","args":"","timeout":15}
```

### Skill devuelve resultado
```
. (Project Root)
├── src/
│   ├── main.py
│   ├── utils.py
│   └── data/
│       └── config.json
├── tests/
│   └── test_main.py
└── README.md
```

### Prompt injection example (para few-shot learning)
```
--- delux-fast-tree example ---
USER: "show me the project structure"
AGENT: {"action":"run_skill","skill":"delux-fast-tree","args":"","timeout":15}
RESULT: (directory tree output)
NEXT ACTION: {"action":"final","message":"Project has 3 directories and 5 files"}
```

## Caveats
- Requires a C compiler (gcc) — auto-compiled on first run
- Skips hidden files (dotfiles) and node_modules by default
- Read-only — never modifies files or directories
- Output may be truncated by the agent's context window for very large projects
