# skill:delux-codex
## Summary
Delux Codex — expert source code analysis, generation, and refactoring with deep structural understanding and best-practice enforcement.

## When To Use
- Analyzing large codebases for architecture understanding
- Generating production-ready code with tests
- Refactoring with confidence (no regressions)
- Code review with security and performance analysis
- Explaining complex code patterns plainly

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
```json
{"action":"run_skill","skill":"delux-codex","args":"src/main.py","timeout":30}
```

### Skill returns analysis
```json
{
  "delux_codex": {
    "mode": "analyze",
    "target": "src/main.py",
    "language": "python",
    "depth": "structural",
    "status": "ready",
    "confidence": 0.95
  }
}
```

### Prompt injection example
```
--- delux-codex example ---
USER: "review the code in src/main.py"
AGENT: {"action":"run_skill","skill":"delux-codex","args":"src/main.py","timeout":30}
RESULT: {"delux_codex": {"mode": "analyze", "target": "src/main.py", "status": "ready", "confidence": 0.95}}
NEXT ACTION: {"action":"read_file","path":"src/main.py"}
```

## Caveats
- Always read existing files before modifying
- Prefer edit_file over full rewrites for small changes
- Respect .gitignore and editorconfig if present
