# skill:delux-codex
## Summary
Delux Codex — expert source code analysis, generation, and refactoring with deep structural understanding and best-practice enforcement.

## When To Use
- Analyzing large codebases for architecture understanding
- Generating production-ready code with tests
- Refactoring with confidence (no regressions)
- Code review with security and performance analysis
- Explaining complex code patterns plainly

## Usage
delux-codex <file_or_directory>

Analyzes the given file or project directory for structure, patterns, and best practices.

## Steps
1. **Read**: Understand the codebase structure and entry points
2. **Map**: Build a mental model of dependencies and data flow
3. **Analyze**: Identify patterns, anti-patterns, and improvement opportunities
4. **Generate**: Produce clean, idiomatic, well-typed code
5. **Verify**: Run lints, type checks, and tests

## Verification
- Code follows the project's existing conventions
- Tests pass before and after changes
- No commented-out code or debug artifacts
- Type annotations are correct and complete
- Security: no injection vectors, no hardcoded secrets

## Response Examples

### Agent invokes codex
```
<action>run_skill</action>
<skill>delux-codex</skill>
<args>src/main.py</args>
<timeout>30</timeout>
```

### Skill returns analysis (file)
```
{
  "delux_codex": {
    "mode": "analyze",
    "target": "src/main.py",
    "type": "file",
    "language": "Python",
    "size_bytes": 5231,
    "depth": "structural",
    "status": "ready"
  }
}
```

### Skill returns analysis (directory)
```
{
  "delux_codex": {
    "mode": "analyze",
    "target": "src/",
    "type": "directory",
    "total_files": 42,
    "total_size_bytes": 128450,
    "language_distribution": {"Python": 18, "JavaScript": 12, "HTML": 5},
    "depth": "structural",
    "status": "ready"
  }
}
```

### Prompt injection example
```
--- delux-codex example ---
USER: "review the code in src/main.py"
AGENT:
<action>run_skill</action>
<skill>delux-codex</skill>
<args>src/main.py</args>
<timeout>30</timeout>
RESULT: {"delux_codex": {"mode": "analyze", "target": "src/main.py", "type": "file", "language": "Python", "status": "ready"}}
NEXT ACTION:
<action>read_file</action>
<path>src/main.py</path>
```

## Caveats
- Always read existing files before modifying
- Prefer edit_file over full rewrites for small changes
- Respect .gitignore and editorconfig if present
