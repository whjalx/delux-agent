# skill:delux-opencode
## Summary
Native OpenCode integration. Delegates complex software engineering tasks to OpenCode — a CLI AI agent specialized in code analysis, refactoring, and multi-file edits.

## When To Use
- Complex multi-file refactoring across a project
- Tasks that need deep codebase understanding (OpenCode excels at this)
- Running OpenCode as a sub-agent for specialized work
- Code review, bug fixing, and feature implementation across many files
- When a task is too large or complex for Delux's step budget

## Usage
delux-opencode <prompt>

Runs OpenCode with the given prompt in the current working directory.

## Steps
1. Formulate a clear, specific prompt for OpenCode
2. Call opencode run with the prompt, capturing output
3. Return structured results: what was done, files changed, any errors

## Verification
- OpenCode must be installed (`which opencode`)
- Results show files changed and their status
- Long-running tasks have a timeout safeguard

## Response Examples

### Delegate a refactoring task to OpenCode
```json
{"action":"run_skill","skill":"delux-opencode","args":"refactor src/utils.py to use async/await pattern","timeout":300}
```

### Skill returns result
```json
{
  "status": "ok",
  "returncode": 0,
  "output": "Refactored src/utils.py to use async/await. Updated 3 functions, added async def wrappers.",
  "errors": ""
}
```

### OpenCode fails
```json
{
  "status": "error",
  "returncode": 1,
  "output": "",
  "errors": "Error: model not configured. Run 'opencode auth' first."
}
```

### Prompt injection example
```
--- delux-opencode example ---
USER: "refactor the utils module to be async"
AGENT: {"action":"run_skill","skill":"delux-opencode","args":"refactor src/utils.py to async/await","timeout":300}
RESULT: {"status":"ok","returncode":0,"output":"Refactored src/utils.py to use async/await..."}
NEXT ACTION: {"action":"shell","command":"python3 -m pytest src/test_utils.py","timeout":60}
```

## Caveats
- Requires OpenCode installed and configured (model, API key)
- OpenCode has its own step budget and may fail on very complex tasks
- OpenCode output is captured as text — may be verbose
- Runs in the current working directory
- Timeout: 5 minutes by default
