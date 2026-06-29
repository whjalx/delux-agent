# SKILL TEMPLATE — How to Create a Skill for Delux

Each skill lives in its own directory inside `skills/<skill-name>/`.
Every skill has **3 required parts**:

## 1. `SKILL.md` — Documentation (required)

Markdown file describing what the skill does, when to use it, and how it responds.

Exact structure required:

```markdown
# skill:<skill-name>
## Summary
One line describing what this skill does.

## When To Use
- Use case 1
- Use case 2

## Usage
<name> <arguments>

## Steps
1. Step 1
2. Step 2

## Response Examples (REQUIRED)

### Agent invokes the skill
```json
{"action":"run_skill","skill":"<name>","args":"<arguments>","timeout":30}
\```

### Skill returns result
```json
{
  "field": "value",
  "status": "ok"
}
\```

### Prompt injection example
\```
--- <name> example ---
USER: "<example user input>"
AGENT: {"action":"run_skill","skill":"<name>","args":"<args>","timeout":30}
RESULT: {"field": "value", "status": "ok"}
NEXT ACTION: {"action":"shell/final/read_file","..."}
\```
```

## Caveats
- Important warnings
```

## 2. `exec.py` (or `exec.bash`, `exec.go`, etc.) — Executable script (recommended)

Script that executes the skill logic. Receives command-line arguments and returns JSON via stdout.

Minimal structure:

```python
import sys, json

def my_skill(args: list[str]) -> dict:
    # Logic here
    return {"status": "ok", "result": "done"}

if __name__ == "__main__":
    args = sys.argv[1:]
    print(json.dumps(my_skill(args)))
```

## 3. Response JSON (required for all skills even without exec)

Every skill MUST document in `SKILL.md`:
- **Input JSON**: what the agent sends to invoke it (`{"action":"run_skill","skill":"...","args":"..."}`)
- **Output JSON**: what the skill returns when executed
- **Prompt injection example**: the full flow USER → AGENT → RESULT → NEXT ACTION

This allows even small models to learn the exact format by reading the file.

## Automatic Creation Rule

When the agent needs to create a new skill:
1. Read this file (SKILL_TEMPLATE) to understand the format
2. Read an existing skill in SKILLS as a reference example
3. Use `create_skill` to create the directory and SKILL.md automatically
4. If applicable, use `write_file` to create `exec.py` with the logic
5. Save the skill to memory with `remember`
